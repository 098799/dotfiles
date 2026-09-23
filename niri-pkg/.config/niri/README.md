# niri setup

niri is the scrolling-tiling Wayland session. It sits next to i3; lightdm
lists both. This setup copies the i3 keys and habits where niri can, and
this file says where each part lives and why the unusual parts exist.

**On screen:** `Mod+Shift+C` shows every key binding.
**After an edit:** run `niri validate`. niri reloads on save. If a file has
an error, niri refuses the whole config and keeps the last good one. You get no
popup, so an edit that "does nothing" usually has a syntax error.

## Where things are

Everything is in `~/dotfiles/niri-pkg/` and GNU Stow links it into `~`.

| Path (live) | What |
|---|---|
| `~/.config/niri/config.kdl` | Entry point: input, keyboard layouts, workspaces, overview notes. Includes the files below. |
| `~/.config/niri/layout.kdl` | Gaps, column widths, borders, tab strip, shadow. |
| `~/.config/niri/rules.kdl` | Per-app rules: which windows float, which have no border. |
| `~/.config/niri/binds.kdl` | All key bindings, grouped by topic. |
| `~/.config/niri/startup.kdl` | Programs started at login (waybar, dunst, syncthing, …). |
| `~/.config/niri/environment.kdl` | Env vars for started programs. Mostly a list of vars to remove. |
| `~/.config/waybar/` | The bar. It runs the same `~/scripts/*.sh` blocks as i3blocks. |
| `~/.config/swaylock/config` | Lock screen colours. |
| `~/bin/niri-*`, `barmenu`, `i3blocks-waybar` | Helper scripts (table below). |

`~/.config/niri` and `~/.config/waybar` link to whole directories, so a new
file there is live at once. `~/bin` has **one link per file**. After you add a
script to `niri-pkg/bin/`, run `cd ~/dotfiles && stow -R niri-pkg`, or else
the key that calls the script does nothing.

Some scripts that the config calls are **not** in this package:
`theme-restore`, `wallpaper-pick`, `neomacs-try`, `w95-sysmon`, `ftl-speed`,
`cmon` (in `bin-pkg` or plain `~/bin`), and the bar blocks in `~/scripts/`
(from `i3-pkg`).

## Keys at a glance

The grammar is the same as in i3:

| Keys | Does |
|---|---|
| `j` `k` `l` `;` | left, down, up, right (the arrow keys do the same) |
| `Mod` + direction | focus |
| `Mod+Shift` + direction | move the window or column |
| `Mod+Ctrl` + `j`/`k`/`l`/`;` | resize by 10% (add `Shift` for 2%) |
| `Mod+Ctrl` + `←`/`→` | focus the other monitor |
| `Mod` + workspace letter (`R T Y U I O P`, `G H /`, `M , .`) | go to workspace |
| `Mod+Shift` + workspace letter | send the column there |
| `Mod+Alt+Shift` + … | capture tools: screenshots, recording, autoclick |

The keys that act differently from plain niri:

| Key | Does |
|---|---|
| `Mod+J` / `Mod+;` | Left/right. In a **tabbed** column: walk the tabs first, then go to the next column. In a **stacked** column: go straight to the next column. |
| `Mod+C` / `Mod+V` | Pull the column on the right into this column, as a stack / push the bottom window out to its own column (i3 split v / split h). |
| `Mod+W` | Tabbed column on/off. |
| `Mod+E` / `Mod+Shift+E` | Step through column widths 1/3, 1/2, 2/3, full. |
| `Mod+F` / `Mod+A` | Maximize column / real fullscreen. |
| `Mod+Shift+Z` | Terminal **below** the focused window, not in a new column. |
| `Mod+Ctrl+1/2/3` | Resize the window to 50/75/90% and center it. |
| `Mod+Tab` | Overview of all workspaces. |
| `Mod+Alt+G` / `Mod+Alt+Shift+G` | Gaps off / back on. |
| `Mod+BackSpace` | Menu: screen layouts, theme, font size. |
| `Mod+[` / `Mod+]` | Volume -/+10% (i3 muscle memory). niri's own use of these keys moved to `Mod+Shift+[` / `]`. |

## Helper scripts

A niri key binding runs exactly **one** action, and it cannot decide
anything. When a key needs two actions, or a check first, it runs a script.

