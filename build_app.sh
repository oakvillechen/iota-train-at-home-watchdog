#!/bin/bash
set -e

cd "$(dirname "$0")"
echo "=== 🔨 Building IOTA Watchdog macOS App ==="

# Select python interpreter with PyInstaller
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
    --hidden-import iota_cluster_sync \
    iota_watchdog_gui.py

echo "Creating Zip bundle..."
cd dist
zip -r -q ../IOTA-Watchdog-macOS.zip "IOTA Watchdog.app"
cd ..

echo "✅ Build complete! Output: dist/IOTA Watchdog.app and IOTA-Watchdog-macOS.zip"
