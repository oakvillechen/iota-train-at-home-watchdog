#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IOTA Cluster Status Reporter (方案 A: 端到端 AES-256 加密同步)
将本机 Watchdog 采集到的节点状态通过 AES-256 加密后，自动上传至 GitHub 仓库 data/node-{hash}.json
完全隐藏真实 Miner ID、IP、收益和机器名称，仅持有密码的 Dashboard 网页可解密查看。
"""

import base64
import ctypes
import hashlib
import json
import logging
import os
import socket
import ssl
import time
import urllib.error
import urllib.request

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

logger = logging.getLogger("iota_cluster_sync")


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

    try:
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

        res = CCCrypt(
            0,
            0,
            1,
            key,
            32,
            iv,
            plaintext,
            len(plaintext),
            out_buf,
            out_len,
            ctypes.byref(moved),
        )
        if res != 0:
            raise ValueError(f"CCCrypt failed with code {res}")
        ciphertext = out_buf.raw[: moved.value]
    except Exception as e:
        # 兜底：调用系统 openssl
        import subprocess

        proc = subprocess.Popen(
            [
                "/usr/bin/openssl",
                "enc",
                "-aes-256-cbc",
                "-K",
                key.hex(),
                "-iv",
                iv.hex(),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ciphertext, err = proc.communicate(input=plaintext)
        if proc.returncode != 0:
            raise RuntimeError(f"OpenSSL encrypt failed: {err.decode('utf-8')}")

    return {
        "v": 1,
        "alg": "AES-256-CBC",
        "salt": base64.b64encode(salt).decode("ascii"),
        "iv": base64.b64encode(iv).decode("ascii"),
        "data": base64.b64encode(ciphertext).decode("ascii"),
    }


def upload_worker_status(config: dict, status_dict: dict) -> tuple[bool, str]:
    """
    通过 GitHub REST API 将节点状态同步至 data/{node_slug}.json
    若开启端到端加密，将使用 AES-256-CBC 加密整包，并将文件名脱敏为哈希代号
    """
    token = config.get("github_token", "").strip()
    if not token:
        token_file = os.path.join(os.path.dirname(__file__), ".github_token")
        if os.path.exists(token_file):
            try:
                with open(token_file, "r") as tf:
                    token = tf.read().strip()
            except Exception:
                pass

    if not token:
        return False, "未配置 GitHub Token (Fine-grained PAT 或 Classic Token)"

    repo = config.get("github_repo", "oakvillechen/iota-train-at-home-watchdog").strip()
    branch = config.get("github_branch", "main").strip()

    # 获取机器标识符与别名
    hostname = socket.gethostname().split(".")[0]
    raw_miner_id = (
        status_dict.get("miner_id")
        or status_dict.get("miner_hotkey")
        or config.get("miner_id", "")
    ).strip()
    raw_worker_id = config.get("worker_id", "").strip() or f"miner-{raw_miner_id}"
    worker_name = config.get("worker_name", "").strip() or f"Mac ({hostname})"

    # 加密开关及密码
    encrypt_enabled = config.get("cloud_encrypt_enabled", True)
    encrypt_pwd = config.get("cloud_encrypt_password", "").strip() or "iota2026"

    # 文件命名与匿名化处理
    if encrypt_enabled:
        # 对 Miner ID 或 Worker ID 生成单向截断 SHA-256 哈希，彻底脱敏文件名与 Git 历史
        unique_seed = raw_miner_id if (raw_miner_id and raw_miner_id != "检测中...") else raw_worker_id
        node_slug = "node-" + hashlib.sha256(unique_seed.encode("utf-8")).hexdigest()[:12]
        file_path = f"data/{node_slug}.json"
        display_id = node_slug
    else:
        node_slug = raw_worker_id
        file_path = f"data/{node_slug}.json"
        display_id = raw_worker_id

    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"IOTA-Watchdog-Sync/{display_id}",
    }

    # 构建赛博上报 Payload
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

    content_b64 = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

    # 带冲突自动重试机制的提交 (处理并发 commit 409 Conflict)
    max_retries = 3
    last_err = ""

    for attempt in range(max_retries):
        sha = None
        try:
            req = urllib.request.Request(
                f"{api_url}?ref={branch}&_t={int(time.time()*1000)}",
                headers=headers,
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sha = data.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                sha = None
            elif e.code == 401:
                return False, "GitHub Token 无效或已过期 (401 Unauthorized)"
            elif e.code == 403:
                return False, "Token 缺少该仓库的 Contents: Write 权限或触发 Rate Limit (403)"
            else:
                last_err = f"探测文件失败 (HTTP {e.code})"
                time.sleep(1.5)
                continue
        except Exception as e:
            last_err = f"探测网络失败: {e}"
            time.sleep(1.5)
            continue

        body = {
            "message": f"telemetry: update status for {display_id} [{now_str}]",
            "content": content_b64,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        try:
            body_bytes = json.dumps(body).encode("utf-8")
            put_headers = dict(headers)
            put_headers["Content-Type"] = "application/json"
            put_req = urllib.request.Request(
                api_url, data=body_bytes, headers=put_headers, method="PUT"
            )
            with urllib.request.urlopen(put_req, timeout=12) as put_resp:
                if put_resp.status in (200, 201):
                    # 如果原先存在未加密的旧文件 miner-{raw_miner_id}.json，异步删除清理
                    if encrypt_enabled and raw_miner_id and raw_miner_id != "检测中...":
                        legacy_id = f"miner-{raw_miner_id}"
                        if legacy_id != display_id:
                            try:
                                delete_worker_file(config, legacy_id)
                            except Exception:
                                pass
                    return True, f"上报成功 ({now_str}) [AES-256 已加密]"
                else:
                    last_err = f"HTTP {put_resp.status}"
        except urllib.error.HTTPError as e:
            if e.code == 409 and attempt < max_retries - 1:
                time.sleep(1.5)
                continue
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                err_msg = err_data.get("message", str(e))
            except Exception:
                err_msg = str(e)
            return False, f"HTTP {e.code}: {err_msg}"
        except Exception as e:
            last_err = f"网络请求失败: {e}"
            if attempt < max_retries - 1:
                time.sleep(1.5)
                continue

    return False, last_err or "上报重试耗尽"


def delete_worker_file(config: dict, worker_id: str) -> tuple:
    """
    通过 GitHub REST API 删除旧的或失效的未加密节点数据文件 data/{worker_id}.json
    """
    token = config.get("github_token", "").strip()
    if not token or not worker_id:
        return False, "缺少 Token 或 worker_id"

    repo = config.get("github_repo", "oakvillechen/iota-train-at-home-watchdog").strip()
    branch = config.get("github_branch", "main").strip()
    file_path = f"data/{worker_id}.json"
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"IOTA-Watchdog-Prune/{worker_id}",
    }

    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"{api_url}?ref={branch}&_t={int(time.time()*1000)}", headers=headers, method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sha = data.get("sha")

            if not sha:
                return True, "文件已不存在"

            del_payload = json.dumps(
                {
                    "message": f"security: purge unencrypted raw miner file {file_path}",
                    "sha": sha,
                    "branch": branch,
                }
            ).encode("utf-8")

            del_req = urllib.request.Request(
                api_url, data=del_payload, headers=headers, method="DELETE"
            )
            with urllib.request.urlopen(del_req, timeout=10) as put_resp:
                return True, f"已清理敏感文件 {file_path}"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return True, "文件已不存在"
            if e.code == 409 and attempt < 3:
                time.sleep(1.5)
                continue
            return False, f"HTTP {e.code}"
        except Exception as e:
            if attempt < 3:
                time.sleep(1.5)
                continue
            return False, f"清理失败: {e}"
    return False, "清理重试耗尽"


def update_cluster_manifest(config: dict, active_node_slugs: list) -> tuple:
    """
    更新 data/cluster_manifest.json，仅包含脱敏后的 node-xxxx 列表
    """
    token = config.get("github_token", "").strip()
    if not token:
        return False, "缺少 Token"

    repo = config.get("github_repo", "oakvillechen/iota-train-at-home-watchdog").strip()
    branch = config.get("github_branch", "main").strip()
    file_path = "data/cluster_manifest.json"
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "IOTA-Watchdog-Manifest",
    }

    manifest_data = {
        "updated_at": int(time.time()),
        "nodes": sorted(list(set(active_node_slugs))),
    }
    content_b64 = base64.b64encode(
        json.dumps(manifest_data, indent=2).encode("utf-8")
    ).decode("utf-8")

    try:
        sha = None
        try:
            req = urllib.request.Request(
                f"{api_url}?ref={branch}&_t={int(time.time()*1000)}", headers=headers, method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                sha = json.loads(resp.read().decode("utf-8")).get("sha")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                return False, f"HTTP {e.code}"

        body = {
            "message": "telemetry: update cluster manifest with anonymous nodes",
            "content": content_b64,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        put_req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        with urllib.request.urlopen(put_req, timeout=10) as resp:
            return True, "已更新集群列表"
    except Exception as e:
        return False, str(e)
