#!/bin/bash
# Dotfiles installation script using GNU Stow
#
# NEW MACHINE SETUP:
# 1. Install dependencies:
#      sudo pacman -S stow git zsh alacritty i3 rofi
#
# 2. Clone dotfiles:
#      git clone <your-repo-url> ~/dotfiles
#
# 3. Run this script:
#      cd ~/dotfiles && ./install.sh
#
# 4. Optional: Install oh-my-zsh, powerlevel10k, etc.

set -e

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DOTFILES_DIR"

echo "Installing dotfiles from: $DOTFILES_DIR"

# Check for stow
if ! command -v stow &> /dev/null; then
    echo "Error: stow not installed. Run: sudo pacman -S stow"
    exit 1
fi

# Remove conflicting files/symlinks that would block stow
echo "Cleaning up existing files..."
rm -f ~/.zshrc ~/.gitconfig ~/.gitignore_global ~/.config/alacritty/alacritty.toml
rm -f ~/scripts ~/.screenlayout
rm -f ~/.config/i3/config
rm -rf ~/.config/i3blocks ~/.config/rofi

# Create necessary directories
mkdir -p ~/.config/i3

# Core packages (always install)
echo "Stowing core packages..."
stow -v -t ~ zsh git alacritty-pkg i3-pkg bin-pkg

# Seed the i3 active palette symlink if it's missing — i3's `include` silently
# no-ops on a missing file, which would drop the bar{} block and client.*
# colors. The `theme` script overwrites this symlink on demand.
if [[ ! -e ~/.config/i3/active-palette.conf ]]; then
    ln -sf colors.d/gruvbox-dark.conf ~/.config/i3/active-palette.conf
fi

# Seed alacritty runtime overlays — the stowed alacritty.toml imports them via
# general.import. Missing imports log errors and leave fallbacks active, so seed
# defaults to keep things quiet. Theme + {big,middle,small,huge}-font rewrite these.
if [[ ! -e ~/.config/alacritty/active-palette.toml ]]; then
    uv run alacritty/combiner.py dark gruvbox
fi
if [[ ! -e ~/.config/alacritty/active-font.toml ]]; then
    printf '[font]\nsize = 16\n' > ~/.config/alacritty/active-font.toml
fi
# The face override, owned by `w95 on`/`off`. Seeded empty: an import alacritty
# cannot read is a startup error, and the default state is "no override".
if [[ ! -e ~/.config/alacritty/active-fontface.toml ]]; then
    printf '# no face override; alacritty.toml decides\n' \
        > ~/.config/alacritty/active-fontface.toml
fi

# Windows 95 desktop. Re-stowed unconditionally when it is already installed:
# every new palette, chrome file or w95-* script this package grows needs a fresh
# symlink, and a host stowed before that commit keeps working *except* for the one
# missing file -- `theme light win95` then dies half way through and leaves Win95
# colours under stock i3. `--no-folding` because .config/i3 is a shared directory.
if [[ -e ~/.local/bin/w95 ]]; then
    echo "Re-stowing win95-pkg..."
    stow -v -t ~ --no-folding win95-pkg
    # w95-switch only ever repoints this symlink, it never creates it, and i3's
    # `include` no-ops silently on a missing file. Seed it like active-palette.conf.
    if [[ ! -e ~/.config/i3/active-keys.conf ]]; then
        ln -sfn no-keys.conf ~/.config/i3/active-keys.conf
    fi
fi

# Optional packages (uncomment as needed)
# stow -v -t ~ emacs
# stow -v -t ~ vim
# stow -v -t ~ bash
# stow -v -t ~ espanso-pkg
# stow -v -t ~ logid-pkg

echo ""
echo "Done! Installed packages:"
echo "  - zsh        : ~/.zshrc"
echo "  - git        : ~/.gitconfig, ~/.gitignore_global"
echo "  - alacritty  : ~/.config/alacritty/alacritty.toml"
echo "  - i3         : ~/.config/i3/, i3blocks, rofi, scripts, screenlayout"
echo "  - bin        : ~/bin/ (theme scripts, utilities)"
echo ""
echo "Optional packages (install manually):"
echo "  - espanso    : stow -t ~ espanso-pkg"
echo "  - logid      : stow -t ~ logid-pkg"
echo "  - emacs      : stow -t ~ emacs"
echo "  - vim        : stow -t ~ vim"
echo ""
echo "To add more packages:  stow -t ~ <package>"
echo "To remove a package:   stow -D -t ~ <package>"
