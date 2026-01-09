#!/bin/bash
# Volume control script for i3blocks
# Supports click actions: left=mute, scroll=adjust

# Handle click events
case $BLOCK_BUTTON in
    1) pactl set-sink-mute @DEFAULT_SINK@ toggle ;;  # left click - toggle mute
    3) pavucontrol & ;;  # right click - open mixer
    4) pactl set-sink-volume @DEFAULT_SINK@ +5% ;;   # scroll up
    5) pactl set-sink-volume @DEFAULT_SINK@ -5% ;;   # scroll down
esac

# Get volume info
VOLUME=$(pactl get-sink-volume @DEFAULT_SINK@ | grep -Po '\d+(?=%)' | head -1)
MUTED=$(pactl get-sink-mute @DEFAULT_SINK@ | grep -Po '(?<=Mute: )\w+')

if [[ "$MUTED" == "yes" ]]; then
    echo "󰖁 MUTE"
    echo "󰖁"
    echo "#dc322f"
else
    if [[ $VOLUME -ge 70 ]]; then
        ICON="󰕾"
    elif [[ $VOLUME -ge 30 ]]; then
        ICON="󰖀"
    else
        ICON="󰕿"
    fi
    echo "$ICON $VOLUME%"
    echo "$ICON $VOLUME%"

    # Color based on volume level
    if [[ $VOLUME -gt 100 ]]; then
        echo "#dc322f"
    fi
fi
