"""Sound devices and streams from PulseAudio (pipewire-pulse): what pavucontrol shows.

How it reads, and why this way: there is no pulsectl and no Python libpulse here,
and libpulse over ctypes means mirroring pa_sink_info & co. by hand (their layout
changes between versions). So the panel takes the cheapest honest route:

  ONE long-lived `pactl subscribe` child, read on a thread. It prints a line per
  event ("Event 'change' on sink #6278") and nothing else: it sleeps in poll() while
  nothing happens (~0 CPU). It dies with the daemon (PR_SET_PDEATHSIG).

  On an event, a debounced `pactl -f json list sinks / sources / sink-inputs` (only
  the kinds that changed; at most READS_PER_S a second; streams only while the panel
  is open) and `pactl -f json info` for the defaults. ~10 ms each.

So a volume key (Tomek's keys run pactl / wpctl) reaches the strip in ~30 ms: the
event wakes the thread, the list runs, the strip is drawn on the main loop.
Setting runs pactl too (set-sink-volume, …), on a thread, and the event that
follows brings the new state back."""

from __future__ import annotations

import ctypes
import json
import signal
import subprocess
import threading
import time

from . import core

READS_PER_S = 4
_LIBC = ctypes.CDLL(None)  # loaded before any fork: the child only calls prctl
PR_SET_PDEATHSIG = 1


class Dev:
    """A sink, a source or a stream (sink-input)."""

    __slots__ = ("kind", "index", "name", "desc", "sub", "vol", "mute", "glyph", "sink", "corked")

    def __init__(self, kind: str, index: int, name: str, desc: str, vol: int, mute: bool, *,
                 sub: str = "", glyph: str = "", sink: int = -1, corked: bool = False):
        self.kind, self.index, self.name, self.desc = kind, index, name, desc
        self.vol, self.mute, self.sub, self.glyph = vol, mute, sub, glyph
        self.sink, self.corked = sink, corked

    def __repr__(self):
        return f"Dev({self.kind} {self.index} {self.desc!r} {self.vol}%{' muted' if self.mute else ''})"


def volume(entry: dict) -> int:
    """The loudest channel, in % (pa_cvolume_max, as pavucontrol's slider shows it)."""
    vals = [ch.get("value", 0) for ch in (entry.get("volume") or {}).values() if isinstance(ch, dict)]
    return round(max(vals) * 100 / 65536) if vals else 0


GLYPH_SPEAKER, GLYPH_HEADPHONES, GLYPH_HEADSET = "\U000f04c3", "\U000f02cb", "\U000f02ce"
GLYPH_TV, GLYPH_MIC, GLYPH_USB = "\U000f0502", "\U000f036c", "\U000f0553"


def device_glyph(entry: dict, kind: str) -> str:
    p = entry.get("properties") or {}
    words = " ".join(str(p.get(k, "")) for k in ("device.icon_name", "device.form_factor", "device.bus",
                                                   "device.profile.description", "node.name")).lower()
    if "hdmi" in words or "displayport" in words or "tv" in words.split():
        return GLYPH_TV
    if "bluez" in words or "bluetooth" in words or "headset" in words:
        return GLYPH_HEADSET if kind == "sink" else GLYPH_MIC
    if kind == "source":
        return GLYPH_MIC
    if "headphone" in words:
        return GLYPH_HEADPHONES
    return GLYPH_SPEAKER


def names(entry: dict) -> tuple[str, str]:
    """A device row's two lines. "Ryzen HD Audio Controller Headphones" is the card's
    name and the port's: then the port is the name ("Headphones") and the card goes
    under it. Otherwise the description, and under it the port and the bus."""
    p = entry.get("properties") or {}
    desc = entry.get("description") or entry.get("name", "")
    card = p.get("device.description") or ""
    port = next((prt.get("description") or "" for prt in entry.get("ports") or []
                 if prt.get("name") == entry.get("active_port")), "")
    bus = p.get("device.bus") or ""
    bus = "" if bus == "pci" else bus
    if card and port and desc == f"{card} {port}":
        return port, " · ".join(w for w in (card, bus) if w)
    return desc, " · ".join(w for w in (port or p.get("device.profile.description") or "", bus) if w)


