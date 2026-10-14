"""The wallpaper, chosen on purpose. The bar's wallpaper pill (the design on screen,
a pin mark when pinned; hover opens the panel, a click pins it), and also `bardeck
open wallpaper`, the palette's "Open Wallpaper", niri-screen-switch's "Wallpaper: choose…".

The pictures are ~/Pictures/wallpapers/<palette>-<mode>-N[-laptop|-wide|-uw][-gpt].png:
design N of a theme, in one version per screen shape. The panel shows the current
theme's designs, each in the version for the focused screen (as wallpaper-pick
would choose it), the one on screen outlined. A click (or Enter) PINS that design
for this theme: `wallpaper-pick --pin N` writes ~/.config/theme/wallpaper-pin and
applies it, and from then on a layout change shows the same design in the new
shape instead of a random one. "shuffle" (`s`) unpins and picks at random again.

Thumbnails: made once with PIL on a thread, cached in ~/.cache/bardeck/wallthumbs
(keyed by path, mtime and size), loaded with cairo's own PNG reader.
Keys: `j`/`;` (or ←/→) left/right, `i`/`o` (or ↓/↑) down/up, Enter pin, `s` shuffle.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import struct
import threading

import cairo

from . import core
from .core import Hits, button, rgba, text
from .deck import Panel
from .ws import niri

WALL_DIR = f"{core.REAL_HOME}/Pictures/wallpapers"
PIN_FILE = f"{core.REAL_HOME}/.config/theme/wallpaper-pin"
FEHBG = f"{core.REAL_HOME}/.fehbg"
PICK = f"{core.REAL_HOME}/bin/wallpaper-pick"
THUMBS = f"{core.REAL_HOME}/.cache/bardeck/wallthumbs"
THUMB_W = 480  # px: sharp at the full bar's zoom on a 2× screen

GLYPH_WALL, GLYPH_SHUFFLE, GLYPH_PIN, GLYPH_IMAGE = "\U000f021f", "\U000f049d", "\U000f0403", "\U000f02e9"


def png_aspect(path: str) -> float | None:
    """Width / height from the PNG header (IHDR): no decoding."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        w, h = struct.unpack(">II", head[16:24])
        return w / h if h else None
    except (OSError, struct.error):
        return None


def aspect_of(path: str) -> float | None:
    if path.endswith(".png"):
        return png_aspect(path)
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.width / img.height
    except Exception:
        return None


def theme() -> tuple[str, str]:
    """(mode, palette) from ~/.config/theme/state."""
    parts = core.read(core.THEME_STATE).split()
    return (parts[0], parts[1]) if len(parts) >= 2 else ("dark", "gruvbox")


def current_file() -> str:
    found = re.findall(r"/[^ ']+\.(?:png|jpg|jpeg)", core.read(FEHBG))
    return found[-1] if found else ""


def pin_of(palette: str, mode: str) -> str:
    for line in core.read(PIN_FILE).splitlines():
        p = line.split()
        if len(p) == 2 and p[0] == f"{palette}-{mode}":
            return p[1]
    return ""


def screen_aspect() -> float:
    f = niri("FocusedOutput")
    lg = (f or {}).get("logical") if isinstance(f, dict) else None
    if lg and lg.get("height"):
        return lg["width"] / lg["height"]
    return 16 / 9


def designs(palette: str, mode: str) -> dict[str, list[tuple[str, float]]]:
    """design number -> [(file, aspect)], for one theme."""
    out: dict[str, list[tuple[str, float]]] = {}
    pat = re.compile(rf"^{re.escape(palette)}-{re.escape(mode)}-(\d+)[-.]")
    for path in sorted(glob.glob(f"{WALL_DIR}/{palette}-{mode}-*")):
        m = pat.match(os.path.basename(path))
        if not m or not path.endswith((".png", ".jpg", ".jpeg")):
            continue
        a = aspect_of(path)
        if a:
            out.setdefault(m.group(1), []).append((path, a))
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def best(files: list[tuple[str, float]], aspect: float) -> str:
    """The version wallpaper-pick shows when the design is pinned: the closest
    shape (within its 0.06 tolerance), an original before a "-gpt" one."""
    d0 = min(abs(a - aspect) for _, a in files)
    group = [p for p, a in files if abs(a - aspect) <= d0 + 0.06]
    return next((p for p in group if "-gpt." not in p), group[0])


def shape(path: str) -> str:
    m = re.search(r"-(laptop|wide|uw)(-gpt)?\.", os.path.basename(path))
    if not m:
        return ""
    return {"laptop": "16:10", "wide": "16:9", "uw": "21:9"}[m.group(1)] + (" · extended" if m.group(2) else "")


