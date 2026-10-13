"""System: CPU, memory, temperature on the strip; the machine's last five minutes in
the panel, with the busiest processes (to act on: procs.py), the disks and the pending
updates."""

from __future__ import annotations

import time

from . import core, procs
from .core import Hits, button, graph, heading, rgba, text
from .deck import Panel
from .procs import Proc, Procs, nice_target
from .sample import HISTORY, Sampler

CPU = ("warn", 60, "hit", 85)
MEM = (75, 90)
TEMP = (85, 95)  # k10temp Tctl: this Ryzen sits at 60-85 under normal load


def cpu_tone(v: float) -> str:
    return core.level(v, 60, 85)


def temp_tone(v: float) -> str:
    return core.level(v, *TEMP)


def mem_tone(v: float) -> str:
    return core.level(v, *MEM)


class SysStrip:
    name = "sys"

    def __init__(self, s: Sampler):
        self.s = s

    def draw(self, variant: str, scale: int):
        s = self.s
        c = core.StripCanvas(scale)
        cpu = s.cpu[-1] if s.cpu else 0.0
        tone = cpu_tone(cpu)
        c.icon("󰍛", "fg", 14)
        n = 40 if variant == "full" else 24
        recent = list(s.cpu)[-n:]
        w = 36 if variant == "full" else 24
        core.spark(c.cr, c.x, core.MID - 7, w, 14, recent, tone, fill=0.3, line=1.1)
        c.gap(w + 5)
        c.text(f"{cpu:3.0f}%", tone)
        c.gap()
        mem = s.mem[-1] if s.mem else 0.0
        c.icon("󰘚", "fg", 14)
        if variant == "full":
            core.bar(c.cr, c.x, core.MID - 2.5, 22, 5, mem / 100, mem_tone(mem))
            swap = s.swap[-1] if s.swap else 0.0
            if swap > 1:
                core.bar(c.cr, c.x, core.MID + 4, 22, 2, swap / 100, "purple", r=1)
            c.gap(27)
        c.text(f"{mem:.0f}%", mem_tone(mem))
        if s.temp:
            c.gap()
            t = s.temp[-1]
            c.icon("󰔏", temp_tone(t), 14, after=2)
            c.text(f"{t:.0f}°", temp_tone(t))
        for mount, size, free in s.disks:
            used = 100 * (1 - free / size) if size else 0
            if used >= 85:
                c.gap()
                c.icon("󰋊", core.level(used, 85, 95), 14, after=2)
                c.text(f"{core.human_bytes(free)}", core.level(used, 85, 95))
        if s.updates:
            c.gap()
            c.icon("󰏗", "aqua", 14, after=2)
            c.text(str(s.updates), "aqua")
        return c.finish()


