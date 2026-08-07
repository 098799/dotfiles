#!/bin/bash
# Claude.ai usage script for i3blocks
# Shows usage for every configured account, emphasises the active one
# Right-click: rofi menu to switch account (also switches Claude Code credentials)
#
#   claude-usage.sh            the i3blocks line (five-hour window, active bold)
#   claude-usage.sh --json     every window as JSON — what w95-sysmon reads
#   claude-usage.sh --sample   fetch and record history, print nothing
#
# Whichever way it is called it appends to the usage history CSV (see "history"
# below), so the sampling cadence is just "how often somebody asks".

CONFIG_DIR="$HOME/.config"
ACCOUNT_FILE="$CONFIG_DIR/claude-active-account"
CLAUDE_CREDS="$HOME/.claude/.credentials.json"

MODE=bar
case "${1:-}" in
    --json)   MODE=json ;;
    --sample) MODE=sample ;;
    "")       ;;
    *) echo "claude-usage.sh: unknown option: $1" >&2; exit 2 ;;
esac

# How long a fetched response is reused. 120s rather than the old 300s because
# the history below is now charted: at a 60s i3blocks tick that puts a sample
# every two minutes, which is the cadence mr-reviewer's usage-pusher settled on
# for the same endpoint.
CACHE_TTL=${CLAUDE_USAGE_TTL:-120}

# Append-only sample log, one row per account per sample — the Win95 System
# Monitor charts it. Deliberately NOT mr-reviewer's wide layout (one row per
# sample, two positional columns per account, "never reorder this list"): a row
# that names its own account survives an account being added, renamed or
# dropped, which on a laptop happens all the time.
HISTORY_FILE="${CLAUDE_USAGE_HISTORY:-$HOME/.local/state/w95/claude-usage.csv}"
HISTORY_GAP=${CLAUDE_USAGE_HISTORY_GAP:-100}    # seconds between rows per account
HISTORY_DAYS=${CLAUDE_USAGE_HISTORY_DAYS:-14}

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
# `sales` and `success` are pinned rather than auto-labelled: the auto rule
# below would give them Sa/Su, and CS (customer success) is what those two are
# actually called, so S/CS reads right even though it isn't a prefix.
declare -A LABELS=([work]=W [private]=P [builder]=B [sales]=S [success]=CS)

# Auto-label the remaining discovered accounts by initial, lengthening the prefix
# until no two of them collide: `sales` and `success` both wanted "S", and the bar
# read "S:3% S:81%" with nothing to say which was which. The length is chosen once
# and applied to all of them, so they stay the same width and a new account
# widens the set rather than making one odd label longer than its neighbours.
# Only the bar cares — rcmon, cmon and the System Monitor key everything by
# account name (the monitor's fallback bar-line parse is the one exception, and
# that only runs against a copy of this script older than --json).
_cap() { printf '%s%s' "$(printf '%s' "${1:0:1}" | tr '[:lower:]' '[:upper:]')" "${1:1:$2-1}"; }

_auto=()
for _a in "${ACCOUNTS[@]}"; do
    [[ -n "${LABELS[$_a]}" ]] || _auto+=("$_a")
done

