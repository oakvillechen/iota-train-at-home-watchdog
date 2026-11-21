#!/usr/bin/env python3
"""
secret_store.py - 使用 macOS 钥匙串保存 GitHub Token，避免明文写入 watchdog_config.json
"""
import re
import subprocess

SERVICE = "IOTA Watchdog GitHub Token"
ACCOUNT = "github_token"
SECURITY = "/usr/bin/security"

# GitHub token 只包含这些字符；限制字符集以便安全地放入 `security -i` 命令行
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")


def get_token() -> str:
    try:
        out = subprocess.run(
            [SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def set_token(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return delete_token()
    if not _TOKEN_RE.match(token):
        return False
    # 通过 stdin 交给 `security -i`，避免 token 出现在 ps 可见的进程参数里
    cmd = f'add-generic-password -U -a "{ACCOUNT}" -s "{SERVICE}" -w "{token}"\n'
    try:
        out = subprocess.run([SECURITY, "-i"], input=cmd, capture_output=True, text=True, timeout=10)
        return out.returncode == 0 and get_token() == token
    except Exception:
        return False


def delete_token() -> bool:
    try:
        subprocess.run(
            [SECURITY, "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE],
            capture_output=True, timeout=10,
        )
        return True
    except Exception:
        return False
