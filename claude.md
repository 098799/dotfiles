# Dotfiles Configuration Guide

This document describes the i3/i3blocks configuration managed by Claude Code. Run future sessions from `~/dotfiles` directory.

## Directory Structure

```
~/dotfiles/
├── .config/
│   ├── i3/
│   │   └── config          # i3wm config (solarized dark theme)
│   ├── i3blocks/
│   │   └── config          # i3blocks bar config
│   └── rofi/
│       └── config.rasi     # rofi menu styling (solarized dark)
├── scripts/                # i3blocks scripts
│   ├── service-*.sh        # Service monitoring (ontology, consumer, frontend, user)
│   ├── claude-usage.sh     # Claude API usage monitor
│   ├── vpn.sh              # WireGuard VPN status/menu
│   ├── bluetooth.sh        # Bluetooth status/menu
│   ├── volume.sh, mic.sh   # Audio controls
│   ├── cpu.sh, memory.sh   # System resources
│   ├── battery.sh          # Battery status
│   ├── network.sh          # WiFi/ethernet status
│   ├── disk.sh             # Disk usage
│   ├── updates.sh          # Package updates
│   ├── screenshot.sh       # Screenshot tool
│   └── datetime.sh, uptime.sh
├── bin/                    # General scripts (screen_switch, themes, etc.)
└── claude.md               # This file
```

## Symlinks

The following symlinks should exist:

```bash
~/scripts -> ~/dotfiles/scripts
~/.config/i3/config -> ~/dotfiles/.config/i3/config
~/.config/i3blocks -> ~/dotfiles/.config/i3blocks
~/.config/rofi -> ~/dotfiles/.config/rofi
```

To recreate symlinks:
```bash
ln -sf ~/dotfiles/scripts ~/scripts
ln -sf ~/dotfiles/.config/i3/config ~/.config/i3/config
rm -rf ~/.config/i3blocks && ln -s ~/dotfiles/.config/i3blocks ~/.config/i3blocks
rm -rf ~/.config/rofi && ln -s ~/dotfiles/.config/rofi ~/.config/rofi
```

## i3blocks Features

### Service Monitoring (os, oc, fr, us)

Four services are monitored:
- **os** = ontology service
- **oc** = ontology_consumer service
- **fr** = frontend service (Angular)
- **us** = user service

**Colors:**
- Green: service healthy
- Yellow: has errors (UNKNOWN_TOPIC detected) or Angular building
- Red: service stopped

**Interactions:**
- Left click: open logs (`journalctl -u SERVICE -f`)
- Right click: rofi menu (restart/stop/logs/status)

**Error detection:** Checks logs since service started for `UNKNOWN_TOPIC` pattern.

**Angular build detection:** Frontend shows yellow when Angular is compiling (detected via log messages).

### Claude Usage Monitor

Shows Claude API usage percentage and time until reset.

**Colors (based on 5hr window):**
- Green: on track (usage ≤ expected for time elapsed)
- Yellow: 1-15% behind expected
- Red: >15% behind expected

**Interactions:**
- Right click: open claude.ai/settings/usage

**Config:** Requires cookies in `~/.config/claude-cookies` and org ID in script.

### VPN (WireGuard)

Shows VPN status with wg1/wg2 indicator.

**Colors:**
- Green: connected (wg1 or wg2)
- Yellow: disconnected

**Interactions:**
- Right click: rofi menu to connect/disconnect (off, tomek wg_1, tomek2 wg_2)

**Config:** WireGuard configs in `~/.config/wg/wg_1.conf` and `wg_2.conf` (NOT in git - use Syncthing).

### Bluetooth

**Interactions:**
- Right click: rofi menu (bluetoothctl, power on/off, nuke_bt, restart logid)

### Other Blocks

- **CPU**: left click = htop, right click = btop
- **Memory**: left click = htop
- **Disk**: left click = `du -h / | sort -h`, right click = `df -h`
- **Network**: right click = nmtui
- **Volume/Mic**: scroll to adjust, click to mute
- **Battery**: shows percentage, charging status
- **Date/Time**: left click = cal -3, right click = cal -y
- **Screenshot**: left click = select area, right click = full screen

## Color Scheme (Solarized Dark)

```
Base:       #002b36 (background), #073642 (highlight)
Content:    #839496 (body), #93a1a1 (emphasis)
Accent:     #859900 (green), #b58900 (yellow), #cb4b16 (orange), #dc322f (red)
            #268bd2 (blue), #657b83 (gray)
```

## Files NOT in Git (Syncthing only)

These contain sensitive data - sync via Syncthing, not git:

- `~/.config/wg/wg_1.conf` - WireGuard config with private key
- `~/.config/wg/wg_2.conf` - WireGuard config with private key
- `~/.config/claude-cookies` - Claude API session cookies

## Audio Configuration

PulseAudio config in `~/.config/pulse/default.pa` disables `module-suspend-on-idle` to prevent audio devices getting stuck in SUSPENDED state.

After changing audio settings, persist with:
```bash
sudo alsactl store
```

## Maintenance Commands

```bash
# Restart i3blocks
pkill -x i3blocks; i3-msg restart

# Refresh specific block (by signal number)
pkill -RTMIN+1 i3blocks  # ontology
pkill -RTMIN+2 i3blocks  # consumer
pkill -RTMIN+3 i3blocks  # frontend
pkill -RTMIN+4 i3blocks  # user
pkill -RTMIN+10 i3blocks # volume
pkill -RTMIN+11 i3blocks # mic

# Check service logs
journalctl -u SERVICE_NAME -f

# Clear claude usage cache
rm /tmp/.claude_usage_cache
```

## Machine-Specific Notes

- `~/bin/` contains machine-specific scripts - NOT symlinked from dotfiles
- Audio config (`~/.config/pulse/default.pa`) may need adjustment per machine
- Screen layouts in `~/.screenlayout/` are machine-specific
