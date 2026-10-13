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
| `~/.config/niri/startup.kdl` | Programs started at login (waybar after `bardeck css`, dunst, syncthing, …). |
| `~/.config/niri/environment.kdl` | Env vars for started programs. Mostly a list of vars to remove. |
| `~/.config/waybar/` | The bar: floating pills on a transparent bar, almost all drawn by **bardeck** (see [The bar](#the-bar-bardeck)). `config.jsonc` has the two bars (the laptop's eDP-1 takes the compact pills), `modules.jsonc` the modules, `style.css` the native pill (the tray), `bardeck/` the engine, `bar-strip.c` its waybar module. Font = the terminal font (UbuntuMono 12). |
| `~/.config/hypr/hyprlock.conf` | Lock screen: look, and the fingerprint + password setup. |
| `pam.d/hyprlock-password` | The lock screen's password-only PAM file. It is **not** stowed: install it with `sudo cp pam.d/hyprlock-password /etc/pam.d/`. `install.sh` warns when the copy in `/etc` differs. |
| `~/.config/swaylock/config` | Colours for swaylock, the old locker. Only a fallback now. |
| `~/.config/xdg-desktop-portal/niri-portals.conf` | Portal backends. It sends the file picker (Chrome's Upload, Save as) to the GTK picker, not Nautilus. |
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
| `Mod+C` / `Mod+V` | Pull the column on the right into this column, as a stack / push the bottom window out to its own column (i3 split v / split h). On the **rightmost** column, `Mod+C` arms a hot bottom instead (as in i3): the next window you open while that window has focus goes below it, in the same column. The new window is armed too, so the column stays hot. While the focused window is armed, a 4 px line in i3's split indicator colour (`#b16286`) shows under its bottom border. `Mod+V` disarms the focused window. |
| `Mod+W` | Tabbed column on/off. |
| `Mod+E` / `Mod+Shift+E` | Step through column widths 1/3, 1/2, 2/3, full. |
| `Mod+F` / `Mod+A` | Maximize column / real fullscreen. `Mod+A` keeps the column: a window from a stack goes back to its place and height. |
| `Mod+Shift+Z` | Terminal **below** the focused window, not in a new column. |
| `Mod+Ctrl+1/2/3` | Resize the window to 50/75/90% and center it. |
| `Mod+Tab` | Overview of all workspaces. |
| `Mod+Shift+C` | All keys, fullscreen, in columns. Type to filter, `Esc` closes. niri's own overlay is on `Mod+Ctrl+Shift+C`. |
| `Mod+Alt+G` / `Mod+Alt+Shift+G` | Gaps off / back on. |
| `Mod+BackSpace` | Menu: screen layouts, theme, font size. |
| `Mod+[` / `Mod+]` | Volume -/+10% (i3 muscle memory). niri's own use of these keys moved to `Mod+Shift+[` / `]`. |

## Helper scripts

A niri key binding runs exactly **one** action, and it cannot decide
anything. When a key needs two actions, or a check first, it runs a script.

| Script | Started by | Does | Why a script |
|---|---|---|---|
| `niri-focus-lr` | `Mod+J`, `Mod+;`, arrows | Left/right that walks tabs only in a tabbed column. | niri has no "if tabbed" action. The script infers tabbed from tile heights, because the IPC does not report it. |
| `niri-zoom` | `Mod+A` | Fullscreen on/off. On the way out, the window goes back into its old column, at its old place, with the old heights. | niri's fullscreen expels a window from a stacked column and does not put it back. The script saves the column first. The IPC has no fullscreen flag: a fullscreen window's size is the output size. niri keeps one fixed height per column, so the heights are set in 4 passes to land on the exact pixels. |
| `niri-preset-size` | `Mod+Ctrl+1/2/3` | Set width, set height, center. | Three actions. |
| `niri-spawn-below` | `Mod+Shift+Z` | Open a program under the focused window. | niri always opens a new column; the script moves the window into place after it opens. |
| `niri-hot-bottom` | `Mod+C`, `Mod+V`, startup (`daemon`) | `split-v`: consume, or on the rightmost column mark the window. `split-h`: expel and unmark. `daemon`: when a window opens while a marked window has focus, move it to the bottom of that window's column, mark it, and put the column width back. Marks are window ids in `$XDG_RUNTIME_DIR/niri-hot-bottom`. The indicator: it writes a window rule to `/run/user/1000/niri-hot-bottom.kdl` (empty when off), which `config.kdl` includes, and niri reloads it. | niri has no "open the next window below" state. The check needs the column count, and the move must wait for the window to open. `niri-spawn-below` skips a marked window, so the two scripts do not both move the same window. |
| `niri-gaps` | `Mod+Alt+G`, `Mod+Alt+Shift+G` | Set gaps to 0 or back. `niri-gaps get` prints the current gap. | niri has no gap action at runtime. The script rewrites the `gaps` line in `layout.kdl`, and niri reloads it. |
| `niri-auto-width` | startup | One terminal alone gets 2/3 of the width; two terminals get 1/2 each. | niri has one fixed default width. The script listens to niri events and resizes. |
| `niri-minimap` | startup | When you switch workspace, it shows that workspace's whole row of columns for about 4 s, scaled down in the bottom-right corner (at most 40% of the screen width): windows at their true widths with icon and title, a frame for the part on screen (the rest dimmed), `◀ 2   1 ▶` for the columns off screen. Nothing else brings it up; while it is up, a scroll slides the frame. A click on the card dismisses it at once; clicks elsewhere, and on the card while it fades out, go through. `niri-minimap --show` shows it now; `--png FILE [WORKSPACE]` draws it to a file. | niri has no minimap. The IPC gives no view position, so the script replays niri's `center-focused-column "never"` rule to place the frame. After a touchpad swipe or a mouse drag of the view, the frame can be off until niri next scrolls to a column. |
| `niri-keys` | `Mod+Shift+C` | Shows every bind of `binds.kdl` in a fullscreen rofi: 3 columns (4 on a screen 2000+ px wide), the `// ---- name ----` comments as headers, keys with the same action on one row, and the touchpad/mouse gestures at the end. The label is the bind's `hotkey-overlay-title`, or the action when there is none. | niri's overlay is one column and cannot scroll, so on the laptop screen the bottom is cut off. |
| `niri-colcount` | nothing (since bardeck) | Shows `◀2 3/7 4▶`: which column you are in, and how many are off screen. | Was a custom waybar module; the workspace strip's column marks took its place. |
| `bardeck` | waybar (`custom/bardeck`) | The bar's engine: draws every strip, holds every panel. See [The bar](#the-bar-bardeck). | waybar has no hover action and a script per block cost a core's share; one daemon does it all. |
| `i3blocks-waybar` | right clicks on the bar | Runs an i3blocks script and converts its output for waybar. One run serves both bars (2 s shared answer, a lock per script), at `nice 10`; a timeout kills the script's whole process group and shows the last answer. The bt blocks share one `bluetoothctl` query too (`~/scripts/bt-state.sh`, 3 s). | So that the two bars share one set of scripts. The sharing and the nice exist because the blocks cost ~70% of a core on a loaded box (7 Oct 2026); now ~15%. |
| `barmenu` | `i3blocks-waybar` | Bar menus that open under the block you clicked and close on a click outside. | Wayland rofi cannot do either. |
| `niri-screen-switch` | `Mod+BackSpace` | The i3 `screen_switch` menu. It uses `niri msg output` in place of xrandr. `niri-screen-switch "<entry>"` runs one entry without the menu (the bar's displays panel does that), `--list` prints them. | Menu. |
| `niri-record` (+ `-desktop`, `-window`, `-region`) | `Mod+Alt+Shift+L`, `;`, `R` | Start/stop screen recording with gpu-screen-recorder. Add `Ctrl` to record without audio. | ffmpeg x11grab records nothing on Wayland. |
| `niri-screenshot-clip` | `Mod+Alt+Shift+J` | Copy a screenshot of a region to the clipboard. | Two tools in a pipe. |
| `niri-autoclick` | `Mod+Alt+Shift+C` | Start/stop an autoclicker (ydotool). | xdotool cannot click on Wayland. |
| `niri-lock` | `Ctrl+Alt+L`, idle | hyprlock with the current wallpaper. A finger **or** the password unlocks. Returns only when the screen is locked. | Reads the wallpaper path, and waits for the lock so that `before-sleep` does not suspend an open desktop. |
| `niri-idle` | startup | Lock after 10 min, turn the screens off 30 s later, lock before sleep. | swayidle command line. |
| `niri-wallpaper` | startup, `wallpaper-pick`, bardeck (a screen came) | Show the wallpaper from `~/.fehbg` with swaybg, with a **frosted band** behind the bar: the top ~40 px blurred and tinted toward the theme background, fading into the image. One picture per output at its exact size, cached in `~/.cache/niri-wallpaper`; `--plain` without the band. | feh cannot draw on Wayland, and niri 26.04 cannot blur behind a layer surface; the bar never moves, so the blur is baked in. The theme comes from the file name: `theme` writes its state only after the wallpaper. |

## The bar (bardeck)

```
[workspaces + what is open][claude quota]        [agents][system][network][devices][audio][power][displays][tray][notifications][clock]
```

Each pill but the tray is a **strip**: a picture drawn by `bardeck`
(`~/bin/bardeck`, code in `~/.config/waybar/bardeck/`) and shown by
`bar-strip.so`, a waybar CFFI module (`bar-strip.c`). **Hover** a strip and its
**panel** opens under it; it closes when the pointer leaves the strip and the
panel. **Click** pins it (Esc, a click outside or a second click closes it).
Right and middle clicks are waybar's own (`modules.jsonc`); the right ones keep the
i3blocks scripts' menus.

| Strip | On the bar | Panel |
|---|---|---|
| workspaces | Each workspace with windows: its name, and for the visible one a mark per column, in column order: the app's icon, or for a terminal the first letters of its title. The focused column is underlined. Other workspaces show marks too while the pill stays under its width budget (`ws.BUDGET`). Click a name: that workspace; click a mark: that window; scroll: the next one. **Right click: the overview** (no hover panel). | **The overview** (`ws.WsPanel`, right click; another right click, Esc or a click outside closes it): every workspace of every output, each a card with its windows as rows in niri's column order (app icon, title, app; marks for floating, fullscreen, urgent; the focused one tinted), the empty named workspaces as chips. Click a window: focus it; hover it: move it to the workspace above / below, or close it (click twice); click a card's name or an empty chip: go there. An output with many cards takes two or three columns. It reads the strip's niri state: no reads of its own. Pinned: `i`/`o` a window, `k`/`l` a quarter of the list, `j`/`;` the previous / next workspace, Enter focus (and close the overview), `x` close (twice). |
| quota | **Folded** (13 Oct 2026: six full cells took 636 px and pushed the clock off the screen): the active account's thumbnail of qtop's week chart, its 5h window as a tank and its weekly %; every other account one thin gauge after it (the weekly % as the fill, in the verdict's colour; a dim stub when it has no fresh reading). See `bardeck/quota.py`. | Every account's week at full size, its 5h peaks, the pool totals. Pinned: `u`/`p` earlier/later week, `i`/`o` select, Enter: `qtop <account>`. |
| agents | A robot (filled while one works) and how many agents work; an amber badge with the ones that wait for Tomek (a permission dialog or a question on screen; red: stuck on a rate limit or an error); a red dot on the robot when the head pipeline of one of his open MRs failed. Right: cmon. | cmon's board, drawn (`bardeck/agents.py`): **agents**, waiting first (tmux session, ticket and title, state and for how long, slot or worktree; the picked one's last words under the list); click: a terminal attached to its tmux session, as cmon's `A` does. **Queue**: slotq's jobs (`~/.legartis/slotq/state.json`), Enter: the job's MR. **Merge requests**: Tomek's open MRs with pipeline, threads, approved, conflict, draft; click: the browser. Pinned: `i`/`o` select, `k`/`l` half a section, `j`/`;` previous / next section, Enter attach / open, `r` ask rcmon now, `c` cmon. |
| system | A CPU graph of the last 40 s and %, memory (with swap under it), CPU temperature (k10temp). A disk badge at 85% full, an update count when there are updates. | 5 min of CPU, memory, swap, temperature; every core; **the busiest processes** by CPU and by memory, one row per process (`bardeck/procs.py`): hover a row for term (SIGTERM), kill (SIGKILL, click twice), nice (+10 on every thread; back to 0 only where `ulimit -e` allows it, so not here) and info (a block under the lists: full command line, user, start, RSS, threads, cwd, and `htop -p`). PID 1, kernel threads, other users' processes and bardeck itself are dimmed and take no action. A word on the row says how it went (sent TERM, killed, gone, denied, nice 10); a row acted on stays a few seconds after its process left the list. Pinned: `i`/`o` a row, `k`/`l` half a list, `u`/`p` (or `j`/`;`) the CPU / memory list, `t` term, `K` kill (twice), `n` nice, Enter info. Then disks; updates (check / upgrade); htop, biggest dirs, boot blame. |
| network | Signal (the icon's colour), traffic, the VPN, tailscale. The SSID is in the panel. | The link (signal, band, link rates, addresses); **the Wi-Fi networks in range**, nmtui's "Activate a connection" (`bardeck/wifi.py`, NetworkManager over D-Bus, read only while the panel is open): click a row to join, a new secured network opens a password field in its row (Enter join, Tab show, `Ctrl+V` paste, Esc cancel; a failed new profile is deleted again), hover a row for disconnect / forget (click twice); enterprise and WEP go to `nmtui-connect`. Pinned: `i`/`o` select, `k`/`l` half a list, Enter join, `r` scan, `d` disconnect, `x` forget. **The tailnet** (`bardeck/tailnet.py`, tailscaled's local API over its socket, in-process, every ≥5 s only while the panel is open): this node, then each peer (online first, up to 6) with its OS, name, IPv4, and direct / relay (DERP region) when known, or offline and when last seen. Click a row: copy its address (`wl-copy`, a "copied" chip); hover it: "ping" (latency and path, the local API's disco ping, only when asked) and "ssh" (`alacritty -e ssh <host>`); "ping all" pings every online peer once. Exit-node chips only when a peer offers one; changing it needs tailscaled's operator (`sudo tailscale set --operator=$USER`), and the panel says so. The selection runs on from the networks into the peers: Enter / `c` copy, `t` ping (the selected or hovered peer, else all), `s` ssh. Then 5 min of traffic, VPN off / wg_1 / wg_2, network.sh's actions (link rates, reconnect, reset adapter, nmtui, speedtest). |
| devices | Bluetooth, and the headphones, keyboard and mouse lit when connected. | Bluetooth on / off; **every device BlueZ knows**, bluetoothctl drawn (`bardeck/bluez.py`, BlueZ over D-Bus, mirrored only while the panel is open): type icon, battery, marks for connected / paired / trusted, and while a scan runs the devices found with their signal (nameless ones behind "show n unnamed"). Click a paired row to connect, a new one to pair, trust and connect; hover a row for disconnect / forget (click twice). A pairing asks for, or shows, its code in the row (PIN or passkey field, confirm / reject chips); Esc cancels it, and so does closing the panel. Scan runs 25 s, never by itself (an inquiry makes Bluetooth audio stutter). Pinned: `i`/`o` select, `k`/`l` half a list, Enter connect / pair, `r` scan, `d` disconnect, `x` forget, `a` unnamed. Then where sound goes (click to switch output or input), mixer, bluetoothctl, restart logid, nuke bt. |
| audio | The output's volume (its icon red when muted), the mic (red when muted), and while a player plays a ♪ and its title (compact: a play mark). Scroll: ±5% on the default output; middle click: mute; right: pavucontrol. | pavucontrol, drawn (`bardeck/audio.py`): the **player** on top (MPRIS: cover, title, artist, album, a progress bar to click, previous / play-pause / next, a chip per player when there are several), then **output** and **input**, each device a row with its slider (click sets, the wheel steps 5%) and mute; click a row to make it the default (an output takes the playing streams with it). **Apps**: every stream with its own slider and mute, and which output it goes to. Pinned: `i`/`o` select, `k`/`l` half the list, `u`/`p` −/+5% (the player row: previous / next track), `m` mute, Enter default / play-pause, space play-pause, `j`/`;` previous / next player; with no row selected `u`/`p`/`m` act on the default output. |
| displays | A monitor and the count of screens on (full: `/N` when a connected one is off). Amber while a preset runs or a new mode waits to be kept. | The screens drawn to scale where niri put them (the ones that are off greyed, beside; the focused one outlined; click one to select it), then the selected screen's power, scale, rotation, VRR and modes (`bardeck/displays.py`: niri's socket for reads, `niri msg output` for changes). The last screen on cannot be turned off. A new mode goes back after 15 s unless kept (Enter or "keep"), with the panel closed too. Then **niri-screen-switch's entries as presets** (game, screens, sound, theme, font): each runs `niri-screen-switch "<entry>"`, so the script's logic stays in one place; a screen preset whose output is not connected is disabled. Pinned: `u`/`p` (or `j`/`;`) previous/next screen, `i`/`o` a mode, `k`/`l` half a list, Enter try the mode (or keep it), BackSpace go back. Right click: the script's menu. |
| power | Battery, the power profile, turbo boost when on; a cup while caffeine is on; while a screen recording runs a red dot and its time (a hollow amber dot while its picker is up). | The battery's last 24 h (upower's history), draw, health, the charge limit; power profile and turbo boost switches; **keep awake** (caffeine, `bardeck/caffeine.py`): off / on / 1 h / until the battery is below 20%, no lock and no screen off meanwhile; while a **recording** runs (`bardeck/recording.py`), its mode, time, file and a stop button (the key bind's own stop: `niri-record <mode>` again). |
| notif | A bell; a badge with the notifications that came since the panel was last opened. Do Not Disturb: a sleeping bell (yellow), the badge counts the held-back ones too. Middle: Do Not Disturb on / off. Right: the last notification again. | dunst's history (`bardeck/notif.py`, dunst's own D-Bus API): newest first, a header per run of one app, the urgency as a stripe (critical red), new ones marked. Click a card: dunst shows it again (its popup runs its action); hover it: × removes it. Do Not Disturb, clear all (click twice). Pinned: `i`/`o` select, `k`/`l` half a list, Enter show again, `x` remove, `c` clear all (twice), `z` Do Not Disturb. |
| clock | Date and time. | Time to the second, UTC, day of the year, two months with week numbers. Beside them **the weather** (`bardeck/weather.py`, Open-Meteo, no key): now (icon by WMO code, temperature, feels-like, wind), today's min / max and chance of rain, the next 12 h (icon, temperature, rain as bars). The place is `~/.config/bardeck/location` (`lat lon name`; Zürich without it). **Today and tomorrow** (`bardeck/agenda.py`): the events of the iCal feeds listed in `~/.config/bardeck/calendar` (one URL or path per line, optional `#rrggbb` colour and a name; for Google: the calendar's settings, "Integrate calendar", "Secret address in iCal format"), with recurrences, moved and cancelled instances and time zones; the running event is lit with the time left, the next one says "in 40 min", a Meet / Zoom / Teams link gets a camera mark and a "join" chip (click: `xdg-open`). Without the file the panel says how to set it up. **Right click: the whole year.** Pinned: `y` year ⇄ two months, `u`/`p` a month (a year in the year view), `t` today, `i`/`o` an event (`k`/`l` four), Enter join, `r` fetch again. |
| palette (no strip: **Mod+D**, `bardeck open palette`) | — | **The launcher** (rofi's place; `bardeck/palette.py`): a field and the best ten rows of apps (the `.desktop` files, ranked by the fuzzy match and by how often each was started — here (`~/.local/state/bardeck/palette.json`) and before under rofi (`~/.cache/rofi3.druncache`, `rofi-4.runcache`, read again when they change)), **the command history** (every line run before with its arguments — rofi's and the palette's — as a row of its own: `susp` finds `systemctl suspend`; X11-only tools such as `scrot` or `record-window` are still found, with a note, but never offered on an empty field), open windows (Enter focuses), commands on PATH (`>` first, or low in the list when the first word names one; run through `rofi-run`, so its terminal rules and `run-overrides` hold), and actions (niri-screen-switch's entries, network.sh / vpn.sh / power-profile.sh menu entries, "Open <panel>" for every panel). `=` (or plain arithmetic) is a calculator, Enter copies the result; `:` searches the web or opens an address. A chip says each row's kind, matched letters are lit. Keys: Enter run, Ctrl+n/p or arrows, Tab / Shift+Tab the filter (all, apps, windows, commands, actions), Ctrl+u, Ctrl+w, Ctrl+v, Esc. Programs start as niri's children (its Spawn action), not the daemon's: they would inherit its nice 5. |
| clip (no strip: **Mod+Shift+V**, `bardeck open clip`) | — | **The clipboard history** (`bardeck/clip.py`, `clipstore.py`): newest first, pinned on top; text as two lines, images as thumbnails. Enter or click copies an entry back (`wl-copy`, an image with its MIME type), closes, and **pastes it into the window you opened it from** (ydotool — real keys through /dev/uinput, so X11 apps such as Emacs get them too; wtype only without ydotoold — sends that app's paste key: Ctrl+Shift+V in a terminal, Ctrl+V for an image there — Claude Code's image paste; in Thunar Ctrl+Shift+V for an image = `niri-paste-image`, a new file in the open folder; Ctrl+V elsewhere); `y` copies only; hover a row for pin / ×. Keys: `i`/`o` select, `k`/`l` half a list, Enter paste, `y` copy only, `p` pin, `x` remove, `c` clear all but the pinned (twice), `/` search (every word; Enter back to the list, Esc clears). |

**Caffeine.** niri's own `org.freedesktop.ScreenSaver.Inhibit`, on the session
bus, in-process: niri marks its idle notifications inhibited, and swayidle
(`niri-idle`) never hears the seat went idle. niri drops the inhibitor itself when
bardeck's bus connection goes, so a dead daemon leaves none behind; the mode is
kept in `$XDG_RUNTIME_DIR/bardeck/caffeine` and taken up again after a restart.
Not `systemd-inhibit --what=idle`: swayidle 1.9.0 fails to read logind's
`BlockInhibited` ("Invalid argument", `swayidle -d`) and ignores it.
**Recording** is niri-record's state file (`$XDG_RUNTIME_DIR/niri-record-<mode>.state`):
the power strip stats three absent files a second, and draws only when they appear.

**Pairing's agent.** bardeck registers a BlueZ agent (`org.bluez.Agent1`,
KeyboardDisplay) only while a pairing it started runs, and makes it the default
agent for that time; then it unregisters, and BlueZ gives the default back to
blueman-applet. It answers only bluetoothd, gives codes only for the device being
paired, and authorizes services only for that device and paired or trusted ones.

**The short list.** `BAR-FEATURES.md` (next to this file) says in one line per
feature what the bar can do and how to reach it; Mod+D → "bar features" opens it, and
`bardeck/tips.py` shows one of its lines a day as a notification until each was shown
once. What changed when, and what was verified: `BAR-LEDGER.md`.

**The buttons reuse the scripts.** A panel button runs the i3blocks script's own
menu entry (`core.menu_action`): a `rofi` shim on PATH answers the menu with the
button's choice. So `vpn.sh` still owns the wg-quick lines, `network.sh` the
adapter reset and the speedtest, `bt-*.sh` the devices (their `MAC=`/`NAME=` are
the device list).

**One process for the whole bar, and no others.** The old bar ran a script per
block per bar every few seconds (~15% of a core after the 7 Oct sharing fix, ~70%
before). bardeck reads `/proc` and `/sys`, NetworkManager and BlueZ over D-Bus
(BlueZ only when it signals a change), addresses by ioctl, and niri's socket. It
starts no program in steady state but one: `iw` and the devices panel's `pactl`
only while their panel is open, `checkupdates` once an hour on its own thread, and
the audio strip's one long-lived `pactl subscribe` (below). The tailnet is read from
tailscaled's socket (one HTTP GET, ~1 ms) only while the network panel is open. The
clock panel fetches the weather (at most every 30 min) and the calendar feeds (at
most every 15 min) on threads of their own, only while it is open, with a timeout;
the answers are kept in `$XDG_RUNTIME_DIR/bardeck/` (`weather.json`,
`calendar-*.ics`), so the panel opens with the last ones, and says how old they are
when they are stale or the machine is offline. dunst's history is read when
dunst signals that a popup closed (one async D-Bus call per notification) and when
the notif panel opens; "unread" is a timestamp in
`$XDG_RUNTIME_DIR/bardeck/notif-seen`. A strip is drawn only when
its inputs changed (`key()`), written only when its bytes changed, and only in
the variant a screen shows. Strips are raw ARGB (`core.write_strip`), not PNG:
waybar copies them on its main thread instead of decoding. Measured 7 Oct 2026
over 90 s: **bardeck ~1.0% of a core, waybar ~0.1%, 0 child processes**, ~45 MB.
(The first version was 7.6%: a /proc scan per signal to find waybar, and
`bt-state.sh`/`iw`/`ip` every 4 s.)

**Key-opened panels.** `bardeck open NAME` sends one datagram to the daemon's
socket (the launcher script does it without importing cairo: ~30 ms), and the
panel opens pinned, centred near the top of the focused output (niri's
`FocusedOutput`), at that bar's zoom. The same key again, Esc or a click outside
closes it. Passing a strip does not swap it; clicking one does.

**Clipboard: one idle child, on purpose.** There is no cliphist, and only
`wl-paste` hears the selection change (wlr-data-control; a GTK window sees it only
while it has the focus). So `bardeck/clip.py` keeps ONE `wl-paste --watch`
running (since 13 Oct 2026: the daemon's second child). It sleeps until a copy;
then it runs `clipstore.py`, a short stdlib-only Python (~30 ms, one more
`wl-paste` for the types, and one for an image), which files the copy in
`~/.local/state/bardeck/clip/`: dedup by hash, the newest 200 plus the pinned
ones, images as files with a thumbnail (Pillow), nothing over 5 MB, and nothing
a password manager marks (`CLIPBOARD_STATE=sensitive`, `x-kde-passwordManagerHint`).
The child dies with the daemon (PR_SET_PDEATHSIG) and is restarted when it ends.

**Agents: rcmon asked on edges, not polled.** The agents panel adds no
bookkeeping: rcmon's `/api/state` is cmon's own board plus its reading of every
pane, and `/api/mrs` its cache of the open MRs. One `/api/state` costs rcmon ~0.18 s
of CPU (it captures every pane) and may make it read GitLab (its MR cache lives
60 s), so bardeck asks only on an edge: every 4 s it reads `/proc/<pid>/stat` of each
claude process (a working one burns 4-6 ticks/s, one at a prompt ~1) and the mtime
of cmon's lock directory, and asks when one went quiet or busy, ended, or was
spawned: at most every 30 s, at least every 5 min, every 4 s while the panel is
open. The last answer is kept in `$XDG_RUNTIME_DIR/bardeck/agents.json`. With rcmon
down the MRs come from `glab api` (GET), at most every 60 s while the panel is open.

**Audio: one idle child, on purpose.** There is no pulsectl and no Python
libpulse here, and libpulse over ctypes means copying `pa_sink_info` & co. by hand.
So `bardeck/pulse.py` keeps ONE `pactl subscribe` running (since 13 Oct 2026, so the
measurement above now reads "1 child process"): it prints a line per PulseAudio
event and sleeps in poll() otherwise (~0 CPU). On a sink, source or server event
(streams only while the panel is open) bardeck runs `pactl -f json list` for what
changed, at most 4 times a second, and draws the strip: a volume key reaches the
bar in ~30 ms (the native module it replaced followed the events too). The child
dies with the daemon (PR_SET_PDEATHSIG) and is restarted when PulseAudio restarts.
The players come over MPRIS on the session bus, in-process (`bardeck/mpris.py`);
covers are decoded with Pillow, only while the panel shows them: GdkPixbuf would
decode through glycin, a sandboxed loader process that lingers ~30 s.

**Fast panels.** The panels live in the daemon on one hidden layer-shell
overlay. A panel opens in ~20 ms (one map and one blit); the quota panel, which
takes ~0.15 s to draw, is drawn ahead whenever its data changes.
`BARDECK_TRACE=1` prints the times.

**Theme.** The colours follow `~/bin/theme` (`~/.config/theme/state`): the
palette comes from the same `~/.config/i3/colors.d/<palette>-<mode>.conf` i3
uses, with status colours tuned per theme in `core.STATUS`. On a switch bardeck
writes `waybar/theme.css` (imported by `style.css`, not in git) and reloads
waybar.

**Standing out on the wallpapers.** The bar has no background: the wallpaper
shows between the pills, and behind them is a frosted band that `niri-wallpaper`
bakes into the wallpaper (blurred and tinted; niri cannot blur behind a layer
surface). On a busy wallpaper (gruvbox-dark-20's fractal) the gaps between the
pills showed sharp detail before, and the bar looked broken into pieces. Each pill is nearly opaque (0.96), has a soft shadow
under it (stronger on dark themes), a rim, and a faint highlight along its top,
so it reads as a raised object where its colour matches the wallpaper (the light
themes' pills are the cream of their wallpapers). On the darkest wallpapers no
shadow shows, so the dark themes' rim is a step brighter. `style.css` gives the
native pills the same (box-shadow). Checked on every gruvbox-dark, gruvbox-light
and selenized-dark wallpaper.

**Working on it.**

- `bardeck render FILE STRIP [compact]` and `bardeck panel FILE PANEL` draw one
  to a PNG; `BARDECK_THEME="light gruvbox"` draws another theme.
- After a Python edit: `pkill -USR2 -x waybar` (it restarts the daemon too).
  Never `pkill -f bardeck`: it matches your own shell.
- After an edit to `bar-strip.c`: run its build line (in the file, and in
  `install.sh`), then restart waybar.
- **waybar exits on a CSS error**, a `/*` inside a comment included. Check
  `/run/user/1000/waybar.log` after a `style.css` edit; restart it with
  `niri msg action spawn -- sh -c 'waybar > /run/user/1000/waybar.log 2>&1'`.
- **Size.** The code draws a 28 px bar (a 24 px pill and 3 px for its shadow,
  `core.SH`), and each variant `core.ZOOM` bigger: the big screen's bar 36/28
  (36 px, text ~17 px), the laptop's as drawn (its screen is at scale 1.25
  already, and a bigger bar would not fit its 1536 px). Panels take their strip's
  zoom. To change it: `core.ZOOM`, the bar's `height` in `config.jsonc`, the
  `window#waybar.main` rules in `style.css`, `BAND` in `niri-wallpaper` and
  `BAR_HEIGHT` in `barmenu` (39: 3 px margin + 36).
- No `restart-interval` on `custom/bardeck`: with it, every waybar reload left a
  zombie `[waybar]` process.
- A strip may change width freely (`bar-strip.so` sizes itself to the
  picture), but the bar must fit: waybar cuts off what runs past the screen's
  edge. At 36 px the main bar's pills come to ~2,250 of 2,548 px (7 Oct 2026).
  No pill is in the centre: when room runs short, waybar pushes a centre module
  about.

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
- **Colours.** They are fixed hex values in `layout.kdl` and
  `hypr/hyprlock.conf`; the theme scripts (`dark-gruv` etc.) do not change them.
  The bar follows the theme (see [The bar](#the-bar-bardeck)).
- **See the live state:** `niri msg windows`, `niri msg workspaces`,
  `niri msg outputs`, `niri msg -j event-stream`.
- **The niri log:** `journalctl --user -t niri`. Each reload writes a
  `loaded config` line there.

## Lock screen: finger OR password

swaylock needed the password **and** then a finger. It starts PAM only
after Enter, and the PAM stack (`swaylock` → `login` → `system-auth`) asks
`pam_fprintd` first. So the typed password waited for a finger.

hyprlock reads the fingerprint itself, over fprintd's D-Bus API, at the same
time as the password field. Its PAM service must therefore **not** contain
`pam_fprintd`. If it does, a typed password waits for a finger again. The
stock `/etc/pam.d/hyprlock` includes `login`, so `hyprlock.conf` uses
`hyprlock-password` instead. That file is `system-auth` without its
`pam_fprintd` line and without faillock: when the finger unlocks, hyprlock
cancels the waiting password call, and faillock counts that as a failed login.
Three finger unlocks would then lock the password for 10 min.

To test without locking your session, run a nested niri (`niri -c <empty
file>`), then `WAYLAND_DISPLAY=wayland-N hyprlock -v`, and `grim` that
display. `kill -USR1` unlocks it.

## niri limits that shaped this setup (niri 26.04)

- One action per key. That is the reason for most of the scripts.
- The IPC does not report if a column is tabbed, and it does not report a
  window's position on screen (`tile_pos_in_workspace_view` is always null).
  To record one window, use the portal picker.
- No runtime action for gaps, and no sticky windows. So the w95-sysmon
  drop-down stays on one workspace.
- **In an included file, a block that is off by default needs an explicit
  `on`.** niri merges each block onto its defaults. `border { width 4 … }`
  with no `on` loads the width and colours and draws nothing, and you get no
  error. That is how the split of `config.kdl` lost the focus border. To check
  the border on the live session: `niri msg focused-window` must show
  `window_offset_in_tile` = `[4.0, 4.0]`; `[0.0, 0.0]` means no border.
- A border has one colour on all four sides. So the hot-bottom indicator is
  a hard shadow (softness 0, 4 px down), which shows as a line under the
  bottom border, not in its place. A window rule cannot match one window
  id either, so the rule matches `is-focused` and the file exists only
  while the focused window is armed. That costs one config reload per
  change, and a `loaded config` line in the log for each.
- Wayland app-ids are not X11 classes. A rule that matches nothing gives no
  error.
- niri runs under `systemd --user` and inherits its environment. This is why
  `environment.kdl` exists.
- Screen sharing goes through xdg-desktop-portal. A portal left over from an
  i3 session has no screen-cast support. `startup.kdl` restarts it.
- Native Wayland GTK apps (Thunar, the file picker) ignore `settings.ini` and
  xsettingsd. They read the GTK theme and icons from gsettings
  (`org.gnome.desktop.interface`). `theme` writes those keys too. Set them by
  hand with `gsettings set org.gnome.desktop.interface icon-theme Faenza-Darkest`.

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
