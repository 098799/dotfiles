#!/bin/bash
# Recording status/toggle for i3blocks
# Left-click: record window, Middle-click: record region, Right-click: record desktop

PIDFILE_WIN="/tmp/record-window.pid"
PIDFILE_DESK="/tmp/record-desktop.pid"
PIDFILE_REG="/tmp/record-region.pid"

case $BLOCK_BUTTON in
    1) alacritty -e ~/bin/record-window & ;;
    2) alacritty -e ~/bin/record-region & ;;
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
elif [[ -f "$PIDFILE_REG" ]] && kill -0 "$(cat "$PIDFILE_REG")" 2>/dev/null; then
    echo "󰻃 REC"
    echo "󰻃"
    echo "#dc322f"
else
    echo "󰻃"
    echo "󰻃"
fi
