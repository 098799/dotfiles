"""Workspaces: niri's workspaces of each output, with what is open in them.

Each workspace with windows (and the visible one) is a chip: its name, then one mark
per column in column order: the app's icon, or for a terminal the first letters of
its title (seven Alacritty icons say nothing; "cm cl nv" does). The focused column is
underlined. Click a chip: that workspace. Click a mark: that window. Scroll: the
next / previous workspace. Right click: the overview (WsPanel), every workspace of
every output with its windows.

niri's IPC socket directly ($NIRI_SOCKET): a request is a JSON line, the reply one
JSON line; the event stream only says *that* something changed, and a redraw asks
for the whole state (a few hundred µs).
"""

from __future__ import annotations

import json
import math
import os
import socket
import threading

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import core  # noqa: E402
from .core import MID, PILL_H, PILL_Y, SH, Hits, button, rgba, text  # noqa: E402
from .deck import Panel  # noqa: E402

TERMINALS = {"alacritty", "kitty", "foot", "org.wezfurlong.wezterm", "com.mitchellh.ghostty"}
MAX_MARKS = {"full": 7, "compact": 4}
# The full strip's width budget (px as drawn, before core.ZOOM). It grows with every
# workspace; past this the workspaces you are not on show fewer marks (2, then none)
# so the bar does not run off the screen. The visible ones always keep theirs.
BUDGET = {"full": 470, "compact": 10_000}
ICON = 16


