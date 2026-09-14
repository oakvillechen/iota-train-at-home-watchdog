#!/usr/bin/env python3
import os
import sys
import time
import glob
import subprocess
import re
import json
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, scrolledtext

CONFIG_FILE = os.path.expanduser("~/Library/Logs/IOTA Train at Home/watchdog_config.json")
LOG_DIR = os.path.expanduser("~/Library/Logs/IOTA Train at Home")
APP_NAME = "IOTA Train at Home"
APP_PATH = "/Applications/IOTA Train at Home.app"

DEFAULT_CONFIG = {
    "max_stale_minutes": 10,
    "cooldown_minutes": 3,
    "check_interval_seconds": 15,
    "auto_watchdog_enabled": True,
    "filter_key_logs_only": True,
    "auto_scroll": True,
    "dark_mode": True,
    "caffeinate_enabled": True,
    "log_font_size": 12
}

# 忽略的高频底层网络心跳日志（避免刷屏）
IGNORED_PATTERNS = [
    "CASVersionMismatch",
    "has no p2p_node_ids",
    "dropped — hotkey not in current run",
    "P2P /peer/status from",
    "Making orchestrator request | method: GET | path: /miner/heartbeat",
    "Making orchestrator request | method: GET | path: /miner/all_layers_training",
    "Telemetry flush:",
    "TelemetryBufferService",
]

KEY_LOG_KEYWORDS = [
    "reset_miner_state", "Resetting miner", "Starting", "worker", "registered",
    "register", "registration", "speedtest", "Speedtest", "attestation",
    "training.state", "Loading model weights", "optimizer state", "training",
    "epoch", "step", "gradient", "upload", "earning", "reward", "payout",
    "incentive", "balance", "500 - Internal Server Error", "CRITICAL", "ERROR",
    "FORWARD complete", "BACKWARD complete", "Forward pass", "Backward pass",
    "Downloaded activation", "Peer status dict has", "Broadcast peer status",
    "all_layers_training", "activation_queue", "select_by_capacity", "report_loss",
    "submit_activation", "submit_weights", "position", "queued", "queue_id",
    "/miner/register/status"
]

