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
rm -f ~/.zshrc ~/.gitconfig ~/.gitignore_global ~/.alacritty.toml
rm -f ~/scripts ~/.screenlayout
rm -f ~/.config/i3/config
rm -rf ~/.config/i3blocks ~/.config/rofi

# Remove i3 helper files if they exist (stow will recreate as symlinks)
rm -f ~/.config/i3/{CURRENT_MONITOR,alternating_layouts.py,create_config.sh,layout.sh} 2>/dev/null || true

# Create necessary directories
mkdir -p ~/.config/i3

# Core packages (always install)
echo "Stowing core packages..."
stow -v -t ~ zsh git alacritty-pkg i3-pkg

# Optional packages (uncomment as needed)
# stow -v -t ~ emacs
# stow -v -t ~ vim
# stow -v -t ~ bash
# stow -v -t ~ bin-pkg   # Note: may conflict with existing ~/bin

echo ""
echo "Done! Installed packages:"
echo "  - zsh        : ~/.zshrc"
echo "  - git        : ~/.gitconfig, ~/.gitignore_global"
echo "  - alacritty  : ~/.alacritty.toml"
echo "  - i3         : ~/.config/i3/, i3blocks, rofi, scripts, screenlayout"
echo ""
echo "To add more packages:  stow -t ~ <package>"
echo "To remove a package:   stow -D -t ~ <package>"
