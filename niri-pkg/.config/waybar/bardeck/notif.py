"""Notifications: dunst's history, drawn. A bell on the strip with the number of
notifications that came since the panel was last opened; in the panel the history,
newest first and grouped by app, Do Not Disturb and "clear all".

Everything goes over dunst's own D-Bus API (org.dunstproject.cmd0 on the session
bus), in-process. Nothing polls: dunst's PropertiesChanged (displayedLength,
historyLength, paused, waitingLength) and its history signals arrive on the main
loop. A notification reaches the history when its popup closes: then (displayed
went down, or historyLength changed) the history is read again, one async call (a
few ms) per notification, so the strip's count stays right. historyLength alone is
not enough: at the cap (dunstrc history_length) it stays the same while the entries
change.

Unread = in the history with a timestamp past the newest one the panel showed. That
timestamp is kept in $XDG_RUNTIME_DIR/bardeck/notif-seen, so it survives a bardeck
(waybar) restart and a dunst restart: dunst's timestamps are CLOCK_BOOTTIME µs, the
same clock for every dunst of this boot.

Pinned keys: `i`/`o` select, `k`/`l` half a list, Enter show it again (dunst pops it
from the history), `x` remove it, `c` clear all (twice), `z` Do Not Disturb."""

from __future__ import annotations

import html
import os
import re
import threading
import time
import zlib

import cairo

from . import core
from .core import Hits, button, rgba, text
from .deck import Panel

DUNST = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
CMD = "org.dunstproject.cmd0"
PROPS = "org.freedesktop.DBus.Properties"
SEEN_FILE = f"{core.RUN_DIR}/notif-seen"

GLYPH_BELL, GLYPH_BELL_IDLE, GLYPH_BELL_OFF = "\U000f009a", "\U000f009c", "\U000f009b"
GLYPH_SLEEP, GLYPH_CLEAR, GLYPH_CLOSE = "\U000f00a0", "\U000f00e2", "\U000f0156"

# The urgency stripe on a card's left edge.
URGENCY_TONE = {"CRITICAL": "hit", "NORMAL": "bg3", "LOW": "bg2"}
# An app with no icon file gets a letter tile in one of these, by its name.
TILE_TONES = ("blue", "aqua", "purple", "orange", "ok", "warn")
# Pango markup that notifications use and dunst renders; a body that does not parse
# as markup gets these taken out and is drawn as plain text.
_TAGS = re.compile(r"</?(?:b|i|u|s|a|img|span|small|big|tt|sub|sup|br)\b[^<>]*/?>", re.I)


class Note:
    """One notification in dunst's history."""

    __slots__ = ("id", "app", "summary", "body", "icon", "urgency", "ts", "wall")

    def __init__(self, d: dict, wall: float):
        self.id = int(d.get("id", 0))
        self.app = str(d.get("appname", "")) or "?"
        self.summary = str(d.get("summary", "")).strip()
        self.body = str(d.get("body", "")).strip()
        self.icon = str(d.get("icon_path", ""))
        self.urgency = str(d.get("urgency", "NORMAL")).upper()
        self.ts = int(d.get("timestamp", 0))  # dunst's: CLOCK_BOOTTIME, µs
        self.wall = wall                        # the same moment, as time.time()


def wall_clock(ts_us: int) -> float:
    """dunst's timestamp as epoch seconds. dunst stamps a notification with
    CLOCK_BOOTTIME (checked 13 Oct 2026: a screenshot's notification matched the
    time in its file name to the second; CLOCK_MONOTONIC was a day off, the time
    spent asleep)."""
    return time.time() - (time.clock_gettime(time.CLOCK_BOOTTIME) - ts_us / 1e6)


def ago(wall: float, now: float | None = None) -> str:
    """"now", "3 min", "14:02" (today), "yesterday 18:04", "Mon 09:12", "12 Oct 09:12"."""
    now = time.time() if now is None else now
    d = now - wall
    if d < 60:
        return "now"
    if d < 3600:
        return f"{int(d // 60)} min"
    t, today = time.localtime(wall), time.localtime(now)
    days = (time.mktime((*today[:3], 0, 0, 0, 0, 0, -1)) - time.mktime((*t[:3], 0, 0, 0, 0, 0, -1))) / 86400
    hm = time.strftime("%H:%M", t)
    if days < 0.5:
        return hm
    if days < 1.5:
        return f"yesterday {hm}"
    if days < 6.5:
        return time.strftime("%a ", t) + hm
    return time.strftime("%-d %b ", t) + hm


