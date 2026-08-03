"""w95stat — the numbers behind the Windows 95 System Monitor.

Two sources, deliberately split:

* **Native sampling** (`/proc`, `/sys`, `pactl`) for anything charted or
  controlled. A chart needs a fresh number every second, and parsing "󰍛 6%"
  back into an integer would be a strange way to get one.

* **The i3blocks scripts themselves** for everything whose logic is the user's
  own and would rot if reimplemented here: which Claude accounts exist and how
  their usage is fetched, which WireGuard conf is "tomek2", how this laptop's
  SSID is spelled, whether `checkupdates` has been cached in the last hour.
  Those are run as-is and their first line is parsed, so the monitor and the
  bar can never disagree.

The dividing line is "would I be copying a decision, or a formula?". Formulas
(percent of a percent, bytes per second) get reimplemented; decisions do not.

Nothing here imports GTK. The slow probes — `bluetoothctl`, `checkupdates`,
`curl` to the Claude API — run on a worker thread and are handed back through a
`dispatch` callable the caller supplies (`GLib.idle_add` in the app), so this
module stays runnable, and testable, from a plain shell:

    python3 w95stat.py        # dump every reading as text
"""

import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HOME = os.path.expanduser("~")

# Where the i3blocks scripts live. The stow symlink first, the repo second, so
# a working tree that hasn't been stowed yet still runs.
SCRIPT_DIRS = [
    os.path.join(HOME, "scripts"),
    os.path.join(HOME, "dotfiles", "i3-pkg", "scripts"),
]


def script_path(name):
    """Absolute path of an i3blocks block script, or None if it isn't there."""
    for directory in SCRIPT_DIRS:
        candidate = os.path.join(directory, name + ".sh")
        if os.access(candidate, os.X_OK):
            return candidate
    return None


# ── text hygiene ────────────────────────────────────────────────────────
# The block scripts speak Nerd Font: their labels carry glyphs from the
# Private Use Areas, which render as tofu in W95FA. Strip those (and any pango
# markup) and what's left is the human-readable half — "Sunrise_3291943",
# "wg1", "MXM3" — which is exactly what this app wants to display.

_PUA = re.compile(
    "[\ue000-\uf8ff"                       # Basic Multilingual Plane PUA
    "\U000f0000-\U000ffffd"                # Supplementary PUA-A (Material Design icons)
    "\U00100000-\U0010fffd]"               # Supplementary PUA-B
)
_MARKUP = re.compile(r"<[^>]+>")
_ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'))


def plain(text):
    """A block's output as prose: no glyphs, no pango, no double spaces."""
    text = _MARKUP.sub("", _PUA.sub("", text or ""))
    for entity, char in _ENTITIES:
        text = text.replace(entity, char)
    return " ".join(text.split())


# ── running the block scripts ───────────────────────────────────────────

