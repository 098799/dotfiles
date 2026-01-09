#!/bin/bash
# CPU usage script for i3blocks
# Left-click: htop, Right-click: htop sorted by CPU

case $BLOCK_BUTTON in
    1) alacritty -e htop & ;;
    3) alacritty -e htop -s PERCENT_CPU & ;;
esac

# Read CPU stats
read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat

# Calculate total and idle
TOTAL=$((user + nice + system + idle + iowait + irq + softirq + steal))
IDLE=$idle

# Read previous values from fixed file
PREV_FILE="/tmp/.i3blocks_cpu_prev"
if [[ -f "$PREV_FILE" ]]; then
    read -r PREV_TOTAL PREV_IDLE < "$PREV_FILE"
else
    PREV_TOTAL=$TOTAL
    PREV_IDLE=$IDLE
fi

# Save current values
echo "$TOTAL $IDLE" > "$PREV_FILE"

# Calculate usage
DIFF_TOTAL=$((TOTAL - PREV_TOTAL))
DIFF_IDLE=$((IDLE - PREV_IDLE))

if [[ $DIFF_TOTAL -gt 0 ]]; then
    USAGE=$(awk "BEGIN {printf \"%.0f\", 100 * ($DIFF_TOTAL - $DIFF_IDLE) / $DIFF_TOTAL}")
else
    USAGE=0
fi

echo "󰍛 $USAGE%"
echo "󰍛 $USAGE%"

# Color based on usage
if [[ $USAGE -ge 90 ]]; then
    echo "#dc322f"
elif [[ $USAGE -ge 70 ]]; then
    echo "#cb4b16"
elif [[ $USAGE -ge 50 ]]; then
    echo "#b58900"
fi
