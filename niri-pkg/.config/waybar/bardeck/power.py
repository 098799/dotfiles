"""Power: battery and power profile on the strip; in the panel the battery's last 24 h
(upower's own history), its draw and health, and the profile and boost switches.
The battery's charge limit and the keyboard light (charge.py). Also what keeps the
machine awake or busy: caffeine (caffeine.py: a cup on the strip), what closing the
lid does (lid.py: a laptop on the strip while it does nothing; the CPU guard)
and a screen recording that runs (recording.py: a red dot and its time on the strip,
the file and a stop button in the panel).

The switches run power-profile.sh's and cpu-boost.sh's clicks (they sudo-tee sysfs)."""

from __future__ import annotations

import glob
import os
import time

from . import charge, core, lid, recording
from .caffeine import MODES as CAFFEINE_MODES
from .caffeine import Caffeine
from .charge import Charge
from .lid import Lid
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


GLYPH_CUP = "\U000f0176"
GLYPH_STOP = "\uf04d"
GLYPH_LAPTOP = "\U000f0322"


def rec_dot(cr, x: float, mid: float, r: float, rec: recording.Recording) -> float:
    """The recording's mark: a red dot (amber, hollow, while its picker is up). Returns the width."""
    cr.new_sub_path()
    cr.arc(x + r, mid, r - (0.75 if rec.picking else 0), 0, 6.2832)
    if rec.picking:
        cr.set_source_rgba(*rgba("warn"))
        cr.set_line_width(1.5)
        cr.stroke()
    else:
        cr.set_source_rgba(*rgba("hit"))
        cr.fill()
    return 2 * r


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
    """Drawn every second when its inputs change: a recording's time is one of them."""

    name = "power"

    def __init__(self, s: Sampler, caffeine: Caffeine, lid: Lid):
        self.s = s
        self.caffeine = caffeine
        self.lid = lid
        self.rec: recording.Recording | None = None
        self.rec_at = 0.0

    def current(self) -> recording.Recording | None:
        now = time.monotonic()
        if now - self.rec_at >= 0.5:  # once per tick, not once per variant
            self.rec, self.rec_at = recording.current(), now
        return self.rec

    def key(self, variant: str):
        s = self.s
        self.caffeine.check()
        rec = self.current()
        return (s.bat.get("capacity"), s.bat.get("status"), s.ac, s.profile, s.boost, self.caffeine.mode,
                self.lid.mode(), rec and (rec.kind, int(rec.elapsed())))

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
        if self.caffeine.on:
            c.gap(7)
            c.icon(GLYPH_CUP, "warn", 14, after=0)
        if self.lid.mode() == "ignore":
            c.gap(7)
            c.icon(GLYPH_LAPTOP, "warn", 14, after=0)  # closing the lid will not suspend
        rec = self.rec
        if rec is not None:
            c.gap(9)
            c.x += rec_dot(c.cr, c.x, core.MID, 4.5, rec) + 4
            if not rec.picking:
                c.text(recording.clock(rec.elapsed()), "hit", size=12, bold=True)
        return c.finish()