def niri(request) -> dict | list | None:
    path = os.environ.get("NIRI_SOCKET")
    if not path:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)  # on the main loop: a stalled niri must not freeze the bar
            s.connect(path)
            s.sendall((json.dumps(request) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        reply = json.loads(buf)
    except (OSError, ValueError):
        return None
    ok = reply.get("Ok") if isinstance(reply, dict) else None
    if isinstance(ok, dict) and len(ok) == 1:
        return next(iter(ok.values()))
    return ok


def action(name: str, **args) -> None:
    niri({"Action": {name: args}})


_ICONS: dict[tuple, cairo.ImageSurface | None] = {}


def app_icon(app_id: str, scale: float):
    scale = max(1, math.ceil(scale - 1e-6))  # icon themes come in whole scales
    key = (app_id, scale)
    if key in _ICONS:
        return _ICONS[key]
    gicon = None
    for cand in dict.fromkeys((app_id, app_id.lower(), app_id.split(".")[-1].lower())):
        try:
            info = Gio.DesktopAppInfo.new(f"{cand}.desktop")
        except TypeError:
            info = None
        if info and info.get_icon():
            gicon = info.get_icon()
            break
    if gicon is None:
        gicon = Gio.ThemedIcon.new_with_default_fallbacks(app_id.lower() or "application-x-executable")
    surf = None
    theme = Gtk.IconTheme.get_default()
    info = theme.lookup_by_gicon_for_scale(gicon, ICON, scale, Gtk.IconLookupFlags.FORCE_SIZE)
    if info is not None:
        try:
            pix = info.load_icon()
            surf = Gdk.cairo_surface_create_from_pixbuf(pix, scale, None)
        except GLib.Error:
            surf = None
    _ICONS[key] = surf
    return surf


def term_letters(title: str) -> str:
    word = (title or "").strip().split(" ")[0].split("/")[-1].lstrip("~:@") or "?"
    return word[:2].lower()


class WsStrip:
    """Draws one picture per output; keeps the click map of each."""

    name = "ws"

    def __init__(self, on_change):
        self.on_change = on_change
        self.outputs: dict[str, dict] = {}
        self.workspaces: list[dict] = []
        self.windows: list[dict] = []
        self.hits: dict[tuple, list[tuple[float, float, object]]] = {}  # (mx, my, variant) -> map
        self.widths: dict[tuple, float] = {}
        self._pending = False
        if os.environ.get("NIRI_SOCKET"):
            threading.Thread(target=self._events, daemon=True).start()

    # -- state -----------------------------------------------------------------

    def _events(self) -> None:
        import time

        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(os.environ["NIRI_SOCKET"])
                    s.sendall(b'"EventStream"\n')
                    f = s.makefile("rb")
                    # Terminal titles change all the time (agents animate them): at most
                    # five redraws a second.
                    for _line in f:
                        if not self._pending:
                            self._pending = True
                            GLib.timeout_add(200, self._refresh)
            except OSError as err:
                core.log(f"niri event stream: {err!r}")
            time.sleep(2)

    def _refresh(self) -> bool:
        self._pending = False
        self.load()
        self.on_change()
        return False

    def load(self) -> None:
        outs = niri("Outputs")
        if isinstance(outs, dict):
            self.outputs = {n: o for n, o in outs.items() if o.get("logical")}
        self.workspaces = niri("Workspaces") or []
        self.windows = niri("Windows") or []

    # -- drawing ---------------------------------------------------------------

    def files(self) -> list[tuple[str, dict, str]]:
        """(output name, its logical rect, variant) for every picture to draw: the laptop
        screen's bar takes the compact strips (config.jsonc), every other the full ones."""
        return [(name, o["logical"], "compact" if name.startswith("eDP") else "full")
                for name, o in self.outputs.items()]

    def draw(self, output: str, variant: str, scale: float):
        hidden_steps = (MAX_MARKS[variant], 2, 0) if variant == "full" else (0,)
        for hidden in hidden_steps:
            surf, hits = self._draw(output, variant, scale, hidden)
            if surf.get_width() / scale <= BUDGET[variant]:
                break
        return surf, hits

    def _draw(self, output: str, variant: str, scale: float, hidden: int):
        c = core.StripCanvas(scale)
        cr = c.cr
        wins_by_ws: dict[int, list[dict]] = {}
        for w in self.windows:
            wins_by_ws.setdefault(w.get("workspace_id"), []).append(w)
        hits: list[tuple[float, float, object]] = []
        c.x = SH + 2
        for ws in sorted((w for w in self.workspaces if w.get("output") == output), key=lambda w: w["idx"]):
            wins = wins_by_ws.get(ws["id"], [])
            if not wins and not ws.get("is_active"):
                continue
            cols: dict[int, list[dict]] = {}
            floating = []
            for w in wins:
                pos = (w.get("layout") or {}).get("pos_in_scrolling_layout")
                if pos:
                    cols.setdefault(pos[0], []).append(w)
                else:
                    floating.append(w)
            columns = [sorted(cols[k], key=lambda w: w["layout"]["pos_in_scrolling_layout"][1])
                       for k in sorted(cols)]
            label = ws.get("name") or str(ws["idx"])
            x0 = c.x
            focused, active, urgent = ws.get("is_focused"), ws.get("is_active"), ws.get("is_urgent")
            # Measure first: the chip's background goes under its content.
            lw = core.text_w(cr, label, 13, bold=bool(focused))
            # Compact (the laptop), or past BUDGET: fewer marks where you are not.
            n_marks = MAX_MARKS[variant] if (active or focused) else hidden
            marks = columns[:n_marks]
            mw = sum(self._mark_w(cr, col[0]) + 3 for col in marks)
            more = len(columns) - len(marks) if marks else 0
            more_w = core.text_w(cr, f"+{more}", 11) + 3 if more > 0 else 0
            cw = 8 + lw + (6 + mw + more_w if marks else 0) + 6
            bg = "urgent" if urgent else ("accent" if focused else ("bg2" if active else None))
            if bg:
                core.rrect(cr, x0, PILL_Y + 2.5, cw, PILL_H - 5, 5)
                cr.set_source_rgba(*rgba(bg, 1.0 if focused or urgent else 0.8))
                cr.fill()
            fg = "bg" if focused or urgent else ("title" if active else "fg")
            text(cr, x0 + 8, MID, label, 13, fg, bold=bool(focused), valign=0.5)
            x = x0 + 8 + lw + 6
            hits.append((x0, x0 + 8 + lw + 3, ("ws", ws["id"])))
            active_win = ws.get("active_window_id")
            for col in marks:
                w0 = col[0]
                mw1 = self._mark_w(cr, w0)
                self._mark(cr, x, w0, fg, scale, on_accent=bool(focused))
                if any(w["id"] == active_win for w in col) and len(columns) > 1:
                    core.rrect(cr, x, PILL_Y + PILL_H - 5, mw1, 2, 1)
                    cr.set_source_rgba(*rgba("bg" if focused else "title", 0.9))
                    cr.fill()
                target = next((w for w in col if w["id"] == active_win), w0)
                hits.append((x - 1, x + mw1 + 2, ("win", target["id"])))
                x += mw1 + 3
            if more > 0:
                text(cr, x, MID, f"+{more}", 11, fg, valign=0.5)
                x += more_w
            c.x = x0 + cw + 4
        c.x -= 4
        c.x = max(c.x, 20)
        c.PAD = SH + 2
        surf = c.finish()
        return surf, hits

    def _mark_w(self, cr, w: dict) -> float:
        if (w.get("app_id") or "").lower() in TERMINALS:
            return max(14, core.text_w(cr, term_letters(w.get("title", "")), 11) + 6)
        return ICON

    def _mark(self, cr, x: float, w: dict, fg: str, scale: int, on_accent: bool) -> None:
        app = w.get("app_id") or ""
        if app.lower() in TERMINALS:
            letters = term_letters(w.get("title", ""))
            mw = self._mark_w(cr, w)
            core.rrect(cr, x, MID - 8, mw, 16, 4)
            cr.set_source_rgba(*rgba("bg" if on_accent else "bg1", 0.35 if on_accent else 1))
            cr.fill()
            text(cr, x + mw / 2, MID, letters, 11, fg, align=0.5, valign=0.5)
            return
        surf = app_icon(app, scale)
        if surf is None:
            text(cr, x + ICON / 2, MID, (app[:1] or "?").upper(), 12, fg, align=0.5, valign=0.5)
            return
        cr.save()
        cr.translate(x, MID - ICON / 2)
        cr.set_source_surface(surf, 0, 0)
        cr.paint()
        cr.restore()

    # -- input -----------------------------------------------------------------

    def click(self, key: tuple, local_x: float) -> None:
        for x0, x1, (kind, ident) in self.hits.get(key, []):
            if x0 <= local_x < x1:
                if kind == "ws":
                    action("FocusWorkspace", reference={"Id": ident})
                else:
                    action("FocusWindow", id=ident)
                return

    def scroll(self, up: bool) -> None:
        action("FocusWorkspaceUp" if up else "FocusWorkspaceDown")



# ── the overview ─────────────────────────────────────────────────────────────

GLYPH_FLOAT, GLYPH_FULL, GLYPH_URGENT = "\U000f05af", "", ""
GLYPH_UP, GLYPH_DOWN, GLYPH_CLOSE = "", "", ""


def win_order(wins: list[dict]) -> list[dict]:
    """A workspace's windows as niri lays them out: column by column, top to bottom,
    the floating ones last."""
    def place(w):
        pos = (w.get("layout") or {}).get("pos_in_scrolling_layout")
        return (0, pos[0], pos[1]) if pos else (1, 0, w["id"])
    return sorted(wins, key=place)


class WsPanel(Panel):
    """Every workspace of every output, each a card with its windows as rows (opened by
    a right click on the workspaces strip). Click a window: focus it; hover it: move it
    to the workspace above / below, or close it (click twice). Click a card's name or an
    empty workspace: go there. Pinned: i/o a window, k/l half a list, j/; the previous /
    next workspace, Enter focus, x close (twice).

    It reads the strip's own niri state (WsStrip keeps it from niri's event stream), so
    it costs no reads; without a strip (`bardeck panel`) it asks niri itself."""

    name = "ws"
    COL_W = 380
    GAP = 14
    ROW_H = 26
    HEAD_H = 26
    COL_H = 560  # an output's cards go to a second (third) column past this

    def __init__(self):
        self.src = None  # the WsStrip, set by the daemon
        self.outputs: dict[str, dict] = {}
        self.workspaces: list[dict] = []
        self.windows: list[dict] = []
        self.sel = 0        # the keyboard's window id
        self.hovered = 0    # the window id under the pointer
        self.closing = 0    # a window id whose close asks to be clicked again
        self.rects: list[tuple[float, float, float, float, int]] = []  # x0, x1, y0, y1, window id
        self.order: list[tuple[int, int]] = []  # (window id, workspace id), as drawn
        self.loaded = 0.0

    def load(self) -> None:
        if self.src is not None:
            self.outputs, self.workspaces, self.windows = self.src.outputs, self.src.workspaces, self.src.windows
            return
        import time

        if time.monotonic() - self.loaded < 0.5:
            return
        self.loaded = time.monotonic()
        outs = niri("Outputs")
        if isinstance(outs, dict):
            self.outputs = {n: o for n, o in outs.items() if o.get("logical")}
        self.workspaces = niri("Workspaces") or []
        self.windows = niri("Windows") or []

    def opened(self) -> None:
        self.loaded = 0.0
        self.load()
        focused = next((w for w in self.windows if w.get("is_focused")), None)
        self.sel = focused["id"] if focused else 0
        self.hovered = self.closing = 0

    def closed(self) -> None:
        self.hovered = self.closing = 0

    # -- layout ----------------------------------------------------------------

    def plan(self):
        """Per output (left to right): (name, its rect, empty workspaces, columns), each
        column a list of (workspace, its windows, card height)."""
        by_ws: dict[int, list[dict]] = {}
        for w in self.windows:
            by_ws.setdefault(w.get("workspace_id"), []).append(w)
        out = []
        for name, o in sorted(self.outputs.items(), key=lambda kv: (kv[1]["logical"]["x"], kv[1]["logical"]["y"])):
            cards, empty = [], []
            for ws in sorted((w for w in self.workspaces if w.get("output") == name), key=lambda w: w["idx"]):
                wins = win_order(by_ws.get(ws["id"], []))
                if wins or ws.get("is_active"):
                    cards.append((ws, wins, self.HEAD_H + max(1, len(wins)) * self.ROW_H + 8))
                elif ws.get("name"):  # niri's spare unnamed workspace at the end: left out
                    empty.append(ws)
            total = sum(h + 8 for *_, h in cards)
            n = max(1, min(3, math.ceil(total / self.COL_H)))
            cols, acc, cur = [], 0.0, []
            for card in cards:
                if cur and acc >= total / n * (len(cols) + 1) and len(cols) < n - 1:
                    cols.append(cur)
                    cur = []
                cur.append(card)
                acc += card[2] + 8
            cols.append(cur)
            out.append((name, o["logical"], empty, cols))
        return out

    def size(self):
        self.load()  # the strip's state: new after every niri event
        plan = self.plan()
        if not plan:
            return 360, 90
        w = 2 * 16 + sum(len(cols) * self.COL_W + (len(cols) - 1) * 12 for *_, cols in plan)
        w += self.GAP * (len(plan) - 1)
        h = max(self.top_h(empty) + max(sum(c[2] + 8 for c in col) for col in cols) for _, _, empty, cols in plan)
        return int(w), int(h + 8)

    def top_h(self, empty: list) -> float:
        return 14 + 22 + (30 if empty else 0)

    # -- actions ---------------------------------------------------------------

    def focus(self, wid: int) -> bool:
        action("FocusWindow", id=wid)
        return True

    def go(self, ws: dict) -> bool:
        action("FocusWorkspace", reference={"Id": ws["id"]})
        return True

    def move(self, wid: int, ws: dict) -> bool:
        self.closing = 0
        action("MoveWindowToWorkspace", window_id=wid, reference={"Id": ws["id"]}, focus=False)
        return False

    def close(self, wid: int) -> bool:
        if self.closing != wid:
            self.closing = wid  # the chip turns red: a second click closes
            return False
        self.closing = 0
        action("CloseWindow", id=wid)
        return False

    def neighbours(self, ws_id: int) -> tuple[dict | None, dict | None]:
        """The workspaces above and below ws_id on its output."""
        ws = next((w for w in self.workspaces if w["id"] == ws_id), None)
        if ws is None:
            return None, None
        same = sorted((w for w in self.workspaces if w.get("output") == ws.get("output")), key=lambda w: w["idx"])
        i = same.index(ws)
        return (same[i - 1] if i > 0 else None), (same[i + 1] if i + 1 < len(same) else None)

    # -- input -----------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool | str:
        ids = [wid for wid, _ in self.order]
        if not ids:
            return False
        i = ids.index(self.sel) if self.sel in ids else -1
        half = max(1, len(ids) // 4)
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = ids[min(len(ids) - 1, i + 1)]
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = ids[max(0, i - 1)]
        elif key in ("k", "Page_Down"):
            self.sel = ids[min(len(ids) - 1, i + half)]
        elif key in ("l", "Page_Up"):
            self.sel = ids[max(0, i - half)]
        elif key in ("j", "semicolon", "Left", "Right"):
            spaces = list(dict.fromkeys(ws for _, ws in self.order))
            cur = dict(self.order).get(self.sel, spaces[0])
            j = spaces.index(cur) + (-1 if key in ("j", "Left") else 1)
            target = spaces[max(0, min(len(spaces) - 1, j))]
            self.sel = next(wid for wid, ws in self.order if ws == target)
        elif key in ("Return", "KP_Enter") and self.sel in ids:
            self.focus(self.sel)
            return "close"
        elif key in ("x", "Delete") and self.sel in ids:
            self.close(self.sel)
        else:
            return False
        if self.closing and self.closing != self.sel:
            self.closing = 0
        return True

    def hover(self, x: float, y: float) -> bool:
        at = next((wid for x0, x1, y0, y1, wid in self.rects if x0 <= x < x1 and y0 <= y < y1), 0)
        if at != self.hovered:
            self.hovered = at
            return True
        return False

    # -- drawing ---------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        W, H = self.size()
        core.panel_frame(cr, W, H)
        P = 16
        self.rects, self.order = [], []
        plan = self.plan()
        if not plan:
            text(cr, P, 16, "niri says nothing", 14, "dim", bold=True)
            return
        sx, sy = cr.get_target().get_device_scale()
        scale = sx * cr.get_matrix().xx
        x = P
        for name, rect, empty, cols in plan:
            ow = len(cols) * self.COL_W + (len(cols) - 1) * 12
            o = self.outputs.get(name, {})
            nwin = sum(len(wins) for col in cols for _, wins, _ in col)
            label = f"{name} · {rect['width']}×{rect['height']}"
            right = f"{nwin} window{'s' if nwin != 1 else ''}"
            rw = text(cr, x + ow, 11, right, 11, "dim", align=1) + 10
            model = " ".join(v for v in (o.get("make"), o.get("model")) if v)
            text(cr, x, 10, label, 13, "title", bold=True)
            if model:
                lw = core.text_w(cr, label, 13, bold=True) + 8
                text(cr, x + lw, 12, model, 11, "dim", width=max(10.0, ow - lw - rw))
            y = 14 + 22
            if empty:
                ex = x
                ex += text(cr, ex, y + 4, "empty", 11, "dim") + 8
                for ws in empty:
                    label_e = ws.get("name") or str(ws["idx"])
                    cw = core.text_w(cr, label_e, 11) + 14
                    if ex + cw > x + ow:
                        break
                    button(cr, hits, ex, y, label_e, lambda ws=ws: self.go(ws), w=cw, h=20, size=11)
                    ex += cw + 5
                y += 30
            for c, col in enumerate(cols):
                cx, cy = x + c * (self.COL_W + 12), y
                for ws, wins, ch in col:
                    self.draw_card(cr, hits, cx, cy, ws, wins, ch, rect, scale)
                    cy += ch + 8
            x += ow + self.GAP

    def draw_card(self, cr, hits: Hits, x: float, y: float, ws: dict, wins: list[dict], h: float, rect: dict,
                  scale: float) -> None:
        W = self.COL_W
        focused, active, urgent = ws.get("is_focused"), ws.get("is_active"), ws.get("is_urgent")
        core.rrect(cr, x + 0.5, y + 0.5, W - 1, h - 1, 8)
        cr.set_source_rgba(*rgba("bg1", 0.55))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("urgent" if urgent else ("accent" if focused else "bg2"), 0.9 if focused else 1))
        cr.set_line_width(1.2 if focused or urgent else 1)
        cr.stroke()
        label = ws.get("name") or str(ws["idx"])
        hx, mid = x + 10, y + self.HEAD_H / 2 + 1
        lw = core.text_w(cr, label, 13, bold=True) + 12
        tone_bg = "urgent" if urgent else ("accent" if focused else ("bg2" if active else None))
        if tone_bg:
            core.rrect(cr, hx - 4, mid - 9, lw, 18, 5)
            cr.set_source_rgba(*rgba(tone_bg))
            cr.fill()
        text(cr, hx + 2, mid, label, 13, "bg" if (focused or urgent) else "title", bold=True, valign=0.5)
        hits.add(hx - 4, mid - 10, lw, 20, lambda: self.go(ws))
        info = [f"#{ws['idx']}"] + (["focused"] if focused else (["visible"] if active else []))
        text(cr, hx + lw + 4, mid, " · ".join(info), 11, "dim", valign=0.5)
        n = len(wins)
        text(cr, x + W - 10, mid, f"{n}" if n else "empty", 11, "dim", align=1, valign=0.5)
        ry = y + self.HEAD_H
        if not wins:
            text(cr, x + 12, ry + self.ROW_H / 2, "nothing open", 12, "dim", valign=0.5)
        for w in wins:
            self.draw_row(cr, hits, x + 4, ry, W - 8, w, ws, rect, scale)
            ry += self.ROW_H

    def draw_row(self, cr, hits: Hits, x: float, y: float, w: float, win: dict, ws: dict, rect: dict,
                 scale: float) -> None:
        H, wid = self.ROW_H, win["id"]
        mid = y + H / 2
        self.order.append((wid, ws["id"]))
        self.rects.append((x, x + w, y, y + H, wid))
        picked = wid in (self.sel, self.hovered)
        focused = win.get("is_focused")
        if focused or picked:
            core.rrect(cr, x, y + 1, w, H - 2, 6)
            if focused:
                cr.set_source_rgba(*rgba("accent", 0.20))
                cr.fill_preserve()
                cr.set_source_rgba(*rgba("accent", 0.55 if picked else 0.35))
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.set_source_rgba(*rgba("bg2", 0.8))
                cr.fill()
            if wid == self.sel:  # the keyboard's mark
                core.rrect(cr, x + 1, y + 6, 3, H - 12, 1.5)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
        hits.add(x, y, w, H, lambda: self.focus(wid))

        app = win.get("app_id") or ""
        ix = x + 10
        surf = app_icon(app, scale) if app else None
        if surf is not None:
            cr.save()
            cr.translate(ix, mid - ICON / 2)
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            text(cr, ix + ICON / 2, mid, (app[:1] or "?").upper(), 12, "fg", align=0.5, valign=0.5)
        tx = ix + ICON + 8

        right = x + w - 6
        if picked:
            label = "close?" if self.closing == wid else "close"
            right -= button(cr, hits, right - self.chip_w(cr, label, GLYPH_CLOSE), y + 4, label,
                            lambda: self.close(wid), h=H - 8, size=11, glyph=GLYPH_CLOSE,
                            on=self.closing == wid, tone="hit") + 5
            up, down = self.neighbours(ws["id"])
            for target, glyph in ((down, GLYPH_DOWN), (up, GLYPH_UP)):
                if target is None:
                    continue
                tl = target.get("name") or str(target["idx"])
                right -= button(cr, hits, right - self.chip_w(cr, tl, glyph), y + 4, tl,
                                lambda t=target: self.move(wid, t), h=H - 8, size=11, glyph=glyph) + 5
        else:
            marks = []
            if win.get("is_urgent"):
                marks.append((GLYPH_URGENT, "urgent"))
            if win.get("is_floating"):
                marks.append((GLYPH_FLOAT, "blue"))
            tile = (win.get("layout") or {}).get("tile_size") or (0, 0)
            if abs(tile[0] - rect["width"]) < 1 and abs(tile[1] - rect["height"]) < 1:
                marks.append((GLYPH_FULL, "purple"))  # niri's IPC has no fullscreen flag: the tile fills the screen
            for glyph, tone in marks:
                right -= core.icon(cr, right, mid, glyph, 12, tone, align=1) + 6
            right -= text(cr, right, mid, app.split(".")[-1].lower()[:14], 11, "fg" if focused else "dim", align=1,
                          valign=0.5) + 10
        title = win.get("title") or app or "?"
        tone = "title" if (focused or picked or win["id"] == ws.get("active_window_id")) else "fg2"
        text(cr, tx, mid, title, 12, tone, bold=bool(focused), valign=0.5, width=max(30.0, right - tx - 4))

    @staticmethod
    def chip_w(cr, label: str, glyph: str) -> float:
        return core.text_w(cr, label, 11) + core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 23
