#!/bin/bash
# Screenshot button for i3blocks
# Left-click: select area, Right-click: full screen

case $BLOCK_BUTTON in
    1) scrot -zs ~/screenshot_%Y%m%d_%H%M%S.png & ;;
    3) scrot -z ~/screenshot_%Y%m%d_%H%M%S.png & ;;
esac

echo "󰹑"
echo "󰹑"
