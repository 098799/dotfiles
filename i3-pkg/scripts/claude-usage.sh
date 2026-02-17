#!/bin/bash
# Claude.ai usage script for i3blocks
# Supports multiple accounts with rofi switcher
# Right-click: rofi menu to switch account (also switches Claude Code credentials)

CONFIG_DIR="$HOME/.config"
ACCOUNT_FILE="$CONFIG_DIR/claude-active-account"
CLAUDE_CREDS="$HOME/.claude/.credentials.json"

# Get current account (default to work)
if [[ -f "$ACCOUNT_FILE" ]]; then
    ACCOUNT=$(cat "$ACCOUNT_FILE" | tr -d '[:space:]')
else
    ACCOUNT="work"
fi

COOKIE_FILE="$CONFIG_DIR/claude-cookies-$ACCOUNT"
CACHE_FILE="/tmp/.claude_usage_cache_$ACCOUNT"

# Handle click
case $BLOCK_BUTTON in
    3)
        eval $(xdotool getmouselocation --shell)
        # Pre-select current account
        if [[ "$ACCOUNT" == "work" ]]; then
            SELECTED=1
        else
            SELECTED=0
        fi
        CHOICE=$(echo -e "private\nwork" | rofi -dmenu -p "claude" -selected-row $SELECTED -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: 2;}")
        if [[ -n "$CHOICE" && "$CHOICE" != "$ACCOUNT" ]]; then
            echo "$CHOICE" > "$ACCOUNT_FILE"
            # Clear cache to force refresh
            rm -f /tmp/.claude_usage_cache_* 2>/dev/null || true
            # Switch Claude Code credentials
            CREDS_FILE="$HOME/.claude/.credentials-$CHOICE.json"
            if [[ -f "$CREDS_FILE" ]]; then
                # Backup current credentials if not already backed up
                if [[ ! -f "$HOME/.claude/.credentials-$ACCOUNT.json" ]]; then
                    cp "$CLAUDE_CREDS" "$HOME/.claude/.credentials-$ACCOUNT.json"
                fi
                cp "$CREDS_FILE" "$CLAUDE_CREDS"
            fi
            ACCOUNT="$CHOICE"
            COOKIE_FILE="$CONFIG_DIR/claude-cookies-$ACCOUNT"
            CACHE_FILE="/tmp/.claude_usage_cache_$ACCOUNT"
        fi
        ;;
esac

# Check for cookie file
if [[ ! -f "$COOKIE_FILE" ]]; then
    echo "<span background='#073642' foreground='#657b83'> 󰚩 No cookies </span>"
    echo "󰚩"
    exit 0
fi

# Parse ORG_ID from cookie file
ORG_ID=$(grep -oP '^# ORG_ID=\K.*' "$COOKIE_FILE")
if [[ -z "$ORG_ID" ]]; then
    echo "<span background='#073642' foreground='#657b83'> 󰚩 No ORG_ID </span>"
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
if [[ -n "$RESETS" ]] && [[ $DIFF -gt 0 ]]; then
    TIME_ELAPSED_PCT=$((100 - (DIFF * 100 / 18000)))

    if [[ $TIME_ELAPSED_PCT -gt 0 ]]; then
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
    if [[ $USAGE_INT -ge 80 ]]; then
        COLOR="#dc322f"
    elif [[ $USAGE_INT -ge 50 ]]; then
        COLOR="#b58900"
    else
        COLOR="#859900"
    fi
fi

# Account label (W for work, P for private)
if [[ "$ACCOUNT" == "work" ]]; then
    LABEL="W"
else
    LABEL="P"
fi

echo "<span background='#073642' foreground='$COLOR'> 󰚩 $LABEL ${USAGE_INT}% (${RESET_STR}) </span>"
echo "󰚩 $LABEL ${USAGE_INT}%"
