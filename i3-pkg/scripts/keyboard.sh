#!/bin/bash
# Keyboard layout script for i3blocks
# Click to toggle between US and PL

# Handle click - toggle layout
case $BLOCK_BUTTON in
    1|3)
        CURRENT=$(setxkbmap -query | grep layout | awk '{print $2}')
        if [[ "$CURRENT" == "us" ]]; then
            setxkbmap pl
        else
            setxkbmap us
        fi
        ;;
esac

LAYOUT=$(setxkbmap -query | grep layout | awk '{print toupper($2)}')

echo "⌨ $LAYOUT"
echo "⌨ $LAYOUT"
