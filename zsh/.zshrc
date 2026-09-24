# Dumb terminal handling (for Emacs TRAMP, etc.)
if [[ "$TERM" == "dumb" ]]; then
    unsetopt zle
    unsetopt prompt_cr
    unsetopt prompt_subst
    unfunction precmd 2>/dev/null
    unfunction preexec 2>/dev/null
    PS1='$ '
    return
fi

# Enable Powerlevel10k instant prompt (must stay near top)
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
    source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# Oh-My-Zsh configuration
export ZSH="$HOME/.oh-my-zsh"
export WORKON_HOME="$HOME/.virtualenvs"
DISABLE_UPDATE_PROMPT=true

plugins=(
    command-not-found
    fast-syntax-highlighting
    git
    pip
    python
    sudo
    virtualenvwrapper
    colorize
    rsync
    z
)

source $ZSH/oh-my-zsh.sh

# Completion caching
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path ~/.zsh/cache

# VTE integration
[ -f /etc/profile.d/vte.sh ] && source /etc/profile.d/vte.sh

# Virtualenvwrapper
export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3
source "$HOME/.local/bin/virtualenvwrapper.sh"
export PYTHONPATH="${PYTHONPATH}:$HOME/.virtualenvs:$HOME"
export VIRTUAL_ENV_DISABLE_PROMPT=1

# Editor configuration
alias e="emacsclient -t"
alias ee="emacsclient -c"
export EDITOR="emacsclient -c"
export VISUAL="emacsclient -c"

# General aliases
alias watch="watch "
alias cd..='cd ..'
alias p3='ipython'
alias mdview='google-chrome-stable'
alias cal='cal -m'
alias sl='ls'
alias LS='ls'
alias ll='ls -alh'
alias vi='vim'
alias pyt='pytest -nauto -sxk ""'
alias rmvirtualenv='deactivate && rmvirtualenv $(pwd | rev | cut -f 1 -d "/" | rev)'
alias refvirtualenv='rmvirtualenv && mkvirtualenv'
alias emacs-test='emacs -batch -l ert -l ~/.emacs.conf/elisp.el -l ~/.emacs.conf/autoimport.el -l ~/.emacs.conf/test-elisp.el -f ert-run-tests-batch-and-exit'
alias supen='cd ~/pypen && cd dpypen && workon pypen && supen'
alias suink='cd ~/pypen && cd dpypen && workon pypen && suink'
alias ranger='ranger --choosedir=/tmp/.rangerdir; LASTDIR=$(cat /tmp/.rangerdir); cd "$LASTDIR"'
alias adb='~/.buildozer/android/platform/android-sdk/platform-tools/adb'

# Use bat instead of cat
if command -v bat &> /dev/null; then
    alias cat='bat --paging=never'
fi

# Python configuration
export PYTHONBREAKPOINT=ipdb.set_trace
export PYTHONSTARTUP="$HOME/dotfiles/pythonstartup.py"

py3clean() {
    find . -type f -name "*.py[co]" -delete
    find . -type d -name "__pycache__" -delete
}

export PATH_TO_HTML=/tmp

# DBus activation
# NEVER `--all` here. `--all` pushes this pane's ENTIRE env into the dbus/systemd
# user activation environment, and systemd --user outlives the session, so the
# junk is inherited by the NEXT compositor and by every app it spawns. That is
# what broke the niri switch: an empty ZDOTDIR got baked in, which makes zsh read
# /.zshrc instead of ~/.zshrc, so terminals opened with no aliases and no `claw`.
# Under `niri --session` (systemd-managed) the session exports these itself, so
# only do this for a session that has no manager to do it — i.e. plain startx.
if [[ -z "$XDG_SESSION_DESKTOP" && -n "$DISPLAY" ]]; then
    dbus-update-activation-environment --systemd \
        DISPLAY XAUTHORITY XDG_CURRENT_DESKTOP XDG_SESSION_TYPE 2>/dev/null
fi

# Compiler configuration
export FC="gfortran"
export CXX="g++"
export CC="gcc"

# PATH
PATH="$PATH:$HOME/bin:$HOME/.local/bin"
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"

# Powerlevel10k theme
source /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

#---------------------------------------------------------------------------
# Work-specific
#---------------------------------------------------------------------------

