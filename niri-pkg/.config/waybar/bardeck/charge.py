"""The laptop battery's charge limit and the keyboard light, for the power panel.

Charge limit: TLP owns it. A limit chip rewrites DROPIN (the file the w95 System
Monitor's "Power" panel writes too, so the two agree) and applies it now with
`tlp setcharge START STOP BAT0`; without the file TLP would put its old limit back
at the next boot. "full once" is `tlp setcharge 95 100` with no file: TLP calls
that temporary, until the next boot or `tlp setcharge` with no thresholds, which
is what "back to N%" runs. (Not `tlp fullcharge`: it refuses on battery.) Both need root: `sudo -n`, on a thread (tlp takes about a second).

The limit the firmware uses is read from sysfs (charge_control_end_threshold),
the one TLP restores from DROPIN. When they differ, a full charge is on.

Keyboard light: /sys/class/leds/*kbd_backlight (the ThinkPad's: 0..2), set with
brightnessctl, which needs no root (logind)."""

from __future__ import annotations

import glob
import os
import re
import shlex
import subprocess
import threading

from . import core

DROPIN = "/etc/tlp.d/95-w95-charge-limit.conf"
LIMITS = (60, 80, 100)  # the stop thresholds offered; each starts 5 below
HEADER = (
    "# Battery charge limit -- rewritten by the w95 System Monitor \"Power\" panel\n"
    "# and by the niri bar's power panel (bardeck/charge.py).\n"
    "# Edit by hand if you like; both only ever replace this whole file.\n"
)
KBD_NAMES = {2: ("off", "low", "high")}  # max_brightness -> a word per level


class Charge:
    def __init__(self):
        self.status: tuple[str, str] | None = None  # (tone, words) of the last change
        self._busy = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def bat(self) -> str:
        found = sorted(glob.glob("/sys/class/power_supply/BAT*"))
        return found[0] if found else ""

    def stop(self) -> int | None:
        """The stop threshold the firmware uses now; None: no knob."""
        try:
            return int(core.read(f"{self.bat()}/charge_control_end_threshold", ""))
        except ValueError:
            return None

    def saved(self) -> int | None:
        """The stop threshold in DROPIN, which TLP restores at boot."""
        m = re.search(r"^STOP_CHARGE_THRESH_\w+=(\d+)", core.read(DROPIN), re.M)
        return int(m.group(1)) if m else None

    def set_limit(self, stop: int) -> None:
        name = os.path.basename(self.bat()) or "BAT0"
        start = stop - 5
        body = f"{HEADER}START_CHARGE_THRESH_{name}={start}\nSTOP_CHARGE_THRESH_{name}={stop}\n"
        self._run(f"printf '%s' {shlex.quote(body)} | sudo -n tee {DROPIN} >/dev/null"
                  f" && sudo -n tlp setcharge {start} {stop} {name}", f"limit {stop}%")

    def full_once(self) -> None:
        name = os.path.basename(self.bat()) or "BAT0"
        self._run(f"sudo -n tlp setcharge 95 100 {name}", "full charge")

    def restore(self) -> None:
        name = os.path.basename(self.bat()) or "BAT0"
        self._run(f"sudo -n tlp setcharge {name}", "back to the limit")

    def _run(self, cmd: str, words: str) -> None:
        if not self._busy.acquire(blocking=False):
            return
        self.status = ("warn", words + "…")

        def body():
            try:
                r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=30,
                                   stdin=subprocess.DEVNULL)
                if r.returncode == 0:
                    self.status = None
                else:
                    err = (r.stderr or r.stdout).strip().splitlines()
                    self.status = ("hit", (err[-1] if err else f"failed (exit {r.returncode})")[:60])
                    core.log(f"charge {words}: {(r.stderr or r.stdout).strip()[:200]}")
            except Exception as err:
                self.status = ("hit", "failed")
                core.log(f"charge {words}: {err!r}")
            finally:
                self._busy.release()

        threading.Thread(target=body, daemon=True).start()


# ── the keyboard light ───────────────────────────────────────────────────────


def kbd_dir() -> str:
    found = sorted(glob.glob("/sys/class/leds/*kbd_backlight"))
    return found[0] if found else ""


def kbd() -> tuple[int, int] | None:
    """(level, max), or None: no keyboard light."""
    d = kbd_dir()
    try:
        cur, top = int(core.read(f"{d}/brightness", "")), int(core.read(f"{d}/max_brightness", ""))
    except ValueError:
        return None
    return (cur, top) if d and top > 0 else None


def kbd_levels(top: int) -> list[tuple[int, str]]:
    names = KBD_NAMES.get(top)
    if names:
        return list(enumerate(names))
    return [(round(top * p / 100), f"{p}%") for p in (0, 33, 66, 100)]


def set_kbd(level: int) -> None:
    subprocess.Popen(["brightnessctl", f"--device={os.path.basename(kbd_dir())}", "--quiet", "set", str(level)],
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
