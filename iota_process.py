#!/usr/bin/env python3
"""
iota_process.py - 精确定位并终止 IOTA Train at Home 相关进程

按可执行文件路径匹配，而不是 `pkill -f <名字>`，避免误杀命令行里恰好包含
"IOTA Train at Home" 的其他进程 (如 tail/grep 日志目录的终端命令)。
"""
import os
import signal
import subprocess
import time

APP_BUNDLE_MARKERS = (
    "/Applications/IOTA Train at Home.app/",
)
PROC_TITLE_PREFIXES = (
    "main_pool:ai.macrocosmos.iota",
)


def _is_iota_exe(comm: str) -> bool:
    if any(m in comm for m in APP_BUNDLE_MARKERS):
        return True
    return comm.startswith(PROC_TITLE_PREFIXES)


def find_iota_pids() -> list:
    try:
        out = subprocess.run(["/bin/ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    me = os.getpid()
    pids = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, comm = line.partition(" ")
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid != me and _is_iota_exe(comm.strip()):
            pids.append(pid)
    return pids


def is_running() -> bool:
    return bool(find_iota_pids())


def stop_iota(grace_seconds: float = 5.0) -> int:
    """先 SIGTERM 让应用正常退出，超时后对残留进程 SIGKILL。返回处理的进程数。"""
    pids = find_iota_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not find_iota_pids():
            return len(pids)
        time.sleep(0.5)
    for pid in find_iota_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return len(pids)
