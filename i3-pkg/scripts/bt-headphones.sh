#!/bin/bash
# Bluetooth headphones (WH-1000XM4) widget for i3blocks
# Left-click: toggle connect/disconnect

MAC="AC:80:0A:1C:DA:F3"
NAME="XM4"

case $BLOCK_BUTTON in
    1|3)
        eval $(xdotool getmouselocation --shell)
        if echo "info $MAC" | timeout 2 bluetoothctl 2>/dev/null | grep -q "Connected: yes"; then
            ACTION=$(echo -e "disconnect\ncancel" | rofi -dmenu -p "$NAME" -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 2;}")
            [[ "$ACTION" == "disconnect" ]] && bluetoothctl disconnect "$MAC" 2>/dev/null &
        else
            ACTION=$(echo -e "connect\ncancel" | rofi -dmenu -p "$NAME" -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 2;}")
            [[ "$ACTION" == "connect" ]] && bluetoothctl connect "$MAC" 2>/dev/null &
        fi
        ;;
esac

if echo "info $MAC" | timeout 2 bluetoothctl 2>/dev/null | grep -q "Connected: yes"; then
    echo "󰋋 $NAME"
    echo "󰋋"
    echo "#859900"
else
    echo "󰟎 $NAME"
    echo "󰟎"
    echo "#657b83"
fi
