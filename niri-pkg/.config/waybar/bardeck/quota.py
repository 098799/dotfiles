"""Claude quota: the strip (a week chart per account) and its panel (every week).

All numbers and verdicts come from qtop (~/bin/qtop, imported, not copied), which
reads rcmon's usage federation files. Nothing here asks Anthropic.

The strip, per account:

    W [▁▂▄▆ ╱ ┊ ‥]▮ 33     one cell per account
       │    │  │  │  └ weekly %, in the verdict's colour
       │    │  │  └── the 5h window, as a tank (blue; yellow over burn's ceiling, red at 100%)
       │    │  └───── projection from the last 24 h to the reset
       │    └──────── even pace to 95% at the reset (the line to stay near)
       └───────────── this quota week's usage, from its start to the reset

    colour = qtop's verdict: green lands well, yellow wastes points, red hits 100%
    early. The active account (right-click to switch) is underlined.

The panel: every account's week full size, its 5h peaks against burn's ceiling, the
pool totals. Pinned: u/p earlier/later week, i/o select, Enter or a click on a card
opens `qtop <account>`.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import math
import os
import shutil
import time
from datetime import datetime, timedelta

import cairo

from . import core
from .core import BAR_H, PALETTE, rgba, rrect, text
from .core import text_w as text_width
from .deck import Panel

ACCOUNT_FILE = f"{core.REAL_HOME}/.config/claude-active-account"


def load_qtop():
    """qtop's model (Store, Week, verdicts), imported from the script itself."""
    path = shutil.which("qtop") or f"{core.REAL_HOME}/bin/qtop"
    loader = importlib.machinery.SourceFileLoader("qtop", path)
    spec = importlib.util.spec_from_loader("qtop", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


Q = load_qtop()


class Row:
    """One account now: its week (or a past one), its 5h window, and how to say it."""

    def __init__(self, m, account: str, active: str, now: float, back: int = 0):
        self.account = account
        self.label = Q.LETTER.get(account, account[:2].upper())
        self.active = account == active
        self.pool = Q.pool_of(account)
        self.week, self.back, self.weeks = m.week_of(account, back)
        last = m.store.last(account)
        self.stale = last is None or now - last.t > Q.STALE_S
        self.five_live = bool(last and last.r5 and last.r5 > now and not self.stale)
        self.u5 = (last.u5 or 0.0) if self.five_live else 0.0
        self.r5 = (last.r5 - now) if self.five_live else None
        if self.week is None:
            self.verdict, self.tone = "no readings", "dim"
        else:
            self.verdict, self.tone = Q.week_verdict(self.week, now)
        if self.stale and back == 0:
            why = m.why(account)
            age = Q.ago(now - last.t) if last else "ever"
            self.verdict, self.tone = (f"{why} · {age}" if why else f"no reading for {age}"), "dim"
        # "over" = the week in the log has reset and no reading of the new one came yet.
        self.over = self.week is None or (back == 0 and self.week.over(now))

    @property
    def colour(self) -> str:
        return self.tone if self.tone in ("ok", "warn", "hit") else "dim"

    def five_colour(self) -> str:
        if self.u5 >= 100:
            return "hit"
        return "warn" if self.u5 >= Q.CEILING[self.pool] else "fg"


def rows(m, now: float, back: int = 0) -> list[Row]:
    active = read_active()
    return [Row(m, a, active, now, back) for a in m.accounts()]


def read_active() -> str:
    try:
        with open(ACCOUNT_FILE) as fh:
            return fh.read().strip()
    except OSError:
        return "work"


def week_chart(cr, x: float, y: float, w: float, h: float, row: Row, now: float, *,
               detail: bool) -> None:
    """qtop's week chart drawn with cairo: usage area, even pace, projection, now.

    detail=False is the bar's thumbnail: no labels, the lines only. detail=True adds
    the day bands, the 50% and target rules, and the end labels."""
    wk = row.week
    cr.save()
    rrect(cr, x, y, w, h, 2 if detail else 1.5)
    cr.set_source_rgba(*rgba("bg1" if detail else "bg1"))
    cr.fill_preserve()
    cr.clip()
    if wk is None:
        cr.restore()
        return

    def X(t: float) -> float:
        return x + (t - wk.start) / Q.WEEK * w

    def Y(v: float) -> float:
        return y + h - max(0.0, min(100.0, v)) / 100 * h

    if detail:
        # Alternate day bands, from local midnight.
        day = datetime.fromtimestamp(wk.start).replace(hour=0, minute=0, second=0, microsecond=0)
        i = 0
        while day.timestamp() < wk.reset:
            if i % 2:
                a, b = X(day.timestamp()), X((day + timedelta(days=1)).timestamp())
                cr.rectangle(a, y, b - a, h)
                cr.set_source_rgba(*rgba("bg", 0.35))
                cr.fill()
            day += timedelta(days=1)
            i += 1
        cr.set_line_width(1)
        cr.set_source_rgba(*rgba("sep"))
        for v in (25, 50, 75):
            cr.move_to(x, round(Y(v)) + 0.5)
            cr.line_to(x + w, round(Y(v)) + 0.5)
        cr.set_dash([1, 3])
        cr.stroke()
        cr.set_dash([])

    tone = row.colour if not row.over else "dim"
    pts = [(X(t), Y(v)) for t, v in wk.points]

    # Even pace to TARGET at the reset.
    cr.set_line_width(1.0 if detail else 0.8)
    cr.set_source_rgba(*rgba("pace", 0.9 if detail else 0.75))
    cr.set_dash([3, 3] if detail else [1.5, 1.5])
    cr.move_to(X(wk.start), Y(0))
    cr.line_to(X(wk.reset), Y(Q.TARGET))
    cr.stroke()
    cr.set_dash([])

    if pts:
        # Area under the usage line, then the line.
        cr.move_to(pts[0][0], y + h)
        for px, py in pts:
            cr.line_to(px, py)
        cr.line_to(pts[-1][0], y + h)
        cr.close_path()
        grad = cairo.LinearGradient(0, y, 0, y + h)
        grad.add_color_stop_rgba(0, *rgba(tone, 0.55)[:3], 0.55)
        grad.add_color_stop_rgba(1, *rgba(tone, 0.15)[:3], 0.15)
        cr.set_source(grad)
        cr.fill()
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.set_source_rgba(*rgba(tone))
        cr.set_line_width(1.5 if detail else 1.2)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

        # Projection from the last 24 h: to 100% and flat from there when it walls.
        proj = wk.projected(now) if row.back == 0 else None
        if proj is not None:
            full = wk.full_at(now)
            cr.move_to(*pts[-1])
            if full is not None:
                cr.line_to(X(full), Y(100))
                cr.line_to(X(wk.reset), Y(100))
            else:
                cr.line_to(X(wk.reset), Y(proj))
            cr.set_source_rgba(*rgba(tone, 0.85))
            cr.set_line_width(1.0)
            cr.set_dash([2, 2] if detail else [1.2, 1.2])
            cr.stroke()
            cr.set_dash([])
            if full is not None:
                cr.arc(X(full), Y(100) + (3 if detail else 1.2), 3 if detail else 1.4, 0, 2 * math.pi)
                cr.set_source_rgba(*rgba("hit"))
                cr.fill()

    # Now.
    if row.back == 0 and wk.start < now < wk.reset:
        cr.move_to(round(X(now)) + 0.5, y)
        cr.line_to(round(X(now)) + 0.5, y + h)
        cr.set_source_rgba(*rgba("title", 0.45 if detail else 0.35))
        cr.set_line_width(1)
        cr.stroke()
    cr.restore()


def peaks_chart(cr, x: float, y: float, w: float, h: float, row: Row) -> None:
    """The 5h windows of the week, one bar per window, against burn's ceiling."""
    wk = row.week
    if wk is None:
        return
    ceiling = Q.CEILING[row.pool]

    def X(t: float) -> float:
        return x + (t - wk.start) / Q.WEEK * w

    for end, peak in wk.windows:
        a, b = X(end - 5 * 3600), X(end)
        a, b = max(a, x), min(b, x + w)
        if b <= a:
            continue
        bh = max(1.0, min(100.0, peak) / 100 * h)
        cr.rectangle(a + 0.5, y + h - bh, max(1.0, b - a - 1), bh)
        colour = "hit" if peak >= 100 else ("warn" if peak >= ceiling else "fg")
        cr.set_source_rgba(*rgba(colour, 0.9 if colour != "fg" else 0.55))
        cr.fill()
    cy = round(y + h - ceiling / 100 * h) + 0.5
    cr.move_to(x, cy)
    cr.line_to(x + w, cy)
    cr.set_source_rgba(*rgba("warn", 0.5))
    cr.set_line_width(1)
    cr.set_dash([2, 3])
    cr.stroke()
    cr.set_dash([])


# ── the strip ────────────────────────────────────────────────────────────────

# Cell sizes; the strip's width follows the number of accounts.
STRIP = {
    "full": {"chart": 36, "pct": True},
    "compact": {"chart": 28, "pct": False},
}


def strip_layout(cr, rs: list[Row], variant: str) -> tuple[list[tuple[Row, float, float]], float]:
    """(row, x, width) per cell, and the strip's width."""
    spec = STRIP[variant]
    gap, edge = 8.0, 9.0
    out, x = [], edge
    for r in rs:
        w = text_width(cr, r.label, 13, bold=True) + 3 + spec["chart"] + 2 + 3
        if spec["pct"]:
            w += 3 + text_width(cr, "100", 13)
        out.append((r, x, w))
        x += w + gap
    return out, x - gap + edge


def draw_strip(rs: list[Row], now: float, variant: str, scale: int):
    probe = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    cells, width = strip_layout(probe, rs, variant)
    surf, cr = core.surface(width, BAR_H, scale)
    core.pill(cr, width)
    chart = STRIP[variant]["chart"]
    top, ch = 5.0, BAR_H - 10.0
    for r, x, w in cells:
        dim = r.over or r.stale
        lw = text(cr, x, BAR_H / 2, r.label, 13, "title" if r.active else ("dim" if dim else "fg"),
                  bold=r.active, valign=0.5)
        cx = x + lw + 3
        week_chart(cr, cx, top, chart, ch, r, now, detail=False)
        if dim:
            text(cr, cx + chart / 2, BAR_H / 2, "?", 13, "dim", align=0.5, valign=0.5)
        # 5h tank: blue under the ceiling, so it never reads as a weekly verdict colour.
        tx = cx + chart + 2
        cr.rectangle(tx, top, 3, ch)
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill()
        if r.five_live and r.u5 > 0:
            th = max(1.0, min(100.0, r.u5) / 100 * ch)
            cr.rectangle(tx, top + ch - th, 3, th)
            cr.set_source_rgba(*rgba("pace" if r.five_colour() == "fg" else r.five_colour()))
            cr.fill()
        if STRIP[variant]["pct"]:
            pct = "?" if dim else f"{r.week.used:.0f}"
            text(cr, tx + 6, BAR_H / 2, pct, 13, "dim" if dim else r.colour, bold=r.active, valign=0.5)
        if r.active:
            rrect(cr, x - 2, BAR_H - 4, w + 4, 2, 1)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
    return surf


# ── the deck (the drop-down) ─────────────────────────────────────────────────

DECK_W = 860
HEAD_H = 46
CARD_H = 112
FOOT_H = 26
INFO_W = 230
PAD = 14


def deck_size(n: int) -> tuple[int, int]:
    return DECK_W, HEAD_H + n * CARD_H + FOOT_H


def draw_deck(cr, m, now: float, back: int, sel: int) -> list[tuple[str, float, float]]:
    """Draw the deck at (0, 0). Returns (account, y0, y1) per card, for clicks."""
    rs = rows(m, now, back)
    w, h = deck_size(len(rs))
    core.panel_frame(cr, w, h)

    # Header: title, freshness, federation, clock; the pools under it.
    x = text(cr, PAD, 8, "Claude quota", 16, "title", bold=True) + PAD + 10
    newest = m.store.newest()
    fresh = now - newest
    dot = "ok" if fresh < 300 else ("warn" if fresh < Q.STALE_S else "hit")
    x += text(cr, x, 10, "●", 13, dot) + 4
    x += text(cr, x, 10, f"sample {Q.ago(fresh)} ago" if newest else "no samples", 13, "dim") + 12
    fed = m.fed()
    if not fed or now - float(fed.get("updated_at") or 0) > Q.FED_DOWN_S:
        text(cr, x, 10, "federation silent — is rcmon running?", 13, "hit")
    else:
        peers = fed.get("peers") or {}
        bad = [n for n, p in peers.items()
               if p.get("error") or not p.get("pulled_at") or now - p["pulled_at"] > 300]
        x += text(cr, x, 10, "fed ", 13, "dim")
        x += text(cr, x, 10, "●", 13, "warn" if bad else "ok") + 4
        text(cr, x, 10, " ".join(f"{n}{'✗' if n in bad else '✓'}" for n in peers), 13, "dim")
    stamp = datetime.fromtimestamp(now).strftime("%a %d %b %H:%M")
    if back:
        stamp = f"{back} week{'s' if back > 1 else ''} back · " + stamp
    text(cr, w - PAD, 10, stamp, 13, "warn" if back else "dim", align=1)
    pools = "".join(t for t, _ in Q.pool_summary(m, now)).strip()
    text(cr, PAD, 27, pools or " ", 12, "fg")

    hits = []
    for i, r in enumerate(rs):
        y0 = HEAD_H + i * CARD_H
        hits.append((r.account, y0, y0 + CARD_H))
        cr.move_to(PAD, y0 + 0.5)
        cr.line_to(w - PAD, y0 + 0.5)
        cr.set_source_rgba(*rgba("sep", 0.7))
        cr.set_line_width(1)
        cr.stroke()
        if i == sel:
            cr.rectangle(1, y0 + 1, w - 2, CARD_H - 1)
            cr.set_source_rgba(*rgba("alt", 0.45))
            cr.fill()
        if r.active:
            cr.rectangle(1, y0 + 8, 3, CARD_H - 16)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
        draw_card(cr, r, now, PAD, y0 + 8, w - 2 * PAD, CARD_H - 16)

    hint = "click a card or Enter: qtop on it · i/o select · u/p earlier/later week · esc closes"
    text(cr, w / 2, h - FOOT_H + 5, hint, 12, "dim", align=0.5)
    return hits


def draw_card(cr, r: Row, now: float, x: float, y: float, w: float, h: float) -> None:
    # Info column.
    lw = text(cr, x + 4, y - 2, r.label, 22, "title" if r.active else "fg", bold=True)
    name = r.account + (f" · {Q.ALIAS[r.account]}" if r.account in Q.ALIAS else "")
    text(cr, x + 12 + lw, y + 1, name, 14, "title")
    pool_x = x + 12 + lw
    text(cr, pool_x, y + 17, r.pool + (" · active" if r.active else ""), 12, "max" if r.pool == "max" else "team")

    wk = r.week
    if wk is not None and not r.over:
        big = text(cr, x + 4, y + 34, f"{wk.used:.0f}%", 26, r.colour, bold=True)
        sub = f"week {Q.when(wk.start, now)} → {Q.when(wk.reset, now)}" if r.back else f"↻ {Q.dur(wk.reset - now)}"
        text(cr, x + 10 + big, y + 38, sub, 12, "dim")
        pace = wk.pace(now) if r.back == 0 else None
        if pace is not None:
            text(cr, x + 10 + big, y + 52, f"pace {pace:+.0f} pts", 12,
                 "warn" if pace > 10 else ("ok" if pace > -15 else "pace"))
    else:
        text(cr, x + 4, y + 34, "?%", 26, "dim", bold=True)
        if wk is not None:
            text(cr, x + 50, y + 44, f"reset {Q.when(wk.reset, now)}", 12, "dim")
    text(cr, x + 4, y + 68, r.verdict, 13, r.tone if r.tone != "dim" else "dim", bold=r.tone == "hit")

    # 5h meter.
    my = y + h - 6
    mw = 120
    cr.rectangle(x + 4, my, mw, 5)
    cr.set_source_rgba(*rgba("alt"))
    cr.fill()
    if r.five_live:
        cr.rectangle(x + 4, my, mw * min(100.0, r.u5) / 100, 5)
        cr.set_source_rgba(*rgba(r.five_colour() if r.five_colour() != "fg" else "pace"))
        cr.fill()
    ceiling = Q.CEILING[r.pool]
    cr.rectangle(x + 4 + mw * ceiling / 100, my - 2, 1, 9)
    cr.set_source_rgba(*rgba("warn", 0.7))
    cr.fill()
    five = f"5h {r.u5:.0f}% ↻ {Q.dur(r.r5)}" if r.five_live else "5h idle"
    text(cr, x + mw + 10, my - 6, five, 12, "fg" if r.five_live else "dim")

    # Chart, the 5h peaks under it, the day names under those.
    cx, cw = x + INFO_W, w - INFO_W - 44
    peaks_h, label_h = 12, 13
    chh = h - peaks_h - label_h - 4
    week_chart(cr, cx, y, cw, chh, r, now, detail=True)
    peaks_chart(cr, cx, y + chh + 2, cw, peaks_h, r)
    if wk is None:
        return

    def X(t: float) -> float:
        return cx + (t - wk.start) / Q.WEEK * cw

    def Y(v: float) -> float:
        return y + chh - max(0.0, min(100.0, v)) / 100 * chh

    day = datetime.fromtimestamp(wk.start).replace(hour=0, minute=0, second=0, microsecond=0)
    while day.timestamp() < wk.reset:
        noon = X(day.timestamp() + 43200)
        if cx + 8 < noon < cx + cw - 8:
            text(cr, noon, y + h - label_h + 1, f"{day:%a}", 11, "dim", align=0.5)
        day += timedelta(days=1)
    # Right-hand labels: target, projection, now value — skipped when they would overlap.
    taken: list[float] = []

    def label(v: float, s: str, colour: str) -> None:
        ly = Y(v) - 7
        if any(abs(ly - t) < 11 for t in taken):
            return
        taken.append(ly)
        text(cr, cx + cw + 5, ly, s, 11, colour)

    if not r.over:
        label(wk.used, f"{wk.used:.0f}%", r.colour)
        proj = wk.projected(now) if r.back == 0 else None
        if proj is not None:
            label(proj, f"~{proj:.0f}%", r.colour)
    label(Q.TARGET, f"{Q.TARGET:.0f}%", "pace")


def model():
    """qtop's model, with Store.weeks cached until the log grows.

    weeks() rebuilds every week from the whole log, and a deck draw asks for it twice
    per account (the cards and the pool totals): two thirds of the draw time."""
    m = Q.Model(Q.Store(Q.CSV))
    store, raw, cache = m.store, m.store.weeks, {}

    def weeks(account: str):
        key = (account, store.offset)
        if key not in cache:
            for old in [k for k in cache if k[1] != store.offset]:
                del cache[old]
            cache[key] = raw(account)
        return cache[key]

    store.weeks = weeks
    return m


# ── the strip and panel objects bardeck drives ───────────────────────────────


class Quota:
    """The data (qtop's model, weeks cached) and the strip; QuotaPanel draws the panel."""

    name = "quota"

    def __init__(self):
        self.m = model()
        self.seen = None

    def changed(self) -> bool:
        """New readings, a switched account, or a new minute (the "now" line moves)."""
        def mt(p):
            try:
                return os.stat(p).st_mtime
            except OSError:
                return 0.0
        key = (mt(Q.CSV), mt(Q.SNAPSHOT), mt(ACCOUNT_FILE), int(time.time() // 60))
        if key == self.seen:
            return False
        self.seen = key
        self.m.store.load()
        return True

    def strips(self, variant: str, scale: int):
        now = time.time()
        return draw_strip(rows(self.m, now), now, variant, scale)


class QuotaPanel(Panel):
    name = "quota"
    drawn_ahead = True

    def __init__(self, quota: Quota):
        self.q = quota
        self.back, self.sel = 0, -1

    def size(self):
        return deck_size(len(self.q.m.accounts()))

    def opened(self) -> None:
        accts = self.q.m.accounts()
        active = read_active()
        self.back, self.sel = 0, (accts.index(active) if active in accts else -1)

    def state(self) -> tuple:
        return (self.back, self.sel)

    def draw(self, cr, hits: core.Hits) -> None:
        cards = draw_deck(cr, self.q.m, time.time(), self.back, self.sel)
        w, _ = self.size()
        for account, y0, y1 in cards:
            hits.add(0, y0, w, y1 - y0, lambda a=account: open_qtop(a))

    def key(self, key: str, ctrl: bool) -> bool:
        n = len(self.q.m.accounts())
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = (self.sel + 1) % n
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = (self.sel - 1) % n
        elif key in ("u", "Left") or (ctrl and key == "b"):
            self.back += 1
        elif key in ("p", "Right") or (ctrl and key == "f"):
            self.back = max(0, self.back - 1)
        elif key in ("Return", "KP_Enter") and 0 <= self.sel < n:
            open_qtop(self.q.m.accounts()[self.sel])
        else:
            return False
        return True


def open_qtop(account: str) -> bool:
    core.spawn(["alacritty", "-e", "qtop", account])
    return True  # close the panel
