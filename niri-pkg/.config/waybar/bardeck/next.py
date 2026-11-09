"""Next: the bar's middle — the meeting on now, or the next one, as a countdown.

From the clock panel's agenda (agenda.py, the same iCalendar feeds): timed events
only, no all-day ones, up to LOOKAHEAD ahead (so tomorrow's first one shows in the
evening). On now: a dot in the calendar's colour, the title, the minutes left.
Next: the title and "in 25 min" (under 90 min) or its start time. Amber from
WARN_MIN before it starts. Nothing in the window: no pill at all.

Click: the event's meeting link (Meet, Zoom, Teams), when it has one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import cairo

from . import agenda as agenda_mod
from . import core
from .core import BAR_H, MID, px

LOOKAHEAD = timedelta(hours=12)
WARN_MIN = 5
SOON_MIN = 90       # under this: "in 25 min"; over it: "14:30"
TITLE_CHARS = {"full": 42, "compact": 20}  # the laptop bar is near full
GLYPH_CAL, GLYPH_VIDEO = "\U000f00ed", "\U000f0567"


def _mins(td: timedelta) -> int:
    return max(0, int(td.total_seconds() // 60))


def _short(title: str, variant: str) -> str:
    title, n = " ".join(title.split()), TITLE_CHARS[variant]
    return title if len(title) <= n else title[:n - 1] + "…"


class NextStrip:
    name = "next"

    def __init__(self, agenda: agenda_mod.Agenda):
        self.agenda = agenda

    def pick(self, now: datetime) -> tuple[str, agenda_mod.Event] | None:
        """("now", the event on now) or ("next", the next one in LOOKAHEAD)."""
        events = sorted((e for evs in self.agenda.days.values() for e in evs if not e.all_day),
                        key=lambda e: e.start)
        on = [e for e in events if e.start <= now < e.end]
        upcoming = [e for e in events if now < e.start <= now + LOOKAHEAD]
        # A meeting about to start beats the tail of the one you are in.
        if upcoming and (not on or upcoming[0].start - now <= timedelta(minutes=WARN_MIN)):
            return "next", upcoming[0]
        if on:
            return "now", min(on, key=lambda e: e.end)
        return None

    def key(self, variant: str):
        self.agenda.refresh()
        now = datetime.now().astimezone()
        got = self.pick(now)
        return now.strftime("%H%M"), got and (got[0], got[1].title, got[1].start), self.agenda.parsed_for

    def click(self) -> None:
        got = self.pick(datetime.now().astimezone())
        if got and got[1].url:
            core.spawn(["xdg-open", got[1].url])

    def draw(self, variant: str, scale: float):
        now = datetime.now().astimezone()
        got = self.pick(now)
        if got is None:
            empty = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, px(BAR_H, scale))
            empty.set_device_scale(scale, scale)
            return empty
        kind, e = got
        c = core.StripCanvas(scale)
        colour = e.colour or "blue"
        if kind == "now":
            c.cr.arc(c.x + 4, MID, 4, 0, 6.2832)
            c.cr.set_source_rgba(*core.rgba(colour))
            c.cr.fill()
            c.x += 14
            c.text(_short(e.title, variant), "title")
            c.gap(8)
            c.text(f"{_mins(e.end - now)} min left", "dim", size=12)
        else:
            left = e.start - now
            soon = left <= timedelta(minutes=WARN_MIN)
            tone = "warn" if soon else "fg"
            c.icon(GLYPH_VIDEO if e.url else GLYPH_CAL, "warn" if soon else colour, 14, after=6)
            c.text(_short(e.title, variant), "title" if soon else "fg")
            c.gap(8)
            m = _mins(left) + 1
            when = (f"in {m} min" if m < SOON_MIN else
                    (e.start.strftime("%H:%M") if e.start.date() == now.date() else e.start.strftime("tomorrow %H:%M")))
            c.text(when, tone, size=12, bold=soon)
        return c.finish()
