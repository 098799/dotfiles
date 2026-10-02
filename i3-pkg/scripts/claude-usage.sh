#!/bin/bash
# Claude.ai usage for i3blocks / waybar / w95 — a READER.
# Shows usage for every configured account, emphasises the active one
# Right-click: rofi menu to switch account (also switches Claude Code credentials)
#
#   claude-usage.sh            the i3blocks line (five-hour window, active bold)
#   claude-usage.sh --json     every window as JSON — what w95-sysmon reads
#   claude-usage.sh --sample   no-op, kept for old callers
#
# Nothing here asks Anthropic. rcmon's usage federation (rcmon/usage_federation.py in
# the Legartis repo, DEV-6940) is the one quota checker on each box: it merges this
# box's readings with the other box's and writes ~/.local/state/w95/claude-usage.json
# (and the history CSV beside it). This script only reads that snapshot.

# The REAL home, not $HOME: agents run with HOME=~/claude-<account> and may call this
# script; read through their $HOME it found no accounts and saved their own team
# credentials as ~/claude-prim/.claude/.credentials-private.json (seen 30 Sep 2026).
HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
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

SNAPSHOT="${CLAUDE_USAGE_SNAPSHOT:-$HOME/.local/state/w95/claude-usage.json}"

# Accounts in display order: the three legacy ones first, then any extra
# discovered from either a claude-cookies-<name> file in $CONFIG_DIR or a
# ~/claude-<name> alt HOME holding a Claude Code login — the same two
# conventions the other monitors (and rcmon's usage federation) auto-discover.
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
# main2 is the second Max account (~/claude-main2, 1 Oct 2026): P2 pairs it with
# private's P. The same pins live in claw's CLAW_TAGS (.zshrc), cmon's SESSION_TAGS
# and qtop's LETTER — keep all four in step.
declare -A LABELS=([work]=W [private]=P [main2]=P2 [builder]=B [sales]=S [success]=CS)

# Auto-label the remaining discovered accounts by initial, lengthening the prefix
# until no two of them collide: `sales` and `success` both wanted "S", and the bar
# read "S:3% S:81%" with nothing to say which was which. The length is chosen once
# and applied to all of them, so they stay the same width and a new account
# widens the set rather than making one odd label longer than its neighbours.
# Only the bar cares — the other monitors and the System Monitor key everything by
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

# Only an account with a backup in ~/.claude can be switched into the real home
# (private always can: the live file is its own). An account that lives in its own
# ~/claude-<name> home and has no backup — main2, success — is used there, by name
# (`claw main2`). A copy of its login in ~/.claude would be a second holder of one
# refresh chain, and the first to refresh logs the other out.
switchable() { [[ "$1" == private || -f "$HOME/.claude/.credentials-$1.json" ]]; }

# Keep active account's backup in sync (tokens get refreshed by Claude Code).
# Never for an account that was not switched in: the live file then still holds
# another account's login, and saving it under this name would hand that login to
# every reader of the backup (creds_for, rcmon).
if [[ -f "$CLAUDE_CREDS" ]] && switchable "$ACCOUNT"; then
    BACKUP="$HOME/.claude/.credentials-$ACCOUNT.json"
    if ! cmp -s "$CLAUDE_CREDS" "$BACKUP" 2>/dev/null; then
        cp "$CLAUDE_CREDS" "$BACKUP"
    fi
fi

# Handle click
case $BLOCK_BUTTON in
    3)
        eval $(xdotool getmouselocation --shell)
        # Only switchable accounts, current one pre-selected.
        MENU_ACCOUNTS=()
        for _a in "${ACCOUNTS[@]}"; do switchable "$_a" && MENU_ACCOUNTS+=("$_a"); done
        SELECTED=0
        for i in "${!MENU_ACCOUNTS[@]}"; do
            [[ "${MENU_ACCOUNTS[$i]}" == "$ACCOUNT" ]] && SELECTED=$i && break
        done
        MENU=$(printf '%s\n' "${MENU_ACCOUNTS[@]}")
        CHOICE=$(echo "$MENU" | rofi -dmenu -p "claude" -selected-row $SELECTED -theme-str "window {width: 200px; location: north west; x-offset: ${X}px; y-offset: ${Y}px;} listview {lines: ${#MENU_ACCOUNTS[@]};}")
        if [[ -n "$CHOICE" && "$CHOICE" != "$ACCOUNT" ]] && switchable "$CHOICE"; then
            echo "$CHOICE" > "$ACCOUNT_FILE"
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

[[ "$MODE" == sample ]] && exit 0

