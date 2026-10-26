"""Drive a test kanata with a fake keyboard and read what it outputs.

The kanata output device is grabbed (EVIOCGRAB) before any key is injected,
so nothing reaches the compositor. Abort if the grab fails.
Run as root: python3 hrm-harness.py <kanata.kbd>
"""
import re
import subprocess
import sys
import time

import evdev
from evdev import UInput, ecodes as e

cfg_src = open(sys.argv[1]).read()
src = UInput({e.EV_KEY: list(range(1, 250))}, name="hrm-test-src")
time.sleep(0.5)
src_path = src.device.path
cfg = re.sub(r"linux-dev \S+", f"linux-dev {src_path}", cfg_src)
cfg_path = "/tmp/hrm-test.kbd"
open(cfg_path, "w").write(cfg)

before = set(evdev.list_devices())
kan = subprocess.Popen(["kanata", "-n", "-c", cfg_path], stdout=subprocess.DEVNULL, stderr=open("/tmp/hrm-test-kanata.log", "w"))
out = None
for _ in range(100):
    time.sleep(0.05)
    for p in set(evdev.list_devices()) - before:
        d = evdev.InputDevice(p)
        if d.name.startswith("kanata"):
            out = d
    if out:
        break
if not out:
    kan.kill(); sys.exit("no kanata output device")
out.grab()  # raises if it fails -> nothing injected
time.sleep(1.0)
while out.read_one():  # drain
    pass

SPECIAL = {";": "SEMICOLON", "lctl": "LEFTCTRL", "lmet": "LEFTMETA", "lalt": "LEFTALT",
           "ralt": "RIGHTALT", "spc": "SPACE", "caps": "CAPSLOCK", "esc": "ESC"}


class Keys(dict):
    def __missing__(self, name):
        return getattr(e, "KEY_" + SPECIAL.get(name, name.upper()))


K = Keys()


def ev(key, val, wait_ms):
    src.write(e.EV_KEY, K[key], val); src.syn()
    time.sleep(wait_ms / 1000)


def collect():
    time.sleep(0.4)
    seq = []
    while (x := out.read_one()) is not None:
        if x.type == e.EV_KEY and x.value in (0, 1):
            name = e.bytype[e.EV_KEY][x.code]
            name = name if isinstance(name, str) else name[0]
            seq.append(("+" if x.value else "-") + name.replace("KEY_", "").replace("BTN_", "btn_").lower())
    return " ".join(seq)


def case(title, steps, expect):
    time.sleep(0.4)  # idle, so prior-idle does not leak between cases
    for key, val, wait in steps:
        ev(key, val, wait)
    got = collect()
    ok = got == expect
    print(f"{'PASS' if ok else 'FAIL'}  {title}\n      got:    {got}\n      expect: {expect}")
    return ok


MODS = {"leftshift", "rightshift", "leftctrl", "rightctrl", "leftalt", "rightalt", "leftmeta", "rightmeta"}


def typed(seq):
    """Replay the output: return [(key, mods held at its press)] for non-modifier presses."""
    held, out = set(), []
    for tok in seq.split():
        sign, name = tok[0], tok[1:]
        if name in MODS:
            (held.add if sign == "+" else held.discard)(name)
        elif sign == "+":
            out.append((name, frozenset(held)))
    return out


def case_typed(title, steps, expect):
    """Like case(), but compares what was TYPED (key + mods held), not the raw event order."""
    time.sleep(0.4)
    for key, val, wait in steps:
        ev(key, val, wait)
    raw = collect()
    got = [(k, sorted(m)) for k, m in typed(raw)]
    want = [(k, sorted(m)) for k, m in expect]
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {title}\n      raw:    {raw}\n      typed:  {got}")
    return ok


COPILOT = [("lmet", 1, 3), ("leftshift", 1, 3), ("f23", 1, 60), ("f23", 0, 3), ("leftshift", 0, 3), ("lmet", 0, 0)]
COPILOT_AT_ONCE = [("lmet", 1, 1), ("leftshift", 1, 1), ("f23", 1, 1), ("f23", 0, 1), ("leftshift", 0, 1), ("lmet", 0, 0)]

def tap(k, gap=60):
    return [(k, 1, 40), (k, 0, gap)]


