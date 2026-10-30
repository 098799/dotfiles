# node-path.zsh — put nvm's default node on PATH without loading nvm (~0.8 s).
# Sourced by ~/.zshrc (which then makes `nvm` itself lazy) and by ~/bin/claw-fast.
# Returns 1 when the default alias does not name one installed version
# (lts/*, node, …): the caller must then load nvm the old way.
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
() {
    local def
    local -a ver
    def="$(<"$NVM_DIR/alias/default")" 2>/dev/null || return 1
    ver=("$NVM_DIR"/versions/node/v${def#v}(/N) "$NVM_DIR"/versions/node/v${def#v}.*(/nOn[1]N))
    (( $#ver )) || return 1
    path=("${ver[1]}/bin" ${path:#$NVM_DIR/versions/node/*})
}
