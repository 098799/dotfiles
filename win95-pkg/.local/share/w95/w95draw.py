"""Hand-drawn Win95 chrome that CSS can't express: the flag, the glyphs,
and the rotated "Windows95" banner down the side of the Start menu.

All of it is cairo on a DrawingArea — no image assets to go stale.
"""

import math

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, PangoCairo  # noqa: E402

FLAG = [(0xFF, 0x00, 0x00), (0x00, 0xA0, 0x00), (0x00, 0x00, 0xC0), (0xFF, 0xC0, 0x00)]


def _rgb(cr, c):
    cr.set_source_rgb(c[0] / 255, c[1] / 255, c[2] / 255)


class Flag(Gtk.DrawingArea):
    """The four-pane waving flag. Each quadrant is a quad whose right edge
    rides a sine wave, which is what sells it as cloth rather than a grid."""

    def __init__(self, size=16):
        super().__init__()
        self.size = size
        self.set_size_request(size + 2, size)
        self.connect("draw", self._draw)

    def _draw(self, _w, cr):
        s = self.size
        cr.save()
        cr.translate(1, (self.get_allocated_height() - s) / 2 + 1)
        k = s / 16.0

        def wave(x):
            """Vertical offset of the flag surface at horizontal position x."""
            return math.sin((x / s) * math.pi * 1.15 + 0.4) * 1.6 * k

        gap = 1.0 * k
        for i, col in enumerate(FLAG):
            cx, cy = i % 2, i // 2
            x0 = 1.5 * k + cx * (s * 0.46)
            x1 = x0 + s * 0.46 - gap
            y0 = 1.0 * k + cy * (s * 0.42)
            y1 = y0 + s * 0.42 - gap
            # Left edge rides the wave; right edge rides it a phase later.
            cr.move_to(x0, y0 + wave(x0))
            cr.line_to(x1, y0 + wave(x1))
            cr.line_to(x1, y1 + wave(x1))
            cr.line_to(x0, y1 + wave(x0))
            cr.close_path()
            _rgb(cr, col)
            cr.fill()
        cr.restore()
        return False


class Banner(Gtk.DrawingArea):
    """The navy gutter of the Start menu: 'Windows' light, '95' bold,
    rotated 90° counter-clockwise and bottom-aligned."""

    def __init__(self, width=26, size=16):
        super().__init__()
        self.size = size
        self.set_size_request(width, -1)
        self.connect("draw", self._draw)

    def _draw(self, w, cr):
        aw = w.get_allocated_width()
        ah = w.get_allocated_height()
        cr.set_source_rgb(0, 0, 0.5)
        cr.rectangle(0, 0, aw, ah)
        cr.fill()

        layout = PangoCairo.create_layout(cr)
        layout.set_markup(
            '<span font_desc="W95FA %d" foreground="#c0c0c0">Windows</span>'
            '<span font_desc="W95FA Bold %d" foreground="#ffffff">95</span>'
            % (self.size, self.size),
            -1,
        )
        _, th = layout.get_pixel_size()

        # After rotating -90°, the layout's height runs along +x and its width
        # runs upward from the origin. So the origin sits at the LEFT of the
        # strip and at the BOTTOM of the menu.
        cr.save()
        cr.translate((aw - th) / 2, ah - 6)
        cr.rotate(-math.pi / 2)
        PangoCairo.show_layout(cr, layout)
        cr.restore()
        return False