def run_block(name, timeout=8, env=None):
    """Run a block script once and return its i3blocks triple.

    i3blocks' protocol is three optional lines: full text, short text, colour.
    Returns ``(full, short, colour)`` with glyphs stripped from the first two,
    or ``(None, None, None)`` if the script is missing, fails, or times out —
    `bluetoothctl` in particular will hang forever if the daemon is wedged, and
    a frozen monitor is worse than a blank field.
    """
    path = script_path(name)
    if not path:
        return (None, None, None)
    environ = dict(os.environ)
    environ.pop("BLOCK_BUTTON", None)
    if env:
        environ.update(env)
    try:
        out = subprocess.run(
            [path], capture_output=True, text=True, timeout=timeout, env=environ,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return (None, None, None)
    out += ["", "", ""]
    return (plain(out[0]), plain(out[1]), out[2].strip() or None)


def block_action(name, button):
    """Fire a block script's click handler, exactly as clicking the bar would.

    Detached and unwaited: several of these open a terminal or a rofi menu and
    would otherwise pin the monitor for as long as the user reads them.
    """
    path = script_path(name)
    if not path:
        return False
    env = dict(os.environ, BLOCK_BUTTON=str(button))
    try:
        subprocess.Popen(
            [path], env=env, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def spawn(argv):
    """Run something and forget about it."""
    try:
        subprocess.Popen(
            argv, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True


def shell(cmdline):
    """Same, for a command line that wants a shell (pipes, redirections)."""
    return spawn(["/bin/bash", "-c", cmdline])


def term(cmdline, hold=True):
    """Open the command in a terminal, the way the block scripts do.

    `hold` keeps the window up after the command exits so output can be read,
    which is what every "show me `df -h`" block does.
    """
    if hold:
        cmdline += "; read -p 'Press enter to close...'"
    return spawn(["alacritty", "-e", "bash", "-c", cmdline])


def _read(path, default=""):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return default


def _run(argv, timeout=4):
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# ── CPU ─────────────────────────────────────────────────────────────────

class CpuMeter:
    """Percent-busy between successive calls.

    Keeps its own previous sample rather than sharing cpu.sh's
    /tmp/.i3blocks_cpu_prev: two readers writing one delta file would each see
    the *other's* interval, so both would report nonsense whenever the bar and
    the monitor happened to tick close together.
    """

    def __init__(self):
        self._prev = None

    @staticmethod
    def _totals():
        fields = _read("/proc/stat").split("\n", 1)[0].split()[1:]
        values = [int(v) for v in fields[:8]]
        return sum(values), values[3] + values[4]  # idle + iowait

    def sample(self):
        try:
            total, idle = self._totals()
        except (ValueError, IndexError):
            return 0.0
        prev, self._prev = self._prev, (total, idle)
        if prev is None:
            return 0.0
        dt, di = total - prev[0], idle - prev[1]
        if dt <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (dt - di) / dt))


def cpu_info():
    """Model name and core count, for the About box and the System tab."""
    model, cores = "", 0
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name") and not model:
            model = line.split(":", 1)[1].strip()
        elif line.startswith("processor"):
            cores += 1
    return {"model": model or "Unknown processor", "cores": cores}


def loadavg():
    try:
        return os.getloadavg()
    except OSError:
        return (0.0, 0.0, 0.0)


# ── memory ──────────────────────────────────────────────────────────────

def memory():
    """Used/total in bytes for RAM and swap, plus percentages.

    "Used" is total minus *available*, not minus free — the same choice
    memory.sh makes, and the only one that doesn't count the page cache as
    consumed.
    """
    values = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        try:
            values[key] = int(rest.split()[0]) * 1024
        except (IndexError, ValueError):
            continue
    total = values.get("MemTotal", 0)
    avail = values.get("MemAvailable", 0)
    used = max(0, total - avail)
    swap_total = values.get("SwapTotal", 0)
    swap_used = max(0, swap_total - values.get("SwapFree", 0))
    return {
        "used": used, "total": total,
        "percent": 100.0 * used / total if total else 0.0,
        "swap_used": swap_used, "swap_total": swap_total,
        "swap_percent": 100.0 * swap_used / swap_total if swap_total else 0.0,
    }


# ── disk ────────────────────────────────────────────────────────────────

def disk(path="/"):
    try:
        st = os.statvfs(path)
    except OSError:
        return {"used": 0, "total": 0, "free": 0, "percent": 0.0}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    # Match df: capacity is measured against what a normal user can reach, so
    # the root-reserved blocks count as used rather than as free.
    used = total - st.f_bfree * st.f_frsize
    usable = used + free
    return {
        "used": used, "total": total, "free": free,
        "percent": 100.0 * used / usable if usable else 0.0,
    }


# ── temperature ─────────────────────────────────────────────────────────

_TEMP_LABELS = ("Package id 0", "Tctl", "Tdie", "Composite", "CPU")


def _find_temp_input():
    """Pick a CPU temperature sensor once and remember it.

    temp.sh shells out to `sensors`, which costs ~50ms — too much at 1Hz, and
    unnecessary: lm_sensors is reading the same hwmon files we can read.
    """
    best = None
    for hwmon in sorted(_glob("/sys/class/hwmon/hwmon*")):
        name = _read(os.path.join(hwmon, "name"))
        for temp in sorted(_glob(os.path.join(hwmon, "temp*_input"))):
            label = _read(temp.replace("_input", "_label"))
            if label in _TEMP_LABELS or name in ("coretemp", "k10temp", "zenpower"):
                return temp
            best = best or temp
    if best:
        return best
    zones = sorted(_glob("/sys/class/thermal/thermal_zone*/temp"))
    return zones[0] if zones else None


def _glob(pattern):
    import glob as _g
    return _g.glob(pattern)


_TEMP_PATH = None
_TEMP_LOOKED = False


def temperature():
    """CPU temperature in °C, or None on a machine that doesn't report one."""
    global _TEMP_PATH, _TEMP_LOOKED
    if not _TEMP_LOOKED:
        _TEMP_PATH, _TEMP_LOOKED = _find_temp_input(), True
    if not _TEMP_PATH:
        return None
    raw = _read(_TEMP_PATH)
    try:
        return int(raw) / 1000.0
    except ValueError:
        return None


# ── network ─────────────────────────────────────────────────────────────

class NetMeter:
    """Bytes per second in and out, summed over every real interface.

    Loopback is excluded — it's an echo of local traffic, and on a box running
    a dozen dev services it dwarfs the wire.
    """

    def __init__(self):
        self._prev = None
        self._prev_at = None

    @staticmethod
    def _totals():
        rx = tx = 0
        for line in _read("/proc/net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if name == "lo" or name.startswith(("veth", "docker", "br-")):
                continue
            fields = rest.split()
            if len(fields) >= 9:
                rx += int(fields[0])
                tx += int(fields[8])
        return rx, tx

    def sample(self):
        now = time.monotonic()
        try:
            totals = self._totals()
        except ValueError:
            return (0.0, 0.0)
        prev, prev_at = self._prev, self._prev_at
        self._prev, self._prev_at = totals, now
        if prev is None or not prev_at or now <= prev_at:
            return (0.0, 0.0)
        span = now - prev_at
        return (max(0.0, (totals[0] - prev[0]) / span),
                max(0.0, (totals[1] - prev[1]) / span))


def network_link():
    """The interface actually carrying traffic off this machine.

    "First one that is up" is not good enough on a box that runs Docker: this
    laptop has a `br-433e8a…` bridge permanently up with a 172.30/16 address on
    it, and reporting that as the connection would be both wrong and confusing.
    A driver-bound `device` symlink is what separates a real NIC from a bridge,
    a veth or a tunnel, and wireless wins over wired because that is the link
    a laptop is normally on.

    The pretty half (SSID, signal strength) comes from network.sh; this is only
    what's needed to show an address without shelling out.
    """
    wired = None
    for iface in sorted(_glob("/sys/class/net/*")):
        name = os.path.basename(iface)
        if name == "lo" or not os.path.exists(os.path.join(iface, "device")):
            continue
        if _read(os.path.join(iface, "operstate")) != "up":
            continue
        link = {"name": name,
                "wireless": os.path.isdir(os.path.join(iface, "wireless")),
                "address": ipv4_address(name)}
        if link["wireless"]:
            return link
        wired = wired or link
    return wired


def ipv4_address(name):
    for line in _run(["ip", "-4", "-o", "addr", "show", name]).splitlines():
        fields = line.split()
        if "inet" in fields:
            return fields[fields.index("inet") + 1].split("/")[0]
    return ""


def wifi_signal(iface):
    """Signal strength as a percentage, using the same dBm→% curve as the bar."""
    out = _run(["iw", "dev", iface, "link"])
    match = re.search(r"signal:\s*(-?\d+)", out)
    if not match:
        return None
    return max(0, min(100, int((int(match.group(1)) + 100) * 2)))


# ── uptime, host ────────────────────────────────────────────────────────

def uptime_seconds():
    try:
        return float(_read("/proc/uptime").split()[0])
    except (IndexError, ValueError):
        return 0.0


def host_info():
    un = os.uname()
    return {"host": un.nodename, "kernel": un.release, "arch": un.machine,
            "system": un.sysname}


# ── battery ─────────────────────────────────────────────────────────────

def battery():
    """Charge, status and — where the firmware exposes the rate — time left."""
    for path in sorted(_glob("/sys/class/power_supply/BAT*")):
        capacity = _read(os.path.join(path, "capacity"))
        if not capacity:
            continue
        status = _read(os.path.join(path, "status"), "Unknown")
        # Laptops report either energy (µWh / µW) or charge (µAh / µA); both
        # divide out to hours the same way.
        remaining = None
        for level, rate in (("energy_now", "power_now"), ("charge_now", "current_now")):
            try:
                now = int(_read(os.path.join(path, level)))
                draw = int(_read(os.path.join(path, rate)))
            except ValueError:
                continue
            if draw <= 0:
                continue
            if status == "Charging":
                for full in ("energy_full", "charge_full"):
                    try:
                        top = int(_read(os.path.join(path, full)))
                    except ValueError:
                        continue
                    remaining = max(0.0, (top - now) / draw)
                    break
            else:
                remaining = now / draw
            break
        try:
            percent = int(capacity)
        except ValueError:
            percent = 0
        return {"percent": percent, "status": status, "hours": remaining,
                "name": os.path.basename(path)}
    return None


# ── audio (pactl) ───────────────────────────────────────────────────────

def sink():
    """Output volume and mute state."""
    volume = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    muted = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
    match = re.search(r"(\d+)%", volume)
    return {"volume": int(match.group(1)) if match else 0,
            "muted": "yes" in muted}


def source():
    """Input (microphone) mute state."""
    return {"muted": "yes" in _run(["pactl", "get-source-mute", "@DEFAULT_SOURCE@"])}


def set_sink_volume(percent):
    spawn(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % max(0, min(150, percent))])


def toggle_sink_mute():
    spawn(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])


