#!/bin/bash
# Recording status/toggle for i3blocks
# Left-click: record window, Right-click: record desktop

PIDFILE_WIN="/tmp/record-window.pid"
PIDFILE_DESK="/tmp/record-desktop.pid"

case $BLOCK_BUTTON in
    1) alacritty -e ~/bin/record-window & ;;
    3) alacritty -e ~/bin/record-desktop & ;;
esac

# Check if recording
if [[ -f "$PIDFILE_WIN" ]] && kill -0 "$(cat "$PIDFILE_WIN")" 2>/dev/null; then
    echo "󰻃 REC"
    echo "󰻃"
    echo "#dc322f"
elif [[ -f "$PIDFILE_DESK" ]] && kill -0 "$(cat "$PIDFILE_DESK")" 2>/dev/null; then
    echo "󰻃 REC"
    echo "󰻃"
    echo "#dc322f"
else
    echo "󰻃"
    echo "󰻃"
fi
