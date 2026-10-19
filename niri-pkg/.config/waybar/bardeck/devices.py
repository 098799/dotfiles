"""Devices: Bluetooth and the known devices (headphones, keyboard, mouse) on the strip;
in the panel every device BlueZ knows, scan / pair / connect like bluetoothctl,
Bluetooth power, and where sound goes.

The strip's devices are the ones the i3blocks scripts know (MAC and NAME in bt-*.sh).
The panel's list comes from BlueZ (bluez.py): click a paired device to connect it, a
new one (found by a scan) to pair, trust and connect it; hover a row for disconnect
and forget. Pairing asks for, or shows, a code in the device's row. The Bluetooth
buttons run bluetooth.sh's menu."""

from __future__ import annotations

import time

from . import core
from .bluez import BtDevice
from .core import Hits, button, heading, rgba, text
from .deck import Panel
from .net import bars, signal_tone
from .sample import Sampler

# BlueZ's Icon property -> a Nerd Font glyph.
TYPE_GLYPH = {
    "audio-headphones": "\U000f02cb", "audio-headset": "\U000f02ce", "audio-card": "\U000f04c3",
    "audio-speakers": "\U000f04c3", "input-gaming": "\U000f0297", "input-keyboard": "\U000f030c",
    "input-mouse": "\U000f037d", "input-tablet": "\U000f04f6", "phone": "\U000f011c",
    "computer": "\U000f0322", "video-display": "\U000f0379", "camera-photo": "\U000f0100",
    "camera-video": "\U000f0100", "printer": "\U000f042a",
}
GLYPH_BT = "\U000f00af"
GLYPH_SCAN, GLYPH_OFF, GLYPH_FORGET = "\U000f0450", "\U000f00b2", "\U000f01b4"
GLYPH_PAIRED, GLYPH_TRUSTED, GLYPH_CHECK = "\U000f0337", "\U000f0565", ""
GLYPH_KEY, GLYPH_DIAL, GLYPH_YES, GLYPH_NO = "\U000f0306", "\U000f061c", "\U000f012c", "\U000f0156"
GLYPH_EYE, GLYPH_EYE_OFF = "", ""


def bt_tone(s: Sampler) -> tuple[str, str]:
    if not s.bt_powered:
        return "\U000f00b2", "dim"
    if s.bt_connected:
        return "\U000f00b1", "blue"
    return GLYPH_BT, "fg"


class DevStrip:
    name = "dev"

    def __init__(self, s: Sampler):
        self.s = s

    def key(self, variant: str):
        s = self.s
        return (s.bt_powered, tuple(sorted(s.bt_connected)), tuple(sorted(s.bt_battery.items())))

    def draw(self, variant: str, scale: int):
        s = self.s
        c = core.StripCanvas(scale)
        glyph, tone = bt_tone(s)
        c.icon(glyph, tone, 15, after=6)
        for d in s.devices:
            on = d.mac in s.bt_connected
            c.icon(d.glyph, "title" if on else "bg3", 15, after=5)
            pct = s.bt_battery.get(d.mac)
            if on and pct is not None and variant == "full":
                tone = core.level(100 - pct, 70, 85)  # yellow under 30%, red under 15%
                c.cr.arc(c.x - 2, core.MID + 7, 1.8, 0, 6.3)
                c.cr.set_source_rgba(*rgba(tone))
                c.cr.fill()
        c.gap(-5)
        return c.finish()


