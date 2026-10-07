"""Devices: Bluetooth and the known devices (headphones, keyboard, mouse) on the strip;
in the panel, connect / disconnect each, Bluetooth power, and where sound goes.

The devices are the ones the i3blocks scripts know (MAC and NAME in bt-*.sh); their
buttons run those scripts' menus, and Bluetooth's run bluetooth.sh's."""

from __future__ import annotations

from . import core
from .core import Hits, button, heading, rgba, text
from .deck import Panel
from .sample import Sampler


def bt_tone(s: Sampler) -> tuple[str, str]:
    if not s.bt_powered:
        return "󰂲", "dim"
    if s.bt_connected:
        return "󰂱", "blue"
    return "󰂯", "fg"


class DevStrip:
    name = "dev"

    def __init__(self, s: Sampler):
        self.s = s

    def draw(self, variant: str, scale: int):
        s = self.s
        c = core.StripCanvas(scale)
        glyph, tone = bt_tone(s)
        c.icon(glyph, tone, 15, after=6)
        for d in s.devices:
            on = d.mac in s.bt_connected
            c.icon(d.glyph, "title" if on else "bg3", 15, after=5)
            if on and d.kind == "mouse" and s.mouse_level and variant == "full":
                level = s.mouse_level
                tone = "hit" if level in ("Critical", "Low") else ("ok" if level in ("Full", "High") else "fg")
                if level.isdigit():
                    tone = core.level(100 - int(level), 70, 85)
                c.cr.arc(c.x - 2, core.BAR_H / 2 + 7, 1.8, 0, 6.3)
                c.cr.set_source_rgba(*rgba(tone))
                c.cr.fill()
        c.gap(-5)
        return c.finish()


class DevPanel(Panel):
    name = "dev"
    live = 1.0
    W = 470

    def __init__(self, s: Sampler):
        self.s = s

    def size(self):
        n_audio = len(self.s.sinks) + len(self.s.sources)
        return self.W, 210 + 34 * len(self.s.devices) + 22 * max(2, n_audio)

    def opened(self) -> None:
        self.s.want_audio = True
        self.s.poke()

    def closed(self) -> None:
        self.s.want_audio = False

    def draw(self, cr, hits: Hits) -> None:
        s = self.s
        W, P = self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        glyph, tone = bt_tone(s)
        y = 12
        core.icon(cr, P, y + 11, glyph, 22, tone)
        text(cr, P + 30, y, "Bluetooth", 18, "title", bold=True)
        state = "off" if not s.bt_powered else (f"{len(s.bt_connected)} connected" if s.bt_connected else "on")
        text(cr, P + 140, y + 4, state, 12, tone)
        button(cr, hits, W - P - 46, y, "off", lambda: core.menu_action("bluetooth.sh", 3, "power off")
               or self.s.poke(), on=not s.bt_powered, tone="bg3", w=46)
        button(cr, hits, W - P - 98, y, "on", lambda: core.menu_action("bluetooth.sh", 3, "power on")
               or self.s.poke(), on=s.bt_powered, tone="blue", w=46)
        y += 40

        heading(cr, P, y, "devices", W - 2 * P)
        y += 20
        for d in s.devices:
            on = d.mac in s.bt_connected
            core.rrect(cr, P, y, W - 2 * P, 28, 6)
            cr.set_source_rgba(*rgba("bg1", 0.7 if on else 0.35))
            cr.fill()
            core.icon(cr, P + 10, y + 14, d.glyph, 17, "title" if on else "dim")
            text(cr, P + 36, y + 6, d.name, 13, "title" if on else "fg", bold=on)
            name_w = core.text_w(cr, d.name, 13, bold=on)
            text(cr, P + 44 + name_w, y + 7, d.mac, 11, "dim")
            if on and d.kind == "mouse" and s.mouse_level:
                text(cr, W - P - 120, y + 7, f"battery {s.mouse_level.lower()}", 11, "fg", align=1)
            label = "disconnect" if on else "connect"
            button(cr, hits, W - P - 104, y + 3, label,
                   lambda d=d, label=label: core.menu_action(d.script, 1, label) or self.s.poke(),
                   on=False, tone="blue", w=98, h=22, size=11, glyph="󰂲" if on else "󰂱")
            y += 34
        y += 6

        heading(cr, P, y, "sound goes to", W - 2 * P)
        y += 20
        if not s.sinks and not s.sources:
            text(cr, P, y, "reading…", 12, "dim")
            y += 22
        for kind, items, default in (("out", s.sinks, s.default_sink), ("in", s.sources, s.default_source)):
            for item in items:
                cur = item["name"] == default
                core.icon(cr, P + 2, y + 9, ("󰓃" if kind == "out" else "󰍬"), 14, "ok" if cur else "dim")
                text(cr, P + 24, y + 2, item["desc"], 12, "title" if cur else "fg", bold=cur, width=W - 2 * P - 40)
                cmd = "set-default-sink" if kind == "out" else "set-default-source"
                hits.add(P, y, W - 2 * P, 20, lambda n=item["name"], cmd=cmd:
                         core.spawn(["pactl", cmd, n]) or self.s.poke())
                y += 22
        y += 8
        x = P
        for label, glyph, action in (
            ("mixer", "󰕾", lambda: core.spawn(["pavucontrol"]) or True),
            ("bluetoothctl", "󰂯", lambda: core.menu_action("bluetooth.sh", 3, "bluetoothctl") or True),
            ("restart logid", "󰍽", lambda: core.menu_action("bluetooth.sh", 3, "restart logid") or True),
            ("nuke bt", "󰚌", lambda: core.menu_action("bluetooth.sh", 3, "nuke_bt") or True),
        ):
            x += button(cr, hits, x, y, label, action, glyph=glyph) + 8
