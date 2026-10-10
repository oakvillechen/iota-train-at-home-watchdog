#!/usr/bin/env python3
import os
import sys

# 确保 bundle 目录与当前源码目录在模块检索路径中
_base_dir = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(sys.executable)
    _res_dir = os.path.normpath(os.path.join(_exe_dir, "..", "Resources"))
    for _d in [_exe_dir, _res_dir, getattr(sys, "_MEIPASS", "")]:
        if _d and os.path.exists(_d) and _d not in sys.path:
            sys.path.insert(0, _d)
elif _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

import time
import glob
import subprocess
import re
import json
import threading
import webbrowser
import ssl
from datetime import datetime, timedelta

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

try:
    import iota_cluster_sync
except Exception as e:
    print(f"Warning: Failed to import iota_cluster_sync initially: {e}", file=sys.stderr)
    iota_cluster_sync = None

try:
    import updater
except Exception:
    updater = None

try:
    import tkinter as tk
    import tkinter.font as tkFont
    from tkinter import messagebox, scrolledtext
except ModuleNotFoundError:
    for alt_py in ["/usr/local/bin/python3", "/usr/bin/python3"]:
        if os.path.exists(alt_py):
            os.execv(alt_py, [alt_py] + sys.argv)
    raise

APP_VERSION = "1.6.6"
LOG_DIR = os.path.expanduser("~/Library/Logs/IOTA Train at Home")
CONFIG_FILE = os.path.join(LOG_DIR, "watchdog_config.json")
APP_NAME = "IOTA Train at Home"
SYS_APP_PATH = "/Applications/IOTA Train at Home.app"
USER_APP_PATH = os.path.expanduser("~/Applications/IOTA Train at Home.app")

DEFAULT_CONFIG = {
    "max_stale_minutes": 10,
    "cooldown_minutes": 3,
    "check_interval_seconds": 15,
    "auto_watchdog_enabled": True,
    "filter_key_logs_only": True,
    "auto_scroll": True,
    "dark_mode": False,
    "ui_theme": "light",
    "ui_font_scale": 85,
    "auto_check_update": True,
    "skipped_version": "",
    "caffeinate_enabled": True,
    "log_font_size": 12,
    "log_retention_days": 2,
    "zombie_stale_hours": 2,
    "restart_timestamps": [],
    "last_upload_speed": "",
    "last_download_speed": "",
    "cloud_sync_enabled": False,
    "github_token": "",
    "github_repo": "oakvillechen/iota-train-at-home-watchdog",
    "github_branch": "main",
    "worker_id": "",
    "worker_name": "",
    "cloud_sync_interval_seconds": 60
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
    "Failed to send", "Peer unreachable", "unreachable", "dropping",
    "submit_activation", "submit_weights", "position", "queued", "queue_id",
    "/miner/register/status", "orchestrator", "No activations received",
    "Received activations", "Cache size", "cache size of"
]

try:
    import theme
    THEMES = theme.THEMES
