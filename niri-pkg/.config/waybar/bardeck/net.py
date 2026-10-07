"""Network: the link, its signal and traffic, the VPN on the strip; in the panel the
link's details, five minutes of traffic, VPN switches and network.sh's actions.

The buttons run the i3blocks scripts' own menu entries (core.menu_action), so the
wg-quick lines, the adapter reset and the speedtest live in one place:
vpn.sh and network.sh."""

from __future__ import annotations

from . import core
from .core import Hits, button, graph, heading, text
from .deck import Panel
from .sample import HISTORY, Sampler

# vpn.sh's menu entries, by interface.
VPN_CHOICES = (("off", "off", None), ("wg_1", "tomek (wg_1)", "wg_1"), ("wg_2", "tomek2 (wg_2)", "wg_2"))
NET_ACTIONS = (("rescan", "󰑐"), ("link rates", "󰓅"), ("reconnect", "󰑓"),
               ("reset adapter", "󰜺"), ("nmtui", ""), ("speedtest", "󰓅"))


def signal_pct(wifi: dict) -> int | None:
    """NetworkManager's strength, or the dBm iw gave, as 0-100."""
    if wifi.get("strength") is not None:
        return int(wifi["strength"])
    try:
        return max(0, min(100, int((int(wifi.get("signal")) + 100) * 2)))
    except (TypeError, ValueError):
        return None


