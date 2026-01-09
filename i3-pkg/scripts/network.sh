#!/bin/bash
# Network status script for i3blocks
# Shows WiFi or Ethernet status
# Right-click: open nmtui

case $BLOCK_BUTTON in
    3) alacritty -e nmtui & ;;
esac

# Check for active connections
WIFI_IF=$(ip link | grep -oP 'wl\w+' | head -1)
ETH_IF=$(ip link | grep -oP '(en|eth)\w+' | head -1)

# Check WiFi first
if [[ -n "$WIFI_IF" ]] && [[ -d "/sys/class/net/$WIFI_IF/wireless" ]]; then
    STATE=$(cat /sys/class/net/$WIFI_IF/operstate 2>/dev/null)
    if [[ "$STATE" == "up" ]]; then
        # Get SSID
        SSID=$(iwgetid -r 2>/dev/null || echo "WiFi")
        # Get signal quality
        QUALITY=$(iw dev $WIFI_IF link 2>/dev/null | grep 'signal' | awk '{print $2}')
        echo "󰖩 $SSID"
        echo "󰖩"
        if [[ -n "$QUALITY" ]]; then
            # Convert dBm to percentage for color
            PERCENT=$(awk "BEGIN {print int(($QUALITY + 100) * 2)}")
            [[ $PERCENT -gt 100 ]] && PERCENT=100
            [[ $PERCENT -lt 0 ]] && PERCENT=0
            if [[ $PERCENT -ge 70 ]]; then
                echo "#859900"
            elif [[ $PERCENT -ge 40 ]]; then
                echo "#b58900"
            else
                echo "#cb4b16"
            fi
        fi
        exit 0
    fi
fi

# Check Ethernet
if [[ -n "$ETH_IF" ]]; then
    STATE=$(cat /sys/class/net/$ETH_IF/operstate 2>/dev/null)
    if [[ "$STATE" == "up" ]]; then
        IP=$(ip addr show $ETH_IF | grep -oP 'inet \K[\d.]+' | head -1)
        echo "󰈀 $IP"
        echo "󰈀"
        echo "#859900"
        exit 0
    fi
fi

# No connection
echo "󰖪 Down"
echo "󰖪"
echo "#dc322f"
