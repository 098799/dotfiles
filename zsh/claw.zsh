# claw.zsh — the shortcuts opus, sonnet, haiku, fable, foreman (Claude Code) and flash,
# gopus, gsonnet (agy), on top of the engines claw and gclaw: Claude Code (or agy) in a
# fresh tmux session. Sourced by ~/.zshrc, and on its own by the niri launchers
# (Mod+S etc.) as `zsh -fc 'source …/claw.zsh; haiku'`: a full interactive zsh
# costs ~1.7 s before claude even starts. So this file must stand alone — no
# omz, no aliases, nothing else from .zshrc.

# claw [home] [claude args...] — start a tmux session named after the current
# directory and run `claude --dangerously-skip-permissions` in it.
# `claw --help` prints the usage plus the homes it found.

# Account tags are the ones on the i3 bar and the w95 System Monitor. Source of
# truth is the LABELS map in ~/dotfiles/i3-pkg/scripts/claude-usage.sh — keep
# these in step with it. There, "work" is ~/claude-prim under its legacy name
# and "private" is the real HOME, so claw translates prim → work.
# main2 is the second Max account (~/claude-main2, 1 Oct 2026): P2, next to private's P.
typeset -gA CLAW_TAGS=([work]=W [private]=P [main2]=P2 [builder]=B [sales]=S [success]=CS)

# From the passwd entry, not $HOME: a nested claw (inside a session that already
# overrode HOME) must still find the homes next to the real one.
_claw_root() { getent passwd "$(id -un)" | cut -d: -f6; }

# A real home has a .claude/ inside — that also keeps `claw memory` (a backup
# dir) from being read as a home instead of as a prompt for claude.
_claw_homes() {
  local -a h; h=($(_claw_root)/claude-*/.claude(/N:h:t))
  print -l -- "${h[@]#claude-}"
}

# Tag for a home suffix; "" means the real HOME, whose account the bar switches
# by copying credentials into ~/.claude, so read the bar's active-account file.
_claw_tag() {
  local acct="$1"
  [[ "$acct" == prim ]] && acct=work
  if [[ -z "$acct" ]]; then
    local f="$(_claw_root)/.config/claude-active-account"
    [[ -r "$f" ]] && acct="${$(<"$f")//[[:space:]]/}"
    [[ -n "$acct" ]] || acct=private
  fi
  print -r -- "${CLAW_TAGS[$acct]:-${(U)acct[1,1]}}"
}

_claw_help() {
  local root="$(_claw_root)" h
  print -r -- "claw — claude --dangerously-skip-permissions in a fresh tmux session"
  print -r -- ""
  print -r -- "usage: claw [--chrome|--no-chrome] [home|main] [claude args...]"
  print -r -- "       claw --help | -h"
  print -r -- ""
  print -r -- "Effort is forced to medium (CLAUDE_CODE_EFFORT_LEVEL; /effort is locked)."
  print -r -- "--effort <level> on the line forces that level instead. fable forces low."
  print -r -- ""
  print -r -- "The session is named after the current directory plus the account tag the i3"
  print -r -- "bar uses, so \`tmux ls\` says which account every session is on:"
  print -r -- "       ~/legartis4 + builder  ->  legartis4-B"
  print -r -- "A name already in use gets a numeric suffix: legartis4-B-2, legartis4-B-3, …"
  print -r -- ""
  print -r -- "homes (tab-completes):"
  printf '       %-10s %-3s %s\n' "<none>" "$(_claw_tag)" "\$HOME as it is — active account: $(
      f="$root/.config/claude-active-account"; [[ -r $f ]] && print -rn -- "${$(<$f)//[[:space:]]/}" || print -rn -- private)"
  for h in $(_claw_homes); do
    printf '       %-10s %-3s %s\n' "$h" "$(_claw_tag "$h")" "HOME=$root/claude-$h"
  done
  print -r -- ""
  print -r -- "With NO home named, the account is chosen by usage — the same selector"
  print -r -- "cmon/cherd's \"C\" spawns use (\`claude-account explain\` shows why). That"
  print -r -- "selector never chooses a Max account (main, main2): they are not spent on"
  print -r -- "work. \`claw main\` / \`claw main2\` is the only way onto them, and with no"
  print -r -- "other account free claw refuses rather than falling back to \$HOME."
  print -r -- "One exception, for TICKET spawns (cmon C, slotq, foreman, rcmon): a ticket"
  print -r -- "about the tooling itself (cmon/rcmon/cherd/slotq/slotctl/foreman/claw/burn"
  print -r -- "in the title, or the Tooling label) prefers main/main2 — \`claude-account"
  print -r -- "explain --ticket DEV-n\` shows it. claw has no ticket: name main2 yourself."
  print -r -- ""
  print -r -- "Only the FIRST word can name the account. When it is not an account, the"
  print -r -- "whole line goes to claude unchanged, so a prompt that happens to contain an"
  print -r -- "account name is never cut:"
  print -r -- "       claw builder -c            -c on builder"
  print -r -- "       claw -c builder            -c and the prompt \"builder\", selector picks"
  print -r -- ""
  print -r -- "claude's own flags still work, the short ones included:"
  print -r -- "       -c, --continue             resume the last session in this directory"
  print -r -- "       -r, --resume               pick a session from the list"
  print -r -- "       claw \"fix the flaky test\"  start on a prompt"
  print -r -- "       --chrome / --no-chrome     Claude in Chrome connection on (the default)"
  print -r -- "                                  / off; may come before the account:"
  print -r -- "                                  claw --no-chrome builder"
  print -r -- "Full set: \`claude --help\`."
}

