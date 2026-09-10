#!/bin/sh
xrandr --output eDP --off --output DisplayPort-0 --off --output HDMI-A-0 --primary --mode 2560x1440 --pos 0x0 --rotate normal

# The wallpaper set is mixed 16:9 / 21:9 and feh --bg-scale ignores aspect, so
# a layout change without this leaves the previous ratio squashed on the new
# screen. Re-pick against the geometry xrandr has just set.
"$HOME/bin/wallpaper-pick" 2>/dev/null || true
