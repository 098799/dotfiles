#!/bin/bash
# CPU frequency cap for i3blocks (intel_pstate hosts only, e.g. p340)
# Left-click:  rofi menu to pick the cap
# Right-click: quick toggle between quiet (80) and full (100)
#
# The i9-10900K voltage curve turns sharply above ~4.3 GHz. Measured on p340
# with a 2-thread burst: 100%=5.0GHz/84C/57W, 80%=4.3GHz/70C/31W for only
# 13% less throughput. 90% buys nothing at all -- same power, same heat.
#
# On AMD hosts (p14s) intel_pstate does not exist and this block hides itself,
# exactly as cpu-boost.sh and power-profile.sh hide themselves here.

PSTATE="/sys/devices/system/cpu/intel_pstate"
CAP_PATH="$PSTATE/max_perf_pct"
CONF="/etc/cpu-quiet.conf"

[[ -f "$CAP_PATH" ]] || exit 0

MAX_KHZ=$(cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq 2>/dev/null || echo 5300000)

apply() {
    echo "$1" | sudo tee "$CAP_PATH" > /dev/null
    # persist so cpu-quiet.service restores this cap on the next boot
    echo "$1" | sudo tee "$CONF" > /dev/null
    # Refresh whichever bar is running. i3blocks is dead under niri, so the
        # click used to leave the reading stale until the next 30s tick;
        # waybar declares `signal: 14` for this module and takes the same
        # RTMIN offset. Signalling both keeps the i3 session working too.
        pkill -RTMIN+14 i3blocks 2>/dev/null
        pkill -RTMIN+14 waybar 2>/dev/null
}

ghz() { awk "BEGIN {printf \"%.1f\", $MAX_KHZ * $1 / 100 / 1000000}"; }

CURRENT=$(cat "$CAP_PATH" 2>/dev/null)

case $BLOCK_BUTTON in
    1)
        eval $(xdotool getmouselocation --shell)
        CHOICE=$(printf '%s\n' \
            "100  $(ghz 100) GHz  full     57W  84C" \
            " 90  $(ghz 90) GHz  (pointless)" \
            " 80  $(ghz 80) GHz  quiet    31W  70C" \
            " 70  $(ghz 70) GHz  cooler   21W  64C" \
            " 64  $(ghz 64) GHz  no turbo 16W  61C" \
            | rofi -dmenu -p "cpu cap" -theme-str "window {width: 320px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 5;}")
        PCT=$(awk '{print $1}' <<< "$CHOICE")
        if [[ -n "$PCT" && "$PCT" != "$CURRENT" ]]; then
            apply "$PCT"
            CURRENT="$PCT"
        fi
        ;;
    3)
        if [[ "$CURRENT" == "100" ]]; then apply 80; CURRENT=80
        else apply 100; CURRENT=100
        fi
        ;;
esac

if [[ "$CURRENT" -ge 100 ]]; then   COLOR="#dc322f"
elif [[ "$CURRENT" -ge 90 ]]; then  COLOR="#cb4b16"
elif [[ "$CURRENT" -ge 80 ]]; then  COLOR="#b58900"
else                                COLOR="#2aa198"
fi

echo "󰈐 $(ghz "$CURRENT")"
echo "󰈐 $(ghz "$CURRENT")"
echo "$COLOR"
