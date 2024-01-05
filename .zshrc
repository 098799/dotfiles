[[ $TERM == "dumb" ]] && unsetopt zle && PS1='$ ' && return

# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

if [[ "$TERM" == "dumb" ]]
then
    unsetopt zle
    unsetopt prompt_cr
    unsetopt prompt_subst
    unfunction precmd
    unfunction preexec
    PS1='$ '
fi

# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:/usr/local/bin:$PATH

# Path to your oh-my-zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set name of the theme to load. Optionally, if you set this to "random"
# it'll load a random theme each time that oh-my-zsh is loaded.
# See https://github.com/robbyrussell/oh-my-zsh/wiki/Themes
# ZSH_THEME="robbyrussell"
# ZSH_THEME="mod-agnoster"
# ZSH_THEME="powerlevel9k/powerlevel9k"
# POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(ssh root_indicator background_jobs virtualenv context dir vcs)
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(ssh root_indicator background_jobs virtualenv vcs dir)
# POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(status time battery)
POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=()
# POWERLEVEL9K_BATTERY_STAGES=($'\u2581' $'\u2582' $'\u2583' $'\u2584' $'\u2585' $'\u2586' $'\u2587' $'\u2588')
# POWERLEVEL9K_PROMPT_ON_NEWLINE=true
POWERLEVEL9K_PROMPT_ON_NEWLINE=false
# POWERLEVEL9K_TIME_FORMAT='%D{%H:%M}'

export WORKON_HOME="$HOME/.virtualenvs"
DISABLE_UPDATE_PROMPT=true

# Set list of themes to load
# Setting this variable when ZSH_THEME=random
# cause zsh load theme from this variable instead of
# looking in ~/.oh-my-zsh/themes/
# An empty array have no effect
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion. Case
# sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment the following line to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment the following line to change how often to auto-update (in days).
# export UPDATE_ZSH_DAYS=13

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# The optional three formats: "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load? (plugins can be found in ~/.oh-my-zsh/plugins/*)
# Custom plugins may be added to ~/.oh-my-zsh/custom/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(
  command-not-found
  fast-syntax-highlighting
  git
  # helm
  pip
  python
  sudo
  virtualenvwrapper
  colorize
  rsync
  z
)

source $ZSH/oh-my-zsh.sh

source ~/Programs/z/z.sh

zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path ~/.zsh/cache

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='mvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch x86_64"

# ssh
# export SSH_KEY_PATH="~/.ssh/rsa_id"

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within the ZSH_CUSTOM folder.
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"

# [ -f /etc/profile.d/vte-2.91.sh ] && source /etc/profile.d/vte-2.91.sh
source /etc/profile.d/vte.sh

alias watch="watch "

source /home/tgrining/.local/bin/virtualenvwrapper.sh
export PYTHONPATH="${PYTHONPATH}:$HOME/.virtualenvs"  # sure this won't impact performance of lsp?
export PYTHONPATH="${PYTHONPATH}:$HOME"
export VIRTUALENVWRAPPER_PYTHON=`which python3`
export VIRTUAL_ENV_DISABLE_PROMPT=1 #not needed anymore with agnoster

alias cd..='cd ..'
#LC_NUMERIC="en_US.UTF-8"
alias p3='ipython'
alias mdview='google-chrome-stable'
alias e="emacsclient -t"
alias ee="emacsclient -c"
export EDITOR="emacsclient -c"
export VISUAL="emacsclient -c"
# alias cal='ncal -C'
alias cal='cal -m'
alias sl='ls' #no trains for me
alias LS='ls'
alias pyt='pytest -nauto -sxk ""'
# alias mkvirtualenv='mkvirtualenv --python=/usr/bin/python3 -a `pwd` `pwd | rev | cut -f 1 -d "/" | rev`'
alias rmvirtualenv='deactivate && rmvirtualenv `pwd | rev | cut -f 1 -d "/" | rev`'
alias refvirtualenv='rmvirtualenv && mkvirtualenv'
alias ll='ls -alh'
alias vi='vim'
alias supen='cd ~/pypen && cd dpypen && workon pypen && supen'
alias suink='cd ~/pypen && cd dpypen && workon pypen && suink'
# alias sppen='cd ~/pypen && cd pypen && ~/.virtualenvs/pypen/bin/python ~/pypen/pypen/pypen.py sp'
# alias siink='cd ~/pypen && cd pypen && ~/.virtualenvs/pypen/bin/python ~/pypen/pypen/pypen.py si'
# alias lpen='cd ~/pypen && cd pypen && ~/.virtualenvs/pypen/bin/python ~/pypen/pypen/pypen.py lp'
# alias link='cd ~/pypen && cd pypen && ~/.virtualenvs/pypen/bin/python ~/pypen/pypen/pypen.py li'
alias ranger='ranger --choosedir=/tmp/.rangerdir; LASTDIR=`cat /tmp/.rangerdir`; cd "$LASTDIR"'
alias py3clean='find . -name \*.pyc -delete'
export PYTHONBREAKPOINT=ipdb.set_trace