results = [
    case("tap a", [("a", 1, 50), ("a", 0, 0)], "+a -a"),
    case("hold f past term, tap x = Ctrl+x",
         [("f", 1, 250), ("x", 1, 30), ("x", 0, 30), ("f", 0, 0)],
         "+leftctrl +x -x -leftctrl"),
    case("permissive: f down, x tapped inside term = Ctrl+x",
         [("f", 1, 30), ("x", 1, 30), ("x", 0, 30), ("f", 0, 0)],
         "+leftctrl +x -x -leftctrl"),
    case("roll a->s (a released first) = 'as'",
         [("a", 1, 40), ("s", 1, 40), ("a", 0, 40), ("s", 0, 0)],
         "+a +s -a -s"),
    case("mid-word capital: x, then d nested over i = 'xI'",
         [("x", 1, 30), ("x", 0, 30), ("d", 1, 40), ("i", 1, 30), ("i", 0, 30), ("d", 0, 0)],
         "+x -x +leftshift +i -i -leftshift"),
    case("roll d->i = 'di'",
         [("d", 1, 40), ("i", 1, 40), ("d", 0, 40), ("i", 0, 0)],
         "+d +i -d -i"),
    case("prior-idle: x then j nested over k fast = 'xjk' (no Ctrl)",
         [("x", 1, 30), ("x", 0, 30), ("j", 1, 30), ("q", 1, 30), ("q", 0, 30), ("j", 0, 0)],
         "+x -x +j +q -q -j"),
    case("quick-tap: tap a, re-press and hold = held 'a', no Super",
         [("a", 1, 50), ("a", 0, 60), ("a", 1, 400), ("a", 0, 0)],
         "+a -a +a -a"),
    case("hold ; past term + tap j... j as letter = Super+j",
         [(";", 1, 250), ("q", 1, 30), ("q", 0, 30), (";", 0, 0)],
         "+rightmeta +q -q -rightmeta"),
    case("l hold = LEFT alt (not AltGr)",
         [("l", 1, 250), ("x", 1, 30), ("x", 0, 30), ("l", 0, 0)],
         "+leftalt +x -x -leftalt"),
    case("emacs fs chord, f released first = 'fs'",
         [("f", 1, 25), ("s", 1, 40), ("f", 0, 20), ("s", 0, 0)],
         "+f +s -f -s"),
    case("emacs fs chord, s released first = Ctrl+s (same as QMK/ZMK permissive hold)",
         [("f", 1, 25), ("s", 1, 40), ("s", 0, 20), ("f", 0, 0)],
         "+leftctrl +s -s -leftctrl"),
    case("unmapped key passes through", [("q", 1, 30), ("q", 0, 0)], "+q -q"),
    # --- Caps / Esc ---
    case("Caps = Esc", [("caps", 1, 40), ("caps", 0, 0)], "+esc -esc"),
    case("Esc = Caps Lock", [("esc", 1, 40), ("esc", 0, 0)], "+capslock -capslock"),
    # --- thumbs ---
    case("left outer thumb (left Super) = Backspace", [("lmet", 1, 40), ("lmet", 0, 0)], "+backspace -backspace"),
    case("left Super held = Backspace held (repeats)",
         [("lmet", 1, 400), ("lmet", 0, 0)], "+backspace -backspace"),
    case("roll Backspace -> x (x down before Backspace up) = Backspace, x",
         [("lmet", 1, 40), ("x", 1, 40), ("lmet", 0, 40), ("x", 0, 0)], "+backspace +x -backspace -x"),
    case("Backspace held, x tapped inside 200 ms = Backspace, x",
         [("lmet", 1, 40), ("x", 1, 30), ("x", 0, 30), ("lmet", 0, 0)], "+backspace +x -x -backspace"),
    case("left Shift held = MOUSE at once: f = left click, Space = left click; released: f = f",
         [("leftshift", 1, 20), ("f", 1, 30), ("f", 0, 30), ("spc", 1, 30), ("spc", 0, 30), ("leftshift", 0, 60),
          ("f", 1, 30), ("f", 0, 0)],
         "+btn_left -btn_left +btn_left -btn_left +f -f"),
    case("left Shift tapped alone = nothing (no Shift sent)",
         [("leftshift", 1, 40), ("leftshift", 0, 60), ("x", 1, 30), ("x", 0, 0)], "+x -x"),
    case("leftmost tap = MOUSE on: f = click, Space = click; tap again: f = f",
         [("lctl", 1, 40), ("lctl", 0, 60), ("f", 1, 30), ("f", 0, 40), ("spc", 1, 30), ("spc", 0, 40),
          ("lctl", 1, 40), ("lctl", 0, 60), ("f", 1, 30), ("f", 0, 0)],
         "+btn_left -btn_left +btn_left -btn_left +f -f"),
    case("leftmost tapped twice = base again",
         tap("lctl") * 2 + [("f", 1, 30), ("f", 0, 0)], "+f -f"),
    case("leftmost held = MOUSE while held: f = click; released: f = f",
         [("lctl", 1, 250), ("f", 1, 30), ("f", 0, 30), ("lctl", 0, 60), ("f", 1, 30), ("f", 0, 0)],
         "+btn_left -btn_left +f -f"),
    case_typed("Copilot key (Super+Shift+F23) = plain Enter, no Backspace", COPILOT, [("enter", [])]),
    case_typed("Copilot key, whole sequence at once = plain Enter", COPILOT_AT_ONCE, [("enter", [])]),
    case_typed("Copilot then d = Enter, d",
               COPILOT + [("d", 1, 30), ("d", 0, 0)], [("enter", []), ("d", [])]),
    case_typed("Copilot twice = Enter, Enter",
               COPILOT + COPILOT, [("enter", []), ("enter", [])]),
    case_typed("F-Ctrl held + Copilot = Ctrl+Enter",
               [("f", 1, 250)] + COPILOT + [("f", 0, 0)], [("enter", ["leftctrl"])]),
    case_typed("K-Shift held + Copilot = Shift+Enter",
               [("k", 1, 250)] + COPILOT + [("k", 0, 0)], [("enter", ["rightshift"])]),
    case("right Alt tap = Esc", [("ralt", 1, 40), ("ralt", 0, 0)], "+esc -esc"),
    case("Space tap = space", [("spc", 1, 40), ("spc", 0, 0)], "+space -space"),
    case("Space held past 220: u i o p = arrows",
         [("spc", 1, 260), ("u", 1, 30), ("u", 0, 30), ("p", 1, 30), ("p", 0, 30), ("spc", 0, 0)],
         "+left -left +right -right"),
    case("Space held (MOV): left Super = Backspace, n = Super+n",
         [("spc", 1, 260), ("lmet", 1, 30), ("lmet", 0, 30), ("n", 1, 30), ("n", 0, 30), ("spc", 0, 0)],
         "+backspace -backspace +leftmeta +n -leftmeta -n"),
    case("roll Space -> a = ' a' (no MOV)",
         [("spc", 1, 40), ("a", 1, 40), ("spc", 0, 40), ("a", 0, 0)], "+space +a -space -a"),
    # --- SYM ---
    case("left Alt tap = one-shot SYM: d -> '-', then d is d again",
         [("lalt", 1, 40), ("lalt", 0, 40), ("d", 1, 40), ("d", 0, 250), ("d", 1, 40), ("d", 0, 0)],
         "+minus -minus +d -d"),
    case("SYM held: q w = ! @ (shifted 1 2)",
         [("lalt", 1, 40), ("q", 1, 30), ("q", 0, 30), ("w", 1, 30), ("w", 0, 30), ("lalt", 0, 0)],
         "+leftshift +1 -leftshift -1 +leftshift +2 -leftshift -2"),  # shift is down at each press = "!@"
    case_typed("SYM held: a k = ? + (Shift+/ and Shift+=)",
               [("lalt", 1, 40)] + tap("a", 30) + tap("k", 30) + [("lalt", 0, 0)],
               [("slash", ["leftshift"]), ("equal", ["leftshift"])]),
    case_typed("one-shot SYM: a = ?, then a = a",
               tap("lalt") + tap("a", 300) + tap("a", 0), [("slash", ["leftshift"]), ("a", [])]),
    case("J-Ctrl held + left Alt = Ctrl+Tab",
         [("j", 1, 250), ("lalt", 1, 40), ("lalt", 0, 40), ("j", 0, 0)],
         "+rightctrl +tab -tab -rightctrl"),
    case_typed("J-Ctrl held + left Alt tapped 3x = Ctrl+Tab 3x, Ctrl kept (cycles tabs)",
               [("j", 1, 250)] + [("lalt", 1, 40), ("lalt", 0, 60)] * 3 + [("j", 0, 0)],
               [("tab", ["rightctrl"])] * 3),
    case_typed("J-Ctrl + K-Shift held + left Alt = Ctrl+Shift+Tab",
               [("j", 1, 250), ("k", 1, 250), ("lalt", 1, 40), ("lalt", 0, 40), ("k", 0, 30), ("j", 0, 0)],
               [("tab", ["rightctrl", "rightshift"])]),
    case_typed("left Alt tapped twice, then d = Tab, d (SYM ends with the Tab)",
               [("lalt", 1, 40), ("lalt", 0, 60), ("lalt", 1, 40), ("lalt", 0, 100), ("d", 1, 30), ("d", 0, 0)],
               [("tab", []), ("d", [])]),
    case("left Alt tapped, then pressed and held = Tab held down",
         [("lalt", 1, 40), ("lalt", 0, 60), ("lalt", 1, 400), ("lalt", 0, 0)],
         "+tab -tab"),
    case("one-shot SYM, roll d->n (n down before d up) = '->' (SYM ends on the release)",
         [("lalt", 1, 40), ("lalt", 0, 60), ("d", 1, 40), ("n", 1, 40), ("d", 0, 40), ("n", 0, 0)],
         "+minus +leftshift +dot -minus -leftshift -dot"),
    case("F-Ctrl held + left Alt opens SYM: j -> Ctrl+=",
         [("f", 1, 250), ("lalt", 1, 40), ("lalt", 0, 40), ("j", 1, 30), ("j", 0, 30), ("f", 0, 0)],
         "+leftctrl +equal -equal -leftctrl"),
    case_typed("one-shot SYM, then Copilot = plain Enter (no Super)",
               tap("lalt") + COPILOT, [("enter", [])]),
    case("SYM held: left Super = Super (Planck: LGUI under SYM)",
         [("lalt", 1, 40), ("lmet", 1, 30), ("q", 1, 30), ("q", 0, 30), ("lmet", 0, 30), ("lalt", 0, 0)],
         "+leftmeta +leftshift +1 -leftshift -1 -leftmeta"),
    # --- NUM / ADJ ---
    case("right Alt held: q = 1, f = left click",
         [("ralt", 1, 230), ("q", 1, 30), ("q", 0, 30), ("f", 1, 30), ("f", 0, 30), ("ralt", 0, 0)],
         "+1 -1 +btn_left -btn_left"),
    case("right Alt held: left Super = Delete",
         [("ralt", 1, 230), ("lmet", 1, 30), ("lmet", 0, 30), ("ralt", 0, 0)],
         "+delete -delete"),
    case("SYM held + right Alt held = ADJ: a = F1, z = F7",
         [("lalt", 1, 40), ("ralt", 1, 40), ("a", 1, 30), ("a", 0, 30), ("z", 1, 30), ("z", 0, 30),
          ("ralt", 0, 30), ("lalt", 0, 0)],
         "+f1 -f1 +f7 -f7"),
    case("NUM held + left Alt held = ADJ: a = F1",
         [("ralt", 1, 230), ("lalt", 1, 40), ("a", 1, 30), ("a", 0, 30), ("lalt", 0, 30), ("ralt", 0, 0)],
         "+f1 -f1"),
    # --- a key that outputs nothing must not stall require-prior-idle (F would type "f") ---
    # (the 400 ms pause is past the 120 ms prior-idle, so F must be a hold)
    case_typed("left Shift tapped, 400 ms, then F held + x = Ctrl+x",
               tap("leftshift", 400) + [("f", 1, 250)] + tap("x", 30) + [("f", 0, 0)], [("x", ["leftctrl"])]),
    case_typed("leftmost tapped twice, 400 ms, then F held + x = Ctrl+x",
               tap("lctl") + tap("lctl", 400) + [("f", 1, 250)] + tap("x", 30) + [("f", 0, 0)], [("x", ["leftctrl"])]),
    case_typed("Copilot, 400 ms, then A held + x = Super+x",
               COPILOT + [("f24", 0, 400), ("a", 1, 250)] + tap("x", 30) + [("a", 0, 0)], [("enter", []), ("x", ["leftmeta"])]),
]

out.ungrab()
kan.terminate(); kan.wait(timeout=5)
src.close()
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
