#!/bin/bash
# Claude.ai usage script for i3blocks
# Shows usage for every configured account, emphasises the active one
# Right-click: rofi menu to switch account (also switches Claude Code credentials)

CONFIG_DIR="$HOME/.config"
ACCOUNT_FILE="$CONFIG_DIR/claude-active-account"
CLAUDE_CREDS="$HOME/.claude/.credentials.json"

# Accounts in display order: the three legacy ones first, then any extra
# discovered from either a claude-cookies-<name> file in $CONFIG_DIR or a
# ~/claude-<name> alt HOME holding a Claude Code login — the same two
# conventions rcmon/cmon auto-discover (!5956). A cookie alone is enough, and
# so is a login alone: usage falls back to the OAuth endpoint (see
# fetch_usage_oauth) when there's no cookie, which is what a `/login`-only
# account like sales has.
# Labels default to the uppercased first letter; override below for clashes.
ACCOUNTS=(work private builder)
for _f in "$CONFIG_DIR"/claude-cookies-*; do
    [[ -e "$_f" ]] || continue
    _name="${_f##*/claude-cookies-}"
    [[ " ${ACCOUNTS[*]} " == *" $_name "* ]] || ACCOUNTS+=("$_name")
done
for _d in "$HOME"/claude-*; do
    [[ -f "$_d/.claude/.credentials.json" ]] || continue
    _name="${_d##*/claude-}"
    # claude-prim is the "work" account's home under a legacy name.
    [[ "$_name" == "prim" ]] && continue
    [[ " ${ACCOUNTS[*]} " == *" $_name "* ]] || ACCOUNTS+=("$_name")
done
declare -A LABELS=([work]=W [private]=P [builder]=B)
for _a in "${ACCOUNTS[@]}"; do
    [[ -n "${LABELS[$_a]}" ]] || LABELS[$_a]=$(printf '%s' "${_a:0:1}" | tr '[:lower:]' '[:upper:]')
done

# Get current account (default to first configured)
if [[ -f "$ACCOUNT_FILE" ]]; then
    ACCOUNT=$(cat "$ACCOUNT_FILE" | tr -d '[:space:]')
else
    ACCOUNT="${ACCOUNTS[0]}"
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
        # Pre-select current account (find its index in ACCOUNTS)
        SELECTED=0
        for i in "${!ACCOUNTS[@]}"; do
            if [[ "${ACCOUNTS[$i]}" == "$ACCOUNT" ]]; then
                SELECTED=$i
                break
            fi
        done
        MENU=$(printf '%s\n' "${ACCOUNTS[@]}")
        CHOICE=$(echo "$MENU" | rofi -dmenu -p "claude" -selected-row $SELECTED -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: ${#ACCOUNTS[@]};}")
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

# Newest credentials file backing an account, or nothing. Mirrors rcmon's
# home_agents.credential_source: the ~/.claude/.credentials-<acct>.json backup
# this script maintains can be months stale (it only refreshes when the rofi
# switcher swaps accounts), while the alt HOME's copy is refreshed by every
# cmon/cherd spawn under that HOME. Newest wins.
creds_for() {
    local acct="$1" newest="" c
    local -a cands=("$HOME/.claude/.credentials-$acct.json")
    case "$acct" in
        private) cands+=("$HOME/.claude/.credentials.json") ;;
        work) cands+=("$HOME/claude-prim/.claude/.credentials.json") ;;
        *) cands+=("$HOME/claude-$acct/.claude/.credentials.json") ;;
    esac
    for c in "${cands[@]}"; do
        [[ -f "$c" ]] || continue
        [[ -z "$newest" || "$c" -nt "$newest" ]] && newest="$c"
    done
    [[ -n "$newest" ]] && printf '%s' "$newest"
}

# Usage for an account straight from the OAuth endpoint — no browser cookie
# needed. Used when an account has a Claude Code login but no
# claude-cookies-<name> file (the normal state right after `/login`).
#
# Deliberately does NOT refresh an expired access token: that endpoint is rate
# limited PER REFRESH TOKEN, and a 60s i3blocks tick hammering it would keep
# the account permanently 429'd — exactly what wedged the mr-reviewer VM's
# backups for a week. An expired token just reads "?" here until the next
# Claude Code session under that account refreshes it in passing.
fetch_usage_oauth() {
    local acct="$1" creds token
    creds=$(creds_for "$acct")
    [[ -n "$creds" ]] || return 1
    token=$(python3 - "$creds" <<'PY'
import json, sys, time
try:
    o = json.load(open(sys.argv[1])).get("claudeAiOauth", {})
except Exception:
    sys.exit(1)
tok, exp = o.get("accessToken"), o.get("expiresAt") or 0
if not tok or exp / 1000 <= time.time():
    sys.exit(1)
print(tok)
PY
    ) || return 1
    [[ -n "$token" ]] || return 1
    curl -s --max-time 10 'https://api.anthropic.com/api/oauth/usage' \
        -H "Authorization: Bearer $token" \
        -H 'user-agent: claude-code/2.1.100' \
        -H 'anthropic-client-platform: claude_code' \
        2>/dev/null
}

# Fetch usage for a given account. Outputs: USAGE_INT COLOR RESET_STR (or "?" if unavailable)
# Both sources return the same {"five_hour":{"utilization",…}} shape, so
# everything below the fetch is source-agnostic.
fetch_usage() {
    local acct="$1"
    local cookie_file="$CONFIG_DIR/claude-cookies-$acct"
    local cache_file="/tmp/.claude_usage_cache_$acct"

    local org_id=""
    if [[ -f "$cookie_file" ]]; then
        org_id=$(grep -oP '^# ORG_ID=\K.*' "$cookie_file")
    fi

    local response
    if [[ -f "$cache_file" ]] && [[ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt 300 ]]; then
        response=$(cat "$cache_file")
    else
        if [[ -n "$org_id" ]]; then
            response=$(curl -s "https://claude.ai/api/organizations/$org_id/usage" \
                -H 'accept: application/json' \
                -H 'content-type: application/json' \
                -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36' \
                -b "$cookie_file" \
                2>/dev/null)
        else
            response=$(fetch_usage_oauth "$acct")
        fi

        if [[ -n "$response" ]] && echo "$response" | grep -q "five_hour"; then
            echo "$response" > "$cache_file"
        fi
    fi

    if [[ -z "$response" ]]; then
        echo "? #657b83"
        return
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

# Fetch + render every configured account
SPANS=""
SHORT=""
for acct in "${ACCOUNTS[@]}"; do
    read U C R <<< "$(fetch_usage "$acct")"
    label="${LABELS[$acct]:-${acct:0:1}}"
    [[ "$acct" == "$ACCOUNT" ]] && active=1 || active=0
    SPANS="${SPANS}$(format_account "$label" "$U" "$C" "$R" "$active") "
    SHORT="${SHORT}${label}:${U}% "
done

echo " 󰚩 ${SPANS}"
echo "󰚩 ${SHORT}"
