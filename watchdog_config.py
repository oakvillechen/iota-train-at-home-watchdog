#!/usr/bin/env python3
"""
watchdog_config.py - Watchdog 配置读写

GitHub Token 保存在 macOS 钥匙串 (secret_store)，配置文件中不再保存明文 Token；
旧版本写在 watchdog_config.json 里的 Token 会在首次读取时自动迁移进钥匙串。
"""
import json
import os

try:
    import secret_store
except Exception:
    secret_store = None

LOG_DIR = os.path.expanduser("~/Library/Logs/IOTA Train at Home")
CONFIG_FILE = os.path.join(LOG_DIR, "watchdog_config.json")

# 最近一次与钥匙串同步过的 Token，避免每次保存配置都调用 security
_synced_token = None

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
    "cloud_sync_interval_seconds": 60,
    "telemetry_branch": "telemetry",
    "netlog_retention_days": 0
}


def _write_file(cfg: dict):
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def load_config() -> dict:
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    merged = {**DEFAULT_CONFIG, **cfg}

    global _synced_token
    file_token = (cfg.get("github_token") or "").strip()
    if secret_store:
        if file_token:
            if secret_store.set_token(file_token):
                _synced_token = file_token
                try:
                    _write_file({k: v for k, v in cfg.items() if k != "github_token"})
                except Exception:
                    pass
        else:
            merged["github_token"] = secret_store.get_token()
            _synced_token = merged["github_token"]
    return merged


def save_config(cfg: dict):
    global _synced_token
    try:
        to_write = dict(cfg)
        token = (to_write.get("github_token") or "").strip()
        if secret_store:
            if token == _synced_token:
                stored = True
            else:
                stored = secret_store.set_token(token) if token else secret_store.delete_token()
                if stored:
                    _synced_token = token
            # 钥匙串不可用时保留在配置文件中，保证上报功能不中断
            if stored:
                to_write.pop("github_token", None)
        _write_file(to_write)
    except Exception as e:
        print(f"Error saving config: {e}")
