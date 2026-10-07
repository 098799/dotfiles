"""bardeck — the niri bar's engine: draws every strip, holds every panel.

    bardeck daemon                     waybar starts it (custom/bardeck); one per session
    bardeck css                        write theme.css for style.css (niri runs it before waybar)
    bardeck render FILE STRIP [compact] [--scale N] [--warm S]    a strip to a PNG
    bardeck panel FILE PANEL [--scale N] [--warm S]               a panel to a PNG
    BARDECK_TRACE=1 bardeck daemon     print how long each panel takes to open

STRIP / PANEL: quota sys net dev power clock (ws: strip only, one per output).

Waybar shows each strip with bar-strip.so (bar-strip.c), which loads the PNGs from
$XDG_RUNTIME_DIR/bardeck and sends hover / click / scroll to this daemon's socket
there (ctl). "full" strips are drawn at 1x (DP-1), "compact" ones at 2x (the
laptop's eDP-1 at scale 1.25); bar-strip.so's "scale" says the same.

Theme: the palette follows ~/.config/theme/state (core.load_theme). When it changes
the daemon writes theme.css and reloads waybar (SIGUSR2), which also restarts the
daemon, so every strip and panel comes back in the new colours.

Cadence: system every second, network and devices every 2 s, power every 5 s, the
clock on the minute, quota when rcmon's federation writes, workspaces when niri says
something changed. A picture is written only when it changed, and waybar is
signalled only then. Measured cost: see the README.
"""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import os
import signal
import socket
import sys
import time

from . import core
from .core import RUN_DIR

VARIANTS = (("full", 1), ("compact", 2))
THEME_CSS = f"{core.REAL_HOME}/.config/waybar/theme.css"


def write_css() -> bool:
    """theme.css for the current theme; True when it changed."""
    css = core.theme_css()
    if core.read(THEME_CSS) == css.strip():
        return False
    with open(f"{THEME_CSS}.tmp", "w") as fh:
        fh.write(css)
    os.replace(f"{THEME_CSS}.tmp", THEME_CSS)
    return True


def reload_waybar() -> None:
    core.signal_waybar(signal.SIGUSR2)


def build(with_ws: bool = True):
    """Every strip and panel, wired to one sampler."""
    from .clock import ClockPanel, ClockStrip
    from .devices import DevPanel, DevStrip
    from .net import NetPanel, NetStrip
    from .power import PowerPanel, PowerStrip
    from .sample import Sampler
    from .system import SysStrip, SystemPanel

    s = Sampler()
    try:  # quota imports ~/bin/qtop: a host without it still gets the rest of the bar
        from .quota import Quota, QuotaPanel
        quota = Quota()
    except Exception as err:
        core.log(f"no quota strip: {err!r}")
        quota = None
    strips = {
        "sys": (SysStrip(s), 1),
        "net": (NetStrip(s), 2),
        "dev": (DevStrip(s), 2),
        "power": (PowerStrip(s), 5),
        "clock": (ClockStrip(), 1),
    }
    panels = {p.name: p for p in (SystemPanel(s), NetPanel(s), DevPanel(s), PowerPanel(s), ClockPanel())}
    if quota is not None:
        panels["quota"] = QuotaPanel(quota)
    return s, quota, strips, panels


