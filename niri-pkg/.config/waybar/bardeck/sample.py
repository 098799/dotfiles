"""Everything the system, network, devices and power strips show, read in one place.

The fast numbers come from /proc and /sys on the main loop every second: a few
small reads, no process. The rest (NetworkManager and BlueZ over D-Bus, pactl and
iw while their panel is open, checkupdates hourly) runs on a worker thread, so a
slow bluetoothd never stalls the bar or an open panel; the main loop only reads
what the worker last stored.

History rings keep HISTORY seconds for the panels' graphs.
"""

from __future__ import annotations

import glob
import json
import os
import re
import socket
import subprocess
import threading
import time
from collections import deque

from . import core

HISTORY = 300  # seconds of graph in the panels
WORKER_EVERY = 4.0
UPDATES_EVERY = 3600
UPDATES_CACHE = "/tmp/.updates_cache"  # updates.sh's cache: the two agree


def _ints(line: str) -> list[int]:
    return [int(x) for x in line.split()[1:]]


def ipv4(ifname: str) -> str:
    """The interface's IPv4 address: one ioctl (SIOCGIFADDR), no `ip` process."""
    import fcntl
    import struct

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            raw = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", ifname[:15].encode()))
        return socket.inet_ntoa(raw[20:24])
    except OSError:
        return ""


def _hwmon(name: str) -> str | None:
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if core.read(f"{h}/name") == name:
            return h
    return None


