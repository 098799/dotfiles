#!/bin/bash
# Uptime script for i3blocks
# Right-click: show boot analysis

case $BLOCK_BUTTON in
    3) alacritty -e bash -c "systemd-analyze blame | head -30; read -p 'Press enter to close...'" & ;;
esac

# Get uptime in a readable format
UPTIME=$(uptime -p | sed 's/up //')

# Shorten for display
SHORT=$(echo "$UPTIME" | sed 's/ years\?/y/; s/ months\?/mo/; s/ weeks\?/w/; s/ days\?/d/; s/ hours\?/h/; s/ minutes\?/m/; s/, //g')

echo "󰔟 $SHORT"
echo "󰔟 $SHORT"
