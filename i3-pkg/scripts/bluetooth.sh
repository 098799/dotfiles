#!/bin/bash
# Bluetooth status script for i3blocks
# Right-click: rofi menu

# Handle click
case $BLOCK_BUTTON in
    3)
        eval $(xdotool getmouselocation --shell)
        ACTION=$(echo -e "bluetoothctl\npower on\npower off\nnuke_bt\nrestart logid" | rofi -dmenu -p "bt" -theme-str "window {width: 150px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 5;}")
        case $ACTION in
            bluetoothctl) alacritty -e bluetoothctl & ;;
            "power on") bluetoothctl power on 2>/dev/null ;;
            "power off") bluetoothctl power off 2>/dev/null ;;
            nuke_bt) alacritty -e bash -c "$HOME/bin/nuke_bt; read -p 'Press enter to close...'" & ;;
            "restart logid") alacritty -e bash -c "sudo systemctl restart logid; echo 'logid restarted'; sleep 1" & ;;
        esac
        ;;
esac

# Check if bluetooth is powered on
POWERED=$(bluetoothctl show 2>/dev/null | grep "Powered:" | awk '{print $2}')

if [[ "$POWERED" != "yes" ]]; then
    echo "󰂲 Off"
    echo "󰂲"
    echo "#657b83"
    exit 0
fi

# Get connected devices
CONNECTED=$(bluetoothctl devices Connected 2>/dev/null | head -1 | cut -d' ' -f3-)

if [[ -n "$CONNECTED" ]]; then
    # Shorten MX Master to MXM3
    if [[ "$CONNECTED" == "MX Master"* ]]; then
        CONNECTED="MXM3"
    fi
    echo "󰂱 $CONNECTED"
    echo "󰂱"
    echo "#859900"
else
    echo "󰂯 On"
    echo "󰂯"
    echo "#268bd2"
fi
