"""The clock in the middle of the bar; in its panel the time to the second, UTC, the
ISO week, and two months with week numbers. Pinned: u/p an earlier/later month."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone

from . import core
from .core import Hits, rgba, text
from .deck import Panel


class ClockStrip:
    name = "clock"

    def draw(self, variant: str, scale: int):
        now = datetime.now()
        c = core.StripCanvas(scale)
        if variant == "full":
            c.text(now.strftime("%a %d %b"), "fg")
            c.gap(10)
        c.text(now.strftime("%H:%M"), "bright", size=15, bold=True)
        if variant == "full":
            c.gap(8)
            c.text(f"w{now.isocalendar().week}", "dim", size=12)
        return c.finish()


class ClockPanel(Panel):
    name = "clock"
    live = 1.0
    W = 400

    def __init__(self):
        self.shift = 0

    def size(self):
        return self.W, 430

    def opened(self) -> None:
        self.shift = 0

    def key(self, key: str, ctrl: bool) -> bool:
        if key in ("u", "Left") or (ctrl and key == "b"):
            self.shift -= 1
        elif key in ("p", "Right") or (ctrl and key == "f"):
            self.shift += 1
        elif key in ("Home", "t"):
            self.shift = 0
        else:
            return False
        return True

    def draw(self, cr, hits: Hits) -> None:
        W, P = self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        now = datetime.now()
        utc = datetime.now(timezone.utc)
        y = 10
        tw = text(cr, P, y, now.strftime("%H:%M"), 34, "bright", bold=True)
        text(cr, P + tw + 4, y + 16, now.strftime(":%S"), 16, "dim")
        text(cr, W - P, y + 4, now.strftime("%A"), 14, "title", align=1)
        text(cr, W - P, y + 22, now.strftime("%-d %B %Y"), 13, "fg", align=1)
        y += 48
        iso = now.isocalendar()
        day = now.timetuple().tm_yday
        days = 366 if calendar.isleap(now.year) else 365
        text(cr, P, y, f"UTC {utc:%H:%M}", 12, "blue")
        text(cr, W / 2, y, f"week {iso.week}", 12, "fg", align=0.5)
        text(cr, W - P, y, f"day {day} of {days}", 12, "dim", align=1)
        y += 18
        # Year progress.
        core.bar(cr, P, y, W - 2 * P, 3, day / days, "bg3")
        y += 14

        first = date(now.year, now.month, 1)
        mi = (first.year * 12 + first.month - 1) + self.shift
        for k in range(2):
            yy, mm = divmod(mi + k, 12)
            mm += 1
            y = self.month(cr, P, y, W - 2 * P, yy, mm, now.date())
            y += 6
        text(cr, W / 2, self.size()[1] - 22, "click to pin · u/p month · t today", 11, "dim", align=0.5)

    def month(self, cr, x: float, y: float, w: float, year: int, month: int, today: date) -> float:
        text(cr, x, y, f"{calendar.month_name[month]} {year}", 14, "title", bold=True)
        y += 22
        cols = 8
        cw = w / cols
        for i, name in enumerate(("wk", "Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            text(cr, x + cw * i + cw / 2, y, name, 11, "dim" if i == 0 else ("purple" if i >= 6 else "fg"),
                 align=0.5)
        y += 16
        for week in calendar.Calendar(0).monthdatescalendar(year, month):
            text(cr, x + cw / 2, y + 2, str(week[0].isocalendar().week), 11, "bg3", align=0.5)
            for i, d in enumerate(week, start=1):
                cx = x + cw * i + cw / 2
                if d.month != month:
                    continue
                if d == today:
                    core.rrect(cr, cx - 12, y - 1, 24, 18, 6)
                    cr.set_source_rgba(*rgba("accent"))
                    cr.fill()
                    text(cr, cx, y + 1, str(d.day), 12, "bg", bold=True, align=0.5)
                else:
                    tone = "dim" if d < today else ("purple" if i >= 6 else "title")
                    text(cr, cx, y + 1, str(d.day), 12, tone, align=0.5)
            y += 19
        return y + (19 * (6 - len(calendar.Calendar(0).monthdatescalendar(year, month))))

