#!/bin/bash
# Disk usage script for i3blocks
# Right-click: show df -h in terminal

case $BLOCK_BUTTON in
    1) alacritty -e bash -c "sudo du -h / 2>/dev/null | sort -h | tail -50; read -p 'Press enter to close...'" & ;;
    3) alacritty -e bash -c "df -h; read -p 'Press enter to close...'" & ;;
esac

MOUNT="${BLOCK_INSTANCE:-/}"

# Get disk info
read -r _ SIZE USED AVAIL PERCENT _ < <(df -h "$MOUNT" | tail -1)

# Remove % sign
PERCENT_NUM=${PERCENT%\%}

echo "󰋊 $AVAIL"
echo "󰋊"

# Color based on usage
if [[ $PERCENT_NUM -ge 90 ]]; then
    echo "#dc322f"
elif [[ $PERCENT_NUM -ge 75 ]]; then
    echo "#cb4b16"
elif [[ $PERCENT_NUM -ge 60 ]]; then
    echo "#b58900"
fi
