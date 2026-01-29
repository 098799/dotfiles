#!/bin/bash
# Claude.ai usage script for i3blocks
# Requires cookies in ~/.config/claude-cookies
# Right-click: open usage page

case $BLOCK_BUTTON in
    3) xdg-open "https://claude.ai/settings/usage" & ;;
esac

COOKIE_FILE="$HOME/.config/claude-cookies"
CACHE_FILE="/tmp/.claude_usage_cache"
ORG_ID="4fc6cf12-57d2-4884-bdb6-4677435c1f0e"

# Check for cookie file
if [[ ! -f "$COOKIE_FILE" ]]; then
    echo "<span background='#073642' foreground='#657b83'> 󰚩 No cookies </span>"
    echo "󰚩"
    exit 0
fi

# Use cache if fresh (less than 5 min old)
if [[ -f "$CACHE_FILE" ]] && [[ $(($(date +%s) - $(stat -c %Y "$CACHE_FILE"))) -lt 300 ]]; then
    RESPONSE=$(cat "$CACHE_FILE")
else
    RESPONSE=$(curl -s "https://claude.ai/api/organizations/$ORG_ID/usage" \
        -H 'accept: application/json' \
        -H 'content-type: application/json' \
        -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36' \
        -b "$COOKIE_FILE" \
        2>/dev/null)

    if [[ -n "$RESPONSE" ]] && echo "$RESPONSE" | grep -q "five_hour"; then
        echo "$RESPONSE" > "$CACHE_FILE"
    fi
fi

# Parse response
USAGE=$(echo "$RESPONSE" | grep -oP '"five_hour":\s*\{\s*"utilization":\s*\K[0-9.]+' | head -1)
RESETS=$(echo "$RESPONSE" | grep -oP '"resets_at":\s*"\K[^"]+' | head -1)

if [[ -z "$USAGE" ]]; then
    echo "<span background='#073642' foreground='#657b83'> 󰚩 ? </span>"
    echo "󰚩"
    exit 0
fi

# Calculate time until reset
if [[ -n "$RESETS" ]]; then
    RESET_TS=$(date -d "$RESETS" +%s 2>/dev/null)
    NOW_TS=$(date +%s)
    DIFF=$((RESET_TS - NOW_TS))
    if [[ $DIFF -gt 0 ]]; then
        HOURS=$((DIFF / 3600))
        MINS=$(((DIFF % 3600) / 60))
        RESET_STR="${HOURS}h${MINS}m"
    else
        RESET_STR="soon"
    fi
fi

# Round usage to integer
USAGE_INT=$(printf "%.0f" "$USAGE")

# Color based on usage rate (5 hour window)
# Red if using at 2x rate, yellow if 1.5x rate
if [[ -n "$RESETS" ]] && [[ $DIFF -gt 0 ]]; then
    # Time elapsed as percentage of 5 hours
    TIME_ELAPSED_PCT=$((100 - (DIFF * 100 / 18000)))

    if [[ $TIME_ELAPSED_PCT -gt 0 ]]; then
        # Rate = how fast we're using vs sustainable rate
        # rate of 1.0 = on track, 2.0 = twice as fast
        RATE=$(echo "scale=2; $USAGE / $TIME_ELAPSED_PCT" | bc)

        if (( $(echo "$RATE > 1.0" | bc -l) )); then
            COLOR="#dc322f"  # red - will exceed quota
        elif (( $(echo "$RATE > 0.67" | bc -l) )); then
            COLOR="#b58900"  # yellow - on track to use most
        else
            COLOR="#859900"  # green - plenty of buffer
        fi
    else
        COLOR="#859900"  # green - just started
    fi
else
    # Fallback if no reset time
    if [[ $USAGE_INT -ge 80 ]]; then
        COLOR="#dc322f"
    elif [[ $USAGE_INT -ge 50 ]]; then
        COLOR="#b58900"
    else
        COLOR="#859900"
    fi
fi

echo "<span background='#073642' foreground='$COLOR'> 󰚩 ${USAGE_INT}% (${RESET_STR}) </span>"
echo "󰚩 ${USAGE_INT}%"
