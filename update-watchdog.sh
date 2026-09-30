#!/bin/bash
set -e

# ==========================================================
# update-watchdog.sh - IOTA Watchdog 一键升级 / 迁移脚本
# 适用: 命令行运行或双击运行。自动拉取最新 Release，建立版本管理结构。
# ==========================================================

REPO="oakvillechen/iota-train-at-home-watchdog"
BASE_DIR="$HOME/Applications/IOTA-Watchdog"
VERSIONS_DIR="$BASE_DIR/versions"
CACHE_DIR="$HOME/.cache/iota-watchdog/updates"

echo "============================================="
echo "  🚀 IOTA Watchdog 自动升级 & 迁移程序"
echo "============================================="

mkdir -p "$BASE_DIR" "$VERSIONS_DIR" "$CACHE_DIR"

echo "🔍 正在检查 GitHub 最新版本..."
RELEASE_JSON=$(curl -s "https://api.github.com/repos/$REPO/releases/latest")

TAG_NAME=$(echo "$RELEASE_JSON" | grep -m 1 '"tag_name":' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')
if [ -z "$TAG_NAME" ]; then
    echo "❌ 无法获取最新 Release 信息，请检查网络连接。"
    exit 1
fi

VERSION="${TAG_NAME#v}"
echo "✨ 最新可用版本: $TAG_NAME (v$VERSION)"

# 检查本地当前版本
CURRENT_VERSION=""
if [ -L "$BASE_DIR/Current" ]; then
    TARGET_LINK=$(readlink "$BASE_DIR/Current")
    CURRENT_VERSION=$(basename "$TARGET_LINK")
fi

if [ "$CURRENT_VERSION" = "$VERSION" ]; then
    echo "✅ 本地已经是最新版本 ($TAG_NAME)。"
    read -p "是否强制重新下载覆盖？(y/N): " -r FORCE_UPDATE
    if [[ ! $FORCE_UPDATE =~ ^[Yy]$ ]]; then
        echo "已取消升级。"
        exit 0
    fi
fi

# 寻找 zip 下载链接
ZIP_URL=$(echo "$RELEASE_JSON" | grep -i 'browser_download_url' | grep -i 'macos' | grep -i '\.zip' | head -n 1 | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/')
SHA_URL=$(echo "$RELEASE_JSON" | grep -i 'browser_download_url' | grep -i '\.sha256' | head -n 1 | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/')

if [ -z "$ZIP_URL" ]; then
    echo "⚠️ 最新 Release ($TAG_NAME) 尚未挂载 macOS 构建包。"
    exit 1
fi

# 安全校验：确保下载地址只来自本仓库官方 Release
if [[ "$ZIP_URL" != "https://github.com/$REPO/releases/"* ]]; then
    echo "❌ 安全拦截：下载地址非法 ($ZIP_URL)"
    exit 1
fi

ZIP_FILE="$CACHE_DIR/IOTA-Watchdog-$TAG_NAME.zip"
echo "⬇️  正在下载构建包: $ZIP_URL"
curl -L --progress-bar -o "$ZIP_FILE" "$ZIP_URL"

# SHA256 校验
if [ -n "$SHA_URL" ]; then
    echo "🔒 正在校验 SHA256 完整性..."
    SHA_EXPECTED=$(curl -sL "$SHA_URL" | awk '{print $1}')
    SHA_ACTUAL=$(shasum -a 256 "$ZIP_FILE" | awk '{print $1}')
    if [ "$SHA_EXPECTED" != "$SHA_ACTUAL" ]; then
        echo "❌ 校验失败！"
        echo "预期: $SHA_EXPECTED"
        echo "实际: $SHA_ACTUAL"
        rm -f "$ZIP_FILE"
        exit 1
    fi
    echo "✅ SHA256 校验通过。"
else
    echo "⚠️ Release 中未附带 .sha256 签名，跳过校验。"
fi

# 解压到 versions/<VERSION>/
TARGET_VER_DIR="$VERSIONS_DIR/$VERSION"
rm -rf "$TARGET_VER_DIR"
mkdir -p "$TARGET_VER_DIR"

echo "📦 正在解压至: $TARGET_VER_DIR ..."
TMP_DIR="$TARGET_VER_DIR/.tmp"
mkdir -p "$TMP_DIR"
unzip -q -o "$ZIP_FILE" -d "$TMP_DIR"

# 移动 .app
APP_FOUND=$(find "$TMP_DIR" -maxdepth 2 -name "*.app" | head -n 1)
if [ -z "$APP_FOUND" ]; then
    echo "❌ 解压包内未找到 .app 目录。"
    rm -rf "$TMP_DIR"
    exit 1
fi

mv "$APP_FOUND" "$TARGET_VER_DIR/IOTA Watchdog.app"
rm -rf "$TMP_DIR"
echo "$VERSION" > "$TARGET_VER_DIR/version.txt"

# 原子翻转 Current symlink
echo "🔄 正在切换 Current 链接 -> versions/$VERSION ..."
ln -sfn "versions/$VERSION" "$BASE_DIR/Current"

# 创建或更新 launcher.sh
cat << 'EOF' > "$BASE_DIR/launcher.sh"
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_APP="$DIR/Current/IOTA Watchdog.app"
if [ -d "$TARGET_APP" ]; then
    open -n "$TARGET_APP"
else
    echo "Error: Target app not found at $TARGET_APP"
    exit 1
fi
EOF
chmod +x "$BASE_DIR/launcher.sh"

# 清理旧版本 (保留最近 2 个)
cd "$VERSIONS_DIR"
VERSIONS_COUNT=$(ls -1d */ 2>/dev/null | wc -l | tr -d ' ')
if [ "$VERSIONS_COUNT" -gt 2 ]; then
    echo "🧹 清理旧版本缓存..."
    ls -1dt */ | tail -n +3 | xargs rm -rf
fi

echo "============================================="
echo "🎉 升级完成！当前版本: v$VERSION"
echo "📂 安装路径: $BASE_DIR/Current"
echo "🚀 启动入口: $BASE_DIR/launcher.sh"
echo "============================================="

# 关闭旧进程并拉起新版
pkill -f "IOTA Watchdog" 2>/dev/null || true
sleep 1
open -n "$BASE_DIR/Current/IOTA Watchdog.app"
echo "✅ 已拉起最新版本 IOTA Watchdog！"