# Repo-relative account selector. Overridable for a
# checkout somewhere else; silently unused if the repo isn't there.
: ${LEGARTIS_REPO:=$HOME/legartis}

# True when $1 names an account: "main" (the real $HOME) or a claude-<name> home.
# claw, fable and foreman all read the account from the FIRST word only, through
# this, so the three agree on what counts.
_claw_is_home() {
  [[ -n "$1" && ( "$1" == main || -d "$(_claw_root)/claude-$1/.claude" ) ]]
}

claw() {
  local root="$(_claw_root)"

  if [[ "$1" == (--help|-h) ]]; then
    _claw_help
    return 0
  fi

  # --chrome / --no-chrome (Claude in Chrome connection) may come before the
  # account, so `claw --chrome builder` lands on builder instead of sending
  # "builder" as a prompt. They go to claude in front of the other args.
  local -a chromeopt
  while [[ "$1" == (--chrome|--no-chrome) ]]; do
    chromeopt+=("$1"); shift
  done
  # Claude in Chrome is on by default; --no-chrome turns it off.
  (( ${#chromeopt} )) || chromeopt=(--chrome)

  # Only the first word can name the account. It used to be picked out anywhere
  # in the line, which cut a word like "sales" out of the middle of a prompt.
  # "main" means the real $HOME: no HOME override. If the first word is not an
  # account, every word goes to claude as it is.
  local chome="" cname="" picked=""
  if _claw_is_home "$1"; then
    cname="$1"
    [[ "$cname" != main ]] && chome="$root/claude-$cname"
    shift
  fi

  # No account named: ask the selector, exactly as a "C" spawn does, and let it
  # count this session as in-flight load so a second claw a minute later lands
  # somewhere else.
  #
  # An unreachable or refusing selector is now a REFUSAL, not a fallback. It used
  # to leave $HOME alone, which on this box quietly means the personal Max
  # subscription — the account that is not to be spent on work at all. So there is
  # exactly one way to land on it: type it (`claw main`). Everything else stops
  # here with the reason on screen.
  if [[ -z "$cname" ]]; then
    local why=""
    picked="$("$LEGARTIS_REPO"/tools/claude-account pick --home --commit 2>/dev/null)" || picked=""
    if [[ -n "$picked" && -d "$picked/.claude" ]]; then
      chome="$picked"
      cname="${picked:t}"          # /home/x/claude-prim -> claude-prim
      cname="${cname#claude-}"     #                     -> prim
    else
      # Re-run for the reason only — the first call is the one that charges the
      # ledger, and stderr was dropped there so a tmux-less shell stays quiet.
      why="$("$LEGARTIS_REPO"/tools/claude-account pick --home 2>&1 >/dev/null)"
      print -u2 -r -- "claw: no account to spawn on${why:+ — $why}"
      print -u2 -r -- "claw: the Max accounts are not spent on work. \`claw main\` or \`claw main2\` to use one anyway, or name an account: $(_claw_homes | paste -sd' ' -)"
      return 1
    fi
  fi

  local base="${PWD:t}"
  base="${base//[.:[:space:]]/-}"   # tmux gives "." and ":" a special meaning
  [[ -n "$base" ]] || base="claude"
  # "main" is the real $HOME, whose tag the i3 bar derives from the active-account
  # file — that is what _claw_tag does with an empty name, so don't tag it "M".
  base="${base}-$(_claw_tag "${cname:#main}")"

  local name="$base" n=2
  while tmux has-session -t "=$name" 2>/dev/null; do
    name="${base}-$((n++))"
  done

  # Effort is FORCED through CLAUDE_CODE_EFFORT_LEVEL, not --effort: the env var
  # beats --effort, settings.json (effortLevel: high) and modelSettings, and it
  # locks /effort for the session. Default medium; fable passes CLAW_EFFORT=low.
  # An --effort on the line wins (last one counts, as in claude).
  local effort="${CLAW_EFFORT:-medium}" a prev=""
  for a in "$@"; do
    [[ "$prev" == --effort ]] && effort="$a"
    [[ "$a" == --effort=* ]] && effort="${a#--effort=}"
    prev="$a"
  done

  # --dangerously-skip-permissions does not skip the folder-trust dialog; this does.
  local cmd="CLAUDE_CODE_SANDBOXED=1 CLAUDE_CODE_EFFORT_LEVEL=${(q)effort} claude --dangerously-skip-permissions"
  [[ -n "$chome" ]] && cmd="HOME=${(q)chome} $cmd"
  # Join first, then quote each word: inside "…" a bare ${(q)@} flattens all args
  # into ONE escaped word, so claude saw "-c --model x" as a single option.
  set -- "${chromeopt[@]}" "$@"
  (( $# )) && cmd+=" ${(j: :)${(q)@}}"

  # HOME is set on the claude command only, NOT on the session: a session-wide
  # HOME made every new pane start zsh in ~/claude-<home>, which has no .zshrc,
  # so it ran zsh-newuser-install. New panes get CLAW_HOME instead, and the
  # claude() wrapper below puts `claude` typed there back on the session's account.
  # Must be a real array: "${chome:+-e CLAW_HOME=$chome}" collapses into one word,
  # which tmux ignores silently instead of rejecting.
  local -a envopt
  [[ -n "$chome" ]] && envopt=(-e "CLAW_HOME=$chome")

  tmux new-session -d -s "$name" -c "$PWD" "${envopt[@]}" "$cmd" || return
  # CLAW_DETACH=1: print the session name and leave it detached. claw-fast uses
  # it to start the session behind its type-ahead box and attach later.
  if [[ -n "$CLAW_DETACH" ]]; then
    print -r -- "$name"
  elif [[ -n "$TMUX" ]]; then
    tmux switch-client -t "=$name"
  else
    tmux attach-session -t "=$name"
  fi
}

# In a pane of a claw session, `claude` runs on that session's account.
if [[ -n "$CLAW_HOME" ]]; then
  claude() { HOME="$CLAW_HOME" command claude "$@" }
fi

_claw() {
  local -a homes
  homes=($(_claw_root)/claude-*/.claude(/N:h:t))
  _describe 'claude home' "${homes[@]#claude-}"
}
(( $+functions[compdef] )) && compdef _claw claw

# fable [home] [claude args...] — claw on Fable 5.1, effort FORCED to low (claw
# turns CLAW_EFFORT into CLAUDE_CODE_EFFORT_LEVEL). Same account picking, same
# tmux naming. The --model default goes BEFORE "$@" on purpose: claude takes the
# LAST occurrence, so your own --model (or --effort) on the fable line wins. The
# account must stay the first word claw sees, so peel it off here and hand it
# over in front of the defaults.
fable() {
  if [[ "$1" == (--help|-h) ]]; then
    print -r -- "fable — claw with --model claude-fable-5-1, effort forced to low"
    print -r -- "usage: fable [home|main] [claude args...]   (see claw --help)"
    return 0
  fi
  local -a acct
  while [[ "$1" == (--chrome|--no-chrome) ]]; do acct+=("$1"); shift; done
  _claw_is_home "$1" && { acct+=("$1"); shift }
  CLAW_EFFORT=low claw "${acct[@]}" --model claude-fable-5-1 "$@"
}
(( $+functions[compdef] )) && compdef _claw fable

# haiku [home] [claude args...] — claw on Haiku 5.5. Same account picking, tmux
# naming and effort as claw (medium unless --effort or CLAW_EFFORT says else).
# Same --model ordering as fable: your own --model on the haiku line wins.
haiku() { _claw_shortcut haiku claude-haiku-5-5 "$@" }
(( $+functions[compdef] )) && compdef _claw haiku

# The shortcuts that differ only by model (Claude Code: opus, sonnet, haiku). Same account
# picking as claw, and your own --model on the line wins: claude takes the LAST --model.
# _claw_shortcut <name> <model> [claw args...]
_claw_shortcut() {
  local name="$1" model="$2"; shift 2
  if [[ "$1" == (--help|-h) ]]; then
    print -r -- "$name — claw with --model $model"
    print -r -- "usage: $name [home|main] [claude args...]   (see claw --help)"
    return 0
  fi
  local -a acct
  while [[ "$1" == (--chrome|--no-chrome) ]]; do acct+=("$1"); shift; done
  _claw_is_home "$1" && { acct+=("$1"); shift }
  claw "${acct[@]}" --model "$model" "$@"
}

# opus — claw on Opus, no account picked (the usage selector still chooses one).
opus() { _claw_shortcut opus opus "$@" }
(( $+functions[compdef] )) && compdef _claw opus

# sonnet [home] [claude args...] — claw on Sonnet 5.5.
sonnet() { _claw_shortcut sonnet claude-sonnet-5-5 "$@" }
(( $+functions[compdef] )) && compdef _claw sonnet

# foreman [home] [text...] — claw started on "/foreman <text>". The first word is
# the account if it names one; all the other words are joined into ONE prompt, so
# `foreman main please make queue work` opens main on "/foreman please make queue
# work". If the first word is not an account, it is part of the text too.
foreman() {
  if [[ "$1" == (--help|-h) ]]; then
    print -r -- "foreman — claw started on the prompt \"/foreman <text>\""
    print -r -- "usage: foreman [home|main] [text...]   (see claw --help for homes)"
    print -r -- "       foreman main please make queue work"
    print -r -- "       foreman !7301                 selector picks the account"
    return 0
  fi
  local -a acct
  while [[ "$1" == (--chrome|--no-chrome) ]]; do acct+=("$1"); shift; done
  _claw_is_home "$1" && { acct+=("$1"); shift }
  claw "${acct[@]}" "/foreman${*:+ $*}"
}
(( $+functions[compdef] )) && compdef _claw foreman

# gclaw [home|main] [agy args...] — claw for Antigravity's `agy`: a fresh tmux
# session named after the current directory, running
# `agy --dangerously-skip-permissions`. `main` (or no home) is the real HOME. A
# home is ~/agy-<name>/: agy runs with HOME=~/agy-<name>, so its data
# ($HOME/.gemini) and plugin secrets ($HOME/.config/antigravity) live there.
#
# The login is the catch: agy keeps it in the desktop keyring (secret service,
# "antigravity" on "gemini"), one entry per USER, not per HOME, so a fake HOME
# alone would sign in as main. agy skips the keyring and keeps the token in a
# file under $HOME when it finds no D-Bus session bus (unset is not enough: it
# falls back to the default socket), so a fake-home agy gets a dead bus address.
# Its child shells get the real address back through BASH_ENV and the home's
# .zshenv, or glab, dunstify, secret-tool… would break inside the session.
_gclaw_homes() {
  local -a h; h=($(_claw_root)/agy-*(/N:t))
  print -l -- "${h[@]#agy-}"
}

_gclaw_is_home() {
  [[ -n "$1" && ( "$1" == main || -d "$(_claw_root)/agy-$1" ) ]]
}

# Write the pieces a fake home needs. Rewritten on every start, so a home made
# by hand (mkdir ~/agy-x) works too.
_gclaw_prep_home() {
  local h="$1" root="$(_claw_root)"
  mkdir -p "$h/.gemini/antigravity-cli" || return
  # Trust the real home tree, as main's settings do, so the first start in a
  # repo does not stop on agy's workspace-trust question. agy rewrites this
  # file itself later, so only seed it.
  [[ -e "$h/.gemini/antigravity-cli/settings.json" ]] ||
    printf '{\n  "trustedWorkspaces": [\n    "%s"\n  ]\n}\n' "$root" > "$h/.gemini/antigravity-cli/settings.json"
  print -r -- '# gclaw: give child shells of agy the real D-Bus address back (see .zshrc).
if [ -n "${GCLAW_DBUS+x}" ]; then
  if [ -n "$GCLAW_DBUS" ]; then export DBUS_SESSION_BUS_ADDRESS="$GCLAW_DBUS"; else unset DBUS_SESSION_BUS_ADDRESS; fi
  unset GCLAW_DBUS BASH_ENV
fi' > "$h/.gclaw-dbus.sh"
  # Never in the real HOME (main on a token file): that .zshenv is the user's own.
  # There a zsh child keeps the dead bus; bash children still get it back.
  [[ "$h" != "$root" ]] && print -r -- '. "$HOME/.gclaw-dbus.sh"' > "$h/.zshenv"
  return 0
}

_gclaw_help() {
  local root="$(_claw_root)" h
  print -r -- "gclaw — agy --dangerously-skip-permissions in a fresh tmux session"
  print -r -- ""
  print -r -- "usage: gclaw [home|main] [agy args...]"
  print -r -- "       gclaw --new <name>     make the home $root/agy-<name>"
  print -r -- "       gclaw --help | -h"
  print -r -- ""
  print -r -- "Only the FIRST word can name the home, as in claw. Session name:"
  print -r -- "       ~/legartis4 + home work  ->  legartis4-agy-work"
  print -r -- ""
  print -r -- "homes (tab-completes):"
  printf '       %-10s %s\n' "main" "\$HOME as it is ($root), login in the desktop keyring"
  for h in $(_gclaw_homes); do
    printf '       %-10s %s\n' "$h" "HOME=$root/agy-$h, login in a file there"
  done
  print -r -- "No home named = main. A new home asks for a Google login at its first start."
  print -r -- ""
  print -r -- "agy's own flags still work: -c, --model, --effort, -i \"prompt\", …  (agy --help)"
}

gclaw() {
  local root="$(_claw_root)"

  if [[ "$1" == (--help|-h) ]]; then
    _gclaw_help
    return 0
  fi

  if [[ "$1" == --new ]]; then
    [[ -n "$2" && "$2" != main && "$2" != *[^[:alnum:]_-]* ]] ||
      { print -u2 -r -- "gclaw: --new needs a name ([a-z0-9_-], not main)"; return 1 }
    local nh="$root/agy-$2"
    [[ -e "$nh" ]] && { print -u2 -r -- "gclaw: $nh exists already"; return 1 }
    _gclaw_prep_home "$nh" || return
    print -r -- "gclaw: made $nh — \`gclaw $2\` starts on it; log in at the first start"
    return 0
  fi

  local ahome="" aname="main"
  if _gclaw_is_home "$1"; then
    aname="$1"
    [[ "$aname" != main ]] && ahome="$root/agy-$aname"
    shift
  fi
  # main keeps its login in the keyring, except where a token file holds it (p340:
  # its keyring is locked, nobody types the password). On the file, main runs like a
  # fake home: dead bus, restore script — same rule as cmon/agy_accounts.py.
  local afile=""
  [[ -n "$ahome" || -f "$root/.gemini/antigravity-cli/antigravity-oauth-token" ]] && afile="${ahome:-$root}"

  local base="${PWD:t}"
  base="${base//[.:[:space:]]/-}"   # tmux gives "." and ":" a special meaning
  [[ -n "$base" ]] || base="agy"
  base="${base}-agy-${aname}"

  local name="$base" n=2
  while tmux has-session -t "=$name" 2>/dev/null; do
    name="${base}-$((n++))"
  done

  # Absolute path: the binary lives under the real HOME, and a nested gclaw may
  # run with HOME pointed elsewhere.
  local cmd="${(q)root}/.local/bin/agy --dangerously-skip-permissions"
  if [[ -n "$afile" ]]; then
    _gclaw_prep_home "$afile" || return
    cmd="HOME=${(q)afile} GCLAW_DBUS=${(q)DBUS_SESSION_BUS_ADDRESS} BASH_ENV=${(q)afile}/.gclaw-dbus.sh DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent/gclaw-no-bus $cmd"
    # glab reads its login from $HOME: point it at the real one, or MRs cannot be opened.
    [[ "$afile" != "$root" && -d $root/.config/glab-cli ]] && cmd="GLAB_CONFIG_DIR=${(q)root}/.config/glab-cli $cmd"
  fi
  # Claude Code's context for agy (rules, memories, skills): cmon/agy_context.py.
  [[ -f $root/legartis/cmon/agy_context.py ]] &&
    python3 "$root/legartis/cmon/agy_context.py" sync "${ahome:-$root}" >/dev/null 2>&1
  (( $# )) && cmd+=" ${(j: :)${(q)@}}"

  # HOME on the agy command only, never on the session (same reason as claw: a
  # pane in a HOME with no .zshrc runs zsh-newuser-install). AGY_HOME puts `agy`
  # typed in a new pane back on the session's home.
  local -a envopt
  [[ -n "$ahome" ]] && envopt=(-e "AGY_HOME=$ahome")

  tmux new-session -d -s "$name" -c "$PWD" "${envopt[@]}" "$cmd" || return
  if [[ -n "$TMUX" ]]; then
    tmux switch-client -t "=$name"
  else
    tmux attach-session -t "=$name"
  fi
}

# In a pane of a gclaw session, `agy` runs on that session's home, keyring off.
if [[ -n "$AGY_HOME" ]]; then
  agy() {
    HOME="$AGY_HOME" GCLAW_DBUS="$DBUS_SESSION_BUS_ADDRESS" BASH_ENV="$AGY_HOME/.gclaw-dbus.sh" \
      GLAB_CONFIG_DIR="${GLAB_CONFIG_DIR:-/home/tgrining/.config/glab-cli}" \
      DBUS_SESSION_BUS_ADDRESS=unix:path=/nonexistent/gclaw-no-bus command agy "$@"
  }
fi

_gclaw() {
  local -a homes
  homes=(main $(_claw_root)/agy-*(/N:t))
  _describe 'agy home' "${homes[@]#agy-}"
}
(( $+functions[compdef] )) && compdef _gclaw gclaw

# _agy_shortcut <name> <model> <default effort> [gclaw args...] — the agy shortcuts
# (flash, gopus, gsonnet). The effort goes on the line unless an --effort is already
# there, or GCLAW_EFFORT says else. agy has no env var that locks the model the way
# CLAUDE_CODE_EFFORT_LEVEL locks claw's effort: these are start flags, and /model or
# /effort inside the session can still change them. Always pass the model: a home's
# saved default may be another one (main's was Claude Sonnet).
_agy_shortcut() {
  local name="$1" model="$2" effort="$3"; shift 3
  if [[ "$1" == (--help|-h) ]]; then
    print -r -- "$name — gclaw with --model $model --effort $effort"
    print -r -- "usage: $name [home|main] [agy args...]   (see gclaw --help)"
    print -r -- "       --effort low|medium|high|xhigh|max on the line, or GCLAW_EFFORT, sets the effort"
    return 0
  fi
  local -a acct eff
  _gclaw_is_home "$1" && { acct+=("$1"); shift }
  local a seen=""
  for a in "$@"; do [[ "$a" == (--effort|--effort=*) ]] && seen=1; done
  [[ -n "$seen" ]] || eff=(--effort "${GCLAW_EFFORT:-$effort}")
  gclaw "${acct[@]}" --model "$model" "${eff[@]}" "$@"
}

# flash — agy on Gemini 3.8 Flash.
flash() { _agy_shortcut flash gemini-3.8-flash high "$@" }
(( $+functions[compdef] )) && compdef _gclaw flash

# gopus — agy on Claude Opus 5.5 (served through agy's own quota, not Claude Code's).
gopus() { _agy_shortcut gopus claude-opus-5-5 high "$@" }
(( $+functions[compdef] )) && compdef _gclaw gopus

# gsonnet — agy on Claude Sonnet 5.5 (agy's quota, see gopus).
gsonnet() { _agy_shortcut gsonnet claude-sonnet-5-5 high "$@" }
(( $+functions[compdef] )) && compdef _gclaw gsonnet