export PATH_TO_HTML=/tmp

cd `pwd`

dbus-update-activation-environment --all

export FC="gfortran"
export CXX="g++"
export CC="gcc"

PATH="$PATH:/home/tgrining/bin"
# source /home/tgrining/.oh-my-zsh/custom/themes/powerlevel10k/powerlevel10k.zsh-theme

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh



###################
# Legartis-specific
###################

alias k='kubectl'
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"

alias ap='ansible-playbook'

alias kg="k get"
alias kgp="k get pods"
alias kgpi="k get pods -n inference-models"
alias kgpl="k get pods -n legartis-prod"
alias kgna="k get namespaces"
alias kgno="k get nodes"

alias knsl="kubie ns legartis-prod"
alias knsi="kubie ns inference-models"

alias kd="k describe"
alias kdp="k describe pod"
alias kdna="k describe namespaces"
alias kdno="k describe nodes"

alias document="cd ~/legartis/ && cd services/backend/document_service/document_service/"
alias workflow="cd ~/legartis/ && cd services/backend/workflow_service/workflow_service/"
alias ontology="cd ~/legartis/ && cd services/backend/ontology_service/ontology_service/"
alias e2e="cd ~/legartis/ && cd services/backend/e2e/e2e/"
alias pythia="cd ~/legartis/ && cd services/backend/pythia_service/pythia_service/"
alias annotation="cd ~/legartis/ && cd services/backend/annotation_service/annotation_service/"
alias user="cd ~/legartis/ && cd services/backend/user_service/user_service/"
alias cdpt="cd ~/legartis/ && cd services/backend/pythia_service/pythia_service/provision_classification/"
alias cdpd="cd ~/legartis/ && cd services/backend/pythia_service/pythia_service/document/"

alias pshell="~/.virtualenvs/legartis/bin/python -m pythia_service.manage shell_plus"
alias pdbshell="~/.virtualenvs/legartis/bin/python -m pythia_service.manage dbshell"
alias dshell="~/.virtualenvs/legartis/bin/python -m document_service.manage shell_plus"
alias oshell="~/.virtualenvs/legartis/bin/python -m ontology_service.manage shell_plus"
alias wshell="~/.virtualenvs/legartis/bin/python -m workflow_service.manage shell_plus"
alias ushell="~/.virtualenvs/legartis/bin/python -m user_service.manage shell_plus"

function ke() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    service=$(echo $service_pod | cut -f "1" -d "-")
    k exec $service_pod --stdin --tty -- python -m "$service"_service.manage shell_plus
}

function kep() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    k exec $service_pod --stdin --tty -- /bin/bash
}

# function migrate_openshift_all() {
#     project=$(oc project | cut -d " " -f "3")
#     read "?You are currently on the $project project, are you sure you want to apply migrations there? [y/n] " response
#     if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]];
#     then
#         for service in annotation document ml ontology pythia user workflow
#         do
#             migrate_openshift $service
#         done
#     else
#         echo "Aborted!"
#     fi
# }

# function migrate_openshift() {
#     service_pod=$(kgp | cut -f "1" -d " " | grep $1 | tail -1)
#     service=$(echo $service_pod | cut -f "1" -d "-")
#     k exec $service_pod --stdin --tty -- python -m "$service"_service.manage migrate
#     k exec $service_pod --stdin --tty -- python -m "$service"_service.manage sync_oidc
# }

function klp() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl logs $service_pod
}

function klr() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl logs $service_pod | log_reader
}

function kl() {
    kubectl logs $@
}

function klf() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | head "-$2" | tail -1)
    kubectl logs -f $service_pod ${@:3}  # all argument except the first two
}

function kli() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | tail -1)
    kubectl logs $service_pod ${@:3} -c init  # all argument except the first two
}

function klif() {
    service_pod=$(kgp | cut -f "1" -d " " | grep $1 | tail -1)
    kubectl logs -f $service_pod ${@:3} -c init  # all argument except the first two
}

function kepc() {
        k exec $1 --stdin --tty -c $2 -- /bin/bash
}

function kepshc() {
    k exec $1 --stdin --tty -c $2 -- /bin/sh
}

function kepsh() {
    k exec $1 --stdin --tty -- /bin/sh
}

function dl() {
    docker logs $1 -f
}

function de() {
    docker exec -it $1 bash
}

source /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme

ANSIBLE_COW_SELECTION=random

[ -f "/home/tgrining/.ghcup/env" ] && source "/home/tgrining/.ghcup/env" # ghcup-env

[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

export PYTHONSTARTUP="/home/tgrining/dotfiles/pythonstartup.py"
