# kanata — the TOTEM layout on the p14s built-in keyboard

The laptop keyboard runs the same layout as the TOTEM (`~/zmk-config-totem/config/totem.keymap`):
home-row mods, the six thumb keys, and the layers SYM / NUM / ADJ / MOV / MOUSE.
`kanata.kbd` has the full map and the timing in its header.

Only `/dev/input/by-path/platform-i8042-serio-0-event-kbd` (the built-in keyboard) is
grabbed. External keyboards do their layout in firmware and never pass through kanata.

## The bottom row = the TOTEM thumbs

| Laptop key | TOTEM thumb | Tap | Hold |
|---|---|---|---|
| leftmost (Fn)* | left outer | Backspace | — |
| left Super | left middle | one-shot SYM | SYM (J-Ctrl held: Ctrl+Tab) |
| left Alt | left inner | toggle MOUSE | MOV |
| Space | right inner | Space | Super |
| right Alt | right middle | Esc | NUM |
| Copilot key** | right outer | Enter | — |

Caps Lock = the TOTEM left outer pinky: toggles MOV. Right Ctrl stays Ctrl.
Reach ADJ (F1–F12) with SYM + right Alt, or NUM + left Super.

\* The ThinkPad firmware owns Fn; it sends no key code. BIOS setting **FnCtrlKeySwap = Enable**
(set 8 Oct 2026 through think-lmi, no BIOS password) makes it send Left Ctrl, and the Ctrl key
becomes Fn. It takes effect after a reboot. Check or undo it from Linux:

```bash
sudo cat /sys/class/firmware-attributes/thinklmi/attributes/FnCtrlKeySwap/current_value
echo Disable | sudo tee /sys/class/firmware-attributes/thinklmi/attributes/FnCtrlKeySwap/current_value   # then reboot
```

\*\* The Copilot key (P14s Gen 6, right of right Alt) has no key code of its own: firmware sends
Left Super + Left Shift + F23. kanata maps F23 to `(unmod (lsft) ret)`: Enter without that Shift.
Its Super opens SYM for a moment, and the F23 press uses up the one-shot. Held mods still apply:
F-Ctrl + Copilot = Ctrl+Enter, K-Shift + Copilot = Shift+Enter. The BIOS has no Copilot option.

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
sudo python3 ~/.config/kanata/hrm-harness.py ~/.config/kanata/kanata.kbd   # 31 cases
sudo systemctl disable --now kanata-laptop  # turn it off
journalctl -u kanata-laptop
```

**Emergency exit:** hold Left Ctrl + Space + Esc, as kanata sees them: after the Fn/Ctrl swap
that is the leftmost key + Space + the Esc key in the top-left corner. kanata exits 0 and
stays off until `sudo systemctl restart kanata-laptop`.

The unit in `/etc/systemd/system/` is a **copy**; `install.sh` warns when it differs. After you edit it:
`sudo install -m644 ~/dotfiles/kanata-pkg/systemd/kanata-laptop.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart kanata-laptop`.

Install from scratch (p14s only — p340 has no built-in keyboard): `pikaur -S kanata-bin`, then
`./install.sh` in `~/dotfiles`. It stows `kanata-pkg` only where kanata is installed and prints
the one root command for the unit. Then set FnCtrlKeySwap as above.

## Known limits

- **No Polish letters** on this laptop: the `pl` xkb layout is gone (right Alt is a thumb key).
- **Ctrl/Shift + mouse click:** the touchpad and the TrackPoint are other devices, so kanata does not
  see the click. A held `F` becomes Ctrl only when its 180 ms term ends. Hold the key a moment
  before you click.
- **Emacs `fs` chord:** release `f` first and you get `fs`. Release `s` first and you get `C-s`.
  QMK PERMISSIVE_HOLD and ZMK `balanced` do the same.
- **No bilateral filter**, like the TOTEM and like the QMK boards in practice (their Achordion
  `achordion_chord` falls through to `return true` for every home-row key). If same-hand misfires
  start, kanata 1.12 has `defhands` + `tap-hold-opposite-hand-release` — the Achordion equivalent.
