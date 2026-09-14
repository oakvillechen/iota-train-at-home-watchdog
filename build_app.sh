#!/bin/bash
set -e

cd "$(dirname "$0")"
echo "=== 🔨 Building IOTA Watchdog macOS App ==="

# Check PyInstaller
if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

echo "Packaging IOTA Watchdog.app with custom icon..."
python3 -m PyInstaller --noconfirm --onedir --windowed \
    --name "IOTA Watchdog" \
    --icon "AppIcon.icns" \
    --add-data "icon.png:." \
    iota_watchdog_gui.py

echo "Creating Zip bundle..."
cd dist
zip -r -q ../IOTA-Watchdog-macOS.zip "IOTA Watchdog.app"
cd ..

echo "✅ Build complete! Output: dist/IOTA Watchdog.app and IOTA-Watchdog-macOS.zip"
