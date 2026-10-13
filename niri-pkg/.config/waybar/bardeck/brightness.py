"""Brightness of each screen, for the displays panel.

The laptop (an eDP output): the kernel's backlight. Read from /sys/class/backlight
in-process (two small files), set with `brightnessctl --class=backlight` (the
brightness keys use it too, so the two agree). It never goes below MIN_LAPTOP:
at 0 the panel goes black.

An external screen: DDC/CI, VCP feature 0x10 (luminance), with `ddcutil`. Each call
takes 50–500 ms, so all of them run on one worker thread and the panel only draws
what it last stored. `ddcutil detect` maps a niri output (its DRM connector, e.g.
DP-1) to an I²C bus once per set of connected outputs; then each read or write
names that bus (`--bus N`), which skips the probe of every bus. The value is read
when the panel asks for it and again after READ_EVERY (the monitor's own buttons
change it too). A set is optimistic: the new level shows at once, and while the
pointer or the wheel sends many, only the last one waiting is sent.

The i2c-dev devices need the ddcutil package's udev rule (60-ddcutil-i2c.rules:
uaccess on a video adapter's bus) and the i2c_dev module."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import threading
import time

from . import core

MIN_LAPTOP = 1     # %
STEP = 5           # % for the wheel and the keys
READ_EVERY = 10.0  # s between reads of an external screen while the panel is open
TIMEOUT = 8        # s for one ddcutil call


def laptop(name: str) -> bool:
    return name.startswith("eDP")


def backlight_dir() -> str:
    found = sorted(glob.glob("/sys/class/backlight/*"))
    return found[0] if found else ""


def parse_detect(out: str) -> dict[str, int]:
    """`ddcutil detect` -> {connector: bus} for the displays that answer DDC/CI. An
    "Invalid display" block (a laptop panel, a screen with DDC/CI off) is left out."""
    buses = {}
    for block in re.split(r"\n(?=\S)", out):
        if not block.startswith("Display"):
            continue
        bus = re.search(r"I2C bus:\s+/dev/i2c-(\d+)", block)
        conn = re.search(r"DRM[ _]connector:\s+card\d+-(\S+)", block)
        if bus and conn:
            buses[conn.group(1)] = int(bus.group(1))
    return buses


def parse_vcp(out: str) -> tuple[int, int] | None:
    """`ddcutil getvcp 10 --brief` ("VCP 10 C 50 100") -> (current, max)."""
    m = re.search(r"VCP\s+10\s+C\s+(\d+)\s+(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m and int(m.group(2)) > 0 else None


class Brightness:
    def __init__(self):
        self.level: dict[str, int] = {}     # output -> % (external: the last read or set)
        self.why: dict[str, str] = {}       # output -> why it has none
        self.maxes: dict[str, int] = {}     # output -> the monitor's VCP 0x10 maximum
        self.buses: dict[str, int] = {}     # connector -> I²C bus
        self.detected: frozenset[str] | None = None  # the outputs the last detect saw
        self.read_at: dict[str, float] = {}
        self.want: dict[str, int] = {}      # output -> % waiting to be sent
        self.reads: set[str] = set()        # outputs waiting to be read
        self.connected: frozenset[str] = frozenset()
        self.busy = ""                      # the output the worker talks to now
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None

    # -- the panel's side (main loop) ---------------------------------------------

    def get(self, name: str, connected) -> int | None:
        """The output's level in %, or None (see self.why). An external one is read
        on the worker when it is unknown or older than READ_EVERY."""
        if laptop(name):
            return self.read_laptop(name)
        if shutil.which("ddcutil") is None:
            self.why[name] = "ddcutil is not installed"
            return None
        with self._cv:
            self.connected = frozenset(connected)
            stale = time.monotonic() - self.read_at.get(name, -READ_EVERY) >= READ_EVERY
            if stale and name not in self.want:
                self.read_at[name] = time.monotonic()  # once per READ_EVERY, not per draw
                self.reads.add(name)
                self._wake()
        return self.level.get(name)

    def set(self, name: str, pct: int) -> None:
        pct = max(MIN_LAPTOP if laptop(name) else 0, min(100, int(pct)))
        with self._cv:
            self.level[name] = pct
            self.want[name] = pct
            self.reads.discard(name)
            self._wake()

    def step(self, name: str, by: int) -> None:
        cur = self.level.get(name) if not laptop(name) else self.read_laptop(name)
        if cur is not None:
            self.set(name, cur + by)

    def read_laptop(self, name: str) -> int | None:
        if name in self.want or self.busy == name:  # the file may still have the old value
            return self.level.get(name)
        d = backlight_dir()
        try:
            cur = int(core.read(f"{d}/brightness", "-1"))
            top = int(core.read(f"{d}/max_brightness", "0"))
        except ValueError:
            cur, top = -1, 0
        if not d or cur < 0 or top <= 0:
            self.why[name] = "no backlight"
            return None
        self.level[name] = round(cur * 100 / top)
        return self.level[name]

    # -- the worker ---------------------------------------------------------------

    def _wake(self) -> None:
        """Holding self._cv."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="brightness")
            self._thread.start()
        self._cv.notify()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self.want and not self.reads:
                    self._cv.wait()
                if self.want:  # a set before any read
                    name = next(iter(self.want))
                    job = ("set", name, self.want.pop(name))
                else:
                    name = self.reads.pop()
                    job = ("read", name, 0)
                self.busy = name
            try:
                if laptop(name):
                    self._set_laptop(job[2])
                elif job[0] == "set":
                    self._set_ddc(name, job[2])
                else:
                    self._read_ddc(name)
            except Exception as err:
                self.why[name] = "failed"
                core.log(f"brightness {job[0]} {name}: {err!r}")
            finally:
                self.busy = ""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT,
                              env=dict(os.environ, HOME=core.REAL_HOME), stdin=subprocess.DEVNULL)

    def _set_laptop(self, pct: int) -> None:
        self._run("brightnessctl", "--class=backlight", "--quiet", "set", f"{pct}%")

    def _bus(self, name: str) -> int | None:
        if self.detected != self.connected:  # a screen came or went: map the buses again
            r = self._run("ddcutil", "detect")
            self.buses = parse_detect(r.stdout)
            self.detected = self.connected
        bus = self.buses.get(name)
        if bus is None:
            self.why[name] = "no DDC/CI (turn it on in the monitor's menu)"
            self.level.pop(name, None)
        return bus

    def _read_ddc(self, name: str) -> None:
        bus = self._bus(name)
        if bus is None:
            return
        r = self._run("ddcutil", "--bus", str(bus), "getvcp", "10", "--brief")
        got = parse_vcp(r.stdout)
        if got is None:
            self.why[name] = "no answer to DDC/CI"
            self.level.pop(name, None)
            core.log(f"brightness read {name}: {(r.stderr or r.stdout).strip()[:120]}")
            return
        cur, top = got
        self.maxes[name] = top
        with self._cv:
            if name not in self.want:  # a set since: it wins
                self.level[name] = round(cur * 100 / top)
        self.why.pop(name, None)

    def _set_ddc(self, name: str, pct: int) -> None:
        bus = self._bus(name)
        if bus is None:
            return
        if name not in self.maxes:
            self._read_ddc(name)
            if name not in self.maxes:
                return
        value = round(pct * self.maxes[name] / 100)
        r = self._run("ddcutil", "--bus", str(bus), "--noverify", "setvcp", "10", str(value))
        if r.returncode != 0:
            self.why[name] = "the monitor refused it"
            core.log(f"brightness set {name}: {(r.stderr or r.stdout).strip()[:120]}")
            self.read_at[name] = 0.0  # read the true value back on the next draw
