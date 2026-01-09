#!/bin/bash
# Battery indicator script for i3blocks
# Right-click: show detailed battery info

case $BLOCK_BUTTON in
    3) alacritty -e bash -c "upower -i /org/freedesktop/UPower/devices/battery_BAT0; read -p 'Press enter to close...'" & ;;
esac

# Find battery
BATTERY_PATH=""
for bat in /sys/class/power_supply/BAT*; do
    if [[ -d "$bat" ]]; then
        BATTERY_PATH="$bat"
        break
    fi
done

# No battery found (desktop)
if [[ -z "$BATTERY_PATH" ]]; then
    exit 0
fi

# Read battery info
CAPACITY=$(cat "$BATTERY_PATH/capacity" 2>/dev/null || echo "0")
STATUS=$(cat "$BATTERY_PATH/status" 2>/dev/null || echo "Unknown")

# Select icon based on capacity and status
if [[ "$STATUS" == "Charging" ]]; then
    ICON="󰂄"
elif [[ "$STATUS" == "Full" ]]; then
    ICON="󰁹"
elif [[ $CAPACITY -ge 80 ]]; then
    ICON="󰂁"
elif [[ $CAPACITY -ge 60 ]]; then
    ICON="󰁿"
elif [[ $CAPACITY -ge 40 ]]; then
    ICON="󰁽"
elif [[ $CAPACITY -ge 20 ]]; then
    ICON="󰁻"
else
    ICON="󰁺"
fi

echo "$ICON $CAPACITY%"
echo "$ICON $CAPACITY%"

# Color based on level
if [[ "$STATUS" == "Charging" ]]; then
    echo "#b58900"
elif [[ $CAPACITY -le 10 ]]; then
    echo "#dc322f"
elif [[ $CAPACITY -le 25 ]]; then
    echo "#cb4b16"
elif [[ $CAPACITY -le 50 ]]; then
    echo "#b58900"
fi
