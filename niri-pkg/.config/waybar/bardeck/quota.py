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

FOLDED (13 Oct 2026): only the active account gets that cell; every other account is
one thin gauge after it — its weekly % as the fill, in the verdict's colour (a dim
stub when it has no fresh reading). Six full cells took 636 px and pushed the clock
off the screen; the panel (hover) still shows every account at full size.

The panel: every account's week full size, its 5h peaks against burn's ceiling, the
pool totals. Two columns: cc (Claude Code) and agy (Antigravity). Each has two
sections: "main (private)" (the personal Max accounts: private, main2, agy's main)
and "work (others)" (everything else). Pinned: u/p earlier/later week, i/o select
(down each column, then the next), Enter or a click on a card opens `qtop <account>`.
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
from .core import BAR_H, MID, PALETTE, PILL_H, PILL_Y, SH, rgba, rrect, text
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
        self.name = account + (f" · {Q.ALIAS[account]}" if account in Q.ALIAS else "")
        self.ceiling = Q.CEILING[self.pool]
        self.extra: list[tuple[str, object]] = []  # agy: the other weekly buckets (label, Week)

    @property
    def colour(self) -> str:
        return self.tone if self.tone in ("ok", "warn", "hit") else "dim"

    def five_colour(self) -> str:
        if self.u5 >= 100:
            return "hit"
        return "warn" if self.u5 >= self.ceiling else "fg"


# ── agy (Antigravity CLI) accounts ───────────────────────────────────────────
#
# qtop lists them (Model.accounts() adds "agy:<home>"), but its Store reads only
# claude-usage.csv, so their cards had no week. rcmon's agy_federation.py writes a
# history beside it, one row per bucket per reading; AgyHistory reads that.

AGY_HISTORY = os.environ.get("AGY_USAGE_HISTORY") or f"{core.REAL_HOME}/.local/state/w95/agy-usage.csv"
AGY_FIVE = {"gemini-weekly": "gemini-5h", "3p-weekly": "3p-5h"}  # a weekly bucket's 5h sibling
FLOAT_S = 1800  # an unused bucket's reset floats at now + its window; this close = not started


def _floating(t: float, used: float, reset: float, window: float) -> bool:
    return used <= 0 and abs(reset - (t + window)) < FLOAT_S


class AgyHistory:
    """agy-usage.csv, read incrementally: {(home, bucket): [(t, used, reset)]}."""

    def __init__(self, path: str = AGY_HISTORY):
        self.path = path
        self.offset, self.inode, self.tail = 0, None, ""
        self.rows: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
        self._weeks: dict[tuple[str, str], list] = {}

    def load(self) -> bool:
        try:
            st = os.stat(self.path)
        except OSError:
            return False
        if st.st_ino != self.inode or st.st_size < self.offset:
            self.offset, self.tail, self.rows, self.inode = 0, "", {}, st.st_ino
        if st.st_size == self.offset:
            return False
        with open(self.path, encoding="utf-8", errors="replace") as fh:
            fh.seek(self.offset)
            chunk = fh.read()
            self.offset = fh.tell()
        lines = (self.tail + chunk).split("\n")
        self.tail = lines.pop()
        for line in lines:
            # timestamp,account,group,bucket,window,used,resets_at — the group may hold a comma.
            p = line.split(",")
            if len(p) < 7 or p[0] == "timestamp":
                continue
            t, reset = Q.iso_ts(p[0]), Q.iso_ts(p[-1])
            try:
                used = float(p[-2])
            except ValueError:
                continue
            if t is None or reset is None:
                continue
            self.rows.setdefault((p[1], p[-4]), []).append((t, used, reset))
        self._weeks.clear()
        return True

    def trim(self, cutoff: float) -> None:
        for rs in self.rows.values():
            if rs and rs[0][0] < cutoff:
                rs[:] = [r for r in rs if r[0] >= cutoff]
        self._weeks.clear()

    def buckets(self, home: str) -> list[str]:
        """The weekly buckets of one home, in the snapshot's order where it has one."""
        acc = Q.agy_account(home) or {}
        order = [str(b.get("id")) for b in acc.get("buckets") or [] if isinstance(b, dict)]
        have = [b for (h, b) in self.rows if h == home and b.endswith("-weekly")]
        return [b for b in order if b in have] + sorted(b for b in have if b not in order)

    def last(self, home: str, bucket: str) -> tuple[float, float, float] | None:
        rs = self.rows.get((home, bucket))
        return rs[-1] if rs else None

    def weeks(self, home: str, bucket: str) -> list:
        """Every quota week of one weekly bucket, oldest first, as qtop Weeks.

        A bucket nobody used has a reset that floats at now + 7 d; those readings join
        the week that follows them (its reset is fixed by the first use)."""
        key = (home, bucket)
        if key in self._weeks:
            return self._weeks[key]
        groups: list[list] = []  # [reset, floating, points]
        for t, used, reset in self.rows.get(key, []):
            fl = _floating(t, used, reset, Q.WEEK)
            g = groups[-1] if groups else None
            if g and (abs(reset - g[0]) <= 7200 or (g[1] and t < g[0])):
                g[0] = reset if g[1] or not fl else g[0]
                g[1] = g[1] and fl
                g[2].append((t, used))
            else:
                groups.append([reset, fl, [(t, used)]])
        peaks: dict[float, float] = {}
        for t, used, reset in self.rows.get((home, AGY_FIVE.get(bucket, "")), []):
            if not _floating(t, used, reset, 5 * 3600):
                r = Q._round(reset, 600)
                peaks[r] = max(peaks.get(r, 0.0), used)
        out = []
        for reset, _, pts in groups:
            wins = {r: p for r, p in peaks.items() if reset - Q.WEEK < r <= reset + 5 * 3600}
            out.append(Q.Week(f"agy:{home}", reset, pts, wins))
        self._weeks[key] = out
        return out


def agy_label(bucket: str) -> str:
    return Q.AGY_LABEL.get(bucket, bucket.split("-")[0][:6])


class AgyRow(Row):
    """An agy account's card. Its week is the weekly bucket with the most used (the
    one that stops agy first: no Gemini left means no Opus either); the other weekly
    buckets ride along in `extra`, drawn as thin lines on the same chart."""

    def __init__(self, m, account: str, now: float, back: int = 0):
        home = account[len(Q.AGY_KEY):]
        hist: AgyHistory = m.agy
        who = Q.AGY_NAME.get(home, home)
        self.account = account
        self.label = "g" + Q.LETTER.get(who, who[:2].upper())
        self.name = f"agy · {who}" + (f" · {home}" if home != who else "")
        self.active = False
        self.pool = "agy"
        self.ceiling = 100.0  # burn sets no 5h ceiling for agy
        acc = Q.agy_account(home) or {}
        observed = Q.iso_ts(acc.get("observed_at"))
        self.stale = observed is None or now - observed > Q.STALE_S

        live = []
        for b in hist.buckets(home):
            ws = hist.weeks(home, b)
            if ws:
                live.append((b, ws))
        # The binding bucket: the most used now (the first on a tie: Gemini).
        live.sort(key=lambda bw: -bw[1][-1].used if not bw[1][-1].over(now) else 1.0)
        self.bucket = live[0][0] if live else None
        self.week, self.back, self.weeks = None, 0, 0
        self.extra = []
        if live:
            ws = live[0][1]
            self.back = max(0, min(back, len(ws) - 1))
            self.week, self.weeks = ws[-1 - self.back], len(ws)
            for b, other in live[1:]:
                near = min(other, key=lambda w: abs(w.reset - self.week.reset))
                self.extra.append((agy_label(b), near))

        five = hist.last(home, AGY_FIVE.get(self.bucket or "", ""))
        self.five_live = bool(five and five[2] > now and not self.stale
                              and not _floating(five[0], five[1], five[2], 5 * 3600))
        self.u5 = five[1] if self.five_live else 0.0
        self.r5 = (five[2] - now) if self.five_live else None

        if self.week is None:
            self.verdict, self.tone = "no readings", "dim"
        else:
            v, self.tone = Q.week_verdict(self.week, now)
            self.verdict = f"{agy_label(self.bucket)} {v}"
        if self.stale and back == 0:
            err = str(acc.get("error") or "")[:24]
            age = Q.ago(now - observed) if observed else "ever"
            self.verdict, self.tone = (f"{err} · {age}" if err else f"no reading for {age}"), "dim"
        self.over = self.week is None or (back == 0 and self.week.over(now))


def rows(m, now: float, back: int = 0) -> list[Row]:
    active = read_active()
    return [AgyRow(m, a, now, back) if a.startswith(Q.AGY_KEY) else Row(m, a, active, now, back)
            for a in m.accounts()]


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

    # agy: the other weekly buckets, thin lines on this week's clock.
    if detail:
        for _, other in row.extra:
            opts = [(X(t), Y(v)) for t, v in other.points if wk.start <= t <= wk.reset]
            if len(opts) < 2:
                continue
            cr.move_to(*opts[0])
            for p in opts[1:]:
                cr.line_to(*p)
            cr.set_source_rgba(*rgba("accent", 0.8))
            cr.set_line_width(1.0)
            cr.stroke()

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
    ceiling = row.ceiling

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
    "full": {"chart": 31, "pct": True},
    "compact": {"chart": 28, "pct": False},
}


