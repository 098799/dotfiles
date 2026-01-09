#!/bin/bash
# Memory usage script for i3blocks
# Left-click: htop sorted by memory, Right-click: free -h

case $BLOCK_BUTTON in
    1) alacritty -e htop -s PERCENT_MEM & ;;
    3) alacritty -e bash -c "free -h; read -p 'Press enter to close...'" & ;;
esac

# Read memory info (extract just the number, ignore unit)
TOTAL=$(grep MemTotal /proc/meminfo | awk '{print $2}')
AVAILABLE=$(grep MemAvailable /proc/meminfo | awk '{print $2}')

# Calculate used memory in GB
USED_KB=$((TOTAL - AVAILABLE))
USED_GB=$(awk "BEGIN {printf \"%.1f\", $USED_KB / 1024 / 1024}")
TOTAL_GB=$(awk "BEGIN {printf \"%.1f\", $TOTAL / 1024 / 1024}")
PERCENT=$(awk "BEGIN {printf \"%.0f\", 100 * $USED_KB / $TOTAL}")

echo "󰘚 ${USED_GB}G/${TOTAL_GB}G"
echo "󰘚 $PERCENT%"

# Color based on usage
if [[ $PERCENT -ge 90 ]]; then
    echo "#dc322f"
elif [[ $PERCENT -ge 75 ]]; then
    echo "#cb4b16"
elif [[ $PERCENT -ge 60 ]]; then
    echo "#b58900"
fi
