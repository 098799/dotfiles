#!/bin/bash
# Power profile switcher for i3blocks
# Left-click: rofi menu to select profile

PROFILE_PATH="/sys/firmware/acpi/platform_profile"

if [[ ! -f "$PROFILE_PATH" ]]; then
    exit 0
fi

CURRENT=$(cat "$PROFILE_PATH" 2>/dev/null)

case $BLOCK_BUTTON in
    1)
        eval $(xdotool getmouselocation --shell)
        CHOICE=$(echo -e "low-power\nbalanced\nperformance" | rofi -dmenu -p "power" -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 3;}")
        if [[ -n "$CHOICE" && "$CHOICE" != "$CURRENT" ]]; then
            echo "$CHOICE" | sudo tee "$PROFILE_PATH" > /dev/null
            CURRENT="$CHOICE"
            # Refresh whichever bar is running. i3blocks is dead under niri, so the
        # click used to leave the reading stale until the next 30s tick;
        # waybar declares `signal: 12` for this module and takes the same
        # RTMIN offset. Signalling both keeps the i3 session working too.
        pkill -RTMIN+12 i3blocks 2>/dev/null
        pkill -RTMIN+12 waybar 2>/dev/null
        fi
        ;;
esac

case "$CURRENT" in
    low-power)    ICON="󰌪"; LABEL="lo"; COLOR="#2aa198" ;;
    balanced)     ICON="󰛲"; LABEL="bal"; COLOR="#b58900" ;;
    performance)  ICON="󱐋"; LABEL="hi"; COLOR="#dc322f" ;;
    *)            ICON="?"; LABEL="?"; COLOR="" ;;
esac

echo "$ICON $LABEL"
echo "$ICON $LABEL"
[[ -n "$COLOR" ]] && echo "$COLOR"