class DevPanel(Panel):
    """Bluetooth power, then the devices: a list like bluetoothctl's `devices`, to
    connect, pair, disconnect and forget from. Click a row (or `i`/`o` and Enter when
    pinned). While a pairing runs the panel holds the keyboard: a code to type goes
    into the row's field, Enter answers, Esc cancels the pairing."""

    name = "dev"
    live = 1.0
    W = 470
    ROWS = 7      # rows shown; the list scrolls (wheel, keys) past that
    ROW_H = 26
    FIELD_H = 42

    def __init__(self, s: Sampler):
        self.s = s
        self.sel = -1          # the keyboard's row (-1: none yet)
        self.top = 0           # the first row shown
        self.hovered = -1
        self.unnamed = False   # show the found devices that send no name
        self.buf = ""          # the PIN or passkey typed
        self.reveal = True
        self.note = ""         # a word under the field (digits only, …)
        self.forgetting = ""   # a device whose forget button asks to be clicked again
        self.rows: list[tuple[float, float, int]] = []  # (y0, y1, index), for hover

    # -- state -----------------------------------------------------------------

    @property
    def bt(self):
        return self.s.bt

    @property
    def devs(self) -> list[BtDevice]:
        return self.bt.devices(self.unnamed)

    @property
    def typing(self) -> bool:  # Panel.typing: a pairing has the keyboard (codes, Esc)
        return bool(self.bt.pairing)

    def list_h(self, n: int | None = None) -> float:
        n = len(self.devs) if n is None else n
        h = 22 + max(1, min(self.ROWS, n)) * self.ROW_H + 8
        if n > self.ROWS or self.bt.unnamed_count():
            h += 16  # "n more", "n unnamed" under the list
        if self.bt.request is not None:
            h += self.FIELD_H
        return h

    def size(self):
        n_audio = len(self.s.sinks) + len(self.s.sources)
        return self.W, 52 + self.list_h() + 28 + 22 * max(1, n_audio) + 36

    def opened(self) -> None:
        self.s.want_audio = True
        self.bt.open()
        self.bt.settle()
        self.sel, self.top, self.hovered, self.forgetting = -1, 0, -1, ""
        self.buf, self.note = "", ""
        self.s.poke()

    def closed(self) -> None:
        self.s.want_audio = False
        self.bt.close()
        self.buf, self.note = "", ""

    def follow(self) -> None:
        """Scroll so the selection shows."""
        n = len(self.devs)
        self.top = max(0, min(self.top, n - self.ROWS))
        if 0 <= self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.ROWS:
            self.top = self.sel - self.ROWS + 1

    # -- actions ---------------------------------------------------------------

    def activate(self, d: BtDevice) -> bool:
        self.forgetting = ""
        if not d.paired:
            self.buf, self.note = "", ""
        self.bt.activate(d)
        return False

    def forget(self, d: BtDevice) -> bool:
        if self.forgetting != d.path:
            self.forgetting = d.path  # the button turns red: a second click forgets
            return False
        self.forgetting = ""
        self.bt.forget(d)
        return False

    def scan(self) -> bool:
        self.bt.scan()
        return False

    def toggle_unnamed(self) -> bool:
        self.unnamed = not self.unnamed
        return False

    def submit(self) -> None:
        r = self.bt.request
        if r is None:
            return
        if r.kind in ("pin", "passkey"):
            if not self.bt.answer(self.buf):
                self.note = "6 digits, up to 999999" if r.kind == "passkey" else "a PIN has 1 to 16 characters"
                return
            self.buf, self.note = "", ""
        elif r.kind == "confirm":
            self.bt.answer()

    def reject(self) -> bool:
        self.bt.drop_request("org.bluez.Error.Rejected")
        return False

    def confirm(self) -> bool:
        self.bt.answer()
        return False

    # -- input -----------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool:
        devs = self.devs
        n = len(devs)
        cur = devs[self.sel] if 0 <= self.sel < n else None
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key in ("k", "Page_Down") or (ctrl and key == "v"):
            self.sel = min(n - 1, self.sel + self.ROWS // 2)
        elif key in ("l", "Page_Up"):
            self.sel = max(0, self.sel - self.ROWS // 2)
        elif key in ("Return", "KP_Enter") and cur is not None:
            self.activate(cur)
        elif key == "r":
            self.scan()
        elif key == "a":
            self.toggle_unnamed()
        elif key == "d" and cur is not None and cur.connected:
            self.bt.disconnect(cur)
        elif key in ("Delete", "x") and cur is not None and cur.paired:
            self.forget(cur)
        else:
            return False
        self.follow()
        return True

    def text_key(self, key: str, char: str, ctrl: bool, alt: bool) -> bool:
        """A pairing runs: answer its question, or Esc to cancel it."""
        r = self.bt.request
        if key == "Escape" or (ctrl and key == "g"):
            self.bt.cancel_pairing()
            self.buf, self.note = "", ""
        elif r is None or r.kind == "show":
            return False
        elif r.kind == "confirm":
            if key in ("Return", "KP_Enter", "y"):
                self.confirm()
            elif key == "n":
                self.reject()
            else:
                return False
        elif key in ("Return", "KP_Enter"):
            self.submit()
        elif key == "BackSpace":
            self.buf = "" if ctrl else self.buf[:-1]
        elif ctrl and key == "u":
            self.buf = ""
        elif key in ("Tab", "ISO_Left_Tab"):
            self.reveal = not self.reveal
        elif char and not ctrl:
            if r.kind == "passkey" and (not char.isdigit() or len(self.buf) >= 6):
                self.note = "the passkey is 6 digits"
            elif len(self.buf) < 16:
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
        top = max(0, min(self.top + (1 if down else -1), len(self.devs) - self.ROWS))
        if top == self.top:
            return False
        self.top = top
        return True

    # -- drawing ---------------------------------------------------------------

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

        y = self.draw_list(cr, hits, P, y)

        heading(cr, P, y, "sound goes to", W - 2 * P)
        y += 20
        if not s.sinks and not s.sources:
            text(cr, P, y, "reading…", 12, "dim")
            y += 22
        for kind, items, default in (("out", s.sinks, s.default_sink), ("in", s.sources, s.default_source)):
            for item in items:
                cur = item["name"] == default
                core.icon(cr, P + 2, y + 9, ("\U000f04c3" if kind == "out" else "\U000f036c"), 14,
                          "ok" if cur else "dim")
                text(cr, P + 24, y + 2, item["desc"], 12, "title" if cur else "fg", bold=cur, width=W - 2 * P - 40)
                cmd = "set-default-sink" if kind == "out" else "set-default-source"
                hits.add(P, y, W - 2 * P, 20, lambda n=item["name"], cmd=cmd:
                         core.spawn(["pactl", cmd, n]) or self.s.poke())
                y += 22
        y += 8
        x = P
        for label, glyph, action in (
            ("mixer", "\U000f057e", lambda: core.spawn(["pavucontrol"]) or True),
            ("bluetoothctl", GLYPH_BT, lambda: core.menu_action("bluetooth.sh", 3, "bluetoothctl") or True),
            ("restart logid", "\U000f037d", lambda: core.menu_action("bluetooth.sh", 3, "restart logid") or True),
            ("nuke bt", "\U000f068c", lambda: core.menu_action("bluetooth.sh", 3, "nuke_bt") or True),
        ):
            x += button(cr, hits, x, y, label, action, glyph=glyph) + 8

    def draw_list(self, cr, hits: Hits, P: float, y: float) -> float:
        """The devices, from y. Returns the y under them."""
        W = self.W
        bt = self.bt
        devs = self.devs
        end = y + self.list_h(len(devs))
        right = W - P
        if self.s.bt_powered:
            left = bt.scan_until - time.monotonic()
            label = f"scanning {max(0, int(left))}s" if bt.scan_until else (
                "scanning" if bt.discovering else "scan")
            bw = self.chip_w(cr, label, GLYPH_SCAN)
            button(cr, hits, right - bw, y - 5, label, self.scan, h=20, size=11, glyph=GLYPH_SCAN,
                   on=bool(bt.scan_until or bt.discovering), tone="blue")
            right -= bw + 8
        found = sum(1 for d in devs if not d.paired and d.rssi is not None)
        if found:
            right -= text(cr, right, y - 1, f"{found} found", 11, "dim", align=1) + 8
        heading(cr, P, y, "devices", right - P - 4)
        y += 22
        self.rows = []
        if not devs:
            words = ("reading…" if bt.objs == {} else
                     "no devices: scan, with the device in pairing mode" if self.s.bt_powered else
                     "Bluetooth is off")
            text(cr, P + 4, y + 4, words, 12, "dim")
            return end
        req = bt.request
        asked = next((i for i, d in enumerate(devs) if req is not None and d.path == req.path), -1)
        if asked >= 0 and not self.top <= asked < self.top + self.ROWS:
            self.top = asked - self.ROWS + 1 if asked >= self.top + self.ROWS else asked  # the question shows
        self.top = max(0, min(self.top, len(devs) - self.ROWS))
        shown = devs[self.top:self.top + self.ROWS]
        for i, d in enumerate(shown, start=self.top):
            y0 = y
            self.draw_row(cr, hits, P, y, i, d)
            y += self.ROW_H
            if req is not None and req.path == d.path:
                self.draw_prompt(cr, hits, P, y, d)
                y += self.FIELD_H
            self.rows.append((y0, y, i))
        if req is not None and all(req.path != d.path for d in shown):
            # Its row scrolled away: keep the question, at the end.
            d = next((x for x in devs if x.path == req.path), None)
            self.draw_prompt(cr, hits, P, y, d)
            y += self.FIELD_H
        y += 2
        more = len(devs) - self.top - len(shown)
        if len(devs) > self.ROWS:
            words = f"▾ {more} more · scroll" if more else f"▴ {self.top} above"
            text(cr, W - P, y, words, 10, "dim", align=1)
        n_unnamed = bt.unnamed_count()
        if n_unnamed:
            label = f"{GLYPH_EYE_OFF}  hide {n_unnamed} unnamed" if self.unnamed else \
                f"{GLYPH_EYE}  show {n_unnamed} unnamed"
            tw = text(cr, P + 4, y, label, 10, "fg")
            hits.add(P, y - 2, tw + 8, 16, self.toggle_unnamed)
        return end

    def draw_row(self, cr, hits: Hits, P: float, y: float, i: int, d: BtDevice) -> None:
        W, H = self.W, self.ROW_H
        x0, rw, mid = P - 6, W - 2 * P + 12, y + H / 2
        picked = i == self.sel or i == self.hovered
        if d.connected or picked:
            core.rrect(cr, x0, y + 1, rw, H - 2, 7)
            if d.connected:
                cr.set_source_rgba(*rgba("accent", 0.20))
                cr.fill_preserve()
                cr.set_source_rgba(*rgba("accent", 0.55 if picked else 0.35))
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.set_source_rgba(*rgba("bg1"))
                cr.fill()
            if i == self.sel:  # the keyboard's mark: a bar at the left edge
                core.rrect(cr, x0 + 1, y + 6, 3, H - 12, 1.5)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
        hits.add(x0, y, rw, H, lambda: self.activate(d))

        lit = d.connected or picked
        core.icon(cr, P + 9, mid, TYPE_GLYPH.get(d.icon, GLYPH_BT), 15,
                  "title" if lit else ("fg" if d.paired else "dim"), align=0.5)
        x = P + 26

        # The right end first, so the name knows its room: the status, or the
        # buttons on a picked row, else battery and signal.
        right = W - P
        status = self.bt.status.get(d.path)
        chips = picked and not status and d.path != self.bt.pairing
        if chips and d.paired:
            asking = self.forgetting == d.path
            label = "forget?" if asking else "forget"
            right -= button(cr, hits, right - self.chip_w(cr, label, GLYPH_FORGET), y + 4, label,
                            lambda: self.forget(d), h=H - 8, size=11, glyph=GLYPH_FORGET, on=asking,
                            tone="hit") + 6
        if chips and d.connected:
            right -= button(cr, hits, right - self.chip_w(cr, "disconnect", GLYPH_OFF), y + 4, "disconnect",
                            lambda: self.bt.disconnect(d), h=H - 8, size=11, glyph=GLYPH_OFF) + 6
        if status:
            tone_s, words = status
            if tone_s == "warn" and words != "busy":
                words += "." * (1 + int(time.monotonic()) % 3)
            right -= text(cr, right, mid, words, 11, tone_s, align=1, valign=0.5,
                          width=W / 2 - P) + 8
        elif not (chips and d.paired):
            if d.signal is not None:
                right -= text(cr, right, mid, f"{d.rssi} dBm", 10, "dim", align=1, valign=0.5) + 6
                right -= 18
                bars(cr, right, mid, d.signal, signal_tone(d.signal))
                right -= 10
            if not d.paired and not chips:
                right -= text(cr, right, mid, "new", 10, "aqua", align=1, valign=0.5) + 8
        if d.battery is not None and not (chips and d.paired):
            tone_b = core.level(100 - d.battery, 70, 85)
            right -= text(cr, right, mid, f"{d.battery}%", 11, tone_b, align=1, valign=0.5) + 2
            right -= core.icon(cr, right, mid, battery_glyph(d.battery), 13, tone_b, align=1) + 10

        # The name, then its marks: connected, paired, trusted.
        marks = [(GLYPH_CHECK, 12, "accent")] if d.connected else []
        if d.paired:
            marks.append((GLYPH_PAIRED, 12, "blue"))
        if d.trusted:
            marks.append((GLYPH_TRUSTED, 11, "aqua" if d.paired else "dim"))
        name_tone = "title" if lit else ("fg2" if d.paired or d.named else "dim")
        room = max(40.0, right - x - 17 * len(marks) - 8)
        x += text(cr, x, mid, d.name, 13, name_tone, bold=d.connected, valign=0.5, width=room) + 8
        for glyph, size, tone_m in marks:
            core.icon(cr, x, mid, glyph, size, tone_m)
            x += 17

    @staticmethod
    def chip_w(cr, label: str, glyph: str) -> float:
        return core.text_w(cr, label, 11) + core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 23

    def draw_prompt(self, cr, hits: Hits, P: float, y: float, d: BtDevice | None) -> None:
        """The pairing's question under the device's row: a field for the PIN or
        passkey, the passkey to confirm, or the code to type on the device."""
        W = self.W
        r = self.bt.request
        name = d.name if d is not None else "the device"
        x0, fw = P + 22, W - 2 * P - 22
        fy, fh = y + 2, 24
        core.rrect(cr, x0 + 0.5, fy + 0.5, fw - 1, fh - 1, 6)
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("accent"))
        cr.set_line_width(1.2)
        cr.stroke()
        mid = fy + fh / 2
        hits.add(x0, fy, fw, fh, lambda: None)  # a click on the question keeps the panel (and pins)
        tx = x0 + 28
        if r.kind in ("pin", "passkey"):
            core.icon(cr, x0 + 9, mid, GLYPH_KEY if r.kind == "pin" else GLYPH_DIAL, 12, "accent")
            eye = GLYPH_EYE_OFF if self.reveal else GLYPH_EYE
            ex = x0 + fw - 24
            core.icon(cr, ex + 12, mid, eye, 13, "fg" if self.reveal else "dim", align=0.5)
            hits.add(ex, fy, 24, fh, lambda: setattr(self, "reveal", not self.reveal))
            room = ex - tx - 6
            if self.buf:
                shown = self.buf if self.reveal else "●" * len(self.buf)
                tw = text(cr, tx, mid, shown, 13, "title", valign=0.5)
            else:
                what = f"PIN for {name}" if r.kind == "pin" else f"the passkey {name} shows"
                text(cr, tx, mid, what, 12, "dim", valign=0.5, width=room)
                tw = 0
            cr.rectangle(tx + tw + 1, fy + 5, 1.5, fh - 10)  # the caret
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
            hint = self.note or "Enter pair · Tab hide · Esc cancel"
        elif r.kind == "confirm":
            core.icon(cr, x0 + 9, mid, GLYPH_DIAL, 12, "accent")
            cw = text(cr, tx, mid, spaced(r.code), 15, "title", bold=True, valign=0.5)
            right = x0 + fw - 3
            right -= button(cr, hits, right - self.chip_w(cr, "confirm", GLYPH_YES), fy + 3, "confirm",
                            self.confirm, h=fh - 6, size=11, glyph=GLYPH_YES, on=True, tone="ok") + 6
            right -= button(cr, hits, right - self.chip_w(cr, "reject", GLYPH_NO), fy + 3, "reject",
                            self.reject, h=fh - 6, size=11, glyph=GLYPH_NO) + 6
            text(cr, tx + cw + 10, mid, f"the same on {name}?", 11, "fg", valign=0.5,
                 width=max(30.0, right - tx - cw - 16))
            hint = "Enter / y confirm · n reject · Esc cancel"
        else:  # "show": type it on the device
            core.icon(cr, x0 + 9, mid, GLYPH_KEY, 12, "accent")
            tw = text(cr, tx, mid, "type", 11, "dim", valign=0.5) + 8
            tw += text(cr, tx + tw, mid, spaced(r.code), 15, "title", bold=True, valign=0.5) + 8
            right = x0 + fw - 10
            if r.code.isdigit() and len(r.code) == 6:  # a passkey: dots for the keys typed so far
                for k in range(6):
                    cr.new_sub_path()
                    cr.arc(right - (5 - k) * 9 - 3, mid, 3, 0, 6.3)
                    cr.set_source_rgba(*rgba("accent" if k < r.entered else "bg2"))
                    cr.fill()
                right -= 6 * 9 + 6
            text(cr, tx + tw, mid, f"on {name}, then Enter", 11, "fg", valign=0.5,
                 width=max(30.0, right - tx - tw))
            hint = "Esc cancel"
        text(cr, x0 + 4, fy + fh + 1, hint, 10, "warn" if self.note else "dim")


def spaced(code: str) -> str:
    """123456 as 123 456, for reading off a screen."""
    return f"{code[:3]} {code[3:]}" if code.isdigit() and len(code) == 6 else code


def battery_glyph(pct: int) -> str:
    """md-battery-10 … md-battery (U+F007A … U+F0082, then U+F0079 for full)."""
    if pct >= 95:
        return "\U000f0079"
    return chr(0xF007A + max(0, min(8, pct // 10 - 1)))
