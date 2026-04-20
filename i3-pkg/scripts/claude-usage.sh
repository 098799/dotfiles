#!/bin/bash
# Claude.ai usage script for i3blocks
# Shows both work and private usage, emphasises the active account
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

# Keep active account's backup in sync (tokens get refreshed by Claude Code)
if [[ -f "$CLAUDE_CREDS" ]]; then
    BACKUP="$HOME/.claude/.credentials-$ACCOUNT.json"
    if ! cmp -s "$CLAUDE_CREDS" "$BACKUP" 2>/dev/null; then
        cp "$CLAUDE_CREDS" "$BACKUP"
    fi
fi

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
                # Always save current credentials back (tokens may have been refreshed)
                cp "$CLAUDE_CREDS" "$HOME/.claude/.credentials-$ACCOUNT.json"
                cp "$CREDS_FILE" "$CLAUDE_CREDS"
            fi
            # Kill chrome-native-host processes so the plugin reconnects with new creds
            pkill -f 'claude.*--chrome-native-host' 2>/dev/null || true
            ACCOUNT="$CHOICE"
        fi
        ;;
esac

# Fetch usage for a given account. Outputs: USAGE_INT COLOR RESET_STR (or "?" if unavailable)
fetch_usage() {
    local acct="$1"
    local cookie_file="$CONFIG_DIR/claude-cookies-$acct"
    local cache_file="/tmp/.claude_usage_cache_$acct"

    if [[ ! -f "$cookie_file" ]]; then
        echo "? #657b83"
        return
    fi

    local org_id
    org_id=$(grep -oP '^# ORG_ID=\K.*' "$cookie_file")
    if [[ -z "$org_id" ]]; then
        echo "? #657b83"
        return
    fi

    local response
    if [[ -f "$cache_file" ]] && [[ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt 300 ]]; then
        response=$(cat "$cache_file")
    else
        response=$(curl -s "https://claude.ai/api/organizations/$org_id/usage" \
            -H 'accept: application/json' \
            -H 'content-type: application/json' \
            -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36' \
            -b "$cookie_file" \
            2>/dev/null)

        if [[ -n "$response" ]] && echo "$response" | grep -q "five_hour"; then
            echo "$response" > "$cache_file"
        fi
    fi

    local usage resets
    usage=$(echo "$response" | grep -oP '"five_hour":\s*\{\s*"utilization":\s*\K[0-9.]+' | head -1)
    resets=$(echo "$response" | grep -oP '"resets_at":\s*"\K[^"]+' | head -1)

    if [[ -z "$usage" ]]; then
        echo "? #657b83"
        return
    fi

    local usage_int reset_str color
    usage_int=$(printf "%.0f" "$usage")
    reset_str=""

    if [[ -n "$resets" ]]; then
        local reset_ts now_ts diff
        reset_ts=$(date -d "$resets" +%s 2>/dev/null)
        now_ts=$(date +%s)
        diff=$((reset_ts - now_ts))
        if [[ $diff -gt 0 ]]; then
            local hours mins
            hours=$((diff / 3600))
            mins=$(((diff % 3600) / 60))
            reset_str="${hours}h${mins}m"
        else
            reset_str="soon"
        fi
    fi

    # Color based on usage rate (5 hour window)
    if [[ -n "$resets" ]] && [[ $diff -gt 0 ]]; then
        local time_elapsed_pct rate
        time_elapsed_pct=$((100 - (diff * 100 / 18000)))

        if [[ $time_elapsed_pct -gt 0 ]]; then
            rate=$(echo "scale=2; $usage / $time_elapsed_pct" | bc)

            if (( $(echo "$rate > 1.0" | bc -l) )); then
                color="#dc322f"
            elif (( $(echo "$rate > 0.67" | bc -l) )); then
                color="#b58900"
            else
                color="#859900"
            fi
        else
            color="#859900"
        fi
    else
        if [[ $usage_int -ge 80 ]]; then
            color="#dc322f"
        elif [[ $usage_int -ge 50 ]]; then
            color="#b58900"
        else
            color="#859900"
        fi
    fi

    echo "$usage_int $color $reset_str"
}

# Fetch both accounts
read W_USAGE W_COLOR W_RESET <<< "$(fetch_usage work)"
read P_USAGE P_COLOR P_RESET <<< "$(fetch_usage private)"

# Build display for each account
format_account() {
    local label="$1" usage="$2" color="$3" reset="$4" is_active="$5"

    local text="${label}:${usage}%"
    if [[ -n "$reset" && "$usage" != "?" ]]; then
        text="${text}(${reset})"
    fi

    if [[ "$is_active" == "1" ]]; then
        echo "<span foreground='$color'><b>${text}</b></span>"
    else
        echo "<span foreground='#657b83'>${text}</span>"
    fi
}

if [[ "$ACCOUNT" == "work" ]]; then
    W_ACTIVE=1; P_ACTIVE=0
else
    W_ACTIVE=0; P_ACTIVE=1
fi

W_SPAN=$(format_account "W" "$W_USAGE" "$W_COLOR" "$W_RESET" "$W_ACTIVE")
P_SPAN=$(format_account "P" "$P_USAGE" "$P_COLOR" "$P_RESET" "$P_ACTIVE")

echo " 󰚩 ${W_SPAN} ${P_SPAN} "
echo "󰚩 W:${W_USAGE}% P:${P_USAGE}%"