class Thumbs:
    """Small PNGs of the wallpapers, made on a thread, read on the main loop."""

    def __init__(self, ready):
        self.ready = ready  # called (on the main loop) when a thumbnail lands
        self.surfaces: dict[str, cairo.ImageSurface | None] = {}
        self.lock = threading.Lock()
        self.queue: list[str] = []
        self.busy = False

    @staticmethod
    def file(path: str) -> str:
        try:
            st = os.stat(path)
        except OSError:
            return ""
        key = hashlib.sha1(repr((path, st.st_mtime, st.st_size, THUMB_W)).encode()).hexdigest()[:16]
        return f"{THUMBS}/{key}.png"

    def get(self, path: str):
        if path in self.surfaces:
            return self.surfaces[path]
        f = self.file(path)
        if f and os.path.exists(f):
            try:
                self.surfaces[path] = cairo.ImageSurface.create_from_png(f)
            except Exception:
                self.surfaces[path] = None
            return self.surfaces[path]
        self.want(path)
        return None

    def want(self, path: str) -> None:
        with self.lock:
            if path in self.queue:
                return
            self.queue.append(path)
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self._work, daemon=True, name="wallthumbs").start()

    def _work(self) -> None:
        from gi.repository import GLib
        from PIL import Image

        while True:
            with self.lock:
                if not self.queue:
                    self.busy = False
                    return
                path = self.queue.pop(0)
            out = self.file(path)
            try:
                os.makedirs(THUMBS, exist_ok=True)
                with Image.open(path) as img:
                    img = img.convert("RGB")
                    img.thumbnail((THUMB_W, THUMB_W), Image.LANCZOS)
                    img.save(f"{out}.tmp.png", compress_level=1)
                os.replace(f"{out}.tmp.png", out)
            except Exception as err:
                core.log(f"wallpaper thumb {path}: {err!r}")
                self.surfaces[path] = None
            GLib.idle_add(lambda: self.ready() or False)


class WallStrip:
    """The pill: a picture icon, the design on screen, and a pin when it is pinned.
    Hover: the panel; click: pinned open."""

    name = "wallpaper"

    @staticmethod
    def state() -> tuple[str, str, str]:
        mode, palette = theme()
        m = re.match(rf"{re.escape(palette)}-{re.escape(mode)}-(\d+)[-.]", os.path.basename(current_file()))
        return palette, m.group(1) if m else "", pin_of(palette, mode)

    def key(self, variant: str):
        return self.state()

    def draw(self, variant: str, scale: int):
        palette, design, pin = self.state()
        cv = core.StripCanvas(scale)
        cv.icon(GLYPH_WALL, "fg", 15, after=4 if design else 0)
        if design:
            cv.text(design, "fg2", 12)
        if pin:
            cv.gap(4)
            cv.icon(GLYPH_PIN, "accent", 12, after=0)
        return cv.finish()