| Script | Started by | Does | Why a script |
|---|---|---|---|
| `niri-focus-lr` | `Mod+J`, `Mod+;`, arrows | Left/right that walks tabs only in a tabbed column. | niri has no "if tabbed" action. The script infers tabbed from tile heights, because the IPC does not report it. |
| `niri-preset-size` | `Mod+Ctrl+1/2/3` | Set width, set height, center. | Three actions. |
| `niri-spawn-below` | `Mod+Shift+Z` | Open a program under the focused window. | niri always opens a new column; the script moves the window into place after it opens. |
| `niri-gaps` | `Mod+Alt+G`, `Mod+Alt+Shift+G` | Set gaps to 0 or back. `niri-gaps get` prints the current gap. | niri has no gap action at runtime. The script rewrites the `gaps` line in `layout.kdl`, and niri reloads it. |
| `niri-auto-width` | startup | One terminal alone gets 2/3 of the width; two terminals get 1/2 each. | niri has one fixed default width. The script listens to niri events and resizes. |
| `niri-colcount` | waybar | Shows `◀2 3/7 4▶`: which column you are in, and how many are off screen. | Custom waybar module. |
| `i3blocks-waybar` | waybar | Runs an i3blocks script and converts its output for waybar. | So that the two bars share one set of scripts. |
| `barmenu` | `i3blocks-waybar` | Bar menus that open under the block you clicked and close on a click outside. | Wayland rofi cannot do either. |
| `niri-screen-switch` | `Mod+BackSpace` | The i3 `screen_switch` menu. It uses `niri msg output` in place of xrandr. | Menu. |
| `niri-record` (+ `-desktop`, `-window`, `-region`) | `Mod+Alt+Shift+L`, `;`, `R` | Start/stop screen recording with gpu-screen-recorder. Add `Ctrl` to record without audio. | ffmpeg x11grab records nothing on Wayland. |
| `niri-screenshot-clip` | `Mod+Alt+Shift+J` | Copy a screenshot of a region to the clipboard. | Two tools in a pipe. |
| `niri-autoclick` | `Mod+Alt+Shift+C` | Start/stop an autoclicker (ydotool). | xdotool cannot click on Wayland. |
| `niri-lock` | `Ctrl+Alt+L`, idle | swaylock with the current wallpaper. | Reads the wallpaper path. |
| `niri-idle` | startup | Lock after 10 min, turn the screens off 30 s later, lock before sleep. | swayidle command line. |
| `niri-wallpaper` | startup, `wallpaper-pick` | Show the wallpaper from `~/.fehbg` with swaybg. | feh cannot draw on Wayland. |

## How to change things

- **Add a key.** Put it in `binds.kdl`, in the section it belongs to. If it
  needs more than one action, write a script in `niri-pkg/bin/`, run
  `stow -R niri-pkg`, and bind `spawn "script-name"`. Keep all keys in
  `binds.kdl`. niri merges the included files, and a key bound in two files
  gives no error, but only one of the two bindings works.
- **Make an app float or change how it opens.** Add a `window-rule` in
  `rules.kdl`. To get the app-id and title, focus the window and run
  `niri msg focused-window`. The app-id is often not the X11 class.
- **Start something at login.** Add a line to `startup.kdl`. It runs at the
  next login, not on save.
- **A new terminal has a stale variable** (a wrong venv, `TMUX`, kube
  context). Add `NAME null` to `environment.kdl`.
- **Colours.** They are fixed hex values in `layout.kdl`, `swaylock/config`
  and `waybar/style.css`. The theme scripts (`dark-gruv` etc.) do not change
  them.
- **See the live state:** `niri msg windows`, `niri msg workspaces`,
  `niri msg outputs`, `niri msg -j event-stream`.
- **The niri log:** `journalctl --user -t niri`. Each reload writes a
  `loaded config` line there.

## niri limits that shaped this setup (niri 26.04)

- One action per key. That is the reason for most of the scripts.
- The IPC does not report if a column is tabbed, and it does not report a
  window's position on screen (`tile_pos_in_workspace_view` is always null).
  To record one window, use the portal picker.
- No runtime action for gaps, and no sticky windows. So the w95-sysmon
  drop-down stays on one workspace.
- Wayland app-ids are not X11 classes. A rule that matches nothing gives no
  error.
- niri runs under `systemd --user` and inherits its environment. This is why
  `environment.kdl` exists.
- Screen sharing goes through xdg-desktop-portal. A portal left over from an
  i3 session has no screen-cast support. `startup.kdl` restarts it.

## Not ported from i3

- **espanso and autokey do not work here.** The installed espanso build is
  `espanso-x11-bin`, which sees only Xwayland windows. Text expansion does
  not work in Alacritty or in any Wayland window, and you get no error. The
  fix is the separate `espanso-wayland` package (AUR).
- `Mod+Shift+V` "restart i3": niri has nothing to restart. `Mod+Shift+X`
  quits the session (it asks first).
- picom: niri draws the corners and shadows itself (`layout.kdl`, `rules.kdl`).
- volumeicon and i3blocks signals: waybar follows PulseAudio itself, so the
  volume keys do not need to signal the bar.
- xbacklight: the brightness keys use brightnessctl.
- Resize one edge only (i3 resize mode `h`/`n`/`u`/`m`): niri resizes around
  the center and has no action for one edge.
- `Mod+Shift+B` "move to previous workspace": niri does not have it. The
  key moves the column one workspace down.
- Windows 95 mode (`w95-autobar`, the i3-95 chrome): i3 only.
