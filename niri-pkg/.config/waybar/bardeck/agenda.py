"""Today's and tomorrow's events for the clock panel, from iCalendar (.ics) feeds.

There is no calendar program on this machine (no gcalcli, no khal) and Google
Calendar has no API without OAuth, but each Google calendar has a private address
in iCal format. ~/.config/bardeck/calendar lists the sources, one per line:

    https://calendar.google.com/calendar/ical/…/private-…/basic.ics  #83a598  work
    ~/some/local.ics

(an optional #rrggbb colour and a name after the URL or path; `#` at the start of
a line is a comment). A URL is fetched only while the clock panel is open, at most
every FETCH_EVERY seconds, on a thread, and kept in $XDG_RUNTIME_DIR/bardeck/; the
feeds are parsed on that thread too, so a big calendar never stalls the bar.

The parser knows what a calendar feed needs for two days: VEVENT with DTSTART /
DTEND / DURATION (TZID through zoneinfo, UTC, floating, all-day dates), RRULE
(DAILY, WEEKLY with BYDAY, MONTHLY and YEARLY by day or by "2nd Tuesday", INTERVAL,
COUNT, UNTIL), EXDATE, moved or cancelled instances (RECURRENCE-ID), and
STATUS:CANCELLED."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import core

CONFIG = f"{core.REAL_HOME}/.config/bardeck/calendar"
FETCH_EVERY = 15 * 60
RETRY_EVERY = 3 * 60
STALE = 60 * 60
TIMEOUT = 15
COLOURS = ("blue", "purple", "aqua", "orange", "ok")
HOWTO = ("Google Calendar → Settings → the calendar → Integrate calendar → "
         "Secret address in iCal format")

DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
# Outlook writes Windows zone names; the few seen around here.
WINDOWS_TZ = {"W. Europe Standard Time": "Europe/Zurich", "Central Europe Standard Time": "Europe/Budapest",
              "Romance Standard Time": "Europe/Paris", "GMT Standard Time": "Europe/London",
              "UTC": "UTC", "Eastern Standard Time": "America/New_York",
              "Pacific Standard Time": "America/Los_Angeles", "Central European Standard Time": "Europe/Warsaw"}
MEETING = re.compile(r"https://(?:meet\.google\.com|[\w.-]*zoom\.us|teams\.microsoft\.com|teams\.live\.com"
                     r"|[\w.-]*webex\.com|whereby\.com|app\.gather\.town)/[^\s<>\"'\\]+")
ANY_URL = re.compile(r"https?://[^\s<>\"'\\]+")
LOCAL = datetime.now().astimezone().tzinfo


class Event:
    __slots__ = ("start", "end", "all_day", "title", "where", "url", "colour", "cal")

    def __init__(self, start: datetime, end: datetime, all_day: bool, title: str, where: str, url: str,
                 colour: str, cal: str):
        self.start, self.end, self.all_day = start, end, all_day
        self.title, self.where, self.url, self.colour, self.cal = title, where, url, colour, cal


class Source:
    __slots__ = ("spec", "colour", "name", "url", "path")

    def __init__(self, spec: str, colour: str, name: str):
        self.spec, self.colour, self.name = spec, colour, name
        if spec.startswith("webcal://"):
            spec = "https://" + spec[len("webcal://"):]
        self.url = spec if spec.startswith(("http://", "https://")) else ""
        if self.url:
            self.path = f"{core.RUN_DIR}/calendar-{hashlib.sha1(self.url.encode()).hexdigest()[:12]}.ics"
        else:
            self.path = os.path.expanduser(spec.replace("~", core.REAL_HOME, 1) if spec.startswith("~") else spec)


def sources() -> list[Source]:
    out = []
    for line in core.read(CONFIG).splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        colour = next((p for p in parts[1:] if re.fullmatch(r"#[0-9a-fA-F]{6}", p)), "")
        name = " ".join(p for p in parts[1:] if p != colour)
        out.append(Source(parts[0], colour.lower(), name))
    for i, src in enumerate(out):
        src.colour = src.colour or COLOURS[i % len(COLOURS)]
    return out


# ── parsing ──────────────────────────────────────────────────────────────────


def _lines(raw: str):
    """Unfolded content lines (RFC 5545 3.1: a line starting with a space continues the last)."""
    cur = ""
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t"):
            cur += line[1:]
            continue
        if cur:
            yield cur
        cur = line
    if cur:
        yield cur


def _split(line: str) -> tuple[str, dict, str]:
    """NAME;PARAM=V;…:VALUE → (NAME, {PARAM: V}, VALUE); quotes protect ; and :."""
    quoted, cut = False, []
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in ";:":
            cut.append((i, ch))
            if ch == ":":
                break
    if not cut or cut[-1][1] != ":":
        return line.upper(), {}, ""
    colon = cut[-1][0]
    head, value = line[:colon], line[colon + 1:]
    bits = [head[a + 1:b] for a, b in zip([-1] + [i for i, _ in cut[:-1]], [i for i, _ in cut])]
    params = {}
    for b in bits[1:]:
        k, _, v = b.partition("=")
        params[k.upper()] = v.strip('"')
    return bits[0].upper(), params, value


def _text(v: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _tz(name: str | None):
    if not name:
        return None
    name = WINDOWS_TZ.get(name, name)
    for cand in (name, name.rsplit("/", 2)[-2] + "/" + name.rsplit("/", 1)[-1] if name.count("/") >= 2 else ""):
        if cand:
            try:
                return ZoneInfo(cand)
            except (KeyError, ValueError, OSError):
                continue
    return LOCAL


def _when(value: str, params: dict) -> date | datetime | None:
    """A DATE (all day) or an aware DATE-TIME (floating ones are local)."""
    v = value.strip()
    try:
        if params.get("VALUE") == "DATE" or len(v) == 8:
            return datetime.strptime(v[:8], "%Y%m%d").date()
        dt = datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if v.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc)
    return dt.replace(tzinfo=_tz(params.get("TZID")) or LOCAL)


def _duration(v: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta()
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _key(v: date | datetime) -> object:
    """Comparable identity of an instance: UTC seconds for a time, the date for a day."""
    return v.timestamp() if isinstance(v, datetime) else v


def _nth(year: int, month: int, n: int, wd: int) -> date | None:
    """The n-th (n < 0: from the end) weekday wd of a month."""
    first = date(year, month, 1)
    nxt = date(year + month // 12, month % 12 + 1, 1)
    days = [first + timedelta(i) for i in range((nxt - first).days) if (first + timedelta(i)).weekday() == wd]
    try:
        return days[n - 1] if n > 0 else days[n]
    except IndexError:
        return None


def _month_days(year: int, month: int, rule: dict, start: date) -> list[date]:
    out = []
    nxt = date(year + month // 12, month % 12 + 1, 1)
    last = (nxt - timedelta(1)).day
    if rule.get("BYDAY"):
        for tok in rule["BYDAY"].split(","):
            m = re.fullmatch(r"([+-]?\d+)?(\w\w)", tok)
            if not m or m.group(2) not in DAYS:
                continue
            wd = DAYS[m.group(2)]
            if m.group(1):
                d = _nth(year, month, int(m.group(1)), wd)
                if d:
                    out.append(d)
            else:
                out += [date(year, month, k) for k in range(1, last + 1) if date(year, month, k).weekday() == wd]
    else:
        days = [int(x) for x in rule.get("BYMONTHDAY", str(start.day)).split(",") if x.lstrip("-").isdigit()]
        for k in days:
            k = last + 1 + k if k < 0 else k
            if 1 <= k <= last:
                out.append(date(year, month, k))
    return sorted(set(out))


def _dates(rule: dict, start: date, until_day: date):
    """The days a rule recurs on, from start's day, in order, until until_day (inclusive)."""
    freq = rule.get("FREQ", "")
    step = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = "COUNT" in rule
    if freq == "DAILY":
        days = {DAYS[t[-2:]] for t in rule.get("BYDAY", "").split(",") if t[-2:] in DAYS}
        k = 0
        if not count:  # a series from years ago: jump close to the window
            k = max(0, (until_day - start).days // step - 2 * 400) * step
        while True:
            d = start + timedelta(k)
            if d > until_day:
                return
            if not days or d.weekday() in days:
                yield d
            k += step
    elif freq == "WEEKLY":
        days = sorted({DAYS[t[-2:]] for t in rule.get("BYDAY", "").split(",") if t[-2:] in DAYS}) or [start.weekday()]
        monday = start - timedelta(start.weekday())
        w = 0
        if not count:
            w = max(0, (until_day - monday).days // 7 // step - 60) * step
        while True:
            base = monday + timedelta(weeks=w)
            if base > until_day:
                return
            for wd in days:
                d = base + timedelta(wd)
                if start <= d <= until_day:
                    yield d
            w += step
    elif freq == "MONTHLY":
        y, m = start.year, start.month
        while date(y, m, 1) <= until_day:
            for d in _month_days(y, m, rule, start):
                if start <= d <= until_day:
                    yield d
            y, m = y + (m - 1 + step) // 12, (m - 1 + step) % 12 + 1
    elif freq == "YEARLY":
        months = sorted({int(m) for m in rule.get("BYMONTH", str(start.month)).split(",") if m.isdigit()})
        y = start.year
        while date(y, 1, 1) <= until_day:
            for m in months:
                for d in _month_days(y, m, rule, start):
                    if start <= d <= until_day:
                        yield d
            y += step
    else:  # an unknown FREQ: the first instance only
        yield start


def parse(raw: str, colour: str, lo: datetime, hi: datetime) -> tuple[str, str, list[Event]]:
    """(calendar name, its colour, the events overlapping [lo, hi))."""
    cal_name, cal_colour = "", ""
    vevents, cur = [], None
    for line in _lines(raw):
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur = {}
        elif name == "END" and value.upper() == "VEVENT":
            if cur is not None:
                vevents.append(cur)
            cur = None
        elif cur is not None:
            cur.setdefault(name, []).append((params, value))
        elif name == "X-WR-CALNAME":
            cal_name = _text(value)
        elif name == "X-APPLE-CALENDAR-COLOR" and re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value):
            cal_colour = value[:7].lower()
    colour = colour if colour.startswith("#") else (cal_colour or colour)

    def one(ev, name):
        return ev[name][0] if name in ev else ({}, "")

    moved: set[tuple[str, object]] = set()
    for ev in vevents:
        if "RECURRENCE-ID" in ev:
            rid = _when(one(ev, "RECURRENCE-ID")[1], one(ev, "RECURRENCE-ID")[0])
            if rid is not None:
                moved.add((one(ev, "UID")[1], _key(rid)))

    out = []
    for ev in vevents:
        if one(ev, "STATUS")[1].upper() == "CANCELLED":
            continue
        start = _when(one(ev, "DTSTART")[1], one(ev, "DTSTART")[0])
        if start is None:
            continue
        all_day = not isinstance(start, datetime)
        if "DTEND" in ev:
            end = _when(one(ev, "DTEND")[1], one(ev, "DTEND")[0]) or start
            length = end - start if type(end) is type(start) else timedelta(days=1 if all_day else 0)
        elif "DURATION" in ev:
            length = _duration(one(ev, "DURATION")[1])
        else:
            length = timedelta(days=1) if all_day else timedelta()
        title = _text(one(ev, "SUMMARY")[1]) or "(no title)"
        where = _text(one(ev, "LOCATION")[1])
        desc = _text(one(ev, "DESCRIPTION")[1])
        url = one(ev, "X-GOOGLE-CONFERENCE")[1] or ""
        if not url:
            m = MEETING.search(f"{where}\n{one(ev, 'URL')[1]}\n{desc}")
            url = m.group(0) if m else ""
        if not url:
            m = ANY_URL.search(where) or ANY_URL.search(one(ev, "URL")[1])
            url = m.group(0) if m else ""
        uid = one(ev, "UID")[1]

        def add(s):
            if all_day:
                a = datetime.combine(s, dtime(), LOCAL)
                b = datetime.combine(s + length, dtime(), LOCAL)
            else:
                a, b = s, s + length
            if a < hi and (b > lo or (a == b and a >= lo)):
                out.append(Event(a.astimezone(LOCAL), b.astimezone(LOCAL), all_day, title, where, url, colour,
                                 cal_name))

        rrule = one(ev, "RRULE")[1]
        if not rrule or "RECURRENCE-ID" in ev:
            add(start)
            continue
        rule = {}
        for part in rrule.split(";"):
            k, _, v = part.partition("=")
            rule[k.upper()] = v.upper() if k.upper() != "UNTIL" else v
        ex = set()
        for params, value in ev.get("EXDATE", []):
            for v in value.split(","):
                d = _when(v, params)
                if d is not None:
                    ex.add(_key(d))
        until = _when(rule["UNTIL"], {}) if "UNTIL" in rule else None
        if isinstance(until, datetime) and not isinstance(start, datetime):
            until = until.date()
        elif isinstance(until, date) and not isinstance(until, datetime) and isinstance(start, datetime):
            until = datetime.combine(until, dtime(23, 59, 59), start.tzinfo)
        count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
        tz = start.tzinfo if isinstance(start, datetime) else None
        sday = start.date() if isinstance(start, datetime) else start
        last_day = (hi + timedelta(days=1)).astimezone(tz or LOCAL).date()
        n = 0
        for d in _dates(rule, sday, last_day):
            # Recur on the wall clock of DTSTART's zone: a 9:00 meeting stays at 9:00 over DST.
            inst = datetime.combine(d, start.time(), tz) if tz else d
            if until is not None and inst > until:
                break
            n += 1
            if count is not None and n > count:
                break
            if _key(inst) in ex or (uid, _key(inst)) in moved:
                continue
            add(inst)
    return cal_name, colour, out


# ── fetching and the panel's view ────────────────────────────────────────────


class Agenda:
    """refresh() is safe to call on every draw: it starts a thread only when a feed
    is older than FETCH_EVERY or the day changed."""

    def __init__(self):
        self.days: dict[date, list[Event]] = {}
        self.parsed_for: date | None = None
        self.parsed_stamp: tuple = ()
        self.at = 0.0          # the oldest feed's age stamp (epoch), for "stale"
        self.error = ""
        self.busy = False
        self.configured = False
        self.n_sources = 0
        self._tried = 0.0

    def refresh(self, force: bool = False) -> None:
        srcs = sources()
        self.configured, self.n_sources = bool(srcs), len(srcs)
        if not srcs or self.busy:
            if not srcs:
                self.days, self.parsed_for = {}, None
            return
        now = time.time()
        due = [s for s in srcs if s.url and now - _mtime(s.path) >= FETCH_EVERY]
        fetch = bool(due) and now - self._tried >= (60 if force else RETRY_EVERY)
        stamp = tuple((s.spec, s.colour, _mtime(s.path)) for s in srcs)
        if not fetch and not force and self.parsed_for == date.today() and stamp == self.parsed_stamp:
            return
        if fetch:
            self._tried = now
        self.busy = True
        threading.Thread(target=self._work, args=(srcs, due if fetch else []), daemon=True).start()

    def _work(self, srcs: list[Source], due: list[Source]) -> None:
        try:
            errors = []
            for s in due:
                try:
                    req = urllib.request.Request(s.url, headers={"User-Agent": "bardeck"})
                    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                        body = resp.read()
                    if b"BEGIN:VCALENDAR" not in body[:2000]:
                        raise ValueError("not an iCalendar feed")
                    os.makedirs(core.RUN_DIR, exist_ok=True)
                    with open(f"{s.path}.tmp", "wb") as fh:
                        fh.write(body)
                    os.replace(f"{s.path}.tmp", s.path)
                except Exception as err:  # noqa: BLE001 — offline, 404: keep the cached copy
                    code = getattr(err, "code", None)  # an HTTPError is an OSError too
                    errors.append(f"HTTP {code}" if code else ("offline" if isinstance(err, OSError) else str(err)[:40]))
                    core.log(f"calendar: {s.name or 'feed'}: {err!r}")
            today = date.today()
            lo = datetime.combine(today, dtime(), LOCAL)
            hi = lo + timedelta(days=2)
            days: dict[date, list[Event]] = {today: [], today + timedelta(1): []}
            missing = 0
            for s in srcs:
                try:
                    with open(s.path, encoding="utf-8", errors="replace") as fh:
                        raw = fh.read()
                except OSError:
                    missing += 1
                    continue
                name, colour, events = parse(raw, s.colour, lo, hi)
                for e in events:
                    e.cal = s.name or name
                    for d in days:
                        a = datetime.combine(d, dtime(), LOCAL)
                        if e.start < a + timedelta(1) and (e.end > a or (e.end == e.start and e.start >= a)):
                            days[d].append(e)
            for evs in days.values():
                evs.sort(key=lambda e: (not e.all_day, e.start, e.title))
            stamps = [_mtime(s.path) for s in srcs if s.url]
            self.days, self.parsed_for = days, today
            self.parsed_stamp = tuple((s.spec, s.colour, _mtime(s.path)) for s in srcs)
            self.at = min(stamps) if stamps else time.time()
            self.error = errors[0] if errors else (f"{missing} feed not read yet" if missing == 1 else (
                f"{missing} feeds not read yet" if missing else ""))
        except Exception as err:  # noqa: BLE001 — a feed the parser chokes on must not kill the panel
            self.error = f"calendar: {err}"[:60]
            core.log(f"calendar: {err!r}")
        finally:
            self.busy = False

    @property
    def age(self) -> float:
        return time.time() - self.at if self.at else 0.0


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0