GAUGE_W, GAUGE_GAP = 4.0, 3.0  # a folded account: one thin gauge


def fold(rs: list[Row]) -> tuple[list[Row], list[Row]]:
    """(the account with a full cell: the active one, else the first; the rest)."""
    head = [r for r in rs if r.active][:1] or rs[:1]
    return head, [r for r in rs if r not in head]


def strip_layout(cr, rs: list[Row], variant: str) -> tuple[list[tuple[Row, float, float]], float]:
    """(row, x, width) per full cell — the active account only — and the strip's width
    with the folded accounts' gauges after it."""
    spec = STRIP[variant]
    gap, edge = 8.0, SH + 7.0
    head, rest = fold(rs)
    out, x = [], edge
    for r in head:
        w = text_width(cr, r.label, 13, bold=True) + 3 + spec["chart"] + 2 + 3
        if spec["pct"]:
            w += 3 + text_width(cr, "100", 13)
        out.append((r, x, w))
        x += w + gap
    if rest:
        x += len(rest) * (GAUGE_W + GAUGE_GAP) - GAUGE_GAP + gap
    return out, x - gap + edge


def draw_strip(rs: list[Row], now: float, variant: str, scale: int):
    probe = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
    cells, width = strip_layout(probe, rs, variant)
    surf, cr = core.surface(width, BAR_H, scale)
    core.pill(cr, width)
    chart = STRIP[variant]["chart"]
    top, ch = PILL_Y + 4.0, PILL_H - 8.0
    for r, x, w in cells:
        dim = r.over or r.stale
        lw = text(cr, x, MID, r.label, 13, "title" if r.active else ("dim" if dim else "fg"),
                  bold=r.active, valign=0.5)
        cx = x + lw + 3
        week_chart(cr, cx, top, chart, ch, r, now, detail=False)
        if dim:
            text(cr, cx + chart / 2, MID, "?", 13, "dim", align=0.5, valign=0.5)
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
            text(cr, tx + 6, MID, pct, 13, "dim" if dim else r.colour, bold=r.active, valign=0.5)
        if r.active:
            rrect(cr, x - 2, PILL_Y + PILL_H - 4, w + 4, 2, 1)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
    # The folded accounts: a gauge each, weekly % as the fill, in the verdict's colour.
    _, rest = fold(rs)
    gx = (cells[-1][1] + cells[-1][2] + 8.0) if cells else SH + 7.0
    for r in rest:
        rrect(cr, gx, top, GAUGE_W, ch, 1.5)
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill()
        dim = r.over or r.stale or r.week is None
        frac = 0.12 if dim else max(0.06, min(100.0, r.week.used) / 100)
        rrect(cr, gx, top + ch * (1 - frac), GAUGE_W, ch * frac, 1.5)
        cr.set_source_rgba(*rgba("bg3" if dim else r.colour))
        cr.fill()
        gx += GAUGE_W + GAUGE_GAP
    return surf


