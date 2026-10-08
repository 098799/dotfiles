"""Drive a test kanata with a fake keyboard and read what it outputs.

The kanata output device is grabbed (EVIOCGRAB) before any key is injected,
so nothing reaches the compositor. Abort if the grab fails.
Run as root: python3 hrm_harness.py <kanata.kbd>
"""
import re
import subprocess
import sys
import time

import evdev
from evdev import UInput, ecodes as e

cfg_src = open(sys.argv[1]).read()
src = UInput({e.EV_KEY: list(range(1, 120))}, name="hrm-test-src")
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

K = {c: getattr(e, "KEY_" + c.upper()) for c in "asdfjklqxi"}
K[";"] = e.KEY_SEMICOLON


def ev(key, val, wait_ms):
    src.write(e.EV_KEY, K[key], val); src.syn()
    time.sleep(wait_ms / 1000)


def collect():
    time.sleep(0.4)
    seq = []
    while (x := out.read_one()) is not None:
        if x.type == e.EV_KEY and x.value in (0, 1):
            name = e.KEY[x.code]
            name = name if isinstance(name, str) else name[0]
            seq.append(("+" if x.value else "-") + name.replace("KEY_", "").lower())
    return " ".join(seq)


def case(title, steps, expect):
    time.sleep(0.4)  # idle, so prior-idle does not leak between cases
    for key, val, wait in steps:
        ev(key, val, wait)
    got = collect()
    ok = got == expect
    print(f"{'PASS' if ok else 'FAIL'}  {title}\n      got:    {got}\n      expect: {expect}")
    return ok


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
]

out.ungrab()
kan.terminate(); kan.wait(timeout=5)
src.close()
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
