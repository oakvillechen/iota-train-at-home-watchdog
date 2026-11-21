#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IOTA Cluster Status Reporter (方案 A: 端到端 AES-256 加密同步)
将本机 Watchdog 采集到的节点状态通过 AES-256 加密后，上传至 GitHub 仓库 telemetry 分支的 data/node-{hash}.json
完全隐藏真实 Miner ID、IP、收益和机器名称，仅持有密码的 Dashboard 网页可解密查看。

telemetry 分支只保留一个无父提交的快照：每次上报都基于当前快照生成新的孤立提交并强制更新分支，
旧提交不再被引用，因此不会像以前那样在 main 上无限累积遥测提交历史。
"""

import base64
import ctypes
import hashlib
import hmac
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request

try:
    import net_ssl
    net_ssl.install_default()
except Exception:
    pass

logger = logging.getLogger("iota_cluster_sync")

DEFAULT_REPO = "oakvillechen/iota-train-at-home-watchdog"
TELEMETRY_BRANCH = "telemetry"
MIN_PASSWORD_LEN = 8
WEAK_PASSWORDS = {"iota2026", "password", "12345678"}
MAC_INFO = b"iota-watchdog-mac-v2"


def password_problem(pwd: str):
    """返回密码不合格的原因；合格时返回 None"""
    pwd = (pwd or "").strip()
    if len(pwd) < MIN_PASSWORD_LEN:
        return f"加密密码至少需要 {MIN_PASSWORD_LEN} 位"
    if pwd.lower() in WEAK_PASSWORDS:
        return "不能使用公开的默认密码，请设置自己的加密密码"
    return None


def get_local_ip():
    """获取本机内网 IP 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def encrypt_payload_aes256(password: str, plaintext: bytes) -> dict:
    """
    使用 macOS 原生 CommonCrypto (CCCrypt) 执行标准 AES-256-CBC + PKCS7 加密。
    零第三方依赖，兼容浏览器 Web Crypto API。
    """
    salt = os.urandom(16)
    iv = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000, 32)

    # 仅使用进程内的 CommonCrypto；不再回退到 `openssl -K <hex>`，那会把密钥暴露在 ps 可见的命令行参数里
    libc = ctypes.cdll.LoadLibrary("/usr/lib/libSystem.B.dylib")
    CCCrypt = libc.CCCrypt
    CCCrypt.argtypes = [
        ctypes.c_uint32,  # op (0 = Encrypt)
        ctypes.c_uint32,  # alg (0 = AES)
        ctypes.c_uint32,  # options (1 = PKCS7Padding)
        ctypes.c_char_p,  # key
        ctypes.c_size_t,  # keyLength (32 bytes = 256 bits)
        ctypes.c_char_p,  # iv (16 bytes)
        ctypes.c_char_p,  # dataIn
        ctypes.c_size_t,  # dataInLength
        ctypes.c_char_p,  # dataOut
        ctypes.c_size_t,  # dataOutAvailable
        ctypes.POINTER(ctypes.c_size_t),  # dataOutMoved
    ]
    CCCrypt.restype = ctypes.c_int32

    out_len = len(plaintext) + 32
    out_buf = ctypes.create_string_buffer(out_len)
    moved = ctypes.c_size_t(0)

    res = CCCrypt(0, 0, 1, key, 32, iv, plaintext, len(plaintext), out_buf, out_len, ctypes.byref(moved))
    if res != 0:
        raise ValueError(f"CCCrypt failed with code {res}")
    ciphertext = out_buf.raw[: moved.value]

    # Encrypt-then-MAC：CBC 本身不防篡改，附加 HMAC-SHA256 供网页端校验完整性
    mac_key = hmac.new(key, MAC_INFO, hashlib.sha256).digest()
    mac = hmac.new(mac_key, salt + iv + ciphertext, hashlib.sha256).digest()
    return {
        "v": 2,
        "alg": "AES-256-CBC",
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "data": base64.b64encode(ciphertext).decode("ascii"),
        "mac": base64.b64encode(mac).decode("ascii"),
    }


def _resolve_token(config: dict) -> str:
    token = (config.get("github_token") or "").strip()
    if token:
        return token
    try:
        import secret_store
        token = secret_store.get_token()
        if token:
            return token
    except Exception:
        pass
    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github_token")
    if os.path.exists(token_file):
        try:
            with open(token_file, "r") as tf:
                return tf.read().strip()
        except Exception:
            pass
    return ""