def wifi_glyph(pct: int | None) -> str:
    if pct is None:
        return "󰖩"
    return "󰤟󰤢󰤥󰤨"[min(3, pct // 26)]


class NetStrip:
    name = "net"

    def __init__(self, s: Sampler):
        self.s = s

    def draw(self, variant: str, scale: int):
        s = self.s
        c = core.StripCanvas(scale)
        links = s.links
        wifi = s.wifi
        if not links:
            c.icon("󰖪", "hit", 15)
            c.text("offline", "hit")
        elif wifi.get("ssid"):
            pct = signal_pct(wifi)
            tone = "ok" if (pct or 0) >= 70 else ("warn" if (pct or 0) >= 40 else "orange")
            c.icon(wifi_glyph(pct), tone, 15)
            if variant == "full":
                ssid = wifi["ssid"]
                c.text(ssid if len(ssid) <= 11 else ssid[:10] + "…", "title")
        else:
            name, kind, ip = links[0]
            c.icon("󰈀", "ok", 15)
            if variant == "full":
                c.text(ip or name, "title")
        if variant == "full" and links:
            c.gap(8)
            n = 30
            rx, tx = list(s.rx)[-n:], list(s.tx)[-n:]
            top = max([1.0, *rx, *tx])
            core.spark(c.cr, c.x, core.MID - 7, 34, 14, rx, "blue", top=top, fill=0.35, line=1)
            core.spark(c.cr, c.x, core.MID - 7, 34, 14, tx, "purple", top=top, fill=0.0, line=1)
            c.gap(38)
            now = (rx[-1] if rx else 0) + (tx[-1] if tx else 0)
            if now >= 100 * 1024:
                c.text(core.human_bytes(rx[-1] if rx else 0), "blue", size=12)
        if s.vpn:
            c.gap(8)
            c.icon("󰦝", "ok", 14, after=2)
            if variant == "full":
                c.text(s.vpn[0].replace("_", ""), "ok")
        elif variant == "full":
            c.gap(8)
            c.icon("󰦞", "dim", 14, after=0)
        if s.tailscale:
            c.gap(6)
            c.icon("󰖂", "aqua", 13, after=0)
        return c.finish()


class NetPanel(Panel):
    name = "net"
    live = 1.0
    W = 470

    def __init__(self, s: Sampler):
        self.s = s

    def size(self):
        return self.W, 352

    def opened(self) -> None:
        self.s.want_link = True  # iw's dBm and link rates, only while open
        self.s.poke()

    def closed(self) -> None:
        self.s.want_link = False

    def draw(self, cr, hits: Hits) -> None:
        s = self.s
        W, P = self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        wifi = s.wifi
        y = 12
        if wifi.get("ssid"):
            pct = signal_pct(wifi)
            tone = "ok" if (pct or 0) >= 70 else ("warn" if (pct or 0) >= 40 else "orange")
            core.icon(cr, P, y + 11, wifi_glyph(pct), 22, tone)
            text(cr, P + 30, y, wifi["ssid"], 18, "title", bold=True)
            band = ""
            try:
                band = "5 GHz" if float(wifi.get("freq", 0)) < 5900 and float(wifi.get("freq", 0)) > 4900 else (
                    "6 GHz" if float(wifi.get("freq", 0)) >= 5900 else "2.4 GHz")
            except ValueError:
                pass
            dbm = f"{wifi['signal']} dBm · " if wifi.get("signal") else ""
            text(cr, W - P, y + 4, f"{dbm}{pct or 0}% · {band}", 12, tone, align=1)
            y += 28
            if wifi.get("rx"):
                text(cr, P + 30, y, f"↓ {wifi['rx']}   ↑ {wifi.get('tx', '?')}   link rate", 12, "dim")
            else:
                text(cr, P + 30, y, f"{wifi.get('bitrate', '?')} link rate", 12, "dim")
        elif s.links:
            core.icon(cr, P, y + 11, "󰈀", 22, "ok")
            text(cr, P + 30, y, "wired", 18, "title", bold=True)
            y += 28
        else:
            core.icon(cr, P, y + 11, "󰖪", 22, "hit")
            text(cr, P + 30, y, "offline", 18, "hit", bold=True)
            y += 28
        y += 20
        for name, kind, ip in s.links:
            text(cr, P, y, name, 12, "fg")
            text(cr, P + 110, y, ip or "no IPv4", 12, "title")
            y += 16
        if s.tailscale:
            text(cr, P, y, "tailscale0", 12, "fg")
            text(cr, P + 110, y, s.tailscale, 12, "aqua")
            y += 16
        y += 8

        rx = s.rx[-1] if s.rx else 0
        tx = s.tx[-1] if s.tx else 0
        heading(cr, P, y, "traffic", W - 2 * P - 150)
        text(cr, W - P - 70, y - 2, f"↓ {core.human_bytes(rx, True)}", 12, "blue", align=1)
        text(cr, W - P, y - 2, f"↑ {core.human_bytes(tx, True)}", 12, "purple", align=1)
        y += 20
        top = max([1.0, *s.rx, *s.tx]) * 1.1
        graph(cr, P, y, W - 2 * P, 64, [(list(s.rx), "blue"), (list(s.tx), "purple")], top=top, grid=())
        text(cr, P + 6, y + 4, f"{HISTORY // 60} min · peak {core.human_bytes(top / 1.1, True)}", 10, "dim")
        y += 76

        heading(cr, P, y, "vpn", W - 2 * P)
        y += 20
        x = P
        up = set(s.vpn)
        for label, choice, iface in VPN_CHOICES:
            on = (iface in up) if iface else not up
            x += button(cr, hits, x, y, label, lambda c=choice: core.menu_action("vpn.sh", 3, c) or self.s.poke(),
                        on=on, tone="ok" if iface else "bg3", glyph="󰦝" if iface else "󰦞") + 8
        others = [v for v in s.vpn if v not in ("wg_1", "wg_2")]
        if others:
            text(cr, x + 4, y + 3, " ".join(others), 12, "ok")
        y += 34

        heading(cr, P, y, "actions", W - 2 * P)
        y += 20
        x = P
        for label, glyph in NET_ACTIONS:
            bw = core.text_w(cr, label, 12) + core.text_w(cr, glyph, 14, family=core.ICON_FONT) + 23
            if x + bw > W - P:
                x, y = P, y + 28
            x += button(cr, hits, x, y, label, lambda c=label: core.menu_action("network.sh", 3, c) or True,
                        glyph=glyph) + 8