# One pass over the snapshot. Bar mode prints "label<TAB>text<TAB>colour" per account;
# json mode prints the list w95-sysmon reads. Accounts, labels and the active flag come
# from here (the bar's own vocabulary); the numbers come from the federation.
PY_READ=$(cat <<'PY'
import json, sys, time

mode, path, active = sys.argv[1], sys.argv[2], sys.argv[3]
names = sys.argv[4::2]
labels = sys.argv[5::2]
now = time.time()
STALE_SNAPSHOT_S = 300   # the federation writes every 30 s; older = rcmon is not running
STALE_READING_S = 900    # shown, but marked "~": no fresh reading for 15 min

try:
    snap = json.load(open(path))
    rows = {r["account"]: r for r in snap.get("accounts") or [] if isinstance(r, dict)}
    down = now - float(snap.get("updated_at") or 0) > STALE_SNAPSHOT_S
except (OSError, ValueError, TypeError):
    rows, down = {}, True


def human(seconds):
    """"2d10h", "4h6m", "12m" — the bar's spelling, with days for the weekly."""
    if seconds is None:
        return ""
    if seconds <= 0:
        return "soon"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return "%dd%dh" % (days, hours)
    if hours:
        return "%dh%dm" % (hours, rest // 60)
    return "%dm" % (rest // 60)


def win(node):
    """A snapshot window as of now: its resets_in counted from the snapshot's write."""
    if not node or node.get("percent") is None:
        return None
    left = node.get("resets_in")
    if left is not None and not down:
        left = max(0, int(left - (now - float(snap["updated_at"]))))
    return {"percent": node["percent"], "resets_in": left, "resets": human(left)}


def colour(percent, left):
    """Green/yellow/red by burn rate over the 5h window, by level when it has not started."""
    if left is not None and left > 0:
        elapsed = 100 - left * 100 // 18000
        if elapsed > 0:
            rate = percent / elapsed
            return "#dc322f" if rate > 1.0 else "#b58900" if rate > 0.67 else "#859900"
        return "#859900"
    return "#dc322f" if percent >= 80 else "#b58900" if percent >= 50 else "#859900"


out = []
for name, label in zip(names, labels):
    row = {} if down else rows.get(name, {})
    five, weekly = win(row.get("five_hour")), win(row.get("weekly"))
    scoped = [w | {"name": c.get("name", "scoped")} for c in row.get("scoped") or [] if (w := win(c))]
    if mode == "json":
        out.append({"account": name, "label": label, "active": name == active,
                    "five_hour": five, "weekly": weekly, "scoped": scoped,
                    "source": row.get("source"), "host": row.get("host"),
                    "age_s": row.get("age_s"), "error": row.get("error") or ("usage federation not running" if down else "")})
        continue
    if not five:
        print("%s\t%s:?\t#657b83" % (name, label))
        continue
    stale = "~" if (row.get("age_s") or 0) > STALE_READING_S else ""
    text = "%s:%s%d%%" % (label, stale, five["percent"])
    print("%s\t%s\t%s\t%s" % (name, text, colour(five["percent"], five["resets_in"]), five["resets"]))
if mode == "json":
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
PY
)

ARGS=()
for acct in "${ACCOUNTS[@]}"; do ARGS+=("$acct" "${LABELS[$acct]:-${acct:0:1}}"); done

if [[ "$MODE" == json ]]; then
    python3 -c "$PY_READ" json "$SNAPSHOT" "$ACCOUNT" "${ARGS[@]}"
    exit 0
fi

# Build display for each account
format_account() {
    local text="$1" color="$2" reset="$3" is_active="$4"
    [[ -n "$reset" ]] && text="${text}(${reset})"
    if [[ "$is_active" == "1" ]]; then
        echo "<span foreground='$color'><b>${text}</b></span>"
    else
        echo "<span foreground='#657b83'>${text}</span>"
    fi
}

SPANS=""
SHORT=""
while IFS=$'\t' read -r acct text color reset; do
    [[ "$acct" == "$ACCOUNT" ]] && active=1 || active=0
    SPANS="${SPANS}$(format_account "$text" "$color" "$reset" "$active") "
    # short_text: the same coloured spans without the reset timers. The laptop
    # waybar shows it (no room for the timers); i3bar did on overflow too.
    SHORT="${SHORT}$(format_account "$text" "$color" "" "$active") "
done < <(python3 -c "$PY_READ" bar "$SNAPSHOT" "$ACCOUNT" "${ARGS[@]}")

echo " 󰚩 ${SPANS}"
echo "󰚩 ${SHORT}"
