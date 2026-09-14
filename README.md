# IOTA Train at Home Watchdog & Monitor Console

> A real-time monitoring, auto-restart watchdog, and deep cleanup utility designed for **IOTA Train at Home** (Bittensor Subnet Miner) on macOS.

---

## ✨ Features

- 🟢 **Real-Time Queue Tracking**: Instantly parses `/miner/register/status` to show current position, previous position, movement delta (e.g. `⬆ 前进 115 位`), and total wait duration without duplication.
- ⚡ **Auto-Crash & Freeze Watchdog**: Detects deadlocks, silent log freezes, or process drops and automatically recovers the miner with launch protection cooldowns.
- ☕ **macOS Anti-Sleep (caffeinate)**: Keeps GPU/MPS and network operations running at full speed when the screen turns off.
- 📊 **Training & Mesh Metrics**: Tracks real-time P2P peer count, broadcast mesh status, speedtest bandwidth, and Forward / Backward step counts.
- 🧹 **One-Click Deep Cleanup & Reset**: Safely terminates background processes, wipes corrupt application cache/states/logs without deleting watchdog scripts, and restarts a fresh session.
- 🌙 **Modern Dark/Light UI**: Built with Tkinter, featuring customizable font sizes, log filtering, and one-click copy buttons for Hotkey / Coldkey.

---

## 🚀 Quick Start

### 1. Launch GUI Monitor
Simply double-click:
```bash
./start_watchdog.command
```
or run via Terminal:
```bash
python3 iota_watchdog_gui.py
```

### 2. CLI / Headless Mode
For headless or background terminal environments:
```bash
python3 iota_watchdog.py
```

### 3. One-Click Deep Clean & Reset
```bash
./clean_iota_tah.command
```
*(Or use the `🧹 一键深度清理重置` button inside the GUI console)*

---

## 🛠 File Structure

| File | Description |
|---|---|
| `iota_watchdog_gui.py` | Full Tkinter GUI watchdog console with real-time queue position parsing & control actions |
| `iota_watchdog.py` | CLI / Headless watchdog daemon |
| `start_watchdog.command` | Double-clickable macOS launcher script |
| `clean_iota_tah.command` | Deep cleanup script preserving watchdog tools |

---

## ⚙️ Requirements

- macOS with Python 3.8+
- Tkinter (`python3 -m tkinter`)
- IOTA Train at Home App installed (`/Applications/IOTA Train at Home.app`)
