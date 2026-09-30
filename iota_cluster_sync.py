#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IOTA Cluster Status Reporter (方案 1: 纯 GitHub API 同步)
将本机 Watchdog 采集到的节点状态自动上传至指定 GitHub 仓库的 data/{worker_id}.json
"""

import base64
import json
import logging
import os
import socket
import time
import requests

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


def upload_worker_status(config: dict, status_dict: dict) -> tuple[bool, str]:
    """
    通过 GitHub REST API 将节点状态同步至 data/{worker_id}.json
    :param config: 全局配置字典，包含 token, repo, branch, worker_id, worker_name
    :param status_dict: 节点当前运行状态参数
    :return: (是否成功, 提示消息)
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
    worker_id = config.get("worker_id", "").strip() or f"node-{hostname.lower()}"
    worker_name = config.get("worker_name", "").strip() or f"Mac ({hostname})"

    file_path = f"data/{worker_id}.json"
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"IOTA-Watchdog-Sync/{worker_id}"
    }

    # 1. 尝试获取已有文件的 sha (更新已有文件时必须携带 sha)
    sha = None
    try:
        res = requests.get(f"{api_url}?ref={branch}", headers=headers, timeout=8)
        if res.status_code == 200:
            sha = res.json().get("sha")
        elif res.status_code == 404:
            sha = None  # 文件尚不存在，直接新建
        elif res.status_code == 401:
            return False, "GitHub Token 无效或已过期 (401 Unauthorized)"
        elif res.status_code == 403:
            return False, "Token 缺少该仓库的 Contents: Write 权限或触发 Rate Limit (403)"
    except Exception as e:
        return False, f"探测现有文件失败: {e}"

    # 2. 构建赛博上报 Payload
    now_ts = int(time.time())
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))

    payload = {
        "worker_id": worker_id,
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
        "last_log": status_dict.get("last_log", "暂无最新日志")
    }

    json_str = json.dumps(payload, indent=2, ensure_ascii=False)
    content_b64 = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

    # 3. 提交 PUT contents 请求
    body = {
        "message": f"telemetry: update status for {worker_id} [{now_str}]",
        "content": content_b64,
        "branch": branch
    }
    if sha:
        body["sha"] = sha

    try:
        put_res = requests.put(api_url, headers=headers, json=body, timeout=10)
        if put_res.status_code in (200, 201):
            return True, f"上报成功 ({now_str})"
        else:
            err_msg = put_res.json().get("message", put_res.text)
            return False, f"HTTP {put_res.status_code}: {err_msg}"
    except Exception as e:
        return False, f"网络请求失败: {e}"


if __name__ == "__main__":
    # 本地快速测试
    print("Testing cluster reporter module...")
    mock_config = {
        "github_token": os.environ.get("GITHUB_TOKEN", ""),
        "github_repo": "oakvillechen/iota-train-at-home-watchdog",
        "github_branch": "main",
        "worker_id": "test-worker",
        "worker_name": "Test Node 01"
    }
    mock_status = {
        "status": "training",
        "phase": "测试中 (Layer 3)",
        "proc_running": True,
        "upload_speed": "20.0 Mbps",
        "download_speed": "50.0 Mbps",
        "recent_tokens": "10.5万",
        "last_log": "Module self-test log output"
    }
    ok, msg = upload_worker_status(mock_config, mock_status)
    print(f"Result: ok={ok}, message={msg}")
