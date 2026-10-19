"""Network: the link, its signal and traffic, the VPN on the strip; in the panel the
link's details, the Wi-Fi networks in range (join one, like nmtui), the tailnet's
devices (tailnet.py: copy an address, ssh, ping), five minutes of traffic, VPN
switches and network.sh's actions.

The buttons run the i3blocks scripts' own menu entries (core.menu_action), so the
wg-quick lines, the adapter reset and the speedtest live in one place:
vpn.sh and network.sh."""

from __future__ import annotations

import time

from . import core, tailnet
from .core import Hits, button, graph, heading, text
from .deck import Panel
from .sample import HISTORY, Sampler
from .tailnet import Peer
from .wifi import Network

# vpn.sh's menu entries, by interface.
VPN_CHOICES = (("off", "off", None), ("wg_1", "tomek (wg_1)", "wg_1"), ("wg_2", "tomek2 (wg_2)", "wg_2"))
# The panel's network list replaced network.sh's "rescan" (a terminal with nmcli's list).
NET_ACTIONS = (("link rates", "󰓅"), ("reconnect", "󰑓"),
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


def signal_tone(pct: int | None) -> str:
    return "ok" if (pct or 0) >= 70 else ("warn" if (pct or 0) >= 40 else "orange")


def bars(cr, x: float, mid: float, pct: int, tone: str) -> float:
    """Four rising bars, lit by signal: the list's own signal mark. Returns the width."""
    lit = 1 + (pct >= 30) + (pct >= 55) + (pct >= 75)
    for i in range(4):
        h = 4 + 3 * i
        core.rrect(cr, x + i * 5, mid + 6 - h, 3, h, 1)
        cr.set_source_rgba(*core.rgba(tone if i < lit else "bg2"))
        cr.fill()
    return 18


GLYPH_LOCK, GLYPH_OPEN, GLYPH_SAVED = "\uf023", "\uf09c", "\uf02e"
GLYPH_SCAN, GLYPH_OFF, GLYPH_FORGET = "󰑐", "󰖪", "\U000f01b4"
GLYPH_EYE, GLYPH_EYE_OFF, GLYPH_CHECK = "\uf06e", "\uf070", "\uf00c"
GLYPH_TS, GLYPH_SHELL = "\U000f0582", "\uf120"
ME = 10_000  # the hover index of this node's own tailscale row (keys never select it)


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
            # No SSID on the bar (the panel has it): the icon's colour says the link.
            c.icon(wifi_glyph(pct), tone, 15, after=0)
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
    """The link, then the networks in range: a list to join one from, like nmtui's
    "Activate a connection". Click a row (or `i`/`o` and Enter when pinned) to join;
    a secured network that is not saved yet opens a password field in its row.

    Under it the tailnet: this node and each peer. The keyboard's selection runs on
    from the last network into the peers. A click on a peer (or Enter) copies its
    address; hovered, it shows "ping" and "ssh"; `t` pings the selected or hovered
    peer, or with none every online one (pings run only when asked)."""

    name = "net"
    live = 1.0
    W = 470
    ROWS = 8      # rows shown; the list scrolls (wheel, keys) past that
    ROW_H = 26
    FIELD_H = 42
    TS_ROWS = 6   # peers shown (online first); the rest are counted
    TS_H = 24

    def __init__(self, s: Sampler):
        self.s = s
        self.sel = -1          # the keyboard's row (-1: none yet)
        self.top = 0           # the first row shown
        self.hovered = -1
        self.asking: Network | None = None  # the row with the password field open
        self.buf = ""
        self.reveal = False
        self.note = ""         # a word under the field (too short, …)
        self.forgetting = ""   # an SSID whose forget button asks to be clicked again
        self.rows: list[tuple[float, float, int]] = []  # (y0, y1, index), for hover
        self.copied: tuple[str, float] = ("", 0.0)  # the address last copied, and when
        self.exit_asked = False  # an exit node was clicked without operator rights: say why louder

    # -- state -----------------------------------------------------------------

    @property
    def nets(self) -> list[Network]:
        return self.s.nets.networks

    @property
    def peers(self) -> list[Peer]:
        return self.s.ts.peers[:self.TS_ROWS]

    @property
    def typing(self) -> bool:  # Panel.typing: the Deck sends every key to text_key
        return self.asking is not None

    def ts_h(self) -> float:
        ts = self.s.ts
        h = 22 + self.TS_H + 8
        if ts.state != "Running":
            return h
        h += max(1, len(self.peers)) * self.TS_H
        if len(ts.peers) > self.TS_ROWS:
            h += 14
        if ts.exit_options or ts.exit_status:
            h += 30 + (14 if not ts.operator else 0)
        if ts.error:
            h += 14
        return h

    def list_h(self) -> float:
        n = len(self.nets)
        h = 22 + max(1, min(self.ROWS, n)) * self.ROW_H + 8
        if n > self.ROWS:
            h += 14  # "n more" under the list
        if self.asking is not None:
            h += self.FIELD_H
        return h

    def size(self):
        return self.W, 316 + self.list_h() + self.ts_h()

    def opened(self) -> None:
        self.s.want_link = True  # iw's dBm and link rates, the networks, the tailnet: only while open
        if time.monotonic() - self.s.nets.scanned_at > 20:
            self.s.nets.want_scan = True
        self.s.ts.read_at = 0.0
        self.s.ts.pings, self.s.ts.via = {}, {}  # an old latency is no reading
        self.sel, self.top, self.hovered, self.forgetting, self.exit_asked = -1, 0, -1, "", False
        self.s.nets.settle()
        self.cancel()
        self.s.poke()

    def closed(self) -> None:
        self.s.want_link = False
        self.cancel()

    def cancel(self) -> None:
        self.asking, self.buf, self.reveal, self.note = None, "", False, ""

    def follow(self) -> None:
        """Scroll so the selection shows."""
        n = len(self.nets)
        self.top = max(0, min(self.top, n - self.ROWS))
        if self.sel >= n:  # a tailnet peer: the network list stays where it is
            return
        if 0 <= self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.ROWS:
            self.top = self.sel - self.ROWS + 1

    # -- actions ---------------------------------------------------------------

    def join(self, n: Network) -> bool:
        """A click on a row, or Enter. True closes the panel (nmtui opened)."""
        w = self.s.nets
        self.forgetting = ""
        if n.active:
            return False
        if w.needs_password(n) or w.ask == n.ssid:
            self.cancel()
            self.asking = n
            self.note = "the saved password failed: type it again" if n.saved else ""
            return False
        if not n.saved and (n.enterprise or n.wep):
            w.connect(n)
            return True
        w.connect(n)
        return False

    def submit(self) -> None:
        n = self.asking
        if n is None:
            return
        if not 8 <= len(self.buf) <= 63:
            self.note = "a WPA password has 8 to 63 characters"
            return
        self.s.nets.connect(n, self.buf)
        self.cancel()
        self.s.poke()

    def forget(self, n: Network) -> bool:
        if self.forgetting != n.ssid:
            self.forgetting = n.ssid  # the button turns red: a second click forgets
            return False
        self.forgetting = ""
        self.s.nets.forget(n)
        return False

    def rescan(self) -> bool:
        self.s.nets.want_scan = True
        self.s.poke()
        return False

    def copy_ip(self, p: Peer) -> bool:
        if p.ip:
            tailnet.copy(p.ip)
            self.copied = (p.ip, time.monotonic())
        return False

    def ping(self, p: Peer | None = None) -> bool:
        """One peer, or every online one: only ever on demand."""
        for peer in [p] if p is not None else [x for x in self.s.ts.peers if x.online]:
            self.s.ts.ping(peer)
        return False

    def ssh(self, p: Peer) -> bool:
        tailnet.ssh(p.host)
        return True

    def exit_node(self, p: Peer | None) -> bool:
        ts = self.s.ts
        if not ts.operator:
            self.exit_asked = True  # the line under the chips turns yellow
            return False
        ts.set_exit_node(p)
        return False

    def peer_at(self, i: int) -> Peer | None:
        """The peer behind a selection / hover index (the networks come first)."""
        if i == ME:
            return self.s.ts.me
        j = i - len(self.nets)
        peers = self.peers
        return peers[j] if 0 <= j < len(peers) else None

    def paste(self) -> None:
        gi = __import__("gi")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk

        got = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""
        self.buf += got.strip("\r\n")

    # -- input -----------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool:
        nets = self.nets
        n = len(nets)
        last = n + len(self.peers) - 1  # the selection runs on into the tailnet's peers
        peer = self.peer_at(self.sel) or (self.peer_at(self.hovered) if self.hovered >= n else None)
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = min(last, self.sel + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key in ("k", "Page_Down") or (ctrl and key == "v"):
            self.sel = min(last, self.sel + self.ROWS // 2)
        elif key in ("l", "Page_Up"):
            self.sel = max(0, self.sel - self.ROWS // 2)
        elif key in ("Return", "KP_Enter") and 0 <= self.sel < n:
            self.join(nets[self.sel])
        elif key in ("Return", "KP_Enter", "c") and peer is not None:
            self.copy_ip(peer)
        elif key == "t":
            self.ping(peer if peer is not None and not peer.me else None)
        elif key == "s" and peer is not None and peer.shell and not peer.me:
            self.ssh(peer)
            return "close"
        elif key == "r":
            self.rescan()
        elif key == "d":
            active = next((x for x in nets if x.active), None)
            if active is not None:
                self.s.nets.disconnect(active)
        elif key in ("Delete", "x") and 0 <= self.sel < n and nets[self.sel].saved:
            self.forget(nets[self.sel])
        else:
            return False
        self.follow()
        return True

    def text_key(self, key: str, char: str, ctrl: bool, alt: bool) -> bool:
        if key == "Escape" or (ctrl and key == "g"):
            self.cancel()
        elif key in ("Return", "KP_Enter"):
            self.submit()
        elif key == "BackSpace":
            self.buf = "" if ctrl else self.buf[:-1]
        elif ctrl and key == "u":
            self.buf = ""
        elif ctrl and key in ("v", "y"):
            self.paste()
        elif key in ("Tab", "ISO_Left_Tab"):
            self.reveal = not self.reveal
        elif char and not ctrl:
            self.buf += char
            self.note = ""
        else:
            return False
        return True

    def hover(self, x: float, y: float) -> bool:
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    def scroll(self, down: bool) -> bool:
        top = max(0, min(self.top + (1 if down else -1), len(self.nets) - self.ROWS))
        if top == self.top:
            return False
        self.top = top
        return True

    # -- drawing ---------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        s = self.s
        W, P = self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        wifi = s.wifi
        y = 12
        if wifi.get("ssid"):
            pct = signal_pct(wifi)
            tone = signal_tone(pct)
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
        y += 8

        y = self.draw_list(cr, hits, P, y)
        y = self.draw_tailnet(cr, hits, P, y)

        rx = s.rx[-1] if s.rx else 0
        tx = s.tx[-1] if s.tx else 0
        heading(cr, P, y, "traffic", W - 2 * P - 150)
        text(cr, W - P - 70, y - 2, f"↓ {core.human_bytes(rx, True)}", 12, "blue", align=1)
        text(cr, W - P, y - 2, f"↑ {core.human_bytes(tx, True)}", 12, "purple", align=1)
        y += 20
        top = max([1.0, *s.rx, *s.tx]) * 1.1
        graph(cr, P, y, W - 2 * P, 44, [(list(s.rx), "blue"), (list(s.tx), "purple")], top=top, grid=())
        text(cr, P + 6, y + 4, f"{HISTORY // 60} min · peak {core.human_bytes(top / 1.1, True)}", 10, "dim")
        y += 56

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

    def draw_list(self, cr, hits: Hits, P: float, y: float) -> float:
        """The networks in range, from y. Returns the y under them."""
        W = self.W
        nets = self.nets
        w = self.s.nets
        end = y + self.list_h()
        scanning = time.monotonic() - w.scanned_at < 4
        label = "scanning" if scanning else "scan"
        bw = self.chip_w(cr, label, GLYPH_SCAN)
        button(cr, hits, W - P - bw, y - 5, label, self.rescan, h=20, size=11, glyph=GLYPH_SCAN, on=scanning,
               tone="bg3")
        cw = text(cr, W - P - bw - 8, y - 1, f"{len(nets)} in range", 11, "dim", align=1) + 8 if nets else 0
        heading(cr, P, y, "networks", W - 2 * P - bw - cw - 12)
        y += 22
        self.rows = []
        if not nets:
            text(cr, P + 4, y + 4, "looking for networks…" if self.s.want_link else "no networks", 12, "dim")
            return end
        self.top = max(0, min(self.top, len(nets) - self.ROWS))
        shown = nets[self.top:self.top + self.ROWS]
        for i, n in enumerate(shown, start=self.top):
            y0 = y
            self.draw_row(cr, hits, P, y, i, n)
            y += self.ROW_H
            if self.asking is not None and self.asking.ssid == n.ssid:
                self.draw_field(cr, hits, P, y)
                y += self.FIELD_H
            self.rows.append((y0, y, i))
        if self.asking is not None and all(self.asking.ssid != n.ssid for n in shown):
            # Its row scrolled away (or the network left): keep the field, at the end.
            self.draw_field(cr, hits, P, y)
            y += self.FIELD_H
        more = len(nets) - self.top - len(shown)
        if len(nets) > self.ROWS:
            words = f"▾ {more} more · scroll" if more else f"▴ {self.top} above"
            text(cr, W / 2, y + 1, words, 10, "dim", align=0.5)
        return end

    def draw_row(self, cr, hits: Hits, P: float, y: float, i: int, n: Network) -> None:
        W, H = self.W, self.ROW_H
        x0, rw, mid = P - 6, W - 2 * P + 12, y + H / 2
        picked = i == self.sel or i == self.hovered
        if n.active or picked:
            core.rrect(cr, x0, y + 1, rw, H - 2, 7)
            if n.active:
                cr.set_source_rgba(*core.rgba("accent", 0.20))
                cr.fill_preserve()
                cr.set_source_rgba(*core.rgba("accent", 0.55 if picked else 0.35))
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.set_source_rgba(*core.rgba("bg1"))
                cr.fill()
            if i == self.sel:  # the keyboard's mark: a bar at the left edge
                core.rrect(cr, x0 + 1, y + 6, 3, H - 12, 1.5)
                cr.set_source_rgba(*core.rgba("accent"))
                cr.fill()
        hits.add(x0, y, rw, H, lambda: self.join(n))

        tone = signal_tone(n.strength)
        x = P + bars(cr, P, mid, n.strength, tone) + 8

        # The right end first, so the name knows its room: the status, or the
        # buttons on a picked row, else security and signal.
        right = W - P
        status = self.s.nets.status.get(n.ssid)
        if picked and n.active:
            right -= button(cr, hits, right - self.chip_w(cr, "disconnect", GLYPH_OFF), y + 4, "disconnect",
                            lambda: self.s.nets.disconnect(n), h=H - 8, size=11, glyph=GLYPH_OFF) + 6
        elif picked and n.saved and not status:
            asking = self.forgetting == n.ssid
            label = "forget?" if asking else "forget"
            right -= button(cr, hits, right - self.chip_w(cr, label, GLYPH_FORGET), y + 4, label,
                            lambda: self.forget(n), h=H - 8, size=11, glyph=GLYPH_FORGET, on=asking,
                            tone="hit") + 6
        if status:
            tone_s, words = status
            if words in ("connecting", "authenticating", "disconnecting"):
                words += "." * (1 + int(time.monotonic()) % 3)
            right -= text(cr, right, mid, words, 11, tone_s, align=1, valign=0.5) + 8
        elif not picked or not (n.active or n.saved):
            right -= text(cr, right, mid, f"{n.strength}%", 11, "dim", align=1, valign=0.5) + 10
            sec = n.security
            right -= text(cr, right, mid, sec, 10, "dim", align=1, valign=0.5) + 4
            core.icon(cr, right, mid, GLYPH_OPEN if n.open else GLYPH_LOCK, 12, "dim" if not n.open else "warn",
                      align=1)
            right -= 22

        # The name, then its marks: saved, the bands.
        name_tone = "title" if (n.active or picked) else "fg2"
        marks_w = 18 * bool(n.saved and not n.active) + 22 * len(n.bands) + (20 if n.active else 0)
        room = max(40.0, right - x - marks_w - 8)
        x += text(cr, x, mid, n.ssid, 13, name_tone, bold=n.active, valign=0.5, width=room) + 8
        if n.active:
            core.icon(cr, x, mid, GLYPH_CHECK, 12, "accent")
            x += 18
        elif n.saved:
            core.icon(cr, x, mid, GLYPH_SAVED, 11, "blue")
            x += 16
        for b in sorted(n.bands, key=float):
            bw = core.text_w(cr, b, 9) + 8
            core.rrect(cr, x + 0.5, mid - 7.5, bw, 14, 4)
            cr.set_source_rgba(*core.rgba("bg2"))
            cr.set_line_width(1)
            cr.stroke()
            text(cr, x + 4.5, mid, b, 9, "dim", valign=0.5)
            x += bw + 4

    @staticmethod
    def chip_w(cr, label: str, glyph: str) -> float:
        return core.text_w(cr, label, 11) + core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 23

    def draw_field(self, cr, hits: Hits, P: float, y: float) -> None:
        """The password field under the asking row."""
        W, H = self.W, self.FIELD_H
        n = self.asking
        x0, fw = P + 22, W - 2 * P - 22
        fy, fh = y + 2, 24
        core.rrect(cr, x0 + 0.5, fy + 0.5, fw - 1, fh - 1, 6)
        cr.set_source_rgba(*core.rgba("bg1"))
        cr.fill_preserve()
        cr.set_source_rgba(*core.rgba("accent"))
        cr.set_line_width(1.2)
        cr.stroke()
        core.icon(cr, x0 + 9, fy + fh / 2, GLYPH_LOCK, 12, "accent")
        eye = GLYPH_EYE_OFF if self.reveal else GLYPH_EYE
        ex = x0 + fw - 24
        core.icon(cr, ex + 12, fy + fh / 2, eye, 13, "fg" if self.reveal else "dim", align=0.5)
        hits.add(ex, fy, 24, fh, lambda: setattr(self, "reveal", not self.reveal))
        hits.add(x0, fy, fw - 24, fh, lambda: None)  # a click in the field keeps it (and pins)
        tx = x0 + 28
        room = ex - tx - 6
        if self.buf:
            shown = self.buf if self.reveal else "●" * len(self.buf)
            # The end of a long password stays in sight, like a field scrolls.
            while len(shown) > 1 and core.text_w(cr, shown, 13) > room - 4:
                shown = shown[1:]
            tw = text(cr, tx, fy + fh / 2, shown, 13, "title", valign=0.5)
        else:
            text(cr, tx, fy + fh / 2, f"password for {n.ssid}" if n else "password", 12, "dim", valign=0.5,
                 width=room)
            tw = 0
        cr.rectangle(tx + tw + 1, fy + 5, 1.5, fh - 10)  # the caret
        cr.set_source_rgba(*core.rgba("accent"))
        cr.fill()
        hint = self.note or "Enter join · Tab show · Esc cancel"
        text(cr, x0 + 4, fy + fh + 1, hint, 10, "warn" if self.note else "dim")

    # -- the tailnet -----------------------------------------------------------

    def draw_tailnet(self, cr, hits: Hits, P: float, y: float) -> float:
        """This node, its peers and the exit node, from y. Returns the y under them."""
        W = self.W
        ts = self.s.ts
        end = y + self.ts_h()
        running = ts.state == "Running"
        right = W - P
        if running and any(p.online for p in ts.peers):
            busy = bool(ts._pinging)
            label = "pinging" if busy else "ping all"
            bw = core.text_w(cr, label, 11) + 18
            button(cr, hits, right - bw, y - 5, label, self.ping, h=20, size=11, on=busy, tone="bg3")
            right -= bw + 8
        if ts.tailnet:
            right -= text(cr, right, y - 1, ts.tailnet, 11, "dim", align=1) + 8
        heading(cr, P, y, "tailscale", right - P - 4)
        y += 22
        if not running:
            words = {"": ts.error or "tailscaled does not answer", "Stopped": "stopped (tailscale up)",
                     "NeedsLogin": "logged out (tailscale login)", "Starting": "starting…"}.get(
                ts.state, ts.state.lower())
            core.icon(cr, P + 8, y + self.TS_H / 2, GLYPH_TS, 13, "dim", align=0.5)
            text(cr, P + 22, y + self.TS_H / 2, words, 12, "dim", valign=0.5)
            return end
        if ts.me is not None:
            self.draw_peer(cr, hits, P, y, ME, ts.me)
            self.rows.append((y, y + self.TS_H, ME))
        y += self.TS_H
        n = len(self.nets)
        peers = self.peers
        for j, p in enumerate(peers):
            self.draw_peer(cr, hits, P, y, n + j, p)
            self.rows.append((y, y + self.TS_H, n + j))
            y += self.TS_H
        if not peers:
            text(cr, P + 22, y + self.TS_H / 2, "no other devices on the tailnet", 12, "dim", valign=0.5)
            y += self.TS_H
        rest = ts.peers[self.TS_ROWS:]
        if rest:
            off = sum(not p.online for p in rest)
            words = f"+ {len(rest)} more" + (f" ({off} offline)" if off else "")
            text(cr, W / 2, y + 1, words, 10, "dim", align=0.5)
            y += 14
        if ts.exit_options or ts.exit_status:
            y += 4
            text(cr, P, y + 11, "exit node", 12, "fg", valign=0.5)
            x = P + 76
            tone = "accent" if ts.operator else "bg3"
            for label, peer, on in [("none", None, not ts.exit_status)] + [
                    (p.name, p, p.exit_node) for p in ts.exit_options]:
                bw = core.text_w(cr, label, 11) + 18
                if x + bw > W - P:
                    break
                x += button(cr, hits, x, y, label, lambda p=peer: self.exit_node(p), h=22, size=11, on=on,
                            tone=tone) + 6
            y += 26
            if not ts.operator:
                text(cr, P, y, f"setting it needs operator rights: sudo tailscale set --operator={tailnet.USER}",
                     10, "warn" if self.exit_asked else "dim")
                y += 14
        if ts.error:
            text(cr, P, y, ts.error, 10, "warn", width=W - 2 * P)
        return end

    def draw_peer(self, cr, hits: Hits, P: float, y: float, i: int, p: Peer) -> None:
        W, H = self.W, self.TS_H
        ts = self.s.ts
        x0, rw, mid = P - 6, W - 2 * P + 12, y + H / 2
        picked = i == self.sel or i == self.hovered
        if picked:
            core.rrect(cr, x0, y + 1, rw, H - 2, 7)
            cr.set_source_rgba(*core.rgba("bg1"))
            cr.fill()
            if i == self.sel:
                core.rrect(cr, x0 + 1, y + 5, 3, H - 10, 1.5)
                cr.set_source_rgba(*core.rgba("accent"))
                cr.fill()
        hits.add(x0, y, rw, H, lambda: self.copy_ip(p))

        tone = ("accent" if p.me else "aqua") if p.online else "bg3"
        core.icon(cr, P + 8, mid, p.glyph, 13, tone, align=0.5)
        ipx = P + 168
        x = P + 22
        name_tone = "title" if (picked or p.me) else ("fg2" if p.online else "dim")
        x += text(cr, x, mid, p.name, 13, name_tone, bold=p.me, valign=0.5, width=ipx - x - 8) + 6
        if p.me and x < ipx - 40:
            text(cr, x, mid, "this device", 10, "dim", valign=0.5)
        elif p.exit_node and x < ipx - 30:
            text(cr, x, mid, "exit", 10, "ok", valign=0.5)
        text(cr, ipx, mid, p.ip or "no IPv4", 12, "title" if picked else ("fg" if p.online else "dim"),
             valign=0.5)

        right = W - P
        ping = ts.pings.get(p.ip)
        if self.copied[0] == p.ip and p.ip and time.monotonic() - self.copied[1] < 2:
            label = "copied"
            right -= button(cr, hits, right - self.chip_w(cr, label, GLYPH_CHECK), y + 3, label,
                            lambda: self.copy_ip(p), h=H - 6, size=11, on=True, tone="ok",
                            glyph=GLYPH_CHECK) + 6
        elif picked and not p.me:
            if p.shell:
                bw = self.chip_w(cr, "ssh", GLYPH_SHELL)
                right -= button(cr, hits, right - bw, y + 3, "ssh", lambda: self.ssh(p), h=H - 6, size=11,
                                glyph=GLYPH_SHELL) + 6
            if p.online:
                bw = core.text_w(cr, "ping", 11) + 18
                right -= button(cr, hits, right - bw, y + 3, "ping", lambda: self.ping(p), h=H - 6,
                                size=11) + 6
            if ping:
                self.ping_words(cr, right - 2, mid, ping)
            return
        if p.me:
            words = f"home {p.relay}" if p.relay else "online"
            text(cr, right, mid, words, 11, "dim", align=1, valign=0.5)
            return
        if not p.online:
            words = f"offline · {core.ago(time.time() - p.seen)} ago" if p.seen else "offline"
            text(cr, right, mid, words, 11, "dim", align=1, valign=0.5)
            return
        if ping:
            right -= self.ping_words(cr, right, mid, ping) + 4
        via = ts.via.get(p.ip) or ("direct" if p.addr else (f"relay {p.relay}" if p.active and p.relay else ""))
        if via and ping:
            right -= text(cr, right, mid, "·", 11, "dim", align=1, valign=0.5) + 4
        if via:
            text(cr, right, mid, via, 11, "ok" if via == "direct" else "warn", align=1, valign=0.5)
        elif not ping:
            text(cr, right, mid, "idle", 11, "dim", align=1, valign=0.5)

    @staticmethod
    def ping_words(cr, right: float, mid: float, ping: tuple[str, str]) -> float:
        tone, words = ping
        if words == "pinging":
            words += "." * (1 + int(time.monotonic()) % 3)
        return text(cr, right, mid, words, 11, tone, align=1, valign=0.5)
