#!/bin/bash
# CPU temperature script for i3blocks

# Get CPU package temp from coretemp (integer only)
TEMP=$(sensors coretemp-isa-0000 2>/dev/null | grep "Package" | awk '{print int($4)}')

if [[ -z "$TEMP" ]]; then
    # Fallback to thermal zone
    TEMP=$(cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | sort -rn | head -1)
    TEMP=$((TEMP / 1000))
fi

echo "󰔏 ${TEMP}°C"
echo "󰔏 ${TEMP}°C"

# Color based on temp
if [[ $TEMP -ge 85 ]]; then
    echo "#dc322f"
elif [[ $TEMP -ge 70 ]]; then
    echo "#cb4b16"
elif [[ $TEMP -ge 60 ]]; then
    echo "#b58900"
fi