def parse_devices(raw: str, kind: str) -> list[Dev]:
    out = []
    for e in json.loads(raw or "[]"):
        name = e.get("name", "")
        if kind == "source" and (name.endswith(".monitor") or (e.get("properties") or {}).get(
                "device.class") == "monitor"):
            continue
        desc, sub = names(e)
        out.append(Dev(kind, int(e.get("index", -1)), name, desc, volume(e), bool(e.get("mute")), sub=sub,
                       glyph=device_glyph(e, kind)))
    return out


def parse_streams(raw: str) -> list[Dev]:
    out = []
    for e in json.loads(raw or "[]"):
        p = e.get("properties") or {}
        app = (p.get("application.name") or p.get("application.process.binary") or p.get("node.name")
               or "stream")
        media = p.get("media.name") or ""
        if media == app:
            media = ""
        out.append(Dev("app", int(e.get("index", -1)), p.get("application.process.binary") or app, app,
                       volume(e), bool(e.get("mute")), sub=media, glyph=app_glyph(p),
                       sink=int(e.get("sink", -1)), corked=bool(e.get("corked"))))
    return out


APP_GLYPHS = (("firefox", "\U000f0239"), ("chrom", "\U000f02af"), ("spotify", "\U000f04c7"),
              ("vlc", "\U000f057c"), ("mpv", "\U000f0fce"), ("discord", "\U000f066f"),
              ("telegram", "\uf2c6"), ("slack", "\U000f04b1"), ("zoom", "\U000f0567"),
              ("steam", "\U000f04d3"), ("teams", "\U000f02bb"), ("speech", "\U000f050c"))
GLYPH_APP = "\U000f075a"  # a note


def app_glyph(props: dict) -> str:
    words = " ".join(str(props.get(k, "")) for k in ("application.name", "application.process.binary",
                                                       "application.icon_name", "application.id")).lower()
    return next((g for key, g in APP_GLYPHS if key in words), GLYPH_APP)


