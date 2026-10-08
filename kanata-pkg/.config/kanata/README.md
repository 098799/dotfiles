# kanata — home-row mods on the p14s built-in keyboard

The laptop keyboard gets the same home-row mods as the TOTEM and the Corne:
`A`=Super `S`=Alt `D`=Shift `F`=Ctrl | `J`=Ctrl `K`=Shift `L`=Alt `;`=Super.
Timing is copied from `~/zmk-config-totem/config/totem.keymap` (see the header of `kanata.kbd`).

Only `/dev/input/by-path/platform-i8042-serio-0-event-kbd` (the built-in keyboard) is
grabbed. External keyboards do their mods in firmware and never pass through kanata.

## Files

| File | What |
|---|---|
| `kanata.kbd` | the config |
| `~/dotfiles/kanata-pkg/systemd/kanata-laptop.service` | system unit (runs as root, so no `input`/`uinput` group and no re-login). Not stowed: `.stow-local-ignore` keeps it out of `~` |
| `hrm-harness.py` | behaviour check: a fake keyboard feeds a private kanata, output is grabbed so nothing types |

## Commands

```bash
sudo systemctl restart kanata-laptop        # after an edit of kanata.kbd
kanata --check -c ~/.config/kanata/kanata.kbd
sudo python3 ~/.config/kanata/hrm-harness.py ~/.config/kanata/kanata.kbd   # 13 cases
sudo systemctl disable --now kanata-laptop  # turn it off
journalctl -u kanata-laptop
```

**Emergency exit:** hold the physical `LeftCtrl` + `Space` + `Esc`. kanata exits 0 and stays off
until `sudo systemctl restart kanata-laptop`.

The unit in `/etc/systemd/system/` is a **copy**; `install.sh` warns when it differs. After you edit it:
`sudo install -m644 ~/dotfiles/kanata-pkg/systemd/kanata-laptop.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart kanata-laptop`.

Install from scratch (p14s only — p340 has no built-in keyboard): `pikaur -S kanata-bin`, then
`./install.sh` in `~/dotfiles`. It stows `kanata-pkg` only where kanata is installed and prints
the one root command for the unit.

## Known limits

- **Ctrl/Shift + mouse click:** the touchpad and the TrackPoint are other devices, so kanata does not
  see the click. A held `F` becomes Ctrl only when its 180 ms term ends. Hold the key a moment
  before you click.
- **Emacs `fs` chord:** release `f` first and you get `fs`. Release `s` first and you get `C-s`.
  QMK PERMISSIVE_HOLD and ZMK `balanced` do the same.
- **No bilateral filter**, like the TOTEM and like the QMK boards in practice (their Achordion
  `achordion_chord` falls through to `return true` for every home-row key). If same-hand misfires
  start, kanata 1.12 has `defhands` + `tap-hold-opposite-hand-release` — the Achordion equivalent.
