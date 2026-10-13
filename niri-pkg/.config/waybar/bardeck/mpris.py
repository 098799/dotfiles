"""Media players over MPRIS (the session bus): what plays, its cover, and the buttons.

In-process, on the main loop, no program: every running `org.mpris.MediaPlayer2.*`
name (ListNames, never the activatable ones: a call to an activatable name would
start it). Players signal their own changes: PropertiesChanged and Seeked for the
players, NameOwnerChanged for players coming and going. A change costs one async
GetAll of that player. The position is not signalled (MPRIS says so): it is read
with the rest and then counted on locally while it plays.

playerctld is skipped: it mirrors the player that was last active, so it would show
that player twice.

Cover art (mpris:artUrl), only when the panel draws it: a file:// is read as it is
(Chromium writes one to /tmp); http(s) is fetched on a thread with urllib, once, into
$XDG_RUNTIME_DIR/bardeck/art/. Decoded in-process with Pillow (or cairo for a PNG),
not GdkPixbuf: here GdkPixbuf decodes through glycin, which starts a sandboxed loader
process that lingers ~30 s."""

from __future__ import annotations

import hashlib
import os
import threading
import time
import urllib.parse
import urllib.request

from . import core

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
ROOT = "org.mpris.MediaPlayer2"
SKIP = {"org.mpris.MediaPlayer2.playerctld"}
ART_DIR = f"{core.RUN_DIR}/art"
ART_PX = 256  # covers are kept this big, and drawn smaller
ART_KEEP = 64  # fetched covers kept on disk


class Player:
    __slots__ = ("name", "owner", "identity", "status", "title", "artist", "album", "art", "length",
                 "position", "pos_at", "rate", "can_next", "can_prev", "can_play", "can_pause", "can_seek",
                 "track")

    def __init__(self, name: str, owner: str = ""):
        self.name, self.owner = name, owner
        self.identity = name[len(PREFIX):].split(".")[0].capitalize()
        self.status = "Stopped"
        self.title = self.artist = self.album = self.art = self.track = ""
        self.length = 0  # µs; 0 = unknown (a stream)
        self.position = 0
        self.pos_at = time.monotonic()
        self.rate = 1.0
        self.can_next = self.can_prev = self.can_play = self.can_pause = self.can_seek = False

    @property
    def playing(self) -> bool:
        return self.status == "Playing"

    @property
    def shown(self) -> bool:
        """Worth a card: it plays, is paused, or has a title (Chromium keeps an empty one)."""
        return self.status in ("Playing", "Paused") or bool(self.title)

    def now(self) -> int:
        """The position now, in µs: the last reading, counted on while it plays."""
        pos = self.position
        if self.playing:
            pos += int((time.monotonic() - self.pos_at) * 1e6 * self.rate)
        return max(0, min(pos, self.length)) if self.length else max(0, pos)

    def take(self, props: dict) -> None:
        """Properties from GetAll or PropertiesChanged (unpacked)."""
        if "PlaybackStatus" in props:
            if self.playing:  # freeze the count where it stands
                self.position, self.pos_at = self.now(), time.monotonic()
            self.status = props["PlaybackStatus"] or "Stopped"
        if "Metadata" in props:
            md = props["Metadata"] or {}
            title = str(md.get("xesam:title") or "")
            if title != self.title or str(md.get("mpris:trackid") or "") != self.track:
                self.position, self.pos_at = 0, time.monotonic()
            self.title = title
            self.track = str(md.get("mpris:trackid") or "")
            artist = md.get("xesam:artist") or ""
            self.artist = ", ".join(artist) if isinstance(artist, (list, tuple)) else str(artist)
            self.album = str(md.get("xesam:album") or "")
            self.art = str(md.get("mpris:artUrl") or "")
            try:
                self.length = int(md.get("mpris:length") or 0)
            except (TypeError, ValueError):
                self.length = 0
        if "Position" in props:
            self.position, self.pos_at = int(props["Position"] or 0), time.monotonic()
        if "Rate" in props:
            self.rate = float(props["Rate"] or 1.0)
        for key, attr in (("CanGoNext", "can_next"), ("CanGoPrevious", "can_prev"), ("CanPlay", "can_play"),
                          ("CanPause", "can_pause"), ("CanSeek", "can_seek")):
            if key in props:
                setattr(self, attr, bool(props[key]))
        if props.get("Identity"):
            self.identity = str(props["Identity"])


