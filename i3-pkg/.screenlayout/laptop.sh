#!/bin/sh
xrandr --output HDMI-A-0 --off --output DisplayPort-0 --off --output eDP --primary --mode 1920x1200 --pos 0x0 --rotate normal

# The wallpaper set is mixed 16:9 / 21:9 and feh --bg-scale ignores aspect, so
# a layout change without this leaves the previous ratio squashed on the new
# screen. Re-pick against the geometry xrandr has just set.
"$HOME/bin/wallpaper-pick" 2>/dev/null || true
