"""Power: battery and power profile on the strip; in the panel the battery's last 24 h
(upower's own history), its draw and health, and the profile and boost switches.

The switches run power-profile.sh's and cpu-boost.sh's clicks (they sudo-tee sysfs)."""

from __future__ import annotations

import glob
import os
import time

from . import core
from .core import Hits, button, heading, rgba, text
from .deck import Panel
from .sample import Sampler

PROFILE = {
    "low-power": ("󰌪", "lo", "aqua"),
    "balanced": ("󰛲", "bal", "warn"),
    "performance": ("󱐋", "hi", "hit"),
}


def bat_glyph(cap: int, status: str) -> str:
    if status == "Charging":
        return "󰂄"
    return "󰁺󰁻󰁼󰁽󰁾󰁿󰂀󰂁󰂂󰁹"[min(9, max(0, cap // 10))]


def bat_tone(cap: int, status: str) -> str:
    if status == "Charging":
        return "warn"
    if cap <= 10:
        return "hit"
    if cap <= 25:
        return "orange"
    return "ok" if cap > 50 else "warn"


def history(hours: float = 24) -> list[tuple[float, float]]:
    """upower's charge history of the laptop battery: (time, percent)."""
    files = [f for f in glob.glob("/var/lib/upower/history-charge-*.dat") if ":" not in os.path.basename(f)]
    if not files:
        return []
    path = max(files, key=os.path.getsize)
    since = time.time() - hours * 3600
    out = []
    for line in core.read(path).splitlines():
        parts = line.split("\t")
        try:
            t, v = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            continue
        if t >= since and v > 0:
            out.append((t, v))
    return out


class PowerStrip:
    name = "power"

    def __init__(self, s: Sampler):
        self.s = s

    def key(self, variant: str):
        s = self.s
        return (s.bat.get("capacity"), s.bat.get("status"), s.ac, s.profile, s.boost)

    def draw(self, variant: str, scale: int):
        s = self.s
        c = core.StripCanvas(scale)
        if s.bat:
            cap = int(s.bat.get("capacity") or 0)
            status = s.bat.get("status", "")
            tone = bat_tone(cap, status)
            c.icon(bat_glyph(cap, status), tone, 15, after=3)
            c.text(f"{cap}%", tone)
            if s.ac and status != "Charging":
                c.icon("", "dim", 12, after=0)  # plugged in, held at the charge limit
            c.gap(10)
        glyph, label, tone = PROFILE.get(s.profile, ("?", s.profile or "?", "fg"))
        c.icon(glyph, tone, 15, after=2 if variant == "full" else 0)
        if variant == "full":
            c.text(label, tone)
        if s.boost == "1":
            c.gap(6)
            c.icon("󰓅", "hit", 14, after=0)
        return c.finish()


class PowerPanel(Panel):
    name = "power"
    live = 2.0
    W = 470

    def __init__(self, s: Sampler):
        self.s = s
        self.hist: list[tuple[float, float]] = []
        self.hist_at = 0.0

    def size(self):
        return self.W, 330

    def opened(self) -> None:
        if time.time() - self.hist_at > 60:
            self.hist, self.hist_at = history(), time.time()

    def draw(self, cr, hits: Hits) -> None:
        s = self.s
        W, P = self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        y = 12
        b = s.bat
        if b:
            cap = int(b.get("capacity") or 0)
            status = b.get("status", "")
            tone = bat_tone(cap, status)
            core.icon(cr, P, y + 13, bat_glyph(cap, status), 24, tone)
            bw = text(cr, P + 30, y - 2, f"{cap}%", 26, tone, bold=True)
            text(cr, P + 40 + bw, y + 2, status.lower() + (" · on AC" if s.ac else ""), 13, "title")
            try:
                watts = int(b.get("power_now") or 0) / 1e6
                now_e, full_e, design = (int(b.get(k) or 0) for k in ("energy_now", "energy_full",
                                                                       "energy_full_design"))
            except ValueError:
                watts, now_e, full_e, design = 0, 0, 0, 0
            parts = []
            if watts > 0.1:
                parts.append(f"{watts:.1f} W")
                if status == "Discharging":
                    parts.append(f"{core.dur(now_e / 1e6 / watts * 3600)} left")
                elif status == "Charging" and full_e > now_e:
                    parts.append(f"full in {core.dur((full_e - now_e) / 1e6 / watts * 3600)}")
            if design:
                parts.append(f"health {100 * full_e / design:.0f}%")
            limit = core.read(f"{s.bat_dir}/charge_control_end_threshold")
            if limit:
                parts.append(f"stops at {limit}%")
            text(cr, P + 40 + bw, y + 20, " · ".join(parts), 12, "dim")
        else:
            text(cr, P, y, "no battery", 18, "dim", bold=True)
        y += 52

        heading(cr, P, y, "last 24 h", W - 2 * P)
        y += 20
        gx, gw, gh = P, W - 2 * P, 70
        core.graph(cr, gx, y, gw, gh, [], grid=(25, 50, 75))
        if self.hist:
            t0 = time.time() - 24 * 3600
            pts = [(gx + (t - t0) / (24 * 3600) * gw, y + gh - v / 100 * gh) for t, v in self.hist]
            cr.move_to(pts[0][0], y + gh)
            for p in pts:
                cr.line_to(*p)
            cr.line_to(pts[-1][0], y + gh)
            cr.close_path()
            cr.set_source_rgba(*rgba("ok", 0.22))
            cr.fill()
            cr.move_to(*pts[0])
            for p in pts[1:]:
                cr.line_to(*p)
            cr.set_source_rgba(*rgba("ok"))
            cr.set_line_width(1.3)
            cr.stroke()
        for h in (6, 12, 18):
            text(cr, gx + gw - h / 24 * gw, y + gh + 2, f"-{h}h", 10, "dim", align=0.5)
        y += gh + 26

        heading(cr, P, y, "power profile", W - 2 * P)
        y += 20
        x = P
        for prof in (s.profiles or list(PROFILE)):
            glyph, label, tone = PROFILE.get(prof, ("", prof, "fg"))
            x += button(cr, hits, x, y, prof, lambda p=prof: core.menu_action("power-profile.sh", 1, p)
                        or self.s.poke(), on=prof == s.profile, tone=tone, glyph=glyph) + 8
        y += 36
        heading(cr, P, y, "cpu", W - 2 * P)
        y += 20
        x = P
        if s.boost is not None:
            on = s.boost == "1"
            x += button(cr, hits, x, y, "turbo boost " + ("on" if on else "off"),
                        lambda: core.menu_action("cpu-boost.sh", 1) or None, on=on, tone="hit", glyph="󰓅") + 8
        if s.cap is not None:
            x += button(cr, hits, x, y, f"cap {s.cap}%", lambda: core.menu_action("cpu-cap.sh", 3) or None,
                        glyph="󰈐") + 8
        button(cr, hits, x, y, "upower details", lambda: core.menu_action("battery.sh", 3) or True, glyph="󰂄")
