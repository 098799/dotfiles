#!/bin/bash
# Dotfiles installation script
# Run from ~/dotfiles directory

set -e

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dotfiles from: $DOTFILES_DIR"

# Remove existing symlinks/files
echo "Removing old symlinks..."
rm -f ~/.zshrc ~/.gitconfig ~/.gitignore_global ~/.alacritty.toml
rm -f ~/scripts
rm -rf ~/.config/i3blocks ~/.config/rofi ~/.screenlayout
rm -f ~/.config/i3/config

# Create necessary directories
mkdir -p ~/.config/i3

# Create new symlinks
echo "Creating symlinks..."

# Zsh
ln -sf "$DOTFILES_DIR/zsh/.zshrc" ~/.zshrc

# Git
ln -sf "$DOTFILES_DIR/git/.gitconfig" ~/.gitconfig
ln -sf "$DOTFILES_DIR/git/.gitignore_global" ~/.gitignore_global

# Alacritty
ln -sf "$DOTFILES_DIR/alacritty-pkg/.alacritty.toml" ~/.alacritty.toml

# i3 and related
ln -sf "$DOTFILES_DIR/i3-pkg/.config/i3/config" ~/.config/i3/config
ln -sf "$DOTFILES_DIR/i3-pkg/.config/i3blocks" ~/.config/i3blocks
ln -sf "$DOTFILES_DIR/i3-pkg/.config/rofi" ~/.config/rofi
ln -sf "$DOTFILES_DIR/i3-pkg/.screenlayout" ~/.screenlayout
ln -sf "$DOTFILES_DIR/i3-pkg/scripts" ~/scripts

# Optional packages (uncomment as needed):
# ln -sf "$DOTFILES_DIR/emacs/.emacs" ~/.emacs
# ln -sf "$DOTFILES_DIR/emacs/.emacs.d" ~/.emacs.d
# ln -sf "$DOTFILES_DIR/vim/.vimrc" ~/.vimrc
# ln -sf "$DOTFILES_DIR/vim/.vim" ~/.vim
# ln -sf "$DOTFILES_DIR/bash/.bashrc" ~/.bashrc
# ln -sf "$DOTFILES_DIR/bash/.bash_aliases" ~/.bash_aliases

echo "Done! Symlinks created:"
echo ""
for link in ~/.zshrc ~/.gitconfig ~/.gitignore_global ~/.alacritty.toml ~/scripts ~/.config/i3blocks ~/.config/rofi ~/.config/i3/config ~/.screenlayout; do
    if [ -L "$link" ]; then
        echo "  $link -> $(readlink "$link")"
    fi
done