# ── the deck (the drop-down) ─────────────────────────────────────────────────

PAD = 14
INFO_W = 230
COL_GAP = 56  # between the two columns; the divider runs down its middle
DECK_W = 1320
COL_W = (DECK_W - 2 * PAD - COL_GAP) // 2
HEAD_H = 46
COLHEAD_H = 26  # the column titles, under the header and not scrolled
TOP_H = HEAD_H + COLHEAD_H  # where the cards' band starts
CARD_H = 112
SEC_H = 28  # a section's header: "main (private)"
EMPTY_H = 24  # an empty section's one dim line
FOOT_H = 26
SCROLL_STEP = 48  # px per wheel notch (PgUp/PgDn move a whole band)

# The columns: qtop's Claude accounts, then agy's (the AGY_KEY ones).
COLUMNS = (("cc", "cc · Claude Code", False), ("agy", "agy · Antigravity", True))
# The personal Max accounts: the "main (private)" section. agy's home main is one too.
PRIVATE = ("private", "main2")
SECTIONS = ("main (private)", "work (others)")


def is_private(account: str) -> bool:
    if account.startswith(Q.AGY_KEY):
        home = account[len(Q.AGY_KEY):]
        return Q.AGY_NAME.get(home, home) == "private"
    return account in PRIVATE


