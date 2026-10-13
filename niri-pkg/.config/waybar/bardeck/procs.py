"""The system panel's busiest processes, and what may be done to them: term, kill,
nice, and a closer look.

Only this user's own processes take actions. PID 1, kernel threads, other users'
processes and bardeck itself are listed dimmed, with none. A signal is one
os.kill, on the main loop; before it the process's start time is read again, so a
PID that died and came back as another process since the last scan is left alone.

Nice: Linux keeps a nice value per THREAD, and setpriority(PRIO_PROCESS, pid) (what
`renice -p` does) moves only the main one; so every thread in /proc/<pid>/task is
moved. Raising nice is always allowed for one's own processes; lowering it needs
root or RLIMIT_NICE (`ulimit -e`, 0 on this machine), so "nice 0" is offered only
when the limit allows it.
"""

from __future__ import annotations

import os
import pwd
import resource
import signal
import time

from . import core

PF_KTHREAD = 0x00200000  # /proc/<pid>/stat flags: a kernel thread
NICE_TO = 10


class Proc:
    """One row: a process and its number (CPU % of one core, or RSS bytes)."""

    __slots__ = ("pid", "name", "value", "uid", "nice", "threads", "kthread", "start")

    def __init__(self, pid: int, name: str, value: float, nice: int, threads: int, kthread: bool, start: int):
        self.pid, self.name, self.value = pid, name, value
        self.nice, self.threads, self.kthread, self.start = nice, threads, kthread, start
        try:
            self.uid = os.stat(f"/proc/{pid}").st_uid
        except OSError:
            self.uid = -1


def stat_fields(pid: int) -> tuple[str, list[str]] | None:
    """(comm, the fields after it) of /proc/<pid>/stat; field n of proc(5) is [n - 3]."""
    raw = core.read(f"/proc/{pid}/stat")
    if not raw:
        return None
    return raw[raw.find("(") + 1:raw.rfind(")")], raw[raw.rfind(")") + 2:].split()


_USERS: dict[int, str] = {}


def user(uid: int) -> str:
    if uid not in _USERS:
        try:
            _USERS[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _USERS[uid] = str(uid)
    return _USERS[uid]


def blocked(p: Proc) -> str:
    """Why p takes no actions: "" when it does."""
    if p.pid == 1:
        return "init"
    if p.kthread:
        return "kernel"
    if p.pid == os.getpid():
        return "the bar"
    if p.uid != os.getuid():
        return user(p.uid) if p.uid >= 0 else "gone"
    return ""


def may_lower_to(n: int) -> bool:
    if os.geteuid() == 0:
        return True
    soft = resource.getrlimit(resource.RLIMIT_NICE)[0]
    return soft == resource.RLIM_INFINITY or 20 - n <= soft


def nice_target(p: Proc) -> int | None:
    """What the nice chip sets p to: NICE_TO, or back to 0 when that is allowed; None = no chip."""
    if p.nice < NICE_TO:
        return NICE_TO
    if p.nice > 0 and may_lower_to(0):
        return 0
    return None


class Procs:
    """The actions, and their outcome per PID for the rows (`status`)."""

    def __init__(self):
        self.status: dict[int, tuple[str, str]] = {}  # pid -> (tone, words)
        self.killing = 0  # a PID whose kill chip asks to be clicked again

    def settle(self) -> None:
        """A new opening: forget the outcomes."""
        self.status.clear()
        self.killing = 0

    def same(self, p: Proc) -> bool:
        """p's PID still names the process the scan saw."""
        got = stat_fields(p.pid)
        return got is not None and int(got[1][19]) == p.start

    def refresh(self) -> None:
        """A signalled process that exited since: "gone"."""
        for pid, (_tone, words) in list(self.status.items()):
            if words in ("sent TERM", "killed") and not os.path.exists(f"/proc/{pid}"):
                self.status[pid] = ("dim", "gone")

    def send(self, p: Proc, sig: int) -> None:
        if blocked(p):
            return
        if not self.same(p):
            self.status[p.pid] = ("dim", "gone")
            return
        try:
            os.kill(p.pid, sig)
            self.status[p.pid] = ("warn" if sig == signal.SIGTERM else "hit",
                                  "sent TERM" if sig == signal.SIGTERM else "killed")
        except ProcessLookupError:
            self.status[p.pid] = ("dim", "gone")
        except PermissionError:
            self.status[p.pid] = ("hit", "denied")

    def term(self, p: Proc) -> bool:
        self.killing = 0
        self.send(p, signal.SIGTERM)
        return False

    def kill(self, p: Proc) -> bool:
        """The first click arms it (the chip turns red), the second sends SIGKILL."""
        if self.killing != p.pid:
            self.killing = p.pid
            return False
        self.killing = 0
        self.send(p, signal.SIGKILL)
        return False

    def renice(self, p: Proc) -> bool:
        self.killing = 0
        target = nice_target(p)
        if target is None or blocked(p):
            return False
        if not self.same(p):
            self.status[p.pid] = ("dim", "gone")
            return False
        moved = 0
        try:
            tids = os.listdir(f"/proc/{p.pid}/task")
        except OSError:
            tids = []
        for tid in tids:
            try:
                os.setpriority(os.PRIO_PROCESS, int(tid), target)
                moved += 1
            except ProcessLookupError:  # a thread that just ended
                continue
            except PermissionError:
                self.status[p.pid] = ("hit", "denied")
                return False
        if moved:
            p.nice = target  # the next scan reads it back
            self.status[p.pid] = ("aqua", f"nice {target}")
        else:
            self.status[p.pid] = ("dim", "gone")
        return False


def info(pid: int) -> dict | None:
    """What the info block shows: full command line, user, start, RSS, threads, cwd."""
    got = stat_fields(pid)
    if got is None:
        return None
    comm, f = got
    status = {}
    for line in core.read(f"/proc/{pid}/status").splitlines():
        k, _, v = line.partition(":")
        status[k] = v.strip()
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmd = fh.read().rstrip(b"\0").replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        cmd = ""
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        cwd = "?"  # another user's: not readable
    ticks = os.sysconf("SC_CLK_TCK")
    uptime = float(core.read("/proc/uptime", "0").split()[0])
    age = max(0.0, uptime - int(f[19]) / ticks)
    try:
        uid = int(status.get("Uid", "-1").split()[0])
    except (ValueError, IndexError):
        uid = -1
    rss_kb = status.get("VmRSS", "0 kB").split()[0]
    return {
        "comm": comm, "cmd": cmd or f"[{comm}]", "user": user(uid) if uid >= 0 else "?",
        "started": time.strftime("%H:%M" if age < 86400 else "%d %b %H:%M", time.localtime(time.time() - age)),
        "age": age, "rss": int(rss_kb) * 1024 if rss_kb.isdigit() else 0,
        "threads": status.get("Threads", "?"), "nice": int(f[16]), "cwd": cwd, "state": f[0],
    }