class Pulse:
    def __init__(self):
        self.sinks: list[Dev] = []
        self.sources: list[Dev] = []
        self.streams: list[Dev] = []
        self.default_sink = ""
        self.default_source = ""
        self.read_once = False
        self.want_streams = False  # the panel is open: read the streams too
        self.changed = None        # main-loop callback after new data (set by watch)
        self.error = ""
        self._dirty = {"sink", "source", "sink-input", "server"}
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    # -- reading ---------------------------------------------------------------

    @staticmethod
    def _pactl(*args: str) -> str:
        try:
            return subprocess.run(["pactl", "-f", "json", *args], capture_output=True, text=True,
                                  timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def read(self, kinds: set[str] | None = None) -> None:
        """Re-read what `kinds` names (all by default). Blocking: the reader thread, or
        a one-off render."""
        kinds = {"sink", "source", "sink-input", "server"} if kinds is None else kinds
        try:
            if "server" in kinds or not self.read_once:
                raw = self._pactl("info")
                if not raw:  # no server: say so, show nothing stale
                    self.sinks, self.sources, self.streams = [], [], []
                    self.error, self.read_once = "no sound server", True
                    return
                info = json.loads(raw)
                self.default_sink = info.get("default_sink_name", self.default_sink)
                self.default_source = info.get("default_source_name", self.default_source)
            if "sink" in kinds:
                self.sinks = parse_devices(self._pactl("list", "sinks"), "sink")
            if "source" in kinds:
                self.sources = parse_devices(self._pactl("list", "sources"), "source")
            if "sink-input" in kinds and (self.want_streams or not self.read_once):
                self.streams = parse_streams(self._pactl("list", "sink-inputs"))
            self.read_once = True
            self.error = ""
        except (ValueError, TypeError, AttributeError) as err:
            self.error = "pactl said something odd"
            core.log(f"pulse: {err!r}")

    def ensure(self) -> None:
        if not self.read_once:
            self.read()

    def watch(self, changed) -> None:
        """Start the event feed and the reader. `changed` runs on the main loop after
        every read."""
        self.changed = changed
        threading.Thread(target=self._feed, daemon=True, name="pactl-subscribe").start()
        threading.Thread(target=self._reader, daemon=True, name="pactl-read").start()

    def poke(self, kinds: set[str] | None = None) -> None:
        with self._lock:
            self._dirty |= kinds or {"sink", "source", "sink-input", "server"}
        self._wake.set()

    def _feed(self) -> None:
        """`pactl subscribe`, for ever: restart it when PulseAudio restarts (backing off)."""
        wait = 1.0
        while True:
            started = time.monotonic()
            try:
                self._proc = subprocess.Popen(
                    ["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL, text=True, bufsize=1,
                    preexec_fn=lambda: _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGTERM))
                self.poke()  # (re)connected: everything may have changed meanwhile
                for line in self._proc.stdout:
                    # "Event 'change' on sink-input #42". Clients come and go with
                    # every pactl (ours too), modules and cards follow the devices:
                    # only the kinds the panel shows wake the reader.
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] == "Event":
                        kind = parts[3]
                        if kind in ("sink", "source", "server") or (kind == "sink-input" and self.want_streams):
                            self.poke({kind})
                self._proc.wait()
            except OSError as err:
                core.log(f"pactl subscribe: {err!r}")
            self.error = "no sound server"
            wait = 1.0 if time.monotonic() - started > 30 else min(30.0, wait * 2)
            time.sleep(wait)

    def _reader(self) -> None:
        gap = 1.0 / READS_PER_S
        while True:
            self._wake.wait()
            started = time.monotonic()
            with self._lock:
                kinds, self._dirty = self._dirty, set()
                self._wake.clear()
            if kinds:
                self.read(kinds)
                if self.changed is not None:
                    from gi.repository import GLib

                    GLib.idle_add(lambda: self.changed() or False)
            # Debounce: a held volume key sends a burst; read at most READS_PER_S a
            # second, and what came in meanwhile in one go after the gap.
            time.sleep(max(0.0, gap - (time.monotonic() - started)))

    # -- acting (pactl on a thread; the event that follows brings the state) ------

    @staticmethod
    def run(*cmds: list[str]) -> None:
        def go():
            for argv in cmds:
                try:
                    subprocess.run(["pactl", *argv], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    pass

        threading.Thread(target=go, daemon=True).start()

    VERB = {"sink": "sink", "source": "source", "app": "sink-input"}

    def set_volume(self, d: Dev, pct: int) -> None:
        d.vol = max(0, pct)  # at once on screen; the event confirms it
        self.run([f"set-{self.VERB[d.kind]}-volume", str(d.index), f"{d.vol}%"])

    def step(self, d: Dev, delta: int) -> None:
        """±delta %, never past 100 from here (above 100 was set elsewhere: only down)."""
        if delta > 0:
            pct = min(max(d.vol, 100), d.vol + delta) if d.vol < 100 else d.vol
        else:
            pct = max(0, d.vol + delta)
        if pct != d.vol:
            self.set_volume(d, pct)

    def toggle_mute(self, d: Dev) -> None:
        d.mute = not d.mute
        self.run([f"set-{self.VERB[d.kind]}-mute", str(d.index), "1" if d.mute else "0"])

    def make_default(self, d: Dev) -> None:
        """The default sink (and every stream moved to it), or the default source."""
        if d.kind == "sink":
            self.default_sink = d.name
            self.run(["set-default-sink", d.name],
                     *(["move-sink-input", str(s.index), d.name] for s in self.streams))
        elif d.kind == "source":
            self.default_source = d.name
            self.run(["set-default-source", d.name])

    # -- what the strip shows ----------------------------------------------------

    def sink(self) -> Dev | None:
        return next((d for d in self.sinks if d.name == self.default_sink), self.sinks[0] if self.sinks else None)

    def source(self) -> Dev | None:
        return next((d for d in self.sources if d.name == self.default_source), None)

    def sink_desc(self, index: int) -> str:
        d = next((d for d in self.sinks if d.index == index), None)
        return d.desc if d else ""