def sections(accounts: list[str]) -> list[tuple[str, list[tuple[str, list[str]]]]]:
    """Each column as (title, [(section title, its accounts)]), in the order drawn."""
    out = []
    for _, title, is_agy in COLUMNS:
        mine = [a for a in accounts if a.startswith(Q.AGY_KEY) == is_agy]
        out.append((title, [(SECTIONS[0], [a for a in mine if is_private(a)]),
                            (SECTIONS[1], [a for a in mine if not is_private(a)])]))
    return out


def order(accounts: list[str]) -> list[str]:
    """The accounts in the order i/o step through them: column by column, section by section."""
    return [a for _, secs in sections(accounts) for _, accts in secs for a in accts]


def layout(accounts: list[str]) -> tuple[dict[str, tuple[float, float]], list[tuple[float, float, str, bool]], float]:
    """(each card's (x, y) in the band, each section's (x, y, title, empty), the band's height)."""
    pos: dict[str, tuple[float, float]] = {}
    heads: list[tuple[float, float, str, bool]] = []
    tallest = 0.0
    for ci, (_, secs) in enumerate(sections(accounts)):
        x = PAD + ci * (COL_W + COL_GAP)
        y = 0.0
        for title, accts in secs:
            heads.append((x, y, title, not accts))
            y += SEC_H + (0.0 if accts else EMPTY_H)
            for a in accts:
                pos[a] = (x, y)
                y += CARD_H
        tallest = max(tallest, y)
    return pos, heads, tallest


