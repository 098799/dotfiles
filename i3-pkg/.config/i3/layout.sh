THIRD_MONITOR=`cat ~/.config/i3/CURRENT_MONITOR`

if [ "$THIRD_MONITOR" != "" ]
then
    xrandr --output "eDP-1" --primary --mode 1920x1080 --pos 1016x1080 --rotate normal --output "HDMI-1" --mode 1920x1080 --pos 0x0 --rotate normal --output $THIRD_MONITOR --mode 1920x1080 --pos 1920x0 --rotate normal
else
    xrandr --output "eDP-1" --primary --mode 1920x1080 --pos 1016x1080 --rotate normal
fi
