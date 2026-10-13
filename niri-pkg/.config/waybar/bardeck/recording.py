"""A screen recording that runs: niri-record's state file, read cheaply, and the stop
its key binds use.

niri-record <mode> (desktop / window / region; gpu-screen-recorder) writes
$XDG_RUNTIME_DIR/niri-record-<mode>.state: "SELECT" and its own PID while the portal
picker or slurp is up, then "REC" and the recorder's PID; the output path goes to
niri-record-<mode>.out. Running `niri-record <mode>` again stops the recording (or
cancels the picking): the same command the key binds run, so the panel's stop button
runs it too. A check is three stat()s of files that are not there, and a /proc read
when one is: the power strip checks every second.
"""

from __future__ import annotations

import os
import time

from . import core, procs

MODES = ("desktop", "window", "region")
RUNTIME = os.path.dirname(core.RUN_DIR)
SCRIPT = f"{core.REAL_HOME}/bin/niri-record"


class Recording:
    __slots__ = ("mode", "kind", "pid", "started", "out")

    def __init__(self, mode: str, kind: str, pid: int, started: float, out: str):
        self.mode, self.kind, self.pid, self.started, self.out = mode, kind, pid, started, out

    @property
    def picking(self) -> bool:
        return self.kind != "REC"

    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started)

    def stop(self) -> bool:
        core.spawn([SCRIPT if os.path.exists(SCRIPT) else "niri-record", self.mode])
        return False


def current() -> Recording | None:
    """The recording that runs (or whose picker is up), or None."""
    for mode in MODES:
        path = f"{RUNTIME}/niri-record-{mode}.state"
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        lines = core.read(path).splitlines()
        try:
            kind, pid = lines[0], int(lines[1])
        except (IndexError, ValueError):
            continue
        got = procs.stat_fields(pid)
        if got is None:  # a stale file: the script's next run clears it
            continue
        started = mtime
        if kind == "REC":
            # The recorder's own start: the file was written right after it.
            uptime = float(core.read("/proc/uptime", "0").split()[0])
            started = time.time() - (uptime - int(got[1][19]) / os.sysconf("SC_CLK_TCK"))
        out = core.read(f"{RUNTIME}/niri-record-{mode}.out") if kind == "REC" else ""
        return Recording(mode, kind, pid, started, out)
    return None


def clock(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"
