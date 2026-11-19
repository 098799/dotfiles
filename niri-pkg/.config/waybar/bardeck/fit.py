"""Fit: the bar sheds detail when its pills do not fit the screen, and takes it back
when they do again.

The daemon knows every strip's width, so each tick it adds up a bar (the workspace
strip of the tightest output, every other strip, the tray, the gaps) and compares it
with the output's width. Too wide: the next step of STEPS is applied (a pill drawn in
its compact form, or not at all) until the bar fits. Room again (the step's saving
plus HYSTERESIS): the last step is taken back. Nothing is lost: every panel still
opens from its pill, and a pill that is off has a key or a menu entry.

The order is the whole policy: what goes first is what matters least on the bar.
"""

from __future__ import annotations

import time

from .core import BAR_MARGIN_X

# Per bar: (strip, the variant to draw it in, or None = no pill), least needed first.
STEPS = {
    "full": (
        ("wallpaper", None),     # a thumbnail; Mod+BackSpace has "Wallpaper: choose…"
        ("net", "compact"),      # the traffic graph and the VPN's name go; the link icon stays
        ("audio", "compact"),    # the song's title goes
        ("next", "compact"),     # the meeting's title is cut shorter
        ("sys", "compact"),      # a shorter CPU graph, no memory bar
        ("clock", "compact"),    # the date goes
        ("quota", "compact"),
    ),
    # The laptop's bar is compact already: only whole pills are left to drop.
    "compact": (
        ("wallpaper", None),
        ("disp", None),          # Mod+BackSpace has the screen layouts
    ),
}

# The strips of a bar besides ws (config.jsonc: modules-left, -center, -right).
STRIPS = ("quota", "next", "sys", "net", "dev", "cam", "audio", "power", "disp", "wallpaper",
          "notif", "clock")
# GTK's box spacing ("spacing": 2): 2 gaps in the left box, 10 in the right one.
GAPS = 2 * 12
HYSTERESIS = 24  # px of room past a step's saving before it is taken back
SAFETY = 6       # px kept free: the tray's width is an estimate

# The tray pill (style.css #tray, config.jsonc "tray"): icon, spacing, padding + margin.
TRAY = {"full": (20, 10, 34), "compact": (16, 8, 24)}
TRAY_EVERY_S = 15.0
_tray: tuple[float, int] = (0.0, 4)


def tray_items() -> int:
    """How many tray icons there are: the StatusNotifierWatcher's count, asked every
    TRAY_EVERY_S. A hidden (passive) item is counted too: the estimate errs wide."""
    global _tray
    now = time.monotonic()
    if now - _tray[0] < TRAY_EVERY_S:
        return _tray[1]
    n = _tray[1]
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        got = bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                            "org.freedesktop.DBus.Properties", "Get",
                            GLib.Variant("(ss)", ("org.kde.StatusNotifierWatcher",
                                                  "RegisteredStatusNotifierItems")),
                            None, Gio.DBusCallFlags.NO_AUTO_START, 200, None)
        n = len(got.unpack()[0])
    except Exception:
        pass  # no watcher (waybar is starting): keep the last count
    _tray = (now, n)
    return n


def tray_px(variant: str) -> float:
    n = tray_items()
    if n == 0:
        return 0.0
    icon, gap, around = TRAY[variant]
    return n * icon + (n - 1) * gap + around


def drawn_as(strip: str, variant: str, applied: int) -> str | None:
    """The variant to draw this strip in with the first `applied` steps on; None = no pill."""
    for name, to in STEPS.get(variant, ())[:applied]:
        if name == strip:
            return to
    return variant


def overflow(variant: str, widths: dict[str, float], ws_widths: list[tuple[float, float]]) -> float | None:
    """How many px the tightest bar of this variant is too wide (negative: its room).
    widths: bar px per "<strip>-<variant>"; ws_widths: (the output's width, its
    workspace strip's width) per output with this bar. None when there is none."""
    if not ws_widths:
        return None
    rest = sum(widths.get(f"{s}-{variant}", 0.0) for s in STRIPS)
    rest += tray_px(variant) + GAPS + 2 * BAR_MARGIN_X + SAFETY
    return max(ws + rest - out for out, ws in ws_widths)