class Daemon:
    def __init__(self):
        from gi.repository import GLib

        from .deck import Deck
        from .ws import WsStrip

        self.GLib = GLib
        self.s, self.quota, self.strips, self.panels = build()
        self.deck = Deck(self.panels)
        self.ws = WsStrip(self.draw_ws)
        self.tick_n = 0
        self.dirty = False
        self.last_variants = None
        # The raw state, compared raw: a theme that falls back to gruvbox (no colors.d
        # file) must not look like a change on every tick, or waybar reloads for ever.
        self.theme = core.theme_key()
        if write_css():  # waybar started with another theme's colours
            reload_waybar()
        self.ws.load()
        self.draw_ws()
        self.tick()
        GLib.timeout_add(1000, self.tick)

    def variants(self):
        """Only the pictures a bar shows: compact while the laptop screen (eDP) is on,
        full while another screen is. Both when niri cannot say."""
        names = list(self.ws.outputs)
        if not names:
            return VARIANTS
        laptop = any(n.startswith("eDP") for n in names)
        other = any(not n.startswith("eDP") for n in names)
        return tuple(v for v in VARIANTS if (v[0] == "compact" and laptop) or (v[0] == "full" and other))

    def write(self, name: str, surf) -> None:
        if core.write_png(f"{RUN_DIR}/{name}.png", surf):
            self.dirty = True

    def tick(self) -> bool:
        t0 = time.perf_counter()
        n = self.tick_n
        self.tick_n += 1
        if n % 2 == 0 and core.theme_key() != self.theme:
            self.theme = core.theme_key()
            core.load_theme()
            core.log(f"theme {' '.join(core.THEME)}: reloading waybar")
            write_css()
            reload_waybar()  # restarts this daemon too: everything comes back in the new colours
            return True
        variants = self.variants()
        fresh = variants != self.last_variants  # a screen came or went: draw its bar now
        self.last_variants = variants
        if fresh and self.quota is not None:
            self.quota.seen = None
        try:
            self.s.tick()
            for name, (strip, every) in self.strips.items():
                if n % every == 0 or fresh:
                    for variant, scale in variants:
                        self.write(f"{name}-{variant}", strip.draw(variant, scale))
            if self.quota is not None and (n % 2 == 0 or fresh) and self.quota.changed():
                for variant, scale in variants:
                    self.write(f"quota-{variant}", self.quota.strips(variant, scale))
                self.deck.invalidate("quota")
        except Exception as err:  # keep the bar alive across one bad reading
            core.log(f"tick: {err!r}")
            if core.TRACE:
                import traceback
                traceback.print_exc()
        self.flush()
        if core.TRACE and n % 30 == 0:
            core.log(f"tick {n}: {(time.perf_counter() - t0) * 1000:.1f} ms")
        return True

    def draw_ws(self) -> None:
        for output, rect, variant in self.ws.files():
            scale = dict(VARIANTS)[variant]
            surf, hits = self.ws.draw(output, variant, scale)
            key = (rect["x"], rect["y"], variant)
            self.ws.hits[key] = hits
            self.ws.widths[key] = surf.get_width() / scale
            self.write(f"ws-{variant}@{rect['x']}_{rect['y']}", surf)
        self.flush()

    def flush(self) -> None:
        if self.dirty:
            self.dirty = False
            core.signal_waybar()

    def message(self, msg: str) -> None:
        parts = msg.split()
        if len(parts) < 7:
            return
        verb, strip = parts[0], parts[1]
        cx, mx, my, px = (int(v) for v in parts[2:6])
        variant = parts[6]
        if strip == "ws":
            key = (mx, my, variant)
            local = px - (cx - self.ws.widths.get(key, 0) / 2)
            if verb == "click":
                self.ws.click(key, local)
            elif verb in ("scroll-up", "scroll-down"):
                self.ws.scroll(verb == "scroll-up")
            return
        self.deck.message(verb, strip, float(cx), self.deck.monitor_at(mx, my))
        if verb == "click":
            self.s.poke()


def daemon() -> int:
    os.makedirs(RUN_DIR, exist_ok=True)
    libc = ctypes.CDLL("libc.so.6")
    libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG: go when waybar goes
    lock = open(f"{RUN_DIR}/daemon.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)  # both bars start one; the second waits here
    libc.prctl(15, b"bardeck", 0, 0, 0)  # PR_SET_NAME
    os.nice(5)

    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    d = Daemon()
    ctl = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    path = f"{RUN_DIR}/ctl"
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    ctl.bind(path)
    ctl.setblocking(False)

    # Act from an idle callback at default priority, never straight from a source
    # above GDK's: GDK starts a Wayland read in its source's prepare step, a
    # higher-priority dispatch skips the check step that finishes it, and the
    # layer-shell map then waits for that read for ever (seen: the first click froze
    # the daemon inside show_all).
    def on_ctl(*_args) -> bool:
        while True:
            try:
                msg = ctl.recv(256).decode(errors="replace")
            except BlockingIOError:
                return True
            GLib.idle_add(lambda msg=msg: d.message(msg) or False)

    GLib.io_add_watch(ctl.fileno(), GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN, on_ctl)
    Gtk.main()
    return 0


def render(argv: list[str]) -> int:
    """`render FILE STRIP [compact]` and `panel FILE PANEL`: draw one to a PNG."""
    scale = int(argv[argv.index("--scale") + 1]) if "--scale" in argv else 1
    warm = float(argv[argv.index("--warm") + 1]) if "--warm" in argv else 2.0
    os.makedirs(RUN_DIR, exist_ok=True)
    s, quota, strips, panels = build()
    end = time.time() + warm
    while True:
        s.tick()
        if time.time() >= end:
            break
        time.sleep(1)
    s._slow()
    out, what = argv[2], argv[3]
    if argv[1] == "render":
        variant = "compact" if "compact" in argv[4:] else "full"
        if what == "quota":
            quota.changed()
            surf = quota.strips(variant, scale)
        elif what == "ws":
            from .ws import WsStrip
            w = WsStrip(lambda: None)
            w.load()
            name = next(iter(w.outputs))
            surf, _ = w.draw(name, variant, scale)
        else:
            surf = strips[what][0].draw(variant, scale)
        surf.write_to_png(out)
        return 0
    import cairo

    p = panels[what]
    if what == "quota":
        quota.changed()
    if what == "sys":
        s.want_top = True
        s._top(time.monotonic())
        time.sleep(1)
        s._top(time.monotonic())
    p.opened()
    w, h = p.size()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w * scale, h * scale)
    surf.set_device_scale(scale, scale)
    p.draw(cairo.Context(surf), core.Hits())
    surf.write_to_png(out)
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "daemon":
        return daemon()
    if cmd == "css":
        write_css()
        return 0
    if cmd in ("render", "panel") and len(argv) > 3:
        return render(argv)
    print(__doc__, file=sys.stderr)
    return 2
