#!/bin/sh
xrandr --newmode "2560x1440R" 241.50 2560 2608 2640 2720 1440 1443 1448 1481 +hsync -vsync 2>/dev/null
xrandr --addmode DisplayPort-0 "2560x1440R" 2>/dev/null
xrandr --output eDP --off --output DisplayPort-0 --primary --mode "2560x1440R" --pos 0x0 --rotate normal