_len=1
while :; do
    # Seed with every pinned label, not just the legacy three — an account that
    # auto-labels to "S" or "CS" would otherwise collide with sales/success.
    _seen=" "
    for _a in "${ACCOUNTS[@]}"; do
        [[ -n "${LABELS[$_a]}" ]] && _seen="$_seen${LABELS[$_a]} "
    done
    _clash=0
    for _a in "${_auto[@]}"; do
        _cand=$(_cap "$_a" "$_len")
        if [[ " $_seen " == *" $_cand "* ]]; then _clash=1; break; fi
        _seen="$_seen$_cand "
    done
    # Stop when unique, or when the longest name has nothing left to give.
    (( _clash == 0 )) && break
    _max=0
    for _a in "${_auto[@]}"; do (( ${#_a} > _max )) && _max=${#_a}; done
    (( _len >= _max )) && break
    _len=$((_len + 1))
done

for _a in "${_auto[@]}"; do
    LABELS[$_a]=$(_cap "$_a" "$_len")
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

# The raw usage document for an account, from the 120s cache or from the wire.
# Both sources return the same {"five_hour":{"utilization",…}} shape, so
# everything above this line picks a transport and everything below it is
# source-agnostic.
fetch_response() {
    local acct="$1"
    local cookie_file="$CONFIG_DIR/claude-cookies-$acct"
    local cache_file="/tmp/.claude_usage_cache_$acct"

    if [[ -f "$cache_file" ]] && [[ $(($(date +%s) - $(stat -c %Y "$cache_file"))) -lt $CACHE_TTL ]]; then
        cat "$cache_file"
        return
    fi

    local org_id=""
    if [[ -f "$cookie_file" ]]; then
        org_id=$(grep -oP '^# ORG_ID=\K.*' "$cookie_file")
    fi

    local response
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
    printf '%s' "$response"
}

# Five-hour readout for the bar. Outputs: USAGE_INT COLOR RESET_STR (or "?" if unavailable)
fetch_usage() {
    local acct="$1"
    local response
    response=$(fetch_response "$acct")

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

# ── every window, and the history ───────────────────────────────────────
# The bar only ever wanted the five-hour number, so everything else the usage
# document carries — the weekly limit, the per-model weekly limit — was thrown
# away here. The System Monitor charts all of them, so one pass hands the whole
# document to python: it appends a history row per account (rate-limited to one
# every $HISTORY_GAP seconds, so a 60s bar tick doesn't double up) and, in
# --json mode, prints the structured readout.
#
# Responses arrive NUL-separated rather than as arguments because a usage
# document is a few KB of JSON and this way nothing has to be quoted.
walk_accounts() {
    local acct active
    for acct in "${ACCOUNTS[@]}"; do
        [[ "$acct" == "$ACCOUNT" ]] && active=1 || active=0
        printf '%s\0%s\0%s\0%s\0' \
            "$acct" "${LABELS[$acct]:-${acct:0:1}}" "$active" "$(fetch_response "$acct")"
    done
}

# Held in a variable and run with `python3 -c`, not fed on stdin: stdin is
# where the account stream arrives.
PY_EMIT=$(cat <<'PY'
import json, os, sys, time
from datetime import datetime, timezone

MODE = os.environ.get("CLAUDE_USAGE_MODE", "sample")
PATH = os.path.expanduser(os.environ["CLAUDE_USAGE_HISTORY"])
GAP = int(os.environ["CLAUDE_USAGE_HISTORY_GAP"])
DAYS = int(os.environ["CLAUDE_USAGE_HISTORY_DAYS"])
MAX_BYTES = 4 << 20
HEADER = ("timestamp,account,five_h_util,five_h_resets_in,"
          "seven_d_util,seven_d_resets_in,scoped_util,scoped_name\n")


def seconds_left(stamp):
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, int(when.timestamp() - time.time()))


def human(seconds):
    """"2d10h", "4h6m", "12m" — the bar's spelling, with days for the weekly."""
    if seconds is None:
        return ""
    if seconds <= 0:
        return "soon"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return "%dd%dh" % (days, hours)
    if hours:
        return "%dh%dm" % (hours, rest // 60)
    return "%dm" % (rest // 60)


def window(node):
    if not isinstance(node, dict) or node.get("utilization") is None:
        return None
    left = seconds_left(node.get("resets_at"))
    return {"percent": int(round(node["utilization"])),
            "resets_in": left, "resets": human(left)}


def scoped(document):
    """The per-model weekly caps, out of the `limits` array.

    They have no top-level key of their own — seven_day_opus and friends are
    null even when `limits` carries a weekly_scoped entry for Opus — so this is
    the only place the model-specific weekly quota can be read.
    """
    out = []
    for limit in document.get("limits") or []:
        if limit.get("kind") != "weekly_scoped" or limit.get("percent") is None:
            continue
        model = ((limit.get("scope") or {}).get("model") or {})
        left = seconds_left(limit.get("resets_at"))
        out.append({"name": model.get("display_name") or "scoped",
                    "percent": int(round(limit["percent"])),
                    "resets_in": left, "resets": human(left)})
    return out


def last_seen(accounts):
    """When each account last got a row, from the tail of the file.

    Only the tail: at one row per account every two minutes this file is tens
    of thousands of lines, and all that is wanted is the last row of each.
    """
    seen = {}
    try:
        size = os.path.getsize(PATH)
        with open(PATH) as fh:
            fh.seek(max(0, size - 65536))
            lines = fh.read().splitlines()[1:]
    except OSError:
        return seen
    for line in lines:
        parts = line.split(",")
        if len(parts) > 1 and parts[1] in accounts:
            seen[parts[1]] = parts[0]
    return seen


def trim():
    """Keep the file bounded without a cron job: rewrite it when it gets big,
    dropping everything older than DAYS. ISO-8601 sorts lexicographically, so
    the cutoff is a string comparison and no row has to be parsed."""
    try:
        if os.path.getsize(PATH) < MAX_BYTES:
            return
        cutoff = datetime.fromtimestamp(time.time() - DAYS * 86400).isoformat(" ")[:19]
        cutoff = cutoff.replace(" ", "T")
        with open(PATH) as fh:
            fh.readline()
            keep = [line for line in fh if line[:19] >= cutoff]
        with open(PATH + ".tmp", "w") as fh:
            fh.write(HEADER)
            fh.writelines(keep)
        os.replace(PATH + ".tmp", PATH)
    except OSError:
        pass


chunks = sys.stdin.buffer.read().split(b"\0")
accounts = []
for i in range(0, len(chunks) - 1, 4):
    name, tag, active, body = chunks[i:i + 4]
    try:
        document = json.loads(body.decode("utf-8", "replace")) if body.strip() else {}
    except ValueError:
        document = {}
    if not isinstance(document, dict):
        document = {}
    caps = scoped(document)
    accounts.append({
        "account": name.decode(),
        "label": tag.decode(),
        "active": active == b"1",
        "five_hour": window(document.get("five_hour")),
        "weekly": window(document.get("seven_day")),
        "scoped": caps,
    })

# History. A row per account, at most one every GAP seconds — the bar ticks
# every 60s and the monitor polls on its own schedule, and both land here.
now = datetime.now()
stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
seen = last_seen({a["account"] for a in accounts})
rows = []
for account in accounts:
    if account["five_hour"] is None and account["weekly"] is None:
        continue                       # a failed probe is not a zero reading
    previous = seen.get(account["account"])
    if previous:
        try:
            age = (now - datetime.strptime(previous, "%Y-%m-%dT%H:%M:%S")).total_seconds()
        except ValueError:
            age = GAP
        if age < GAP:
            continue

    def cell(node, key):
        return "" if not node else str(node[key] if node[key] is not None else "")

    cap = (account["scoped"] or [None])[0]
    rows.append(",".join([
        stamp, account["account"],
        cell(account["five_hour"], "percent"), cell(account["five_hour"], "resets_in"),
        cell(account["weekly"], "percent"), cell(account["weekly"], "resets_in"),
        cell(cap, "percent"), (cap or {}).get("name", "").replace(",", " "),
    ]))

if rows:
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        fresh = not os.path.exists(PATH)
        # O_APPEND, one short write for the whole pass: the bar and the monitor
        # can both be in here at once, and appends that small do not interleave.
        with open(PATH, "a") as fh:
            if fresh:
                fh.write(HEADER)
            fh.write("\n".join(rows) + "\n")
        trim()
    except OSError:
        pass

if MODE == "json":
    json.dump(accounts, sys.stdout)
    sys.stdout.write("\n")
PY
)

emit() {
    walk_accounts | \
    CLAUDE_USAGE_MODE="$1" \
    CLAUDE_USAGE_HISTORY="$HISTORY_FILE" \
    CLAUDE_USAGE_HISTORY_GAP="$HISTORY_GAP" \
    CLAUDE_USAGE_HISTORY_DAYS="$HISTORY_DAYS" \
    python3 -c "$PY_EMIT"
}

if [[ "$MODE" != bar ]]; then
    emit "$MODE"
    exit 0
fi

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

# Record the sample last, and only after the block's own two lines are out:
# i3blocks reads this until EOF, so anything slow belongs behind the output,
# not in front of it. Every response it needs is already in the 120s cache.
emit sample
