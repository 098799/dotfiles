#!/bin/bash
# Date/time script for i3blocks

# Handle click - show calendar
case $BLOCK_BUTTON in
    1) alacritty -e bash -c "cal -3; read -p 'Press enter to close...'" & ;;
    3) alacritty -e bash -c "cal -y; read -p 'Press enter to close...'" & ;;
esac

echo "$(date '+%a %d %b %H:%M')"
echo "$(date '+%H:%M')"