def body_text(s: str) -> tuple[str, bool]:
    """(what to draw, is it markup). dunst's markup is Pango's; a body that does not
    parse (a stray "<" or "&", an <a href>, an unclosed tag) is drawn as plain text
    with the known tags taken out, since set_markup on bad markup draws nothing.

    The lines are joined into one paragraph ("a\n\nb" -> "a · b"): Pango's
    set_height(-n) caps the lines of each paragraph, not of the layout, so a body
    with newlines drew past its card into the next one."""
    from gi.repository import GLib, Pango

    s = " · ".join(line.strip() for line in s.replace("\r", "").split("\n") if line.strip())
    try:
        Pango.parse_markup(s, -1, "\0")
        return s, True
    except GLib.Error:
        return html.unescape(_TAGS.sub("", s)), False


class Dunst:
    """dunst's state, kept fresh by its signals on the main loop."""

    def __init__(self):
        self.history: list[Note] = []  # newest first; replaced whole
        self.up = False                 # dunst answered the last call
        self.paused = False
        self.waiting = 0                # held back while paused
        self.displayed = 0
        self.length = 0                 # historyLength
        self.seen = self.load_seen()    # the newest timestamp the panel showed
        self.open = False               # the panel is open: what arrives is seen
        self.icons: dict[str, object] = {}  # icon_path -> GdkPixbuf.Pixbuf, or None (unreadable)
        self._loading: set[str] = set()
        self._bus = None
        self._timer = 0
        self.read()
        self.watch()

    # -- the bus -----------------------------------------------------------------

    def bus(self):
        if self._bus is None:
            from gi.repository import Gio

            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        return self._bus

    def watch(self) -> None:
        """Subscribe on the main loop: dunst's property changes and history signals,
        and dunst (re)starting."""
        from gi.repository import Gio

        try:
            bus = self.bus()
        except Exception as err:
            core.log(f"notif: no session bus: {err!r}")
            return
        none = Gio.DBusSignalFlags.NONE
        bus.signal_subscribe(DUNST, PROPS, "PropertiesChanged", PATH, CMD, none, self._on_props)
        for member in ("NotificationHistoryCleared", "NotificationHistoryRemoved"):
            bus.signal_subscribe(DUNST, CMD, member, PATH, None, none, lambda *_a: self.refresh())
        bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                             "/org/freedesktop/DBus", DUNST, none, self._on_owner)

    def _on_props(self, _bus, _sender, _path, _iface, _member, params) -> None:
        _iface, changed, _gone = params.unpack()
        reread = "historyLength" in changed
        if "displayedLength" in changed:
            n = int(changed["displayedLength"])
            reread = reread or n < self.displayed  # a popup closed: it went to the history
            self.displayed = n
        self.take(changed)
        if reread:
            self.refresh()

    def _on_owner(self, _bus, _sender, _path, _iface, _member, params) -> None:
        _name, _old, new = params.unpack()
        if new:
            self.refresh()
        else:
            self.up = False

    def take(self, props: dict) -> None:
        if "paused" in props:
            self.paused = bool(props["paused"])
        if "waitingLength" in props:
            self.waiting = int(props["waitingLength"])
        if "historyLength" in props:
            self.length = int(props["historyLength"])
        if "displayedLength" in props:
            self.displayed = int(props["displayedLength"])

    # -- reading -----------------------------------------------------------------

    def read(self) -> None:
        """Everything, now (blocking, ~6 ms): at start and when the panel opens.
        NO_AUTO_START: never start a notification daemon by asking it something."""
        from gi.repository import Gio, GLib

        try:
            bus = self.bus()
            flags = Gio.DBusCallFlags.NO_AUTO_START
            props = bus.call_sync(DUNST, PATH, PROPS, "GetAll", GLib.Variant("(s)", (CMD,)),
                                  GLib.VariantType("(a{sv})"), flags, 500, None).unpack()[0]
            hist = bus.call_sync(DUNST, PATH, CMD, "NotificationListHistory", None,
                                 GLib.VariantType("(aa{sv})"), flags, 500, None).unpack()[0]
        except Exception as err:
            if self.up or core.TRACE:
                core.log(f"notif: dunst: {err!r}")
            self.up = False
            return
        self.take(props)
        self.got(hist)

    def refresh(self) -> None:
        """Read the history again soon, without blocking; a burst of signals is one read."""
        from gi.repository import GLib

        if not self._timer:
            self._timer = GLib.timeout_add(150, self._refresh_now)

    def _refresh_now(self) -> bool:
        from gi.repository import Gio, GLib

        self._timer = 0
        flags = Gio.DBusCallFlags.NO_AUTO_START
        bus = self.bus()
        bus.call(DUNST, PATH, CMD, "NotificationListHistory", None, GLib.VariantType("(aa{sv})"),
                 flags, 1000, None, self._got_history)
        bus.call(DUNST, PATH, PROPS, "GetAll", GLib.Variant("(s)", (CMD,)), GLib.VariantType("(a{sv})"),
                 flags, 1000, None, self._got_props)
        return False

    def _got_history(self, bus, res) -> None:
        try:
            self.got(bus.call_finish(res).unpack()[0])
        except Exception as err:
            self.up = False
            if core.TRACE:
                core.log(f"notif: history: {err!r}")

    def _got_props(self, bus, res) -> None:
        try:
            self.take(bus.call_finish(res).unpack()[0])
        except Exception:
            pass

    def got(self, raw: list[dict]) -> None:
        notes = [Note(d, wall_clock(int(d.get("timestamp", 0)))) for d in raw]
        # dunst lists them in the order they closed; newest first by when they came.
        notes.sort(key=lambda n: (n.ts, n.id), reverse=True)
        self.history, self.up = notes, True
        if self.open:
            self.mark_seen()
        keep = {n.icon for n in notes}
        for path in list(self.icons):  # a copy: an icon thread may add one meanwhile
            if path not in keep:
                self.icons.pop(path, None)
        for path in keep:  # load new icons now, so the panel opens with them
            self.icon(path)

    # -- unread ------------------------------------------------------------------

    @staticmethod
    def load_seen() -> int:
        try:
            return int(core.read(SEEN_FILE, "0") or 0)
        except ValueError:
            return 0

    @property
    def unread(self) -> int:
        return sum(1 for n in self.history if n.ts > self.seen)

    def mark_seen(self) -> None:
        newest = max((n.ts for n in self.history), default=0)
        if newest > self.seen:
            self.seen = newest
            try:
                os.makedirs(core.RUN_DIR, exist_ok=True)
                with open(f"{SEEN_FILE}.tmp", "w") as fh:
                    fh.write(f"{newest}\n")
                os.replace(f"{SEEN_FILE}.tmp", SEEN_FILE)
            except OSError as err:
                core.log(f"notif: {err!r}")

    # -- acting ------------------------------------------------------------------

    def call(self, method: str, args: tuple | None = None, iface: str = CMD) -> None:
        """Fire a call at dunst; its signals bring the new state."""
        from gi.repository import Gio, GLib

        def done(bus, res):
            try:
                bus.call_finish(res)
            except Exception as err:
                core.log(f"notif: {method}: {err!r}")
            self.refresh()

        try:
            self.bus().call(DUNST, PATH, iface, method, GLib.Variant(*args) if args else None, None,
                            Gio.DBusCallFlags.NO_AUTO_START, 1000, None, done)
        except Exception as err:
            core.log(f"notif: {method}: {err!r}")

    def drop(self, n: Note) -> None:
        self.history = [x for x in self.history if x.id != n.id]  # at once, before dunst says so

    def pop(self, n: Note) -> None:
        """Show it again: dunst takes it out of the history and displays it."""
        self.drop(n)
        self.call("NotificationPopHistory", ("(u)", (n.id,)))

    def remove(self, n: Note) -> None:
        self.drop(n)
        self.call("NotificationRemoveFromHistory", ("(u)", (n.id,)))

    def clear(self) -> None:
        self.history = []
        self.call("NotificationClearHistory")

    def set_paused(self, on: bool) -> None:
        from gi.repository import GLib

        self.paused = on
        self.call("Set", ("(ssv)", (CMD, "paused", GLib.Variant("b", on))), iface=PROPS)

    # -- icons ---------------------------------------------------------------------

    def icon(self, path: str):
        """The pixbuf for an icon_path, or None. Loaded on a thread the first time,
        when the history brings it (a screenshot's icon is the whole screenshot:
        ~10 ms to decode); an open panel redraws every second and picks it up."""
        if not path or path in self.icons:
            return self.icons.get(path)
        if path not in self._loading:
            self._loading.add(path)
            threading.Thread(target=self._load, args=(path,), daemon=True).start()
        return None

    def _load(self, path: str) -> None:
        pb = None
        try:
            if os.path.isfile(path) and os.access(path, os.R_OK):
                import gi

                gi.require_version("GdkPixbuf", "2.0")
                from gi.repository import GdkPixbuf

                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 48, 48, True)
        except Exception as err:
            if core.TRACE:
                core.log(f"notif: icon {path}: {err!r}")
        self.icons[path] = pb
        self._loading.discard(path)