# Kubectl aliases
alias k='kubectl'
alias kg="k get"
alias kgp="k get pods"
alias kgpi="k get pods -n inference-models"
alias kgpl="k get pods -n legartis-prod"
alias kgna="k get namespaces"
alias kgno="k get nodes"

alias knsl="kubie ns legartis-prod"
alias knsi="kubie ns inference-models"
alias kns="kubie ns"

alias kd="k describe"
alias kdp="k describe pod"
alias kdna="k describe namespaces"
alias kdno="k describe nodes"

# === dev-env slot helpers ===
# Resolves paths: no arg / "" → the base worktree + its virtualenv
#                  N          → the Nth slot's worktree + its virtualenv
# Sources slot.env when available so DB connections hit the right postgres.

_legartis_slot_env() {
  local slot="$1"
  local envfile="$HOME/.legartis/slots/${slot}/slot.env"
  [[ -n "$slot" && -f "$envfile" ]] && set -a && source "$envfile" && set +a
}

_legartis_dir()  { echo "$HOME/legartis${1:+$1}"; }
_legartis_venv() { echo "$HOME/.virtualenvs/legartis${1:+$1}"; }

# cd into the backend service dir for a slot
o() { cd "$(_legartis_dir "$1")/services/backend/ontology_service/"; }

# Django shell_plus (runs in subshell to not leak env vars)
oshell() {
  local slot="$1"; shift
  ( _legartis_slot_env "$slot"
    "$(_legartis_venv "$slot")/bin/python" -m ontology_service.manage shell_plus "$@" )
}

# Backend service tests
otest() {
  local slot="$1"; shift
  _legartis_slot_env "$slot"
  cd "$(_legartis_dir "$slot")/services/backend/ontology_service/"
  PYTEST_RUN=True "$(_legartis_venv "$slot")/bin/pytest" \
    "-o=python_files=tests.py *_tests.py *_itests.py test_*.py" \
    --create-db --no-migrations --disable-pytest-warnings \
    --ds=ontology_service.configuration.settings \
    -m "not isolateme" -W "ignore" -n 8 "$@"
}

# E2E tests
etest() {
  local slot="$1"; shift
  _legartis_slot_env "$slot"
  "$(_legartis_venv "$slot")/bin/pytest" \
    --disable-pytest-warnings -o="python_files=test_*.py" -W "ignore" "$@"
}

# Run a Python script with slot env + slot venv (runs in subshell)
# Usage: sh <slot> <script> [args...]  e.g. sh 4 scripts_2026/backfill_risk_levels.py
lpy() {
  local slot="$1"; shift
  ( _legartis_slot_env "$slot"
    "$(_legartis_venv "$slot")/bin/python" "$@" )
}

# Sync this branch's new auth roles to dev, additively, from the Nth slot
# worktree. Wraps `pnpm run deploy:branch-roles:with-login`.
#
# A role that already exists is skipped whole, with its group mappings, so this
# can never repair a role with wrong or missing groups. Check those by hand.
#
# Undo: `pnpm run destroy:branch-roles:with-login`.
# Usage: keycloak <slot> [extra args]  e.g. keycloak 0
keycloak() {
  local slot="$1"; shift
  ( cd "$(_legartis_dir "$slot")/deployments/cdktf" \
      && pnpm run deploy:branch-roles:with-login "$@" )
}

# Numbered shortcuts — e.g. oshell4, otest4, etest4, o4, lpy4, keycloak4
for _n in 0 1 2 3 4 5 6 7 8; do
  eval "oshell${_n}()   { oshell ${_n} \"\$@\"; }"
  eval "otest${_n}()    { otest ${_n} \"\$@\"; }"
  eval "etest${_n}()    { etest ${_n} \"\$@\"; }"
  eval "o${_n}()        { o ${_n}; }"
  eval "lpy${_n}()      { lpy ${_n} \"\$@\"; }"
  eval "keycloak${_n}() { keycloak ${_n} \"\$@\"; }"
done
unset _n

# Ansible
alias ap='ansible-playbook'
ANSIBLE_COW_SELECTION=random

# Docker helpers
dvrm() {
    for did in $(docker volume ls | awk '{print $2}'); do
        docker volume rm $did
    done
}

