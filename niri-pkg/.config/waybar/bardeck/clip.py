"""The clipboard history: what was copied, to copy again. A key-opened panel (no
strip): `bardeck open clip`.

Recording: the daemon keeps ONE long-lived `wl-paste --watch` child (started by
Clip.watch, restarted when it ends, gone with the daemon: PR_SET_PDEATHSIG). It
sleeps in poll() until the selection changes, then runs clipstore.py, a short
stdlib-only process that files the copy in ~/.local/state/bardeck/clip/ (see
clipstore.py: what is kept, what is skipped, the index). Nothing else runs.

The panel reads the index when it opens, and again while open when its mtime
moves. Enter (or a click) copies an entry back with `wl-copy` (with its MIME type
for an image) and closes; the watcher then sees it and moves it to the top.
`p` pins an entry (it stays on top and out of the KEEP cap), `x` removes one,
`c` twice clears all but the pinned, `/` searches (every word must appear).
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time

import cairo

from . import clipstore, core
from .core import Hits, button, rgba, text
from .deck import Panel

_LIBC = ctypes.CDLL(None)  # loaded before any fork: the child only calls prctl
PR_SET_PDEATHSIG = 1

GLYPH_CLIP, GLYPH_SEARCH, GLYPH_PIN, GLYPH_PIN_OFF = "\U000f0a38", "\U000f0349", "\U000f0403", "\U000f0931"
GLYPH_CLOSE, GLYPH_CLEAR, GLYPH_IMAGE, GLYPH_EMPTY = "\U000f0156", "\U000f05e9", "\U000f02e9", "\U000f014c"


def ago(ts: float, now: float) -> str:
    s = max(0, int(now - ts))
    if s < 60:
        return "now"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def matches(e: dict, words: list[str]) -> bool:
    hay = (e.get("head") or "").lower() if e.get("kind") == "text" else f"image {e.get('mime', '')}"
    return all(w in hay for w in words)


def marked(s: str, words: list[str], tone: str) -> str:
    """Pango markup of s with every occurrence of the words in `tone`, bold."""
    from gi.repository import GLib

    low = s.lower()
    hit = [False] * len(s)
    for w in words:
        i = low.find(w)
        while w and i >= 0:
            hit[i:i + len(w)] = [True] * len(w)
            i = low.find(w, i + len(w))
    out, i = [], 0
    colour = core.PALETTE.get(tone, tone)
    while i < len(s):
        j = i
        while j < len(s) and hit[j] == hit[i]:
            j += 1
        chunk = GLib.markup_escape_text(s[i:j], -1)
        out.append(f'<span foreground="{colour}" weight="bold">{chunk}</span>' if hit[i] else chunk)
        i = j
    return "".join(out)


class Clip:
    """The history's index as the panel sees it, and the watcher that fills it."""

    def __init__(self):
        self.entries: list[dict] = []
        self.mtime = -1.0
        self.error = ""
        self.running = False
        self._thumbs: dict[str, cairo.ImageSurface | None] = {}

    # -- the watcher (a thread that keeps one child) ---------------------------

    def watch(self) -> None:
        threading.Thread(target=self._feed, daemon=True, name="wl-paste-watch").start()

    def _feed(self) -> None:
        """`wl-paste --watch`, for ever: restarted when it ends (the compositor
        restarted, the seat went), backing off."""
        wait = 1.0
        argv = ["wl-paste", "--watch", sys.executable, "-I", clipstore.__file__, "store"]
        while True:
            started = time.monotonic()
            try:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        preexec_fn=lambda: _LIBC.prctl(PR_SET_PDEATHSIG, signal.SIGTERM))
                self.running, self.error = True, ""
                proc.wait()
                self.error = f"wl-paste ended ({proc.returncode})"
            except OSError as err:
                self.error = "wl-paste not found" if isinstance(err, FileNotFoundError) else str(err)
                core.log(f"clip: {err!r}")
            self.running = False
            wait = 1.0 if time.monotonic() - started > 30 else min(60.0, wait * 2)
            time.sleep(wait)

    # -- the index -------------------------------------------------------------

    def refresh(self, force: bool = False) -> bool:
        """Re-read the index when it changed. True when it did."""
        try:
            mtime = os.stat(clipstore.path("index.json")).st_mtime
        except OSError:
            mtime = 0.0
        if mtime == self.mtime and not force:
            return False
        self.mtime = mtime
        entries = clipstore.load()
        # Pinned on top (newest first among them), then the rest, newest first.
        self.entries = sorted(entries, key=lambda e: (not e.get("pinned"), -float(e.get("ts", 0))))
        live = {e.get("id") for e in entries}
        self._thumbs = {k: v for k, v in self._thumbs.items() if k in live}
        return True

    def thumb(self, e: dict):
        ident = e.get("id", "")
        if ident not in self._thumbs:
            surf = None
            for f in (clipstore.path(f"{ident}.thumb.png"), clipstore.data_file(e)):
                try:
                    surf = cairo.ImageSurface.create_from_png(f)  # PNG only: cairo's own reader
                    break
                except (cairo.Error, OSError, MemoryError):
                    continue
            self._thumbs[ident] = surf
        return self._thumbs[ident]

    # -- acting ----------------------------------------------------------------

    def copy(self, e: dict) -> None:
        """Put the entry on the clipboard again (wl-copy serves it, detached)."""
        argv = ["wl-copy"]
        if e.get("kind") == "image":
            argv += ["--type", e.get("mime") or "image/png"]
        try:
            with open(clipstore.data_file(e), "rb") as fh:
                subprocess.Popen(argv, stdin=fh, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        except OSError as err:
            self.error = f"copy failed: {err.strerror or err}"

    def pin(self, e: dict) -> None:
        clipstore.change(e["id"], pinned=not e.get("pinned"))
        self.refresh(force=True)

    def remove(self, e: dict) -> None:
        clipstore.remove(e["id"])
        self.refresh(force=True)

    def clear(self) -> None:
        clipstore.clear()
        self.refresh(force=True)


class ClipPanel(Panel):
    name = "clip"
    live = 1.0  # a copy made while it is open shows up; the ages tick
    W = 520
    LIST_MAX = 430
    LINE_H = 15
    IMG_H = 64
    GAP = 4

    def __init__(self, clip: Clip):
        self.clip = clip
        self.sel = 0
        self.top = 0
        self.hovered = -1
        self.hover_btn = ""     # "pin" / "x": the hovered row's button under the pointer
        self.clearing = False   # "clear" asks to be pressed again
        self.searching = False  # the search field has the keyboard
        self.buf = ""
        self.rows: list[tuple[float, float, int]] = []  # (y0, y1, index), for hover
        self.btns: list[tuple[float, float, float, float, str]] = []
        self._lines: dict[tuple, int] = {}
        self._measure = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))

    # -- state -----------------------------------------------------------------

    @property
    def typing(self) -> bool:
        return self.searching

    @property
    def words(self) -> list[str]:
        return self.buf.lower().split()

    @property
    def shown(self) -> list[dict]:
        words = self.words
        return [e for e in self.clip.entries if matches(e, words)] if words else self.clip.entries

    def opened(self) -> None:
        self.clip.refresh()
        self.sel, self.top, self.hovered, self.hover_btn, self.clearing = 0, 0, -1, "", False
        self.searching, self.buf = False, ""

    def closed(self) -> None:
        self.searching = self.clearing = False

    # -- layout ----------------------------------------------------------------

    def text_w(self) -> float:
        return self.W - 2 * 16 - 64  # the row less its padding and the right column

    @staticmethod
    def preview(e: dict) -> str:
        """The first two lines that are not blank, dedented; one long line wraps to two."""
        rows = (e.get("head") or "")[:1200].replace("\t", "    ").replace("\r", "").split("\n")
        rows = [r.rstrip() for r in rows]
        while rows and not rows[0].strip():
            rows.pop(0)
        rows = [r for r in rows[:2] if r.strip()] or [" "]
        return textwrap.dedent("\n".join(rows))

    def lines(self, e: dict) -> int:
        key = (e.get("id"), self.text_w())
        if key not in self._lines:
            lay = self.layout(self._measure, e, markup=False)
            self._lines[key] = max(1, min(2, lay.get_line_count()))
        return self._lines[key]

    def layout(self, cr, e: dict, markup: bool = True):
        from gi.repository import Pango

        s = self.preview(e)
        words = self.words
        lay = core.layout(cr, marked(s, words, "warn") if markup and words else s, 12,
                          markup=bool(markup and words), width=self.text_w())
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        # A negative height counts lines per paragraph: two lines are one line each.
        lay.set_height(-1 if "\n" in s else -2)
        return lay

    def row_h(self, e: dict) -> float:
        if e.get("kind") == "image":
            return self.IMG_H
        return 14 + self.lines(e) * self.LINE_H

    def room(self) -> float:
        total = sum(self.row_h(e) + self.GAP for e in self.shown)
        return min(self.LIST_MAX, total) if self.shown else 90

    def max_top(self) -> int:
        shown, room = self.shown, self.room()
        top, used = len(shown), 0.0
        while top > 0 and used + self.row_h(shown[top - 1]) + self.GAP <= room + 0.5:
            top -= 1
            used += self.row_h(shown[top]) + self.GAP
        return top

    def size(self):
        return self.W, 12 + 28 + 22 + 36 + self.room() + 16 + 26

    def follow(self) -> None:
        shown = self.shown
        self.sel = max(0, min(self.sel, len(shown) - 1))
        self.top = max(0, min(self.top, self.max_top()))
        if self.sel < self.top:
            self.top = self.sel
        room = self.room()
        while self.top < self.sel and sum(self.row_h(e) + self.GAP for e in shown[self.top:self.sel + 1]) > room:
            self.top += 1

    # -- actions ---------------------------------------------------------------

    def copy(self, e: dict) -> bool:
        self.clip.copy(e)
        return True  # closes the panel: paste where you were

    def pin(self, e: dict) -> bool:
        self.clearing = False
        self.clip.pin(e)
        return False

    def remove(self, e: dict) -> bool:
        self.clearing = False
        self.clip.remove(e)
        self.hovered = -1
        self.follow()
        return False

    def clear(self) -> bool:
        if not self.clearing:
            self.clearing = True  # the chip turns red: a second press clears
            return False
        self.clearing = False
        self.clip.clear()
        self.sel = self.top = 0
        return False

    def move(self, key: str, ctrl: bool) -> bool:
        """The keys that move the selection, in the list and in the field."""
        n = len(self.shown)
        half = 4
        if key == "Down" or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key == "Up" or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key == "Page_Down" or (ctrl and key == "v" and not self.searching):
            self.sel = min(n - 1, self.sel + half)
        elif key == "Page_Up":
            self.sel = max(0, self.sel - half)
        else:
            return False
        self.follow()
        return True

    # -- input -----------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool:
        shown = self.shown
        sel = shown[self.sel] if 0 <= self.sel < len(shown) else None
        if key == "c" and not ctrl:
            return self.clear() or True
        self.clearing = False
        if self.move(key, ctrl):
            return True
        if key == "i":
            return self.move("Down", False)
        if key == "o":
            return self.move("Up", False)
        if key == "k":
            return self.move("Page_Down", False)
        if key == "l":
            return self.move("Page_Up", False)
        if key == "slash":
            self.searching = True
        elif key in ("Return", "KP_Enter") and sel is not None:
            self.copy(sel)
            self.close()
        elif key == "p" and not ctrl and sel is not None:
            self.pin(sel)
            self.sel = next((i for i, e in enumerate(self.shown) if e.get("id") == sel.get("id")), 0)
            self.follow()
        elif key in ("x", "Delete") and sel is not None:
            self.remove(sel)
        else:
            return False
        return True

    def text_key(self, key: str, char: str, ctrl: bool) -> bool:
        if self.move(key, ctrl):
            return True
        if key == "Escape" or (ctrl and key == "g"):
            self.searching, self.buf = False, ""
        elif key in ("Return", "KP_Enter", "Tab"):
            self.searching = False  # back to the list, the filter kept
        elif key == "BackSpace":
            self.buf = "" if ctrl else self.buf[:-1]
        elif ctrl and key == "u":
            self.buf = ""
        elif char and not ctrl:
            self.buf += char
        else:
            return False
        self.sel, self.top = 0, 0
        return True

    def hover(self, x: float, y: float) -> bool:
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        btn = next((b for bx, by, bw, bh, b in self.btns if idx == self.hovered and bx <= x < bx + bw
                    and by <= y < by + bh), "")
        if (idx, btn) != (self.hovered, self.hover_btn):
            self.hovered, self.hover_btn = idx, btn
            return True
        return False

    def scroll(self, down: bool) -> bool:
        top = max(0, min(self.top + (1 if down else -1), self.max_top()))
        if top == self.top:
            return False
        self.top = top
        return True

    # -- drawing ---------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        clip = self.clip
        if clip.refresh():
            self.follow()
        W, P = self.W, 16
        H = self.size()[1]
        core.panel_frame(cr, W, H)
        y = 12
        core.icon(cr, P, y + 11, GLYPH_CLIP, 20, "title")
        text(cr, P + 28, y, "Clipboard", 18, "title", bold=True)
        if clip.entries:
            label = "clear?" if self.clearing else "clear"
            cw = core.text_w(cr, label, 11) + core.text_w(cr, GLYPH_CLEAR, 13, family=core.ICON_FONT) + 23
            button(cr, hits, W - P - cw, y + 1, label, self.clear, h=22, size=11, glyph=GLYPH_CLEAR,
                   on=self.clearing, tone="hit")
        y += 28
        pinned = sum(1 for e in clip.entries if e.get("pinned"))
        n = len(clip.entries)
        words = [f"{n} {'entry' if n == 1 else 'entries'}"] + ([f"{pinned} pinned"] if pinned else [])
        if self.words:
            words.insert(0, f"{len(self.shown)} found")
        x = P + 28 + text(cr, P + 28, y, " · ".join(words), 12, "dim")
        if clip.error:
            text(cr, x, y, f" · {clip.error}", 12, "hit")
        y += 22
        self.draw_field(cr, hits, P, y)
        y += 36
        self.draw_list(cr, hits, P, y)
        hint = ("type to search · Enter list · Esc clear" if self.searching else
                "Enter copy · p pin · x remove · / search · c clear · Esc close")
        text(cr, W / 2, H - 20, hint, 10, "dim", align=0.5)

    def draw_field(self, cr, hits: Hits, P: float, y: float) -> None:
        x0, fw, fh = P - 6, self.W - 2 * P + 12, 26
        core.rrect(cr, x0 + 0.5, y + 0.5, fw - 1, fh - 1, 7)
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("accent" if self.searching else "bg2"))
        cr.set_line_width(1.2 if self.searching else 1)
        cr.stroke()
        mid = y + fh / 2
        core.icon(cr, x0 + 10, mid, GLYPH_SEARCH, 13, "accent" if self.searching else "dim")
        hits.add(x0, y, fw, fh, lambda: setattr(self, "searching", True))
        tx = x0 + 30
        if self.buf:
            tw = text(cr, tx, mid, self.buf, 13, "title", valign=0.5, width=fw - 40)
        else:
            tw = 0
            if not self.searching:
                text(cr, tx, mid, "/ to search", 12, "dim", valign=0.5)
        if self.searching:
            cr.rectangle(tx + tw + 1, y + 6, 1.5, fh - 12)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()

    def draw_list(self, cr, hits: Hits, P: float, y: float) -> None:
        W = self.W
        shown = self.shown
        self.rows, self.btns = [], []
        room = self.room()
        if not shown:
            mid = y + room / 2
            core.icon(cr, W / 2, mid - 10, GLYPH_EMPTY, 24, "bg3", align=0.5)
            words = ("no match" if self.words else
                     "nothing copied yet" if self.clip.running or not self.clip.error else "not recording")
            text(cr, W / 2, mid + 8, words, 12, "dim", align=0.5)
            return
        self.top = max(0, min(self.top, self.max_top()))
        bottom = y + room
        now = time.time()
        more = 0
        cr.save()
        cr.rectangle(0, y, W, room)
        cr.clip()
        for i in range(self.top, len(shown)):
            e = shown[i]
            h = self.row_h(e)
            if y + h > bottom + 0.5:
                more += 1
            if y >= bottom:
                continue
            self.draw_row(cr, hits, P, y, i, e, now, bottom)
            self.rows.append((y, min(y + h + self.GAP, bottom), i))
            y += h + self.GAP
        cr.restore()
        if more:
            fade = cairo.LinearGradient(0, bottom - 16, 0, bottom)
            fade.add_color_stop_rgba(0, *rgba("bg", 0.0))
            fade.add_color_stop_rgba(1, *rgba("bg", 0.97))
            cr.rectangle(1, bottom - 16, W - 2, 16)
            cr.set_source(fade)
            cr.fill()
            above = f"▴ {self.top} above · " if self.top else ""
            text(cr, W - P, bottom + 1, f"{above}▾ {more} more", 10, "dim", align=1)
        elif self.top:
            text(cr, W - P, bottom + 1, f"▴ {self.top} above", 10, "dim", align=1)

    def draw_row(self, cr, hits: Hits, P: float, y: float, i: int, e: dict, now: float, bottom: float) -> None:
        W = self.W
        x0, rw = P - 6, W - 2 * P + 12
        h = self.row_h(e)
        picked = i == self.sel or i == self.hovered
        core.rrect(cr, x0, y, rw, h, 7)
        if e.get("pinned"):
            cr.set_source_rgba(*rgba("accent", 0.16 if not picked else 0.26))
        else:
            cr.set_source_rgba(*rgba("bg1", 1.0 if picked else 0.45))
        cr.fill()
        if i == self.sel:  # the keyboard's mark: a bar at the left edge
            core.rrect(cr, x0 + 1, y + 6, 3, h - 12, 1.5)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
        hits.add(x0, y, rw, min(h, bottom - y), lambda: self.copy(e))

        # The right column: age and pin mark; on the hovered row the pin and × buttons.
        right = x0 + rw - 8
        top = y + 6
        if i == self.hovered:
            bs = 20
            for label, glyph, action in (("x", GLYPH_CLOSE, lambda: self.remove(e)),
                                         ("pin", GLYPH_PIN_OFF if e.get("pinned") else GLYPH_PIN,
                                          lambda: self.pin(e))):
                bx = right - bs
                on = self.hover_btn == label
                core.rrect(cr, bx, top - 1, bs, bs, bs / 2)
                cr.set_source_rgba(*rgba(("hit" if label == "x" else "accent") if on else "bg2"))
                cr.fill()
                core.icon(cr, bx + bs / 2, top - 1 + bs / 2, glyph, 12, "bg" if on else "title", align=0.5)
                if top + bs <= bottom:
                    box = (bx - 2, top - 3, bs + 4, bs + 4)
                    self.btns.append((*box, label))
                    hits.add(*box, action)
                right = bx - 6
        else:
            right -= text(cr, right, top + 1, ago(float(e.get("ts", 0)), now), 10, "dim", align=1)
            if e.get("pinned"):
                core.icon(cr, right - 4, top + 8, GLYPH_PIN, 11, "accent", align=1)

        tx = x0 + 12
        if e.get("kind") == "image":
            self.draw_image(cr, tx, y, h, e, picked)
            return
        lay = self.layout(cr, e)
        cr.move_to(tx, top)
        cr.set_source_rgba(*rgba("title" if picked else "fg2"))
        from gi.repository import PangoCairo

        PangoCairo.show_layout(cr, lay)

    def draw_image(self, cr, x: float, y: float, h: float, e: dict, picked: bool) -> None:
        box_h, box_w = h - 12, 150
        surf = self.clip.thumb(e)
        tw = 0.0
        if surf is not None and surf.get_width() and surf.get_height():
            k = min(box_h / surf.get_height(), box_w / surf.get_width())
            tw, th = surf.get_width() * k, surf.get_height() * k
            ty = y + (h - th) / 2
            cr.save()
            core.rrect(cr, x, ty, tw, th, 4)
            cr.clip()
            cr.translate(x, ty)
            cr.scale(k, k)
            cr.set_source_surface(surf, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
            cr.restore()
            core.rrect(cr, x + 0.5, ty + 0.5, tw - 1, th - 1, 4)
            cr.set_source_rgba(*rgba("bg2"))
            cr.set_line_width(1)
            cr.stroke()
        else:
            tw = box_h
            core.rrect(cr, x, y + 6, tw, box_h, 4)
            cr.set_source_rgba(*rgba("bg2"))
            cr.fill()
            core.icon(cr, x + tw / 2, y + h / 2, GLYPH_IMAGE, 20, "dim", align=0.5)
        tx = x + tw + 12
        mid = y + h / 2
        size = f"{e['w']}×{e['h']}" if e.get("w") else "image"
        text(cr, tx, mid - 9, size, 13, "title" if picked else "fg2", bold=True, valign=0.5)
        mime = (e.get("mime") or "image").split("/")[-1].upper()
        text(cr, tx, mid + 9, f"{mime} · {core.human_bytes(e.get('size', 0))}", 11, "dim", valign=0.5)