# ── the strip ────────────────────────────────────────────────────────────────


class NotifStrip:
    """A bell; a badge with the unread count. Do Not Disturb: the sleeping bell."""

    name = "notif"

    def __init__(self, d: Dunst):
        self.d = d

    def count(self) -> int:
        d = self.d
        return d.unread + (d.waiting if d.paused else 0)

    def key(self, variant: str):
        d = self.d
        return d.up, d.paused, self.count()

    def draw(self, variant: str, scale: int):
        d = self.d
        c = core.StripCanvas(scale)
        n = self.count()
        if not d.up:
            c.icon(GLYPH_BELL_OFF, "dim", 15, after=0)
        elif d.paused:
            c.icon(GLYPH_SLEEP, "warn", 15, after=0)
        else:
            c.icon(GLYPH_BELL if n else GLYPH_BELL_IDLE, "title" if n else "fg", 15, after=0)
        if n:
            c.gap(3)
            c.x += badge(c.cr, c.x, core.MID, "99+" if n > 99 else str(n), "warn" if d.paused else "accent")
        return c.finish()


def badge(cr, x: float, mid: float, label: str, tone: str, size: float = 10) -> float:
    """A count in a filled pill, from x, centred on mid. Returns its width."""
    tw = core.text_w(cr, label, size, bold=True)
    h = size + 4
    w = max(h, tw + 8)
    core.rrect(cr, x, mid - h / 2, w, h, h / 2)
    cr.set_source_rgba(*rgba(tone))
    cr.fill()
    text(cr, x + w / 2, mid, label, size, "bg", bold=True, align=0.5, valign=0.5)
    return w


