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
| Notification area | `w95tray.py`, inside `w95bar` | starts with the bar |
| Status readouts | `w95-sysmon` (`$mod+s`) | always available, both desktops |

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

### Notification area

The sunken well left of the clock is a real XEmbed system tray, so nm-applet,
the Nextcloud client, syncthing and anything else with a tray icon land there.
Before it existed `_NET_SYSTEM_TRAY_S0` had no owner on this machine at all —
i3's tray is part of i3bar, and Win95 mode has no `bar {}` block — so those apps
had nowhere to draw and silently showed nothing. Check the owner with:

    xprop -root _NET_SYSTEM_TRAY_S0

It needs **python-xlib**; without it the bar still starts and just has no
notification area. The protocol needs an X selection, raw `ClientMessage`
delivery and a `MANAGER` broadcast, none of which PyGObject exposes —
`Gdk.Window.add_filter` is not introspectable. Only the embedding half is GTK
(`Gtk.Socket`). `w95tray.py` explains the rest, including why
`_NET_SYSTEM_TRAY_VISUAL` is deliberately not advertised (no compositor) and why
StatusNotifierItem is not implemented (everything here falls back to XEmbed).

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

Two things about that grab are load-bearing and were both got wrong once:

* **It has to be taken after the window is mapped.** `show_all()` only queues
  the map, so grabbing immediately after it returns `GDK_GRAB_NOT_VIEWABLE`.
  Nothing checked the return value, so the failure was silent and total — with
  no grab, a click outside the menu went to whatever was underneath and the
  menu simply stayed on screen. `_try_grab` now retries until the window is
  viewable and complains on stderr if it never manages it.
* **Rows must not be focusable.** A row is a `GtkButton`, so the first one took
  focus the moment the menu opened and sat there in navy — "Programs"
  permanently lit, looking selected when it was not. `set_can_focus(False)`,
  and the stylesheet highlights `:hover` only, never `:focus`. Win95 lit the
  row under the pointer and nothing else.

## System Monitor

`w95bar` replaces i3bar, and with it goes the `bar {}` block — so Win95 mode
has no i3blocks strip and no tray. `w95-sysmon` is where all of that went:

    $mod+s        drop it in; press again to send it away

It is a quake console. Full width, slides down from the top edge, sticky across
workspaces, no decoration. The process stays **resident and hidden** between
presses — that is what makes every press after the first instant. `Esc` and the
X button hide it too; only File ▸ Exit really quits.

Hidden, it splits what it keeps doing:

* **The charts keep running.** A strip chart whose history starts when you open
  it cannot answer the question it exists for — what happened while you were
  not watching. Sampling on a fixed interval regardless of visibility is also
  the only way the x-axis means anything: stop and restart it and the series
  splices two sessions together with no gap drawn, while the first reading back
  averages the entire absence into one point (both meters are differential). A
  thirty-second CPU burn arrived as a single spike, at the wrong height, in the
  wrong place. Measured cost of leaving it on: **60 ms of CPU per minute**,
  about 0.1% of one core, for three small reads under `/proc`.
* **The probes stop.** `bluetoothctl` and `checkupdates` have no business
  firing at a window nobody is looking at, and unlike the charts they are
  point-in-time state with no history to miss.
* **Except the Claude sampler**, which is the exception that proves the rule:
  once its history is charted, a probe skipped is a hole that cannot be filled
  in later. See *Claude quotas* below.

Start it at login with `w95-sysmon --hidden` and the panel already knows the
last few minutes the first time you open it. That has to be `exec`, never
`exec_always`: a second invocation is a keypress being forwarded to the
resident one, so a reload would pop the panel open every time.

Everything is on one page: three scrolling charts (processor, memory, network),
a row of Claude usage charts under them, then nine group boxes covering every
block the bar had, plus `temp`, `keyboard` and `record`, which have scripts but
were never enabled in `i3blocks/config`.

And it is not a read-out. Every block that did something when you clicked it in
the bar does it here from a real control:

| | |
|---|---|
| Bluetooth | Connect/Disconnect per device, adapter power, battery level |
| VPN | one row per `~/.config/wg/*.conf`, up and down |
| Audio | volume trackbar, mute, mic mute, mixer |
| Power | platform profile radios, CPU boost, battery estimate |
| Claude | every quota per account, a week of history, and the account switcher |
| System | htop, `df -h`, `pacman -Syu`, boot log, screenshot, keyboard layout |

