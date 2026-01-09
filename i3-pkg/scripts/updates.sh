#!/bin/bash
# Arch/Manjaro updates script for i3blocks
# Left click to refresh, right click to open terminal with update

case $BLOCK_BUTTON in
    1) checkupdates > /tmp/.updates_cache 2>/dev/null ;;
    3) alacritty -e bash -c "sudo pacman -Syu; read -p 'Press enter to close...'" & ;;
esac

# Use cache if fresh (less than 1 hour old), otherwise check
CACHE="/tmp/.updates_cache"
if [[ -f "$CACHE" ]] && [[ $(($(date +%s) - $(stat -c %Y "$CACHE"))) -lt 3600 ]]; then
    UPDATES=$(cat "$CACHE" | wc -l)
else
    UPDATES=$(checkupdates 2>/dev/null | tee "$CACHE" | wc -l)
fi

if [[ $UPDATES -gt 0 ]]; then
    echo "󰏗"
    echo "󰏗"
    echo "#dc322f"
else
    echo "󰏗"
    echo "󰏗"
    echo "#859900"
fi