def fmt_time(us: int) -> str:
    s = max(0, us // 1_000_000)
    h, rem = divmod(s, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


class Mpris:
    def __init__(self):
        self.players: dict[str, Player] = {}  # well-known name -> player
        self.owners: dict[str, str] = {}      # unique name (":1.42") -> well-known name
        self.changed = None
        self._bus = None
        self._art: dict[str, object] = {}     # artUrl -> cairo surface, or None (failed / loading)
        self._fetching: set[str] = set()

    # -- the bus ---------------------------------------------------------------

    def bus(self):
        if self._bus is None:
            from gi.repository import Gio

            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        return self._bus

    def _call(self, name, path, iface, method, args=None, reply=None, done=None, sync=False):
        from gi.repository import Gio, GLib

        params = GLib.Variant(*args) if args else None
        rtype = GLib.VariantType(reply) if reply else None
        if sync:
            return self.bus().call_sync(name, path, iface, method, params, rtype, Gio.DBusCallFlags.NO_AUTO_START,
                                        1000, None).unpack()

        def finish(bus, res):
            try:
                out = bus.call_finish(res).unpack()
            except Exception as err:  # the player left meanwhile, or does not answer
                if core.TRACE:
                    core.log(f"mpris {name} {method}: {err!r}")
                return
            if done is not None:
                done(out)

        self.bus().call(name, path, iface, method, params, rtype, Gio.DBusCallFlags.NO_AUTO_START, 1000, None,
                        finish)
        return None

    def scan(self, sync: bool = False) -> None:
        """Every running player (ListNames: running names only)."""
        names = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                           sync=True)[0]
        for name in names:
            if name.startswith(PREFIX) and name not in SKIP and name not in self.players:
                self.add(name, sync=sync)

    def add(self, name: str, owner: str = "", sync: bool = False) -> None:
        if not owner:
            try:
                owner = self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                   "GetNameOwner", ("(s)", (name,)), sync=True)[0]
            except Exception:
                return
        self.players[name] = Player(name, owner)
        self.owners[owner] = name
        self.refresh(name, sync=sync)

    def refresh(self, name: str, sync: bool = False) -> None:
        def got(iface):
            def take(out):
                p = self.players.get(name)
                if p is not None:
                    p.take(out[0])
                    self.notify()
            return take

        for iface in (PLAYER, ROOT):
            if sync:
                try:
                    got(iface)(self._call(name, PATH, "org.freedesktop.DBus.Properties", "GetAll",
                                          ("(s)", (iface,)), sync=True))
                except Exception:
                    pass
            else:
                self._call(name, PATH, "org.freedesktop.DBus.Properties", "GetAll", ("(s)", (iface,)),
                           done=got(iface))

    def read_position(self, p: Player) -> None:
        def take(out):
            p.take({"Position": out[0]})

        self._call(p.name, PATH, "org.freedesktop.DBus.Properties", "Get", ("(ss)", (PLAYER, "Position")),
                   done=take)

    def notify(self) -> None:
        if self.changed is not None:
            self.changed()

    def watch(self, changed) -> None:
        """On the main loop: follow the players. `changed` runs after every change."""
        from gi.repository import Gio

        self.changed = changed
        bus = self.bus()

        def props(_bus, sender, _path, _iface, _member, params):
            name = self.owners.get(sender)
            p = self.players.get(name) if name else None
            if p is None:
                return
            iface, changed_props, invalidated = params.unpack()
            p.take(changed_props)
            if invalidated or "Metadata" in changed_props:
                self.refresh(name)  # some players only invalidate, or drop the position
            if "PlaybackStatus" in changed_props and p.playing:
                self.read_position(p)  # resumed: maybe at another place
            self.notify()

        def seeked(_bus, sender, _path, _iface, _member, params):
            name = self.owners.get(sender)
            if name in self.players:
                self.players[name].take({"Position": params.unpack()[0]})
                self.notify()

        def owner(_bus, _sender, _path, _iface, _member, params):
            name, old, new = params.unpack()
            if not name.startswith(PREFIX) or name in SKIP:
                return
            if old:
                self.owners.pop(old, None)
                self.players.pop(name, None)
            if new:
                self.add(name, new)
            self.notify()

        bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", PATH, PLAYER,
                             Gio.DBusSignalFlags.NONE, props)
        bus.signal_subscribe(None, PLAYER, "Seeked", PATH, None, Gio.DBusSignalFlags.NONE, seeked)
        # Only names under org.mpris.MediaPlayer2: not every client of the session bus.
        bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                             "/org/freedesktop/DBus", ROOT, Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE, owner)
        try:
            self.scan()
        except Exception as err:
            core.log(f"mpris: {err!r}")

    # -- what to show ----------------------------------------------------------

    def ordered(self) -> list[Player]:
        """The players worth a card: playing first, then paused, then the rest."""
        rank = {"Playing": 0, "Paused": 1}
        return sorted((p for p in self.players.values() if p.shown),
                      key=lambda p: (rank.get(p.status, 2), p.identity.lower(), p.name))

    def playing(self) -> Player | None:
        return next((p for p in self.ordered() if p.playing), None)

    # -- acting ----------------------------------------------------------------

    def act(self, p: Player, method: str, args=None) -> None:
        self._call(p.name, PATH, PLAYER, method, args)

    def play_pause(self, p: Player) -> None:
        self.act(p, "PlayPause")

    def next(self, p: Player) -> None:
        self.act(p, "Next")

    def previous(self, p: Player) -> None:
        self.act(p, "Previous")

    def seek_to(self, p: Player, frac: float) -> None:
        """SetPosition: MPRIS wants the track id with it (a stale id is ignored)."""
        if not (p.can_seek and p.length and p.track):
            return
        pos = int(max(0.0, min(1.0, frac)) * p.length)
        self.act(p, "SetPosition", ("(ox)", (p.track, pos)))
        p.position, p.pos_at = pos, time.monotonic()

    # -- cover art ---------------------------------------------------------------

    def art(self, p: Player):
        """The cover as a cairo surface (ART_PX square), or None (none, or not here yet:
        a fetch then starts, and the panel is redrawn when it is in)."""
        url = p.art
        if not url:
            return None
        if url not in self._art and url not in self._fetching:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme == "file":
                self._art[url] = load_cover(urllib.parse.unquote(parsed.path))
            elif parsed.scheme in ("http", "https"):
                self._fetching.add(url)
                threading.Thread(target=self._fetch, args=(url,), daemon=True).start()
            if len(self._art) > 32:  # Chromium makes a new file per track: keep the last few
                for k in list(self._art)[:-16]:
                    del self._art[k]
        return self._art.get(url)

    def _fetch(self, url: str) -> None:
        from gi.repository import GLib

        path = f"{ART_DIR}/{hashlib.sha1(url.encode()).hexdigest()}"
        try:
            if not os.path.exists(path):
                os.makedirs(ART_DIR, exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": "bardeck"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = resp.read(8 << 20)
                with open(f"{path}.tmp", "wb") as fh:
                    fh.write(data)
                os.replace(f"{path}.tmp", path)
                old = sorted(os.scandir(ART_DIR), key=lambda e: e.stat().st_mtime)[:-ART_KEEP]
                for e in old:  # a tmpfs: keep the last ART_KEEP covers
                    os.unlink(e.path)
        except Exception as err:
            core.log(f"cover {url[:80]}: {err!r}")
            path = ""

        def done():
            self._fetching.discard(url)
            self._art[url] = load_cover(path) if path else None
            self.notify()
            return False

        GLib.idle_add(done)


def load_cover(path: str):
    """A picture file as an ART_PX-square cairo surface (the middle square), or None."""
    import cairo

    try:
        from PIL import Image
    except ImportError:
        Image = None
    try:
        with open(path, "rb") as fh:
            png = fh.read(8) == b"\x89PNG\r\n\x1a\n"
        if Image is not None:
            with Image.open(path) as im:
                im = im.convert("RGBA")
                side = min(im.size)
                if side <= 0:
                    return None
                left, top = (im.width - side) // 2, (im.height - side) // 2
                im = im.resize((ART_PX, ART_PX), Image.LANCZOS, box=(left, top, left + side, top + side))
                data = bytearray(im.tobytes("raw", "BGRa"))  # cairo's ARGB32: premultiplied, little-endian
            return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, ART_PX, ART_PX, ART_PX * 4)
        if not png:
            return None  # no Pillow: only what cairo reads itself
        src = cairo.ImageSurface.create_from_png(path)
    except Exception:
        return None
    w, h = src.get_width(), src.get_height()
    side = min(w, h)
    if side <= 0:
        return None
    k = ART_PX / side
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, ART_PX, ART_PX)
    cr = cairo.Context(surf)
    cr.scale(k, k)
    cr.set_source_surface(src, -(w - side) / 2, -(h - side) / 2)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint()
    return surf
