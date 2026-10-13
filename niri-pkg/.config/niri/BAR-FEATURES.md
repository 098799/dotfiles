# What the bar can do — the short list

Built on 13 Oct 2026. One line per feature: what it is and how to use it.
The details are in README.md ("The bar"); what changed when is in BAR-LEDGER.md.

Every pill opens its panel on **hover**; a **click pins** the panel (then it has the
keyboard: `i`/`o` select, `k`/`l` half a list, Enter, Esc). Mod+D → "bar features"
opens this file. The bar shows one of these lines a day as a tip (see the end).

## Keys

- **Launcher on Mod+D** — apps, windows, your old rofi commands with their arguments (`susp` → `systemctl suspend`, `cam h` → `cam help`), `>` any command, `=` a calculator, `:` a web search. Tab changes the filter.
- **Clipboard history on Mod+Shift+V** — Enter pastes the entry into the window you came from (terminal, Emacs, Thunar: an image becomes a file in the folder). `y` copies only, `p` pins, `/` searches.

## Left side

- **Workspace overview: right-click the workspace pill** — every workspace and window as cards. Click a window to go there; hover it to move it a workspace up/down or close it.
- **Claude quota is folded** — the active account shows its chart; every other account is one thin bar (the weekly %, in qtop's colour). Hover for every account at full size.

## Right side

- **Agents pill (the robot)** — the number shows working agents; an amber badge means an agent waits for you; a red dot means a failed MR pipeline. Click an agent row to attach a terminal to it; click an MR to open it.
- **Kill or nice a process: system pill** — hover a process in the busiest lists for term, kill (click twice), nice (lower priority) and info.
- **Join a Wi-Fi network: network pill** — click a network to join; a new one asks for its password in its row. Hover for disconnect or forget.
- **Tailscale peers: network pill** — click a peer to copy its IP; hover it for ping and ssh.
- **Pair Bluetooth: devices pill** — "scan" for 25 s, click a new device to pair, trust and connect. A PIN or a code to confirm shows in the device's row.
- **Audio and media: speaker pill** — scroll on it for volume, middle-click to mute. The panel has the player (cover, seek, previous/play/next), every output and mic with a slider, and every app's own volume.
- **Displays: monitor pill** — the screens to scale; change scale, rotation, mode (a new mode goes back after 15 s unless you keep it), and the niri-screen-switch presets (game mode, layouts, sound, theme, font).
- **Keep awake: power pill** — "keep awake" on / 1 h / until 20% battery: no lock, no screen off. A cup shows on the pill.
- **Recording indicator: power pill** — while niri-record runs, a red dot and the time; the panel has a stop button.
- **Notifications: the bell** — the badge counts new ones. Click a card to show it again, hover × to remove, "do not disturb" to hold popups. Middle-click the bell: do not disturb.
- **Weather and today's meetings: the clock** — the next 12 h of weather from MeteoSwiss (Zürich). For meetings, put your Google "Secret address in iCal format" into `~/.config/bardeck/calendar`; a meeting link gets a "join" chip.
- **The whole year: right-click the clock.**

## Things to set up once

- **Calendar** — `~/.config/bardeck/calendar`: one iCal URL per line (Google Calendar → Settings → your calendar → Integrate calendar → Secret address in iCal format).
- **Weather place** — `~/.config/bardeck/location`: `8001 name` (a Swiss postcode) or `lat lon name` (Zürich without it).
- **Tailscale exit node** — needs `sudo tailscale set --operator=tgrining` once, and a peer that offers one.

## The daily tip

Once a day, at the first check after 09:00, a notification shows the next `- **…**`
line of this file, until all were shown once. Do Not Disturb holds it like any
popup. Start the tips again: `rm ~/.local/state/bardeck/tips.json` (the next one comes at
the next check). Stop them:
`echo '{"off": true}' > ~/.local/state/bardeck/tips.json`.