dcrm() {
    for did in $(docker ps -a | cut -f 1 -d " "); do
        docker rm $did
    done
}

drm() {
    for did in $(docker ps | cut -f 1 -d " "); do
        docker kill $did
    done
}

dl() {
    docker logs $1 -f
}

de() {
    docker exec -it $1 bash
}

# Kubernetes shell helpers
ke() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    service=$(echo $service_pod | cut -f "1" -d "-")
    k exec $service_pod --stdin --tty -- python -m "$service"_service.manage shell_plus
}

kex() {
    service_pod="ontology-consumer-worker"
    service_pod=$(kgp | cut -f "1" -d " " | grep $service_pod | head "-$2" | tail -1)
    service=$(echo $service_pod | cut -f "1" -d "-")
    k exec $service_pod --stdin --tty -- python -m "$service"_service.manage shell_plus
}

kep() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl exec -it $service_pod -- awk 'BEGIN {system("/bin/bash")}'
}

kepx() {
    service_pod="ontology-consumer-worker"
    service_pod=$(kgp | cut -f "1" -d " " | grep $service_pod | head "-$2" | tail -1)
    kubectl exec -it $service_pod -- awk 'BEGIN {system("/bin/bash")}'
}

kep2() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -2 | head -1)
    k exec $service_pod --stdin --tty -- /bin/bash
}

kep3() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -3 | head -1)
    k exec $service_pod --stdin --tty -- /bin/bash
}

kepc() {
    k exec $1 --stdin --tty -c $2 -- /bin/bash
}

kepshc() {
    k exec $1 --stdin --tty -c $2 -- /bin/sh
}

kepsh() {
    k exec $1 --stdin --tty -- /bin/sh
}

# Kubernetes log helpers
klp() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl logs $service_pod
}

klr() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl logs $service_pod | log_reader
}

kl() {
    kubectl logs $@
}

klf() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl logs -f $service_pod ${@:3}
}

kld() {
    k logs -l deployment=$1 -f --tail=1000
}

kli() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | tail -1)
    kubectl logs $service_pod ${@:3} -c init
}

klif() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | tail -1)
    kubectl logs -f $service_pod ${@:3} -c init
}

#---------------------------------------------------------------------------
# tmux + claude
#---------------------------------------------------------------------------

# claw [home] [claude args...] — start a tmux session named after the current
# directory and run `claude --dangerously-skip-permissions` in it.
# `claw --help` prints the usage plus the homes it found.

# Account tags are the ones on the i3 bar and the w95 System Monitor. Source of
# truth is the LABELS map in ~/dotfiles/i3-pkg/scripts/claude-usage.sh — keep
# these in step with it. There, "work" is ~/claude-prim under its legacy name
# and "private" is the real HOME, so claw translates prim → work.
typeset -gA CLAW_TAGS=([work]=W [private]=P [builder]=B [sales]=S [success]=CS)

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
  print -r -- "usage: claw [home|main] [claude args...]"
  print -r -- "       claw --help | -h"
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
  print -r -- "selector never chooses MAIN: it is not spent on work. \`claw main\` is the"
  print -r -- "only way onto it, and with no other account free claw refuses rather than"
  print -r -- "falling back to \$HOME."
  print -r -- ""
  print -r -- "Every other word goes to claude, in any order — the home is picked out"
  print -r -- "wherever it sits, so these are the same:"
  print -r -- "       claw builder -c            claw -c builder"
  print -r -- ""
  print -r -- "claude's own flags still work, the short ones included:"
  print -r -- "       -c, --continue             resume the last session in this directory"
  print -r -- "       -r, --resume               pick a session from the list"
  print -r -- "       claw \"fix the flaky test\"  start on a prompt"
  print -r -- "Full set: \`claude --help\`."
}

# Repo-relative account selector. Overridable for a
# checkout somewhere else; silently unused if the repo isn't there.
: ${LEGARTIS_REPO:=$HOME/legartis}

