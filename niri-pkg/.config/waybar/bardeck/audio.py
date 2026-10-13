"""Audio: the volume, the mic and what plays on the strip; in the panel pavucontrol,
drawn: the media player (cover, progress, buttons), every output and input with its
slider and mute, and every app's stream.

Reading: PulseAudio through one `pactl subscribe` and a debounced `pactl -f json list`
per event (pulse.py says why), the players over MPRIS on the session bus (mpris.py).
Both are events, not polling: the strip is drawn when they say something changed,
~30 ms after a volume key.

Strip: scroll = ±5% on the default output; middle click = mute (modules.jsonc);
left click pins the panel. Panel, pinned: `i`/`o` select a row, `k`/`l` half the
list, `u`/`p` volume −/+5% (on the media row: previous / next track), `m` mute,
Enter = make it the default (an output or input) / play-pause (the media row),
space = play / pause, `j`/`;` = the previous / next player. With no row selected,
`u`/`p`/`m` act on the default output."""

from __future__ import annotations

import math

import cairo

from . import core
from .core import Hits, button, heading, rgba, text
from .deck import Panel
from .mpris import Mpris, Player, fmt_time
from .pulse import Dev, Pulse

GLYPH_VOL = ("\U000f057f", "\U000f0580", "\U000f057e")  # low, medium, high
GLYPH_MUTED = "\U000f0581"
GLYPH_MIC, GLYPH_MIC_OFF = "\U000f036c", "\U000f036d"
GLYPH_NOTE, GLYPH_PLAY, GLYPH_PAUSE = "\U000f075a", "\U000f040a", "\U000f03e4"
GLYPH_PREV, GLYPH_NEXT, GLYPH_CHECK = "\U000f04ae", "\U000f04ad", "\uf00c"
STEP = 5


def vol_glyph(vol: int, mute: bool) -> str:
    if mute or vol == 0:
        return GLYPH_MUTED
    return GLYPH_VOL[0 if vol < 34 else (1 if vol < 67 else 2)]


def mute_glyph(d: Dev) -> str:
    if d.kind == "source":
        return GLYPH_MIC_OFF if d.mute else GLYPH_MIC
    return vol_glyph(d.vol, d.mute)


class Audio:
    """The two feeds, shared by the strip and the panel."""

    def __init__(self):
        self.pulse = Pulse()
        self.mpris = Mpris()
        self.watching = False

    def watch(self, changed) -> None:
        self.watching = True
        self.pulse.watch(changed)
        self.mpris.watch(changed)

    def ensure(self) -> None:
        """Without the feeds (a one-off render): read once, now."""
        if not self.watching and not self.pulse.read_once:
            self.pulse.read()
            try:
                self.mpris.scan(sync=True)
            except Exception as err:
                core.log(f"mpris: {err!r}")


class AudioStrip:
    name = "audio"
    TITLE_CHARS = 18  # the main bar is near full (README: ~2,250 of 2,548 px)

    def __init__(self, a: Audio):
        self.a = a

    def watch(self, changed) -> None:
        """Main loop (main.Daemon): follow PulseAudio and the players; `changed` redraws."""
        self.a.watch(changed)

    def scroll(self, up: bool) -> None:
        sink = self.a.pulse.sink()
        if sink is not None:
            self.a.pulse.step(sink, STEP if up else -STEP)

    def key(self, variant: str):
        a = self.a
        a.ensure()
        sink, src, p = a.pulse.sink(), a.pulse.source(), a.mpris.playing()
        return (sink and (sink.vol, sink.mute), src and src.mute,
                p and (p.title if variant == "full" else True))

    def draw(self, variant: str, scale: int):
        a = self.a
        a.ensure()
        c = core.StripCanvas(scale)
        sink, src = a.pulse.sink(), a.pulse.source()
        if sink is None:
            c.icon(GLYPH_MUTED, "dim", 15, after=3)
            c.text("no sound", "dim")
        else:
            c.icon(vol_glyph(sink.vol, sink.mute), "hit" if sink.mute else "title", 15, after=3)
            c.text(f"{sink.vol}%", "dim" if sink.mute else ("warn" if sink.vol > 100 else "title"))
        if src is not None:
            c.gap(8)
            c.icon(GLYPH_MIC_OFF if src.mute else GLYPH_MIC, "hit" if src.mute else "ok", 15, after=0)
        p = a.mpris.playing()
        if p is not None:
            c.gap(10)
            if variant == "full" and p.title:
                c.icon(GLYPH_NOTE, "accent", 13, after=3)
                title = p.title if len(p.title) <= self.TITLE_CHARS else p.title[:self.TITLE_CHARS - 1] + "…"
                c.text(title, "fg2", size=12)
            else:
                c.icon(GLYPH_PLAY, "accent", 14, after=0)
        return c.finish()


