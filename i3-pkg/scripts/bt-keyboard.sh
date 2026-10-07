#!/bin/bash
# Bluetooth keyboard (TOTEM) widget for i3blocks
# Left-click: toggle connect/disconnect

MAC="F8:99:5A:0D:01:33"
NAME="TOTEM"
ICON_ON=$(printf '\U000f030c')   # mdi-keyboard
ICON_OFF=$(printf '\U000f0330')  # mdi-keyboard-off

# Is $MAC connected? One shared bluetoothctl query for every bt block
# (see bt-state.sh); --fresh asks bluetoothd now, for a click.
connected() {
    "${BASH_SOURCE%/*}/bt-state.sh" "$@" | grep -q "^connected $MAC "
}

case $BLOCK_BUTTON in
    1|3)
        eval $(xdotool getmouselocation --shell)
        if connected --fresh; then
            ACTION=$(echo -e "disconnect\ncancel" | rofi -dmenu -p "$NAME" -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 2;}")
            [[ "$ACTION" == "disconnect" ]] && bluetoothctl disconnect "$MAC" 2>/dev/null &
        else
            ACTION=$(echo -e "connect\ncancel" | rofi -dmenu -p "$NAME" -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 2;}")
            [[ "$ACTION" == "connect" ]] && bluetoothctl connect "$MAC" 2>/dev/null &
        fi
        ;;
esac

if connected; then
    echo "$ICON_ON $NAME"
    echo "$ICON_ON"
    echo "#859900"
else
    echo "$ICON_OFF $NAME"
    echo "$ICON_OFF"
    echo "#657b83"
fi