THEMES = {
    "dark": {
        "bg_root": "#0b0f19",
        "bg_card": "#161f30",
        "bg_subcard": "#1f2c42",
        "border": "#2d3d54",
        "fg_title": "#f8fafc",
        "fg_text": "#e2e8f0",
        "fg_muted": "#94a3b8",
        "entry_bg": "#0b0f19",
        "entry_fg": "#38bdf8",
        "btn_neutral_bg": "#2d3d54",
        "btn_neutral_hover": "#3b506e",
        "btn_neutral_fg": "#f8fafc",
        "btn_exit_bg": "#dc2626",
        "btn_exit_hover": "#ef4444",
        "log_bg": "#030712",
        "log_fg": "#f8fafc",
    },
    "light": {
        "bg_root": "#f1f5f9",
        "bg_card": "#ffffff",
        "bg_subcard": "#f8fafc",
        "border": "#cbd5e1",
        "fg_title": "#0f172a",
        "fg_text": "#1e293b",
        "fg_muted": "#64748b",
        "entry_bg": "#f8fafc",
        "entry_fg": "#1d4ed8",
        "btn_neutral_bg": "#e2e8f0",
        "btn_neutral_hover": "#cbd5e1",
        "btn_neutral_fg": "#0f172a",
        "btn_exit_bg": "#ef4444",
        "btn_exit_hover": "#dc2626",
        "log_bg": "#0f172a",
        "log_fg": "#f8fafc",
    }
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")

class ModernButton(tk.Label):
    def __init__(self, parent, text, command=None, bg_color="#2d3d54", fg_color="#f8fafc", hover_bg="#3b506e", font=("Helvetica", 11, "bold"), padx=12, pady=5, **kwargs):
        super().__init__(parent, text=text, bg=bg_color, fg=fg_color, font=font, padx=padx, pady=pady, relief="solid", bd=1, cursor="pointinghand", **kwargs)
        self.command = command
        self.bg_color = bg_color
        self.hover_bg = hover_bg
        self.fg_color = fg_color

        self.bind("<Enter>", lambda e: self.config(bg=self.hover_bg))
        self.bind("<Leave>", lambda e: self.config(bg=self.bg_color))
        self.bind("<Button-1>", self._on_click)

    def _on_click(self, event=None):
        if callable(self.command):
            self.command()

    def set_colors(self, bg_color, fg_color, hover_bg=None):
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_bg = hover_bg or bg_color
        self.config(bg=bg_color, fg=fg_color)

class IotaWatchdogApp:
    def __init__(self, root):
        self.root = root
        self.root.title("IOTA Train at Home 智能监控控制台")
        self.root.geometry("980x980")
        self.root.minsize(800, 800)

        self.config = load_config()
        self.dark_mode = self.config.get("dark_mode", True)
        self.log_font_size = self.config.get("log_font_size", 12)
        self.caffeinate_proc = None
        self.is_restarting = False

        self.is_monitoring = self.config.get("auto_watchdog_enabled", True)
        self.filter_key_logs = tk.BooleanVar(value=self.config.get("filter_key_logs_only", True))
        self.auto_scroll_var = tk.BooleanVar(value=self.config.get("auto_scroll", True))
        self.caffeinate_var = tk.BooleanVar(value=self.config.get("caffeinate_enabled", True))
        
        self.last_restart_time = 0
        self.current_log_file = None
        self.log_file_pos = 0

        # 排队与状态统计数据
        self.miner_hotkey = "检测中..."
        self.payout_coldkey = "检测中..."
        self.current_layer = "检测中..."
        self.current_network = "IOTA Bittensor Subnet"
        self.current_run_id = "检测中..."
        self.current_epoch = "检测中..."
        self.current_phase = "检测中..."
        self.last_status = "检测中..."
        self.last_upload_speed = "检测中..."
        self.last_download_speed = "检测中..."
        self.active_peers_count = "检测中..."
        self.peer_mesh_status = "检测中..."
        self.all_layers_ready = "未知"
        
        self.queue_start_time = None
        self.prev_queue_position = None
        self.last_queue_position = None
        self.queue_id = "检测中..."
        self.forward_count = 0
        self.backward_count = 0
        self.is_actively_training = False
        self.last_peer_log_time = 0
        self.last_queue_heartbeat_log_time = 0

        self.widgets = {}

        self.setup_ui()
        self.apply_theme()

        if self.caffeinate_var.get():
            self.start_caffeinate()

        # 扫描历史测速与初始状态
        self.load_initial_stats()

        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()

        self.stream_thread = threading.Thread(target=self.log_stream_loop, daemon=True)
        self.stream_thread.start()

        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

    def get_queue_status_text(self, wait_mins=0.0):
        if self.last_queue_position is None:
            return f"排队状态: ⏳ 正在排队就绪中 (已等 {wait_mins:.1f} 分钟)"

        if self.prev_queue_position is not None and self.prev_queue_position != self.last_queue_position:
            diff = self.prev_queue_position - self.last_queue_position
            if diff > 0:
                diff_str = f" | ⬆ 前进 {diff} 位"
            elif diff < 0:
                diff_str = f" | ⬇ 后退 {abs(diff)} 位"
            else:
                diff_str = ""
            pos_str = f"目前 第 {self.last_queue_position} 位 (前次 {self.prev_queue_position}{diff_str})"
        else:
            pos_str = f"目前 第 {self.last_queue_position} 位"

        return f"排队状态: ⏳ {pos_str} | 已等 {wait_mins:.1f} 分钟"

    def load_initial_stats(self):
        latest_log = self.get_latest_log()
        if latest_log and os.path.exists(latest_log):
            try:
                with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    # 测速
                    speed_matches = list(re.finditer(r"Speedtest completed with results:\s*(\{.*?\})", content))
                    if speed_matches:
                        data = json.loads(speed_matches[-1].group(1).replace("'", '"'))
                        up = data.get("upload_mbps")
                        down = data.get("download_mbps")
                        if up is not None and down is not None:
                            self.last_upload_speed = f"{up:.1f} Mbps"
                            self.last_download_speed = f"{down:.1f} Mbps"
                            self.update_speed_ui()
                    
                    # 活跃邻居
                    peer_matches = list(re.finditer(r"Peer status dict has (\d+) entries", content))
                    if peer_matches:
                        self.active_peers_count = f"{peer_matches[-1].group(1)} 个"

                    # 广播网格联通
                    bc_matches = list(re.finditer(r"Broadcast peer status:\s*(\d+/\d+)\s*ok", content))
                    if bc_matches:
                        self.peer_mesh_status = f"{bc_matches[-1].group(1)} 在线"

                    # All layers training
                    all_matches = list(re.finditer(r"request to /miner/all_layers_training;\s*response:\s*(True|False)", content))
                    if all_matches:
                        self.all_layers_ready = "已就绪 (True)" if all_matches[-1].group(1) == "True" else "未就绪 (False)"

                    # 提取排队位置历史
                    pos_matches = list(re.finditer(r"['\"]position['\"]\s*:\s*([0-9]+)", content))
                    if pos_matches:
                        unique_positions = []
                        for m in pos_matches:
                            val = int(m.group(1))
                            if not unique_positions or unique_positions[-1] != val:
                                unique_positions.append(val)
                        if len(unique_positions) >= 2:
                            self.prev_queue_position = unique_positions[-2]
                        self.last_queue_position = unique_positions[-1]
                        self.root.after(0, lambda: [
                            self.lbl_node_phase.config(text=f"当前阶段: 🟡 队列排队中 ({self.current_layer})", fg="#d97706" if not self.dark_mode else "#fbbf24"),
                            self.lbl_init_timer.config(text=self.get_queue_status_text(0.0), fg="#d97706" if not self.dark_mode else "#fbbf24")
                        ])

                    # 计算 Forward / Backward 历史
                    fwd_matches = re.findall(r"FORWARD complete", content)
                    bwd_matches = re.findall(r"BACKWARD complete", content)
                    if fwd_matches or bwd_matches:
                        self.forward_count = len(fwd_matches)
                        self.backward_count = len(bwd_matches)
                        self.is_actively_training = True

                    # 提取心跳
                    hb_matches = list(re.finditer(r"response:\s*({.*?status.*?})", content))
                    if hb_matches:
                        latest_hb = hb_matches[-1].group(1)
                        st_m = re.search(r"['\"]status['\"]\s*:\s*['\"]([^'\"]+)['\"]", latest_hb)
                        if st_m:
                            self.last_status = st_m.group(1)
                            if self.last_status == "initializing":
                                self.queue_start_time = time.time()
            except Exception:
                pass

    def update_speed_ui(self):
        def _update():
            if self.last_upload_speed != "检测中...":
                self.lbl_speed_info.config(text=f"最近测速网速: ⬆ 上传 {self.last_upload_speed}  (⬇ 下载 {self.last_download_speed})", fg="#0284c7" if not self.dark_mode else "#38bdf8")
        self.root.after(0, _update)

    def change_font_size(self, delta):
        new_size = max(9, min(26, self.log_font_size + delta))
        if new_size != self.log_font_size:
            self.log_font_size = new_size
            self.config["log_font_size"] = self.log_font_size
            save_config(self.config)
            self.txt_log.config(font=("Menlo", self.log_font_size))
            self.lbl_font_display.config(text=f"{self.log_font_size}pt")

    def start_caffeinate(self):
        if self.caffeinate_proc is None or self.caffeinate_proc.poll() is not None:
            try:
                self.caffeinate_proc = subprocess.Popen(["caffeinate", "-i", "-m", "-s"])
                self.append_watchdog_log("☕ [防休眠已开启] macOS 息屏后系统/网络/GPU将持续全速工作。")
            except Exception as e:
                self.append_watchdog_log(f"⚠️ 开启防休眠失败: {e}")

    def stop_caffeinate(self):
        if self.caffeinate_proc and self.caffeinate_proc.poll() is None:
            try:
                self.caffeinate_proc.terminate()
                self.caffeinate_proc.wait(timeout=1)
            except Exception:
                pass
            self.caffeinate_proc = None
            self.append_watchdog_log("💤 [防休眠已关闭] 恢复系统默认休眠。")

    def toggle_caffeinate(self):
        enabled = self.caffeinate_var.get()
        self.config["caffeinate_enabled"] = enabled
        save_config(self.config)
        if enabled:
            self.start_caffeinate()
        else:
            self.stop_caffeinate()

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.config["dark_mode"] = self.dark_mode
        save_config(self.config)
        self.apply_theme()

    def apply_theme(self):
        t = THEMES["dark"] if self.dark_mode else THEMES["light"]
        
        self.root.configure(bg=t["bg_root"])
        self.btn_theme.config(text="☀️ 浅色模式" if self.dark_mode else "🌙 深色模式")
        self.btn_theme.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        self.btn_exit.set_colors(t["btn_exit_bg"], "#ffffff", t["btn_exit_hover"])

        for name, w in self.widgets.items():
            if isinstance(w, tk.Frame) or isinstance(w, tk.LabelFrame):
                if name.startswith("root_") or name in ["main_frame", "ctrl_frame", "font_ctrl_frame", "cfg_sub_frame"]:
                    w.config(bg=t["bg_root"])
                elif name.startswith("card_"):
                    w.config(bg=t["bg_card"], fg=t["fg_title"] if isinstance(w, tk.LabelFrame) else None)
                elif name.startswith("subcard_"):
                    w.config(bg=t["bg_subcard"])
                else:
                    w.config(bg=t["bg_card"])
            elif isinstance(w, tk.Label) and not isinstance(w, ModernButton):
                if name.startswith("lbl_title"):
                    w.config(bg=t["bg_card"], fg=t["fg_title"])
                elif name.startswith("lbl_sub_"):
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                elif name.startswith("lbl_badge_"):
                    w.config(bg=t["bg_subcard"], fg="#38bdf8" if self.dark_mode else "#1d4ed8")
                elif name in ["lbl_proc_status", "lbl_node_phase", "lbl_log_time", "lbl_train_stats"]:
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                elif name == "lbl_speed_info":
                    w.config(bg=t["bg_card"])
                elif name == "lbl_font_display":
                    w.config(bg=t["bg_root"], fg=t["fg_text"])
                elif name == "lbl_font_tag":
                    w.config(bg=t["bg_root"], fg=t["fg_muted"])
                elif name == "lbl_init_timer":
                    w.config(bg=t["bg_card"])
                elif "cfg_" in name:
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                else:
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
            elif isinstance(w, tk.Checkbutton):
                w.config(bg=t["bg_root"] if "ctrl" in name else t["bg_card"], fg=t["fg_text"], selectcolor=t["bg_card"], activebackground=t["bg_root"])
            elif isinstance(w, tk.Entry):
                w.config(bg=t["entry_bg"], fg=t["entry_fg"], insertbackground=t["entry_fg"], readonlybackground=t["entry_bg"], selectbackground="#2563eb", selectforeground="#ffffff")

        self.btn_toggle.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        self.btn_clear_log.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        self.btn_font_dec.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        self.btn_font_inc.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        self.btn_copy_hk.set_colors("#2563eb", "#ffffff", "#3b82f6")
        self.btn_copy_ck.set_colors("#2563eb", "#ffffff", "#3b82f6")
        self.btn_restart.set_colors("#dc2626", "#ffffff", "#ef4444")
        self.btn_clean_reset.set_colors("#b45309", "#ffffff", "#d97706")
        self.btn_save.set_colors("#059669", "#ffffff", "#10b981")

        self.txt_log.config(bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["log_fg"], font=("Menlo", self.log_font_size))

    def copy_to_clipboard(self, text, label_name):
        if not text or "检测中" in text:
            messagebox.showwarning("提示", f"{label_name} 尚未就绪，暂无法复制！")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.append_watchdog_log(f"📋 已复制 {label_name} 到剪贴板: {text}")

    def exit_app(self):
        try:
            self.running = False
            self.stop_caffeinate()
        except Exception:
            pass

        try:
            script = 'tell application "Terminal" to close (every window whose name contains "start_watchdog" or name contains "iota_watchdog_gui")'
            subprocess.Popen(["osascript", "-e", script], stderr=subprocess.DEVNULL)
        except Exception:
            pass

        try:
            self.root.destroy()
        except Exception:
            pass

        os._exit(0)

    def manual_restart(self):
        if self.is_restarting:
            return
        threading.Thread(target=self._do_restart, args=(True,), daemon=True).start()

    def confirm_deep_clean(self):
        if self.is_restarting:
            return
        ans = messagebox.askyesno(
            "确认深度清理与重置",
            "确定要执行 IOTA 深度清理与完全重置吗？\n\n"
            "此操作将会：\n"
            "• 强制终止 IOTA 及 miner 所有后台进程\n"
            "• 清理 Electron 应用缓存、配置与 savedState\n"
            "• 清理矿工钱包与矿工配置缓存\n"
            "• 清理旧的 .log 日志（保留本监控脚本）\n"
            "• 重新拉起全新的 IOTA Train at Home 实例\n\n"
            "是否继续？"
        )
        if ans:
            threading.Thread(target=self._do_deep_clean, daemon=True).start()

    def _do_deep_clean(self):
        if self.is_restarting:
            return
        self.is_restarting = True
        self.root.after(0, lambda: self.btn_clean_reset.config(text="⏳ 清理重置中..."))
        self.append_watchdog_log("🧹 [深度清理重置] 开始执行彻底清理与重置流程...")

        try:
            # 1. 停止进程
            self.append_watchdog_log("🛑 正在终止所有 IOTA 相关进程...")
            subprocess.run(["pkill", "-9", "-f", "IOTA Train at Home"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-f", "main_pool"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-f", "iota-cli"], stderr=subprocess.DEVNULL)
            time.sleep(1.5)

            # 2. 清理 Application Support / Caches / Preferences / State
            self.append_watchdog_log("🧹 正在清理应用缓存、配置与状态文件...")
            import shutil

            clean_dirs = [
                os.path.expanduser("~/Library/Application Support/IOTA Train at Home"),
                os.path.expanduser("~/Library/Caches/com.electron.iota-train-at-home"),
                os.path.expanduser("~/Library/Caches/com.electron.iota-train-at-home.ShipIt"),
                os.path.expanduser("~/Library/Preferences/com.electron.iota-train-at-home.plist"),
                os.path.expanduser("~/Library/Saved Application State/com.electron.iota-train-at-home.savedState"),
                os.path.expanduser("~/.bittensor/wallets/.pool_miner_payout.json"),
                os.path.expanduser("~/.bittensor/wallets/iota"),
                os.path.expanduser("~/.bittensor/miners"),
            ]
            for p in clean_dirs:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.isfile(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

            # 清理 ~/Library/Caches/iota*
            for cp in glob.glob(os.path.expanduser("~/Library/Caches/iota*")):
                if os.path.isdir(cp):
                    shutil.rmtree(cp, ignore_errors=True)
                elif os.path.isfile(cp):
                    try:
                        os.remove(cp)
                    except Exception:
                        pass

            # 3. 清理 Logs (仅 .log 文件，保留 watchdog 脚本)
            self.append_watchdog_log("🗑️ 正在清理旧日志文件...")
            for lp in glob.glob(os.path.join(LOG_DIR, "*.log")):
                try:
                    os.remove(lp)
                except Exception:
                    pass

            self.append_watchdog_log("✅ 深度清理完毕！正在启动全新 IOTA 会话...")
            time.sleep(1.5)

            # 4. 重新拉起应用
            if os.path.exists(APP_PATH):
                subprocess.run(["open", APP_PATH])
            else:
                subprocess.run(["open", "-a", APP_NAME])

            self.last_restart_time = time.time()
            self.queue_start_time = None
            self.log_file_pos = 0
            self.forward_count = 0
            self.backward_count = 0
            self.is_actively_training = False
            self.current_log_file = None
            self.miner_hotkey = "检测中..."
            self.payout_coldkey = "检测中..."
            self.current_layer = "检测中..."
            self.current_run_id = "检测中..."
            self.current_epoch = "检测中..."
            self.last_upload_speed = "检测中..."
            self.last_download_speed = "检测中..."
            self.active_peers_count = "检测中..."
            self.peer_mesh_status = "检测中..."
            self.all_layers_ready = "未知"

            self.update_miner_info_ui()
            self.update_speed_ui()
            self.append_watchdog_log("🚀 全新 IOTA Train at Home 已拉起，进入启动保护冷却期！")

        except Exception as e:
            self.append_watchdog_log(f"❌ 深度清理过程发生异常: {e}")
        finally:
            time.sleep(3)
            self.is_restarting = False
            self.root.after(0, lambda: self.btn_clean_reset.config(text="🧹 深度清理与重置"))

    def _do_restart(self, is_manual=False):
        if self.is_restarting:
            return
        self.is_restarting = True
        
        reason = "手动强制触发" if is_manual else "假死超时自动触发"
        self.append_watchdog_log(f"⚡ [执行强制重启] 原因: {reason}，正在停止旧进程...")
        self.root.after(0, lambda: self.btn_restart.config(text="⏳ 正在杀死旧进程..."))

        try:
            subprocess.run(["pkill", "-9", "-f", "IOTA Train at Home"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-f", "main_pool"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "-f", "iota-cli"], stderr=subprocess.DEVNULL)
            
            time.sleep(2)
            self.root.after(0, lambda: self.btn_restart.config(text="🚀 正在重新拉起应用..."))

            if os.path.exists(APP_PATH):
                subprocess.run(["open", APP_PATH])
            else:
                subprocess.run(["open", "-a", APP_NAME])

            self.last_restart_time = time.time()
            self.queue_start_time = None
            self.log_file_pos = 0
            self.forward_count = 0
            self.backward_count = 0
            self.is_actively_training = False
            self.append_watchdog_log("✅ 已成功拉起 IOTA Train at Home 应用！进入启动保护冷却期...")

        except Exception as e:
            self.append_watchdog_log(f"❌ 重启过程发生异常: {e}")
        finally:
            time.sleep(3)
            self.is_restarting = False
            self.root.after(0, lambda: self.btn_restart.config(text="⚡ 手动强制重启 IOTA"))

    def setup_ui(self):
        main_frame = tk.Frame(self.root, padx=14, pady=12)
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.widgets["main_frame"] = main_frame

        # 1. 顶部 Header
        header_frame = tk.Frame(main_frame, bd=1, relief="solid", padx=14, pady=10)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        self.widgets["card_header"] = header_frame

        top_row = tk.Frame(header_frame)
        top_row.pack(fill=tk.X)
        self.widgets["subcard_toprow"] = top_row

        title_lbl = tk.Label(top_row, text="IOTA Train at Home 智能监控控制台", font=("Helvetica", 17, "bold"))
        title_lbl.pack(side=tk.LEFT)
        self.widgets["lbl_title_main"] = title_lbl

        self.btn_exit = ModernButton(top_row, text="🚪 退出程序", command=self.exit_app, bg_color="#dc2626", fg_color="#ffffff", hover_bg="#ef4444", font=("Helvetica", 11, "bold"), padx=12, pady=4)
        self.btn_exit.pack(side=tk.RIGHT, padx=(10, 0))

        self.btn_theme = ModernButton(top_row, text="☀️ 浅色模式", command=self.toggle_theme, font=("Helvetica", 11, "bold"), padx=10, pady=4)
        self.btn_theme.pack(side=tk.RIGHT, padx=(10, 0))

        self.lbl_watchdog_status = tk.Label(top_row, text="● 自动守护中", font=("Helvetica", 13, "bold"), fg="#16a34a")
        self.lbl_watchdog_status.pack(side=tk.RIGHT)
        self.widgets["lbl_watchdog_status"] = self.lbl_watchdog_status

        # 2. 矿工与网络连接面板
        info_card = tk.LabelFrame(main_frame, text=" 矿工 ID 与连接信息 (一键复制) ", font=("Helvetica", 12, "bold"), padx=12, pady=10)
        info_card.pack(fill=tk.X, pady=(0, 10))
        self.widgets["card_info"] = info_card

        row1 = tk.Frame(info_card)
        row1.pack(fill=tk.X, pady=3)
        self.widgets["subcard_row1"] = row1

        lbl_hk = tk.Label(row1, text="Miner ID (Hotkey):", font=("Helvetica", 12, "bold"), width=16, anchor="w")
        lbl_hk.pack(side=tk.LEFT)
        self.widgets["lbl_sub_hk"] = lbl_hk

        self.entry_miner_id = tk.Entry(row1, font=("Menlo", 12, "bold"), bd=1, relief="solid")
        self.entry_miner_id.insert(0, "检测中...")
        self.entry_miner_id.config(state="readonly")
        self.entry_miner_id.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=2)
        self.widgets["entry_miner_id"] = self.entry_miner_id

        self.btn_copy_hk = ModernButton(row1, text="📋 复制 ID", command=lambda: self.copy_to_clipboard(self.miner_hotkey, "Miner ID"), bg_color="#2563eb", fg_color="#ffffff", hover_bg="#3b82f6", font=("Helvetica", 11, "bold"), padx=10, pady=3)
        self.btn_copy_hk.pack(side=tk.RIGHT)

        row2 = tk.Frame(info_card)
        row2.pack(fill=tk.X, pady=3)
        self.widgets["subcard_row2"] = row2

        lbl_ck = tk.Label(row2, text="Payout Coldkey:", font=("Helvetica", 12, "bold"), width=16, anchor="w")
        lbl_ck.pack(side=tk.LEFT)
        self.widgets["lbl_sub_ck"] = lbl_ck

        self.entry_coldkey = tk.Entry(row2, font=("Menlo", 12), bd=1, relief="solid")
        self.entry_coldkey.insert(0, "检测中...")
        self.entry_coldkey.config(state="readonly")
        self.entry_coldkey.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=2)
        self.widgets["entry_coldkey"] = self.entry_coldkey

        self.btn_copy_ck = ModernButton(row2, text="📋 复制 Coldkey", command=lambda: self.copy_to_clipboard(self.payout_coldkey, "Payout Coldkey"), bg_color="#2563eb", fg_color="#ffffff", hover_bg="#3b82f6", font=("Helvetica", 11, "bold"), padx=10, pady=3)
        self.btn_copy_ck.pack(side=tk.RIGHT)

        row3 = tk.Frame(info_card)
        row3.pack(fill=tk.X, pady=(6, 0))
        self.widgets["subcard_row3"] = row3

        self.lbl_layer = tk.Label(row3, text="连接 Layer: 检测中", font=("Helvetica", 12, "bold"), padx=10, pady=3, relief="groove")
        self.lbl_layer.pack(side=tk.LEFT, padx=(0, 8))
        self.widgets["lbl_badge_layer"] = self.lbl_layer

        self.lbl_network = tk.Label(row3, text="Network: IOTA Subnet", font=("Helvetica", 12, "bold"), padx=10, pady=3, relief="groove")
        self.lbl_network.pack(side=tk.LEFT, padx=(0, 8))
        self.widgets["lbl_badge_network"] = self.lbl_network

        self.lbl_run_id = tk.Label(row3, text="Run ID: 检测中", font=("Helvetica", 12, "bold"), padx=10, pady=3, relief="groove")
        self.lbl_run_id.pack(side=tk.LEFT, padx=(0, 8))
        self.widgets["lbl_badge_runid"] = self.lbl_run_id

        self.lbl_epoch = tk.Label(row3, text="Epoch: 检测中", font=("Helvetica", 12, "bold"), padx=10, pady=3, relief="groove")
        self.lbl_epoch.pack(side=tk.LEFT, padx=(0, 8))
        self.widgets["lbl_badge_epoch"] = self.lbl_epoch

        # 3. 运行状态看板（含实时排队状态与训练计算状态）
        status_card = tk.LabelFrame(main_frame, text=" 节点运行与排队/训练实时看板 ", font=("Helvetica", 12, "bold"), padx=12, pady=8)
        status_card.pack(fill=tk.X, pady=(0, 10))
        self.widgets["card_status"] = status_card

        grid_frame = tk.Frame(status_card)
        grid_frame.pack(fill=tk.X)
        self.widgets["subcard_grid"] = grid_frame

        # 进程与心跳
        self.lbl_proc_status = tk.Label(grid_frame, text="进程状态: 🟢 检测中...", font=("Helvetica", 12, "bold"), anchor="w")
        self.lbl_proc_status.grid(row=0, column=0, sticky="w", pady=3, padx=(0, 25))
        self.widgets["lbl_proc_status"] = self.lbl_proc_status

        self.lbl_log_time = tk.Label(grid_frame, text="最新日志心跳: 检测中...", font=("Helvetica", 12, "bold"), anchor="w")
        self.lbl_log_time.grid(row=0, column=1, sticky="w", pady=3)
        self.widgets["lbl_log_time"] = self.lbl_log_time

        # 当前阶段与排队位置
        self.lbl_node_phase = tk.Label(grid_frame, text="当前阶段: 检测中...", font=("Helvetica", 12, "bold"), anchor="w")
        self.lbl_node_phase.grid(row=1, column=0, sticky="w", pady=3, padx=(0, 25))
        self.widgets["lbl_node_phase"] = self.lbl_node_phase

        self.lbl_init_timer = tk.Label(grid_frame, text="排队状态: 🟢 检测排队中...", font=("Helvetica", 12, "bold"), fg="#16a34a", anchor="w")
        self.lbl_init_timer.grid(row=1, column=1, sticky="w", pady=3)
        self.widgets["lbl_init_timer"] = self.lbl_init_timer

        # 训练计算实时统计
        self.lbl_train_stats = tk.Label(grid_frame, text="训练计算统计: ⏳ 待机中 (等待全网各层握手对齐触发计算)", font=("Helvetica", 12, "bold"), fg="#4b5563", anchor="w")
        self.lbl_train_stats.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 2))
        self.widgets["lbl_train_stats"] = self.lbl_train_stats

        # 最近测速网速
        self.lbl_speed_info = tk.Label(grid_frame, text="最近测速网速: ⬆ 上传 检测中...  (⬇ 下载 检测中...)", font=("Helvetica", 12, "bold"), fg="#0284c7", anchor="w")
        self.lbl_speed_info.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 2))
        self.widgets["lbl_speed_info"] = self.lbl_speed_info

        # 4. 控制与工具栏
        ctrl_frame = tk.Frame(main_frame)
        ctrl_frame.pack(fill=tk.X, pady=(0, 8))
        self.widgets["ctrl_frame"] = ctrl_frame

        self.btn_toggle = ModernButton(ctrl_frame, text="⏸ 暂停自动守护", command=self.toggle_monitoring, font=("Helvetica", 11, "bold"), padx=10, pady=5)
        self.btn_toggle.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_restart = ModernButton(ctrl_frame, text="⚡ 手动强制重启 IOTA", command=self.manual_restart, bg_color="#dc2626", fg_color="#ffffff", hover_bg="#ef4444", font=("Helvetica", 11, "bold"), padx=12, pady=5)
        self.btn_restart.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_clean_reset = ModernButton(ctrl_frame, text="🧹 一键深度清理重置", command=self.confirm_deep_clean, bg_color="#b45309", fg_color="#ffffff", hover_bg="#d97706", font=("Helvetica", 11, "bold"), padx=11, pady=5)
        self.btn_clean_reset.pack(side=tk.LEFT, padx=(0, 10))

        self.chk_caffeinate = tk.Checkbutton(ctrl_frame, text="☕ 防休眠常开", variable=self.caffeinate_var, font=("Helvetica", 11, "bold"), command=self.toggle_caffeinate)
        self.chk_caffeinate.pack(side=tk.LEFT, padx=(4, 8))
        self.widgets["chk_caffeinate_ctrl"] = self.chk_caffeinate

        self.chk_key_only = tk.Checkbutton(ctrl_frame, text="只显核心事件", variable=self.filter_key_logs, font=("Helvetica", 11), command=self.on_filter_toggle)
        self.chk_key_only.pack(side=tk.LEFT, padx=(4, 6))
        self.widgets["chk_key_ctrl"] = self.chk_key_only

        self.chk_auto_scroll = tk.Checkbutton(ctrl_frame, text="自动滚屏", variable=self.auto_scroll_var, font=("Helvetica", 11), command=self.on_scroll_toggle)
        self.chk_auto_scroll.pack(side=tk.LEFT, padx=(4, 6))
        self.widgets["chk_scroll_ctrl"] = self.chk_auto_scroll

        self.btn_clear_log = ModernButton(ctrl_frame, text="清屏", command=self.clear_ui_log, font=("Helvetica", 11, "bold"), padx=8, pady=4)
        self.btn_clear_log.pack(side=tk.RIGHT, padx=(6, 0))

        font_frame = tk.Frame(ctrl_frame)
        font_frame.pack(side=tk.RIGHT, padx=(4, 0))
        self.widgets["font_ctrl_frame"] = font_frame

        self.btn_font_inc = ModernButton(font_frame, text="A+", command=lambda: self.change_font_size(1), font=("Helvetica", 11, "bold"), padx=8, pady=3)
        self.btn_font_inc.pack(side=tk.RIGHT, padx=(2, 0))

        self.lbl_font_display = tk.Label(font_frame, text=f"{self.log_font_size}pt", font=("Menlo", 11, "bold"))
        self.lbl_font_display.pack(side=tk.RIGHT, padx=(3, 3))
        self.widgets["lbl_font_display"] = self.lbl_font_display

        self.btn_font_dec = ModernButton(font_frame, text="A-", command=lambda: self.change_font_size(-1), font=("Helvetica", 11, "bold"), padx=8, pady=3)
        self.btn_font_dec.pack(side=tk.RIGHT, padx=(2, 2))

        lbl_font_tag = tk.Label(font_frame, text="字号:", font=("Helvetica", 11, "bold"))
        lbl_font_tag.pack(side=tk.RIGHT, padx=(0, 2))
        self.widgets["lbl_font_tag"] = lbl_font_tag

        # 参数配置栏
        cfg_frame = tk.Frame(main_frame, bd=1, relief="solid", padx=12, pady=6)
        cfg_frame.pack(fill=tk.X, pady=(0, 10))
        self.widgets["card_cfg"] = cfg_frame

        lbl_c2 = tk.Label(cfg_frame, text="彻底无日志假死判定 (分):", font=("Helvetica", 11, "bold"))
        lbl_c2.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["cfg_lbl_c2"] = lbl_c2

        self.entry_max_stale = tk.Entry(cfg_frame, width=5, bd=1, relief="solid", font=("Helvetica", 11, "bold"), justify="center")
        self.entry_max_stale.insert(0, str(self.config.get("max_stale_minutes", 10)))
        self.entry_max_stale.pack(side=tk.LEFT, padx=(0, 14), ipady=2)
        self.widgets["entry_max_stale"] = self.entry_max_stale

        lbl_c3 = tk.Label(cfg_frame, text="重启保护冷却 (分):", font=("Helvetica", 11, "bold"))
        lbl_c3.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["cfg_lbl_c3"] = lbl_c3

        self.entry_cooldown = tk.Entry(cfg_frame, width=5, bd=1, relief="solid", font=("Helvetica", 11, "bold"), justify="center")
        self.entry_cooldown.insert(0, str(self.config.get("cooldown_minutes", 3)))
        self.entry_cooldown.pack(side=tk.LEFT, padx=(0, 14), ipady=2)
        self.widgets["entry_cooldown"] = self.entry_cooldown

        self.btn_save = ModernButton(cfg_frame, text="💾 保存并应用参数", command=self.apply_config, bg_color="#059669", fg_color="#ffffff", hover_bg="#10b981", font=("Helvetica", 11, "bold"), padx=10, pady=3)
        self.btn_save.pack(side=tk.LEFT)

        # 5. 实时日志展示区域
        log_frame = tk.LabelFrame(main_frame, text=" 核心事件日志 (自动换行已开启) ", font=("Helvetica", 12, "bold"), padx=6, pady=6)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.widgets["card_log"] = log_frame

        self.txt_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=("Menlo", self.log_font_size), bd=0)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        self.txt_log.tag_config("SPEEDTEST", foreground="#38bdf8")
        self.txt_log.tag_config("REGISTER", foreground="#a78bfa")
        self.txt_log.tag_config("QUEUE", foreground="#fbbf24")
        self.txt_log.tag_config("TRAINING", foreground="#4ade80")
        self.txt_log.tag_config("UPLOAD", foreground="#2dd4bf")
        self.txt_log.tag_config("EARNINGS", foreground="#facc15")
        self.txt_log.tag_config("WARN", foreground="#fbbf24")
        self.txt_log.tag_config("ERROR", foreground="#f87171")
        self.txt_log.tag_config("WATCHDOG", foreground="#f472b6")
        self.txt_log.tag_config("CLEANUP", foreground="#fb923c")
        self.txt_log.tag_config("NORMAL", foreground="#cbd5e1")

        self.append_watchdog_log("🚀 控制台已就绪！已开启实时排队位置探测与训练启动监控。")

    def on_filter_toggle(self):
        self.config["filter_key_logs_only"] = self.filter_key_logs.get()
        save_config(self.config)

    def on_scroll_toggle(self):
        self.config["auto_scroll"] = self.auto_scroll_var.get()
        save_config(self.config)

    def append_watchdog_log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] [WATCHDOG] {msg}\n"
        self._insert_text(line, "WATCHDOG")

    def update_miner_info_ui(self):
        def _update():
            if self.miner_hotkey and self.miner_hotkey != "检测中...":
                self.entry_miner_id.config(state="normal")
                self.entry_miner_id.delete(0, tk.END)
                self.entry_miner_id.insert(0, self.miner_hotkey)
                self.entry_miner_id.config(state="readonly")

            if self.payout_coldkey and self.payout_coldkey != "检测中...":
                self.entry_coldkey.config(state="normal")
                self.entry_coldkey.delete(0, tk.END)
                self.entry_coldkey.insert(0, self.payout_coldkey)
                self.entry_coldkey.config(state="readonly")

            if self.current_layer and self.current_layer != "检测中...":
                self.lbl_layer.config(text=f"连接 Layer: {self.current_layer}")
            if self.current_run_id and self.current_run_id != "检测中...":
                self.lbl_run_id.config(text=f"Run ID: {self.current_run_id}")
            if self.current_epoch and self.current_epoch != "检测中...":
                self.lbl_epoch.config(text=f"Epoch: {self.current_epoch}")

        self.root.after(0, _update)

    def is_key_event(self, line):
        for p in IGNORED_PATTERNS:
            if p in line:
                return False
        for k in KEY_LOG_KEYWORDS:
            if k in line:
                return True
        return False

    def classify_and_append(self, line):
        line_clean = line.rstrip()
        if not line_clean:
            return

        # 提取 Hotkey
        if "hotkey" in line_clean.lower() or "5" in line_clean:
            hk_match = re.search(r"5[0-9A-Za-z]{47}", line_clean)
            if hk_match:
                found_key = hk_match.group(0)
                if not self.miner_hotkey or self.miner_hotkey == "检测中...":
                    self.miner_hotkey = found_key
                    self.update_miner_info_ui()

        # 提取实时测速
        if "Speedtest completed with results:" in line_clean:
            try:
                m = re.search(r"Speedtest completed with results:\s*(\{.*?\})", line_clean)
                if m:
                    data = json.loads(m.group(1).replace("'", '"'))
                    up = data.get("upload_mbps")
                    down = data.get("download_mbps")
                    if up is not None and down is not None:
                        self.last_upload_speed = f"{up:.1f} Mbps"
                        self.last_download_speed = f"{down:.1f} Mbps"
                        self.update_speed_ui()
            except Exception:
                pass

        # 提取排队位置与注册队列状态 (例: 'status': 'queued', 'position': 1140)
        if "position" in line_clean and ("queued" in line_clean or "register" in line_clean or "status" in line_clean):
            pos_m = re.search(r"['\"]position['\"]\s*:\s*([0-9]+)", line_clean)
            if pos_m:
                new_pos = int(pos_m.group(1))
                if self.last_queue_position is not None and self.last_queue_position != new_pos:
                    self.prev_queue_position = self.last_queue_position
                self.last_queue_position = new_pos

                qid_m = re.search(r"['\"]queue_id['\"]\s*:\s*['\"]([^'\"]+)['\"]", line_clean)
                if qid_m:
                    self.queue_id = qid_m.group(1)

                if self.queue_start_time is None:
                    self.queue_start_time = time.time()
                wait_mins = (time.time() - self.queue_start_time) / 60

                # 实时刷新 UI 看板
                def _update_q(w=wait_mins):
                    self.lbl_node_phase.config(text=f"当前阶段: 🟡 队列排队中 ({self.current_layer})", fg="#d97706" if not self.dark_mode else "#fbbf24")
                    self.lbl_init_timer.config(text=self.get_queue_status_text(w), fg="#d97706" if not self.dark_mode else "#fbbf24")
                self.root.after(0, _update_q)

        # 提取活跃邻居数与广播状态
        if "Broadcast peer status:" in line_clean:
            m = re.search(r"Broadcast peer status:\s*(\d+/\d+)\s*ok", line_clean)
            if m:
                self.peer_mesh_status = f"{m.group(1)} 在线"

        if "Peer status dict has" in line_clean:
            m = re.search(r"Peer status dict has (\d+) entries", line_clean)
            if m:
                self.active_peers_count = f"{m.group(1)} 个"
                now = time.time()
                if now - self.last_peer_log_time > 60:
                    self.last_peer_log_time = now
                    self._insert_text(f"[{datetime.now().strftime('%H:%M:%S')}] 📡 [P2P 握手] 当前 {self.current_layer} 已连接 {m.group(1)} 个活跃邻居节点 ({self.peer_mesh_status})\n", "SPEEDTEST")

        # 提取全网层就绪状态
        if "request to /miner/all_layers_training" in line_clean:
            m = re.search(r"response:\s*(True|False)", line_clean)
            if m:
                self.all_layers_ready = "已就绪 (True)" if m.group(1) == "True" else "等待各层中 (False)"

        # 提取心跳与状态迁移
        if "request to /miner/heartbeat" in line_clean and "response:" in line_clean:
            hb_m = re.search(r"response:\s*({.*?status.*?})", line_clean)
            if hb_m:
                try:
                    hb_data = eval(hb_m.group(1))
                    status = hb_data.get("status", "")
                    layer = hb_data.get("layer")
                    epoch = hb_data.get("epoch")
                    run_id = hb_data.get("run_id")
                    if layer is not None:
                        self.current_layer = f"Layer {layer}"
                    if epoch is not None:
                        self.current_epoch = f"Epoch {epoch}"
                    if run_id:
                        self.current_run_id = run_id
                    self.update_miner_info_ui()

                    if status == "initializing":
                        if self.queue_start_time is None:
                            self.queue_start_time = time.time()
                        self.last_status = "initializing"
                        now = time.time()
                        if now - self.last_queue_heartbeat_log_time > 60:
                            self.last_queue_heartbeat_log_time = now
                            mins = (now - self.queue_start_time) / 60
                            pos_str = f"当前排位: 第 {self.last_queue_position} 位 | " if self.last_queue_position is not None else ""
                            self._insert_text(f"[{datetime.now().strftime('%H:%M:%S')}] ⏳ [排队心跳] {self.current_layer} 排队就绪保持中 ({pos_str}已等待 {mins:.1f} 分钟 | P2P 邻居: {self.active_peers_count})\n", "QUEUE")
                    elif status in ["training", "idle", "running"]:
                        if self.last_status == "initializing" or not self.is_actively_training:
                            self.is_actively_training = True
                            self.queue_start_time = None
                            self._insert_text(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🚀🚀🚀 [正式训练已开启] 全网各层已就绪！本机正式进入分布式训练计算 (Epoch: {self.current_epoch}) 🚀🚀🚀\n\n", "TRAINING")
                        self.last_status = status
                except Exception:
                    pass

        # 统计 Forward / Backward
        if "FORWARD complete" in line_clean or "Forward pass" in line_clean:
            self.forward_count += 1
            if not self.is_actively_training:
                self.is_actively_training = True
                self.queue_start_time = None
                self._insert_text(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🚀🚀🚀 [正式训练已开启] 收到激活数据并完成 Forward 计算！ 🚀🚀🚀\n\n", "TRAINING")
            self.root.after(0, lambda: self.lbl_train_stats.config(text=f"训练计算统计: 🔥 正在计算中！(已完成 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次)", fg="#15803d" if not self.dark_mode else "#4ade80"))
        elif "BACKWARD complete" in line_clean or "Backward pass" in line_clean:
            self.backward_count += 1
            if not self.is_actively_training:
                self.is_actively_training = True
                self.queue_start_time = None
                self._insert_text(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🚀🚀🚀 [正式训练已开启] 完成 Backward 反向传播梯度计算！ 🚀🚀🚀\n\n", "TRAINING")
            self.root.after(0, lambda: self.lbl_train_stats.config(text=f"训练计算统计: 🔥 正在计算中！(已完成 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次)", fg="#15803d" if not self.dark_mode else "#4ade80"))

        tag = "NORMAL"
        if "position" in line_clean.lower() or "queued" in line_clean.lower():
            tag = "QUEUE"
        elif "speedtest" in line_clean.lower() or "latency" in line_clean:
            tag = "SPEEDTEST"
        elif "register" in line_clean or "attestation" in line_clean or "reset_miner_state" in line_clean:
            tag = "REGISTER"
        elif "training" in line_clean or "Loading model weights" in line_clean or "epoch" in line_clean or "step" in line_clean or "FORWARD" in line_clean or "BACKWARD" in line_clean:
            tag = "TRAINING"
        elif "upload" in line_clean or "gradient" in line_clean or "flush" in line_clean or "sync" in line_clean:
            tag = "UPLOAD"
        elif "earning" in line_clean or "reward" in line_clean or "payout" in line_clean or "incentive" in line_clean:
            tag = "EARNINGS"
        elif "ERROR" in line_clean or "500 - Internal Server Error" in line_clean:
            tag = "ERROR"
        elif "WARNING" in line_clean:
            tag = "WARN"

        self._insert_text(line_clean + "\n", tag)

    def _insert_text(self, text, tag):
        def _do():
            self.txt_log.insert(tk.END, text, tag)
            if self.auto_scroll_var.get():
                self.txt_log.see(tk.END)
        self.root.after(0, _do)

    def clear_ui_log(self):
        self.txt_log.delete("1.0", tk.END)

    def apply_config(self):
        try:
            self.config["max_stale_minutes"] = max(2, int(self.entry_max_stale.get().strip()))
            self.config["cooldown_minutes"] = max(1, int(self.entry_cooldown.get().strip()))
            save_config(self.config)
            self.append_watchdog_log(f"✅ 参数已保存: 无日志假死判定 {self.config['max_stale_minutes']}分 | 重启冷却 {self.config['cooldown_minutes']}分")
            messagebox.showinfo("成功", "配置已成功保存！")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的正整数！")

    def toggle_monitoring(self):
        self.is_monitoring = not self.is_monitoring
        self.config["auto_watchdog_enabled"] = self.is_monitoring
        save_config(self.config)
        if self.is_monitoring:
            self.lbl_watchdog_status.config(text="● 自动守护中", fg="#16a34a")
            self.btn_toggle.config(text="⏸ 暂停自动守护")
            self.append_watchdog_log("▶ 自动守护已恢复。")
        else:
            self.lbl_watchdog_status.config(text="⏸ 自动监控已暂停", fg="#d97706")
            self.btn_toggle.config(text="▶ 恢复自动监控")
            self.append_watchdog_log("⏸ 自动守护已暂停（仅手动操作）。")

    def get_latest_log(self):
        files = glob.glob(os.path.join(LOG_DIR, "*[0-9]-cli.log"))
        if not files:
            return None
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return files[0]

    def extract_process_info(self):
        try:
            out = subprocess.check_output(["ps", "aux"]).decode()
            for line in out.splitlines():
                if "main_pool:ai.macrocosmos.iota.tah.worker" in line:
                    coldkey_match = re.search(r"--payout-coldkey\s+([0-9A-Za-z]+)", line)
                    if coldkey_match:
                        self.payout_coldkey = coldkey_match.group(1)
                        self.update_miner_info_ui()
                    break
        except Exception:
            pass

    def check_process(self):
        try:
            out = subprocess.check_output(["pgrep", "-f", "IOTA Train at Home"]).decode().strip()
            pids = out.splitlines()
            return True, f"正常运行中 (PID: {pids[0]})"
        except subprocess.CalledProcessError:
            return False, "未运行"

    def log_stream_loop(self):
        self.extract_process_info()

        while self.running:
            try:
                latest_log = self.get_latest_log()
                if latest_log:
                    if latest_log != self.current_log_file:
                        self.current_log_file = latest_log
                        try:
                            with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
                                all_lines = f.readlines()
                                initial_lines = all_lines[-60:]
                                for l in initial_lines:
                                    if not self.filter_key_logs.get() or self.is_key_event(l):
                                        self.classify_and_append(l)
                                self.log_file_pos = f.tell()
                        except Exception:
                            self.log_file_pos = 0

                    if os.path.exists(self.current_log_file):
                        file_size = os.path.getsize(self.current_log_file)
                        if file_size < self.log_file_pos:
                            self.log_file_pos = 0

                        with open(self.current_log_file, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(self.log_file_pos)
                            new_lines = f.readlines()
                            self.log_file_pos = f.tell()

                            for line in new_lines:
                                if not self.filter_key_logs.get() or self.is_key_event(line):
                                    self.classify_and_append(line)

            except Exception:
                pass

            time.sleep(0.8)

    def monitor_loop(self):
        while self.running:
            try:
                now_ts = time.time()
                proc_running, proc_text = self.check_process()

                if proc_running:
                    self.root.after(0, lambda: self.lbl_proc_status.config(text=f"进程状态: 🟢 {proc_text}", fg="#15803d" if not self.dark_mode else "#4ade80"))
                else:
                    self.root.after(0, lambda: self.lbl_proc_status.config(text=f"进程状态: 🔴 {proc_text}", fg="#dc2626" if not self.dark_mode else "#f87171"))

                in_cooldown = (now_ts - self.last_restart_time) < (self.config["cooldown_minutes"] * 60)
                if in_cooldown:
                    remain = int((self.config["cooldown_minutes"] * 60) - (now_ts - self.last_restart_time))
                    self.root.after(0, lambda r=remain: self.lbl_init_timer.config(text=f"排队状态: 启动保护中 (剩余 {r}s)", fg="#2563eb" if not self.dark_mode else "#38bdf8"))
                    time.sleep(self.config.get("check_interval_seconds", 15))
                    continue

                if not proc_running and self.is_monitoring:
                    self.append_watchdog_log("检测到 IOTA 进程未运行，自动重新拉起...")
                    self._do_restart(is_manual=False)
                    time.sleep(self.config.get("check_interval_seconds", 15))
                    continue

                latest_log = self.get_latest_log()
                if not latest_log:
                    self.root.after(0, lambda: self.lbl_node_phase.config(text="当前阶段: 未找到日志", fg="#6b7280"))
                    time.sleep(self.config.get("check_interval_seconds", 15))
                    continue

                mtime = os.path.getmtime(latest_log)
                stale_sec = now_ts - mtime
                log_time_str = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
                self.root.after(0, lambda s=stale_sec, t=log_time_str: self.lbl_log_time.config(text=f"最新日志心跳: {t} ({int(s)}秒前)"))

                # 假死检测（无任何日志输出）
                if stale_sec > self.config["max_stale_minutes"] * 60:
                    self.root.after(0, lambda: self.lbl_node_phase.config(text="当前阶段: ❌ 日志超时无写入 (假死)", fg="#dc2626"))
                    self.root.after(0, lambda: self.lbl_init_timer.config(text="排队状态: 🔴 进程假死无响应", fg="#dc2626"))
                    if self.is_monitoring:
                        self.append_watchdog_log(f"❌ 判定假死: 日志已超过 {int(stale_sec//60)} 分钟无任何输出，执行重启恢复！")
                        self._do_restart(is_manual=False)
                        time.sleep(self.config.get("check_interval_seconds", 15))
                        continue

                try:
                    with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[-150:]
                except Exception:
                    lines = []

                heartbeat_lines = []
                hb_pattern = re.compile(r"response:\s*({.*?status.*?})")
                for line in lines:
                    m = hb_pattern.search(line)
                    if m:
                        heartbeat_lines.append(m.group(1))

                if heartbeat_lines:
                    latest_hb_str = heartbeat_lines[-1]
                    try:
                        run_id_m = re.search(r"['\"]run_id['\"]\s*:\s*['\"]([^'\"]+)['\"]", latest_hb_str)
                        if run_id_m:
                            self.current_run_id = run_id_m.group(1)

                        layer_m = re.search(r"['\"]layer['\"]\s*:\s*([0-9]+)", latest_hb_str)
                        if layer_m:
                            self.current_layer = f"Layer {layer_m.group(1)}"

                        epoch_m = re.search(r"['\"]epoch['\"]\s*:\s*([0-9]+)", latest_hb_str)
                        if epoch_m:
                            self.current_epoch = f"Epoch {epoch_m.group(1)}"

                        phase_m = re.search(r"['\"]phase['\"]\s*:\s*['\"]([^'\"]+)['\"]", latest_hb_str)
                        if phase_m:
                            self.current_phase = phase_m.group(1)

                        self.update_miner_info_ui()
                    except Exception:
                        pass

                    # 计算排队等待时长
                    mesh_str = f"P2P 网格: {self.peer_mesh_status}" if self.peer_mesh_status != "检测中..." else f"邻居 {self.active_peers_count}"

                    if "'status': 'initializing'" in latest_hb_str or '"status": "initializing"' in latest_hb_str:
                        if self.queue_start_time is None:
                            self.queue_start_time = time.time()
                        wait_mins = (time.time() - self.queue_start_time) / 60
                        
                        self.root.after(0, lambda m=mesh_str: self.lbl_node_phase.config(text=f"当前阶段: 🟡 队列握手中 ({self.current_layer} | {m})", fg="#d97706" if not self.dark_mode else "#fbbf24"))
                        self.root.after(0, lambda w=wait_mins: self.lbl_init_timer.config(text=self.get_queue_status_text(w), fg="#d97706" if not self.dark_mode else "#fbbf24"))
                        
                        if not self.is_actively_training:
                            self.root.after(0, lambda: self.lbl_train_stats.config(text="训练计算统计: ⏳ 待机排队中 (等待全网各层握手对齐后自动触发训练)", fg="#64748b" if not self.dark_mode else "#94a3b8"))
                    else:
                        # 正式进入训练
                        self.queue_start_time = None
                        self.root.after(0, lambda: self.lbl_node_phase.config(text=f"当前阶段: 🚀 正式训练中 ({self.current_layer} | {self.current_epoch})", fg="#15803d" if not self.dark_mode else "#4ade80"))
                        self.root.after(0, lambda: self.lbl_init_timer.config(text="排队状态: 🔥 训练已正式开始 (已脱离排队，持续产出算力！)", fg="#15803d" if not self.dark_mode else "#4ade80"))
                        self.root.after(0, lambda: self.lbl_train_stats.config(text=f"训练计算统计: 🔥 算力全开计算中！(Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次)", fg="#15803d" if not self.dark_mode else "#4ade80"))
                else:
                    self.root.after(0, lambda: self.lbl_node_phase.config(text=f"当前阶段: 🟢 活跃通信中 ({self.current_layer})", fg="#15803d" if not self.dark_mode else "#4ade80"))
                    if self.last_queue_position is not None and not self.is_actively_training:
                        wait_mins = (time.time() - self.queue_start_time) / 60 if self.queue_start_time else 0.0
                        self.root.after(0, lambda w=wait_mins: self.lbl_init_timer.config(text=self.get_queue_status_text(w), fg="#d97706" if not self.dark_mode else "#fbbf24"))
                    else:
                        self.root.after(0, lambda: self.lbl_init_timer.config(text="排队状态: 🟢 通信正常保持中", fg="#15803d" if not self.dark_mode else "#4ade80"))

            except Exception:
                pass

            time.sleep(self.config.get("check_interval_seconds", 15))

if __name__ == "__main__":
    root = tk.Tk()
    app = IotaWatchdogApp(root)
    root.mainloop()
