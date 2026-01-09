#!/bin/bash
# Microphone control script for i3blocks
# Supports click actions: left=mute toggle

# Handle click events
case $BLOCK_BUTTON in
    1|3) pactl set-source-mute @DEFAULT_SOURCE@ toggle ;;  # click - toggle mute
esac

# Get mic info
MUTED=$(pactl get-source-mute @DEFAULT_SOURCE@ | grep -Po '(?<=Mute: )\w+')

if [[ "$MUTED" == "yes" ]]; then
    echo "󰍭 OFF"
    echo "󰍭"
    echo "#dc322f"
else
    echo "󰍬 ON"
    echo "󰍬"
    echo "#859900"
fi