except Exception:
    THEMES = {
        "light": {
            "bg_root": "#F4F6FA", "bg_card": "#FFFFFF", "bg_subcard": "#F8FAFC", "border": "#E6E9F0",
            "fg_title": "#141A26", "fg_text": "#141A26", "fg_muted": "#5A6577",
            "entry_bg": "#FFFFFF", "entry_fg": "#4F46E5",
            "btn_neutral_bg": "#ECEEFE", "btn_neutral_hover": "#E0E3FA", "btn_neutral_fg": "#4F46E5",
            "btn_exit_bg": "#E02424", "btn_exit_hover": "#C81E1E",
            "log_bg": "#FFFFFF", "log_fg": "#141A26"
        },
        "dark": {
            "bg_root": "#0B0D13", "bg_card": "#12151F", "bg_subcard": "#171B26", "border": "#222839",
            "fg_title": "#EDEFF5", "fg_text": "#EDEFF5", "fg_muted": "#9AA3B5",
            "entry_bg": "#12151F", "entry_fg": "#8B93F8",
            "btn_neutral_bg": "#222839", "btn_neutral_hover": "#2E374D", "btn_neutral_fg": "#EDEFF5",
            "btn_exit_bg": "#DC2626", "btn_exit_hover": "#EF4444",
            "log_bg": "#07090E", "log_fg": "#E2E8F0"
        },
        "midnight-neon": {
            "bg_root": "#040711", "bg_card": "#080D1A", "bg_subcard": "#070B16", "border": "#00F2FE",
            "fg_title": "#00F2FE", "fg_text": "#E2E8F0", "fg_muted": "#94A3B8",
            "entry_bg": "#050811", "entry_fg": "#00F2FE",
            "btn_neutral_bg": "#0E1A2E", "btn_neutral_hover": "#172A4B", "btn_neutral_fg": "#00F2FE",
            "btn_exit_bg": "#FF0055", "btn_exit_hover": "#FF3377",
            "log_bg": "#03060F", "log_fg": "#00F2FE"
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

def format_size(size_bytes):
    """将字节数格式化为人类可读的字符串"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

class ModernButton(tk.Label):
    def __init__(self, parent, text, command=None, bg_color="#2d3d54", fg_color="#f8fafc", hover_bg="#3b506e", font=None, padx=10, pady=4, **kwargs):
        btn_font = font or ("Helvetica", 10, "bold")
        super().__init__(parent, text=text, bg=bg_color, fg=fg_color, font=btn_font, padx=padx, pady=pady, relief="solid", bd=1, cursor="pointinghand", **kwargs)
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
        self.app_version = updater.get_local_version(fallback=APP_VERSION) if updater else APP_VERSION
        self.root.title(f"IOTA Watchdog v{self.app_version} - Train at Home 智能监控控制台")
        self.root.geometry("1080x880")
        self.root.minsize(920, 720)

        # 尝试加载自定义图标
        try:
            icon_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
            if os.path.exists(icon_p):
                self._app_icon = tk.PhotoImage(file=icon_p)
                self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass

        self.config = load_config()
        self.dark_mode = self.config.get("dark_mode", True)
        self.log_font_size = self.config.get("log_font_size", 12)
        self.ui_font_scale = int(self.config.get("ui_font_scale", 85))
        self.setup_fonts()
        self.log_retention_days = self.config.get("log_retention_days", 2)
        self.caffeinate_proc = None
        self.last_log_cleanup_time = 0
        self.is_restarting = False

        # 实时网络吞吐与资产估值状态
        self.live_down_str = "0.0 KB/s"
        self.live_up_str = "0.0 KB/s"
        self.sn9_usd_price = 0.0
        self.tao_usd_price = 0.0
        self.total_earned_val = 0.0
        self.total_paid_val = 0.0
        self.total_pending_val = 0.0

        # UI 交互状态
        self.cfg_expanded = False
        self.user_scrolled_away = False

        self.is_monitoring = self.config.get("auto_watchdog_enabled", True)
        self.filter_key_logs = tk.BooleanVar(value=self.config.get("filter_key_logs_only", True))
        self.auto_scroll_var = tk.BooleanVar(value=self.config.get("auto_scroll", True))
        self.caffeinate_var = tk.BooleanVar(value=self.config.get("caffeinate_enabled", True))
        
        self.last_restart_time = 0
        self.current_log_file = None
        self.log_file_pos = 0

        # 排队与状态统计数据
        self.miner_hotkey = "检测中..."
        hk_file = os.path.expanduser("~/.bittensor/wallets/iota/hotkeys/iota_miner")
        if os.path.exists(hk_file):
            try:
                with open(hk_file, "r") as f:
                    hk_data = json.load(f)
                    if "ss58Address" in hk_data:
                        self.miner_hotkey = hk_data["ss58Address"]
            except Exception:
                pass

        # 确立并持久化 Miner ID 作为永久唯一身份
        actual_wid = self.get_worker_identity()
        old_wid = self.config.get("worker_id", "")
        if old_wid != actual_wid:
            self.config["worker_id"] = actual_wid
            save_config(self.config)
            if old_wid and old_wid.startswith("node-") and actual_wid.startswith("miner-"):
                def _cleanup_old_file():
                    try:
                        time.sleep(3)
                        global iota_cluster_sync
                        if iota_cluster_sync and hasattr(iota_cluster_sync, "delete_worker_file"):
                            iota_cluster_sync.delete_worker_file(self.config, old_wid)
                    except Exception:
                        pass
                threading.Thread(target=_cleanup_old_file, daemon=True).start()
        self.payout_coldkey = "检测中..."
        self.current_layer = "检测中..."
        self.current_network = "IOTA Bittensor Subnet"
        self.current_run_id = "检测中..."
        self.current_epoch = "检测中..."
        self.current_phase = "检测中..."
        self.last_status = "检测中..."
        self.last_upload_speed = self.config.get("last_upload_speed") or "检测中..."
        self.last_download_speed = self.config.get("last_download_speed") or "检测中..."
        self.active_peers_count = "检测中..."
        self.peer_mesh_status = "检测中..."
        self.all_layers_ready = "未知"
        
        # P2P 广播与激活丢弃告警监测
        self.p2p_recent_drops = []
        self.p2p_total_drops = 0
        self.p2p_last_unreachable = 0
        self.p2p_last_total_peers = 0
        self.p2p_last_ok_peers = 0
        self.p2p_health_level = "GREEN"
        self.p2p_last_broadcast_time = 0
        self.last_speedtest_time = ""
        self.coldkey_visible = False
        self.last_payout_fetch_time = 0
        
        self.queue_start_time = None
        self.prev_queue_position = None
        self.last_queue_position = None
        self.queue_id = "检测中..."
        self.forward_count = 0
        self.backward_count = 0
        self.is_actively_training = False
        self.last_peer_log_time = 0
        self.last_queue_heartbeat_log_time = 0

        # v1.4.0 链上状态、排名与僵尸状态检测 (P0)
        self.is_zombie = False
        self.zombie_flat_hours = 0.0
        self.zombie_net_growth = 0
        self.zombie_alert_text = ""
        self.chain_data_available = True
        self.chain_token_count = 0
        self.chain_network_tokens = 0
        self.chain_network_growth_2h = 0
        self.chain_rank = None
        self.chain_num_miners = None
        self.chain_contribution_perc = None
        self.next_payout_ts = None
        self.current_window_tokens = 0.0

        # v1.4.0 Orchestrator 与 Cache 状态 (P1)
        self.orchestrator_status = "检测中..."
        self.last_cache_size = None
        self.last_cache_max = 16
        self.all_layers_training_bool = None
        self.last_activation_time = time.time()

        # v1.4.0 Epoch 感知与防频繁重启 (P2)
        self.current_epoch_num = None
        self.epoch_start_time = None
        self.last_activation_epoch = None
        self.restart_timestamps = self.config.get("restart_timestamps", [])

        # 云端多机上报状态 (Cyber Dashboard)
        self.last_log_line = ""
        self.last_6h_total_str = ""
        self.cur_cycle_tokens_str = ""
        self.last_cloud_sync_time = 0
        self.last_cloud_sync_msg = "未初始化"
        self.recent_hourly_tokens = []
        self.last_payout_info = {}
        self.next_payout_info = {}
        self.pending_update_info = None

        self.widgets = {}

        # 启动时立即尝试提取 Hotkey / Coldkey
        self.extract_process_info()

        self.setup_ui()
        self.apply_theme()

        if self.caffeinate_var.get():
            self.start_caffeinate()

        self.running = True
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

        # macOS: 修复最小化后点击 Dock 图标无法恢复窗口的问题
        self.root.bind("<Activate>", self._on_activate)
        self.root.createcommand("::tk::mac::ReopenApplication", self._on_reopen)

        # 延迟到 mainloop 启动后再执行后台线程，避免 macOS Tkinter 报 main thread is not in main loop
        self.root.after(100, self.start_background_tasks)

    def _on_activate(self, event=None):
        """macOS: 窗口被激活时确保从最小化状态恢复"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _on_reopen(self):
        """macOS: 点击 Dock 图标时恢复窗口（::tk::mac::ReopenApplication）"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def start_background_tasks(self):
        self.append_watchdog_log("🚀 IOTA Train at Home 智能监控控制台已就绪，正在同步运行状态与日志流...")
        self.load_initial_stats()
        threading.Thread(target=self.cleanup_old_logs, daemon=True).start()
        self.stream_thread = threading.Thread(target=self.log_stream_loop, daemon=True)
        self.stream_thread.start()
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        threading.Thread(target=self._cloud_sync_loop, daemon=True).start()
        threading.Thread(target=self._live_net_speed_loop, daemon=True).start()
        self.root.after(500, lambda: self.trigger_fetch_payout(manual=False))
        self.root.after(1000, self._tick_countdown)
        if self.config.get("auto_check_update", True):
            self.root.after(2000, lambda: threading.Thread(target=lambda: self._check_update_worker(manual=False), daemon=True).start())

    def _live_net_speed_loop(self):
        """后台实时测量 IOTA 所在本地机器的网络实时传输吞吐 (上传/下载速率)"""
        def get_interface_bytes():
            try:
                out = subprocess.check_output(["netstat", "-ibn"], stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
                in_b = 0
                out_b = 0
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 10 and parts[0].startswith("en") and "<Link#" in parts[2]:
                        try:
                            in_b += int(parts[6])
                            out_b += int(parts[9])
                        except ValueError:
                            pass
                return in_b, out_b
            except Exception:
                return 0, 0

        last_in, last_out = get_interface_bytes()
        last_t = time.time()

        while getattr(self, "running", True):
            time.sleep(1.5)
            now_t = time.time()
            cur_in, cur_out = get_interface_bytes()
            dt = max(0.5, now_t - last_t)

            delta_in = max(0, cur_in - last_in)
            delta_out = max(0, cur_out - last_out)

            rate_in = delta_in / dt
            rate_out = delta_out / dt

            def fmt_bps(bps):
                if bps >= 1024 * 1024:
                    return f"{bps / (1024 * 1024):.2f} MB/s"
                elif bps >= 1024:
                    return f"{bps / 1024:.1f} KB/s"
                else:
                    return f"{bps:.0f} B/s"

            self.live_down_str = fmt_bps(rate_in)
            self.live_up_str = fmt_bps(rate_out)
            last_in = cur_in
            last_out = cur_out
            last_t = now_t

            self.root.after(0, self.update_live_net_ui)

    def update_live_net_ui(self):
        txt = f"⬇ {self.live_down_str}   ⬆ {self.live_up_str}"
        if hasattr(self, "lbl_kpi_net_val"):
            self.lbl_kpi_net_val.config(text=txt)
        if hasattr(self, "lbl_speed_live"):
            self.lbl_speed_live.config(text=f"本地实时流量: ⬇ {self.live_down_str}  ⬆ {self.live_up_str}")

    def _shorten_id(self, key_str):
        if not key_str or "检测中" in key_str or len(key_str) < 14:
            return key_str
        return f"{key_str[:6]}...{key_str[-4:]}"

    def update_kpi_cards(self):
        """同步更新顶栏 4 大核心 KPI 指示卡片"""
        # Card 1: 节点状态
        if hasattr(self, "lbl_kpi_status_val"):
            proc_running, _ = self.check_process()
            if not proc_running:
                st_txt = "🔴 进程未运行"
                st_fg = "#dc2626" if not self.dark_mode else "#f87171"
            elif self.is_actively_training:
                st_txt = "🟢 正式训练中"
                st_fg = "#16a34a" if not self.dark_mode else "#4ade80"
            elif self.last_queue_position is not None and self.last_queue_position > 0:
                st_txt = f"🟡 队列第 {self.last_queue_position} 位"
                st_fg = "#d97706" if not self.dark_mode else "#fbbf24"
            else:
                st_txt = "🟢 节点通信中"
                st_fg = "#16a34a" if not self.dark_mode else "#4ade80"
            self.lbl_kpi_status_val.config(text=st_txt, fg=st_fg)

            layer_info = self.current_layer if "检测" not in self.current_layer else "--"
            ep_info = self.current_epoch if "检测" not in self.current_epoch else "--"
            sub_txt = f"{layer_info} · {ep_info}"
            if hasattr(self, "lbl_kpi_status_sub"):
                self.lbl_kpi_status_sub.config(text=sub_txt)

        # Card 2: 算力产出
        if hasattr(self, "lbl_kpi_compute_val"):
            self.lbl_kpi_compute_val.config(text=f"Fwd: {self.forward_count} · Bwd: {self.backward_count}")
            chain_wan = self.chain_token_count / 10000.0 if getattr(self, "chain_token_count", 0) else 0.0
            rank_txt = f"全网第 {self.chain_rank} 名" if getattr(self, "chain_rank", None) else "排名同步中"
            if hasattr(self, "lbl_kpi_compute_sub"):
                self.lbl_kpi_compute_sub.config(text=f"链上: {chain_wan:,.2f}万 · {rank_txt}")

        # Card 3: 实时网络与测速
        if hasattr(self, "lbl_kpi_net_val"):
            self.lbl_kpi_net_val.config(text=f"⬇ {self.live_down_str}   ⬆ {self.live_up_str}")
            down_sp = self.last_download_speed if self.last_download_speed != "检测中..." else "--"
            up_sp = self.last_upload_speed if self.last_upload_speed != "检测中..." else "--"
            if hasattr(self, "lbl_kpi_net_sub"):
                self.lbl_kpi_net_sub.config(text=f"测速 ⬇{down_sp} ⬆{up_sp} | 网格 {self.peer_mesh_status}")

        # Card 4: 收益账单估值
        if hasattr(self, "lbl_kpi_earn_val"):
            earned = getattr(self, "total_earned_val", 0.0)
            self.lbl_kpi_earn_val.config(text=f"{earned:.3f} IOTA")
            price = getattr(self, "sn9_usd_price", getattr(self, "tao_usd_price", 0.0))
            if hasattr(self, "lbl_kpi_earn_sub"):
                if price > 0:
                    self.lbl_kpi_earn_sub.config(text=f"≈ ${earned * price:,.2f} USD (按 ${price:,.2f}/IOTA)")
                else:
                    paid = getattr(self, "total_paid_val", 0.0)
                    self.lbl_kpi_earn_sub.config(text=f"已到账: {paid:.3f} IOTA")

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
                    lines = content.splitlines()[-200:]
                    now_ts = time.time()

                    # 测速
                    speed_matches = list(re.finditer(r"Speedtest completed with results:\s*(\{.*?\})", content))
                    if speed_matches:
                        data = json.loads(speed_matches[-1].group(1).replace("'", '"'))
                        up = data.get("upload_mbps")
                        down = data.get("download_mbps")
                        if up is not None and down is not None:
                            self.last_upload_speed = f"{up:.1f} Mbps"
                            self.last_download_speed = f"{down:.1f} Mbps"
                            self.config["last_upload_speed"] = self.last_upload_speed
                            self.config["last_download_speed"] = self.last_download_speed
                            save_config(self.config)
                            # 提取最近测速时间
                            sp_start = max(0, speed_matches[-1].start() - 60)
                            sp_m = re.search(r"\[\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})", content[sp_start:speed_matches[-1].start()])
                            if sp_m:
                                self.last_speedtest_time = sp_m.group(1)
                            self.update_speed_ui()
                    
                    # 活跃邻居
                    peer_matches = list(re.finditer(r"Peer status dict has (\d+) entries", content))
                    if peer_matches:
                        self.active_peers_count = f"{peer_matches[-1].group(1)} 个"

                    # 广播网格联通
                    bc_matches = list(re.finditer(r"Broadcast peer status:\s*(\d+)/(\d+)\s*ok", content))
                    if bc_matches:
                        last_bc = bc_matches[-1]
                        ok = int(last_bc.group(1))
                        tot = int(last_bc.group(2))
                        self.p2p_last_ok_peers = ok
                        self.p2p_last_total_peers = tot
                        self.p2p_last_unreachable = max(0, tot - ok)
                        self.peer_mesh_status = f"{ok}/{tot} 在线"
                        # 检查此条广播时间戳是否在最近 10 分钟内
                        bc_start = max(0, last_bc.start() - 60)
                        bc_ts_m = re.search(r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", content[bc_start:last_bc.end()])
                        if bc_ts_m:
                            try:
                                dt = datetime.strptime(bc_ts_m.group(1), "%Y-%m-%d %H:%M:%S")
                                self.p2p_last_broadcast_time = dt.timestamp()
                            except Exception:
                                self.p2p_last_broadcast_time = 0
                        else:
                            self.p2p_last_broadcast_time = 0

                    # 扫描丢弃 Forward 激活 (仅统计近 10 分钟)
                    drop_matches = list(re.finditer(r"(Failed to send forward activation|Peer unreachable for forward activation)", content))
                    if drop_matches:
                        self.p2p_total_drops = len(drop_matches)
                        self.p2p_recent_drops = []
                        for dm in drop_matches[-20:]:
                            dm_start = max(0, dm.start() - 60)
                            dm_ts_m = re.search(r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", content[dm_start:dm.end()])
                            if dm_ts_m:
                                try:
                                    dt = datetime.strptime(dm_ts_m.group(1), "%Y-%m-%d %H:%M:%S")
                                    if now_ts - dt.timestamp() <= 600:
                                        self.p2p_recent_drops.append(dt.timestamp())
                                except Exception:
                                    pass

                    # All layers training
                    all_matches = list(re.finditer(r"request to /miner/all_layers_training;\s*response:\s*(True|False)", content))
                    if all_matches:
                        self.all_layers_ready = "已就绪 (True)" if all_matches[-1].group(1) == "True" else "未就绪 (False)"

                    # 计算 Forward / Backward 历史
                    fwd_matches = re.findall(r"FORWARD complete", content)
                    bwd_matches = re.findall(r"BACKWARD complete", content)
                    self.forward_count = len(fwd_matches)
                    self.backward_count = len(bwd_matches)

                    # 尾部状态解析：判定当前是排队中还是正式训练中
                    tail_content = "\n".join(lines)
                    pos_matches = list(re.finditer(r"['\"]position['\"]\s*:\s*([0-9]+)", tail_content))
                    st_matches = list(re.finditer(r"['\"]status['\"]\s*:\s*['\"]([^'\"]+)['\"]", tail_content))

                    latest_status = st_matches[-1].group(1) if st_matches else None
                    if pos_matches:
                        unique_positions = [int(m.group(1)) for m in pos_matches]
                        if len(unique_positions) >= 2:
                            self.prev_queue_position = unique_positions[-2]
                        self.last_queue_position = unique_positions[-1]

                    if latest_status == "queued" or (self.last_queue_position is not None and latest_status != "training"):
                        self.last_status = "queued"
                        self.is_actively_training = False
                        self.queue_start_time = time.time()
                        self.root.after(0, lambda: [
                            self.lbl_node_phase.config(text=f"当前阶段: 🟡 队列排队中 ({self.current_layer})", fg="#d97706" if not self.dark_mode else "#fbbf24"),
                            self.lbl_init_timer.config(text=self.get_queue_status_text(0.0), fg="#d97706" if not self.dark_mode else "#fbbf24"),
                            self.lbl_train_stats.config(
                                text=f"训练计算统计: ⏳ 待机排队中 (累计历史 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次，等待入队就绪)" if self.forward_count > 0 else "训练计算统计: ⏳ 待机排队中 (等待全网各层握手对齐后自动触发训练)",
                                fg="#64748b" if not self.dark_mode else "#94a3b8"
                            )
                        ])
                    elif latest_status == "initializing":
                        self.last_status = "initializing"
                        self.is_actively_training = False
                        self.queue_start_time = time.time()
                    elif latest_status == "training" or (fwd_matches and not pos_matches):
                        self.last_status = "training"
                        self.is_actively_training = True

                    # 初始解析 Cache size (P1)
                    cache_matches = list(re.finditer(r"(?:cache size of (\d+)|Cache size:\s*(\d+)/(\d+))", content))
                    if cache_matches:
                        last_cm = cache_matches[-1]
                        if last_cm.group(1):
                            self.last_cache_size = int(last_cm.group(1))
                            self.last_cache_max = 16
                        else:
                            self.last_cache_size = int(last_cm.group(2))
                            self.last_cache_max = int(last_cm.group(3))

                    # 初始解析 all_layers_training (P1)
                    al_matches = list(re.finditer(r"request to /miner/all_layers_training.*?response:\s*(True|False)", content))
                    if al_matches:
                        self.all_layers_training_bool = (al_matches[-1].group(1) == "True")
                        self.all_layers_ready = "全部层就绪 (True)" if self.all_layers_training_bool else "等待各层中 (False)"

                    # 初始解析 orchestrator 激活状态 (P1)
                    if list(re.finditer(r"(?:No activations received from orchestrator|Received activations: 0)", content[-5000:])):
                        self.orchestrator_status = "等待 orchestrator 分配"
                    elif list(re.finditer(r"Activation push RECV", content[-5000:])):
                        self.orchestrator_status = "正常接收激活中"

                    # 初始解析 heartbeat 中的 epoch (P2)
                    hb_matches = list(re.finditer(r"request to /miner/heartbeat.*?response:\s*({.*?})", content))
                    if hb_matches:
                        try:
                            hb_dict = eval(hb_matches[-1].group(1))
                            if hb_dict.get("epoch") is not None:
                                self.current_epoch_num = int(hb_dict["epoch"])
                                self.current_epoch = f"Epoch {self.current_epoch_num}"
                                self.epoch_start_time = time.time()
                                self.last_activation_epoch = self.current_epoch_num
                        except Exception:
                            pass

                    self.update_orchestrator_cache_ui()
                    self.update_p2p_health_ui()
            except Exception:
                pass

    def update_speed_ui(self):
        def _update():
            if self.last_upload_speed != "检测中...":
                t_str = f" ({self.last_speedtest_time} 测得)" if getattr(self, "last_speedtest_time", "") else ""
                self.lbl_speed_info.config(text=f"最近测速网速: ⬆ 上传 {self.last_upload_speed}  (⬇ 下载 {self.last_download_speed}){t_str}", fg="#0284c7" if not self.dark_mode else "#38bdf8")
        self.root.after(0, _update)

    def update_orchestrator_cache_ui(self):
        def _do():
            if hasattr(self, "lbl_orchestrator"):
                if self.last_cache_size is not None:
                    if self.last_cache_size >= self.last_cache_max:
                        c_tag = "满 (待Backward计算)"
                        c_fg = "#15803d" if not self.dark_mode else "#4ade80"
                    elif self.last_cache_size == 0:
                        c_tag = "空 (待分发活)"
                        c_fg = "#d97706" if not self.dark_mode else "#fbbf24"
                    else:
                        c_tag = "正常计算中"
                        c_fg = "#2563eb" if not self.dark_mode else "#60a5fa"
                    cache_text = f"Cache 占用: {self.last_cache_size}/{self.last_cache_max} ({c_tag})"
                else:
                    cache_text = "Cache 占用: 检测中..."

                orch_fg = "#15803d" if not self.dark_mode else "#4ade80"
                if "等待" in self.orchestrator_status:
                    orch_fg = "#d97706" if not self.dark_mode else "#fbbf24"

                orch_text = f"Orchestrator 分配: {self.orchestrator_status}"
                al_text = f"全网层就绪: {'是' if self.all_layers_training_bool else '否'}" if self.all_layers_training_bool is not None else ""
                al_part = f" | {al_text}" if al_text else ""
                self.lbl_orchestrator.config(text=f"{orch_text} | {cache_text}{al_part}", fg=orch_fg)

            if hasattr(self, "lbl_epoch_status"):
                dur_mins = int((time.time() - self.epoch_start_time) / 60) if self.epoch_start_time else 0
                ep_text = f"{self.current_epoch} · 持续 {dur_mins} 分钟" if self.current_epoch and "检测" not in self.current_epoch else "Epoch: 检测中..."
                idle_eps = (self.current_epoch_num - self.last_activation_epoch) if (self.current_epoch_num and self.last_activation_epoch) else 0
                if idle_eps >= 2 and self.is_actively_training:
                    ep_hint = "⚠️ 已超 2 个 epoch 无新激活 (可考虑重启一次)"
                    ep_fg = "#dc2626" if not self.dark_mode else "#f87171"
                else:
                    ep_hint = "等待上游 layer 或 epoch 切换 (正常)"
                    ep_fg = "#16a34a" if not self.dark_mode else "#4ade80"
                self.lbl_epoch_status.config(text=f"Epoch 感知: {ep_text} | 分配提示: {ep_hint}", fg=ep_fg)

        self.root.after(0, _do)

    def update_countdown_ui(self, window_tokens=None):
        if window_tokens is not None:
            self.current_window_tokens = window_tokens
        now = datetime.now()
        if self.next_payout_ts and self.next_payout_ts > now.timestamp():
            rem_sec = max(0, self.next_payout_ts - now.timestamp())
        else:
            target_20pm = datetime(now.year, now.month, now.day, 20, 0, 0)
            if now >= target_20pm:
                target_20pm += timedelta(days=1)
            rem_sec = max(0, (target_20pm - now).total_seconds())

        rem_h = int(rem_sec // 3600)
        rem_m = int((rem_sec % 3600) // 60)
        w_wan = (self.current_window_tokens / 10000.0) if hasattr(self, "current_window_tokens") else 0.0

        countdown_text = f"⏳ 结算倒计时: 距离下次结算还有 {rem_h} 小时 {rem_m:02d} 分 (每天 20:00 EDT / UTC 00:00) | 本窗口增量: +{w_wan:.2f} 万 Tokens"
        def _do():
            if hasattr(self, "lbl_payout_countdown"):
                self.lbl_payout_countdown.config(text=countdown_text)
        self.root.after(0, _do)

    def _tick_countdown(self):
        if not self.running:
            return
        self.update_countdown_ui()
        self.update_orchestrator_cache_ui()
        self.root.after(30000, self._tick_countdown)

    def update_zombie_banner_ui(self):
        def _do():
            if hasattr(self, "banner_zombie") and hasattr(self, "lbl_zombie_msg"):
                if self.is_zombie:
                    self.lbl_zombie_msg.config(text=self.zombie_alert_text)
                    if hasattr(self, "widgets") and "card_kpi" in self.widgets and self.widgets["card_kpi"].winfo_ismapped():
                        self.banner_zombie.pack(before=self.widgets["card_kpi"], fill=tk.X, pady=(0, 10))
                    else:
                        self.banner_zombie.pack(fill=tk.X, pady=(0, 10))
                else:
                    self.banner_zombie.pack_forget()
        self.root.after(0, _do)

    def update_p2p_health_ui(self):
        now = time.time()
        self.p2p_recent_drops = [t for t in self.p2p_recent_drops if now - t <= 600]
        recent_drop_count = len(self.p2p_recent_drops)
        unreachable = self.p2p_last_unreachable
        total_peers = self.p2p_last_total_peers

        # 判断是否处于排队或握手等待状态（此时未入网格，不应报错）
        is_in_queue = (self.last_status in ["queued", "initializing", "resetting"] or 
                       (self.last_queue_position is not None and not self.is_actively_training))
        is_bc_fresh = (now - getattr(self, "p2p_last_broadcast_time", 0)) <= 600

        if is_in_queue:
            new_level = "IDLE"
            text = "P2P传输与广播健康: ⏸️ 队列排队中 (待入队后连入邻居网格)"
            fg_color = "#64748b" if not self.dark_mode else "#94a3b8"
        else:
            # 仅在广播数据新鲜且确实处于工作状态时判定网格异常
            is_red = (
                recent_drop_count >= 15 or 
                (is_bc_fresh and total_peers >= 6 and unreachable >= 8) or 
                (is_bc_fresh and total_peers >= 10 and (unreachable / total_peers) >= 0.5)
            )
            is_yellow = (
                recent_drop_count >= 5 or 
                (is_bc_fresh and unreachable >= 3) or 
                (is_bc_fresh and total_peers >= 10 and (unreachable / total_peers) >= 0.2)
            )

            if is_red:
                new_level = "RED"
                text = f"P2P传输与广播健康: 🔴 严重告警 (近10分丢弃: {recent_drop_count}次 | 广播不可达: {unreachable}/{total_peers}) - 算力丢弃中!"
                fg_color = "#dc2626" if not self.dark_mode else "#f87171"
            elif is_yellow:
                new_level = "YELLOW"
                text = f"P2P传输与广播健康: 🟡 传输异常 (近10分丢弃: {recent_drop_count}次 | 广播不可达: {unreachable}/{total_peers}) - 存在超时丢包"
                fg_color = "#d97706" if not self.dark_mode else "#fbbf24"
            else:
                new_level = "GREEN"
                bc_info = f" | 广播不可达: {unreachable}/{total_peers}" if is_bc_fresh and total_peers > 0 else ""
                text = f"P2P传输与广播健康: 🟢 良好稳定 (近10分丢弃: {recent_drop_count}次{bc_info})"
                fg_color = "#15803d" if not self.dark_mode else "#4ade80"

        if new_level != self.p2p_health_level and new_level != "IDLE":
            old_level = self.p2p_health_level
            self.p2p_health_level = new_level
            if new_level == "RED":
                self._insert_text(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 [P2P网络严重告警] 激活张量大量丢弃({recent_drop_count}次)或广播不可达({unreachable}/{total_peers})，已严重影响挖矿有效产出！\n", "ERROR")
            elif new_level == "YELLOW" and old_level == "GREEN":
                self._insert_text(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ [P2P网络轻度异常] 检测到 {unreachable} 个节点不可达或发生转发超时，请注意观察网络延迟。\n", "WARN")
            elif new_level == "GREEN" and old_level in ["YELLOW", "RED"]:
                self._insert_text(f"[{datetime.now().strftime('%H:%M:%S')}] 🟢 [P2P网络恢复良好] 传输通道已恢复正常稳定。\n", "TRAINING")
        elif new_level == "IDLE":
            self.p2p_health_level = "IDLE"

        def _do_update():
            if hasattr(self, "lbl_p2p_health"):
                self.lbl_p2p_health.config(text=text, fg=fg_color)
        self.root.after(0, _do_update)

    def trigger_fetch_payout(self, manual=False):
        if manual and hasattr(self, "lbl_payout_totals"):
            self.lbl_payout_totals.config(text="正在刷新官方结算数据...")
        threading.Thread(target=self._fetch_payout_worker, args=(manual,), daemon=True).start()

    def _fetch_payout_worker(self, manual=False):
        if not self.miner_hotkey or self.miner_hotkey == "检测中...":
            hk_file = os.path.expanduser("~/.bittensor/wallets/iota/hotkeys/iota_miner")
            if os.path.exists(hk_file):
                try:
                    with open(hk_file, "r") as f:
                        hk_data = json.load(f)
                        if "ss58Address" in hk_data:
                            self.miner_hotkey = hk_data["ss58Address"]
                            self.update_miner_info_ui()
                except Exception:
                    pass

        if not self.miner_hotkey or self.miner_hotkey == "检测中...":
            if manual:
                self.root.after(0, lambda: messagebox.showwarning("提示", "未检测到有效的 Miner Hotkey，暂无法查询结算数据！"))
            return

        hotkey = self.miner_hotkey
        base = "https://iota-web.api.macrocosmos.ai/mainnet"
        import urllib.request, gzip, ssl

        try:
            ctx = ssl._create_unverified_context()
        except Exception:
            ctx = None

        def _get_json(url):
            req = urllib.request.Request(url, headers={"User-Agent": "iota-train-at-home-1.1.0", "Accept-Encoding": "gzip"})
            kwargs = {"timeout": 8}
            if ctx:
                kwargs["context"] = ctx
            with urllib.request.urlopen(req, **kwargs) as resp:
                raw = resp.read()
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8"))

        try:
            totals = _get_json(f"{base}/v1/entitlements/totals/hotkey/{hotkey}")
            history = _get_json(f"{base}/v1/entitlements/history/hotkey/{hotkey}")
            
            # 查询下次官方结算时间戳 (P1)
            try:
                payout_ts_res = _get_json(f"{base}/v1/entitlements/next_payout_timestamp")
                self.next_payout_ts = payout_ts_res.get("next_payout_time")
            except Exception:
                pass

            # 获取当前 Subnet 9 (SN9 / IOTA) 市场价格进行当天市值估算
            try:
                price_req = urllib.request.Request(
                    "https://api.coingecko.com/api/v3/simple/price?ids=iota-2&vs_currencies=usd",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(price_req, timeout=4) as pr:
                    p_data = json.loads(pr.read().decode("utf-8"))
                    if "iota-2" in p_data and "usd" in p_data["iota-2"]:
                        self.sn9_usd_price = float(p_data["iota-2"]["usd"])
                        self.tao_usd_price = self.sn9_usd_price
            except Exception:
                pass

            earned = totals.get("total_amount_earned", 0.0)
            paid = totals.get("total_amount_paid", 0.0)
            pending = totals.get("total_amount_pending", 0.0)
            min_pay = totals.get("minimum_payout_amount", 0.4)

            self.total_earned_val = earned
            self.total_paid_val = paid
            self.total_pending_val = pending

            amounts = history.get("alpha_amounts", [])
            timestamps = history.get("timestamps", [])
            statuses = history.get("statuses", [])

            payout_lines = []
            if amounts and timestamps:
                combined = list(zip(amounts, timestamps, statuses))
                # 按时间降序排列 (最新结算在最上方)
                combined.sort(key=lambda x: x[1], reverse=True)
                price = getattr(self, "sn9_usd_price", getattr(self, "tao_usd_price", 0.0))
                for amt, ts, st in combined[:8]:
                    dt_str = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
                    st_str = "已结算" if st == "settled" else st
                    usd_hint = f" (≈ ${amt * price:,.2f})" if price > 0 else ""
                    payout_lines.append(f"● {dt_str} EDT: {amt:.3f} IOTA{usd_hint} · {st_str}")

                last_amt = amounts[-1]
                last_ts = timestamps[-1]
                last_st = statuses[-1] if statuses else "settled"
                dt_str = datetime.fromtimestamp(last_ts).strftime("%m-%d %H:%M")
                st_str = "已结算" if last_st == "settled" else last_st
                usd_hint = f" (≈ ${float(last_amt) * price:,.2f})" if price > 0 else ""
                self.last_payout_info = {
                    "amount": round(float(last_amt), 3),
                    "amount_str": f"{float(last_amt):.3f} IOTA",
                    "timestamp": last_ts,
                    "time_str": f"{dt_str} EDT",
                    "status": st_str,
                    "display": f"{float(last_amt):.3f} IOTA{usd_hint} ({st_str}) · {dt_str} EDT"
                }
            else:
                payout_lines.append("暂无历史结算发放记录")

            if getattr(self, "next_payout_ts", None):
                next_dt_str = datetime.fromtimestamp(self.next_payout_ts).strftime("%m-%d %H:%M")
                self.next_payout_info = {
                    "timestamp": self.next_payout_ts,
                    "time_str": f"{next_dt_str} EDT",
                    "display": f"{next_dt_str} EDT"
                }

            # 聚合多 Run 计算有效 Token 贡献量（按 20:00 结算周期统计近 3 天对比，以及最近 6 小时每小时贡献）
            token_lines = []
            cand_runs = []
            if self.current_run_id and "检测中" not in self.current_run_id:
                cand_runs.append(self.current_run_id)
            # 扫描最近的 cli 日志以发现所有近期运行的 Run ID
            cli_logs = glob.glob(os.path.join(LOG_DIR, "*[0-9]-cli.log"))
            cli_logs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            for lf_path in cli_logs[:5]:
                try:
                    with open(lf_path, "r", errors="ignore") as lf:
                        for l in lf:
                            for rm in re.finditer(r"4\.12\.16\.\d+-tah", l):
                                r_cand = rm.group(0)
                                if r_cand not in cand_runs:
                                    cand_runs.append(r_cand)
                except Exception:
                    pass
            for fb in ["4.12.16.20-tah", "4.12.16.24-tah", "4.12.16.14-tah"]:
                if fb not in cand_runs:
                    cand_runs.append(fb)

            # 查询矿工在主 Run 下的官方排名 (P0 功能 2)
            primary_run_clean = cand_runs[0].replace("run-", "").replace("_", ".")
            try:
                rank_res = _get_json(f"{base}/v1/epoch_miner_scores/runs/{primary_run_clean}/hotkeys/{hotkey}/run_level_rank")
                self.chain_rank = rank_res.get("rank")
                self.chain_num_miners = rank_res.get("num_hotkeys")
                self.chain_contribution_perc = rank_res.get("act_contribution_perc")
            except Exception:
                pass

            now = datetime.now()

            def _fetch_run_pts(r_name):
                c_run = r_name.replace("run-", "").replace("_", ".")
                u = f"{base}/miners/{hotkey}/runs/{c_run}/tokens"
                try:
                    res = _get_json(u)
                    return r_name, res.get("data_points", [])
                except Exception:
                    return r_name, []

            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(4, len(cand_runs))) as ex:
                run_pts_map = dict(ex.map(_fetch_run_pts, cand_runs))

            sorted_run_pts = {}
            for r_name, points in run_pts_map.items():
                if points:
                    sorted_run_pts[r_name] = sorted(points, key=lambda x: x.get("timestamp", 0))

            primary_pts = sorted_run_pts.get(cand_runs[0]) or sorted_run_pts.get(primary_run_clean) or []
            if not primary_pts and sorted_run_pts:
                primary_pts = list(sorted_run_pts.values())[0]

            self.chain_token_count = sum(pts[-1].get("token_count", 0) for pts in sorted_run_pts.values() if pts)
            self.chain_network_tokens = primary_pts[-1].get("network_tokens", 0) if primary_pts else 0
            self.chain_data_available = True

            # 僵尸状态检测 (P0 核心需求)
            latest_token_cnt = primary_pts[-1].get("token_count", 0) if primary_pts else 0
            latest_net_tokens = primary_pts[-1].get("network_tokens", 0) if primary_pts else 0
            last_growth_ts = None
            net_at_last_growth = latest_net_tokens
            if primary_pts:
                for pt in reversed(primary_pts[:-1]):
                    if pt.get("token_count", 0) < latest_token_cnt:
                        last_growth_ts = pt.get("timestamp")
                        net_at_last_growth = pt.get("network_tokens", 0)
                        break
                if last_growth_ts is None:
                    last_growth_ts = primary_pts[0].get("timestamp", now.timestamp())
                    net_at_last_growth = primary_pts[0].get("network_tokens", 0)

            now_ts = time.time()
            flat_hours = (now_ts - last_growth_ts) / 3600.0 if last_growth_ts else 0.0
            net_growth = max(0, latest_net_tokens - net_at_last_growth)
            self.zombie_flat_hours = flat_hours
            self.zombie_net_growth = net_growth

            zombie_limit = float(self.config.get("zombie_stale_hours", 2.0))
            proc_running, _ = self.check_process()
            latest_log = self.get_latest_log()
            log_fresh = bool(latest_log and os.path.exists(latest_log) and (now_ts - os.path.getmtime(latest_log) <= self.config.get("max_stale_minutes", 10) * 60))

            # 僵尸告警触发条件（全部满足）：进程在跑、心跳新鲜、链上 flat_hours >= 阈值、且同期全网 network_tokens 仍在增长 (> 10万)
            if proc_running and log_fresh and flat_hours >= zombie_limit and net_growth > 100000:
                self.is_zombie = True
                self.zombie_alert_text = (
                    f"⚠️ 疑似僵尸状态：本地运行正常，但链上已 {flat_hours:.1f} 小时无新 Token 入账（Run 正常，同期全网增长 +{net_growth/10000:.1f}万 Tokens）！\n"
                    f"建议操作：按官方指南，训练中若超过 2 个 epoch 无新 activation 可重启一次节点。"
                )
            else:
                self.is_zombie = False
                self.zombie_alert_text = ""

            def get_tokens_at(pts, target_ts):
                if not pts:
                    return 0.0
                if target_ts <= pts[0].get("timestamp", 0):
                    return 0.0 if pts[0].get("token_count", 0) == 0 else float(pts[0].get("token_count", 0))
                if target_ts >= pts[-1].get("timestamp", 0):
                    return float(pts[-1].get("token_count", 0))
                for i in range(len(pts) - 1):
                    t0 = pts[i].get("timestamp", 0)
                    c0 = pts[i].get("token_count", 0)
                    t1 = pts[i+1].get("timestamp", 0)
                    c1 = pts[i+1].get("token_count", 0)
                    if t0 <= target_ts <= t1:
                        if t1 == t0:
                            return float(c0)
                        ratio = (target_ts - t0) / (t1 - t0)
                        return float(c0) + (float(c1) - float(c0)) * ratio
                return float(pts[-1].get("token_count", 0))

            def get_range_tokens(t_start, t_end):
                ts0 = t_start.timestamp()
                ts1 = t_end.timestamp()
                tot = 0.0
                for pts in sorted_run_pts.values():
                    v0 = get_tokens_at(pts, ts0)
                    v1 = get_tokens_at(pts, ts1)
                    if v1 > v0:
                        tot += (v1 - v0)
                return tot

            # 1. 最近 6 小时贡献（每小时明细 + 合计）
            cur_hour_start = datetime(now.year, now.month, now.day, now.hour, 0, 0)
            hourly_items = []
            sum_6h = 0.0
            for h_offset in range(6, 0, -1):
                h_start = cur_hour_start - timedelta(hours=h_offset)
                h_end = h_start + timedelta(hours=1)
                h_delta = get_range_tokens(h_start, h_end)
                sum_6h += h_delta
                hourly_items.append((h_start.strftime("%H:00"), h_end.strftime("%H:00"), h_delta))

            cur_delta = get_range_tokens(cur_hour_start, now)
            tot_with_current = sum_6h + cur_delta
            self.last_6h_total_str = f"{tot_with_current/10000:.2f}万"

            # 结构化存储最近各小时贡献 (当前进行中小时 + 最近 3 个完整整小时)
            recent_hourly = []
            recent_hourly.append({
                "range": f"{cur_hour_start.strftime('%H:00')}~{now.strftime('%H:%M')}",
                "tokens": f"{cur_delta/10000:.2f}万",
                "tokens_num": round(cur_delta / 10000.0, 2),
                "is_current": True
            })
            for s, e, delta in reversed(hourly_items[-3:]):
                recent_hourly.append({
                    "range": f"{s}~{e}",
                    "tokens": f"{delta/10000:.2f}万",
                    "tokens_num": round(delta / 10000.0, 2),
                    "is_current": False
                })
            self.recent_hourly_tokens = recent_hourly

            # 有效 Token 贡献统计（按时间降序排列：最新小时在最上方）
            s_cur = cur_hour_start.strftime("%H:00")
            e_cur = now.strftime("%H:%M")
            token_lines.append(f"【⏱ 最近 6 小时有效贡献 (合计: {tot_with_current/10000:.2f}万 | 按时间降序)】")
            token_lines.append(f"● {s_cur} ~ {e_cur} (进行中): {cur_delta/10000:6.2f} 万 Tokens")
            for s, e, delta in reversed(hourly_items):
                token_lines.append(f"● {s} ~ {e}: {delta/10000:6.2f} 万 Tokens")

            token_lines.append("")
            # 2. 最近 3 天结算周期对比（以官方 20:00 EDT / UTC 00:00 结算为周期锚点，按日期降序）
            token_lines.append("【📅 结算周期对比 (20:00 锚点，按日期降序)】")
            anchor_date = now.date() if now.hour >= 20 else now.date() - timedelta(days=1)
            anchor_20pm = datetime(anchor_date.year, anchor_date.month, anchor_date.day, 20, 0, 0)

            cur_window_delta = 0.0
            price = getattr(self, "sn9_usd_price", getattr(self, "tao_usd_price", 0.0))
            for cycle_idx in range(3):
                c_start = anchor_20pm - timedelta(days=cycle_idx)
                c_end = c_start + timedelta(days=1)
                q_end = min(c_end, now)
                c_delta = get_range_tokens(c_start, q_end)
                if cycle_idx == 0:
                    cur_window_delta = c_delta
                    self.cur_cycle_tokens_str = f"{cur_window_delta/10000:.2f}万"
                t_wan = c_delta / 10000.0

                s_str = c_start.strftime("%m-%d 20:00")
                if cycle_idx == 0:
                    e_str = "今晚20:00" if now.hour < 20 else "明晚20:00"
                    status_tag = " (进行中)"
                    hint = " ✓ 正常产出中" if t_wan > 0 else " ⚠️ 暂无产出(排查连接)"
                else:
                    e_str = c_end.strftime("%m-%d 20:00")
                    status_tag = " (已结算)"
                    settled_amt = None
                    if amounts and timestamps:
                        for a, t in zip(amounts, timestamps):
                            if abs(t - c_end.timestamp()) <= 10800:
                                settled_amt = a
                                break
                    if settled_amt is not None:
                        usd_s = f" ≈ ${settled_amt * price:,.2f}" if price > 0 else ""
                        hint = f" ✓ 结出 {settled_amt:.3f} IOTA{usd_s}"
                    elif t_wan < 20:
                        hint = " ⚠️ 产出不足0.4 IOTA未结"
                    else:
                        hint = " ✓ 已计入结算"

                token_lines.append(f"● {s_str} ~ {e_str}{status_tag}: {t_wan:6.2f} 万 Tokens{hint}")

            def _update_ui():
                price = getattr(self, "sn9_usd_price", getattr(self, "tao_usd_price", 0.0))
                e_usd = f" (≈${earned * price:,.2f})" if price > 0 else ""
                p_usd = f" (≈${paid * price:,.2f})" if price > 0 else ""
                pend_usd = f" (≈${pending * price:,.2f})" if price > 0 else ""
                price_tag = f" · SN9 (IOTA): ${price:,.2f}" if price > 0 else ""

                if hasattr(self, "lbl_payout_totals"):
                    self.lbl_payout_totals.config(
                        text=f"累计总赚取: {earned:.3f} IOTA{e_usd} | 已结算: {paid:.3f} IOTA{p_usd} | 待结: {pending:.3f} IOTA{pend_usd}{price_tag} (起付门槛 {min_pay} IOTA)"
                    )
                    self.lbl_daily_tokens.config(text="\n".join(token_lines))
                    self.lbl_payout_history.config(text="\n".join(payout_lines))

                # 更新链上收益与本地估算并列面板 (P0 功能 2)
                if hasattr(self, "lbl_chain_metrics"):
                    local_wan = (self.forward_count * 3200) / 10000.0
                    chain_wan = self.chain_token_count / 10000.0
                    rank_info = f"第 {self.chain_rank}/{self.chain_num_miners} 名" if self.chain_rank else "排名同步中"
                    if self.chain_contribution_perc is not None:
                        rank_info += f" (贡献占比 {self.chain_contribution_perc*100:.2f}%)"
                    self.lbl_chain_metrics.config(
                        text=f"● 链上已确认: {chain_wan:,.2f} 万 Tokens (Ground Truth)  |  本地日志估算: {local_wan:,.2f} 万 Tokens (Forward: {self.forward_count}次)  |  全网排名: {rank_info}"
                    )

                # 更新 Run 健康度趋势
                if hasattr(self, "lbl_network_health"):
                    net_wan = self.chain_network_tokens / 10000.0
                    trend_tag = "✓ 增长正常" if net_growth > 0 or self.chain_network_tokens > 0 else "⚠️ 暂无增长"
                    self.lbl_network_health.config(
                        text=f"● Run 健康参考: {primary_run_clean} 全网累计 {net_wan:,.1f} 万 Tokens ({trend_tag}，排除全网故障)"
                    )

                # 更新结算倒计时与僵尸横幅 (P1 & P0)
                self.update_countdown_ui(cur_window_delta)
                self.update_zombie_banner_ui()
                self.update_kpi_cards()

                if manual:
                    self.append_watchdog_log("📊 [收益账单] 官方结算数据、当天市值估算、链上Token与排名已刷新同步！")

            self.root.after(0, _update_ui)
        except Exception as e:
            self.chain_data_available = False
            self.is_zombie = False
            self.update_zombie_banner_ui()
            if hasattr(self, "lbl_chain_metrics"):
                self.root.after(0, lambda: self.lbl_chain_metrics.config(text="● 链上已确认: 链上数据暂不可用 (网络连接超时或节点未响应，稍后自动重试)"))
            if manual:
                self.root.after(0, lambda err=str(e): self.append_watchdog_log(f"⚠️ 刷新官方收益数据失败: {err}"))

    def setup_fonts(self):
        s = self.ui_font_scale / 100.0
        self.font_title = tkFont.Font(family="Helvetica", size=max(10, int(15 * s)), weight="bold")
        self.font_card_title = tkFont.Font(family="Helvetica", size=max(9, int(11 * s)), weight="bold")
        self.font_kpi_title = tkFont.Font(family="Helvetica", size=max(8, int(10 * s)), weight="bold")
        self.font_kpi_val = tkFont.Font(family="Helvetica", size=max(10, int(13 * s)), weight="bold")
        self.font_kpi_sub = tkFont.Font(family="Helvetica", size=max(7, int(9 * s)))
        self.font_body_bold = tkFont.Font(family="Helvetica", size=max(8, int(10 * s)), weight="bold")
        self.font_body = tkFont.Font(family="Helvetica", size=max(8, int(10 * s)))
        self.font_small = tkFont.Font(family="Helvetica", size=max(7, int(9 * s)))
        self.font_btn = tkFont.Font(family="Helvetica", size=max(8, int(10 * s)), weight="bold")
        self.font_mono = tkFont.Font(family="Menlo", size=max(8, int(10 * s)))
        self.font_mono_bold = tkFont.Font(family="Menlo", size=max(8, int(10 * s)), weight="bold")

    def change_ui_font_scale(self, delta):
        new_scale = max(60, min(140, self.ui_font_scale + delta))
        if new_scale == self.ui_font_scale:
            return
        self.ui_font_scale = new_scale
        self.config["ui_font_scale"] = self.ui_font_scale
        save_config(self.config)
        s = self.ui_font_scale / 100.0
        self.font_title.configure(size=max(10, int(15 * s)))
        self.font_card_title.configure(size=max(9, int(11 * s)))
        self.font_kpi_title.configure(size=max(8, int(10 * s)))
        self.font_kpi_val.configure(size=max(10, int(13 * s)))
        self.font_kpi_sub.configure(size=max(7, int(9 * s)))
        self.font_body_bold.configure(size=max(8, int(10 * s)))
        self.font_body.configure(size=max(8, int(10 * s)))
        self.font_small.configure(size=max(7, int(9 * s)))
        self.font_btn.configure(size=max(8, int(10 * s)))
        self.font_mono.configure(size=max(8, int(10 * s)))
        self.font_mono_bold.configure(size=max(8, int(10 * s)))
        if hasattr(self, "lbl_ui_font_display"):
            self.lbl_ui_font_display.config(text=f"{self.ui_font_scale}%")

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
                self.caffeinate_proc = subprocess.Popen(["caffeinate", "-d", "-i", "-m", "-s"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
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

    def cleanup_old_logs(self):
        """清理超过保留天数的过期日志文件"""
        try:
            retention_days = self.config.get("log_retention_days", 2)
            cutoff_time = time.time() - (retention_days * 86400)
            today_str = datetime.now().strftime("%Y-%m-%d")

            all_logs = glob.glob(os.path.join(LOG_DIR, "*.log"))
            deleted_count = 0
            freed_bytes = 0

            for log_path in all_logs:
                basename = os.path.basename(log_path)
                # 跳过今天的日志
                if basename.startswith(today_str):
                    continue
                try:
                    mtime = os.path.getmtime(log_path)
                    fsize = os.path.getsize(log_path)
                    if mtime < cutoff_time:
                        os.remove(log_path)
                        deleted_count += 1
                        freed_bytes += fsize
                        self.append_watchdog_log(f"🗑️ [自动清理] 删除过期日志: {basename} ({format_size(fsize)})")
                except Exception as e:
                    self.append_watchdog_log(f"⚠️ [自动清理] 删除失败 {basename}: {e}")

            self.last_log_cleanup_time = time.time()

            if deleted_count > 0:
                self.append_watchdog_log(f"✅ [自动清理完成] 共删除 {deleted_count} 个过期日志，释放 {format_size(freed_bytes)} 空间")
            else:
                self.append_watchdog_log(f"🧹 [自动清理] 暂无过期日志需要清理 (保留最近 {retention_days} 天)")
        except Exception as e:
            self.append_watchdog_log(f"❌ [自动清理异常] {e}")

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
        if hasattr(self, "btn_exit"):
            self.btn_exit.set_colors(t["btn_exit_bg"], "#ffffff", t["btn_exit_hover"])

        for name, w in self.widgets.items():
            if isinstance(w, tk.Frame) or isinstance(w, tk.LabelFrame):
                if name.startswith("root_") or name in ["main_frame", "ctrl_frame", "font_ctrl_frame", "cfg_sub_frame", "card_kpi", "ui_font_frame"]:
                    w.config(bg=t["bg_root"])
                elif name.startswith("card_"):
                    w.config(bg=t["bg_card"], fg=t["fg_title"] if isinstance(w, tk.LabelFrame) else None)
                elif name.startswith("subcard_"):
                    if "kpi" in name:
                        w.config(bg=t["bg_card"])
                    elif "left" in name or "right" in name:
                        w.config(bg=t["bg_subcard"])
                    else:
                        w.config(bg=t["bg_card"])
                elif name == "banner_update":
                    w.config(bg="#1e1b4b" if self.dark_mode else "#e0e7ff")
                elif name == "banner_zombie":
                    w.config(bg="#450a0a" if self.dark_mode else "#fee2e2")
                else:
                    w.config(bg=t["bg_card"])
            elif isinstance(w, tk.Label) and not isinstance(w, ModernButton):
                if name == "lbl_title_main":
                    w.config(bg=t["bg_root"], fg=t["fg_title"])
                elif name == "lbl_watchdog_status":
                    w.config(bg=t["bg_root"])
                elif name.startswith("lbl_kpi") and name.endswith("_title"):
                    w.config(bg=t["bg_card"], fg=t["fg_title"])
                elif name.endswith("_sub"):
                    w.config(bg=t["bg_card"], fg=t["fg_muted"])
                elif name.endswith("_val"):
                    w.config(bg=t["bg_card"])
                elif name in ["lbl_tag_miner", "lbl_tag_coldkey"]:
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                elif name in ["lbl_search_icon", "lbl_search_count"]:
                    w.config(bg=t["bg_card"], fg=t["fg_muted"])
                elif name == "lbl_scroll_hint":
                    w.config(bg=t["bg_card"], fg="#f59e0b" if self.dark_mode else "#d97706")
                elif name.startswith("lbl_title"):
                    w.config(bg=t["bg_card"], fg=t["fg_title"])
                elif name.startswith("lbl_sub_"):
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                elif name.startswith("lbl_badge_"):
                    w.config(bg=t["bg_subcard"], fg="#38bdf8" if self.dark_mode else "#1d4ed8")
                elif name in ["lbl_proc_status", "lbl_node_phase", "lbl_log_time", "lbl_train_stats"]:
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                elif name in ["lbl_orchestrator", "lbl_epoch_status"]:
                    w.config(bg=t["bg_card"])
                elif name == "lbl_speed_info":
                    w.config(bg=t["bg_card"])
                elif name == "lbl_p2p_health":
                    w.config(bg=t["bg_card"])
                elif name == "lbl_chain_metrics":
                    w.config(bg=t["bg_card"], fg="#38bdf8" if self.dark_mode else "#2563eb")
                elif name in ["lbl_network_health", "lbl_payout_glossary"]:
                    w.config(bg=t["bg_card"], fg=t["fg_muted"])
                elif name == "lbl_payout_countdown":
                    w.config(bg=t["bg_card"], fg="#38bdf8" if self.dark_mode else "#0284c7")
                elif name == "lbl_update_msg":
                    w.config(bg="#1e1b4b" if self.dark_mode else "#e0e7ff", fg="#a5b4fc" if self.dark_mode else "#3730a3")
                elif name == "lbl_zombie_msg":
                    w.config(bg="#450a0a" if self.dark_mode else "#fee2e2", fg="#fca5a5" if self.dark_mode else "#991b1b")
                elif name.startswith("lbl_payout_") or name in ["lbl_dt_title", "lbl_ph_title", "lbl_daily_tokens", "lbl_payout_history"]:
                    bg_c = w.master.cget("bg") if hasattr(w, "master") else t["bg_card"]
                    w.config(bg=bg_c, fg=t["fg_text"])
                elif name in ["lbl_font_display", "lbl_ui_font_display"]:
                    w.config(bg=t["bg_card"], fg=t["fg_text"])
                elif name in ["lbl_font_tag", "lbl_ui_font_tag"]:
                    w.config(bg=t["bg_card"], fg=t["fg_muted"])
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
        if hasattr(self, "btn_ui_font_dec"):
            self.btn_ui_font_dec.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        if hasattr(self, "btn_ui_font_inc"):
            self.btn_ui_font_inc.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        if hasattr(self, "btn_toggle_cfg"):
            self.btn_toggle_cfg.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        if hasattr(self, "btn_clear_search"):
            self.btn_clear_search.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        if hasattr(self, "btn_cloud_sync"):
            self.btn_cloud_sync.set_colors("#6366f1", "#ffffff", "#4f46e5")
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.set_colors("#4F46E5", "#ffffff", "#4338CA")
        self.btn_copy_hk.set_colors("#2563eb", "#ffffff", "#3b82f6")
        self.btn_copy_ck.set_colors("#2563eb", "#ffffff", "#3b82f6")
        if hasattr(self, "btn_toggle_ck"):
            self.btn_toggle_ck.set_colors(t["btn_neutral_bg"], t["btn_neutral_fg"], t["btn_neutral_hover"])
        self.btn_restart.set_colors("#dc2626", "#ffffff", "#ef4444")
        self.btn_clean_reset.set_colors("#b45309", "#ffffff", "#d97706")
        self.btn_save.set_colors("#059669", "#ffffff", "#10b981")
        if hasattr(self, "btn_refresh_payout"):
            self.btn_refresh_payout.set_colors("#0284c7", "#ffffff", "#0369a1")
        if hasattr(self, "btn_zombie_guide"):
            self.btn_zombie_guide.set_colors("#b45309", "#ffffff", "#d97706")
        if hasattr(self, "btn_zombie_restart"):
            self.btn_zombie_restart.set_colors("#dc2626", "#ffffff", "#ef4444")
        self.update_p2p_health_ui()
        self.update_orchestrator_cache_ui()

        self.txt_log.config(bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["log_fg"], font=("Menlo", self.log_font_size))

        # 动态刷新日志多色标签，确保浅色模式下具有绝佳的可读性与对比度
        if self.dark_mode:
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
            self.txt_log.tag_config("SEARCH_MATCH", background="#fbbf24", foreground="#000000")
        else:
            self.txt_log.tag_config("SPEEDTEST", foreground="#0284c7")
            self.txt_log.tag_config("REGISTER", foreground="#7c3aed")
            self.txt_log.tag_config("QUEUE", foreground="#b45309")
            self.txt_log.tag_config("TRAINING", foreground="#15803d")
            self.txt_log.tag_config("UPLOAD", foreground="#0f766e")
            self.txt_log.tag_config("EARNINGS", foreground="#b45309")
            self.txt_log.tag_config("WARN", foreground="#b45309")
            self.txt_log.tag_config("ERROR", foreground="#dc2626")
            self.txt_log.tag_config("WATCHDOG", foreground="#c026d3")
            self.txt_log.tag_config("CLEANUP", foreground="#c2410c")
            self.txt_log.tag_config("NORMAL", foreground="#1e293b")
            self.txt_log.tag_config("SEARCH_MATCH", background="#fde047", foreground="#000000")

    def toggle_coldkey_visibility(self):
        self.coldkey_visible = not self.coldkey_visible
        if self.coldkey_visible:
            self.entry_coldkey.config(show="")
            self.btn_toggle_ck.config(text="🙈 隐藏")
        else:
            if self.payout_coldkey and self.payout_coldkey != "检测中...":
                self.entry_coldkey.config(show="*")
            else:
                self.entry_coldkey.config(show="")
            self.btn_toggle_ck.config(text="👁️ 查看")

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
        now_ts = time.time()
        # 官方防频繁重启检查 (P2: 2 小时内重启 >= 2 次时弹窗提醒)
        recent_restarts = [t for t in self.restart_timestamps if now_ts - t < 7200]
        if len(recent_restarts) >= 2:
            ans = messagebox.askyesno(
                "官方防频繁重启提醒",
                f"⚠️ 检测到您在过去 2 小时内已重启了 {len(recent_restarts)} 次！\n\n"
                "官方指南明确指出：\n"
                "• 官方不建议反复重启！\n"
                "• 每次重启都要重新走一整个 epoch（5–60 分钟）的初始化与排队握手，过于频繁的重启只会更慢。\n\n"
                "是否仍要强制重启？"
            )
            if not ans:
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
            if os.path.exists(SYS_APP_PATH):
                subprocess.run(["open", SYS_APP_PATH])
            elif os.path.exists(USER_APP_PATH):
                subprocess.run(["open", USER_APP_PATH])
            else:
                subprocess.run(["open", "-a", APP_NAME])

            now_ts = time.time()
            self.last_restart_time = now_ts
            self.restart_timestamps = [t for t in self.restart_timestamps if now_ts - t < 86400] + [now_ts]
            self.config["restart_timestamps"] = self.restart_timestamps
            save_config(self.config)

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

            if os.path.exists(SYS_APP_PATH):
                subprocess.run(["open", SYS_APP_PATH])
            elif os.path.exists(USER_APP_PATH):
                subprocess.run(["open", USER_APP_PATH])
            else:
                subprocess.run(["open", "-a", APP_NAME])

            now_ts = time.time()
            self.last_restart_time = now_ts
            self.restart_timestamps = [t for t in self.restart_timestamps if now_ts - t < 86400] + [now_ts]
            self.config["restart_timestamps"] = self.restart_timestamps
            save_config(self.config)

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
        main_frame = tk.Frame(self.root, padx=12, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.widgets["main_frame"] = main_frame

        # ================= 1. 顶部 Header =================
        header_frame = tk.Frame(main_frame, bd=1, relief="solid", padx=12, pady=8)
        header_frame.pack(fill=tk.X, pady=(0, 8))
        self.widgets["card_header"] = header_frame

        top_row = tk.Frame(header_frame)
        top_row.pack(fill=tk.X)
        self.widgets["subcard_toprow"] = top_row

        title_lbl = tk.Label(top_row, text=f"IOTA Watchdog v{self.app_version} · Train at Home 智能监控控制台", font=self.font_title)
        title_lbl.pack(side=tk.LEFT)
        self.widgets["lbl_title_main"] = title_lbl

        # 守护状态标识紧跟标题
        self.lbl_watchdog_status = tk.Label(top_row, text="● 自动守护中", font=self.font_body_bold, fg="#16a34a", padx=8)
        self.lbl_watchdog_status.pack(side=tk.LEFT, padx=(6, 0))
        self.widgets["lbl_watchdog_status"] = self.lbl_watchdog_status

        # 右侧操作区：检查更新 + 深浅色主题切换 + 界面字号缩放
        self.btn_check_update = ModernButton(
            top_row,
            text="🔄 检查更新",
            command=lambda: threading.Thread(target=lambda: self._check_update_worker(manual=True), daemon=True).start(),
            bg_color="#4F46E5",
            fg_color="#ffffff",
            hover_bg="#4338CA",
            font=self.font_btn,
            padx=8,
            pady=3
        )
        self.btn_check_update.pack(side=tk.RIGHT, padx=(6, 0))
        self.widgets["btn_check_update"] = self.btn_check_update

        self.btn_theme = ModernButton(top_row, text="☀️ 浅色模式", command=self.toggle_theme, font=self.font_btn, padx=8, pady=3)
        self.btn_theme.pack(side=tk.RIGHT, padx=(6, 6))

        ui_font_frame = tk.Frame(top_row)
        ui_font_frame.pack(side=tk.RIGHT, padx=(6, 0))
        self.widgets["ui_font_frame"] = ui_font_frame

        self.btn_ui_font_inc = ModernButton(ui_font_frame, text="A+", command=lambda: self.change_ui_font_scale(5), font=self.font_btn, padx=6, pady=2)
        self.btn_ui_font_inc.pack(side=tk.RIGHT, padx=(2, 0))

        self.lbl_ui_font_display = tk.Label(ui_font_frame, text=f"{self.ui_font_scale}%", font=self.font_mono_bold)
        self.lbl_ui_font_display.pack(side=tk.RIGHT, padx=(3, 3))
        self.widgets["lbl_ui_font_display"] = self.lbl_ui_font_display

        self.btn_ui_font_dec = ModernButton(ui_font_frame, text="A-", command=lambda: self.change_ui_font_scale(-5), font=self.font_btn, padx=6, pady=2)
        self.btn_ui_font_dec.pack(side=tk.RIGHT, padx=(2, 2))

        lbl_ui_font_tag = tk.Label(ui_font_frame, text="界面缩放:", font=self.font_body)
        lbl_ui_font_tag.pack(side=tk.RIGHT, padx=(0, 2))
        self.widgets["lbl_ui_font_tag"] = lbl_ui_font_tag

        # 自动更新通知横幅 (默认隐藏)
        banner_update = tk.Frame(main_frame, bd=1, relief="solid", padx=12, pady=6)
        self.banner_update = banner_update
        self.widgets["banner_update"] = banner_update

        lbl_update_msg = tk.Label(banner_update, text="", font=self.font_body_bold, justify="left", anchor="w")
        lbl_update_msg.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_update_msg = lbl_update_msg
        self.widgets["lbl_update_msg"] = lbl_update_msg

        self.btn_update_now = ModernButton(banner_update, text="🚀 立即更新", command=self.perform_auto_update, bg_color="#4F46E5", fg_color="#ffffff", hover_bg="#4338CA", font=self.font_btn, padx=10, pady=3)
        self.btn_update_now.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_update_later = ModernButton(banner_update, text="稍后", command=self.hide_update_banner, bg_color="#64748B", fg_color="#ffffff", hover_bg="#475569", font=self.font_btn, padx=8, pady=3)
        self.btn_update_later.pack(side=tk.RIGHT, padx=(6, 0))

        self.btn_update_skip = ModernButton(banner_update, text="跳过此版本", command=self.skip_update_version, bg_color="#475569", fg_color="#cbd5e1", hover_bg="#334155", font=self.font_small, padx=8, pady=3)
        self.btn_update_skip.pack(side=tk.RIGHT, padx=(6, 0))
        self.banner_update.pack_forget()

        # 疑似僵尸状态告警横幅 (默认隐藏)
        banner_zombie = tk.Frame(main_frame, bd=1, relief="solid", padx=12, pady=8)
        self.banner_zombie = banner_zombie
        self.widgets["banner_zombie"] = banner_zombie

        lbl_zombie_msg = tk.Label(banner_zombie, text="", font=("Helvetica", 11, "bold"), justify="left", anchor="w")
        lbl_zombie_msg.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_zombie_msg = lbl_zombie_msg
        self.widgets["lbl_zombie_msg"] = lbl_zombie_msg

        btn_zombie_restart = ModernButton(banner_zombie, text="⚡ 考虑手动重启", command=self.manual_restart, bg_color="#dc2626", fg_color="#ffffff", hover_bg="#ef4444", font=self.font_btn, padx=10, pady=3)
        btn_zombie_restart.pack(side=tk.RIGHT, padx=(8, 0))
        self.btn_zombie_restart = btn_zombie_restart

        btn_zombie_guide = ModernButton(banner_zombie, text="📖 官方重启指南", command=lambda: webbrowser.open("https://www.trainathome.ai/en/guide/restart"), bg_color="#b45309", fg_color="#ffffff", hover_bg="#d97706", font=self.font_btn, padx=10, pady=3)
        btn_zombie_guide.pack(side=tk.RIGHT, padx=(8, 0))
        self.btn_zombie_guide = btn_zombie_guide
        self.banner_zombie.pack_forget()

        # ================= 2. 核心 KPI 快速仪表盘 (4 大功能卡片并排) =================
        card_kpi = tk.Frame(main_frame)
        card_kpi.pack(fill=tk.X, pady=(0, 8))
        self.widgets["card_kpi"] = card_kpi

        card_kpi.columnconfigure(0, weight=1, uniform="kpi")
        card_kpi.columnconfigure(1, weight=1, uniform="kpi")
        card_kpi.columnconfigure(2, weight=1, uniform="kpi")
        card_kpi.columnconfigure(3, weight=1, uniform="kpi")

        # KPI 1: 节点运行与阶段
        box_kpi1 = tk.Frame(card_kpi, bd=1, relief="solid", padx=10, pady=6)
        box_kpi1.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.widgets["subcard_kpi1"] = box_kpi1

        lbl_k1_t = tk.Label(box_kpi1, text="🟢 节点运行状态", font=self.font_kpi_title, anchor="w")
        lbl_k1_t.pack(fill=tk.X)
        self.widgets["lbl_kpi1_title"] = lbl_k1_t

        self.lbl_kpi_status_val = tk.Label(box_kpi1, text="检测中...", font=self.font_kpi_val, fg="#16a34a", anchor="w")
        self.lbl_kpi_status_val.pack(fill=tk.X, pady=(2, 1))
        self.widgets["lbl_kpi_status_val"] = self.lbl_kpi_status_val

        self.lbl_kpi_status_sub = tk.Label(box_kpi1, text="Layer: -- · Epoch: --", font=self.font_kpi_sub, fg="#64748b", anchor="w")
        self.lbl_kpi_status_sub.pack(fill=tk.X)
        self.widgets["lbl_kpi_status_sub"] = self.lbl_kpi_status_sub

        # KPI 2: 算力产出统计
        box_kpi2 = tk.Frame(card_kpi, bd=1, relief="solid", padx=10, pady=6)
        box_kpi2.grid(row=0, column=1, sticky="nsew", padx=(4, 4))
        self.widgets["subcard_kpi2"] = box_kpi2

        lbl_k2_t = tk.Label(box_kpi2, text="🔥 训练计算产出", font=self.font_kpi_title, anchor="w")
        lbl_k2_t.pack(fill=tk.X)
        self.widgets["lbl_kpi2_title"] = lbl_k2_t

        self.lbl_kpi_compute_val = tk.Label(box_kpi2, text="Fwd: 0 · Bwd: 0", font=self.font_kpi_val, fg="#2563eb", anchor="w")
        self.lbl_kpi_compute_val.pack(fill=tk.X, pady=(2, 1))
        self.widgets["lbl_kpi_compute_val"] = self.lbl_kpi_compute_val

        self.lbl_kpi_compute_sub = tk.Label(box_kpi2, text="链上: 0.00万 · 排名同步中", font=self.font_kpi_sub, fg="#64748b", anchor="w")
        self.lbl_kpi_compute_sub.pack(fill=tk.X)
        self.widgets["lbl_kpi_compute_sub"] = self.lbl_kpi_compute_sub

        # KPI 3: 本地网络实时流量与测速
        box_kpi3 = tk.Frame(card_kpi, bd=1, relief="solid", padx=10, pady=6)
        box_kpi3.grid(row=0, column=2, sticky="nsew", padx=(4, 4))
        self.widgets["subcard_kpi3"] = box_kpi3

        lbl_k3_t = tk.Label(box_kpi3, text="⚡ 本地实时网络流量", font=self.font_kpi_title, anchor="w")
        lbl_k3_t.pack(fill=tk.X)
        self.widgets["lbl_kpi3_title"] = lbl_k3_t

        self.lbl_kpi_net_val = tk.Label(box_kpi3, text="⬇ 0.0 KB/s   ⬆ 0.0 KB/s", font=self.font_kpi_val, fg="#0284c7", anchor="w")
        self.lbl_kpi_net_val.pack(fill=tk.X, pady=(2, 1))
        self.widgets["lbl_kpi_net_val"] = self.lbl_kpi_net_val

        self.lbl_kpi_net_sub = tk.Label(box_kpi3, text="测速: -- | P2P: 检测中", font=self.font_kpi_sub, fg="#64748b", anchor="w")
        self.lbl_kpi_net_sub.pack(fill=tk.X)
        self.widgets["lbl_kpi_net_sub"] = self.lbl_kpi_net_sub

        # KPI 4: 收益账单与当天市值估值
        box_kpi4 = tk.Frame(card_kpi, bd=1, relief="solid", padx=10, pady=6)
        box_kpi4.grid(row=0, column=3, sticky="nsew", padx=(4, 0))
        self.widgets["subcard_kpi4"] = box_kpi4

        lbl_k4_t = tk.Label(box_kpi4, text="💰 Subnet 9 收益估值", font=self.font_kpi_title, anchor="w")
        lbl_k4_t.pack(fill=tk.X)
        self.widgets["lbl_kpi4_title"] = lbl_k4_t

        self.lbl_kpi_earn_val = tk.Label(box_kpi4, text="0.000 IOTA", font=self.font_kpi_val, fg="#d97706", anchor="w")
        self.lbl_kpi_earn_val.pack(fill=tk.X, pady=(2, 1))
        self.widgets["lbl_kpi_earn_val"] = self.lbl_kpi_earn_val

        self.lbl_kpi_earn_sub = tk.Label(box_kpi4, text="正在同步链上结算...", font=self.font_kpi_sub, fg="#64748b", anchor="w")
        self.lbl_kpi_earn_sub.pack(fill=tk.X)
        self.widgets["lbl_kpi_earn_sub"] = self.lbl_kpi_earn_sub

        # ================= 3. 节点与身份紧凑卡片 (一行流线型展示) =================
        info_card = tk.Frame(main_frame, bd=1, relief="solid", padx=10, pady=5)
        info_card.pack(fill=tk.X, pady=(0, 8))
        self.widgets["card_info"] = info_card

        # Miner ID 紧凑显示
        lbl_tag_miner = tk.Label(info_card, text="Miner ID:", font=self.font_body_bold)
        lbl_tag_miner.pack(side=tk.LEFT)
        self.widgets["lbl_tag_miner"] = lbl_tag_miner

        self.lbl_miner_id_val = tk.Label(info_card, text="检测中...", font=self.font_mono_bold, fg="#2563eb", padx=4)
        self.lbl_miner_id_val.pack(side=tk.LEFT)
        self.widgets["lbl_miner_id_val"] = self.lbl_miner_id_val

        self.btn_copy_hk = ModernButton(info_card, text="📋", command=lambda: self.copy_to_clipboard(self.miner_hotkey, "Miner ID"), bg_color="#2563eb", fg_color="#ffffff", hover_bg="#3b82f6", font=self.font_btn, padx=5, pady=1)
        self.btn_copy_hk.pack(side=tk.LEFT, padx=(0, 10))

        # Coldkey 紧凑显示
        lbl_tag_coldkey = tk.Label(info_card, text="Coldkey:", font=self.font_body_bold)
        lbl_tag_coldkey.pack(side=tk.LEFT)
        self.widgets["lbl_tag_coldkey"] = lbl_tag_coldkey

        self.lbl_coldkey_val = tk.Label(info_card, text="••••••••••••", font=self.font_mono, fg="#64748b", padx=4)
        self.lbl_coldkey_val.pack(side=tk.LEFT)
        self.widgets["lbl_coldkey_val"] = self.lbl_coldkey_val

        self.btn_toggle_ck = ModernButton(info_card, text="👁️", command=self.toggle_coldkey_visibility, font=self.font_btn, padx=5, pady=1)
        self.btn_toggle_ck.pack(side=tk.LEFT, padx=(0, 2))

        self.btn_copy_ck = ModernButton(info_card, text="📋", command=lambda: self.copy_to_clipboard(self.payout_coldkey, "Payout Coldkey"), bg_color="#2563eb", fg_color="#ffffff", hover_bg="#3b82f6", font=self.font_btn, padx=5, pady=1)
        self.btn_copy_ck.pack(side=tk.LEFT, padx=(0, 10))

        # 元数据徽标
        self.lbl_layer = tk.Label(info_card, text="Layer: --", font=self.font_small, padx=6, pady=1, relief="groove")
        self.lbl_layer.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["lbl_badge_layer"] = self.lbl_layer

        self.lbl_epoch = tk.Label(info_card, text="Epoch: --", font=self.font_small, padx=6, pady=1, relief="groove")
        self.lbl_epoch.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["lbl_badge_epoch"] = self.lbl_epoch

        self.lbl_run_id = tk.Label(info_card, text="Run: --", font=self.font_small, padx=6, pady=1, relief="groove")
        self.lbl_run_id.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["lbl_badge_runid"] = self.lbl_run_id

        self.lbl_network = tk.Label(info_card, text="Subnet 9", font=self.font_small, padx=6, pady=1, relief="groove")
        self.lbl_network.pack(side=tk.LEFT, padx=(0, 6))
        self.widgets["lbl_badge_network"] = self.lbl_network

        # 唯一的多机云端监控入口（独立保留在此，参数栏冗余按钮已移除）
        self.btn_cloud_sync = ModernButton(info_card, text="☁️ 多机云端监控", command=self.open_cloud_sync_dialog, bg_color="#6366f1", fg_color="#ffffff", hover_bg="#4f46e5", font=self.font_btn, padx=8, pady=2)
        self.btn_cloud_sync.pack(side=tk.RIGHT)
        self.widgets["btn_cloud_sync"] = self.btn_cloud_sync

        # 兼容旧逻辑标签（供后台扫描函数无缝更新）
        self.entry_miner_id = tk.Entry(info_card)
        self.entry_coldkey = tk.Entry(info_card)

        # ================= 4. 链上收益与有效贡献双栏看板 =================
        payout_card = tk.LabelFrame(main_frame, text=" 📊 链上收益账单与有效 Token 贡献 (Subnet 9 链上结算) ", font=self.font_card_title, padx=10, pady=6)
        payout_card.pack(fill=tk.X, pady=(0, 8))
        self.widgets["card_payout"] = payout_card

        # 汇总数据条
        payout_top = tk.Frame(payout_card)
        payout_top.pack(fill=tk.X, pady=(0, 4))
        self.widgets["subcard_payout_top"] = payout_top

        self.lbl_payout_totals = tk.Label(payout_top, text="累计总赚取: 0.000 IOTA | 已结算到账: 0.000 IOTA | 待结转: 0.000 IOTA (起付门槛 0.4 IOTA)", font=self.font_body_bold, anchor="w")
        self.lbl_payout_totals.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.widgets["lbl_payout_totals"] = self.lbl_payout_totals

        self.btn_refresh_payout = ModernButton(payout_top, text="🔄 刷新收益", command=lambda: self.trigger_fetch_payout(manual=True), bg_color="#0284c7", fg_color="#ffffff", hover_bg="#0369a1", font=self.font_btn, padx=8, pady=2)
        self.btn_refresh_payout.pack(side=tk.RIGHT)

        # 左右双栏结构
        payout_cols = tk.Frame(payout_card)
        payout_cols.pack(fill=tk.X)
        self.widgets["subcard_payout_cols"] = payout_cols

        # 左栏：有效贡献统计（按时间日期降序）
        left_col = tk.Frame(payout_cols, bd=1, relief="groove", padx=8, pady=4)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self.widgets["subcard_payout_left"] = left_col

        lbl_dt_title = tk.Label(left_col, text="📈 有效 Token 贡献统计 (按时间降序排列):", font=self.font_body_bold, anchor="w")
        lbl_dt_title.pack(fill=tk.X)
        self.widgets["lbl_dt_title"] = lbl_dt_title

        self.lbl_daily_tokens = tk.Label(left_col, text="正在同步官方数据...", font=self.font_mono, justify="left", anchor="w")
        self.lbl_daily_tokens.pack(fill=tk.X, pady=(2, 0))
        self.widgets["lbl_daily_tokens"] = self.lbl_daily_tokens

        # 右栏：历史结算发放记录（含当天市值估算）
        right_col = tk.Frame(payout_cols, bd=1, relief="groove", padx=8, pady=4)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))
        self.widgets["subcard_payout_right"] = right_col

        lbl_ph_title = tk.Label(right_col, text="💰 历史结算发放记录 (按日到账 + 当天市值估算):", font=self.font_body_bold, anchor="w")
        lbl_ph_title.pack(fill=tk.X)
        self.widgets["lbl_ph_title"] = lbl_ph_title

        self.lbl_payout_history = tk.Label(right_col, text="正在同步官方数据...", font=self.font_mono, justify="left", anchor="w")
        self.lbl_payout_history.pack(fill=tk.X, pady=(2, 0))
        self.widgets["lbl_payout_history"] = self.lbl_payout_history

        # 倒计时、链上确认与指标参考栏
        payout_bottom_box = tk.Frame(payout_card)
        payout_bottom_box.pack(fill=tk.X, pady=(4, 0))
        self.widgets["subcard_payout_bottom"] = payout_bottom_box

        self.lbl_payout_countdown = tk.Label(payout_bottom_box, text="⏳ 结算倒计时: 距离下次结算还有 -- 小时 -- 分 (每天 20:00 EDT / UTC 00:00) | 本窗口增量: +0.00 万 Tokens", font=self.font_body_bold, fg="#0284c7", anchor="w")
        self.lbl_payout_countdown.pack(fill=tk.X)
        self.widgets["lbl_payout_countdown"] = self.lbl_payout_countdown

        self.lbl_chain_metrics = tk.Label(payout_bottom_box, text="● 链上已确认: 正在同步... | 本地估算: 0.00 万 Tokens | 全网排名: 检测中...", font=self.font_small, fg="#2563eb", anchor="w")
        self.lbl_chain_metrics.pack(fill=tk.X, pady=(1, 0))
        self.widgets["lbl_chain_metrics"] = self.lbl_chain_metrics

        self.lbl_network_health = tk.Label(payout_bottom_box, text="● Run 健康参考: 全网累计 token 趋势同步中...", font=self.font_small, fg="#64748b", anchor="w")
        self.lbl_network_health.pack(fill=tk.X, pady=(1, 0))
        self.widgets["lbl_network_health"] = self.lbl_network_health

        self.lbl_payout_glossary = tk.Label(payout_bottom_box, text="💡 术语说明: settled = 已发放到账 | pending = 未达 0.4 IOTA 起付线，攒着下次发 | forfeit = 当天 run 的 loss 没创新低、白干不补", font=self.font_small, fg="#64748b", anchor="w")
        self.lbl_payout_glossary.pack(fill=tk.X, pady=(1, 0))
        self.widgets["lbl_payout_glossary"] = self.lbl_payout_glossary

        # ================= 5. 控制快捷栏与可折叠参数配置 =================
        ctrl_frame = tk.Frame(main_frame)
        ctrl_frame.pack(fill=tk.X, pady=(0, 6))
        self.widgets["ctrl_frame"] = ctrl_frame

        self.btn_restart = ModernButton(ctrl_frame, text="⚡ 手动强制重启 IOTA", command=self.manual_restart, bg_color="#dc2626", fg_color="#ffffff", hover_bg="#ef4444", font=self.font_btn, padx=10, pady=3)
        self.btn_restart.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_clean_reset = ModernButton(ctrl_frame, text="🧹 一键深度清理重置", command=self.confirm_deep_clean, bg_color="#b45309", fg_color="#ffffff", hover_bg="#d97706", font=self.font_btn, padx=10, pady=3)
        self.btn_clean_reset.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_toggle = ModernButton(ctrl_frame, text="⏸ 暂停自动守护", command=self.toggle_monitoring, font=self.font_btn, padx=8, pady=3)
        self.btn_toggle.pack(side=tk.LEFT, padx=(0, 6))

        self.chk_caffeinate = tk.Checkbutton(ctrl_frame, text="☕ 防休眠常开", variable=self.caffeinate_var, font=self.font_body_bold, command=self.toggle_caffeinate)
        self.chk_caffeinate.pack(side=tk.LEFT, padx=(2, 6))
        self.widgets["chk_caffeinate_ctrl"] = self.chk_caffeinate

        # 可折叠高级参数配置切换按钮 (默认收起，点击展开)
        self.btn_toggle_cfg = ModernButton(ctrl_frame, text="⚙️ 守护参数设置 ▼", command=self.toggle_cfg_panel, font=self.font_btn, padx=8, pady=3)
        self.btn_toggle_cfg.pack(side=tk.LEFT, padx=(4, 0))

        # 参数配置面板 (可折叠，默认收起)
        cfg_frame = tk.Frame(main_frame, bd=1, relief="solid", padx=10, pady=5)
        self.card_cfg = cfg_frame
        self.widgets["card_cfg"] = cfg_frame

        lbl_c1 = tk.Label(cfg_frame, text="僵尸判定 (h):", font=self.font_body_bold)
        lbl_c1.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["cfg_lbl_c1"] = lbl_c1

        self.entry_zombie_stale = tk.Entry(cfg_frame, width=4, bd=1, relief="solid", font=self.font_body_bold, justify="center")
        self.entry_zombie_stale.insert(0, str(self.config.get("zombie_stale_hours", 2)))
        self.entry_zombie_stale.pack(side=tk.LEFT, padx=(0, 8), ipady=2)
        self.widgets["entry_zombie_stale"] = self.entry_zombie_stale

        lbl_c2 = tk.Label(cfg_frame, text="假死判定 (分):", font=self.font_body_bold)
        lbl_c2.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["cfg_lbl_c2"] = lbl_c2

        self.entry_max_stale = tk.Entry(cfg_frame, width=4, bd=1, relief="solid", font=self.font_body_bold, justify="center")
        self.entry_max_stale.insert(0, str(self.config.get("max_stale_minutes", 10)))
        self.entry_max_stale.pack(side=tk.LEFT, padx=(0, 8), ipady=2)
        self.widgets["entry_max_stale"] = self.entry_max_stale

        lbl_c3 = tk.Label(cfg_frame, text="冷却 (分):", font=self.font_body_bold)
        lbl_c3.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["cfg_lbl_c3"] = lbl_c3

        self.entry_cooldown = tk.Entry(cfg_frame, width=4, bd=1, relief="solid", font=self.font_body_bold, justify="center")
        self.entry_cooldown.insert(0, str(self.config.get("cooldown_minutes", 3)))
        self.entry_cooldown.pack(side=tk.LEFT, padx=(0, 8), ipady=2)
        self.widgets["entry_cooldown"] = self.entry_cooldown

        lbl_c4 = tk.Label(cfg_frame, text="日志保留 (天):", font=self.font_body_bold)
        lbl_c4.pack(side=tk.LEFT, padx=(0, 4))
        self.widgets["cfg_lbl_c4"] = lbl_c4

        self.entry_retention = tk.Entry(cfg_frame, width=4, bd=1, relief="solid", font=self.font_body_bold, justify="center")
        self.entry_retention.insert(0, str(self.config.get("log_retention_days", 2)))
        self.entry_retention.pack(side=tk.LEFT, padx=(0, 8), ipady=2)
        self.widgets["entry_retention"] = self.entry_retention

        self.btn_save = ModernButton(cfg_frame, text="💾 保存参数", command=self.apply_config, bg_color="#059669", fg_color="#ffffff", hover_bg="#10b981", font=self.font_btn, padx=8, pady=2)
        self.btn_save.pack(side=tk.LEFT)

        # 默认收起参数配置面板
        self.card_cfg.pack_forget()

        # ================= 6. 核心事件日志区域 (占满下半部分，自适应拉伸) =================
        log_frame = tk.LabelFrame(main_frame, text=" 核心事件日志 (自动换行已开启) ", font=self.font_card_title, padx=6, pady=4)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.widgets["card_log"] = log_frame

        # 日志顶部工具栏 (含搜索框、自动滚屏检测与阅读模式挂起)
        log_toolbar = tk.Frame(log_frame)
        log_toolbar.pack(fill=tk.X, pady=(0, 4))
        self.widgets["subcard_log_toolbar"] = log_toolbar

        self.chk_key_only = tk.Checkbutton(log_toolbar, text="只显核心事件", variable=self.filter_key_logs, font=self.font_body, command=self.on_filter_toggle)
        self.chk_key_only.pack(side=tk.LEFT, padx=(2, 4))
        self.widgets["chk_key_ctrl"] = self.chk_key_only

        self.chk_auto_scroll = tk.Checkbutton(log_toolbar, text="自动滚屏", variable=self.auto_scroll_var, font=self.font_body, command=self.on_scroll_toggle)
        self.chk_auto_scroll.pack(side=tk.LEFT, padx=(2, 4))
        self.widgets["chk_scroll_ctrl"] = self.chk_auto_scroll

        # 智能滚屏状态提示 (当用户向上滚动查看历史时，提示阅读模式已挂起)
        self.lbl_scroll_hint = tk.Label(log_toolbar, text="", font=self.font_small, fg="#f59e0b")
        self.lbl_scroll_hint.pack(side=tk.LEFT, padx=(4, 6))
        self.widgets["lbl_scroll_hint"] = self.lbl_scroll_hint

        # 右侧：日志搜索框 + 字号调节 + 清屏
        self.btn_clear_log = ModernButton(log_toolbar, text="清屏", command=self.clear_ui_log, font=self.font_btn, padx=6, pady=2)
        self.btn_clear_log.pack(side=tk.RIGHT, padx=(4, 0))

        font_frame = tk.Frame(log_toolbar)
        font_frame.pack(side=tk.RIGHT, padx=(4, 0))
        self.widgets["font_ctrl_frame"] = font_frame

        self.btn_font_inc = ModernButton(font_frame, text="A+", command=lambda: self.change_font_size(1), font=self.font_btn, padx=5, pady=1)
        self.btn_font_inc.pack(side=tk.RIGHT, padx=(2, 0))

        self.lbl_font_display = tk.Label(font_frame, text=f"{self.log_font_size}pt", font=self.font_mono_bold)
        self.lbl_font_display.pack(side=tk.RIGHT, padx=(2, 2))
        self.widgets["lbl_font_display"] = self.lbl_font_display

        self.btn_font_dec = ModernButton(font_frame, text="A-", command=lambda: self.change_font_size(-1), font=self.font_btn, padx=5, pady=1)
        self.btn_font_dec.pack(side=tk.RIGHT, padx=(2, 2))

        lbl_font_tag = tk.Label(font_frame, text="字号:", font=self.font_body)
        lbl_font_tag.pack(side=tk.RIGHT, padx=(0, 2))
        self.widgets["lbl_font_tag"] = lbl_font_tag

        # 日志关键词实时搜索条
        search_box = tk.Frame(log_toolbar)
        search_box.pack(side=tk.RIGHT, padx=(6, 8))
        self.widgets["subcard_search_box"] = search_box

        lbl_s_icon = tk.Label(search_box, text="🔍", font=self.font_small)
        lbl_s_icon.pack(side=tk.LEFT)
        self.widgets["lbl_search_icon"] = lbl_s_icon

        self.ent_search = tk.Entry(search_box, font=self.font_small, width=14, bd=1, relief="solid")
        self.ent_search.pack(side=tk.LEFT, padx=(2, 2), ipady=1)
        self.widgets["ent_search"] = self.ent_search
        self.ent_search.bind("<KeyRelease>", self.on_search_key)

        self.btn_clear_search = ModernButton(search_box, text="✕", command=self.clear_search, font=self.font_small, padx=4, pady=1)
        self.btn_clear_search.pack(side=tk.LEFT, padx=(1, 2))

        self.lbl_search_count = tk.Label(search_box, text="", font=self.font_small, fg="#64748b")
        self.lbl_search_count.pack(side=tk.LEFT)
        self.widgets["lbl_search_count"] = self.lbl_search_count

        # 核心日志多行显示控件
        self.txt_log = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=("Menlo", self.log_font_size), bd=0)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # 智能滚动监听：用户向上翻看日志时挂起自动滚屏，滚回底部自动恢复
        self.txt_log.bind("<MouseWheel>", self.on_log_scroll_event)
        self.txt_log.bind("<Button-4>", self.on_log_scroll_event)
        self.txt_log.bind("<Button-5>", self.on_log_scroll_event)
        self.txt_log.bind("<B1-Motion>", self.on_log_scroll_event)
        self.txt_log.bind("<ButtonRelease-1>", self.on_log_scroll_event)

        # 各种高亮配色标签
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
        self.txt_log.tag_config("SEARCH_MATCH", background="#fbbf24", foreground="#000000")

        # 兼容旧逻辑标签定义 (保留引用供原有扫描函数安全访问)
        self.lbl_proc_status = tk.Label(main_frame)
        self.lbl_log_time = tk.Label(main_frame)
        self.lbl_node_phase = tk.Label(main_frame)
        self.lbl_init_timer = tk.Label(main_frame)
        self.lbl_orchestrator = tk.Label(main_frame)
        self.lbl_epoch_status = tk.Label(main_frame)
        self.lbl_train_stats = tk.Label(main_frame)
        self.lbl_speed_info = tk.Label(main_frame)
        self.lbl_p2p_health = tk.Label(main_frame)

        self.append_watchdog_log("🚀 控制台已就绪！已开启实时排队位置探测、实时网络吞吐与资产估值监控。")

    def toggle_cfg_panel(self):
        """展开或收起高级参数设置面板"""
        self.cfg_expanded = not self.cfg_expanded
        if self.cfg_expanded:
            self.card_cfg.pack(before=self.widgets["card_log"], fill=tk.X, pady=(0, 6))
            self.btn_toggle_cfg.config(text="⚙️ 守护参数设置 ▲")
        else:
            self.card_cfg.pack_forget()
            self.btn_toggle_cfg.config(text="⚙️ 守护参数设置 ▼")

    def on_search_key(self, event=None):
        """实时关键词高亮并跳转匹配"""
        query = self.ent_search.get().strip()
        self.txt_log.tag_remove("SEARCH_MATCH", "1.0", tk.END)
        if not query:
            self.lbl_search_count.config(text="")
            return
        count = 0
        start_pos = "1.0"
        first_match = None
        while True:
            idx = self.txt_log.search(query, start_pos, nocase=True, stopindex=tk.END)
            if not idx:
                break
            if not first_match:
                first_match = idx
            end_idx = f"{idx}+{len(query)}c"
            self.txt_log.tag_add("SEARCH_MATCH", idx, end_idx)
            count += 1
            start_pos = end_idx
        if count > 0:
            self.lbl_search_count.config(text=f"({count}处)")
            if first_match:
                self.txt_log.see(first_match)
        else:
            self.lbl_search_count.config(text="(未找到)")

    def clear_search(self):
        """清除搜索关键词与高亮"""
        self.ent_search.delete(0, tk.END)
        self.txt_log.tag_remove("SEARCH_MATCH", "1.0", tk.END)
        self.lbl_search_count.config(text="")

    def on_log_scroll_event(self, event=None):
        """检测滚动条位置：用户向上滚动时挂起自动滚屏，滚到底部时恢复"""
        self.root.after(50, self._check_log_scroll_pos)

    def _check_log_scroll_pos(self):
        try:
            _, y_bottom = self.txt_log.yview()
            if y_bottom < 0.95:
                if not self.user_scrolled_away:
                    self.user_scrolled_away = True
                    self.lbl_scroll_hint.config(text="⏸ 阅读中(自动滚屏已暂停 - 滚回底部恢复)", fg="#f59e0b")
            else:
                if self.user_scrolled_away:
                    self.user_scrolled_away = False
                    self.lbl_scroll_hint.config(text="", fg="#10b981")
        except Exception:
            pass

    def on_filter_toggle(self):
        self.config["filter_key_logs_only"] = self.filter_key_logs.get()
        save_config(self.config)

    def on_scroll_toggle(self):
        enabled = self.auto_scroll_var.get()
        self.config["auto_scroll"] = enabled
        save_config(self.config)
        if enabled:
            self.user_scrolled_away = False
            self.lbl_scroll_hint.config(text="")
            self.txt_log.see(tk.END)

    def append_watchdog_log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] [WATCHDOG] {msg}\n"
        self._insert_text(line, "WATCHDOG")

    def update_miner_info_ui(self):
        def _update():
            if self.miner_hotkey and self.miner_hotkey != "检测中...":
                self.lbl_miner_id_val.config(text=self._shorten_id(self.miner_hotkey))
                self.entry_miner_id.config(state="normal")
                self.entry_miner_id.delete(0, tk.END)
                self.entry_miner_id.insert(0, self.miner_hotkey)
                self.entry_miner_id.config(state="readonly")

            if self.payout_coldkey and self.payout_coldkey != "检测中...":
                if self.coldkey_visible:
                    self.lbl_coldkey_val.config(text=self._shorten_id(self.payout_coldkey))
                else:
                    self.lbl_coldkey_val.config(text="••••••••••••")
                self.entry_coldkey.config(state="normal")
                self.entry_coldkey.delete(0, tk.END)
                self.entry_coldkey.insert(0, self.payout_coldkey)
                self.entry_coldkey.config(state="readonly")

            if self.current_layer and self.current_layer != "检测中...":
                self.lbl_layer.config(text=f"Layer: {self.current_layer}")
            if self.current_run_id and self.current_run_id != "检测中...":
                self.lbl_run_id.config(text=f"Run: {self.current_run_id}")
            if self.current_epoch and self.current_epoch != "检测中...":
                self.lbl_epoch.config(text=f"{self.current_epoch}")
            self.update_kpi_cards()

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
                        self.last_speedtest_time = datetime.now().strftime("%H:%M")
                        self.config["last_upload_speed"] = self.last_upload_speed
                        self.config["last_download_speed"] = self.last_download_speed
                        save_config(self.config)
                        self.update_speed_ui()
            except Exception:
                pass

        # 捕获掉线重置与未注册状态
        if "Miner not registered" in line_clean or "Resetting miner" in line_clean or "reset_miner_state" in line_clean:
            self.is_actively_training = False
            self.last_status = "queued"

        # 提取排队位置与注册队列状态 (例: 'status': 'queued', 'position': 1140)
        if "position" in line_clean and ("queued" in line_clean or "register" in line_clean or "status" in line_clean):
            self.is_actively_training = False
            self.last_status = "queued"
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
                    if self.forward_count > 0:
                        self.lbl_train_stats.config(
                            text=f"训练计算统计: ⏳ 待机排队中 (累计历史 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次，等待入队就绪)",
                            fg="#64748b" if not self.dark_mode else "#94a3b8"
                        )
                    else:
                        self.lbl_train_stats.config(text="训练计算统计: ⏳ 待机排队中 (等待全网各层握手对齐后自动触发训练)", fg="#64748b" if not self.dark_mode else "#94a3b8")
                    self.update_p2p_health_ui()
                self.root.after(0, _update_q)

        # 提取活跃邻居数与广播状态
        if "Broadcast peer status:" in line_clean:
            m = re.search(r"Broadcast peer status:\s*(\d+)/(\d+)\s*ok", line_clean)
            if m:
                ok = int(m.group(1))
                tot = int(m.group(2))
                self.p2p_last_ok_peers = ok
                self.p2p_last_total_peers = tot
                self.p2p_last_unreachable = max(0, tot - ok)
                self.p2p_last_broadcast_time = time.time()
                self.peer_mesh_status = f"{ok}/{tot} 在线"
                self.update_p2p_health_ui()

        # 监测 Forward 激活丢弃与 P2P 超时
        if "Failed to send forward activation" in line_clean or "Peer unreachable for forward activation" in line_clean:
            now = time.time()
            self.p2p_recent_drops.append(now)
            self.p2p_total_drops += 1
            self.update_p2p_health_ui()

        if "Peer status dict has" in line_clean:
            m = re.search(r"Peer status dict has (\d+) entries", line_clean)
            if m:
                self.active_peers_count = f"{m.group(1)} 个"
                now = time.time()
                if now - self.last_peer_log_time > 60:
                    self.last_peer_log_time = now
                    self._insert_text(f"[{datetime.now().strftime('%H:%M:%S')}] 📡 [P2P 握手] 当前 {self.current_layer} 已连接 {m.group(1)} 个活跃邻居节点 ({self.peer_mesh_status})\n", "SPEEDTEST")

        # 提取全网层就绪状态 (P1)
        if "request to /miner/all_layers_training" in line_clean:
            m = re.search(r"response:\s*(True|False)", line_clean)
            if m:
                self.all_layers_training_bool = (m.group(1) == "True")
                self.all_layers_ready = "全部层就绪 (True)" if self.all_layers_training_bool else "等待各层中 (False)"
                self.update_orchestrator_cache_ui()

        # 提取 Orchestrator 分配与激活状态 (P1 功能 3)
        if "No activations received from orchestrator" in line_clean or "Received activations: 0" in line_clean:
            self.orchestrator_status = "等待 orchestrator 分配"
            self.update_orchestrator_cache_ui()
        elif "Activation push RECV" in line_clean or "Downloaded activation" in line_clean:
            self.orchestrator_status = "正常接收激活中"
            self.last_activation_time = time.time()
            if self.current_epoch_num:
                self.last_activation_epoch = self.current_epoch_num
            self.update_orchestrator_cache_ui()

        # 提取 Cache 占用大小 (P1 功能 3)
        cache_m = re.search(r"(?:cache size of (\d+)|Cache size:\s*(\d+)/(\d+)|cache size:\s*(\d+))", line_clean)
        if cache_m:
            if cache_m.group(1):
                self.last_cache_size = int(cache_m.group(1))
                self.last_cache_max = 16
            elif cache_m.group(2) and cache_m.group(3):
                self.last_cache_size = int(cache_m.group(2))
                self.last_cache_max = int(cache_m.group(3))
            elif cache_m.group(4):
                self.last_cache_size = int(cache_m.group(4))
                self.last_cache_max = 16
            self.update_orchestrator_cache_ui()

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
                        ep_int = int(epoch)
                        if self.current_epoch_num != ep_int:
                            self.current_epoch_num = ep_int
                            self.epoch_start_time = time.time()
                        self.current_epoch = f"Epoch {ep_int}"
                    if run_id:
                        self.current_run_id = run_id
                    self.update_miner_info_ui()
                    self.update_orchestrator_cache_ui()

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
            self.orchestrator_status = "正常接收激活中"
            self.last_activation_time = time.time()
            if self.current_epoch_num:
                self.last_activation_epoch = self.current_epoch_num
            if not self.is_actively_training:
                self.is_actively_training = True
                self.queue_start_time = None
                self._insert_text(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🚀🚀🚀 [正式训练已开启] 收到激活数据并完成 Forward 计算！ 🚀🚀🚀\n\n", "TRAINING")
            self.root.after(0, lambda: self.lbl_train_stats.config(text=f"训练计算统计: 🔥 正在计算中！(已完成 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次)", fg="#15803d" if not self.dark_mode else "#4ade80"))
            self.update_orchestrator_cache_ui()
        elif "BACKWARD complete" in line_clean or "Backward pass" in line_clean:
            self.backward_count += 1
            if not self.is_actively_training:
                self.is_actively_training = True
                self.queue_start_time = None
                self._insert_text(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🚀🚀🚀 [正式训练已开启] 完成 Backward 反向传播梯度计算！ 🚀🚀🚀\n\n", "TRAINING")
            self.root.after(0, lambda: self.lbl_train_stats.config(text=f"训练计算统计: 🔥 正在计算中！(已完成 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次)", fg="#15803d" if not self.dark_mode else "#4ade80"))
            self.update_orchestrator_cache_ui()

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
        t_clean = text.strip()
        if t_clean:
            self.last_log_line = t_clean

        def _do():
            try:
                self.txt_log.insert(tk.END, text, tag)
                if self.auto_scroll_var.get():
                    self.txt_log.see(tk.END)
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            try:
                _do()
            except Exception:
                pass

    def clear_ui_log(self):
        self.txt_log.delete("1.0", tk.END)

    def apply_config(self):
        try:
            self.config["zombie_stale_hours"] = max(0.5, float(self.entry_zombie_stale.get().strip()))
            self.config["max_stale_minutes"] = max(2, int(self.entry_max_stale.get().strip()))
            self.config["cooldown_minutes"] = max(1, int(self.entry_cooldown.get().strip()))
            self.config["log_retention_days"] = max(1, int(self.entry_retention.get().strip()))
            self.log_retention_days = self.config["log_retention_days"]
            save_config(self.config)
            self.append_watchdog_log(f"✅ 参数已保存: 僵尸判定 {self.config['zombie_stale_hours']}h | 假死判定 {self.config['max_stale_minutes']}分 | 冷却 {self.config['cooldown_minutes']}分 | 日志保留 {self.config['log_retention_days']}天")
            messagebox.showinfo("成功", "配置已成功保存！")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字！")

    def get_miner_id(self):
        """获取链上唯一 Miner ID (ss58Address) 作为全局身份标识"""
        if hasattr(self, "miner_hotkey") and self.miner_hotkey and self.miner_hotkey != "检测中...":
            return self.miner_hotkey
        hk_file = os.path.expanduser("~/.bittensor/wallets/iota/hotkeys/iota_miner")
        if os.path.exists(hk_file):
            try:
                with open(hk_file, "r") as f:
                    hk_data = json.load(f)
                    if "ss58Address" in hk_data:
                        self.miner_hotkey = hk_data["ss58Address"]
                        return self.miner_hotkey
            except Exception:
                pass
        return ""

    def get_worker_identity(self):
        """以 Miner ID 作为唯一的云端节点识别键（无论机器别名如何修改，识别键永远唯一不变）"""
        mid = self.get_miner_id()
        if mid:
            return f"miner-{mid}"
        hostname = socket.gethostname().split(".")[0]
        return f"node-{hostname.lower()}"

    def get_current_telemetry_payload(self):
        """组装节点当前的全面监控遥测快照"""
        import socket
        miner_id = self.get_miner_id()
        proc_running, _ = self.check_process()
        phase = getattr(self, "current_layer", "待命")
        if hasattr(self, "lbl_node_phase"):
            lbl_txt = self.lbl_node_phase.cget("text")
            if "当前阶段:" in lbl_txt:
                phase = lbl_txt.replace("当前阶段:", "").strip()

        status = "training"
        if not proc_running:
            status = "stopped"
        elif self.last_queue_position is not None and self.last_queue_position > 0 and not getattr(self, "is_actively_training", False):
            status = "queueing"
        elif getattr(self, "is_actively_training", False):
            status = "training"
        else:
            status = "running"

        peers_num = 0
        if hasattr(self, "peer_mesh_status"):
            m = re.search(r"(\d+)", str(self.peer_mesh_status))
            if m:
                peers_num = int(m.group(1))

        recent_tokens = getattr(self, "last_6h_total_str", "") or "--"
        cycle_tokens = getattr(self, "cur_cycle_tokens_str", "") or "--"

        last_log = getattr(self, "last_log_line", "").strip()
        if not last_log:
            try:
                latest_log = self.get_latest_log()
                if latest_log and os.path.exists(latest_log):
                    with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
                        lines = [ln.strip() for ln in f.readlines()[-40:] if ln.strip()]
                        if lines:
                            last_log = lines[-1]
            except Exception:
                pass
        # 解析 layer, run_id, epoch
        layer = getattr(self, "current_layer", "")
        if not layer or "检测" in layer:
            if hasattr(self, "lbl_node_phase"):
                lbl_txt = self.lbl_node_phase.cget("text")
                m_l = re.search(r"Layer\s*\d+", lbl_txt, re.IGNORECASE)
                if m_l:
                    layer = m_l.group(0)

        epoch = getattr(self, "current_epoch", "")
        if not epoch or "检测" in epoch:
            if hasattr(self, "lbl_node_phase"):
                lbl_txt = self.lbl_node_phase.cget("text")
                m_e = re.search(r"Epoch\s*\d+", lbl_txt, re.IGNORECASE)
                if m_e:
                    epoch = m_e.group(0)

        run_id = getattr(self, "current_run_id", "")
        if not run_id or "检测" in run_id:
            try:
                for lf in sorted(glob.glob(os.path.join(LOG_DIR, "*cli.log")), reverse=True):
                    with open(lf, "r", errors="ignore") as f:
                        for l in f:
                            m_r = re.search(r"4\.12\.16\.\d+-tah", l)
                            if m_r:
                                run_id = m_r.group(0)
                                break
                    if run_id: break
            except Exception:
                pass

        if not last_log:
            last_log = "节点正常运行中"

        return {
            "miner_id": miner_id,
            "miner_hotkey": miner_id,
            "status": status,
            "phase": phase,
            "proc_running": proc_running,
            "layer": layer or "--",
            "run_id": run_id or "--",
            "epoch": epoch or "--",
            "queue_pos": self.last_queue_position or 0,
            "upload_speed": getattr(self, "last_upload_speed", "--"),
            "download_speed": getattr(self, "last_download_speed", "--"),
            "speedtest_time": getattr(self, "last_speedtest_time", ""),
            "peers_count": peers_num,
            "restart_count": getattr(self, "restart_count", 0),
            "recent_tokens": recent_tokens,
            "cycle_tokens": cycle_tokens,
            "hourly_tokens": getattr(self, "recent_hourly_tokens", []),
            "last_payout": getattr(self, "last_payout_info", {}),
            "next_payout": getattr(self, "next_payout_info", {}),
            "last_log": last_log
        }

    def _cloud_sync_loop(self):
        """后台守护线程：定时将状态同步至 GitHub 仓库供网页端集群监控"""
        first_sync = True
        time.sleep(3)
        while getattr(self, "running", True):
            try:
                if self.config.get("cloud_sync_enabled", False):
                    global iota_cluster_sync
                    if iota_cluster_sync is None:
                        try:
                            import iota_cluster_sync
                        except Exception:
                            pass
                    if iota_cluster_sync is None:
                        self.last_cloud_sync_msg = "iota_cluster_sync 模块未载入"
                    else:
                        payload = self.get_current_telemetry_payload()
                        sync_cfg = dict(self.config)
                        sync_cfg["worker_id"] = self.get_worker_identity()
                        ok, msg = iota_cluster_sync.upload_worker_status(sync_cfg, payload)
                        self.last_cloud_sync_time = time.time()
                        self.last_cloud_sync_msg = msg
                        if ok:
                            if first_sync:
                                self.append_watchdog_log(f"🌐 [云端监控] 状态已成功上报: {msg}")
                                first_sync = False
                        else:
                            self.append_watchdog_log(f"⚠️ [云端同步失败] {msg}")
            except Exception as e:
                self.last_cloud_sync_msg = str(e)
                self.append_watchdog_log(f"⚠️ [云端同步异常] {e}")

            interval = max(15, int(self.config.get("cloud_sync_interval_seconds", 60)))
            time.sleep(interval)

    def open_cloud_sync_dialog(self):
        """打开多机云端监控配置窗口"""
        try:
            import socket
            dlg = tk.Toplevel(self.root)
            dlg.title("🌐 多机云端监控配置 (Cyber Dashboard)")
            dlg.geometry("540x550")
            dlg.resizable(False, False)

            bg_main = "#0f172a" if self.dark_mode else "#f8fafc"
            fg_main = "#f1f5f9" if self.dark_mode else "#0f172a"
            entry_bg = "#1e293b" if self.dark_mode else "#ffffff"
            entry_fg = "#38bdf8" if self.dark_mode else "#0369a1"
            dlg.configure(bg=bg_main)

            container = tk.Frame(dlg, bg=bg_main, padx=20, pady=16)
            container.pack(fill=tk.BOTH, expand=True)

            tk.Label(container, text="🌐 GitHub 集群实时监控上报", font=("Helvetica", 14, "bold"), bg=bg_main, fg=fg_main).pack(anchor="w", pady=(0, 4))
            tk.Label(container, text="每台机器运行本程序并开启上报，即可在同一个 GitHub 网页中一览所有 Miner", font=("Helvetica", 10), bg=bg_main, fg="#94a3b8").pack(anchor="w", pady=(0, 14))

            has_saved_token = bool(self.config.get("github_token", "").strip())
            sync_var = tk.BooleanVar(value=self.config.get("cloud_sync_enabled", has_saved_token))
            chk_enable = tk.Checkbutton(container, text="开启本机自动上报至 GitHub 仓库", variable=sync_var, font=("Helvetica", 11, "bold"), bg=bg_main, fg="#10b981", activebackground=bg_main, selectcolor=entry_bg)
            chk_enable.pack(anchor="w", pady=(0, 10))

            fields = tk.Frame(container, bg=bg_main)
            fields.pack(fill=tk.X, pady=(0, 10))

            default_hostname = socket.gethostname().split(".")[0]
            tk.Label(fields, text="机器显示别名 (仅作为看板展示名称，如: 客厅 Mac Studio / MBP M3):", font=("Helvetica", 10, "bold"), bg=bg_main, fg=fg_main).pack(anchor="w", pady=(2, 2))
            ent_name = tk.Entry(fields, font=("Helvetica", 11), bg=entry_bg, fg=entry_fg, insertbackground=fg_main, bd=1, relief="solid")
            ent_name.insert(0, self.config.get("worker_name", "") or default_hostname)
            ent_name.pack(fill=tk.X, ipady=3, pady=(0, 3))

            cur_mid = self.get_miner_id()
            mid_txt = f"🆔 节点唯一身份 (Miner ID): {cur_mid}" if cur_mid else "🆔 节点唯一身份: 检测中 (以钱包 Miner Hotkey 为准)"
            tk.Label(fields, text=mid_txt, font=("Helvetica", 9), bg=bg_main, fg="#0ea5e9").pack(anchor="w", pady=(0, 8))

            token_label_frame = tk.Frame(fields, bg=bg_main)
            token_label_frame.pack(fill=tk.X, pady=(2, 2))
            tk.Label(token_label_frame, text="GitHub Personal Access Token (PAT):", font=("Helvetica", 10, "bold"), bg=bg_main, fg=fg_main).pack(side=tk.LEFT)

            token_frame = tk.Frame(fields, bg=bg_main)
            token_frame.pack(fill=tk.X, pady=(0, 8))
            ent_token = tk.Entry(token_frame, font=("Helvetica", 11), show="*", bg=entry_bg, fg=entry_fg, insertbackground=fg_main, bd=1, relief="solid")
            ent_token.insert(0, self.config.get("github_token", ""))
            ent_token.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)

            def _enable_clipboard(entry):
                def _paste(e=None):
                    try:
                        txt = dlg.clipboard_get()
                        if txt:
                            entry.delete(0, tk.END)
                            entry.insert(0, txt.strip())
                        return "break"
                    except Exception:
                        return None
                entry.bind("<Command-v>", _paste)
                entry.bind("<Command-V>", _paste)
                entry.bind("<Control-v>", _paste)

            _enable_clipboard(ent_name)
            _enable_clipboard(ent_token)

            def _toggle_token_visibility():
                if ent_token.cget("show") == "*":
                    ent_token.config(show="")
                    btn_view_token.config(text="🙈 隐藏")
                else:
                    ent_token.config(show="*")
                    btn_view_token.config(text="👁️ 显示")

            def _paste_token():
                try:
                    txt = dlg.clipboard_get().strip()
                    if txt:
                        ent_token.delete(0, tk.END)
                        ent_token.insert(0, txt)
                        lbl_msg.config(text="✅ 已从系统剪贴板粘贴 Token", fg="#10b981")
                except Exception as e:
                    lbl_msg.config(text=f"无法读取剪贴板: {e}", fg="#ef4444")

            btn_paste_token = tk.Button(token_frame, text="📋 粘贴", font=("Helvetica", 10), command=_paste_token, bg=entry_bg, fg=fg_main, relief="flat", bd=1)
            btn_paste_token.pack(side=tk.RIGHT, padx=(4, 0))

            btn_view_token = tk.Button(token_frame, text="👁️ 显示", font=("Helvetica", 10), command=_toggle_token_visibility, bg=entry_bg, fg=fg_main, relief="flat", bd=1)
            btn_view_token.pack(side=tk.RIGHT, padx=(4, 0))

            tk.Label(fields, text="GitHub 仓库名 (Owner/Repo):", font=("Helvetica", 10, "bold"), bg=bg_main, fg=fg_main).pack(anchor="w", pady=(2, 2))
            ent_repo = tk.Entry(fields, font=("Helvetica", 11), bg=entry_bg, fg=entry_fg, insertbackground=fg_main, bd=1, relief="solid")
            ent_repo.insert(0, self.config.get("github_repo", "oakvillechen/iota-train-at-home-watchdog"))
            ent_repo.pack(fill=tk.X, ipady=3, pady=(0, 8))
            _enable_clipboard(ent_repo)

            row_int = tk.Frame(fields, bg=bg_main)
            row_int.pack(fill=tk.X, pady=(2, 6))
            tk.Label(row_int, text="上报频率 (秒):", font=("Helvetica", 10, "bold"), bg=bg_main, fg=fg_main).pack(side=tk.LEFT)
            ent_interval = tk.Entry(row_int, width=6, font=("Helvetica", 11, "bold"), bg=entry_bg, fg=entry_fg, justify="center", bd=1, relief="solid")
            ent_interval.insert(0, str(self.config.get("cloud_sync_interval_seconds", 60)))
            ent_interval.pack(side=tk.LEFT, padx=(8, 12), ipady=2)
            tk.Label(row_int, text="(推荐 30~60 秒，避免频繁触发 Rate Limit)", font=("Helvetica", 10), bg=bg_main, fg="#94a3b8").pack(side=tk.LEFT)

            row_enc = tk.Frame(fields, bg=bg_main)
            row_enc.pack(fill=tk.X, pady=(2, 4))
            enc_var = tk.BooleanVar(value=self.config.get("cloud_encrypt_enabled", True))
            chk_enc = tk.Checkbutton(row_enc, text="🔐 开启端到端 AES-256 加密 (隐藏 Miner ID & 资产)", variable=enc_var, font=("Helvetica", 10, "bold"), bg=bg_main, fg=fg_main, selectcolor=entry_bg, activebackground=bg_main, activeforeground=fg_main)
            chk_enc.pack(anchor="w")

            row_pwd = tk.Frame(fields, bg=bg_main)
            row_pwd.pack(fill=tk.X, pady=(2, 8))
            tk.Label(row_pwd, text="解密密码:", font=("Helvetica", 10, "bold"), bg=bg_main, fg=fg_main).pack(side=tk.LEFT)
            ent_pwd = tk.Entry(row_pwd, width=16, font=("Helvetica", 11), bg=entry_bg, fg=entry_fg, bd=1, relief="solid")
            ent_pwd.insert(0, self.config.get("cloud_encrypt_password", "iota2026"))
            ent_pwd.pack(side=tk.LEFT, padx=(8, 12), ipady=2)
            tk.Label(row_pwd, text="(用于网页端解锁真实卡片，默认 iota2026)", font=("Helvetica", 10), bg=bg_main, fg="#94a3b8").pack(side=tk.LEFT)
            _enable_clipboard(ent_pwd)

            lbl_msg = tk.Label(container, text=f"状态: {getattr(self, 'last_cloud_sync_msg', '待就绪')}", font=("Helvetica", 11, "bold"), bg=bg_main, fg="#0ea5e9", wraplength=480, justify="left")
            lbl_msg.pack(anchor="w", pady=(4, 10))

            btn_bar = tk.Frame(container, bg=bg_main)
            btn_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

            def _do_test():
                token = ent_token.get().strip()
                # 如果输入框为空，尝试从已保存或 .github_token 中回退
                if not token:
                    token = self.config.get("github_token", "").strip()
                if not token:
                    token_f = os.path.join(LOG_DIR, ".github_token")
                    if os.path.exists(token_f):
                        try:
                            token = open(token_f).read().strip()
                        except Exception:
                            pass

                if not token:
                    lbl_msg.config(text="❌ 请先填入 GitHub Token (或点击右侧 📋 粘贴)！", fg="#ef4444")
                    return

                # UI 状态置为进行中
                lbl_msg.config(text="⏳ 正在连接 GitHub API 上报测试数据...", fg="#f59e0b")
                btn_test.config(text="⏳ 上报中...")
                dlg.update()

                w_name = ent_name.get().strip() or default_hostname
                temp_cfg = {
                    "github_token": token,
                    "github_repo": ent_repo.get().strip() or "oakvillechen/iota-train-at-home-watchdog",
                    "github_branch": self.config.get("github_branch", "main"),
                    "worker_name": w_name,
                    "worker_id": self.get_worker_identity(),
                    "miner_id": self.get_miner_id(),
                    "cloud_encrypt_enabled": enc_var.get(),
                    "cloud_encrypt_password": ent_pwd.get().strip() or "iota2026"
                }
                payload = self.get_current_telemetry_payload()

                def _async_worker():
                    try:
                        global iota_cluster_sync
                        if iota_cluster_sync is None:
                            try:
                                import iota_cluster_sync
                            except Exception as ex:
                                dlg.after(0, lambda e=str(ex): [
                                    lbl_msg.config(text=f"❌ 错误: 未能加载 iota_cluster_sync 模块 ({e})", fg="#ef4444"),
                                    btn_test.config(text="🚀 测试上报一次")
                                ])
                                return

                        ok, res_msg = iota_cluster_sync.upload_worker_status(temp_cfg, payload)
                        if ok:
                            old_id = self.config.get("worker_id")
                            if old_id and old_id != temp_cfg["worker_id"] and hasattr(iota_cluster_sync, "delete_worker_file"):
                                try:
                                    iota_cluster_sync.delete_worker_file(temp_cfg, old_id)
                                except Exception:
                                    pass
                            self.config["cloud_sync_enabled"] = True
                            self.config["github_token"] = temp_cfg["github_token"]
                            self.config["github_repo"] = temp_cfg["github_repo"]
                            self.config["worker_name"] = temp_cfg["worker_name"]
                            self.config["worker_id"] = temp_cfg["worker_id"]
                            self.config["miner_id"] = temp_cfg.get("miner_id", "")
                            self.config["cloud_encrypt_enabled"] = temp_cfg["cloud_encrypt_enabled"]
                            self.config["cloud_encrypt_password"] = temp_cfg["cloud_encrypt_password"]
                            save_config(self.config)
                            self.last_cloud_sync_time = time.time()
                            self.last_cloud_sync_msg = res_msg
                            self.append_watchdog_log(f"✅ [云端测试] {res_msg} (已上传至 data/{temp_cfg['worker_id']}.json 并自动激活后台同步)")
                            dlg.after(0, lambda: [
                                sync_var.set(True),
                                lbl_msg.config(text=f"✅ 测试成功并已自动开启持续同步！\n数据已推送到 {temp_cfg['github_repo']}/data/{temp_cfg['worker_id']}.json", fg="#10b981"),
                                btn_test.config(text="🚀 测试上报一次")
                            ])
                        else:
                            self.append_watchdog_log(f"⚠️ [云端测试失败] {res_msg}")
                            dlg.after(0, lambda: [
                                lbl_msg.config(text=f"❌ 上报失败: {res_msg}", fg="#ef4444"),
                                btn_test.config(text="🚀 测试上报一次")
                            ])
                    except Exception as err:
                        dlg.after(0, lambda: [
                            lbl_msg.config(text=f"❌ 网络请求异常: {err}", fg="#ef4444"),
                            btn_test.config(text="🚀 测试上报一次")
                        ])

                threading.Thread(target=_async_worker, daemon=True).start()

            def _do_save():
                old_w_id = self.config.get("worker_id", "")

                self.config["cloud_sync_enabled"] = sync_var.get()
                new_w_name = ent_name.get().strip()
                self.config["worker_name"] = new_w_name
                new_w_id = self.get_worker_identity()
                self.config["worker_id"] = new_w_id
                self.config["miner_id"] = self.get_miner_id()
                self.config["cloud_encrypt_enabled"] = enc_var.get()
                self.config["cloud_encrypt_password"] = ent_pwd.get().strip() or "iota2026"

                t_input = ent_token.get().strip()
                if t_input:
                    self.config["github_token"] = t_input
                self.config["github_repo"] = ent_repo.get().strip()
                try:
                    self.config["cloud_sync_interval_seconds"] = max(15, int(ent_interval.get().strip()))
                except ValueError:
                    self.config["cloud_sync_interval_seconds"] = 60
                save_config(self.config)

                # 若旧 ID 存在且与新 ID 不同（如旧版别名格式迁移），清理旧的节点文件
                if old_w_id and new_w_id and old_w_id != new_w_id:
                    cfg_copy = dict(self.config)
                    def _async_del_old():
                        try:
                            if iota_cluster_sync and hasattr(iota_cluster_sync, "delete_worker_file"):
                                iota_cluster_sync.delete_worker_file(cfg_copy, old_w_id)
                        except Exception:
                            pass
                    threading.Thread(target=_async_del_old, daemon=True).start()

                self.append_watchdog_log(f"💾 多机云同步配置已保存 (状态: {'开启' if sync_var.get() else '已禁用'}, 别名: {self.config['worker_name']}, 节点ID: {new_w_id})")
                dlg.destroy()

            def _open_dashboard():
                local_dash = os.path.join(LOG_DIR, "dashboard", "index.html")
                token = self.config.get("github_token", "").strip()
                token_hash = f"#token={token}" if token else ""
                if os.path.exists(local_dash):
                    webbrowser.open(f"file://{local_dash}{token_hash}")
                else:
                    repo = ent_repo.get().strip() or "oakvillechen/iota-train-at-home-watchdog"
                    user = repo.split("/")[0] if "/" in repo else "oakvillechen"
                    repo_name = repo.split("/")[1] if "/" in repo else "iota-train-at-home-watchdog"
                    webbrowser.open(f"https://{user}.github.io/{repo_name}/dashboard/{token_hash}")

            btn_open = ModernButton(btn_bar, text="🌐 打开监控看板", command=_open_dashboard, bg_color="#6366f1", fg_color="#ffffff", hover_bg="#4f46e5", font=("Helvetica", 10, "bold"), padx=10, pady=5)
            btn_open.pack(side=tk.LEFT)

            btn_test = ModernButton(btn_bar, text="🚀 测试上报一次", command=_do_test, bg_color="#0284c7", fg_color="#ffffff", hover_bg="#0ea5e9", font=("Helvetica", 10, "bold"), padx=10, pady=5)
            btn_test.pack(side=tk.LEFT, padx=(8, 0))

            btn_save = ModernButton(btn_bar, text="💾 保存并退出", command=_do_save, bg_color="#059669", fg_color="#ffffff", hover_bg="#10b981", font=("Helvetica", 10, "bold"), padx=12, pady=5)
            btn_save.pack(side=tk.RIGHT)
        except Exception as e:
            messagebox.showerror("打开配置窗口异常", f"无法打开多机云监控窗口:\n{e}")

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
            hk_file = os.path.expanduser("~/.bittensor/wallets/iota/hotkeys/iota_miner")
            if os.path.exists(hk_file):
                try:
                    with open(hk_file, "r") as f:
                        hk_data = json.load(f)
                        if "ss58Address" in hk_data:
                            self.miner_hotkey = hk_data["ss58Address"]
                except Exception:
                    pass

            out = subprocess.check_output(["ps", "aux"]).decode()
            for line in out.splitlines():
                if "main_pool:ai.macrocosmos.iota.tah.worker" in line:
                    coldkey_match = re.search(r"--payout-coldkey\s+([0-9A-Za-z]+)", line)
                    if coldkey_match:
                        self.payout_coldkey = coldkey_match.group(1)
                    break
            self.update_miner_info_ui()
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
                                initial_lines = all_lines[-300:]
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
                # 每 6 小时执行一次过期日志清理
                if time.time() - self.last_log_cleanup_time > 6 * 3600:
                    threading.Thread(target=self.cleanup_old_logs, daemon=True).start()
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

                # 刷新 P2P 广播与传输健康状态
                self.update_p2p_health_ui()

                # 定期刷新官方收益账单与每日贡献量（每 5 分钟）
                if now_ts - self.last_payout_fetch_time > 300:
                    self.last_payout_fetch_time = now_ts
                    self.trigger_fetch_payout(manual=False)

                # 假死检测（无任何日志输出）
                if stale_sec > self.config["max_stale_minutes"] * 60:
                    # 排队保护：排队期间不自动重启，避免丢失队列位置
                    is_in_queue = (self.last_queue_position is not None and 
                                   self.last_queue_position > 0 and 
                                   not self.is_actively_training and
                                   proc_running)
                    if is_in_queue:
                        stale_mins = int(stale_sec // 60)
                        pos = self.last_queue_position
                        self.root.after(0, lambda m=stale_mins, p=pos: [
                            self.lbl_node_phase.config(text=f"当前阶段: ⚠️ 日志 {m} 分钟无写入 (排队保护中)", fg="#d97706" if not self.dark_mode else "#fbbf24"),
                            self.lbl_init_timer.config(text=f"排队状态: 🛡️ 第 {p} 位 — 排队中跳过重启保护队列位置", fg="#d97706" if not self.dark_mode else "#fbbf24")
                        ])
                        # 每 10 分钟提醒一次，但不重启
                        if stale_mins % 10 == 0:
                            self.append_watchdog_log(f"🛡️ [排队保护] 日志已 {stale_mins} 分钟无写入，但当前排第 {pos} 位，跳过自动重启以保护队列位置")
                    else:
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

                # 从最近日志反向扫描提取最新状态与元数据（避免因单行日志截断导致丢失）
                latest_status = None
                latest_pos = None
                latest_queue_id = None
                latest_layer = None
                latest_epoch = None
                latest_run_id = None
                latest_phase = None

                for line in reversed(lines):
                    if not latest_status:
                        st_m = re.search(r"['\"]status['\"]\s*:\s*['\"]([^'\"]+)['\"]", line)
                        if st_m:
                            latest_status = st_m.group(1)
                    if latest_pos is None:
                        p_m = re.search(r"['\"]position['\"]\s*:\s*([0-9]+)", line)
                        if p_m:
                            latest_pos = int(p_m.group(1))
                    if not latest_queue_id:
                        q_m = re.search(r"['\"]queue_id['\"]\s*:\s*['\"]([^'\"]+)['\"]", line)
                        if q_m:
                            latest_queue_id = q_m.group(1)
                    if not latest_layer:
                        l_m = re.search(r"['\"]layer['\"]\s*:\s*([0-9]+)", line)
                        if l_m:
                            latest_layer = f"Layer {l_m.group(1)}"
                    if not latest_epoch:
                        ep_m = re.search(r"['\"]epoch['\"]\s*:\s*([0-9]+)", line)
                        if ep_m:
                            latest_epoch = f"Epoch {ep_m.group(1)}"
                    if not latest_run_id:
                        r_m = re.search(r"['\"]run_id['\"]\s*:\s*['\"]([^'\"]+)['\"]", line)
                        if r_m:
                            latest_run_id = r_m.group(1)
                    if not latest_phase:
                        ph_m = re.search(r"['\"]phase['\"]\s*:\s*['\"]([^'\"]+)['\"]", line)
                        if ph_m:
                            latest_phase = ph_m.group(1)

                if latest_layer:
                    self.current_layer = latest_layer
                if latest_epoch:
                    self.current_epoch = latest_epoch
                if latest_run_id:
                    self.current_run_id = latest_run_id
                if latest_phase:
                    self.current_phase = latest_phase
                if latest_pos is not None:
                    if self.last_queue_position is not None and self.last_queue_position != latest_pos:
                        self.prev_queue_position = self.last_queue_position
                    self.last_queue_position = latest_pos

                self.update_miner_info_ui()
                mesh_str = f"P2P 网格: {self.peer_mesh_status}" if self.peer_mesh_status != "检测中..." else f"邻居 {self.active_peers_count}"

                if latest_status == "queued" or (self.last_queue_position is not None and latest_status not in ["training", "running"]):
                    self.is_actively_training = False
                    self.last_status = "queued"
                    if self.queue_start_time is None:
                        self.queue_start_time = time.time()
                    wait_mins = (time.time() - self.queue_start_time) / 60
                    self.root.after(0, lambda w=wait_mins: [
                        self.lbl_node_phase.config(text=f"当前阶段: 🟡 队列排队中 ({self.current_layer})", fg="#d97706" if not self.dark_mode else "#fbbf24"),
                        self.lbl_init_timer.config(text=self.get_queue_status_text(w), fg="#d97706" if not self.dark_mode else "#fbbf24"),
                        self.lbl_train_stats.config(
                            text=f"训练计算统计: ⏳ 待机排队中 (累计历史 Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次，等待入队就绪)" if self.forward_count > 0 else "训练计算统计: ⏳ 待机排队中 (等待全网各层握手对齐后自动触发训练)",
                            fg="#64748b" if not self.dark_mode else "#94a3b8"
                        )
                    ])
                elif latest_status == "initializing":
                    self.is_actively_training = False
                    self.last_status = "initializing"
                    if self.queue_start_time is None:
                        self.queue_start_time = time.time()
                    wait_mins = (time.time() - self.queue_start_time) / 60
                    self.root.after(0, lambda m=mesh_str, w=wait_mins: [
                        self.lbl_node_phase.config(text=f"当前阶段: 🟡 队列握手中 ({self.current_layer} | {m})", fg="#d97706" if not self.dark_mode else "#fbbf24"),
                        self.lbl_init_timer.config(text=self.get_queue_status_text(w), fg="#d97706" if not self.dark_mode else "#fbbf24"),
                        self.lbl_train_stats.config(text="训练计算统计: ⏳ 待机排队中 (等待全网各层握手对齐后自动触发训练)", fg="#64748b" if not self.dark_mode else "#94a3b8")
                    ])
                elif latest_status in ["training", "running"] or self.is_actively_training:
                    self.queue_start_time = None
                    self.root.after(0, lambda: [
                        self.lbl_node_phase.config(text=f"当前阶段: 🚀 正式训练中 ({self.current_layer} | {self.current_epoch})", fg="#15803d" if not self.dark_mode else "#4ade80"),
                        self.lbl_init_timer.config(text="排队状态: 🔥 训练已正式开始 (已脱离排队，持续产出算力！)", fg="#15803d" if not self.dark_mode else "#4ade80"),
                        self.lbl_train_stats.config(text=f"训练计算统计: 🔥 算力全开计算中！(Forward: {self.forward_count} 次 | Backward: {self.backward_count} 次)", fg="#15803d" if not self.dark_mode else "#4ade80")
                    ])
                else:
                    self.root.after(0, lambda: [
                        self.lbl_node_phase.config(text=f"当前阶段: 🟢 活跃通信中 ({self.current_layer})", fg="#15803d" if not self.dark_mode else "#4ade80"),
                        self.lbl_init_timer.config(text="排队状态: 🟢 通信正常保持中", fg="#15803d" if not self.dark_mode else "#4ade80")
                    ])

            except Exception:
                pass

            time.sleep(self.config.get("check_interval_seconds", 15))

    # ---------------- 自动更新相关业务逻辑 ----------------
    def _check_update_worker(self, manual=False):
        """后台检查更新线程"""
        if not manual and not self.config.get("auto_check_update", True):
            return

        if not updater:
            if manual:
                self.root.after(0, lambda: messagebox.showwarning("检查更新", "updater 模块未加载，无法执行自动更新。"))
            return

        try:
            repo = self.config.get("github_repo", "oakvillechen/iota-train-at-home-watchdog")
            token = self.config.get("github_token") or None
            res = updater.check_for_updates(
                repo=repo,
                token=token,
                timeout=10,
                current_version=APP_VERSION
            )

            if res.get("error"):
                if manual:
                    self.root.after(0, lambda: messagebox.showwarning("检查更新", f"检查更新失败: {res.get('error')}"))
                return

            if not res.get("has_update"):
                if manual:
                    self.root.after(0, lambda: messagebox.showinfo("检查更新", f"当前已是最新版本 (v{res.get('local_version')})"))
                return

            remote_ver = res.get("remote_version")
            skipped_ver = self.config.get("skipped_version", "")
            if not manual and skipped_ver == remote_ver:
                return

            if not res.get("has_mac_zip"):
                self.root.after(0, lambda: self.append_watchdog_log(f"ℹ️ 发现新版本 v{remote_ver}，但暂无 macOS 构建包。"))
                if manual:
                    self.root.after(0, lambda: messagebox.showinfo("检查更新", f"发现新版本 v{remote_ver}，但 Release 中暂未挂载 macOS 构建包，请稍后再试。"))
                return

            self.pending_update_info = res
            self.root.after(0, lambda: self.show_update_banner(res))

        except Exception as e:
            if manual:
                self.root.after(0, lambda: messagebox.showerror("检查更新", f"更新检查发生异常: {e}"))

    def show_update_banner(self, info):
        """显示顶部更新提示横幅"""
        remote_v = info.get("remote_version", "")
        local_v = info.get("local_version", APP_VERSION)
        size_mb = round(info.get("zip_size", 0) / (1024 * 1024), 1)
        size_str = f" ({size_mb}MB)" if size_mb > 0 else ""

        self.lbl_update_msg.config(text=f"🚀 发现全新版本 v{remote_v}{size_str} (当前: v{local_v})，支持一键无感热更新！")
        self.btn_update_now.config(text="🚀 立即更新")
        self.btn_update_now.set_colors("#4F46E5", "#ffffff", "#4338CA")
        self.btn_update_now.command = self.perform_auto_update
        self.btn_update_later.pack(side=tk.RIGHT, padx=(6, 0))
        self.btn_update_skip.pack(side=tk.RIGHT, padx=(6, 0))

        target_widget = self.widgets.get("card_kpi")
        if target_widget and target_widget.winfo_exists() and target_widget.winfo_ismapped():
            self.banner_update.pack(before=target_widget, fill=tk.X, pady=(0, 8))
        else:
            self.banner_update.pack(fill=tk.X, pady=(0, 8))

    def hide_update_banner(self):
        """隐藏更新横幅"""
        self.banner_update.pack_forget()

    def skip_update_version(self):
        """跳过当前版本更新"""
        if hasattr(self, "pending_update_info") and self.pending_update_info:
            skipped = self.pending_update_info.get("remote_version", "")
            if skipped:
                self.config["skipped_version"] = skipped
                save_config(self.config)
                self.append_watchdog_log(f"已跳过版本 v{skipped} 的后续自动提示。")
        self.hide_update_banner()

    def perform_auto_update(self):
        """开始下载并自动更新"""
        if not hasattr(self, "pending_update_info") or not self.pending_update_info:
            return

        self.btn_update_now.config(text="⏳ 正在准备...")
        self.btn_update_now.command = None
        self.btn_update_later.pack_forget()
        self.btn_update_skip.pack_forget()

        threading.Thread(target=self._download_and_install_worker, daemon=True).start()

    def _download_and_install_worker(self):
        """后台下载、校验并部署线程"""
        info = self.pending_update_info
        remote_ver = info.get("remote_version")
        zip_url = info.get("zip_url")
        sha_url = info.get("sha_url")

        os.makedirs(updater.CACHE_DIR, exist_ok=True)
        dest_zip = os.path.join(updater.CACHE_DIR, f"IOTA-Watchdog-v{remote_ver}.zip")

        def _on_progress(pct, downloaded, total):
            mb_done = downloaded / (1024 * 1024)
            mb_tot = total / (1024 * 1024) if total > 0 else 0
            pct_int = int(pct * 100)
            txt = f"⬇️ 正在下载 v{remote_ver}... {pct_int}% ({mb_done:.1f}MB / {mb_tot:.1f}MB)"
            self.root.after(0, lambda: self.lbl_update_msg.config(text=txt))

        try:
            self.append_watchdog_log(f"⬇️ 开始下载更新包 v{remote_ver}...")
            updater.download_file_with_progress(zip_url, dest_zip, progress_callback=_on_progress)

            self.root.after(0, lambda: self.lbl_update_msg.config(text=f"🔒 正在校验 SHA256 完整性..."))
            self.append_watchdog_log(f"🔒 正在校验更新包 SHA256 签名...")
            if not updater.verify_file_sha256(dest_zip, sha_url):
                if os.path.exists(dest_zip):
                    os.remove(dest_zip)
                self.root.after(0, lambda: self._on_update_failed("更新包 SHA256 校验失败，文件可能已损坏，更新终止。"))
                return

            self.root.after(0, lambda: self.lbl_update_msg.config(text=f"📦 正在解压并更新版本链接..."))
            self.append_watchdog_log(f"📦 正在部署至 ~/Applications/IOTA-Watchdog/versions/{remote_ver} 并切换 Current 链接...")
            updater.install_and_symlink(dest_zip, remote_ver)

            self.root.after(0, lambda: self._on_update_ready(remote_ver))

        except Exception as e:
            self.root.after(0, lambda: self._on_update_failed(str(e)))

    def _on_update_ready(self, version):
        """更新部署完毕，通知用户重启"""
        self.lbl_update_msg.config(text=f"🎉 v{version} 已就绪！点击右侧按钮立即无缝切换新版。")
        self.btn_update_now.config(text="🔄 立即重启应用")
        self.btn_update_now.set_colors("#16a34a", "#ffffff", "#15803d")
        self.btn_update_now.command = self._do_restart_new_app
        self.append_watchdog_log(f"✅ 新版本 v{version} 已原子翻转就绪！请点击横幅重启应用。")

    def _do_restart_new_app(self):
        """退出当前程序并拉起新版本"""
        self.append_watchdog_log("🚀 正在退出并启动新版本 IOTA Watchdog...")
        try:
            updater.restart_to_new_app()
        except Exception as e:
            self.append_watchdog_log(f"❌ 自动重启失败: {e}，请通过 ~/Applications/IOTA-Watchdog/launcher.sh 手动启动。")
            messagebox.showerror("重启失败", f"无法自动启动新版: {e}\n请使用 ~/Applications/IOTA-Watchdog/launcher.sh 启动。")

    def _on_update_failed(self, err_msg):
        """更新失败回调"""
        self.lbl_update_msg.config(text=f"❌ 更新失败: {err_msg}")
        self.btn_update_now.config(text="重试")
        self.btn_update_now.set_colors("#dc2626", "#ffffff", "#b91c1c")
        self.btn_update_now.command = self.perform_auto_update
        self.btn_update_later.pack(side=tk.RIGHT, padx=(6, 0))
        self.append_watchdog_log(f"❌ 自动更新失败: {err_msg}")
        messagebox.showerror("更新失败", f"更新过程中遇到问题:\n{err_msg}")

if __name__ == "__main__":
    root = tk.Tk()
    app = IotaWatchdogApp(root)
    root.mainloop()