def _telemetry_branch(config: dict) -> str:
    return (config.get("telemetry_branch") or TELEMETRY_BRANCH).strip()


def _gh_api(method: str, url: str, token: str, body=None, timeout: int = 15):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "IOTA-Watchdog-Sync",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _http_error_message(e: urllib.error.HTTPError) -> str:
    if e.code == 401:
        return "GitHub Token 无效或已过期 (401 Unauthorized)"
    if e.code == 403:
        return "Token 缺少该仓库的 Contents: Write 权限或触发 Rate Limit (403)"
    try:
        msg = json.loads(e.read().decode("utf-8")).get("message", "")
    except Exception:
        msg = ""
    return f"HTTP {e.code}: {msg or e.reason}"


def write_snapshot(token: str, repo: str, branch: str, files: dict, message: str) -> tuple:
    """
    在 `branch` 上写入/删除文件，生成一个无父提交并强制更新分支 (只保留最新快照，不累积历史)。
    files: {path: str 内容 | None 表示删除}
    并发写入时后写者会覆盖先写者本轮的更新，下一轮上报即可恢复，对 60 秒级遥测可接受。
    """
    api = f"https://api.github.com/repos/{repo}"
    last_err = ""
    for attempt in range(3):
        try:
            existing = set()
            base_tree = None
            branch_exists = True
            try:
                tree = _gh_api("GET", f"{api}/git/trees/{branch}?recursive=1", token)
                base_tree = tree.get("sha")
                existing = {t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"}
            except urllib.error.HTTPError as e:
                if e.code in (404, 409):
                    branch_exists = False
                else:
                    raise

            entries = []
            final_paths = set(existing)
            for path, content in files.items():
                if content is None:
                    if path in existing:
                        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                        final_paths.discard(path)
                else:
                    entries.append({"path": path, "mode": "100644", "type": "blob", "content": content})
                    final_paths.add(path)

            # 维护匿名节点清单，供网页端在 Contents API 限流时通过 raw 地址回退读取
            nodes = sorted(
                os.path.basename(p)[:-5]
                for p in final_paths
                if p.startswith("data/node-") and p.endswith(".json")
            )
            manifest = json.dumps({"updated_at": int(time.time()), "nodes": nodes}, indent=2)
            entries.append({"path": "data/cluster_manifest.json", "mode": "100644", "type": "blob", "content": manifest})

            tree_body = {"tree": entries}
            if base_tree:
                tree_body["base_tree"] = base_tree
            new_tree = _gh_api("POST", f"{api}/git/trees", token, tree_body)
            commit = _gh_api("POST", f"{api}/git/commits", token, {
                "message": message,
                "tree": new_tree["sha"],
                "parents": [],
            })
            if branch_exists:
                _gh_api("PATCH", f"{api}/git/refs/heads/{branch}", token, {"sha": commit["sha"], "force": True})
            else:
                _gh_api("POST", f"{api}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
            return True, "ok"
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, _http_error_message(e)
            last_err = _http_error_message(e)
        except Exception as e:
            last_err = f"网络请求失败: {e}"
        if attempt < 2:
            time.sleep(1.5)
    return False, last_err or "上报重试耗尽"


def upload_worker_status(config: dict, status_dict: dict) -> tuple:
    """
    通过 GitHub Git Data API 将节点状态同步至 telemetry 分支的 data/{node_slug}.json
    若开启端到端加密，将使用 AES-256-CBC + HMAC 加密整包，并将文件名脱敏为哈希代号
    """
    token = _resolve_token(config)
    if not token:
        return False, "未配置 GitHub Token (Fine-grained PAT 或 Classic Token)"

    repo = (config.get("github_repo") or DEFAULT_REPO).strip()
    branch = _telemetry_branch(config)

    # 获取机器标识符与别名
    hostname = socket.gethostname().split(".")[0]
    raw_miner_id = (
        status_dict.get("miner_id")
        or status_dict.get("miner_hotkey")
        or config.get("miner_id", "")
    ).strip()
    raw_worker_id = config.get("worker_id", "").strip() or f"miner-{raw_miner_id}"
    worker_name = config.get("worker_name", "").strip() or f"Mac ({hostname})"

    encrypt_enabled = config.get("cloud_encrypt_enabled", True)
    encrypt_pwd = (config.get("cloud_encrypt_password") or "").strip()
    if encrypt_enabled:
        problem = password_problem(encrypt_pwd)
        if problem:
            return False, f"{problem} (在「多机云端监控配置」中修改，并在网页看板使用同一密码)"

    # 文件命名与匿名化处理
    if encrypt_enabled:
        # 对 Miner ID 或 Worker ID 生成单向截断 SHA-256 哈希，彻底脱敏文件名
        unique_seed = raw_miner_id if (raw_miner_id and raw_miner_id != "检测中...") else raw_worker_id
        node_slug = "node-" + hashlib.sha256(unique_seed.encode("utf-8")).hexdigest()[:12]
    else:
        node_slug = raw_worker_id
    file_path = f"data/{node_slug}.json"
    display_id = node_slug

    now_ts = int(time.time())
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))

    payload = {
        "miner_id": raw_miner_id,
        "miner_hotkey": raw_miner_id,
        "worker_id": display_id,
        "worker_name": worker_name,
        "ip": get_local_ip(),
        "updated_at": now_ts,
        "updated_at_str": now_str,
        "status": status_dict.get("status", "running"),
        "phase": status_dict.get("phase", "正常运行中"),
        "proc_running": status_dict.get("proc_running", True),
        "layer": status_dict.get("layer", "--"),
        "run_id": status_dict.get("run_id", "--"),
        "epoch": status_dict.get("epoch", "--"),
        "queue_pos": status_dict.get("queue_pos", 0),
        "upload_speed": status_dict.get("upload_speed", "--"),
        "download_speed": status_dict.get("download_speed", "--"),
        "speedtest_time": status_dict.get("speedtest_time", ""),
        "peers_count": status_dict.get("peers_count", 0),
        "restart_count": status_dict.get("restart_count", 0),
        "recent_tokens": status_dict.get("recent_tokens", "--"),
        "cycle_tokens": status_dict.get("cycle_tokens", "--"),
        "hourly_tokens": status_dict.get("hourly_tokens", []),
        "last_payout": status_dict.get("last_payout", {}),
        "next_payout": status_dict.get("next_payout", {}),
        "last_log": status_dict.get("last_log", "暂无最新日志"),
    }

    raw_json_str = json.dumps(payload, ensure_ascii=False)
    if encrypt_enabled:
        try:
            enc_dict = encrypt_payload_aes256(encrypt_pwd, raw_json_str.encode("utf-8"))
            json_str = json.dumps(enc_dict, indent=2, ensure_ascii=False)
        except Exception as e:
            return False, f"AES 加密失败: {e}"
    else:
        json_str = json.dumps(payload, indent=2, ensure_ascii=False)

    files = {file_path: json_str}
    # 加密模式下清理同一矿工的未加密旧文件
    if encrypt_enabled and raw_miner_id and raw_miner_id != "检测中...":
        legacy_path = f"data/miner-{raw_miner_id}.json"
        if legacy_path != file_path:
            files[legacy_path] = None

    ok, msg = write_snapshot(token, repo, branch, files, f"telemetry: snapshot {display_id} [{now_str}]")
    if not ok:
        return False, msg
    suffix = " [AES-256 已加密]" if encrypt_enabled else " [未加密]"
    return True, f"上报成功 ({now_str}){suffix}"


