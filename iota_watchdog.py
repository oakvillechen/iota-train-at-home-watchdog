#!/usr/bin/env python3
import os
import sys
import time
import glob
import subprocess
import re
from datetime import datetime

# ==================== 配置项 ====================
LOG_DIR = os.path.expanduser("~/Library/Logs/IOTA Train at Home")
APP_NAME = "IOTA Train at Home"
CHECK_INTERVAL_SECS = 30           # 检查间隔（秒）
MAX_INIT_STUCK_MINUTES = 12        # 连续卡在 'status': 'initializing' 的最大容忍时间（分钟）
MAX_LOG_STALE_MINUTES = 3          # 日志无更新判定为进程卡死的时间（分钟）
RESTART_COOLDOWN_MINUTES = 3       # 重启后的冷却时间（分钟，防止启动过程中被误杀）
# ===============================================

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] [Watchdog] {msg}", flush=True)

def get_latest_cli_log():
    files = glob.glob(os.path.join(LOG_DIR, "*[0-9]-cli.log"))
    if not files:
        return None
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return files[0]

def is_app_running():
    try:
        out = subprocess.check_output(["pgrep", "-f", "IOTA Train at Home"]).decode().strip()
        return bool(out)
    except subprocess.CalledProcessError:
        return False

def restart_iota():
    log("⚠️ 触发强制重启 IOTA Train at Home...")
    
    # 强制杀死相关进程
    subprocess.run(["pkill", "-9", "-f", "IOTA Train at Home"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "main_pool"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "iota-cli"], stderr=subprocess.DEVNULL)
    
    time.sleep(3)
    
    # 重新拉起应用
    subprocess.run(["open", "-a", APP_NAME])
    log("🚀 已重新启动 IOTA Train at Home 应用。进入启动冷却期...")

def analyze_log(log_path):
    """
    检查日志状态：
    1. 日志最后修改时间
    2. 是否长时间卡在 initializing
    """
    if not os.path.exists(log_path):
        return "NO_LOG", "日志文件不存在"
    
    mtime = os.path.getmtime(log_path)
    stale_seconds = time.time() - mtime
    if stale_seconds > MAX_LOG_STALE_MINUTES * 60:
        return "STALE", f"日志超过 {int(stale_seconds // 60)} 分钟未更新"

    # 读取日志末尾 200 行
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-200:]
    except Exception as e:
        return "READ_ERROR", str(e)

    heartbeat_lines = []
    hb_pattern = re.compile(r"response:\s*({.*?status.*?})")
    
    for line in lines:
        match = hb_pattern.search(line)
        if match:
            heartbeat_lines.append(match.group(1))

    if heartbeat_lines:
        latest_hb = heartbeat_lines[-1]
        # 如果最新状态是 initializing
        if "'status': 'initializing'" in latest_hb or '"status": "initializing"' in latest_hb:
            return "INITIALIZING", latest_hb
        else:
            return "RUNNING_OK", latest_hb

    return "ACTIVE", "日志正常输出中"

def main():
    log("=== IOTA Train at Home 智能看门狗已启动 ===")
    log(f"监控目录: {LOG_DIR}")
    log(f"最大初始化容忍时间: {MAX_INIT_STUCK_MINUTES} 分钟 | 日志假死判定: {MAX_LOG_STALE_MINUTES} 分钟")

    first_init_detected_time = None
    last_restart_time = 0

    while True:
        try:
            current_time = time.time()

            # 检查是否处于重启冷却中
            if current_time - last_restart_time < RESTART_COOLDOWN_MINUTES * 60:
                time.sleep(CHECK_INTERVAL_SECS)
                continue

            # 1. 检查应用进程是否存在
            if not is_app_running():
                log("检测到 IOTA Train at Home 进程未运行，正在拉起...")
                restart_iota()
                last_restart_time = current_time
                first_init_detected_time = None
                time.sleep(CHECK_INTERVAL_SECS)
                continue

            # 2. 检查日志
            latest_log = get_latest_cli_log()
            if not latest_log:
                log("未找到 cli 日志，等待中...")
                time.sleep(CHECK_INTERVAL_SECS)
                continue

            status, detail = analyze_log(latest_log)

            if status == "STALE":
                log(f"❌ 进程假死: {detail}")
                restart_iota()
                last_restart_time = current_time
                first_init_detected_time = None

            elif status == "INITIALIZING":
                if first_init_detected_time is None:
                    first_init_detected_time = current_time
                    log("ℹ️ 检测到状态为 initializing，开始计时...")
                else:
                    stuck_mins = (current_time - first_init_detected_time) / 60
                    log(f"⏳ 处于 initializing 状态已持续 {stuck_mins:.1f}/{MAX_INIT_STUCK_MINUTES} 分钟")
                    if stuck_mins >= MAX_INIT_STUCK_MINUTES:
                        log(f"❌ 连续卡在 initializing 超过 {MAX_INIT_STUCK_MINUTES} 分钟，判定为失联卡死！")
                        restart_iota()
                        last_restart_time = current_time
                        first_init_detected_time = None
            else:
                # 正常运行中，重置卡死计时
                if first_init_detected_time is not None:
                    log("✅ 节点已成功进入训练/活跃状态，重置初始化计时。")
                    first_init_detected_time = None

        except Exception as e:
            log(f"监控异常: {e}")

        time.sleep(CHECK_INTERVAL_SECS)

if __name__ == "__main__":
    main()
