#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IOTA Telemetry Poller Daemon (本地秒级准点守护进程)
解决 GitHub Actions Cron (schedule) 延迟 15-45 分钟的问题。

直接从本机轮询 Macrocosmos 官方 API，生成加密遥测包并通过 GitHub REST API 即时提交，
调度延迟为 0，运行耗时 < 6 秒，不消耗 GitHub Actions 免费额度。
"""

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("telemetry_daemon")

DEFAULT_REPO = "oakvillechen/iota-train-at-home-watchdog"


def load_local_config():
    cfg_path = os.path.expanduser("~/Library/Logs/IOTA Train at Home/watchdog_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取本地 watchdog_config 失败: {e}")
    return {}


def get_secret_value(env_key, config_key, local_cfg, filename=None, default=""):
    """优先从环境变量获取，其次从本地配置获取，最后从本地受保护文件获取"""
    val = os.environ.get(env_key, "").strip()
    if val:
        return val
    val = local_cfg.get(config_key, "").strip()
    if val:
        return val
    if filename:
        repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fpath = os.path.join(repo_dir, filename)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
            except Exception:
                pass
    return default


def upload_telemetry_to_github(repo, branch, token, json_bytes):
    """通过 GitHub Contents API 即时 PUT data/telemetry/miners.json"""
    api_url = f"https://api.github.com/repos/{repo}/contents/data/telemetry/miners.json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "IOTA-Telemetry-Poller/1.0",
    }

    # 获取当前文件的 sha
    sha = None
    try:
        req = urllib.request.Request(f"{api_url}?ref={branch}&_t={int(time.time()*1000)}", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sha = None
        else:
            logger.warning(f"获取旧 SHA 失败 (HTTP {e.code})")
    except Exception as e:
        logger.warning(f"网络探测失败: {e}")

    content_b64 = base64.b64encode(json_bytes).decode("ascii")
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    body = {
        "message": f"telemetry: update miners.json [{now_str}] (local daemon)",
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    req = urllib.request.Request(
        api_url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.status in (200, 201)


def poll_and_sync(repo, branch, token, m3_hotkey, m1_hotkey, password, repo_dir):
    script_path = os.path.join(repo_dir, "scripts", "poll-telemetry.mjs")
    if not os.path.exists(script_path):
        logger.error(f"找不到 {script_path}")
        return False

    env = dict(os.environ)
    if m3_hotkey:
        env["M3_HOTKEY"] = m3_hotkey
    if m1_hotkey:
        env["M1_HOTKEY"] = m1_hotkey
    if password:
        env["TELEMETRY_PASSWORD"] = password
    env["OUTPUT_PATH"] = os.path.join(repo_dir, "data", "telemetry", "miners.json")

    logger.info("正在从 Macrocosmos 官方 API 抓取各 RUN 及机器遥测...")
    t0 = time.time()
    proc = subprocess.run(
        ["node", script_path],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    duration = time.time() - t0

    if proc.returncode != 0:
        logger.error(f"poll-telemetry.mjs 失败 (耗时 {duration:.1f}s): {proc.stderr}")
        return False

    logger.info(f"官方 API 抓取完成 (耗时 {duration:.1f}s): {proc.stdout.strip()}")

    out_file = env["OUTPUT_PATH"]
    if not os.path.exists(out_file):
        logger.error("产出文件不存在")
        return False

    if token:
        try:
            with open(out_file, "rb") as f:
                content_bytes = f.read()
            ok = upload_telemetry_to_github(repo, branch, token, content_bytes)
            if ok:
                logger.info("已通过 GitHub REST API 成功即时同步 data/telemetry/miners.json (0秒延迟)")
                return True
            else:
                logger.error("GitHub REST API 上传失败")
        except Exception as e:
            logger.error(f"上传 GitHub 异常: {e}")
            return False
    else:
        logger.warning("未配置 GitHub Token，仅更新了本地 data/telemetry/miners.json")
        return True


def main():
    parser = argparse.ArgumentParser(description="IOTA Telemetry Poller Daemon")
    parser.add_argument("--once", action="store_true", help="单次执行后退出")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔秒数 (默认 60s)")
    args = parser.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_cfg = load_local_config()

    token = get_secret_value("GITHUB_TOKEN", "github_token", local_cfg, filename=".github_token")
    repo = local_cfg.get("github_repo", DEFAULT_REPO).strip()
    branch = local_cfg.get("github_branch", "main").strip()
    pwd = get_secret_value("TELEMETRY_PASSWORD", "cloud_encrypt_password", local_cfg, default="iota2026")

    m1_hk = get_secret_value("M1_HOTKEY", "miner_id", local_cfg, filename=".m1_hotkey")
    m3_hk = get_secret_value("M3_HOTKEY", "m3_hotkey", local_cfg, filename=".m3_hotkey")

    logger.info("=========================================")
    logger.info("  IOTA 本地遥测守护进程 (Zero-Delay Poller)")
    logger.info(f"  仓库: {repo} ({branch})")
    m3_tail = f"...{m3_hk[-6:]}" if len(m3_hk) >= 6 else "(未配置)"
    m1_tail = f"...{m1_hk[-6:]}" if len(m1_hk) >= 6 else "(未配置)"
    logger.info(f"  M3: {m3_tail} | M1: {m1_tail}")
    logger.info(f"  模式: {'单次执行' if args.once else f'持续守护 (间隔 {args.interval}s)'}")
    logger.info("=========================================")

    while True:
        try:
            poll_and_sync(repo, branch, token, m3_hk, m1_hk, pwd, repo_dir)
        except Exception as e:
            logger.error(f"执行异常: {e}")

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