class Glyph(Gtk.DrawingArea):
    """Tiny 1-bit pictograms for menu rows and title-bar buttons, drawn at
    whatever size the row needs. Cheaper and sharper than shipping PNGs."""

    def __init__(self, kind, size=16):
        super().__init__()
        self.kind = kind
        self.size = size
        self.set_size_request(size, size)
        self.connect("draw", self._draw)

    def _draw(self, w, cr):
        s = self.size
        cr.translate(0, (w.get_allocated_height() - s) / 2)
        cr.set_line_width(1)
        k = s / 16.0
        cr.scale(k, k)
        getattr(self, "_" + self.kind, self._window)(cr)
        return False

    # -- folder-ish icons -------------------------------------------------
    def _folder(self, cr):
        cr.set_source_rgb(0.86, 0.71, 0.20)
        cr.move_to(1, 4); cr.line_to(6, 4); cr.line_to(7.5, 6)
        cr.line_to(14, 6); cr.line_to(14, 13); cr.line_to(1, 13)
        cr.close_path(); cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0); cr.stroke()

    def _doc(self, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(3.5, 2.5, 9, 11); cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0); cr.stroke()
        for y in (5, 7, 9, 11):
            cr.move_to(5, y + 0.5); cr.line_to(11, y + 0.5)
        cr.set_source_rgb(0.5, 0.5, 0.5); cr.stroke()

    def _gear(self, cr):
        cr.set_source_rgb(0.5, 0.5, 0.5)
        for i in range(8):
            a = i * math.pi / 4
            cr.save(); cr.translate(8, 8); cr.rotate(a)
            cr.rectangle(-1.5, -7.5, 3, 4); cr.fill(); cr.restore()
        cr.arc(8, 8, 4.5, 0, 2 * math.pi); cr.fill()
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.arc(8, 8, 2, 0, 2 * math.pi); cr.fill()

    def _find(self, cr):
        cr.set_source_rgb(0.2, 0.4, 0.8)
        cr.arc(7, 7, 4, 0, 2 * math.pi); cr.set_line_width(1.6); cr.stroke()
        cr.set_source_rgb(0, 0, 0)
        cr.move_to(10, 10); cr.line_to(14, 14); cr.set_line_width(2); cr.stroke()

    def _help(self, cr):
        cr.set_source_rgb(0, 0.3, 0.8)
        cr.rectangle(2.5, 1.5, 11, 13); cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0); cr.set_line_width(1); cr.stroke()
        layout = PangoCairo.create_layout(cr)
        layout.set_markup('<span font_desc="W95FA Bold 9" foreground="#ffffff">?</span>', -1)
        tw, _ = layout.get_pixel_size()
        cr.move_to(8 - tw / 2, 1)
        PangoCairo.show_layout(cr, layout)

    def _run(self, cr):
        cr.set_source_rgb(1, 1, 1); cr.rectangle(2.5, 4.5, 11, 8); cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0); cr.stroke()
        cr.move_to(4, 7); cr.line_to(6, 8.5); cr.line_to(4, 10); cr.stroke()
        cr.move_to(7, 10.5); cr.line_to(11, 10.5); cr.stroke()

    def _shutdown(self, cr):
        cr.set_source_rgb(0.85, 0.2, 0.1)
        cr.arc(8, 9, 5, -0.4 * math.pi, 1.4 * math.pi)
        cr.set_line_width(2); cr.stroke()
        cr.move_to(8, 2); cr.line_to(8, 8); cr.stroke()

    def _window(self, cr):
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.rectangle(2.5, 2.5, 11, 11); cr.fill_preserve()
        cr.set_source_rgb(0, 0, 0); cr.stroke()
        cr.set_source_rgb(0, 0, 0.5)
        cr.rectangle(3, 3, 10, 3); cr.fill()

    def _arrow(self, cr):
        cr.set_source_rgb(0, 0, 0)
        cr.move_to(5, 4); cr.line_to(10, 8); cr.line_to(5, 12)
        cr.close_path(); cr.fill()


def title_glyph(kind, size=9):
    """The _ □ X marks used on title-bar buttons, as a drawing callback."""

    def draw(w, cr):
        aw, ah = w.get_allocated_width(), w.get_allocated_height()
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(1)
        cx, cy = aw / 2, ah / 2
        if kind == "min":
            cr.rectangle(cx - 3, cy + 2, 6, 2); cr.fill()
        elif kind == "max":
            cr.rectangle(cx - 4.5, cy - 4.5, 9, 9); cr.stroke()
            cr.rectangle(cx - 4.5, cy - 4.5, 9, 2); cr.fill()
        else:  # close
            for dx, dy in ((-3, -3), (-3, 3)):
                cr.move_to(cx + dx, cy + dy)
                cr.line_to(cx - dx, cy - dy)
            cr.set_line_width(1.4)
            cr.stroke()
        return False

    area = Gtk.DrawingArea()
    area.set_size_request(size, size)
    area.connect("draw", draw)
    return area
