MONITOR=xrandr | grep " connected" | grep "^DP-" | cut -d" " -f1

if [ "$MONITOR" != "" ]
then
    sed -i -e "s/set \$small_monitor.*/set \$small_monitor /g" ~/.config/i3/config
fi

echo $MONITOR > ~/.config/i3/CURRENT_MONITOR