def delete_worker_file(config: dict, worker_id: str) -> tuple:
    """从 telemetry 分支删除旧的或失效的节点数据文件 data/{worker_id}.json"""
    token = _resolve_token(config)
    if not token or not worker_id:
        return False, "缺少 Token 或 worker_id"
    repo = (config.get("github_repo") or DEFAULT_REPO).strip()
    return write_snapshot(
        token, repo, _telemetry_branch(config),
        {f"data/{worker_id}.json": None},
        f"telemetry: remove {worker_id}",
    )


def _cli_publish(argv: list) -> int:
    """
    将本地文件发布到 telemetry 分支，供 GitHub Actions / 本地守护进程使用:
      GH_TOKEN=... python3 iota_cluster_sync.py publish <local_file> <repo_path>
    """
    if len(argv) != 3 or argv[0] != "publish":
        print("usage: iota_cluster_sync.py publish <local_file> <repo_path>", file=sys.stderr)
        return 2
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    repo = os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO
    branch = os.environ.get("TELEMETRY_BRANCH") or TELEMETRY_BRANCH
    if not token:
        print("GH_TOKEN / GITHUB_TOKEN missing", file=sys.stderr)
        return 2
    with open(argv[1], "r", encoding="utf-8") as f:
        content = f.read()
    ok, msg = write_snapshot(token, repo, branch, {argv[2]: content}, f"telemetry: snapshot {argv[2]}")
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_cli_publish(sys.argv[1:]))
