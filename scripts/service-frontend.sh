#!/bin/bash
# Frontend service status for i3blocks
# Left-click: restart, Right-click: menu

SERVICE="frontend"
SIGNAL=3

case $BLOCK_BUTTON in
    1) i3-msg -q "exec alacritty -e bash -c 'journalctl -u $SERVICE -f'"
       ;;
    3)
        eval $(xdotool getmouselocation --shell)
        ACTION=$(echo -e "restart\nstop\nlogs\nstatus" | rofi -dmenu -p "$SERVICE" -theme-str "window {width: 120px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 4;}")
        case $ACTION in
            restart) i3-msg -q "exec alacritty -e bash -c 'sudo systemctl restart $SERVICE && sleep 1 && pkill -RTMIN+$SIGNAL i3blocks'" ;;
            stop) i3-msg -q "exec alacritty -e bash -c 'sudo systemctl stop $SERVICE && sleep 1 && pkill -RTMIN+$SIGNAL i3blocks'" ;;
            logs) i3-msg -q "exec alacritty -e bash -c 'journalctl -u $SERVICE -f'" ;;
            status) i3-msg -q "exec alacritty -e bash -c 'systemctl status $SERVICE; read -p Press_enter...'" ;;
        esac
        ;;
esac

STATUS=$(systemctl is-active "$SERVICE" 2>/dev/null)

if [[ "$STATUS" == "active" ]]; then
    # Check last log line for build status
    LAST_LOG=$(journalctl -u $SERVICE -n 1 --no-pager 2>/dev/null)
    if echo "$LAST_LOG" | grep -qiE "compiling|building|bundling"; then
        echo "󰒋 fr"
        echo "󰒋"
        echo "#b58900"  # yellow - building
    else
        echo "󰒋 fr"
        echo "󰒋"
        echo "#859900"  # green - ready
    fi
else
    echo "󰒋 fr"
    echo "󰒋"
    echo "#dc322f"
fi
