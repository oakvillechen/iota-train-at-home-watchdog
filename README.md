# IOTA Train at Home Watchdog & Monitor Console

> A real-time monitoring, auto-restart watchdog, and deep cleanup utility designed for **IOTA Train at Home** (Bittensor Subnet Miner) on macOS.

---

## ✨ Features

- 🟢 **Real-Time Queue Tracking**: Instantly parses `/miner/register/status` to show current position, previous position, movement delta (e.g. `⬆ 前进 115 位`), and total wait duration without duplication.
- ⚡ **Auto-Crash & Freeze Watchdog**: Detects deadlocks, silent log freezes, or process drops and automatically recovers the miner with launch protection cooldowns.
- ☕ **macOS Anti-Sleep (caffeinate)**: Keeps GPU/MPS and network operations running at full speed when the screen turns off.
- 📊 **Training & Mesh Metrics**: Tracks real-time P2P peer count, broadcast mesh status, speedtest bandwidth, and Forward / Backward step counts.
- 🧹 **One-Click Deep Cleanup & Reset**: Safely terminates background processes, wipes corrupt application cache/states/logs without deleting watchdog scripts, and restarts a fresh session.
- 🗑️ **Auto Expired Log Cleanup**: Automatically deletes log files older than the configured retention period (default: 2 days) on startup and every 6 hours. Logs each deletion with file size and total space reclaimed.
- 🌙 **Modern Dark/Light UI**: Built with Tkinter, featuring customizable font sizes, log filtering, and one-click copy buttons for Hotkey / Coldkey.

---

## 🚀 Quick Start

### Option A: macOS App (Recommended)

Download the latest `IOTA-Watchdog-macOS.zip`, unzip, and double-click **IOTA Watchdog.app**.

> **Note**: On first launch macOS may show a Gatekeeper warning. Right-click → Open to bypass.

### Option B: Launch GUI Monitor via Terminal

Simply double-click:
```bash
./start_watchdog.command
```
or run via Terminal:
```bash
python3 iota_watchdog_gui.py
```

### Option C: CLI / Headless Mode
For headless or background terminal environments:
```bash
python3 iota_watchdog.py
```

### One-Click Deep Clean & Reset
```bash
./clean_iota_tah.command
```
*(Or use the `🧹 一键深度清理重置` button inside the GUI console)*

---

## ⚙️ Configuration

All settings are saved in `watchdog_config.json` and editable from the GUI:

| Setting | Default | Description |
|---|---|---|
| `max_stale_minutes` | 10 | Minutes without log output before declaring the process frozen |
| `cooldown_minutes` | 3 | Minutes of restart protection cooldown after a restart |
| `log_retention_days` | 2 | Days to keep old log files before auto-deletion |
| `check_interval_seconds` | 15 | How often (seconds) to check process status |
| `caffeinate_enabled` | true | Keep macOS awake while running |
| `log_font_size` | 12 | Log viewer font size (adjustable via A+/A- buttons) |

---

## 🛠 File Structure

| File | Description |
|---|---|
| `iota_watchdog_gui.py` | Full Tkinter GUI watchdog console with real-time queue position parsing & control actions |
| `iota_watchdog.py` | CLI / Headless watchdog daemon |
| `start_watchdog.command` | Double-clickable macOS launcher script |
| `clean_iota_tah.command` | Deep cleanup script preserving watchdog tools |
| `build_app.sh` | Build script to package as macOS .app via PyInstaller |
| `AppIcon.icns` | macOS app icon |

---

## 🔨 Building from Source

```bash
./build_app.sh
```

Requires Python 3.8+ and PyInstaller (`pip3 install pyinstaller`).

Output: `dist/IOTA Watchdog.app` and `IOTA-Watchdog-macOS.zip`.

---

## ⚙️ Requirements

- macOS with Python 3.8+
- Tkinter (`python3 -m tkinter`)
- IOTA Train at Home App installed (`/Applications/IOTA Train at Home.app`)
