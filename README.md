# Dotfiles

Personal dotfiles managed with [GNU Stow](https://www.gnu.org/software/stow/).

## Packages

| Package | Contents |
|---------|----------|
| `zsh` | `.zshrc` |
| `git` | `.gitconfig`, `.gitignore_global` |
| `alacritty-pkg` | `.alacritty.toml` |
| `i3-pkg` | i3 config, i3blocks, rofi, screenlayout, scripts |
| `emacs` | `.emacs`, `.emacs.d/` |
| `vim` | `.vimrc`, `.vim/` |
| `bash` | `.bashrc`, `.bash_aliases` |
| `bin-pkg` | `~/bin/` helper scripts |

## New Machine Setup

```bash
# 1. Install dependencies (Arch/Manjaro)
sudo pacman -S stow git zsh alacritty i3 rofi

# 2. Clone the repo
git clone git@github.com:098799/dotfiles.git ~/dotfiles

# 3. Run the install script
cd ~/dotfiles && ./install.sh

# 4. Install oh-my-zsh
sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

# 5. Install powerlevel10k
git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/themes/powerlevel10k

# 6. Install fast-syntax-highlighting
git clone https://github.com/zdharma-continuum/fast-syntax-highlighting.git ${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/fast-syntax-highlighting
```

## Stow Usage

```bash
# Install a package (creates symlinks in ~)
stow -t ~ <package>

# Remove a package
stow -D -t ~ <package>

# Dry run (see what would happen)
stow -n -v -t ~ <package>

# Reinstall all core packages
stow -t ~ zsh git alacritty-pkg i3-pkg
```

## Structure

```
~/dotfiles/
├── zsh/
│   └── .zshrc
├── git/
│   ├── .gitconfig
│   └── .gitignore_global
├── alacritty-pkg/
│   └── .alacritty.toml
├── i3-pkg/
│   ├── .config/
│   │   ├── i3/
│   │   ├── i3blocks/
│   │   └── rofi/
│   ├── .screenlayout/
│   └── scripts/
├── emacs/
├── vim/
├── bash/
├── bin-pkg/
└── install.sh
```

## Syncing Between Machines

Dotfiles sync via Syncthing. After sync, run on the receiving machine:

```bash
cd ~/dotfiles && ./install.sh
```
