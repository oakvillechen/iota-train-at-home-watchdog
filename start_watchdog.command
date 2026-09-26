#!/bin/bash
export TK_SILENCE_DEPRECATION=1
cd "$(dirname "$0")"
for py in /usr/local/bin/python3 /usr/bin/python3 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c "import tkinter" 2>/dev/null; then
        exec "$py" iota_watchdog_gui.py
    fi
done
exec python3 iota_watchdog_gui.py