class SystemPanel(Panel):
    """The machine's last five minutes. The busiest processes are rows to act on: hover
    one (or select it, pinned: i/o, u/p the other list) for term, kill (click twice),
    nice and info (the full command line, user, start, RSS, threads, cwd)."""

    name = "sys"
    live = 1.0
    W = 600
    ROWS = 6
    ROW_H = 22
    INFO_H = 98
    GHOST_S = 6.0  # a row acted on stays this long after its process left the list, with its word

    def __init__(self, s: Sampler):
        self.s = s
        self.procs = Procs()
        self.sel_col, self.sel_idx, self.sel_pid = 0, -1, 0
        self.hovered: tuple[int, int] | None = None
        self.info_pid = 0
        self.drawn: dict[int, list[Proc]] = {0: [], 1: []}  # the rows as last drawn, per list
        self.ghosts: dict[tuple[int, int], tuple[Proc, int, float]] = {}  # (list, pid) -> (row, index, until)
        self.rects: list[tuple[float, float, float, float, int, int]] = []  # x0, x1, y0, y1, list, index

    def size(self):
        return self.W, 546 + (self.INFO_H if self.info_pid else 0)

    def opened(self) -> None:
        self.s.want_top = True
        self.procs.settle()
        self.sel_col, self.sel_idx, self.sel_pid = 0, -1, 0
        self.hovered, self.info_pid = None, 0
        self.ghosts.clear()

    def closed(self) -> None:
        self.s.want_top = False
        self.info_pid = 0

    # -- the process rows ------------------------------------------------------

    def column(self, c: int, items: list[Proc]) -> list[Proc]:
        """List c's rows: the scan's top ones, with the rows acted on that left it kept
        in place a few seconds (so their word, "gone", shows). Follows the selection."""
        rows = list(items[:self.ROWS])
        now = time.monotonic()
        for (gc, pid), (p, idx, until) in sorted(self.ghosts.items(), key=lambda kv: kv[1][1]):
            if gc == c and now < until and all(r.pid != pid for r in rows):
                rows.insert(min(idx, len(rows)), p)
        self.ghosts = {k: v for k, v in self.ghosts.items() if now < v[2]}
        rows = rows[:self.ROWS]
        self.drawn[c] = rows
        if c == self.sel_col and self.sel_idx >= 0 and rows:
            idx = next((i for i, r in enumerate(rows) if r.pid == self.sel_pid), None)
            self.sel_idx = idx if idx is not None else min(self.sel_idx, len(rows) - 1)
            self.sel_pid = rows[self.sel_idx].pid
        return rows

    def selected(self) -> Proc | None:
        rows = self.drawn.get(self.sel_col, [])
        return rows[self.sel_idx] if 0 <= self.sel_idx < len(rows) else None

    def select(self, c: int, i: int, p: Proc) -> bool:
        self.sel_col, self.sel_idx, self.sel_pid = c, i, p.pid
        return False

    def act(self, fn, p: Proc) -> bool:
        """Run term / kill / renice on p, and keep its rows where they are for a while."""
        fn(p)
        until = time.monotonic() + self.GHOST_S
        for c, rows in self.drawn.items():
            for i, r in enumerate(rows):
                if r.pid == p.pid:
                    self.ghosts[(c, p.pid)] = (r, i, until)
        return False

    def toggle_info(self, p: Proc) -> bool:
        self.info_pid = 0 if self.info_pid == p.pid else p.pid
        return False

    def key(self, key: str, ctrl: bool) -> bool:
        rows = self.drawn.get(self.sel_col, [])
        n = len(rows)
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel_idx = min(n - 1, self.sel_idx + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel_idx = max(0, self.sel_idx - 1)
        elif key in ("k", "Page_Down"):
            self.sel_idx = min(n - 1, self.sel_idx + self.ROWS // 2)
        elif key in ("l", "Page_Up"):
            self.sel_idx = max(0, self.sel_idx - self.ROWS // 2)
        elif key in ("u", "Left", "j"):
            self.sel_col, self.sel_idx = 0, max(0, self.sel_idx)
            rows = self.drawn.get(0, [])
        elif key in ("p", "Right", "semicolon"):
            self.sel_col, self.sel_idx = 1, max(0, self.sel_idx)
            rows = self.drawn.get(1, [])
        else:
            p = self.selected()
            if p is None:
                return False
            if key == "t":
                self.act(self.procs.term, p)
            elif key == "K":
                self.act(self.procs.kill, p)
            elif key == "n":
                self.act(self.procs.renice, p)
            elif key in ("Return", "KP_Enter"):
                self.toggle_info(p)
            else:
                return False
            return True
        if rows:
            self.sel_idx = min(self.sel_idx, len(rows) - 1)
            self.sel_pid = rows[self.sel_idx].pid
        return True

    def hover(self, x: float, y: float) -> bool:
        at = next(((c, i) for x0, x1, y0, y1, c, i in self.rects if x0 <= x < x1 and y0 <= y < y1), None)
        if at != self.hovered:
            self.hovered = at
            return True
        return False

    def draw_proc(self, cr, hits: Hits, x: float, y: float, w: float, c: int, i: int, p: Proc) -> None:
        """One process row: its name, and at the right its number, its status word, or
        (hovered / selected) its chips."""
        H = self.ROW_H
        mid = y + H / 2
        live = any(r.pid == p.pid for r in (self.s.top_cpu if c == 0 else self.s.top_mem)[:self.ROWS])
        picked = self.hovered == (c, i) or (c == self.sel_col and i == self.sel_idx)
        why = procs.blocked(p)
        x0, rw = x - 6, w + 12
        if picked or self.info_pid == p.pid:
            core.rrect(cr, x0, y + 1, rw, H - 2, 6)
            cr.set_source_rgba(*rgba("bg1"))
            cr.fill()
            if c == self.sel_col and i == self.sel_idx:  # the keyboard's mark
                core.rrect(cr, x0 + 1, y + 6, 3, H - 12, 1.5)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
        self.rects.append((x0, x0 + rw, y, y + H, c, i))
        hits.add(x0, y, rw, H, lambda: self.select(c, i, p))

        right = x + w
        status = self.procs.status.get(p.pid)
        if status:
            right -= text(cr, right, mid, status[1], 11, status[0], align=1, valign=0.5) + 8
        elif picked and not why and live:
            for label, fn, tone, on in (
                ("info", lambda: self.toggle_info(p), "accent", self.info_pid == p.pid),
                ("nice" if nice_target(p) != 0 else "nice 0",
                 (lambda: self.act(self.procs.renice, p)) if nice_target(p) is not None else None, "aqua", False),
                ("kill?" if self.procs.killing == p.pid else "kill", lambda: self.act(self.procs.kill, p), "hit",
                 self.procs.killing == p.pid),
                ("term", lambda: self.act(self.procs.term, p), "warn", False),
            ):
                if fn is None:
                    continue
                cw = core.text_w(cr, label, 10) + 14
                button(cr, hits, right - cw, y + 3, label, fn, w=cw, h=H - 6, size=10, on=on, tone=tone)
                right -= cw + 4
            right -= 4
        elif picked and why:
            right -= text(cr, right, mid, why, 11, "dim", align=1, valign=0.5) + 8
        else:
            value = f"{p.value:.0f}%" if c == 0 else core.human_bytes(p.value)
            tone = "dim" if (why or not live) else (cpu_tone(p.value / max(1, self.s.ncpu) * 4) if c == 0 else "fg")
            right -= text(cr, right, mid, value, 12, tone, align=1, valign=0.5) + 8
        # The PID tells the rows of one program apart (six "ng serve web" by memory).
        pid = str(p.pid)
        tag = f"n{p.nice}" if p.nice else ""
        tail = core.text_w(cr, pid, 10) + 6 + (core.text_w(cr, tag, 10) + 5 if tag else 0)
        name_tone = "dim" if (why or not live) else ("title" if picked else "fg2")
        room = right - x - tail
        if room < 50:  # chips: the name keeps the room, the PID goes
            pid, tail, room = "", tail - core.text_w(cr, pid, 10) - 6, right - x - (tail - core.text_w(cr, pid, 10) - 6)
        tx = x + text(cr, x, mid, p.name, 12, name_tone, valign=0.5, width=max(30.0, room)) + 6
        if pid:
            tx += text(cr, tx, mid + 1, pid, 10, "dim", valign=0.5) + 5
        if tag:
            text(cr, tx, mid + 1, tag, 10, "aqua" if p.nice > 0 else "warn", valign=0.5)

    def draw_info(self, cr, hits: Hits, P: float, y: float) -> None:
        """The info block under the lists: one process, close up."""
        W, H = self.W, self.INFO_H - 8
        pid = self.info_pid
        d = procs.info(pid)
        core.rrect(cr, P - 6, y, W - 2 * P + 12, H, 8)
        cr.set_source_rgba(*rgba("bg1", 0.6))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("bg2"))
        cr.set_line_width(1)
        cr.stroke()
        x, right = P + 4, W - P - 4
        right -= button(cr, hits, right - 26, y + 7, "×", lambda: setattr(self, "info_pid", 0) or False,
                        w=26, h=20, size=11) + 6
        if d is None:
            text(cr, x, y + 10, f"pid {pid}: gone", 13, "dim", bold=True)
            return
        right -= button(cr, hits, right - 62, y + 7, "htop", lambda: core.spawn(
            ["alacritty", "-e", "htop", "-p", str(pid)]) or True, w=62, h=20, size=11, glyph="")
        nw = text(cr, x, y + 8, d["comm"], 14, "title", bold=True)
        text(cr, x + nw + 8, y + 11, f"pid {pid} · {d['user']} · state {d['state']}", 11, "dim",
             width=right - x - nw - 16)
        facts = (f"started {d['started']} ({core.dur(d['age'])} ago) · RSS {core.human_bytes(d['rss'])} · "
                 f"{d['threads']} threads · nice {d['nice']}")
        text(cr, x, y + 30, facts, 12, "fg", width=W - 2 * P - 8)
        text(cr, x, y + 47, f"cwd {d['cwd']}", 11, "fg2", width=W - 2 * P - 8)
        lay = core.layout(cr, d["cmd"], 11)
        lay.set_width(int((W - 2 * P - 8) * core.Pango.SCALE))
        lay.set_wrap(core.Pango.WrapMode.CHAR)
        lay.set_height(-2)  # two lines at most, then …
        lay.set_ellipsize(core.Pango.EllipsizeMode.END)
        cr.move_to(x, y + 63)
        cr.set_source_rgba(*rgba("dim"))
        core.PangoCairo.show_layout(cr, lay)

    def draw(self, cr, hits: Hits) -> None:
        s = self.s
        W = self.W
        core.panel_frame(cr, W, self.size()[1])
        P = 16
        # Header.
        hw = text(cr, P, 10, s.host, 18, "title", bold=True)
        la = " ".join(f"{v:.1f}" for v in s.load)
        text(cr, W - P, 14, f"up {core.dur(s.uptime)} · load {la}", 12, "fg", align=1)
        text(cr, P + hw + 10, 15, f"{s.ncpu} threads", 12, "dim")
        text(cr, P, 32, s.cpu_model, 11, "dim", width=W - 2 * P)

        # CPU.
        y = 58
        cpu = s.cpu[-1] if s.cpu else 0
        heading(cr, P, y, "cpu", W - 2 * P - 60)
        text(cr, W - P, y - 3, f"{cpu:.0f}%", 15, cpu_tone(cpu), bold=True, align=1)
        y += 20
        graph(cr, P, y, W - 2 * P, 70, [(list(s.cpu), cpu_tone(cpu))])
        text(cr, P + 6, y + 4, f"{HISTORY // 60} min", 10, "dim")
        y += 76
        n = len(s.cores) or 1
        cw = (W - 2 * P) / n
        for i, v in enumerate(s.cores):
            bx = P + i * cw
            core.rrect(cr, bx + 1, y, cw - 2, 18, 2)
            cr.set_source_rgba(*rgba("bg1"))
            cr.fill()
            bh = 18 * min(100.0, v) / 100
            if bh > 0.5:
                core.rrect(cr, bx + 1, y + 18 - bh, cw - 2, bh, 2)
                cr.set_source_rgba(*rgba(cpu_tone(v)))
                cr.fill()
        y += 30

        # Memory and temperature, side by side.
        half = (W - 2 * P - 16) / 2
        mi = s.meminfo
        used = mi.get("MemTotal", 0) - mi.get("MemAvailable", 0)
        swap_used = mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)
        mem = s.mem[-1] if s.mem else 0
        heading(cr, P, y, "memory", half)
        y2 = y + 20
        graph(cr, P, y2, half, 54, [(list(s.mem), mem_tone(mem)), (list(s.swap), "purple")])
        text(cr, P, y2 + 60, f"{core.human_bytes(used)} of {core.human_bytes(mi.get('MemTotal', 0))}",
             12, mem_tone(mem))
        text(cr, P + half, y2 + 60, f"swap {core.human_bytes(swap_used)}", 12, "purple", align=1)
        tx = P + half + 16
        t = s.temp[-1] if s.temp else 0
        heading(cr, tx, y, "temperature", half)
        graph(cr, tx, y2, half, 54, [(list(s.temp), temp_tone(t))], top=105, grid=(50, 75, 95))
        extra = " · ".join(f"{k} {v:.0f}°" for k, v in s.extra_temps.items())
        text(cr, tx, y2 + 60, f"cpu {t:.0f}°C", 12, temp_tone(t))
        text(cr, tx + half, y2 + 60, extra, 12, "dim", align=1)
        y = y2 + 86

        # Busiest processes: hover a row (or select it, pinned: i/o) for its actions.
        heading(cr, P, y, "busiest", W - 2 * P)
        y += 18
        self.procs.refresh()
        self.rects = []
        col = (W - 2 * P - 16) / 2
        for c, (items, x) in enumerate(((s.top_cpu, P), (s.top_mem, tx))):
            for i, p in enumerate(self.column(c, items)):
                self.draw_proc(cr, hits, x, y + i * self.ROW_H, col, c, i, p)
        if not s.top_cpu:
            text(cr, P, y + 3, "measuring…", 12, "dim")
        y += self.ROWS * self.ROW_H + 8
        if self.info_pid:
            self.draw_info(cr, hits, P, y)
            y += self.INFO_H

        # Disks and updates.
        heading(cr, P, y, "disks & packages", W - 2 * P)
        y += 22
        x = P
        for mount, size, free in s.disks:
            used_pct = 100 * (1 - free / size) if size else 0
            text(cr, x, y, mount, 12, "fg")
            core.bar(cr, x + 34, y + 5, 110, 6, used_pct / 100, core.level(used_pct, 75, 90))
            text(cr, x + 150, y, f"{core.human_bytes(free)} free", 12, "dim")
            x += 250
        upd = s.updates
        label = "no updates" if upd == 0 else (f"{upd} updates" if upd else "updates: ?")
        text(cr, W - P - 180, y, label, 12, "aqua" if upd else "dim", align=1)
        bx = W - P - 170
        bx += button(cr, hits, bx, y - 3, "check", lambda: core.menu_action("updates.sh", 1) or self.s.poke(),
                     size=11, h=20) + 6
        button(cr, hits, bx, y - 3, "upgrade", lambda: core.menu_action("updates.sh", 3) or True, size=11, h=20)
        y += 30

        x = P
        for label, glyph, action in (
            ("htop", "", lambda: core.spawn(["alacritty", "-e", "htop"]) or True),
            ("by memory", "󰘚", lambda: core.spawn(["alacritty", "-e", "htop", "-s", "PERCENT_MEM"]) or True),
            ("biggest dirs", "󰋊", lambda: core.menu_action("disk.sh", 1) or True),
            ("boot blame", "󰔟", lambda: core.menu_action("uptime.sh", 3) or True),
        ):
            x += button(cr, hits, x, y, label, action, glyph=glyph) + 8
