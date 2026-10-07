"""Workspaces: niri's workspaces of each output, with what is open in them.

Each workspace with windows (and the visible one) is a chip: its name, then one mark
per column in column order: the app's icon, or for a terminal the first letters of
its title (seven Alacritty icons say nothing; "cm cl nv" does). The focused column is
underlined. Click a chip: that workspace. Click a mark: that window. Scroll: the
next / previous workspace.

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
from .core import MID, PILL_H, PILL_Y, SH, rgba, text  # noqa: E402

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