# ── the panel ────────────────────────────────────────────────────────────────


class NotifPanel(Panel):
    """dunst's history as cards, newest first, a header per run of one app. Click a
    card: dunst shows it again; hover it: × removes it."""

    name = "notif"
    live = 1.0  # new notifications, icons loaded on their thread, "3 min" ticking on
    W = 440
    LIST_MAX = 420  # the list's height at most (~8 cards); it scrolls past that
    HEAD_H = 24     # an app's header
    LINE_H = 15     # a body line
    CARD_TOP = 6 + 17  # padding and the summary line
    CARD_BOTTOM = 7
    GAP = 4

    def __init__(self, d: Dunst):
        self.d = d
        self.sel = -1
        self.top = 0
        self.hovered = -1
        self.hover_x = False   # the pointer is on the hovered card's ×
        self.clearing = False  # "clear all" asks to be pressed again
        self.was = d.seen      # the seen mark when it opened: newer cards are marked new
        self.rows: list[tuple[float, float, int]] = []    # (y0, y1, index), for hover
        self.xbox: tuple[float, float, float, float] | None = None  # the ×, for hover
        self._lines: dict[tuple, int] = {}  # (id, body) -> body lines (0-2)
        self._measure = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

    @property
    def notes(self) -> list[Note]:
        return self.d.history

    # -- layout ------------------------------------------------------------------

    def text_w(self) -> float:
        return self.W - 2 * 16 - 10  # the card's width (W - 2P + 12) less its padding (12 + 10)

    def body_lines(self, n: Note) -> int:
        key = (n.id, n.body)
        if key not in self._lines:
            if not n.body:
                self._lines[key] = 0
            else:
                lay = self.body_layout(self._measure, n, 2)
                self._lines[key] = max(1, min(2, lay.get_line_count()))
        return self._lines[key]

    def body_layout(self, cr, n: Note, lines: int):
        from gi.repository import Pango

        s, markup = body_text(n.body)
        lay = core.layout(cr, s, 12, markup=markup, width=self.text_w())
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        lay.set_height(-lines)  # at most that many lines, the last one ellipsized
        return lay

    def card_h(self, n: Note) -> float:
        return self.CARD_TOP + self.body_lines(n) * self.LINE_H + self.CARD_BOTTOM

    def head(self, i: int, first: bool) -> bool:
        """Does card i start with its app's header? The first one shown always does."""
        notes = self.notes
        return first or notes[i - 1].app != notes[i].app

    def cards(self, top: int):
        """The cards from top on: (index, with a header, height with the gap under it)."""
        for i in range(top, len(self.notes)):
            h = self.head(i, i == top)
            yield i, h, (self.HEAD_H if h else 0) + self.card_h(self.notes[i]) + self.GAP

    def total(self, top: int = 0, upto: int | None = None) -> float:
        """The height of the cards from top (to upto, with it)."""
        return sum(ch for i, _h, ch in self.cards(top) if upto is None or i <= upto)

    def room(self) -> float:
        """The list's own height: all of it, up to LIST_MAX; past that it scrolls."""
        return min(self.LIST_MAX, self.total()) if self.notes else 70

    def list_h(self) -> float:
        return self.room() + (16 if self.notes and self.total() > self.LIST_MAX else 0)  # "n more"

    def max_top(self) -> int:
        """The last top that still fills the list."""
        room, top = self.room(), len(self.notes) - 1
        while top > 0 and self.total(top - 1) <= room:
            top -= 1
        return max(0, top)

    def size(self):
        return self.W, 68 + self.list_h() + 8

    # -- state -------------------------------------------------------------------

    def opened(self) -> None:
        d = self.d
        d.read()
        self.was = d.seen
        d.open = True
        d.mark_seen()
        self.sel, self.top, self.hovered, self.hover_x, self.clearing = -1, 0, -1, False, False

    def closed(self) -> None:
        self.d.open = False
        self.clearing = False

    def follow(self) -> None:
        """Scroll so the selection shows."""
        self.top = max(0, min(self.top, self.max_top()))
        if 0 <= self.sel < self.top:
            self.top = self.sel
        room = self.room()
        while 0 <= self.sel and self.top < self.sel and self.total(self.top, self.sel) - self.GAP > room:
            self.top += 1

    # -- actions -----------------------------------------------------------------

    def pop(self, n: Note) -> bool:
        self.clearing = False
        self.d.pop(n)
        return False

    def remove(self, n: Note) -> bool:
        self.clearing = False
        self.d.remove(n)
        self.hovered = -1
        return False

    def clear(self) -> bool:
        if not self.clearing:
            self.clearing = True  # the chip turns red: a second press clears
            return False
        self.clearing = False
        self.d.clear()
        self.sel, self.top = -1, 0
        return False

    def dnd(self) -> bool:
        self.clearing = False
        self.d.set_paused(not self.d.paused)
        return False

    # -- input -------------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool:
        notes = self.notes
        n = len(notes)
        half = 4
        if key in ("c", "z"):
            (self.clear if key == "c" else self.dnd)()
            return True
        self.clearing = False
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key in ("k", "Page_Down") or (ctrl and key == "v"):
            self.sel = min(n - 1, self.sel + half)
        elif key in ("l", "Page_Up"):
            self.sel = max(0, self.sel - half)
        elif key in ("Return", "KP_Enter") and 0 <= self.sel < n:
            self.pop(notes[self.sel])
        elif key in ("x", "Delete") and 0 <= self.sel < n:
            self.remove(notes[self.sel])
        else:
            return False
        self.sel = min(self.sel, len(self.notes) - 1)
        self.follow()
        return True

    def hover(self, x: float, y: float) -> bool:
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        bx = self.xbox
        on_x = idx >= 0 and idx == self.hovered and bx is not None and (
            bx[0] <= x < bx[0] + bx[2] and bx[1] <= y < bx[1] + bx[3])
        if (idx, on_x) != (self.hovered, self.hover_x):
            self.hovered, self.hover_x = idx, on_x
            return True
        return False

    def scroll(self, down: bool) -> bool:
        top = max(0, min(self.top + (1 if down else -1), self.max_top()))
        if top == self.top:
            return False
        self.top = top
        return True

    # -- drawing -----------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        d = self.d
        W, P = self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        y = 12
        if not d.up:
            core.icon(cr, P, y + 11, GLYPH_BELL_OFF, 20, "dim")
        else:
            core.icon(cr, P, y + 11, GLYPH_SLEEP if d.paused else GLYPH_BELL, 20, "warn" if d.paused else "title")
        text(cr, P + 28, y, "Notifications", 18, "title", bold=True)

        # The chips, right to left: clear all, Do Not Disturb.
        right = W - P
        if self.notes:
            label = "clear all?" if self.clearing else "clear all"
            cw = self.chip_w(cr, label, GLYPH_CLEAR)
            button(cr, hits, right - cw, y + 1, label, self.clear, h=22, size=11, glyph=GLYPH_CLEAR,
                   on=self.clearing, tone="hit")
            right -= cw + 8
        if d.up:
            label = "do not disturb"
            cw = self.chip_w(cr, label, GLYPH_SLEEP)
            button(cr, hits, right - cw, y + 1, label, self.dnd, h=22, size=11, glyph=GLYPH_SLEEP,
                   on=d.paused, tone="warn")
        y += 28

        # What the list holds, in words.
        x = P + 28
        if not d.up:
            text(cr, x, y, "dunst is not running", 12, "hit")
        else:
            new = sum(1 for n in self.notes if n.ts > self.was)
            words = [f"{new} new" if new else "nothing new", f"{len(self.notes)} in the history"]
            x += text(cr, x, y, " · ".join(words), 12, "dim")
            if d.paused:
                text(cr, x, y, f" · {d.waiting} held back" if d.waiting else " · popups held back", 12, "warn")
        y += 28

        cr.rectangle(P, y - 6, W - 2 * P, 1)
        cr.set_source_rgba(*rgba("bg2"))
        cr.fill()
        self.draw_list(cr, hits, P, y)

    def draw_list(self, cr, hits: Hits, P: float, y: float) -> None:
        W = self.W
        notes = self.notes
        self.rows, self.xbox = [], None
        if not notes:
            mid = y + self.list_h() / 2 - 4
            core.icon(cr, W / 2, mid - 8, GLYPH_BELL_IDLE, 22, "bg3", align=0.5)
            text(cr, W / 2, mid + 6, "no notifications" if self.d.up else "no history", 12, "dim", align=0.5)
            return
        room = self.room()
        bottom = y + room
        self.top = max(0, min(self.top, self.max_top()))
        now = time.time()
        more = 0
        cr.save()
        cr.rectangle(0, y, W, room)
        cr.clip()  # the card at the bottom shows in part: there is more under it
        for i, with_head, ch in self.cards(self.top):
            if y + ch - self.GAP > bottom + 0.5:
                more += 1
            if y >= bottom:
                continue
            y0 = y
            if with_head:
                self.draw_head(cr, P, y, i)
                y += self.HEAD_H
            self.draw_card(cr, hits, P, y, i, notes[i], now, bottom)
            y = y0 + ch
            self.rows.append((y0, min(y, bottom), i))
        cr.restore()
        if more:  # fade the cut card out
            fade = cairo.LinearGradient(0, bottom - 18, 0, bottom)
            fade.add_color_stop_rgba(0, *rgba("bg", 0.0))
            fade.add_color_stop_rgba(1, *rgba("bg", 0.97))
            cr.rectangle(1, bottom - 18, W - 2, 18)
            cr.set_source(fade)
            cr.fill()
        if self.list_h() > room:
            words = f"▾ {more} more · scroll" if more else f"▴ {self.top} above"
            text(cr, W / 2, bottom + 2, words, 10, "dim", align=0.5)

    def draw_head(self, cr, P: float, y: float, i: int) -> None:
        """An app's icon and name, and how many of its cards follow in a row."""
        notes = self.notes
        n = notes[i]
        run = 1
        while i + run < len(notes) and notes[i + run].app == n.app:
            run += 1
        mid = y + self.HEAD_H / 2
        icon_path = next((m.icon for m in notes[i:i + run] if m.icon), "")
        self.draw_icon(cr, P, mid - 9, 18, n.app, icon_path)
        x = P + 26
        x += text(cr, x, mid, n.app, 12, "fg2", bold=True, valign=0.5, width=self.W - 2 * P - 80)
        if run > 1:
            text(cr, x + 6, mid, f"{run}", 11, "dim", valign=0.5)

    def draw_icon(self, cr, x: float, y: float, s: float, app: str, path: str) -> None:
        pb = self.d.icon(path) if path else None
        if pb is not None:
            from gi.repository import Gdk

            pw, ph = pb.get_width(), pb.get_height()
            k = s / max(pw, ph)
            cr.save()
            core.rrect(cr, x, y, s, s, 4)
            cr.clip()
            cr.translate(x + (s - pw * k) / 2, y + (s - ph * k) / 2)
            cr.scale(k, k)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
            cr.restore()
            return
        tone = TILE_TONES[zlib.crc32(app.lower().encode()) % len(TILE_TONES)]
        core.rrect(cr, x, y, s, s, 4)
        cr.set_source_rgba(*rgba(tone, 0.85))
        cr.fill()
        text(cr, x + s / 2, y + s / 2, (app[:1] or "?").upper(), s * 0.62, "bg", bold=True, align=0.5, valign=0.5)

    def draw_card(self, cr, hits: Hits, P: float, y: float, i: int, n: Note, now: float, bottom: float) -> None:
        """One card from y; the list ends at bottom (what is under it is clipped, and
        takes no clicks)."""
        W = self.W
        x0, cw = P - 6, W - 2 * P + 12
        h = self.card_h(n)
        new = n.ts > self.was
        picked = i == self.sel or i == self.hovered
        core.rrect(cr, x0, y, cw, h, 7)
        cr.set_source_rgba(*rgba("bg1", 1.0 if picked else 0.55))
        if i == self.sel:  # the keyboard's mark: an accent rim
            cr.fill_preserve()
            cr.set_source_rgba(*rgba("accent", 0.6))
            cr.set_line_width(1)
            cr.stroke()
        else:
            cr.fill()
        # The urgency stripe, inside the card's left edge.
        core.rrect(cr, x0 + 2, y + 5, 3, h - 10, 1.5)
        cr.set_source_rgba(*rgba(URGENCY_TONE.get(n.urgency, "bg3")))
        cr.fill()
        hits.add(x0, y, cw, min(h, bottom - y), lambda: self.pop(n))

        tx = x0 + 12
        right = x0 + cw - 10
        top = y + 6
        if i == self.hovered:
            # The ×, in the time's place: removes it from the history.
            bs = 18
            bx, by = right - bs + 2, top - 1
            xbox = (bx - 3, by - 3, bs + 6, bs + 6)
            core.rrect(cr, bx, by, bs, bs, bs / 2)
            cr.set_source_rgba(*rgba("hit" if self.hover_x else "bg2"))
            cr.fill()
            core.icon(cr, bx + bs / 2, by + bs / 2, GLYPH_CLOSE, 12, "bg" if self.hover_x else "title", align=0.5)
            if by + bs <= bottom:
                self.xbox = xbox
                hits.add(*xbox, lambda: self.remove(n))
            right = bx - 6
        else:
            when = ago(n.wall, now)
            right -= text(cr, right, top + 1, when, 10, "accent" if new else "dim", align=1, bold=new) + 6
            if new:
                cr.arc(right - 3, top + 8, 3, 0, 6.3)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
                right -= 10
        summary = " ".join(n.summary.split()) or "(no summary)"
        text(cr, tx, top, summary, 13, "title" if new or picked else "fg2", bold=True, width=right - tx - 4)
        lines = self.body_lines(n)
        if lines:
            lay = self.body_layout(cr, n, lines)
            cr.move_to(tx, top + 18)
            cr.set_source_rgba(*rgba("fg2" if new or picked else "fg"))
            from gi.repository import PangoCairo

            PangoCairo.show_layout(cr, lay)

    @staticmethod
    def chip_w(cr, label: str, glyph: str) -> float:
        return core.text_w(cr, label, 11) + core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 23
