"""The clock in the middle of the bar; in its panel the time to the second, UTC, the
ISO week, and two months with week numbers; beside them the weather (weather.py,
MeteoSwiss) and today's and tomorrow's events (agenda.py, iCalendar feeds). Pinned:
u/p an earlier/later month, i/o an event, Enter opens its meeting link."""

from __future__ import annotations

import calendar
import time
from datetime import date, datetime, timedelta, timezone

from . import agenda, core, weather
from .core import Hits, button, heading, rgba, text
from .deck import Panel

GLYPH_VIDEO, GLYPH_RAIN, GLYPH_SUN = "\U000f0567", "\U000f054a", "\U000f059c"


class ClockStrip:
    name = "clock"

    def key(self, variant: str):
        return datetime.now().strftime("%Y%m%d%H%M")

    def draw(self, variant: str, scale: int):
        now = datetime.now()
        c = core.StripCanvas(scale)
        if variant == "full":
            c.text(now.strftime("%a %d %b"), "fg")
            c.gap(10)
        c.text(now.strftime("%H:%M"), "bright", size=15, bold=True)  # the week: in the panel
        return c.finish()


class ClockPanel(Panel):
    """Left: the clock and two months. Right: the weather, then today and tomorrow."""

    name = "clock"
    live = 1.0
    W = 400       # the clock and months column
    SIDE = 372    # the weather and agenda column beside it
    YEAR_W = 780
    ROW_H = 22
    TODAY_ROWS = 7     # events shown per day; the rest are counted
    TOMORROW_ROWS = 4
    WEATHER_H = 172
    POLL_EVERY = 30.0  # seconds between looks at the feeds' ages while open

    def __init__(self):
        self.shift = 0
        self.year = False  # y: the whole year
        self.weather = weather.Weather()
        self.agenda = agenda.Agenda()
        self.sel = -1      # the keyboard's event (index into shown())
        self.hovered = -1
        self.rows: list[tuple[float, float, int]] = []
        self.polled = 0.0

    def shown(self) -> list[agenda.Event]:
        """The event rows on screen, top to bottom (today's, then tomorrow's)."""
        today = date.today()
        days = self.agenda.days
        return (days.get(today, [])[:self.TODAY_ROWS]
                + days.get(today + timedelta(1), [])[:self.TOMORROW_ROWS])

    def side_h(self) -> float:
        h = 12 + self.WEATHER_H
        if not self.agenda.configured:
            return h + 2 * 22 + 3 * 15 + 40
        today = date.today()
        for d, cap in ((today, self.TODAY_ROWS), (today + timedelta(1), self.TOMORROW_ROWS)):
            evs = self.agenda.days.get(d, [])
            h += 22 + max(1, min(cap, len(evs))) * self.ROW_H + (14 if len(evs) > cap else 0) + 6
        return h + (14 if self.agenda.error else 0) + 34

    def size(self):
        if self.year:
            return self.YEAR_W, 556
        return self.W + self.SIDE, max(430, int(self.side_h()))

    def poll(self, force: bool = False) -> None:
        """Start a fetch or a parse when one is due (each on its own thread)."""
        self.polled = time.monotonic()
        self.weather.fetch(force)
        self.agenda.refresh(force)

    def opened(self) -> None:
        self.shift, self.year, self.sel, self.hovered = 0, False, -1, -1
        self.poll()

    def open_event(self, e: agenda.Event) -> bool:
        if not e.url:
            return False
        core.spawn(["xdg-open", e.url])
        return True  # close the panel: the browser wants the screen

    def alternate(self) -> bool:
        self.year, self.shift = not self.year, 0
        return True

    def key(self, key: str, ctrl: bool) -> bool | str:
        step = 12 if self.year else 1
        evs = [] if self.year else self.shown()
        if evs and (key in ("i", "Down", "o", "Up", "k", "l") or (ctrl and key in ("n", "p"))):
            jump = {"i": 1, "Down": 1, "n": 1, "o": -1, "Up": -1, "p": -1, "k": 4, "l": -4}[key]
            self.sel = max(0, min(len(evs) - 1, self.sel + jump if self.sel >= 0 else (0 if jump > 0 else len(evs) - 1)))
            return True
        if key in ("Return", "KP_Enter") and 0 <= self.sel < len(evs):
            return "close" if self.open_event(evs[self.sel]) else True
        if key == "r":
            self.poll(force=True)
            return True
        if key == "y":
            self.year = not self.year
            self.shift = 0
        elif key in ("u", "Left") or (ctrl and key == "b"):
            self.shift -= step
        elif key in ("p", "Right") or (ctrl and key == "f"):
            self.shift += step
        elif key in ("Home", "t"):
            self.shift = 0
        else:
            return False
        return True

    def hover(self, x: float, y: float) -> bool:
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and x >= self.W), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    def draw(self, cr, hits: Hits) -> None:
        if self.year:
            self.draw_year(cr)
            return
        if time.monotonic() - self.polled >= self.POLL_EVERY:
            self.poll()
        W, P = self.W, 16
        H = self.size()[1]
        core.panel_frame(cr, W + self.SIDE, H)
        cr.rectangle(W, 14, 1, H - 50)
        cr.set_source_rgba(*rgba("bg2"))
        cr.fill()
        self.draw_side(cr, hits, W + 16, W + self.SIDE - 16)
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
        text(cr, (W + self.SIDE) / 2, H - 22,
             "click to pin · u/p month · y year · t today · i/o event · Enter join · r refresh", 11, "dim",
             align=0.5)

    def draw_year(self, cr) -> None:
        """Twelve months, four across, with week numbers; u/p a year."""
        W, H = self.size()
        P = 16
        core.panel_frame(cr, W, H)
        now = datetime.now()
        year = now.year + self.shift // 12
        text(cr, P, 10, str(year), 24, "bright", bold=True)
        iso = now.isocalendar()
        text(cr, W - P, 16, f"today {now:%a %-d %b} · week {iso.week}", 12, "fg", align=1)
        cols, gap = 4, 14
        mw = (W - 2 * P - gap * (cols - 1)) / cols
        for m in range(12):
            mx = P + (m % cols) * (mw + gap)
            my = 50 + (m // cols) * 160
            self.mini(cr, mx, my, mw, year, m + 1, now.date())
        text(cr, W / 2, H - 22, "u/p year · y two months · t this year", 11, "dim", align=0.5)

    def mini(self, cr, x: float, y: float, w: float, year: int, month: int, today: date) -> None:
        cur = (year, month) == (today.year, today.month)
        text(cr, x, y, calendar.month_name[month], 13, "accent" if cur else "title", bold=True)
        y += 19
        cw = w / 8
        for i, name in enumerate(("wk", "M", "T", "W", "T", "F", "S", "S")):
            text(cr, x + cw * i + cw / 2, y, name, 10, "bg3" if i == 0 else ("purple" if i >= 6 else "dim"),
                 align=0.5)
        y += 14
        for week in calendar.Calendar(0).monthdatescalendar(year, month):
            text(cr, x + cw / 2, y, str(week[0].isocalendar().week), 10, "bg3", align=0.5)
            for i, d in enumerate(week, start=1):
                if d.month != month:
                    continue
                cx = x + cw * i + cw / 2
                if d == today:
                    core.rrect(cr, cx - 10, y - 1, 20, 15, 5)
                    cr.set_source_rgba(*rgba("accent"))
                    cr.fill()
                    text(cr, cx, y, str(d.day), 11, "bg", bold=True, align=0.5)
                else:
                    tone = "dim" if d < today else ("purple" if i >= 6 else "title")
                    text(cr, cx, y, str(d.day), 11, tone, align=0.5)
            y += 16

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


    # -- the side column: weather and agenda -----------------------------------

    def draw_side(self, cr, hits: Hits, x0: float, x1: float) -> None:
        y = self.draw_weather(cr, x0, x1, 12)
        self.draw_agenda(cr, hits, x0, x1, y)

    def draw_weather(self, cr, x0: float, x1: float, y: float) -> float:
        """Now, today's range and the next 12 hours. Returns the y under it."""
        wx = self.weather
        w = x1 - x0
        end = y + self.WEATHER_H
        age = ""
        if wx.data and (wx.age >= weather.STALE or wx.error):
            age = f"{wx.error + ' · ' if wx.error else ''}{core.ago(wx.age)} old"
        elif wx.busy:
            age = "updating…"
        aw = text(cr, x1, y - 1, age, 11, "warn" if wx.error or wx.age >= weather.STALE else "dim", align=1) + 8 \
            if age else 0
        heading(cr, x0, y, f"weather · {wx.name}", w - aw)
        y += 24
        cur = wx.current()
        if not cur:
            words = "fetching the weather…" if wx.busy else (
                f"no weather ({wx.error})" if wx.error else "no weather yet")
            text(cr, x0, y + 4, words, 12, "dim")
            return end
        word, glyph, tone = weather.symbol(cur.get("code"))
        core.icon(cr, x0 + 16, y + 20, glyph, 32, tone, align=0.5)
        tw = text(cr, x0 + 40, y, f"{cur.get('temp') or 0:.0f}°", 30, "bright", bold=True)
        tx = x0 + 40 + tw + 10
        day = wx.today()
        text(cr, tx, y + 4, word, 13, "title", width=x1 - tx - 96)
        if cur.get("wind") is not None:
            wind = f"wind {cur['wind']:.0f} km/h" + (f" · gusts {cur['gust']:.0f}" if cur.get("gust") else "")
            text(cr, tx, y + 22, wind, 11, "dim", width=x1 - tx - 96)
        if day:
            rx = x1
            rx -= text(cr, rx, y + 2, f"{day['min']:.0f}°", 13, "blue", align=1) + 4
            rx -= text(cr, rx, y + 2, "↓", 12, "dim", align=1) + 8
            rx -= text(cr, rx, y + 2, f"{day['max']:.0f}°", 13, "orange", align=1) + 4
            text(cr, rx, y + 2, "↑", 12, "dim", align=1)
            rain = day.get("rain") or 0
            rw = text(cr, x1, y + 21, f"{rain}%", 12, "blue" if rain >= 30 else "dim", align=1)
            core.icon(cr, x1 - rw - 3, y + 28, GLYPH_RAIN, 12, "blue" if rain >= 30 else "dim", align=1)
        y += 46

        # The next 12 hours: hour, icon, temperature, and the chance of rain as a bar.
        hours = wx.hours(12)
        if hours:
            cw = w / len(hours)
            temps = [h.temp for h in hours]
            lo_t, hi_t = min(temps), max(temps)
            dry = all(h.rain < 5 for h in hours)
            if dry:
                text(cr, (x0 + x1) / 2, y + 69, "no rain in the next 12 h", 10, "dim", align=0.5, valign=0.5)
            for i, h in enumerate(hours):
                cx = x0 + cw * i + cw / 2
                label = "now" if i == 0 else h.at.strftime("%H")
                text(cr, cx, y, label, 10, "accent" if i == 0 else "dim", align=0.5)
                _, g, tone = weather.symbol(h.code)
                core.icon(cr, cx, y + 24, g, 15, tone, align=0.5)
                # The temperature rides a little higher when it is warmer.
                ty = y + 40 + (6 * (hi_t - h.temp) / (hi_t - lo_t) if hi_t > lo_t else 3)
                text(cr, cx, ty, f"{h.temp:.0f}°", 11, "title", align=0.5)
                if dry:
                    continue
                bh = 14 * h.rain / 100
                core.rrect(cr, cx - cw / 2 + 3, y + 62, cw - 6, 14, 2)
                cr.set_source_rgba(*rgba("bg1"))
                cr.fill()
                if bh >= 1:
                    core.rrect(cr, cx - cw / 2 + 3, y + 76 - bh, cw - 6, bh, 2)
                    cr.set_source_rgba(*rgba("blue", 0.45 + 0.5 * h.rain / 100))
                    cr.fill()
                if h.rain >= 30:
                    text(cr, cx, y + 78, f"{h.rain}%", 9, "blue", align=0.5)
        return end

    def draw_agenda(self, cr, hits: Hits, x0: float, x1: float, y: float) -> None:
        ag = self.agenda
        w = x1 - x0
        self.rows = []
        if not ag.configured:
            heading(cr, x0, y, "today", w)
            y += 24
            text(cr, x0, y, "no calendar set up", 12, "fg")
            y += 20
            for line in ("Put a calendar's iCal address (one per line) in", "~/.config/bardeck/calendar",
                         "Google: Settings → the calendar → Integrate calendar", "→ Secret address in iCal format"):
                text(cr, x0, y, line, 10, "title" if line.startswith("~") else "dim", width=w)
                y += 15
            return
        evs = self.shown()
        now = datetime.now().astimezone()
        today = date.today()
        nxt = next((e for e in evs if not e.all_day and e.start > now), None)
        k = 0
        for d, cap, label in ((today, self.TODAY_ROWS, "today"), (today + timedelta(1), self.TOMORROW_ROWS, "tomorrow")):
            day = ag.days.get(d, [])
            right = ""
            if d == today and (ag.error or ag.age >= agenda.STALE):
                right = f"{ag.error + ' · ' if ag.error else ''}{core.ago(ag.age) + ' old' if ag.at else ''}"
            elif d == today and ag.busy:
                right = "updating…"
            rw = text(cr, x1, y - 1, right, 11, "warn" if ag.error else "dim", align=1) + 8 if right else 0
            heading(cr, x0, y, f"{label} · {d:%a %-d %b}", w - rw)
            y += 22
            if not day:
                text(cr, x0 + 14, y + self.ROW_H / 2, "nothing" if ag.parsed_for else "reading the calendar…", 12,
                     "dim", valign=0.5)
                y += self.ROW_H
            for e in day[:cap]:
                self.draw_event(cr, hits, x0, x1, y, k, e, now, e is nxt)
                self.rows.append((y, y + self.ROW_H, k))
                k += 1
                y += self.ROW_H
            if len(day) > cap:
                text(cr, (x0 + x1) / 2, y + 1, f"+ {len(day) - cap} more", 10, "dim", align=0.5)
                y += 14
            y += 6

    def draw_event(self, cr, hits: Hits, x0: float, x1: float, y: float, i: int, e: agenda.Event,
                   now: datetime, is_next: bool) -> None:
        H = self.ROW_H
        mid = y + H / 2
        rx, rw = x0 - 6, x1 - x0 + 12
        live = not e.all_day and e.start <= now < e.end
        past = e.end <= now and not e.all_day
        picked = i == self.sel or i == self.hovered
        if live or picked:
            core.rrect(cr, rx, y + 1, rw, H - 2, 6)
            if live:
                cr.set_source_rgba(*rgba("accent", 0.20))
                cr.fill_preserve()
                cr.set_source_rgba(*rgba("accent", 0.55 if picked else 0.35))
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.set_source_rgba(*rgba("bg1"))
                cr.fill()
            if i == self.sel:
                core.rrect(cr, rx + 1, y + 5, 3, H - 10, 1.5)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
        hits.add(rx, y, rw, H, lambda: self.open_event(e))
        cr.arc(x0 + 4, mid, 3.5, 0, 6.2832)
        cr.set_source_rgba(*rgba(e.colour, 0.45 if past else 1.0))
        cr.fill()
        tone = "dim" if past else "fg"
        if e.all_day:
            text(cr, x0 + 14, mid, "all day", 12, tone, valign=0.5)
        else:
            end = e.end.strftime("%H:%M") if e.end.date() == e.start.date() else e.end.strftime("%a %H:%M")
            text(cr, x0 + 14, mid, f"{e.start:%H:%M}–{end}" if e.end > e.start else f"{e.start:%H:%M}", 12,
                 tone, valign=0.5)
        right = x1
        if picked and e.url:
            label = "join"
            bw = core.text_w(cr, label, 11) + core.text_w(cr, GLYPH_VIDEO, 13, family=core.ICON_FONT) + 23
            right -= button(cr, hits, right - bw, y + 2, label, lambda: self.open_event(e), h=H - 4, size=11,
                            glyph=GLYPH_VIDEO, on=live, tone="accent") + 6
        else:
            if live:
                left = (e.end - now).total_seconds()
                words = f"{core.ago(left)} left" if left >= 60 else "ending"
                right -= text(cr, right, mid, words, 11, "accent", align=1, valign=0.5) + 6
            elif is_next and e.start - now < timedelta(hours=12):
                words = f"in {core.ago((e.start - now).total_seconds())}" if e.start - now >= timedelta(minutes=1) \
                    else "now"
                right -= text(cr, right, mid, words, 11, "accent", align=1, valign=0.5) + 6
            if e.url:
                right -= core.icon(cr, right, mid, GLYPH_VIDEO, 13, "blue" if not past else "dim", align=1) + 6
        tx = x0 + 14 + (56 if e.all_day else 96)
        name_tone = "title" if (live or picked) else ("dim" if past else "fg2")
        text(cr, tx, mid, e.title, 13, name_tone, bold=live, valign=0.5, width=max(30.0, right - tx - 4))