class WallPanel(Panel):
    name = "wallpaper"
    live = 1.0  # the picture changes a moment after a click (wallpaper-pick runs apart)
    W = 640
    P = 16
    COLS = 3
    GAP = 10
    LABEL_H = 20

    def __init__(self):
        self.thumbs = Thumbs(self.redraw)
        self.sel = 0
        self.hovered = -1
        self.cells: list[tuple[float, float, float, float, int]] = []
        self.mode, self.palette = "dark", "gruvbox"
        self.aspect = 16 / 9
        self.items: list[tuple[str, str]] = []  # (design, file for this screen)
        self.applying = ""  # the design a click asked for, until ~/.fehbg shows it

    # -- state -----------------------------------------------------------------

    def opened(self) -> None:
        self.mode, self.palette = theme()
        self.aspect = screen_aspect()
        self.items = [(n, best(files, self.aspect)) for n, files in designs(self.palette, self.mode).items()]
        cur = self.current_design()
        self.sel = next((i for i, (n, _) in enumerate(self.items) if n == cur), 0)
        self.hovered, self.applying = -1, ""
        for _, path in self.items:  # queue every missing thumbnail at once
            self.thumbs.get(path)

    def current_design(self) -> str:
        m = re.match(rf"{re.escape(self.palette)}-{re.escape(self.mode)}-(\d+)[-.]",
                     os.path.basename(current_file()))
        return m.group(1) if m else ""

    def pin(self, design: str) -> bool:
        self.applying = design
        core.spawn([PICK, "--pin", design])
        return True

    def shuffle(self) -> bool:
        self.applying = "?"
        core.spawn([PICK, "--unpin"])
        return True

    # -- layout ----------------------------------------------------------------

    def cell_w(self) -> float:
        return (self.W - 2 * self.P - (self.COLS - 1) * self.GAP) / self.COLS

    def cell_h(self) -> float:
        return round(self.cell_w() / max(1.2, min(self.aspect, 2.6)))

    def rows(self) -> int:
        return max(1, -(-len(self.items) // self.COLS))

    def size(self):
        grid = self.rows() * (self.cell_h() + self.LABEL_H + self.GAP)
        return self.W, round(12 + 28 + 24 + grid + 44)

    # -- input -----------------------------------------------------------------

    def key(self, key: str, ctrl: bool) -> bool:
        n = len(self.items)
        step = {"j": -1, "Left": -1, "semicolon": 1, "Right": 1,
                "i": self.COLS, "Down": self.COLS, "o": -self.COLS, "Up": -self.COLS}.get(key)
        if step is not None and n:
            self.sel = max(0, min(n - 1, self.sel + step))
            return True
        if key in ("Return", "KP_Enter") and n:
            return self.pin(self.items[self.sel][0])
        if key == "s" and not ctrl:
            return self.shuffle()
        return False

    def hover(self, x: float, y: float) -> bool:
        idx = next((i for cx, cy, cw, ch, i in self.cells if cx <= x < cx + cw and cy <= y < cy + ch), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    # -- drawing ---------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        W, P = self.W, self.P
        H = self.size()[1]
        core.panel_frame(cr, W, H)
        y = 12
        core.icon(cr, P, y + 11, GLYPH_WALL, 20, "title")
        text(cr, P + 28, y, "Wallpaper", 18, "title", bold=True)
        pin = pin_of(self.palette, self.mode)
        cur = self.current_design()
        if self.applying and (self.applying == cur or self.applying == "?" and not pin):
            self.applying = ""
        sw = core.text_w(cr, "shuffle", 11) + core.text_w(cr, GLYPH_SHUFFLE, 13, family=core.ICON_FONT) + 23
        button(cr, hits, W - P - sw, y + 1, "shuffle", self.shuffle, glyph=GLYPH_SHUFFLE, size=11,
               on=not pin, tone="accent")
        y += 28
        how = f"design {pin} pinned: a new screen shape keeps it" if pin else "shuffle: a random design on every change"
        text(cr, P + 28, y, f"{self.mode} {self.palette} · {how}", 12, "dim", width=W - 2 * P - 28)
        y += 24

        self.cells = []
        if not self.items:
            msg = ("Windows 95 has no wallpaper" if self.palette == "win95"
                   else f"no {self.palette}-{self.mode}-N pictures in ~/Pictures/wallpapers")
            text(cr, W / 2, y + 30, msg, 12, "dim", align=0.5)
            return
        cw, ch = self.cell_w(), self.cell_h()
        for i, (design, path) in enumerate(self.items):
            col, row = i % self.COLS, i // self.COLS
            x = P + col * (cw + self.GAP)
            cy = y + row * (ch + self.LABEL_H + self.GAP)
            self.draw_cell(cr, x, cy, cw, ch, i, design, path, design == cur, design == pin)
            self.cells.append((x, cy, cw, ch + self.LABEL_H, i))
            hits.add(x, cy, cw, ch + self.LABEL_H, lambda d=design: self.pin(d))
        text(cr, W / 2, H - 22, "click / Enter pin · s shuffle · j ; i o move · Esc close", 10, "dim", align=0.5)

    def draw_cell(self, cr, x, y, w, h, i, design, path, on_screen, pinned) -> None:
        picked = i == self.sel or i == self.hovered
        surf = self.thumbs.get(path)
        cr.save()
        core.rrect(cr, x, y, w, h, 6)
        cr.clip()
        if surf is not None and surf.get_width() and surf.get_height():
            # Cover the cell, centred: as swaybg's "fill" shows it.
            k = max(w / surf.get_width(), h / surf.get_height())
            cr.translate(x + (w - surf.get_width() * k) / 2, y + (h - surf.get_height() * k) / 2)
            cr.scale(k, k)
            cr.set_source_surface(surf, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
        else:
            cr.set_source_rgba(*rgba("bg1"))
            cr.paint()
            core.icon(cr, x + w / 2, y + h / 2, GLYPH_IMAGE, 22, "dim", align=0.5)
        cr.restore()
        if not picked and not on_screen:
            core.rrect(cr, x, y, w, h, 6)  # dim the others a little: the current one reads first
            cr.set_source_rgba(*rgba("bg", 0.18))
            cr.fill()
        ring = "accent" if on_screen else ("fg2" if picked else "bg2")
        core.rrect(cr, x + 1, y + 1, w - 2, h - 2, 6)
        cr.set_source_rgba(*rgba(ring))
        cr.set_line_width(3 if on_screen else (2 if picked else 1))
        cr.stroke()
        if i == self.sel:  # the keyboard's mark: a bar under the picture
            core.rrect(cr, x + w / 2 - 14, y + h + 3, 28, 3, 1.5)
            cr.set_source_rgba(*rgba("accent"))
            cr.fill()
        ly = y + h + 4
        label = f"{design}" + (" · on screen" if on_screen else "")
        if self.applying == design:
            label = f"{design} · applying…"
        tx = x + 2 + text(cr, x + 2, ly, label, 11, "title" if on_screen or picked else "fg2", bold=on_screen)
        if pinned:
            core.icon(cr, tx + 6, ly + 8, GLYPH_PIN, 11, "accent")
        text(cr, x + w - 2, ly, shape(path), 10, "dim", align=1)
