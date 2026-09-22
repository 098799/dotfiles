#!/bin/bash
# Screenshot button for the status bar (i3blocks and waybar both drive it).
# Left-click: select area, Right-click: full screen
#
# scrot is X11-only: under niri it captures Xwayland's root, which holds none of
# the Wayland windows, so the button produced a blank or stale image with no
# error. Pick the capture tool from the session rather than hard-coding either,
# because these scripts are shared with the i3 session, which still needs scrot.
shot_area() {
    if [[ -n ${WAYLAND_DISPLAY:-} ]]; then
        grim -g "$(slurp)" "$1"
    else
        scrot -zs "$1"
    fi
}
shot_full() {
    if [[ -n ${WAYLAND_DISPLAY:-} ]]; then
        grim "$1"
    else
        scrot -z "$1"
    fi
}

# scrot expands strftime itself; grim does not, so the name is built here and
# both paths get the identical filename.
OUT="$HOME/screenshot_$(date +%Y%m%d_%H%M%S).png"

case $BLOCK_BUTTON in
    1) shot_area "$OUT" & ;;
    3) shot_full "$OUT" & ;;
esac

echo "󰹑"
echo "󰹑"