def run(argv: list[str], timeout: float = 2.0) -> str:
    try:
        return subprocess.run(["nice", "-n", "10", *argv], capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


class Device:
    """A Bluetooth device the bar knows by its i3blocks script (bt-<kind>.sh)."""

    GLYPH = {"headphones": "󰋋", "keyboard": "󰌌", "mouse": "󰍽"}

    def __init__(self, kind: str, script: str, mac: str, name: str):
        self.kind, self.script, self.mac, self.name = kind, script, mac, name

    @property
    def glyph(self) -> str:
        return self.GLYPH.get(self.kind, "󰂯")


def bt_devices() -> list[Device]:
    """MAC and NAME from ~/scripts/bt-*.sh: the scripts stay the one list."""
    out = []
    for path in sorted(glob.glob(f"{core.SCRIPTS}/bt-*.sh")):
        kind = os.path.basename(path)[3:-3]
        if kind == "state":
            continue
        src = core.read(path)
        mac = re.search(r'^MAC="([^"]+)"', src, re.M)
        name = re.search(r'^NAME="([^"]+)"', src, re.M)
        if mac:
            out.append(Device(kind, os.path.basename(path), mac.group(1), name.group(1) if name else kind))
    order = {"headphones": 0, "keyboard": 1, "mouse": 2}
    return sorted(out, key=lambda d: order.get(d.kind, 9))


class Sampler:
    def __init__(self):
        self.host = socket.gethostname()
        self.cpu_model = ""
        for line in core.read("/proc/cpuinfo").splitlines():
            if line.startswith("model name"):
                self.cpu_model = line.split(":", 1)[1].strip()
                break
        self.ncpu = os.cpu_count() or 1
        self.cpu = deque(maxlen=HISTORY)
        self.mem = deque(maxlen=HISTORY)
        self.swap = deque(maxlen=HISTORY)
        self.temp = deque(maxlen=HISTORY)
        self.rx = deque(maxlen=HISTORY)
        self.tx = deque(maxlen=HISTORY)
        self.cores: list[float] = []
        self._stat: dict[str, list[int]] = {}
        self._net: tuple[float, int, int] | None = None
        self.meminfo: dict[str, int] = {}
        self.load = (0.0, 0.0, 0.0)
        self.uptime = 0.0
        self.temp_hw = _hwmon("k10temp") or _hwmon("coretemp")
        self.nvme_hw = _hwmon("nvme")
        self.extra_temps: dict[str, float] = {}
        self.bat_dir = next(iter(sorted(glob.glob("/sys/class/power_supply/BAT*"))), None)
        self.bat: dict[str, str] = {}
        self.ac = False
        self.profile = ""
        self.profiles: list[str] = []
        self.boost: str | None = None
        self.cap: str | None = None
        self.disks: list[tuple[str, int, int]] = []
        self._disk_at = 0.0
        self._slow_at, self._slow_now = 0.0, False
        # Worker results (replaced whole, read by the main loop).
        self.wifi: dict = {}
        self.links: list[tuple[str, str, str]] = []  # (name, "wifi" / "eth", ipv4), up only
        self.vpn: list[str] = []
        self.tailscale = ""
        self.bt_powered = False
        self.bt_connected: dict[str, str] = {}
        self.bt_battery: dict[str, int] = {}  # MAC -> %, from BlueZ
        self._bt_dirty, self._bt_at = True, 0.0
        self._system_bus = None
        self.want_link = False  # the network panel is open: iw for dBm and link rates
        self.sinks: list[dict] = []
        self.sources: list[dict] = []
        self.default_sink = ""
        self.default_source = ""
        self.updates: int | None = None
        self.devices = bt_devices()
        self.top_cpu: list[tuple[str, float]] = []
        self.top_mem: list[tuple[str, int]] = []
        self._proc: dict[int, int] = {}
        self._proc_t = 0.0
        self.want_audio = False
        self.want_top = False
        self._lock = threading.Lock()
        self._checking = False
        self._checked_at = 0.0
        self._wake = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    # -- every second, on the main loop ----------------------------------------

    def tick(self) -> None:
        now = time.monotonic()
        stat: dict[str, list[int]] = {}
        for line in core.read("/proc/stat").splitlines():
            if line.startswith("cpu"):
                stat[line.split()[0]] = _ints(line)
        if self._stat:
            def busy(key):
                a, b = self._stat.get(key), stat.get(key)
                if not a or not b:
                    return 0.0
                total = sum(b) - sum(a)
                idle = (b[3] + b[4]) - (a[3] + a[4])
                return 100.0 * (total - idle) / total if total > 0 else 0.0
            self.cpu.append(busy("cpu"))
            self.cores = [busy(f"cpu{i}") for i in range(self.ncpu)]
        self._stat = stat

        mi = {}
        for line in core.read("/proc/meminfo").splitlines():
            k, _, v = line.partition(":")
            mi[k] = int(v.split()[0]) * 1024
        self.meminfo = mi
        total = mi.get("MemTotal", 1)
        self.mem.append(100.0 * (total - mi.get("MemAvailable", 0)) / total)
        st = mi.get("SwapTotal", 0)
        self.swap.append(100.0 * (st - mi.get("SwapFree", 0)) / st if st else 0.0)

        if self.temp_hw:
            t = core.read(f"{self.temp_hw}/temp1_input")
            if t:
                self.temp.append(int(t) / 1000)

        rx = tx = 0
        for line in core.read("/proc/net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if name.startswith(("wl", "en", "eth")):
                f = rest.split()
                rx += int(f[0])
                tx += int(f[8])
        if self._net:
            dt = now - self._net[0]
            if dt > 0:
                self.rx.append(max(0.0, (rx - self._net[1]) / dt))
                self.tx.append(max(0.0, (tx - self._net[2]) / dt))
        self._net = (now, rx, tx)

        la = core.read("/proc/loadavg").split()
        if len(la) >= 3:
            self.load = (float(la[0]), float(la[1]), float(la[2]))
        self.uptime = float(core.read("/proc/uptime", "0").split()[0])

        # What changes slowly is read every 5 s (or after a click: poke()).
        if now - self._slow_at >= 5 or self._slow_now:
            self._slow_at, self._slow_now = now, False
            if self.bat_dir:
                self.bat = {k: core.read(f"{self.bat_dir}/{k}") for k in (
                    "capacity", "status", "power_now", "energy_now", "energy_full", "energy_full_design")}
            self.ac = core.read("/sys/class/power_supply/AC/online") == "1"
            self.profile = core.read("/sys/firmware/acpi/platform_profile")
            if not self.profiles:
                self.profiles = core.read("/sys/firmware/acpi/platform_profile_choices").split()
            boost = "/sys/devices/system/cpu/cpufreq/boost"
            self.boost = core.read(boost) if os.path.exists(boost) else None
            cap = "/sys/devices/system/cpu/intel_pstate/max_perf_pct"
            self.cap = core.read(cap) if os.path.exists(cap) else None
            if self.nvme_hw:
                t = core.read(f"{self.nvme_hw}/temp1_input")
                if t:
                    self.extra_temps["nvme"] = int(t) / 1000

        if now - self._disk_at > 30:
            self._disk_at = now
            disks, seen = [], set()
            for mount in ("/", "/home"):
                try:
                    st_dev = os.stat(mount).st_dev
                    if st_dev in seen:
                        continue
                    seen.add(st_dev)
                    vfs = os.statvfs(mount)
                    disks.append((mount, vfs.f_blocks * vfs.f_frsize, vfs.f_bavail * vfs.f_frsize))
                except OSError:
                    pass
            self.disks = disks

        # Every 30 s always, so the system panel opens with numbers; every 2 s while open.
        if now - self._proc_t >= (2 if self.want_top else 30):
            self._top(now)

    def _top(self, now: float) -> None:
        """Top processes by CPU (since the last scan) and by memory. A scan reads every
        /proc/<pid>/stat: ~20 ms, so not every second."""
        ticks = os.sysconf("SC_CLK_TCK")
        page = os.sysconf("SC_PAGE_SIZE")
        dt = now - self._proc_t if self._proc_t else 0
        cur, cpu, mem = {}, [], []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            raw = core.read(f"/proc/{pid}/stat")
            if not raw:
                continue
            name = raw[raw.find("(") + 1:raw.rfind(")")]
            f = raw[raw.rfind(")") + 2:].split()
            t = int(f[11]) + int(f[12])
            cur[int(pid)] = t
            rss = int(f[21]) * page
            mem.append((name, rss))
            if dt and int(pid) in self._proc:
                cpu.append((name, 100.0 * (t - self._proc[int(pid)]) / ticks / dt))
        self._proc, self._proc_t = cur, now

        def merge(items):
            agg: dict[str, float] = {}
            for n, v in items:
                agg[n] = agg.get(n, 0) + v
            return sorted(agg.items(), key=lambda kv: -kv[1])

        if cpu:
            self.top_cpu = merge(cpu)[:7]
        self.top_mem = merge(mem)[:7]

    # -- the worker thread -----------------------------------------------------

    def poke(self) -> None:
        """Read the slow things now (after a click changed them)."""
        self._slow_now = True
        self._wake.set()

    def _worker(self) -> None:
        while True:
            try:
                self._slow()
                try:
                    age = time.time() - os.stat(UPDATES_CACHE).st_mtime
                except OSError:
                    age = UPDATES_EVERY
                if age >= UPDATES_EVERY and not self._checking and time.time() - self._checked_at >= UPDATES_EVERY:
                    # Its own thread: checkupdates takes up to minutes, and the wifi,
                    # Bluetooth and audio readings must not wait for it.
                    self._checking, self._checked_at = True, time.time()  # one try an hour, failed or not
                    threading.Thread(target=self._check_updates, daemon=True).start()
                self._read_updates()
            except Exception as err:  # never let the worker die
                core.log(f"sampler: {err!r}")
            self._wake.wait(WORKER_EVERY)
            self._wake.clear()

    def _slow(self) -> None:
        """The readings that are not a file read: over D-Bus (NetworkManager, BlueZ) and
        ioctl, in-process. No program starts here but pactl (only while the devices
        panel is open) and iw (only while the network panel is open). This used to run
        bt-state.sh (two bluetoothctl), iw and ip every 4 s: 4% of a core."""
        ifaces = {}
        for name in os.listdir("/sys/class/net"):
            if name.startswith(("wl", "en", "eth")) and core.read(f"/sys/class/net/{name}/operstate") == "up":
                ifaces[name] = "wifi" if os.path.isdir(f"/sys/class/net/{name}/wireless") else "eth"
        wifi = {}
        for name, kind in ifaces.items():
            if kind == "wifi":
                wifi = self._nm_wifi(name)
                if self.want_link:
                    out = run(["iw", "dev", name, "link"])
                    for key, pat in (("signal", r"signal: (-?\d+)"), ("rx", r"rx bitrate: ([\d.]+ \S+)"),
                                     ("tx", r"tx bitrate: ([\d.]+ \S+)")):
                        m = re.search(pat, out)
                        if m:
                            wifi[key] = m.group(1)
                break
        vpn = sorted(n for n in os.listdir("/sys/class/net")
                     if n.startswith(("wg", "tun", "tap")) and n != "tailscale0")
        tailscale = ipv4("tailscale0") if os.path.exists("/sys/class/net/tailscale0") else ""

        if self._bt_dirty or time.monotonic() - self._bt_at > 60:
            self._bt_dirty, self._bt_at = False, time.monotonic()
            self._bluez()

        sinks, sources, dsink, dsource = self.sinks, self.sources, self.default_sink, self.default_source
        if self.want_audio or not self.default_sink:
            try:
                sinks = [{"name": s["name"], "desc": s.get("description") or s["name"]}
                         for s in json.loads(run(["pactl", "-f", "json", "list", "sinks"]) or "[]")]
                sources = [{"name": s["name"], "desc": s.get("description") or s["name"]}
                           for s in json.loads(run(["pactl", "-f", "json", "list", "sources"]) or "[]")
                           if not s["name"].endswith(".monitor")]
            except (ValueError, KeyError, TypeError):
                pass
            dsink = run(["pactl", "get-default-sink"]).strip()
            dsource = run(["pactl", "get-default-source"]).strip()

        with self._lock:
            self.wifi, self.vpn, self.tailscale = wifi, vpn, tailscale
            self.links = [(n, k, ipv4(n)) for n, k in sorted(ifaces.items())]
            self.sinks, self.sources, self.default_sink, self.default_source = sinks, sources, dsink, dsource

    def _nm_wifi(self, iface: str) -> dict:
        """SSID, strength (%), frequency and bitrate from NetworkManager: ~3 ms."""
        out = {"iface": iface}
        try:
            dev = self._dbus("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                             "org.freedesktop.NetworkManager", "GetDeviceByIpIface", ("(s)", (iface,)))[0]
            w = self._props("org.freedesktop.NetworkManager", dev, "org.freedesktop.NetworkManager.Device.Wireless")
            ap_path = w.get("ActiveAccessPoint")
            if ap_path and ap_path != "/":
                ap = self._props("org.freedesktop.NetworkManager", ap_path,
                                 "org.freedesktop.NetworkManager.AccessPoint")
                out["ssid"] = bytes(ap.get("Ssid", b"")).decode(errors="replace")
                out["strength"] = int(ap.get("Strength", 0))
                out["freq"] = str(ap.get("Frequency", ""))
            if w.get("Bitrate"):
                out["bitrate"] = f"{w['Bitrate'] / 1000:.0f} Mbit/s"
        except Exception as err:  # no NetworkManager: say what we know
            if core.TRACE:
                core.log(f"networkmanager: {err!r}")
        return out

    def _bluez(self) -> None:
        """Powered, connected devices and their batteries from BlueZ: one call, ~18 ms
        (it lists every device it ever saw), so only after BlueZ says something changed
        (bt_changed) and once a minute."""
        powered, connected, battery = False, {}, {}
        try:
            objs = self._dbus("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                              None, "(a{oa{sa{sv}}})")[0]
        except Exception:
            objs = {}
        for _path, ifs in objs.items():
            if "org.bluez.Adapter1" in ifs:
                powered = powered or bool(ifs["org.bluez.Adapter1"].get("Powered"))
            dev = ifs.get("org.bluez.Device1")
            if dev and dev.get("Connected"):
                mac = dev.get("Address", "")
                connected[mac] = dev.get("Alias") or dev.get("Name") or mac
                bat = ifs.get("org.bluez.Battery1")
                if bat and "Percentage" in bat:
                    battery[mac] = int(bat["Percentage"])
        with self._lock:
            self.bt_powered, self.bt_connected, self.bt_battery = powered, connected, battery

    def _dbus(self, name, path, iface, method, args=None, reply=None):
        from gi.repository import Gio, GLib

        params = GLib.Variant(*args) if args else None
        return self._bus().call_sync(name, path, iface, method, params,
                                     GLib.VariantType(reply) if reply else None,
                                     Gio.DBusCallFlags.NONE, 1000, None).unpack()

    def _props(self, name, path, iface) -> dict:
        return self._dbus(name, path, "org.freedesktop.DBus.Properties", "GetAll", ("(s)", (iface,)))[0]

    def _bus(self):
        if self._system_bus is None:
            from gi.repository import Gio

            self._system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        return self._system_bus

    def watch_bluez(self) -> None:
        """On the main loop: BlueZ's signals mark the Bluetooth reading stale."""
        from gi.repository import Gio

        def changed(*_args):
            self._bt_dirty = True
            self.poke()

        bus = self._bus()
        for iface, member in (("org.freedesktop.DBus.Properties", "PropertiesChanged"),
                              ("org.freedesktop.DBus.ObjectManager", "InterfacesAdded"),
                              ("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved")):
            bus.signal_subscribe("org.bluez", iface, member, None, None, Gio.DBusSignalFlags.NONE, changed)

    def _read_updates(self) -> None:
        try:
            with open(UPDATES_CACHE) as fh:
                self.updates = sum(1 for line in fh if line.strip())
        except OSError:
            pass

    def _check_updates(self) -> None:
        """checkupdates: 0 = updates listed, 2 = none, anything else = it failed
        (offline, the db lock): then keep the old cache, and try again next hour."""
        try:
            proc = subprocess.run(["nice", "-n", "19", "checkupdates"], capture_output=True, text=True,
                                  timeout=300)
            if proc.returncode in (0, 2):
                with open(UPDATES_CACHE + ".bardeck", "w") as fh:
                    fh.write(proc.stdout if proc.returncode == 0 else "")
                os.replace(UPDATES_CACHE + ".bardeck", UPDATES_CACHE)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            self._checking = False
        self._read_updates()