def draw_deck(cr, m, now: float, back: int, sel: str | None, top: float, h: float) -> list[tuple[str, float, float, float]]:
    """Draw the deck at (0, 0), h tall. The header, the column titles and the footer stay;
    the cards scroll `top` px under the column titles. Returns (account, x, y0, y1) per
    visible card, for clicks."""
    rs = {r.account: r for r in rows(m, now, back)}
    accts = list(rs)
    w = DECK_W
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

    # The two columns: a title each (fixed), a divider between them.
    bottom = h - FOOT_H
    for ci, (title, _) in enumerate(sections(accts)):
        text(cr, PAD + ci * (COL_W + COL_GAP) + 4, HEAD_H + 6, title, 14, "title", bold=True)
    cr.move_to(w / 2 + 0.5, HEAD_H)
    cr.line_to(w / 2 + 0.5, bottom)
    cr.set_source_rgba(*rgba("sep", 0.7))
    cr.set_line_width(1)
    cr.stroke()

    # The cards and section headers scroll between the column titles and the footer:
    # clip them to that band.
    pos, heads, tallest = layout(accts)
    hits = []
    cr.save()
    cr.rectangle(0, TOP_H, w, bottom - TOP_H)
    cr.clip()
    for x, y, title, empty in heads:
        y0 = TOP_H + y - top
        if y0 + SEC_H <= TOP_H or y0 >= bottom:
            continue
        text(cr, x + 4, y0 + 7, title, 13, "fg", bold=True)
        cr.move_to(x, y0 + SEC_H - 0.5)
        cr.line_to(x + COL_W, y0 + SEC_H - 0.5)
        cr.set_source_rgba(*rgba("sep"))
        cr.set_line_width(1)
        cr.stroke()
        if empty:
            text(cr, x + 4, y0 + SEC_H + 4, "none", 12, "dim")
    for account in accts:
        x, y = pos[account]
        r = rs[account]
        y0 = TOP_H + y - top
        if y0 + CARD_H <= TOP_H or y0 >= bottom:
            continue  # off the band: drawn nowhere, clickable nowhere
        hits.append((account, x, max(y0, TOP_H), min(y0 + CARD_H, bottom)))
        cr.move_to(x, y0 + 0.5)
        cr.line_to(x + COL_W, y0 + 0.5)
        cr.set_source_rgba(*rgba("sep", 0.7))
        cr.set_line_width(1)
        cr.stroke()
        if account == sel:
            cr.rectangle(x + 1, y0 + 1, COL_W - 2, CARD_H - 1)
            cr.set_source_rgba(*rgba("alt", 0.45))
            cr.fill()
        if r.active:
            cr.rectangle(x + 1, y0 + 8, 3, CARD_H - 16)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
        draw_card(cr, r, now, x + PAD, y0 + 8, COL_W - 2 * PAD, CARD_H - 16)
    cr.restore()

    # A thin thumb at the right edge while the cards overflow the band.
    span, content = bottom - TOP_H, tallest
    if content > span:
        track = span - 8
        thumb = max(24.0, track * span / content)
        ty = TOP_H + 4 + (track - thumb) * top / (content - span)
        rrect(cr, w - 6, ty, 3, thumb, 1.5)
        cr.set_source_rgba(*rgba("accent", 0.6))
        cr.fill()

    hint = "click a card or Enter: qtop on it · i/o select · u/p earlier/later week · wheel or PgUp/PgDn scroll · esc closes"
    text(cr, w / 2, h - FOOT_H + 5, hint, 12, "dim", align=0.5)
    return hits


