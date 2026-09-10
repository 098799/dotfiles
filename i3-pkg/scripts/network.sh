#!/bin/bash
# Network status script for i3blocks
# Shows WiFi or Ethernet status
# Right-click: rofi menu (rescan, reconnect, reset adapter, nmtui)

WIFI_IF=$(ip link | grep -oP 'wl\w+' | head -1)
ETH_IF=$(ip link | grep -oP '(en|eth)\w+' | head -1)

# The module behind the wireless NIC, for the adapter reset. Derived rather
# than hardcoded, but /etc/sudoers.d/wifi-reset only grants mt7925e -- anything
# else falls through to a password prompt in the terminal, which is fine.
wifi_driver() {
    [[ -n "$WIFI_IF" ]] || return 1
    basename "$(readlink -f "/sys/class/net/$WIFI_IF/device/driver" 2>/dev/null)"
}

# Reset the adapter by reloading its driver, which reboots the card's firmware.
# This is the fix for the wedge where rx pins at VHT-MCS 0 (13 Mbit/s) while tx
# still negotiates MCS 9 -- it survives reconnecting and switching AP, because
# neither restarts the firmware. Runs in a terminal: the link drops for ~10s,
# and the before/after rates are the whole point of watching.
reset_adapter() {
    local mod=$1
    alacritty -e bash -c "
        echo 'Before:'; iw dev $WIFI_IF link 2>/dev/null | grep bitrate
        echo; echo 'Reloading $mod ...'
        sudo modprobe -r $mod && sleep 2 && sudo modprobe $mod || {
            echo 'FAILED'; read -rp 'Press enter to close...'; exit 1; }
        for i in \$(seq 20); do
            iw dev $WIFI_IF link 2>/dev/null | grep -q bitrate && break
            sleep 1
        done
        echo; echo 'After:'; iw dev $WIFI_IF link 2>/dev/null | grep bitrate
        echo; read -rp 'Press enter to close...'" &
}

case $BLOCK_BUTTON in
    3)
        eval "$(xdotool getmouselocation --shell)"
        MOD=$(wifi_driver)
        ACTION=$(echo -e "rescan\nlink rates\nreconnect\nreset adapter\nnmtui\nspeedtest" |
            rofi -dmenu -p "net" -theme-str "window {width: 220px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 6;}")
        case $ACTION in
            rescan)
                alacritty -e bash -c "nmcli dev wifi rescan 2>/dev/null; sleep 2; nmcli dev wifi list; read -rp 'Press enter to close...'" & ;;
            "link rates")
                alacritty -e bash -c "iw dev $WIFI_IF link; echo; iw dev $WIFI_IF station dump | grep -E 'signal|bitrate|tx retries|tx failed'; read -rp 'Press enter to close...'" & ;;
            reconnect)
                nmcli dev disconnect "$WIFI_IF" >/dev/null 2>&1
                nmcli dev connect "$WIFI_IF" >/dev/null 2>&1 & ;;
            "reset adapter")
                [[ -n "$MOD" ]] && reset_adapter "$MOD" ;;
            nmtui) alacritty -e nmtui & ;;
            speedtest)
                alacritty -e bash -c '
                    echo "Downloading 30 MB from Cloudflare..."; echo
                    read -r bps ttfb < <(curl -s -o /dev/null \
                        -w "%{speed_download} %{time_starttransfer}" \
                        "https://speed.cloudflare.com/__down?bytes=30000000")
                    bps=${bps%%.*}
                    # Both units on purpose: MB/s is what a download feels like,
                    # Mbit/s is what fast.com and every ISP quote.
                    printf "down: %s/s  (%sbit/s)\n" \
                        "$(numfmt --to=iec --suffix=B "$bps")" \
                        "$(numfmt --to=si $((bps * 8)))"
                    printf "ttfb: %s ms\n" \
                        "$(awk -v t="$ttfb" "BEGIN{printf \"%.0f\", t*1000}")"
                    echo; read -rp "Press enter to close..."' & ;;
        esac
        ;;
esac


# Check WiFi first
if [[ -n "$WIFI_IF" ]] && [[ -d "/sys/class/net/$WIFI_IF/wireless" ]]; then
    STATE=$(cat /sys/class/net/$WIFI_IF/operstate 2>/dev/null)
    if [[ "$STATE" == "up" ]]; then
        # Get SSID
        SSID=$(iwgetid -r 2>/dev/null || nmcli -t -f active,ssid dev wifi 2>/dev/null | grep '^yes' | cut -d: -f2 || echo "WiFi")
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