Two shapes, in `~/.config/w95/settings` or from Options ▸ Display as (which
writes that file and restarts itself):

```ini
sysmon_mode = drop     # quake panel (default)
sysmon_mode = window   # ordinary floating window; i3-95 gives it a caption
sysmon_size = 62       # drop mode: percent of the screen it covers
```

The page reflows — five columns as a 2560px panel, two as an 1180px window —
so both shapes get the same content without a second layout.

### Where the numbers come from

Split on "would I be copying a decision, or a formula?".

*Formulas* are reimplemented natively in `w95stat.py`: percent busy, bytes per
second, bytes free. They are sampled from `/proc` and `/sys` once a second on
the main loop, because that is what the charts are made of and forking three
shell scripts a second to get them would be absurd.

*Decisions* are not. Which Claude accounts exist and how their usage is fetched,
which WireGuard conf is "tomek2", how this laptop's SSID is spelled, whether
`checkupdates` has been cached in the last hour — those stay in the i3blocks
scripts, which are run as-is and parsed. The monitor and the bar cannot
disagree, and pairing a new Bluetooth device is still done by adding a block
script: `bt_devices()` reads the MAC and name back out of `bt-*.sh`.

Everything that forks runs on a worker thread and lands back on the main loop.
A probe that times out keeps the last good value rather than blanking the field,
because `bluetoothctl` being slow is not news.

### Claude quotas

The bar block showed one number: the five-hour window of whichever account is
signed in. That is the limit you hit most often, but it is not the one that
ruins a week — so the panel shows every limit the usage document carries, per
account, one gauge each:

| | |
|---|---|
| `5h` | the five-hour window, the one the bar block showed |
| `7d` | the weekly quota — seven days to refill, whatever you do |
| *model* | the weekly quota for one model, e.g. Fable |

The model-scoped one exists **only** inside the response's `limits` array:
`seven_day_opus` and its siblings come back `null` even when the scoped limit
is real and at 24%, so nothing else on this machine could see it.

Three limits times four accounts is twelve rows, so the panel splits its
accounts across two columns and takes two of the page's slots.

Where those numbers have *been* is a second row of scopes, under the processor,
memory and network ones: **one chart per account**, all three limits on it —
five-hour green, weekly cyan, model-scoped yellow. One chart per account rather
than one per limit because the question is always asked about an account ("can
`work` finish this today?") and never about a limit across accounts. How far
back they reach is Options ▸ Claude history (12 hours, 24 hours, 7 days) — its
own setting, because Update Speed governs the ring buffers of the live strip
charts and these are drawn from a file.

The dashed diagonal is *pace*: where that account's weekly quota would be if it
were spent evenly across the week. Above the line you run out before it
refills; below it you don't. It is the same judgement the bar's colour makes,
drawn rather than decided. Traces break where sampling stopped for more than 15
minutes — a laptop that was shut all night did not use anything all night, and
a line joined across the gap would say it did.

The history is a CSV that `claude-usage.sh` appends to, one row per account per
sample:

    ~/.local/state/w95/claude-usage.csv

Whoever asks for usage writes a row, at most one per account every 100 seconds:
the i3blocks block in a normal session, the System Monitor in a Win95 one. The
monitor keeps sampling while hidden — `claude_sample = 120` seconds in
`~/.config/w95/settings`, `0` to only sample while the window is on screen —
because the chart is only as good as the samples behind it. Cost is one cached
HTTP call per account per two minutes, the cadence the mr-reviewer usage pusher
settled on against the same endpoint. The file is trimmed to the last 14 days
when it passes 4 MB; nothing else has to run.

This is one row per *account*, not mr-reviewer's one row per *sample* with two
positional columns per account and a "never reorder this list" warning on it —
a row that names its own account survives an account being added, renamed or
dropped, which on this laptop happens all the time.

### One trap worth knowing

Every radio and check box on that page is *both* an input and an output: polled
state writes into it, and it writes into the system. GTK emits `::toggled` for
programmatic changes too, so a sync looks exactly like a click — which is how an
early build of this silently changed the machine's power profile at startup,
just by constructing a radio group. Guard flags are not enough on their own.
`Panel.commit()` is the guarantee: re-read the authority (sysfs, pactl) at the
moment of the click and do nothing if it already agrees.

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

`$mod+s` opens the System Monitor and lives in the **main** i3 config, not in
`win95-keys.conf`, because it is useful in both desktops and because an include
cannot take a key that is already bound. `cmon` moved from `$mod+s` to
`$mod+Shift+s` to make room.

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