class AudioPanel(Panel):
    """The player on top, then OUTPUT, INPUT and APPS as rows: an icon, the name, a
    slider (click sets, the wheel steps) and a mute button. Click a device row to make
    it the default (an output takes the playing streams with it)."""

    name = "audio"
    W = 470
    P = 16
    ROW_H = 36
    MEDIA_H = 132
    SLIDER_W = 150

    def __init__(self, a: Audio):
        self.a = a
        self.sel = -1
        self.hovered = -1
        self.hx = self.hy = -1.0
        self.player = ""  # the shown player's bus name ("" = the first: playing first)
        self.rows: list[tuple[float, float, int]] = []  # (y0, y1, item index), for hover and scroll

    @property
    def live(self) -> float:  # the progress bar moves while something plays
        return 1.0 if self.current() is not None and self.current().playing else 0.0

    # -- state -----------------------------------------------------------------

    def players(self) -> list[Player]:
        return self.a.mpris.ordered()

    def current(self) -> Player | None:
        ps = self.players()
        return next((p for p in ps if p.name == self.player), ps[0] if ps else None)

    def items(self) -> list:
        """Every row the keyboard can select, top to bottom."""
        pl = self.a.pulse
        out: list = []
        p = self.current()
        if p is not None:
            out.append(p)
        return out + pl.sinks + pl.sources + pl.streams

    def size(self):
        self.a.ensure()
        pl = self.a.pulse
        h = 8
        if self.current() is not None:
            h += self.MEDIA_H + 8
        h += 26 + self.ROW_H * max(1, len(pl.sinks)) + 8
        h += 26 + self.ROW_H * max(1, len(pl.sources)) + 8
        h += 26 + (self.ROW_H * len(pl.streams) if pl.streams else 24) + 8
        return self.W, h

    def opened(self) -> None:
        self.sel, self.hovered, self.player = -1, -1, ""
        self.hx = self.hy = -1.0
        pl = self.a.pulse
        pl.want_streams = True
        pl.poke({"sink-input", "sink", "source", "server"})
        if self.a.watching:
            for p in self.players():
                self.a.mpris.read_position(p)

    def closed(self) -> None:
        self.a.pulse.want_streams = False

    # -- actions ---------------------------------------------------------------

    def target(self):
        """What u / p / m act on: the selected row, else the default output."""
        items = self.items()
        if 0 <= self.sel < len(items):
            return items[self.sel]
        return self.a.pulse.sink()

    def step(self, item, up: bool) -> None:
        if isinstance(item, Player):
            (self.a.mpris.next if up else self.a.mpris.previous)(item)
        elif isinstance(item, Dev):
            self.a.pulse.step(item, STEP if up else -STEP)

    def enter(self, item) -> None:
        if isinstance(item, Player):
            self.a.mpris.play_pause(item)
        elif isinstance(item, Dev) and item.kind in ("sink", "source"):
            self.a.pulse.make_default(item)

    def switch_player(self, delta: int) -> None:
        ps = self.players()
        if len(ps) < 2:
            return
        cur = self.current()
        i = ps.index(cur) if cur in ps else 0
        self.player = ps[(i + delta) % len(ps)].name

    def set_from_pointer(self, d: Dev, x0: float, w: float) -> bool:
        self.a.pulse.set_volume(d, round(max(0.0, min(1.0, (self.hx - x0) / w)) * 100))
        return False

    def seek_from_pointer(self, p: Player, x0: float, w: float) -> bool:
        self.a.mpris.seek_to(p, (self.hx - x0) / w)
        return False

    # -- input -----------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool:
        items = self.items()
        n = len(items)
        half = max(1, n // 2)
        if key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key in ("k", "Page_Down"):
            self.sel = min(n - 1, self.sel + half)
        elif key in ("l", "Page_Up"):
            self.sel = max(0, self.sel - half)
        elif key in ("u", "Left") or (ctrl and key == "b"):
            self.step(self.target(), up=False)
        elif key in ("p", "Right") or (ctrl and key == "f"):
            self.step(self.target(), up=True)
        elif key == "m":
            t = self.target()
            if isinstance(t, Dev):
                self.a.pulse.toggle_mute(t)
        elif key in ("Return", "KP_Enter") and 0 <= self.sel < n:
            self.enter(items[self.sel])
        elif key == "space":
            p = self.current()
            if p is not None:
                self.a.mpris.play_pause(p)
        elif key == "j":
            self.switch_player(-1)
        elif key == "semicolon":
            self.switch_player(1)
        else:
            return False
        return True

    def hover(self, x: float, y: float) -> bool:
        self.hx, self.hy = x, y
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    def scroll(self, down: bool) -> bool:
        items = self.items()
        if 0 <= self.hovered < len(items) and isinstance(items[self.hovered], Dev):
            self.a.pulse.step(items[self.hovered], -STEP if down else STEP)
            return True
        return False

    # -- drawing ---------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        self.a.ensure()
        W, P = self.W, self.P
        pl = self.a.pulse
        core.panel_frame(cr, W, self.size()[1])
        self.rows = []
        y = 8
        idx = 0
        p = self.current()
        if p is not None:
            self.draw_media(cr, hits, y, p, idx)
            idx += 1
            y += self.MEDIA_H + 8
        for title, devs, empty in (("output", pl.sinks, "no output"), ("input", pl.sources, "no input")):
            y += 6
            heading(cr, P, y, title, W - 2 * P)
            y += 20
            if not devs:
                text(cr, P + 4, y + 8, pl.error or empty, 12, "dim")
                y += self.ROW_H
            for d in devs:
                self.draw_row(cr, hits, y, idx, d)
                y += self.ROW_H
                idx += 1
            y += 8
        y += 6
        count = f"{len(pl.streams)} playing" if pl.streams else ""
        cw = text(cr, W - P, y - 1, count, 11, "dim", align=1) + 8 if count else 0
        heading(cr, P, y, "apps", W - 2 * P - cw)
        y += 20
        if not pl.streams:
            text(cr, P + 4, y + 3, "no app is playing sound", 12, "dim")
        for d in pl.streams:
            self.draw_row(cr, hits, y, idx, d)
            y += self.ROW_H
            idx += 1

    def mark(self, cr, x0: float, y: float, w: float, h: float, idx: int, *, default: bool = False) -> bool:
        """The row's background: the default's accent, the hover's and keyboard's
        highlight, and the keyboard's bar at the left edge. True = picked."""
        picked = idx == self.sel or idx == self.hovered
        if default or picked:
            core.rrect(cr, x0, y + 1, w, h - 2, 7)
            if default:
                cr.set_source_rgba(*rgba("accent", 0.20))
                cr.fill_preserve()
                cr.set_source_rgba(*rgba("accent", 0.55 if picked else 0.35))
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.set_source_rgba(*rgba("bg1"))
                cr.fill()
        if idx == self.sel:
            core.rrect(cr, x0 + 1, y + 7, 3, h - 14, 1.5)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
        return picked

    def draw_row(self, cr, hits: Hits, y: float, idx: int, d: Dev) -> None:
        W, P, H = self.W, self.P, self.ROW_H
        pl = self.a.pulse
        x0, rw, mid = P - 6, W - 2 * P + 12, y + H / 2
        default = (d.kind == "sink" and d.name == pl.default_sink) or (
            d.kind == "source" and d.name == pl.default_source)
        picked = self.mark(cr, x0, y, rw, H, idx, default=default)
        self.rows.append((y, y + H, idx))
        if d.kind in ("sink", "source"):
            hits.add(x0, y, rw, H, lambda: self.a.pulse.make_default(d) or False)
        else:
            hits.add(x0, y, rw, H, lambda: False)  # a click on a stream row only pins

        # Right to left: mute, the %, the slider; the name takes what is left.
        right = W - P
        mg = mute_glyph(d)
        core.icon(cr, right - 10, mid, mg, 16, "hit" if d.mute else ("title" if picked or default else "fg"),
                  align=0.5)
        hits.add(right - 22, y + 4, 24, H - 8, lambda: self.a.pulse.toggle_mute(d) or False)
        right -= 28
        tone = "dim" if d.mute else ("warn" if d.vol > 100 else "title")
        text(cr, right, mid, f"{d.vol}%", 12, tone, align=1, valign=0.5)
        right -= 42
        sx, sw = right - self.SLIDER_W, self.SLIDER_W
        slider(cr, sx, mid, sw, d.vol, d.mute, live=default or d.kind == "app")
        hits.add(sx - 6, y + 6, sw + 12, H - 12, lambda: self.set_from_pointer(d, sx, sw))

        gx = P + 2
        glyph_tone = "accent" if default else ("hit" if d.mute and d.kind == "app" else
                                               ("title" if picked else "fg"))
        core.icon(cr, gx + 9, mid, d.glyph, 17, glyph_tone, align=0.5)
        nx = P + 28
        room = sx - 14 - nx
        name_tone = "title" if default or picked else "fg2"
        name_w = text(cr, nx, y + 3, d.desc, 13, name_tone, bold=default,
                      width=room - (18 if default else 0))
        if default:
            core.icon(cr, nx + name_w + 6, y + 3 + 8, GLYPH_CHECK, 11, "accent")
        sub = d.sub
        if d.kind == "app":  # the short words first: the media name is the one cut short
            words = ["paused"] if d.corked else []
            if len(pl.sinks) > 1:
                words.append(f"→ {pl.sink_desc(d.sink) or '?'}")
            sub = " · ".join(words + ([d.sub] if d.sub else []))
        elif default:
            sub = " · ".join(w for w in ("default", d.sub) if w)
        if sub:
            text(cr, nx, y + 20, sub, 10, "dim", width=room)

    def draw_media(self, cr, hits: Hits, y: float, p: Player, idx: int) -> None:
        W, P = self.W, self.P
        H = self.MEDIA_H
        x0, cw = P - 6, W - 2 * P + 12
        # The card.
        core.rrect(cr, x0, y, cw, H, 9)
        cr.set_source_rgba(*rgba("bg1", 0.55))
        cr.fill()
        picked = idx == self.sel or idx == self.hovered
        if picked:
            core.rrect(cr, x0 + 0.5, y + 0.5, cw - 1, H - 1, 9)
            cr.set_source_rgba(*rgba("bg2"))
            cr.set_line_width(1)
            cr.stroke()
        if idx == self.sel:
            core.rrect(cr, x0 + 1, y + 10, 3, H - 20, 1.5)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
        self.rows.append((y, y + H, idx))
        hits.add(x0, y, cw, H, lambda: False)

        # The cover: a rounded square.
        S = 84
        cx, cy = P + 2, y + 10
        cover = self.a.mpris.art(p)
        cr.save()
        core.rrect(cr, cx, cy, S, S, 8)
        cr.clip()
        if cover is not None:
            k = S / cover.get_width()
            cr.translate(cx, cy)
            cr.scale(k, k)
            cr.set_source_surface(cover, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
        else:
            cr.rectangle(cx, cy, S, S)
            cr.set_source_rgba(*rgba("bg"))
            cr.fill()
            core.icon(cr, cx + S / 2, cy + S / 2, GLYPH_NOTE, 34, "dim", align=0.5)
        cr.restore()

        tx = cx + S + 14
        room = W - P - tx
        text(cr, tx, y + 10, p.title or "nothing playing", 15, "title" if p.title else "dim", bold=True,
             width=room)
        if p.artist:
            text(cr, tx, y + 32, p.artist, 12, "fg2", width=room)
        if p.album:
            text(cr, tx, y + 49, p.album, 11, "dim", width=room)

        # The buttons, under the words; the players on their right.
        by = y + 68
        bx = tx
        for glyph, action, ok, big in ((GLYPH_PREV, self.a.mpris.previous, p.can_prev, False),
                                       (GLYPH_PAUSE if p.playing else GLYPH_PLAY, self.a.mpris.play_pause,
                                        p.can_pause if p.playing else p.can_play, True),
                                       (GLYPH_NEXT, self.a.mpris.next, p.can_next, False)):
            d = 28 if big else 24
            round_button(cr, hits, bx, by + (28 - d) / 2, d, glyph, (lambda a=action: a(p) or False) if ok else None,
                         on=big)
            bx += d + 8
        players = self.players()
        if len(players) > 1:
            right = W - P
            for q in reversed(players):
                label = q.identity
                bw = core.text_w(cr, label, 11) + 18
                if right - bw < bx + 8:
                    break
                right -= bw
                button(cr, hits, right, by + 4, label, lambda q=q: setattr(self, "player", q.name) or False,
                       h=20, size=11, on=q is p, tone="fg", w=bw)
                if q.playing:  # a dot: this one plays
                    cr.new_path()
                    cr.arc(right + bw - 6, by + 8, 2.5, 0, 2 * math.pi)
                    cr.set_source_rgba(*rgba("accent"))
                    cr.fill()
                right -= 6
        else:
            status = {"Playing": "playing", "Paused": "paused"}.get(p.status, "stopped")
            text(cr, W - P, by + 14, f"{p.identity} · {status}", 11, "dim", align=1, valign=0.5)

        # The progress: elapsed, the bar (a click seeks), the length.
        py = y + H - 18
        now = p.now()
        left = fmt_time(now)
        lw = text(cr, P + 2, py, left, 11, "fg", valign=0.5)
        if p.length:
            total = fmt_time(p.length)
            rw_ = text(cr, W - P, py, total, 11, "dim", align=1, valign=0.5)
            bx0, bw = P + 2 + max(lw, 34) + 8, W - P - rw_ - 8 - (P + 2 + max(lw, 34) + 8)
            frac = now / p.length if p.length else 0
            core.bar(cr, bx0, py - 2, bw, 4, frac, "accent" if p.playing else "fg", track="bg2")
            kx = bx0 + bw * min(1.0, frac)
            cr.new_path()
            cr.arc(kx, py, 5, 0, 2 * math.pi)
            cr.set_source_rgba(*rgba("title" if p.playing else "fg"))
            cr.fill()
            if p.can_seek and p.track:
                hits.add(bx0 - 4, py - 8, bw + 8, 16, lambda: self.seek_from_pointer(p, bx0, bw))
        else:
            text(cr, W - P, py, "no length (a stream)", 11, "dim", align=1, valign=0.5)


def slider(cr, x: float, mid: float, w: float, vol: int, mute: bool, live: bool = True) -> None:
    """A volume track and its knob (at the end past 100%: the % next to it says how far)."""
    frac = min(1.0, vol / 100)
    tone = "bg3" if mute else ("accent" if live else "fg")
    core.bar(cr, x, mid - 2, w, 4, frac, tone, track="bg2")
    kx = x + w * frac
    cr.new_path()
    cr.arc(kx, mid, 6, 0, 2 * math.pi)
    cr.set_source_rgba(*rgba("bg"))
    cr.fill_preserve()
    cr.set_source_rgba(*rgba("dim" if mute else ("title" if live else "fg")))
    cr.set_line_width(2)
    cr.stroke()


def round_button(cr, hits: Hits, x: float, y: float, d: float, glyph: str, action, *, on: bool = False) -> None:
    """A round icon button; no action = greyed (the player cannot do it)."""
    cr.new_path()  # text leaves a current point: an arc would join it with a line
    cr.arc(x + d / 2, y + d / 2, d / 2 - 0.5, 0, 2 * math.pi)
    if on and action is not None:
        cr.set_source_rgba(*rgba("accent"))
        cr.fill()
        fg = "bg"
    else:
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("bg2"))
        cr.set_line_width(1)
        cr.stroke()
        fg = "title" if action is not None else "bg3"
    core.icon(cr, x + d / 2, y + d / 2, glyph, d * 0.55, fg, align=0.5)
    if action is not None:
        hits.add(x, y, d, d, action)
