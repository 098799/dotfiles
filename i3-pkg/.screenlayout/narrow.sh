#!/bin/sh
xrandr --newmode "3200x1800R" 373.00 3200 3248 3280 3360 1800 1803 1808 1852 +hsync -vsync 2>/dev/null
xrandr --addmode DisplayPort-0 "3200x1800R" 2>/dev/null
xrandr --output eDP --off --output DisplayPort-0 --primary --mode "3200x1800R" --pos 0x0 --rotate normal