def toggle_source_mute():
    spawn(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"])


def refresh_bar(signal):
    """Poke i3blocks the way the keybindings do.

    A no-op when the bar isn't running, which is the normal state in Win95
    mode — but it costs nothing and means the monitor and a temporarily
    un-hidden bar stay in step.
    """
    shell("pkill -RTMIN+%d i3blocks 2>/dev/null || true" % signal)


# ── power tuning ────────────────────────────────────────────────────────

PROFILE_PATH = "/sys/firmware/acpi/platform_profile"
PROFILE_CHOICES_PATH = "/sys/firmware/acpi/platform_profile_choices"
BOOST_PATH = "/sys/devices/system/cpu/cpufreq/boost"


def power_profile():
    if not os.path.exists(PROFILE_PATH):
        return None
    choices = _read(PROFILE_CHOICES_PATH).split() or ["low-power", "balanced", "performance"]
    return {"current": _read(PROFILE_PATH), "choices": choices}


def set_power_profile(name):
    # Passwordless sudo is what power-profile.sh already relies on; -n keeps a
    # misconfigured host from parking an invisible password prompt forever.
    return shell("echo %s | sudo -n tee %s >/dev/null" % (name, PROFILE_PATH))


def cpu_boost():
    if not os.path.exists(BOOST_PATH):
        return None
    return _read(BOOST_PATH) == "1"


def set_cpu_boost(on):
    return shell("echo %d | sudo -n tee %s >/dev/null" % (1 if on else 0, BOOST_PATH))


# ── bluetooth ───────────────────────────────────────────────────────────

def bt_devices():
    """The devices the bar has widgets for, read out of those widgets.

    bt-headphones.sh, bt-keyboard.sh and bt-mouse.sh each hard-code one MAC and
    one short name. Scraping them keeps a single copy of both: pair a new
    device by adding a block script, and it shows up here for free.
    """
    devices = []
    for block, kind in (("bt-headphones", "headphones"),
                        ("bt-mouse", "mouse"),
                        ("bt-keyboard", "keyboard")):
        path = script_path(block)
        if not path:
            continue
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        mac = re.search(r'^MAC="([0-9A-Fa-f:]+)"', text, re.M)
        name = re.search(r'^NAME="([^"]*)"', text, re.M)
        if mac:
            devices.append({"block": block, "kind": kind,
                            "mac": mac.group(1),
                            "name": name.group(1) if name else mac.group(1)})
    return devices


def bt_powered():
    return "Powered: yes" in _run(["bluetoothctl", "show"], timeout=3)


def bt_info(mac):
    """Connected state and, when the device reports it, battery percentage."""
    out = _run(["bluetoothctl", "info", mac], timeout=3)
    percent = re.search(r"Battery Percentage:.*\((\d+)\)", out)
    return {"connected": "Connected: yes" in out,
            "paired": "Paired: yes" in out,
            "battery": int(percent.group(1)) if percent else None}


def bt_connect(mac, connect=True):
    spawn(["bluetoothctl", "connect" if connect else "disconnect", mac])


def bt_power(on):
    spawn(["bluetoothctl", "power", "on" if on else "off"])


# ── VPN ─────────────────────────────────────────────────────────────────

WG_DIR = os.path.join(HOME, ".config", "wg")


def vpn_tunnels():
    """WireGuard tunnels this box knows about, and which one is up.

    vpn.sh hard-codes wg_1/wg_2 in its rofi menu; the confs on disk are the
    same list without the hard-coding, so new tunnels appear by existing.
    """
    tunnels = []
    for conf in sorted(_glob(os.path.join(WG_DIR, "*.conf"))):
        name = os.path.basename(conf)[:-5]
        if name.endswith("~"):
            continue
        tunnels.append({"name": name, "conf": conf, "up": link_exists(name)})
    return tunnels


def link_exists(name):
    return os.path.exists("/sys/class/net/" + name)


def vpn_active():
    """Any VPN-ish interface, however it was brought up."""
    for iface in sorted(_glob("/sys/class/net/*")):
        name = os.path.basename(iface)
        if name.startswith(("wg", "tun", "tap")):
            return name
    return None


def vpn_up(conf):
    return term("sudo wg-quick up %s" % conf, hold=False)


def vpn_down(conf):
    return term("sudo wg-quick down %s" % conf, hold=False)


# ── keyboard layout ─────────────────────────────────────────────────────

def keyboard_layout():
    match = re.search(r"^layout:\s*(\S+)", _run(["setxkbmap", "-query"]), re.M)
    return match.group(1).upper() if match else "?"


def toggle_keyboard_layout():
    block_action("keyboard", 1)


# ── recording ───────────────────────────────────────────────────────────

def recording():
    """Which of the record-* helpers is running, if any."""
    for kind, pidfile in (("window", "/tmp/record-window.pid"),
                          ("desktop", "/tmp/record-desktop.pid"),
                          ("region", "/tmp/record-region.pid")):
        try:
            pid = int(_read(pidfile))
            os.kill(pid, 0)
            return kind
        except (ValueError, OSError):
            continue
    return None


# ── Claude usage ────────────────────────────────────────────────────────

_CLAUDE_ROW = re.compile(
    r"<span foreground='(#[0-9a-fA-F]{6})'>(<b>)?([^:<]+):([\d?]+)%(?:\(([^)]*)\))?"
)


def claude_usage(timeout=25):
    """Per-account Claude usage, parsed out of claude-usage.sh's pango line.

    Not reimplemented: that script owns account discovery, the cookie/OAuth
    fallback, the credential shuffling and — importantly — a rate-limit rule
    about never refreshing an expired token on a timer. Re-deriving any of it
    here would be a second thing to keep right.

    Its markup is one span per account, bolded for the active one:
        <span foreground='#859900'><b>W:3%(4h6m)</b></span>
    """
    path = script_path("claude-usage")
    if not path:
        return []
    try:
        raw = subprocess.run(
            [path], capture_output=True, text=True, timeout=timeout,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    if not raw:
        return []
    accounts = []
    for colour, bold, label, usage, resets in _CLAUDE_ROW.findall(raw[0]):
        accounts.append({
            "label": label.strip(),
            "percent": int(usage) if usage.isdigit() else None,
            "resets": resets or "",
            "colour": colour,
            "active": bool(bold),
        })
    return accounts


def claude_switch():
    """Open the account switcher — the same rofi menu the bar's block opens."""
    block_action("claude-usage", 3)


# ── formatting ──────────────────────────────────────────────────────────

def human_bytes(value, unit="B"):
    value = float(value or 0)
    for suffix in ("", "K", "M", "G", "T"):
        if value < 1024 or suffix == "T":
            precision = 0 if (suffix == "" or value >= 100) else 1
            return "%.*f %s%s" % (precision, value, suffix, unit)
        value /= 1024
    return "%.1f T%s" % (value, unit)


def human_duration(seconds):
    seconds = int(seconds or 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "%dd %dh %dm" % (days, hours, minutes)
    if hours:
        return "%dh %dm" % (hours, minutes)
    return "%dm" % minutes


# ── the polling pump ────────────────────────────────────────────────────

class Series:
    """A fixed-length ring of samples, oldest first — one chart's worth."""

    def __init__(self, length=120):
        self.length = length
        self.values = []

    def push(self, value):
        self.values.append(float(value))
        if len(self.values) > self.length:
            del self.values[: len(self.values) - self.length]

    def clear(self):
        self.values = []

    @property
    def latest(self):
        return self.values[-1] if self.values else 0.0

    @property
    def peak(self):
        return max(self.values) if self.values else 0.0

    @property
    def mean(self):
        return sum(self.values) / len(self.values) if self.values else 0.0


class Poller:
    """Runs slow probes off the UI thread on a per-task interval.

    Each task has its own period because the costs differ by three orders of
    magnitude: `bluetoothctl info` is a couple of hundred milliseconds,
    `checkupdates` can be a cold network call, and claude-usage.sh may sit on a
    curl for ten seconds. Sharing one interval would mean either hammering the
    expensive ones or starving the cheap ones.

    A task that is still running is never submitted again — the failure mode
    otherwise is a wedged `bluetoothctl` accumulating one stuck worker per
    tick until the pool is full and *everything* stops updating.
    """

    def __init__(self, dispatch, workers=4):
        self.dispatch = dispatch
        self.tasks = {}
        self._pool = ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="w95stat")
        self._inflight = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = False
        self._paused = False
        self._thread = None

    def add(self, key, fn, interval, on_result):
        self.tasks[key] = {"fn": fn, "interval": interval, "cb": on_result,
                           "due": 0.0}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="w95stat-sched")
        self._thread.start()

    def stop(self):
        self._running = False
        self._wake.set()

    def pause(self, paused=True):
        """Stop probing while the window is hidden.

        The monitor is a glance-at tool: left resident for instant toggling, it
        would otherwise keep running `checkupdates` and curling the Claude API
        all day at a window nobody is looking at.
        """
        self._paused = paused
        if not paused:
            self.refresh()

    def refresh(self, key=None):
        """Make one task — or all of them — due immediately."""
        for name, task in list(self.tasks.items()):
            if key in (None, name):
                task["due"] = 0.0
        self._wake.set()

    def _loop(self):
        while self._running:
            timeout = 1.0
            if not self._paused:
                now = time.monotonic()
                for key, task in list(self.tasks.items()):
                    if task["due"] <= now:
                        task["due"] = now + task["interval"]
                        self._submit(key, task)
                    timeout = min(timeout, max(0.05, task["due"] - now))
            self._wake.wait(timeout)
            self._wake.clear()

    def _submit(self, key, task):
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)

        def work():
            try:
                value = task["fn"]()
            except Exception as exc:  # a probe must never kill the pump
                value = None
                print("w95stat: %s failed: %s" % (key, exc))
            finally:
                with self._lock:
                    self._inflight.discard(key)
            self.dispatch(task["cb"], value)

        self._pool.submit(work)