claw() {
  local root="$(_claw_root)"

  if [[ "$1" == (--help|-h) ]]; then
    _claw_help
    return 0
  fi

  # The home may sit anywhere in the line, so `claw -c builder` works as well as
  # `claw builder -c`. Only a whole argument matching a real home counts; every
  # other word keeps its order and goes to claude. "main" is a name too — it means
  # the real $HOME, and it has to be matched here or it would be passed to claude
  # as a prompt.
  local chome="" cname="" a picked=""
  local -a rest
  for a in "$@"; do
    if [[ -z "$chome" && -z "$cname" && "$a" == main ]]; then
      cname=main
    elif [[ -z "$chome" && "$cname" != main && -d "$root/claude-$a/.claude" ]]; then
      cname="$a"; chome="$root/claude-$a"
    else
      rest+=("$a")
    fi
  done
  set -- "${rest[@]}"

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
      print -u2 -r -- "claw: the personal account is not spent on work. \`claw main\` to use it anyway, or name an account: $(_claw_homes | paste -sd' ' -)"
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

  local cmd="claude --dangerously-skip-permissions"
  # Join first, then quote each word: inside "…" a bare ${(q)@} flattens all args
  # into ONE escaped word, so claude saw "-c --model x" as a single option.
  (( $# )) && cmd+=" ${(j: :)${(q)@}}"

  # -e keeps HOME set for every pane of the session, not just the first command.
  # Must be a real array: "${chome:+-e HOME=$chome}" collapses into one word,
  # which tmux ignores silently instead of rejecting.
  local -a envopt
  [[ -n "$chome" ]] && envopt=(-e "HOME=$chome")

  tmux new-session -d -s "$name" -c "$PWD" "${envopt[@]}" "$cmd" || return
  if [[ -n "$TMUX" ]]; then
    tmux switch-client -t "=$name"
  else
    tmux attach-session -t "=$name"
  fi
}

_claw() {
  local -a homes
  homes=($(_claw_root)/claude-*/.claude(/N:h:t))
  _describe 'claude home' "${homes[@]#claude-}"
}
(( $+functions[compdef] )) && compdef _claw claw

# fable [home] [claude args...] — claw on Fable 5.1 at low effort. Same account
# picking, same tmux naming. The defaults go BEFORE "$@" on purpose: claude takes
# the LAST occurrence of --model/--effort, so this is what lets your own
# --model/--effort on the fable line win. claw finds a home name at any position.
fable() {
  if [[ "$1" == (--help|-h) ]]; then
    print -r -- "fable — claw with --model claude-fable-5-1 --effort low"
    print -r -- "usage: fable [home|main] [claude args...]   (see claw --help)"
    return 0
  fi
  claw --model claude-fable-5-1 --effort low "$@"
}
(( $+functions[compdef] )) && compdef _claw fable

#---------------------------------------------------------------------------
# External tools
#---------------------------------------------------------------------------

# Haskell
[ -f "$HOME/.ghcup/env" ] && source "$HOME/.ghcup/env"

# FZF
source /usr/share/fzf/key-bindings.zsh
source /usr/share/fzf/completion.zsh

# Google Cloud SDK
if [ -f "$HOME/Programs/google-cloud-sdk/path.zsh.inc" ]; then
    source "$HOME/Programs/google-cloud-sdk/path.zsh.inc"
fi
if [ -f "$HOME/Programs/google-cloud-sdk/completion.zsh.inc" ]; then
    source "$HOME/Programs/google-cloud-sdk/completion.zsh.inc"
fi

# NVM
source /usr/share/nvm/init-nvm.sh
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && source "$NVM_DIR/bash_completion"

# Force block cursor (for terminal emulators)
_fix_cursor() {
    echo -ne '\e[2 q'
}
precmd_functions+=(_fix_cursor)

source ~/.profile
export PATH=~/.npm-global/bin:$PATH

# bun completions
[ -s "/home/tgrining/.bun/_bun" ] && source "/home/tgrining/.bun/_bun"

# bun
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"

# AWS: default to the SSO profile (refresh with: aws sso login --profile "$AWS_PROFILE")
export AWS_PROFILE=legartis

# theme: per-mode BAT_THEME / FZF_DEFAULT_OPTS (generated by `theme`)
[ -f ~/.config/theme/env.sh ] && source ~/.config/theme/env.sh

# >>> railway initialize >>>
[ -f "$HOME/.railway/env" ] && source "$HOME/.railway/env"
# <<< railway initialize <<<
