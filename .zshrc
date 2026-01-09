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
source "$HOME/.local/bin/virtualenvwrapper.sh"
export PYTHONPATH="${PYTHONPATH}:$HOME/.virtualenvs:$HOME"
export VIRTUALENVWRAPPER_PYTHON=$(which python3)
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
dbus-update-activation-environment --all

# Compiler configuration
export FC="gfortran"
export CXX="g++"
export CC="gcc"

# PATH
PATH="$PATH:$HOME/bin"
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"

# Powerlevel10k theme
source /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

#---------------------------------------------------------------------------
# Legartis-specific
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

# Service directory shortcuts
alias o1="cd ~/legartis/ && cd services/backend/ontology_service/"
alias o2="cd ~/legartis2/ && cd services/backend/ontology_service/"
alias o3="cd ~/legartis3/ && cd services/backend/ontology_service/"
alias u1="cd ~/legartis/ && cd services/backend/user_service/"
alias u2="cd ~/legartis2/ && cd services/backend/user_service/"
alias u3="cd ~/legartis3/ && cd services/backend/user_service/"
alias e2e="cd ~/legartis/ && cd services/backend/e2e/e2e/"

# Django shell shortcuts
alias pshell="~/.virtualenvs/legartis/bin/python -m pythia_service.manage shell_plus"
alias pdbshell="~/.virtualenvs/legartis/bin/python -m pythia_service.manage dbshell"
alias dshell="~/.virtualenvs/legartis/bin/python -m document_service.manage shell_plus"
alias oshell="~/.virtualenvs/legartis/bin/python -m ontology_service.manage shell_plus"
alias wshell="~/.virtualenvs/legartis/bin/python -m workflow_service.manage shell_plus"
alias ushell="~/.virtualenvs/legartis/bin/python -m user_service.manage shell_plus"

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
# External tools
#---------------------------------------------------------------------------

# Haskell
[ -f "$HOME/.ghcup/env" ] && source "$HOME/.ghcup/env"

# FZF
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

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