if __name__ == "__main__":
    # A text dump of every reading — the way to check the data layer without
    # putting a window on screen.
    cpu, net = CpuMeter(), NetMeter()
    cpu.sample(); net.sample(); time.sleep(1)
    print("cpu          %.1f%%" % cpu.sample())
    mem = memory()
    print("memory       %s / %s (%.0f%%)  swap %.0f%%"
          % (human_bytes(mem["used"]), human_bytes(mem["total"]),
             mem["percent"], mem["swap_percent"]))
    root = disk("/")
    print("disk         %s free of %s (%.0f%%)"
          % (human_bytes(root["free"]), human_bytes(root["total"]), root["percent"]))
    print("temperature  %s" % temperature())
    print("net          %s/s down  %s/s up" % tuple(human_bytes(v) for v in net.sample()))
    print("uptime       %s" % human_duration(uptime_seconds()))
    print("load         %.2f %.2f %.2f" % loadavg())
    print("cpu info     %(model)s (%(cores)d threads)" % cpu_info())
    print("host         %(host)s  %(kernel)s  %(arch)s" % host_info())
    print("battery      %s" % battery())
    print("sink         %s" % sink())
    print("source       %s" % source())
    print("profile      %s" % power_profile())
    print("boost        %s" % cpu_boost())
    print("link         %s" % network_link())
    print("vpn          %s  tunnels=%s" % (vpn_active(), vpn_tunnels()))
    print("keyboard     %s" % keyboard_layout())
    print("recording    %s" % recording())
    print("bt powered   %s" % bt_powered())
    for device in bt_devices():
        print("bt %-10s %s  %s" % (device["name"], device["mac"], bt_info(device["mac"])))
    for name in ("network", "vpn", "bluetooth", "updates", "volume", "mic",
                 "power-profile", "cpu-boost", "battery", "uptime"):
        print("block %-14s %s" % (name, run_block(name)))
    print("claude       %s" % claude_usage())
