#!/bin/bash
# VPN status script for i3blocks
# Detects WireGuard, OpenVPN, and other VPN connections
# Right-click: rofi menu to connect/disconnect

WG_DIR="$HOME/.config/wg"

case $BLOCK_BUTTON in
    3)
        eval $(xdotool getmouselocation --shell)
        # Detect current state for pre-selection
        if ip link show wg_1 &>/dev/null; then
            SELECTED=1
        elif ip link show wg_2 &>/dev/null; then
            SELECTED=2
        else
            SELECTED=0
        fi
        ACTION=$(echo -e "off\ntomek (wg_1)\ntomek2 (wg_2)" | rofi -dmenu -p "vpn" -selected-row $SELECTED -theme-str "window {width: 300px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 3;}")
        case $ACTION in
            off)
                alacritty -e bash -c "sudo wg-quick down $WG_DIR/wg_1.conf 2>/dev/null; sudo wg-quick down $WG_DIR/wg_2.conf 2>/dev/null; echo 'VPN disconnected'; sleep 1" &
                ;;
            "tomek (wg_1)")
                alacritty -e bash -c "sudo wg-quick down $WG_DIR/wg_2.conf 2>/dev/null; sudo wg-quick up $WG_DIR/wg_1.conf; sleep 1" &
                ;;
            "tomek2 (wg_2)")
                alacritty -e bash -c "sudo wg-quick down $WG_DIR/wg_1.conf 2>/dev/null; sudo wg-quick up $WG_DIR/wg_2.conf; sleep 1" &
                ;;
        esac
        ;;
esac

# Check for WireGuard interface
if ip link show wg_1 &>/dev/null; then
    echo "󰦝 wg1"
    echo "󰦝"
    echo "#859900"
    exit 0
elif ip link show wg_2 &>/dev/null; then
    echo "󰦝 wg2"
    echo "󰦝"
    echo "#859900"
    exit 0
fi

# Check for other WireGuard interfaces
WG_IF=$(ip link show type wireguard 2>/dev/null | grep -oP '^\d+: \K[^:]+')
if [[ -n "$WG_IF" ]]; then
    echo "󰦝 $WG_IF"
    echo "󰦝"
    echo "#859900"
    exit 0
fi

# Check for tun/tap interfaces (OpenVPN, etc.)
TUN_IF=$(ip link show | grep -oP '^\d+: \K(tun|tap)[^:]*' | head -1)

if [[ -n "$TUN_IF" ]]; then
    echo "󰦝 VPN"
    echo "󰦝"
    echo "#859900"
    exit 0
fi

# Check NetworkManager VPN connections
NM_VPN=$(nmcli con show --active 2>/dev/null | grep -i vpn)

if [[ -n "$NM_VPN" ]]; then
    echo "󰦝 VPN"
    echo "󰦝"
    echo "#859900"
    exit 0
fi

# No VPN detected
echo "󰦞 No VPN"
echo "󰦞"
echo "#b58900"
