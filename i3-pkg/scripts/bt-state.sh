#!/bin/bash
# Bluetooth state for the bar blocks, asked once and shared.
#
#   bt-state.sh           # state, at most TTL seconds old
#   bt-state.sh --fresh   # ask bluetoothd now (a click acts on this)
#
# Output, one fact per line:
#   powered yes|no
#   connected <MAC> <name>      (one line per connected device)
#
# Why: bluetooth.sh, bt-headphones.sh, bt-keyboard.sh and bt-mouse.sh each
# polled bluetoothctl every 5s, on every bar (waybar draws one bar per screen).
# That was 8+ bluetoothctl runs per tick. Now the first caller asks, under a
# lock, and every other caller in the next TTL seconds reads its answer.
# Commands go as arguments (`bluetoothctl show`), not on stdin: an interactive
# bluetoothctl that reads its commands from a pipe can wait out the timeout.

CACHE="${XDG_RUNTIME_DIR:-/tmp}/bt-state"
TTL=3

fresh=0
[[ $1 == --fresh ]] && fresh=1

is_current() {
    local now mtime
    [[ -s $CACHE ]] || return 1
    printf -v now '%(%s)T' -1
    mtime=$(stat -c %Y "$CACHE" 2>/dev/null) || return 1
    (( now - mtime < TTL ))
}

if (( !fresh )) && is_current; then
    cat "$CACHE"
    exit 0
fi

exec 9>"$CACHE.lock"
if ! flock -w 5 9; then
    # Another caller is stuck on bluetoothd. Its last answer beats no answer.
    cat "$CACHE" 2>/dev/null
    exit 0
fi
# The caller that held the lock has likely just written a current answer.
if (( !fresh )) && is_current; then
    cat "$CACHE"
    exit 0
fi

{
    powered=$(timeout 2 bluetoothctl show 2>/dev/null | awk '/Powered:/ { print $2; exit }')
    echo "powered ${powered:-no}"
    if [[ $powered == yes ]]; then
        timeout 2 bluetoothctl devices Connected 2>/dev/null | awk '/^Device / { $1 = "connected"; print }'
    fi
} >"$CACHE.$$" && mv -f "$CACHE.$$" "$CACHE"
cat "$CACHE"
