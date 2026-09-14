#!/bin/bash
# ==============================================================================
# IOTA Train at Home - Complete Cleanup & Reset Script (macOS)
# ==============================================================================

echo "=================================================="
echo "🛑 Stopping IOTA Train at Home & miner processes..."
echo "=================================================="

pkill -9 -f "IOTA Train at Home" 2>/dev/null
pkill -9 -f "main_pool" 2>/dev/null
pkill -9 -f "iota-cli" 2>/dev/null

sleep 1

echo "=================================================="
echo "🧹 Removing application state, caches & configs..."
echo "=================================================="

# 1. Application Support & Settings (Electron state, preferences)
rm -rf "$HOME/Library/Application Support/IOTA Train at Home"

# 2. Caches & Updates
rm -rf "$HOME/Library/Caches/com.electron.iota-train-at-home"
rm -rf "$HOME/Library/Caches/com.electron.iota-train-at-home.ShipIt"
rm -rf "$HOME/Library/Caches/iota"* 2>/dev/null

# 3. Application Preferences & Saved State
rm -rf "$HOME/Library/Preferences/com.electron.iota-train-at-home.plist"
rm -rf "$HOME/Library/Saved Application State/com.electron.iota-train-at-home.savedState"

# 4. Miner Wallets, Identities & Payout Configs
rm -rf "$HOME/.bittensor/wallets/.pool_miner_payout.json"
rm -rf "$HOME/.bittensor/wallets/iota"
rm -rf "$HOME/.bittensor/miners"

# 5. Logs (Only .log files; preserves watchdog scripts)
rm -f "$HOME/Library/Logs/IOTA Train at Home"/*.log

echo "=================================================="
echo "✅ Cleanup complete! All residual data has been removed."
echo "🚀 You can now restart 'IOTA Train at Home' for a fresh session."
echo "=================================================="
