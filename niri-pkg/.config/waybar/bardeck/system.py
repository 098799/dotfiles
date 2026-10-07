"""System: CPU, memory, temperature on the strip; the machine's last five minutes in
the panel, with the busiest processes, the disks and the pending updates."""

from __future__ import annotations

from . import core
from .core import Hits, button, graph, heading, rgba, text
from .deck import Panel
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
    name = "sys"
    live = 1.0
    W = 600

    def __init__(self, s: Sampler):
        self.s = s

    def size(self):
        return self.W, 550

    def opened(self) -> None:
        self.s.want_top = True

    def closed(self) -> None:
        self.s.want_top = False

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

        # Busiest processes.
        heading(cr, P, y, "busiest", W - 2 * P)
        y += 20
        col = (W - 2 * P - 16) / 2
        for i, (name, pct) in enumerate(s.top_cpu[:6]):
            ry = y + i * 17
            text(cr, P, ry, name, 12, "title", width=col - 60)
            text(cr, P + col, ry, f"{pct:.0f}%", 12, cpu_tone(pct / max(1, s.ncpu) * 4), align=1)
        for i, (name, rss) in enumerate(s.top_mem[:6]):
            ry = y + i * 17
            text(cr, tx, ry, name, 12, "title", width=col - 60)
            text(cr, tx + col, ry, core.human_bytes(rss), 12, "fg", align=1)
        if not s.top_cpu:
            text(cr, P, y, "measuring…", 12, "dim")
        y += 6 * 17 + 10

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
