#!/bin/bash
# Active legartis slots for i3blocks
# Left-click: show full status in terminal
# Shows all slots 0-8: N[D][T][C] where D=docker T=tmux C=claude
# Claude: c=idle C=working (based on CPU usage)
# Colors: solarized palette

case $BLOCK_BUTTON in
    1) alacritty -e bash -c "$HOME/bin/legartis-env status; read -p 'Press enter to close...'" & ;;
esac

docker_names=$(docker ps --format '{{.Names}}' 2>/dev/null)

# Solarized colors
GREEN="#859900"
YELLOW="#b58900"
DIM="#586e75"

output=""
short=""
for slot in $(seq 0 8); do
    wt="$HOME/legartis${slot}"
    [[ -d "$wt/.git" || -f "$wt/.git" ]] || continue

    d=false t=false c=""
    if [[ "$slot" == "0" ]]; then
        echo "$docker_names" | grep -qE "(legartis_0_|local_env_)" && d=true
    else
        echo "$docker_names" | grep -q "legartis_${slot}_" && d=true
    fi

    session="legartis-${slot}"
    if tmux has-session -t "$session" 2>/dev/null; then
        t=true
        # Find claude window and check if it's working
        claude_pane_pid=$(tmux list-windows -t "$session" -F "#{window_name} #{pane_pid}" 2>/dev/null | grep -i claude | awk '{print $NF}')
        if [[ -n "$claude_pane_pid" ]]; then
            # Find the actual claude process under the pane shell
            claude_pid=$(pgrep -P "$claude_pane_pid" -x claude 2>/dev/null | head -1)
            if [[ -n "$claude_pid" ]]; then
                cpu=$(top -bn1 -p "$claude_pid" 2>/dev/null | tail -1 | awk '{print $9}')
                if awk "BEGIN {exit ($cpu > 1.0) ? 0 : 1}" 2>/dev/null; then
                    c="C"  # working
                else
                    c="c"  # idle
                fi
            else
                c="c"
            fi
        fi
    fi

    # Color the slot number based on overall activity
    if [[ "$t" == "true" ]]; then
        slot_color="$GREEN"
    elif [[ "$d" == "true" ]]; then
        slot_color="$GREEN"
    else
        slot_color="$DIM"
    fi

    # Color each flag independently
    [[ "$d" == "true" ]] && ds="<span color='$GREEN'>D</span>" || ds="<span color='$DIM'>-</span>"
    [[ "$t" == "true" ]] && ts="<span color='$GREEN'>T</span>" || ts="<span color='$DIM'>-</span>"
    if [[ "$c" == "C" ]]; then
        cs="<span color='$GREEN'>C</span>"
    elif [[ "$c" == "c" ]]; then
        cs="<span color='$YELLOW'>C</span>"
    else
        cs="<span color='$DIM'>-</span>"
    fi

    # Skip slots with no activity (---)
    [[ "$d" == "false" && "$t" == "false" && -z "$c" ]] && continue

    output="${output} <span color='${slot_color}'>${slot}</span>:${ds}${ts}${cs}"
    short="${short} ${slot}:$(${d} && echo D || echo -)$(${t} && echo T || echo -)${c:-"-"}"
done

if [[ -z "$output" ]]; then
    echo "S -"
    echo "S -"
else
    echo "S${output}"
    echo "S${short}"
fi
