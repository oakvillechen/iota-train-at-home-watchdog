#!/bin/bash
set -e

cd "$(dirname "$0")"
echo "=== 🔨 Building IOTA Watchdog macOS App ==="

# 1. 确定版本号
BUILD_VER="${APP_BUILD_VERSION:-}"
if [ -z "$BUILD_VER" ]; then
    if [ -f "version.txt" ]; then
        BUILD_VER=$(cat version.txt | tr -d ' \n\r' | sed 's/^v//')
    else
        BUILD_VER="1.6.0"
    fi
fi
echo "$BUILD_VER" > version.txt
echo "📦 Build Version: $BUILD_VER"

# 2. 选择可用的 Python 解释器
PY_BIN="python3"
for py in /usr/local/bin/python3 /opt/homebrew/bin/python3 python3; do
    if "$py" -m PyInstaller --version >/dev/null 2>&1; then
        PY_BIN="$py"
        break
    fi
done

echo "Packaging IOTA Watchdog.app with $PY_BIN..."
"$PY_BIN" -m PyInstaller --noconfirm --onedir --windowed \
    --name "IOTA Watchdog" \
    --icon "AppIcon.icns" \
    --add-data "icon.png:." \
    --add-data "version.txt:." \
    --add-data "iota_cluster_sync.py:." \
    --add-data "updater.py:." \
    --add-data "theme.py:." \
    --hidden-import iota_cluster_sync \
    --hidden-import theme \
    --hidden-import updater \
    --hidden-import urllib.request \
    --hidden-import urllib.error \
    --hidden-import ssl \
    iota_watchdog_gui.py

# 3. 注入 version.txt 及支持模块到 .app Bundle 目录
mkdir -p "dist/IOTA Watchdog.app/Contents/Resources"
mkdir -p "dist/IOTA Watchdog.app/Contents/MacOS"
cp version.txt iota_cluster_sync.py updater.py theme.py "dist/IOTA Watchdog.app/Contents/Resources/"
cp version.txt iota_cluster_sync.py updater.py theme.py "dist/IOTA Watchdog.app/Contents/MacOS/"

# 4. 创建 Zip bundle 与 SHA256 校验和
echo "Creating Zip bundle & SHA256 checksum..."
rm -f IOTA-Watchdog-macOS.zip IOTA-Watchdog-macOS.zip.sha256
cd dist
zip -r -q ../IOTA-Watchdog-macOS.zip "IOTA Watchdog.app"
cd ..

# 计算 sha256 校验和 (格式: "<hash>  IOTA-Watchdog-macOS.zip")
shasum -a 256 IOTA-Watchdog-macOS.zip > IOTA-Watchdog-macOS.zip.sha256

echo "✅ Build complete!"
echo "   - Bundle: dist/IOTA Watchdog.app"
echo "   - Zip:    IOTA-Watchdog-macOS.zip ($(du -h IOTA-Watchdog-macOS.zip | awk '{print $1}'))"
echo "   - SHA256: $(cat IOTA-Watchdog-macOS.zip.sha256)"
