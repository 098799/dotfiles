#!/bin/bash
# CPU boost toggle for i3blocks
# Left-click: toggle boost on/off

BOOST_PATH="/sys/devices/system/cpu/cpufreq/boost"

if [[ ! -f "$BOOST_PATH" ]]; then
    exit 0
fi

CURRENT=$(cat "$BOOST_PATH" 2>/dev/null)

case $BLOCK_BUTTON in
    1)
        if [[ "$CURRENT" == "1" ]]; then
            echo 0 | sudo tee "$BOOST_PATH" > /dev/null
            CURRENT=0
        else
            echo 1 | sudo tee "$BOOST_PATH" > /dev/null
            CURRENT=1
        fi
        # Refresh whichever bar is running. i3blocks is dead under niri, so the
        # click used to leave the reading stale until the next 30s tick;
        # waybar declares `signal: 13` for this module and takes the same
        # RTMIN offset. Signalling both keeps the i3 session working too.
        pkill -RTMIN+13 i3blocks 2>/dev/null
        pkill -RTMIN+13 waybar 2>/dev/null
        ;;
esac

if [[ "$CURRENT" == "1" ]]; then
    echo "󰓅"
    echo "󰓅"
    echo "#dc322f"
else
    echo "󰾆"
    echo "󰾆"
    echo "#2aa198"
fi
