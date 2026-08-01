# win95-pkg — a Windows 95 desktop for i3

A stow package. `stow -t ~ win95-pkg` from `~/dotfiles`.

## Daily use

    w95-switch on       # Windows 95
    w95-switch off      # back to normal
    w95-switch toggle
    w95-switch status
    w95-rofi            # the same, from a rofi menu

Switching is a live `i3-msg restart`: windows, workspaces and layout all
survive it. There is no X restart and no logout.

**One-time setup:** log out and pick **"i3 (Win95-switchable)"** at the
LightDM greeter. That session runs `i3-session`, which is what makes the live
switch possible — i3 restarts by re-execing `start_argv[0]`, so putting a
chooser there lets a restart land on a different window manager binary. In a
plain `i3` session `w95-switch` refuses to do anything and tells you so.

## What it touches

| Thing | Where | Switched by |
|---|---|---|
| Window manager | `~/.local/bin/i3-95` (built by `w95 wm install`) | `~/.config/w95/wm` |
| i3 palette | `~/.config/i3/active-palette.conf` | `w95 on` / `off` |
| Window chrome (borders, title font) | `~/.config/i3/active-chrome.conf` | `w95 on` / `off` |
| Keybindings | `~/.config/i3/active-keys.conf` | `w95-switch` |
| GTK theme, icons, cursors | `~/.config/gtk-3.0/settings.ini` | `w95 on` / `off` |
| Terminal palette | `~/.config/alacritty/active-palette.toml` | `w95 on` / `off` |
| Taskbar + wallpaper | `w95bar`, `xsetroot` | `w95-autobar` (exec_always) |

Everything is user-local except one root-owned **copy** in `/usr/share/xsessions`
(LightDM ignores `~/.local/share/xsessions`):

```sh
sudo install -m 644 -o root -g root \
  ~/dotfiles/win95-pkg/.local/share/xsessions/i3-w95.desktop \
  /usr/share/xsessions/i3-w95.desktop
```

It must be a copy, not a symlink, and it must not carry a `TryExec=` line.
`$HOME` is mode `0700`, so the greeter (running as user `lightdm`) can neither
read a symlink target under `~` nor stat a `TryExec` binary there — and a
`TryExec` that cannot be resolved makes the greeter **silently hide** the
session entry. `Exec=` is fine pointing into `~`, because it only runs after
login, as the user. Re-run the `install` above after changing the desktop file.

### Window titles

i3-95 paints its caption and `[_][□][X]` buttons *into the decoration i3
already draws*, so with `default_border pixel N` there is no title bar
anywhere — you cannot tell which window has focus. `chrome.d/win95.conf`
therefore sets `border normal`, and `~/.config/i3/config` includes
`active-chrome.conf` **as its last line**, because an include can only win by
coming after the `default_border` it is overriding. `default_border` applies
only to new windows, so both chrome files also carry a
`for_window [class=".*"] border …` rule and `w95 on`/`off` issue the matching
`i3-msg` to reborder what is already on screen.

### Sizing

Win95 shipped for 640×480; on a 1440p panel a period-accurate 28px taskbar is
a hairline. One number in `~/.config/w95/settings` drives the bar, its fonts,
its icons and the Start-menu text:

```ini
bar_height = 38     # px; font_size and icon sizes derive from it
font_size  = 15     # px; optional override
```

`w95conf.py` reads it, `w95bar` layers the derived sizes over `w95.css` in a
second CSS provider, so the stylesheet itself stays free of templating.
Restart the bar (`w95-restart-bar`) to pick up a change.

### Terminal

`.config/alacritty/win95.toml` is the sixteen VGA text-mode attributes as
Windows 95 set them — silver (`#c0c0c0`) on black, olive "yellow", teal cyan,
white-on-navy selection. `w95 on` copies it over
`~/.config/alacritty/active-palette.toml` (backing up the old one to
`~/.local/state/w95/`) and `live_config_reload` repaints open terminals
immediately. Note that `theme <light|dark> <palette>` *generates* that same
file, so running `theme` while in Win95 mode ends the terminal half of it.

## Start menu

Submenus are `Flyout` windows opened beside the row that owns them, after a
220ms hover (or immediately on click). They deliberately take **no grab of
their own**: the Start menu holds one seat grab with `owner_events=True`, so
pointer events over a flyout still reach it (same application) while a click
anywhere outside lands on the parent and tears the whole stack down. Two
competing grabs is what made the old Programs window open detached, at the
top-left of the screen, with its parent already dismissed.

Rows that fly out: Programs (every `.desktop` on the box, scrolling),
Documents (home dirs + `RecentManager`), Settings (only the control panels
that are actually installed, via `shutil.which`), Find (rofi modes).

## Safety

The failure mode that matters is "the patched WM does not start and I have no
desktop". Three things prevent it:

* `i3-session` **supervises** the window manager. If it exits non-zero the
  state flips back to stock, the Win95 shell is torn down and stock i3 is
  started in the same X session — you get a working desktop, not the greeter,
  and not a login loop.
* `w95-switch on` **preflights** before changing anything: the binary must
  exist, the session must be the switchable one, and the i3 config must parse
  under `i3-95` *with the Win95 keybindings already linked in*. i3 treats a
  duplicate keybinding as a fatal config error, so this is the check that
  matters. On failure nothing is changed.
* You can always drop to a stock session from the greeter — the plain "i3"
  entry is untouched, and it ignores `~/.config/w95/wm` entirely.

## Keybindings

`win95-keys.conf` is deliberately small. On this machine `$mod` is Mod4 and
almost every `$mod+<letter>` is already bound, so the file only claims chords
that are provably free. Win+E, Win+R and Win+M collide with existing bindings
and are parked, commented out, at the bottom of that file. Their commands are
still reachable from the Start menu.

## Testing without risking the session

`~/w95-lab/vm/vm.sh` boots a headless Arch VM (KVM, ssh on 2295) with this
package 9p-mounted read-only, and screenshots the framebuffer through the
QEMU monitor. Everything above — the live switch, the crash fallback, the
preflight refusal — was verified there first.

    ~/w95-lab/vm/vm.sh up
    ~/w95-lab/vm/vm.sh ssh
    ~/w95-lab/vm/vm.sh shot /tmp/x.ppm   # PPM; pipe through `magick`
    ~/w95-lab/vm/vm.sh down
