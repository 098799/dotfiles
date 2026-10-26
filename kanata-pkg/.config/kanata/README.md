# kanata — the Planck thumbs on the p14s built-in keyboard

The laptop keyboard runs the home-row mods and layers SYM / NUM / ADJ / MOV / MOUSE of the
TOTEM (`~/zmk-config-totem/config/totem.keymap`). The thumb row follows the **Planck**
(`~/qmk_firmware/keyboards/planck/keymaps/tg`), not the TOTEM: five thumb keys, one Space
in the middle for both thumbs. Six thumb keys (Corne/TOTEM) put too much on the left thumb.
`kanata.kbd` has the full map and the timing in its header.

Only `/dev/input/by-path/platform-i8042-serio-0-event-kbd` (the built-in keyboard) is
grabbed. External keyboards do their layout in firmware and never pass through kanata.

## The bottom row = the Planck thumbs

| Laptop key | Planck thumb | Tap | Hold |
|---|---|---|---|
| left Super | left outer | Backspace | Backspace (repeats) |
| left Alt | left inner | one-shot SYM | SYM (J-Ctrl held: Ctrl+Tab) |
| Space | middle, both thumbs | Space | MOV |
| right Alt | right inner | Esc | NUM |
| Copilot key** | right outer | Enter | — |
| leftmost (Fn)* | left pinky, bottom corner | MOUSE on / off | MOUSE while held |

**Caps Lock = Esc, and the Esc key = Caps Lock.** Right Ctrl stays Ctrl.

Super alone is on the home row (A, ;). Inside SYM the left Super key is Super, as on the Planck.

MOUSE: tap the leftmost key = on, tap it again = off (two quick taps = back where you were).
Hold it, or hold **left Shift**, = MOUSE only while held: move with J K L ;, click with Space
(or S D F). Left Shift has no tap action, so the cursor moves at once. The Shift keys are D and
K (home-row mods); right Shift stays a plain Shift.

MOV (arrows on U I O P, Home/End/PgUp/PgDn, niri workspaces) is only while Space is held. There is
no MOV toggle any more: Caps Lock, which toggled it, is Esc now.

Reach ADJ (F1–F12) with SYM + right Alt, or NUM + left Alt.

\* The ThinkPad firmware owns Fn; it sends no key code. BIOS setting **FnCtrlKeySwap = Enable**
(set 8 Oct 2026 through think-lmi, no BIOS password) makes it send Left Ctrl, and the Ctrl key
becomes Fn. It takes effect after a reboot. Check or undo it from Linux:

```bash
sudo cat /sys/class/firmware-attributes/thinklmi/attributes/FnCtrlKeySwap/current_value
echo Disable | sudo tee /sys/class/firmware-attributes/thinklmi/attributes/FnCtrlKeySwap/current_value   # then reboot
```

\*\* The Copilot key (P14s Gen 6, right of right Alt) has no key code of its own: firmware sends
Left Super + Left Shift + F23. Left Super is the Backspace thumb, so the three keys are a v1 chord
(`defchords cop`, 40 ms) = Enter, with no Backspace and no Shift. A second group (`copsym`) does
the same inside SYM. Held mods still apply: F-Ctrl + Copilot = Ctrl+Enter, K-Shift + Copilot =
Shift+Enter. The cost: left Super and left Shift wait up to 40 ms (less when you let go or press
another key) before they act. The BIOS has no Copilot option. Not `defchordsv2`: it needs
`concurrent-tap-hold yes`, and that broke the home-row mods (F-Ctrl + right Alt gave "f" + Esc).

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
sudo python3 ~/.config/kanata/hrm-harness.py ~/.config/kanata/kanata.kbd   # 55 cases
sudo systemctl disable --now kanata-laptop  # turn it off
journalctl -u kanata-laptop
```

**Emergency exit:** hold Left Ctrl + Space + Esc, as kanata sees them: after the Fn/Ctrl swap
that is the leftmost key + Space + the Esc key in the top-left corner. kanata exits 0 and
stays off until `sudo systemctl restart kanata-laptop`. The leftmost key is MOUSE, so Space
clicks the left button on the way.

The unit in `/etc/systemd/system/` is a **copy**; `install.sh` warns when it differs. After you edit it:
`sudo install -m644 ~/dotfiles/kanata-pkg/systemd/kanata-laptop.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart kanata-laptop`.

Install from scratch (p14s only — p340 has no built-in keyboard): `pikaur -S kanata-bin`, then
`./install.sh` in `~/dotfiles`. It stows `kanata-pkg` only where kanata is installed and prints
the one root command for the unit. Then set FnCtrlKeySwap as above.

## Known limits

- **No Polish letters** on this laptop: the `pl` xkb layout is gone (right Alt is a thumb key).
- **Ctrl/Shift + mouse click:** the touchpad and the TrackPoint are other devices, so kanata does not
  see the click. For an instant Shift+click use the plain right Shift (left Shift is MOUSE). A held `F` becomes Ctrl only when its 180 ms term ends. Hold the key a moment
  before you click.
- **Emacs `fs` chord:** release `f` first and you get `fs`. Release `s` first and you get `C-s`.
  QMK PERMISSIVE_HOLD and ZMK `balanced` do the same.
- **No bilateral filter**, like the TOTEM and like the QMK boards in practice (their Achordion
  `achordion_chord` falls through to `return true` for every home-row key). If same-hand misfires
  start, kanata 1.12 has `defhands` + `tap-hold-opposite-hand-release` — the Achordion equivalent.
- **kanata idle bug (worked around):** kanata 1.12 stops ticking when the last *output* key is old,
  so after a key that outputs nothing (left Shift, a MOUSE toggle, the Copilot chord) the
  `require-prior-idle` history froze and the next A/S/F/J/L/; hold typed its letter, however long
  you waited. `@tick` holds an empty virtual key for 200 ms on those keys to keep kanata ticking.
  Any new key that outputs nothing needs `@tick` too. The harness has a case for each.