def draw_card(cr, r: Row, now: float, x: float, y: float, w: float, h: float) -> None:
    # Info column.
    lw = text(cr, x + 4, y - 2, r.label, 22, "title" if r.active else "fg", bold=True)
    text(cr, x + 12 + lw, y + 1, r.name, 14, "title")
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
    ceiling = r.ceiling
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
    for name, other in r.extra:
        if other.points and wk.start <= other.points[-1][0] <= wk.reset:
            label(other.used, f"{name} {other.used:.0f}%", "accent")
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
    m.agy = AgyHistory()
    m.agy.load()
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
        key = (mt(Q.CSV), mt(Q.SNAPSHOT), mt(AGY_HISTORY), mt(Q.AGY_SNAPSHOT), mt(ACCOUNT_FILE),
               int(time.time() // 60))
        if key == self.seen:
            return False
        self.seen = key
        if self.m.store.load():
            self.trim(time.time())
        if self.m.agy.load():
            self.m.agy.trim(time.time() - self.KEEP_S)
        return True

    KEEP_S = 36 * 86400  # five quota weeks: the panel's u/p history, and no more

    def trim(self, now: float) -> None:
        """Drop readings older than KEEP_S. qtop's Store keeps every row of a log that
        grows ~2,300 rows a day; the daemon lives for weeks."""
        cutoff = now - self.KEEP_S
        for rows in self.m.store.rows.values():
            if rows and rows[0].t < cutoff:
                rows[:] = [r for r in rows if r.t >= cutoff]

    def strips(self, variant: str, scale: int):
        now = time.time()
        return draw_strip(rows(self.m, now), now, variant, scale)


class QuotaPanel(Panel):
    """Taller than the output (one card per account, agy ones included), it is clamped
    to the room the output leaves and its cards scroll under the header."""

    name = "quota"
    # Not drawn ahead: its height and scroll change with the output and the wheel, so a
    # picture kept per (scroll, height) would only pile up. Five cards draw in a blink.
    drawn_ahead = False

    def __init__(self, quota: Quota):
        self.q = quota
        self.back, self.sel = 0, None  # sel: the selected account's name
        self.top = 0.0  # the cards' scroll, px, under the column titles

    def content_h(self) -> int:
        return int(TOP_H + layout(self.q.m.accounts())[2] + FOOT_H)

    def room(self) -> float:
        """The panel's height the output leaves it, in panel px (before the zoom).
        Before the overlay has an allocation (its first draw), the whole deck."""
        win = getattr(self.deck, "win", None)
        full = win.get_allocated_height() if win is not None else 0
        if full <= 0:
            return self.content_h()
        margin = max(6, round(full * self.deck.FREE_TOP)) if self.deck.free else 6
        return (full - margin - 12) / self.deck.zoom

    def size(self):
        h = min(self.content_h(), max(self.room(), TOP_H + CARD_H + FOOT_H))
        return DECK_W, int(h)

    def card_span(self) -> float:
        """The height the cards show at once."""
        return self.size()[1] - TOP_H - FOOT_H

    def max_top(self) -> float:
        return max(0.0, layout(self.q.m.accounts())[2] - self.card_span())

    def follow(self) -> None:
        """Scroll so the selected card is in the band."""
        pos = layout(self.q.m.accounts())[0]
        if self.sel not in pos:
            return
        y = pos[self.sel][1]
        if y < self.top:
            self.top = y
        elif y + CARD_H > self.top + self.card_span():
            self.top = y + CARD_H - self.card_span()
        self.top = min(max(self.top, 0.0), self.max_top())

    def opened(self) -> None:
        accts = self.q.m.accounts()
        active = read_active()
        self.back, self.sel = 0, (active if active in accts else None)
        self.top = 0.0
        self.follow()

    def scroll(self, down: bool) -> bool:
        before = self.top
        self.top = min(max(self.top + (SCROLL_STEP if down else -SCROLL_STEP), 0.0), self.max_top())
        return self.top != before

    def state(self) -> tuple:
        return (self.back, self.sel, round(self.top), self.size()[1])

    def draw(self, cr, hits: core.Hits) -> None:
        self.top = min(max(self.top, 0.0), self.max_top())
        cards = draw_deck(cr, self.q.m, time.time(), self.back, self.sel, self.top, self.size()[1])
        for account, x, y0, y1 in cards:
            hits.add(x, y0, COL_W, y1 - y0, lambda a=account: open_qtop(a))

    def key(self, key: str, ctrl: bool) -> bool:
        steps = order(self.q.m.accounts())
        n = len(steps)
        if n == 0:
            return False
        cur = steps.index(self.sel) if self.sel in steps else -1
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = steps[(cur + 1) % n]
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = steps[cur - 1 if cur > 0 else n - 1]
        elif key in ("u", "Left") or (ctrl and key == "b"):
            self.back += 1
        elif key in ("p", "Right") or (ctrl and key == "f"):
            self.back = max(0, self.back - 1)
        elif key in ("Page_Down", "Next", "Page_Up", "Prior"):  # a band; the selection stays
            step = self.card_span() if key in ("Page_Down", "Next") else -self.card_span()
            self.top = min(max(self.top + step, 0.0), self.max_top())
            return True
        elif key in ("Return", "KP_Enter") and self.sel in steps:
            # "close": the panel lets go of the keyboard. With True it kept it, and a
            # repeating Enter opened a qtop per repeat (13 Oct 2026: 120 terminals in 3 s).
            return "close" if open_qtop(self.sel) else True
        else:
            return False
        self.follow()
        return True


QTOP_GAP_S = 2.0  # one qtop per click or Enter: a burst of them opens one window
_qtop_at = 0.0


def open_qtop(account: str) -> bool:
    global _qtop_at
    now = time.monotonic()
    if now - _qtop_at >= QTOP_GAP_S:
        _qtop_at = now
        core.spawn(["alacritty", "-e", "qtop", account])
    return True  # close the panel
