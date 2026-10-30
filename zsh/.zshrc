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
# The omz plugin above already sourced virtualenvwrapper_lazy.sh: workon & co load
# the real thing on first use. Sourcing virtualenvwrapper.sh here too cost ~190 ms
# (it runs python hooks) on every shell.
export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3
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

# kgpw <pod-name regex> [kubectl args...]  — watch pods, filtered by name, coloured
kgpw() {
  local pat=$1; shift
  local prog='
    BEGIN { R = "\033[0m"; B = "\033[1m"; D = "\033[2m" }
    NR == 1 { printf "%s%s%s\n", "\033[1;36m", $0, R; next }
    $1 !~ pat { next }
    {
      split($2, rd, "/")
      rc = (rd[1] == rd[2]) ? "32" : "33"
      s = $3
      if (s == "Completed" || s == "Succeeded") sc = "34"
      else if (s == "Running") sc = "32"
      else if (s ~ /Pending|Creating|Init|Terminating/) sc = "33"
      else sc = "31"
      rs = ($4 + 0 > 0) ? "33" : "2"
      tail = ""
      for (i = 5; i <= NF; i++) tail = tail " " $i
      printf "%s%-55s%s %s%-7s%s %s%-24s%s %s%-10s%s%s%s\n", B, $1, R, "\033[" rc "m", $2, R, "\033[" sc "m", s, R, "\033[" rs "m", $4, R, D, substr(tail, 2), R
    }'
  KGPW_PAT=$pat KGPW_PROG=$prog KGPW_ARGS="$*" watch -c -n "${KGPW_INTERVAL:-2}" '
    out=$(kubectl get pods $KGPW_ARGS) || exit 1
    printf "%s\n" "$out" | awk -v pat="$KGPW_PAT" "$KGPW_PROG"
  '
}

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
# Kept in its own file so the niri launchers can source it without the rest
# of this file. Path through the symlink: ~/.zshrc -> dotfiles/zsh/.zshrc.
source "${${(%):-%x}:A:h}/claw.zsh"

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

# NVM — lazy. Sourcing nvm.sh costs ~0.8 s, and it used to run twice (init-nvm.sh
# sources it too): ~1.7 s of every new shell. Instead node-path.zsh puts the
# default alias's bin on PATH (node/npm/npx work at once) and nvm itself loads on
# the first `nvm`.
_nvm_load() {
    unfunction nvm _nvm_load 2>/dev/null
    source /usr/share/nvm/init-nvm.sh
}
if source "${${(%):-%x}:A:h}/node-path.zsh"; then
    nvm() { _nvm_load && nvm "$@" }
else
    _nvm_load
fi

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

#---------------------------------------------------------------------------
# cherd <app> — cherd in a p340 tailnet app repo (~/apps/REGISTRY.md)
#---------------------------------------------------------------------------
# `cherd tower` = ssh -t p340, cd ~/tower, `cherd .`. On p340 itself it runs
# here. A known app name always means p340, even where a same-named dir exists
# locally (~/apps, ~/health on p14s): write `cherd ./health` for the local one.
# `cherd p340:<dir>` opens any other dir under p340's $HOME the same way.
# Anything else (no arg, a path, `doctor`, flags) goes to plain cherd.
typeset -gA CHERD_P340_APPS=(
  apps apps  kit apps/kit
  weekends weekends  health health  pac health  cabinet cabinet  jobs jobs
  chess chess  pens pens  fidelive fidelive  fide fidelive  pokedex pokedex
  pod pod  igarchive igarchive  twitter twitter  imagine imagine
  tetrafit tetrafit  sandbox sandbox  burnlog burnlog  tower tower
  games gamr  gamr gamr  clips paperclips  paperclips paperclips
  dino dinosaurs  dinozaury dinosaurs  dinosaurs dinosaurs
  paint drawing  pixelpaint drawing  drawing drawing
  genesis generation/genesis  museum museum  insphero apps-landing-mocks
  pypen pypen  sudoku kids-sudoku
)

cherd() {
  local dir=
  if (( $# == 1 )); then
    if [[ "$1" == p340:?* ]]; then
      dir="${1#p340:}"
    else
      dir="${CHERD_P340_APPS[$1]}"
    fi
  fi
  if [[ -z "$dir" ]]; then
    command cherd "$@"
    return
  fi
  if [[ ! "$dir" =~ '^[A-Za-z0-9._/-]+$' || "$dir" == *..* ]]; then
    print -u2 -r -- "cherd: bad p340 dir: $dir"
    return 2
  fi
  if [[ "${HOST%%.*}" == p340 ]]; then
    # python3 is found BEFORE the cd: oh-my-zsh turns on a repo's .venv on cd
    # (~/pod and most app repos have one), and cherd's `env python3` would then
    # run in the app's venv, where `requests` is missing.
    local py="$(whence -p python3)" bin="$(whence -p cherd)"
    (cd "$(_claw_root)/$dir" && "$py" "$bin" .)
  else
    # -t: cherd is a TUI. Login+interactive zsh so ~/bin, env and the account
    # setup are the same as when you ssh in by hand; it calls this function
    # again on p340, which takes the branch above (no ssh loop).
    ssh -t p340 "exec zsh -lic 'cherd $1'"
  fi
}

_cherd() {
  _alternative \
    "apps:p340 app:(${(k)CHERD_P340_APPS})" \
    'dirs:local directory:_files -/'
}
compdef _cherd cherd
