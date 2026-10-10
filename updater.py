#!/usr/bin/env python3
"""
updater.py - IOTA Watchdog 自动更新引擎
遵循版本目录 + Current symlink 设计，支持后台检查、校验、无感安装与原子翻转切换。
"""
import os
import sys
import json
import time
import shutil
import hashlib
import zipfile
import urllib.request
import urllib.error
import ssl
import subprocess
from typing import Optional, Tuple, Callable, Dict, Any

try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

REPO_DEFAULT = "oakvillechen/iota-train-at-home-watchdog"
BASE_INSTALL_DIR = os.path.expanduser("~/Applications/IOTA-Watchdog")
CACHE_DIR = os.path.expanduser("~/.cache/iota-watchdog/updates")

def get_bundle_dir() -> str:
    """获取当前可执行文件或包所在目录"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包环境
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def get_local_version(fallback: str = "1.6.0") -> str:
    """读取本地版本号，优先读取 bundle 内的 version.txt"""
    search_paths = [
        os.path.join(get_bundle_dir(), "version.txt"),
        os.path.join(os.path.dirname(sys.executable), "version.txt"),
        os.path.join(os.path.dirname(sys.executable), "..", "Resources", "version.txt"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt"),
    ]
    for p in search_paths:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    if v:
                        return v.lstrip("v")
        except Exception:
            pass
    return fallback.lstrip("v")

def parse_version(v_str: str) -> Tuple[int, ...]:
    """将版本号字符串拆解为数字元组进行数学比较 (例如 1.10.0 > 1.4.0)"""
    cleaned = v_str.strip().lstrip("v")
    # 去除任何预发布后缀 (如 -beta, -rc1)
    base_v = cleaned.split("-")[0]
    nums = []
    for part in base_v.split("."):
        try:
            nums.append(int(part))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)

def is_newer_version(remote_v: str, local_v: str) -> bool:
    """比较远端与本地版本号"""
    return parse_version(remote_v) > parse_version(local_v)

def check_for_updates(
    repo: str = REPO_DEFAULT,
    token: Optional[str] = None,
    timeout: int = 10,
    current_version: Optional[str] = None
) -> Dict[str, Any]:
    """
    检查 GitHub Releases 最新版本。
    返回字典结构:
    {
        "has_update": bool,
        "remote_version": str,
        "local_version": str,
        "has_mac_zip": bool,
        "zip_url": Optional[str],
        "zip_size": int,
        "sha_url": Optional[str],
        "release_notes": str,
        "html_url": str,
        "error": Optional[str]
    }
    """
    local_ver = current_version or get_local_version()
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "IOTA-Watchdog-Updater"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return {"has_update": False, "error": f"HTTP {resp.status}"}
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 403 限流时，自动降级通过网页 302 重定向获取最新 tag (完全无 API 限流)
        try:
            web_url = f"https://github.com/{repo}/releases/latest"
            web_req = urllib.request.Request(web_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(web_req, timeout=timeout) as web_resp:
                final_url = web_resp.geturl()
                if "/releases/tag/" in final_url:
                    fallback_tag = final_url.split("/releases/tag/")[-1].strip()
                    remote_ver = fallback_tag.lstrip("v")
                    has_update = is_newer_version(remote_ver, local_ver)
                    return {
                        "has_update": has_update,
                        "remote_version": remote_ver,
                        "local_version": local_ver,
                        "has_mac_zip": True,
                        "zip_url": f"https://github.com/{repo}/releases/download/{fallback_tag}/IOTA-Watchdog-macOS.zip",
                        "zip_size": 0,
                        "sha_url": f"https://github.com/{repo}/releases/download/{fallback_tag}/IOTA-Watchdog-macOS.zip.sha256",
                        "release_notes": "",
                        "html_url": final_url,
                        "error": None
                    }
        except Exception:
            pass
        return {"has_update": False, "error": f"GitHub API {e.code}"}
    except Exception as e:
        return {"has_update": False, "error": str(e)}

    tag_name = data.get("tag_name", "").strip()
    remote_ver = tag_name.lstrip("v")
    if not remote_ver:
        return {"has_update": False, "error": "No tag name in release"}

    has_update = is_newer_version(remote_ver, local_ver)
    
    assets = data.get("assets", [])
    zip_url = None
    sha_url = None
    zip_size = 0

    expected_url_prefix = f"https://github.com/{repo}/releases/"

    for a in assets:
        name = a.get("name", "")
        dl_url = a.get("browser_download_url", "")
        # 安全规范：严格校验下载地址前缀，绝不从第三方地址下载
        if not dl_url.startswith(expected_url_prefix):
            continue

        # 必须匹配 macOS zip
        if name.endswith(".zip") and ("watchdog" in name.lower() or "macos" in name.lower()):
            zip_url = dl_url
            zip_size = a.get("size", 0)
        elif name.endswith(".sha256"):
            sha_url = dl_url

    has_mac_zip = bool(zip_url)

    return {
        "has_update": has_update,
        "remote_version": remote_ver,
        "local_version": local_ver,
        "has_mac_zip": has_mac_zip,
        "zip_url": zip_url,
        "zip_size": zip_size,
        "sha_url": sha_url,
        "release_notes": data.get("body", ""),
        "html_url": data.get("html_url", ""),
        "error": None
    }

def download_file_with_progress(
    url: str,
    dest_path: str,
    progress_callback: Optional[Callable[[float, int, int], None]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None
) -> bool:
    """下载文件并报告进度"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    temp_path = dest_path + ".downloading"

    req = urllib.request.Request(url, headers={"User-Agent": "IOTA-Watchdog-Updater"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 64 * 1024

            with open(temp_path, "wb") as f:
                while True:
                    if cancel_flag and cancel_flag():
                        f.close()
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        return False

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        pct = (downloaded / total_size) if total_size > 0 else 0.0
                        progress_callback(pct, downloaded, total_size)

        # 下载成功后重命名
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(temp_path, dest_path)
        return True
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e

def verify_file_sha256(file_path: str, sha_url: Optional[str]) -> bool:
    """下载并校验 SHA256 完整性"""
    if not sha_url:
        # Release 中未包含 sha256 校验文件时跳过校验
        return True

    try:
        req = urllib.request.Request(sha_url, headers={"User-Agent": "IOTA-Watchdog-Updater"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8").strip()
            # 格式通常为: "<hash>  IOTA-Watchdog-macOS.zip"
            expected_hash = content.split()[0].lower()
    except Exception as e:
        print(f"Warning: Failed to fetch sha256 from {sha_url}: {e}")
        return True

    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(128 * 1024):
            hasher.update(chunk)
    actual_hash = hasher.hexdigest().lower()

    if actual_hash != expected_hash:
        print(f"SHA256 mismatch! Expected: {expected_hash}, Actual: {actual_hash}")
        return False
    return True

def install_and_symlink(
    zip_path: str,
    target_version: str,
    install_base: str = BASE_INSTALL_DIR
) -> str:
    """
    解压至 versions/<target_version>/
    原子翻转 Current symlink -> versions/<target_version>
    生成 launcher.sh
    保留最近 2 个版本，其余自动清理
    返回解压后的 IOTA Watchdog.app 绝对路径
    """
    versions_dir = os.path.join(install_base, "versions")
    version_dest = os.path.join(versions_dir, target_version)
    os.makedirs(version_dest, exist_ok=True)

    # 1. 解压 zip
    temp_extract = os.path.join(version_dest, ".tmp_extract")
    if os.path.exists(temp_extract):
        shutil.rmtree(temp_extract)
    os.makedirs(temp_extract, exist_ok=True)

    # 优先使用 macOS 原生 ditto 解压以完好保留 Unix 权限和符号链接
    ditto_extracted = False
    try:
        subprocess.run(["ditto", "-xk", zip_path, temp_extract], check=True, stderr=subprocess.DEVNULL)
        ditto_extracted = True
    except Exception:
        pass

    if not ditto_extracted:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                zf.extract(member, temp_extract)
                mode = member.external_attr >> 16
                if mode:
                    extracted_file = os.path.join(temp_extract, member.filename)
                    if os.path.exists(extracted_file):
                        os.chmod(extracted_file, mode)

    # 寻找解压出的 .app 目录
    app_src = None
    for root, dirs, _ in os.walk(temp_extract):
        for d in dirs:
            if d.endswith(".app"):
                app_src = os.path.join(root, d)
                break
        if app_src:
            break

    if not app_src:
        shutil.rmtree(temp_extract)
        raise RuntimeError("更新包内未找到 macOS .app 应用程序包")

    final_app_path = os.path.join(version_dest, os.path.basename(app_src))
    if os.path.exists(final_app_path):
        shutil.rmtree(final_app_path)
    shutil.move(app_src, final_app_path)
    shutil.rmtree(temp_extract)

    # 强制修正 Contents/MacOS 下所有文件的执行权限 (+x)
    final_macos_dir = os.path.join(final_app_path, "Contents", "MacOS")
    if os.path.exists(final_macos_dir):
        for fname in os.listdir(final_macos_dir):
            fpath = os.path.join(final_macos_dir, fname)
            if os.path.isfile(fpath):
                os.chmod(fpath, os.stat(fpath).st_mode | 0o755)

    # 移除 Gatekeeper 隔离属性，防止系统拦截无法打开
    try:
        subprocess.run(["xattr", "-rd", "com.apple.quarantine", final_app_path], stderr=subprocess.DEVNULL)
    except Exception:
        pass

    # 写入版本号标记
    with open(os.path.join(version_dest, "version.txt"), "w", encoding="utf-8") as f:
        f.write(target_version)

    # 2. 原子翻转 Current symlink: Current -> versions/<target_version>
    current_symlink = os.path.join(install_base, "Current")
    relative_target = os.path.join("versions", target_version)
    
    # 在同一目录下创建临时符号链接再进行原子替换
    tmp_symlink = os.path.join(install_base, f".current_tmp_{int(time.time())}")
    if os.path.lexists(tmp_symlink):
        os.remove(tmp_symlink)
    os.symlink(relative_target, tmp_symlink)
    os.replace(tmp_symlink, current_symlink)

    # 3. 创建 launcher.sh (用户快捷启动入口)
    launcher_path = os.path.join(install_base, "launcher.sh")
    launcher_content = """#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_APP="$DIR/Current/IOTA Watchdog.app"
if [ -d "$TARGET_APP" ]; then
    open -n "$TARGET_APP"
else
    echo "Error: Target app not found at $TARGET_APP"
    exit 1
fi
"""
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(launcher_content)
    os.chmod(launcher_path, 0o755)

    # 4. 自动保留最近 2 个版本目录，其余清理
    try:
        all_vers = [d for d in os.listdir(versions_dir) if os.path.isdir(os.path.join(versions_dir, d))]
        all_vers.sort(key=lambda v: parse_version(v), reverse=True)
        for old_v in all_vers[2:]:
            old_path = os.path.join(versions_dir, old_v)
            if old_v != target_version:
                shutil.rmtree(old_path, ignore_errors=True)
    except Exception as e:
        print(f"Version prune warning: {e}")

    # 5. 同步更新 /Applications/IOTA Watchdog.app (如果存在且拥有写权限)
    sys_app = "/Applications/IOTA Watchdog.app"
    try:
        if os.path.exists(sys_app) and (os.access(sys_app, os.W_OK) or os.access("/Applications", os.W_OK)):
            shutil.rmtree(sys_app, ignore_errors=True)
            shutil.copytree(final_app_path, sys_app, symlinks=True)
            sys_macos_dir = os.path.join(sys_app, "Contents", "MacOS")
            if os.path.exists(sys_macos_dir):
                for fname in os.listdir(sys_macos_dir):
                    fpath = os.path.join(sys_macos_dir, fname)
                    if os.path.isfile(fpath):
                        os.chmod(fpath, os.stat(fpath).st_mode | 0o755)
            try:
                subprocess.run(["xattr", "-rd", "com.apple.quarantine", sys_app], stderr=subprocess.DEVNULL)
            except Exception:
                pass
    except Exception as e:
        print(f"Sync /Applications warning: {e}")

    return final_app_path

def restart_to_new_app(install_base: str = BASE_INSTALL_DIR):
    """
    安全退出当前进程并通过最新版 App 启动
    """
    running_path = None
    if getattr(sys, "frozen", False):
        exe_path = sys.executable
        if ".app/Contents/MacOS" in exe_path:
            candidate = exe_path.split(".app/Contents/MacOS")[0] + ".app"
            if os.path.exists(candidate):
                running_path = candidate

    target_app = running_path or os.path.join(install_base, "Current", "IOTA Watchdog.app")
    cmd = ["open", "-n", target_app]
    subprocess.Popen(cmd, start_new_session=True)
    time.sleep(0.5)
    os._exit(0)