class PowerPanel(Panel):
    name = "power"
    live = 1.0  # a recording's clock
    W = 470

    def __init__(self, s: Sampler, caffeine: Caffeine, lid: Lid):
        self.s = s
        self.caffeine = caffeine
        self.lid = lid
        self.hist: list[tuple[float, float]] = []
        self.hist_at = 0.0
        self.rec: recording.Recording | None = None
        self.charge = Charge()

    def size(self):
        self.rec = recording.current()  # a recording's row comes and goes: three stat()s
        h = 356 + (56 if self.rec is not None else 0)
        h += 56 if self.charge.stop() is not None else 0
        h += 56 if charge.kbd() is not None else 0
        h += 56 if lid.has_lid() else 0
        return self.W, h

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
        y += 36
        y = self.draw_charge(cr, hits, P, y)
        y = self.draw_kbd(cr, hits, P, y)
        y = self.draw_caffeine(cr, hits, P, y)
        y = self.draw_lid(cr, hits, P, y)
        if self.rec is not None:
            self.draw_recording(cr, hits, P, y, self.rec)

    def draw_charge(self, cr, hits: Hits, P: float, y: float) -> float:
        """The stop thresholds (each saved for TLP, so it outlasts a reboot), and a full
        charge until the next boot."""
        W, ch = self.W, self.charge
        stop = ch.stop()
        if stop is None:
            return y
        saved = ch.saved()
        full = saved is not None and stop != saved  # a fullcharge (or a hand-run setcharge)
        st = ch.status
        words, tone = (st[1], st[0]) if st else (f"full charge until reboot · then {saved}%", "warn") if full \
            else ("saved for TLP: it stays after a reboot", "dim")
        ww = text(cr, W - P, y - 2, words, 12 if st or full else 11, tone, align=1) + 12
        heading(cr, P, y, "charge limit", W - 2 * P - ww)
        y += 20
        x = P
        limits = sorted(set(charge.LIMITS) | ({saved} if saved else set()))
        for lim in limits:
            x += button(cr, hits, x, y, f"{lim}%", lambda v=lim: ch.set_limit(v) or self.s.poke(),
                        on=lim == saved and not full, tone="ok" if lim < 100 else "warn") + 8
        x += 8
        if full:
            button(cr, hits, x, y, f"back to {saved}%", lambda: ch.restore() or self.s.poke(), glyph="󰁹")
        elif stop < 100:
            button(cr, hits, x, y, "full once", lambda: ch.full_once() or self.s.poke(), tone="warn", glyph="󰂅")
        return y + 36

    def draw_kbd(self, cr, hits: Hits, P: float, y: float) -> float:
        k = charge.kbd()
        if k is None:
            return y
        cur, top = k
        heading(cr, P, y, "keyboard light", self.W - 2 * P)
        y += 20
        x = P
        for level, label in charge.kbd_levels(top):
            x += button(cr, hits, x, y, label, lambda v=level: charge.set_kbd(v), on=level == cur,
                        tone="bg3" if level == 0 else "accent", glyph="󰌌" if level == top else None) + 8
        return y + 36

    def draw_caffeine(self, cr, hits: Hits, P: float, y: float) -> float:
        W = self.W
        caf = self.caffeine
        words = caf.error or caf.words()
        ww = text(cr, W - P, y - 2, words, 12, "hit" if caf.error else "warn", align=1) + 12 if words else 0
        heading(cr, P, y, "keep awake", W - 2 * P - ww)
        y += 20
        x = P
        x += button(cr, hits, x, y, "off", lambda: caf.set(""), on=not caf.on, tone="bg3") + 8
        for mode, label in CAFFEINE_MODES:
            if mode == "battery" and (not self.s.bat or caf.battery_low()):
                continue  # no battery (the desktop), or below the mark already
            x += button(cr, hits, x, y, label, lambda m=mode: caf.set(m), on=caf.mode == mode, tone="warn",
                        glyph=GLYPH_CUP if mode == "on" else None) + 8
        text(cr, x + 4, y + 4, "no lock, no screen off", 11, "dim")
        return y + 36

    def draw_lid(self, cr, hits: Hits, P: float, y: float) -> float:
        """Suspend or do nothing when the lid closes (on battery: logind's HandleLidSwitch).
        With "do nothing", a closed lid holds the CPU at its minimum (lid.py)."""
        if not lid.has_lid():
            return y
        W, ld = self.W, self.lid
        mode = ld.mode()
        st = ld.status
        if st:
            words, tone = st[1], st[0]
        elif ld.error:
            words, tone = f"cpu guard: {ld.error}", "hit"
        elif ld.guarding:
            words, tone = "closed: cpu held at minimum", "warn"
        else:
            words, tone = ld.ac_words(), "dim"
        ww = text(cr, W - P, y - 2, words, 12 if st or ld.error or ld.guarding else 11, tone, align=1) + 12 \
            if words else 0
        heading(cr, P, y, "lid close", W - 2 * P - ww)
        y += 20
        x = P
        for value, label in lid.MODES:
            x += button(cr, hits, x, y, label, lambda v=value: ld.set_mode(v) or self.s.poke(), on=mode == value,
                        tone="warn" if value == "ignore" else "ok",
                        glyph=GLYPH_LAPTOP if value == "ignore" else None) + 8
        if mode == "ignore":
            text(cr, x + 4, y + 4, f"closed: low power, no boost, ≤{lid.CAP_KHZ / 1e6:.1f} GHz", 11, "dim")
        return y + 36

    def draw_recording(self, cr, hits: Hits, P: float, y: float, rec: recording.Recording) -> None:
        W = self.W
        tone = "warn" if rec.picking else "hit"
        tw = text(cr, W - P, y - 3, "picking…" if rec.picking else recording.clock(rec.elapsed()), 13, tone,
                  bold=True, align=1) + 18
        rec_dot(cr, W - P - tw + 6, y + 6, 4.5, rec)
        heading(cr, P, y, f"recording · {rec.mode}", W - 2 * P - tw - 4)
        y += 20
        label = "cancel" if rec.picking else "stop"
        bw = core.text_w(cr, label, 12) + core.text_w(cr, GLYPH_STOP, 14, family=core.ICON_FONT) + 23
        button(cr, hits, W - P - bw, y, label, rec.stop, on=True, tone="hit", glyph=GLYPH_STOP)
        if rec.picking:
            words, wtone = "choose what to record (the share dialog or the region)", "dim"
        else:
            words, wtone = (rec.out or "?").replace(core.REAL_HOME, "~", 1), "title"
        text(cr, P, y + 3, words, 12, wtone, width=W - 2 * P - bw - 12)
