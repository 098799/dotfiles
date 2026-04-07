#!/bin/bash
# Uptime script for i3blocks
# Right-click: show boot analysis

case $BLOCK_BUTTON in
    3) alacritty -e bash -c "systemd-analyze blame | head -30; read -p 'Press enter to close...'" & ;;
esac

# Get uptime in seconds and show only the highest unit
SECS=$(awk '{print int($1)}' /proc/uptime)

if   (( SECS >= 86400 )); then echo "󰔟 $((SECS/86400))d"
elif (( SECS >= 3600 ));  then echo "󰔟 $((SECS/3600))h"
else                            echo "󰔟 $((SECS/60))m"
fi
