#!/bin/bash
# User service status for i3blocks
# Left-click: restart, Right-click: menu

SERVICE="user"
SIGNAL=4

case $BLOCK_BUTTON in
    1) i3-msg -q "exec alacritty -e bash -c 'journalctl --user -u $SERVICE -f'"
       ;;
    3)
        eval $(xdotool getmouselocation --shell)
        ACTION=$(echo -e "restart\nstop\nlogs\nstatus" | rofi -dmenu -p "$SERVICE" -theme-str "window {width: 120px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 4;}")
        case $ACTION in
            restart) i3-msg -q "exec alacritty -e bash -c 'systemctl --user restart $SERVICE && sleep 1 && pkill -RTMIN+$SIGNAL i3blocks'" ;;
            stop) i3-msg -q "exec alacritty -e bash -c 'systemctl --user stop $SERVICE && sleep 1 && pkill -RTMIN+$SIGNAL i3blocks'" ;;
            logs) i3-msg -q "exec alacritty -e bash -c 'journalctl --user -u $SERVICE -f'" ;;
            status) i3-msg -q "exec alacritty -e bash -c 'systemctl --user status $SERVICE; read -p Press_enter...'" ;;
        esac
        ;;
esac

STATUS=$(systemctl --user is-active "$SERVICE" 2>/dev/null)

if [[ "$STATUS" == "active" ]]; then
    # Check logs since service started for errors
    START_TIME=$(systemctl --user show $SERVICE --property=ActiveEnterTimestamp --value)
    if journalctl --user -u $SERVICE --since "$START_TIME" --no-pager 2>/dev/null | grep -qiE "UNKNOWN_TOPIC"; then
        echo "󰒋 us"
        echo "󰒋"
        echo "#b58900"  # yellow - has errors
    else
        echo "󰒋 us"
        echo "󰒋"
        echo "#859900"  # green - healthy
    fi
else
    echo "󰒋 us"
    echo "󰒋"
    echo "#dc322f"
fi
