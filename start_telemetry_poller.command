#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"
echo "=================================================="
echo "  IOTA Telemetry Poller (Zero-Delay Local Daemon)"
echo "  按 Ctrl+C 可停止守护进程"
echo "=================================================="
python3 scripts/poll-daemon.py --interval 60
