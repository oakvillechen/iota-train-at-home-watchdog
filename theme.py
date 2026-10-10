#!/usr/bin/env python3
"""
theme.py - IOTA Watchdog 主题系统
支持 Light (默认，Linear/Vercel 风格)、Dark (深色极简)、Midnight-Neon (保留旧版赛博霓虹风)
"""
import os
import subprocess

THEMES = {
    "light": {
        # 语义色板
        "bg": "#F4F6FA",
        "card": "#FFFFFF",
        "card_sub": "#F8FAFC",
        "border": "#E6E9F0",
        "ink": "#141A26",
        "ink_2": "#5A6577",
        "ink_3": "#8B94A7",
        "indigo": "#4F46E5",
        "indigo_soft": "#ECEEFE",
        "green": "#0E9F6E",
        "green_soft": "#E3F6EE",
        "amber": "#C77414",
        "amber_soft": "#FDF0DC",
        "red": "#E02424",
        "red_soft": "#FDE8E8",
        # 控件兼容映射
        "bg_root": "#F4F6FA",
        "bg_card": "#FFFFFF",
        "bg_subcard": "#F8FAFC",
        "fg_title": "#141A26",
        "fg_text": "#141A26",
        "fg_muted": "#5A6577",
        "entry_bg": "#FFFFFF",
        "entry_fg": "#4F46E5",
        "btn_neutral_bg": "#ECEEFE",
        "btn_neutral_hover": "#E0E3FA",
        "btn_neutral_fg": "#4F46E5",
        "btn_exit_bg": "#E02424",
        "btn_exit_hover": "#C81E1E",
        "log_bg": "#FFFFFF",
        "log_fg": "#141A26",
    },
    "dark": {
        # 语义色板
        "bg": "#0B0D13",
        "card": "#12151F",
        "card_sub": "#171B26",
        "border": "#222839",
        "ink": "#EDEFF5",
        "ink_2": "#9AA3B5",
        "ink_3": "#626C82",
        "indigo": "#8B93F8",
        "indigo_soft": "#1D2338",
        "green": "#3DD598",
        "green_soft": "#142D26",
        "amber": "#F5A524",
        "amber_soft": "#2D2416",
        "red": "#F87171",
        "red_soft": "#2D1818",
        # 控件兼容映射
        "bg_root": "#0B0D13",
        "bg_card": "#12151F",
        "bg_subcard": "#171B26",
        "fg_title": "#EDEFF5",
        "fg_text": "#EDEFF5",
        "fg_muted": "#9AA3B5",
        "entry_bg": "#12151F",
        "entry_fg": "#8B93F8",
        "btn_neutral_bg": "#222839",
        "btn_neutral_hover": "#2E374D",
        "btn_neutral_fg": "#EDEFF5",
        "btn_exit_bg": "#DC2626",
        "btn_exit_hover": "#EF4444",
        "log_bg": "#07090E",
        "log_fg": "#E2E8F0",
    },
    "midnight-neon": {
        # 语义色板 (旧版霓虹黑夜主题，完整保留)
        "bg": "#040711",
        "card": "#080D1A",
        "card_sub": "#070B16",
        "border": "#00F2FE",
        "ink": "#FFFFFF",
        "ink_2": "#94A3B8",
        "ink_3": "#64748B",
        "indigo": "#00F2FE",
        "indigo_soft": "#0A2533",
        "green": "#00FF9D",
        "green_soft": "#072A1E",
        "amber": "#FFAA00",
        "amber_soft": "#2E2005",
        "red": "#FF0055",
        "red_soft": "#2F0512",
        # 控件兼容映射
        "bg_root": "#040711",
        "bg_card": "#080D1A",
        "bg_subcard": "#070B16",
        "fg_title": "#00F2FE",
        "fg_text": "#E2E8F0",
        "fg_muted": "#94A3B8",
        "entry_bg": "#050811",
        "entry_fg": "#00F2FE",
        "btn_neutral_bg": "#0E1A2E",
        "btn_neutral_hover": "#172A4B",
        "btn_neutral_fg": "#00F2FE",
        "btn_exit_bg": "#FF0055",
        "btn_exit_hover": "#FF3377",
        "log_bg": "#03060F",
        "log_fg": "#00F2FE",
    }
}

def detect_system_theme() -> str:
    """检测 macOS 系统当前的外观主题 (Dark / Light)"""
    try:
        out = subprocess.check_output(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            stderr=subprocess.STDOUT
        ).decode().strip()
        if "Dark" in out:
            return "dark"
    except Exception:
        pass
    return "light"

def get_theme(name: str = None) -> dict:
    """获取指定主题，若未指定则返回 light"""
    if not name or name not in THEMES:
        name = "light"
    return THEMES[name]
