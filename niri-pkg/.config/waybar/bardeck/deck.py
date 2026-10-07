"""The Deck: the one overlay that shows a strip's panel under it.

A transparent layer-shell surface over the output below the bar (exclusive zone 0:
it never covers the bar, so the strips keep seeing the pointer), with the panel
drawn on it, centred under its strip.

It is resident: built once and hidden. A panel that is slow to draw (quota: ~0.15 s)
is drawn ahead whenever its data changes; the others draw in a few ms when they
open. An opening is one map and one blit: ~20 ms.

Two ways in, from bar-strip.so:
  hover  "enter": open without taking the keyboard. It closes when the pointer
         leaves the strip and the panel. Hovering another strip swaps the panel.
  click  "click": pin it open, with the keyboard: it stays until Esc, a click
         outside it, or another click on the strip. A click inside a panel pins it.
"""

from __future__ import annotations

import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

from . import core  # noqa: E402


class Panel:
    """What a strip opens. Subclasses draw in panel coordinates, (0, 0) top-left."""

    name = ""
    live = 0.0          # seconds between redraws while open; 0 = only on new data
    drawn_ahead = False  # slow to draw: keep a picture ready (see Deck.prerender)

    def size(self) -> tuple[int, int]:
        raise NotImplementedError

    def draw(self, cr, hits: core.Hits) -> None:
        raise NotImplementedError

    def opened(self) -> None:
        """A fresh opening: reset browsing state (a past week, a selection)."""

    def closed(self) -> None:
        """It closed, or another panel took its place: stop costly sampling."""

    def key(self, key: str, ctrl: bool) -> bool:
        """A key while pinned; True = handled (the panel redraws)."""
        return False

    def state(self) -> tuple:
        """What, besides new data, changes the picture (for the drawn-ahead cache)."""
        return ()

    def alternate(self) -> bool:
        """A right click on the strip (when its module sends it): the other view.
        True = it changed."""
        return False


class Deck:
    # The pointer may cross the bar between a strip and its panel, and a strip only
    # says "enter" after resting hover-ms: wait this long before closing.
    HIDE_GRACE_MS = 160

    def __init__(self, panels: dict[str, Panel]):
        self.panels = panels
        self.panel: Panel | None = None
        self.shown = self.pinned = False
        self.center: float | None = None
        self.origin: tuple[int, int] | None = None
        self.hits = core.Hits()
        self.cache: dict[tuple, cairo.ImageSurface] = {}
        self.hide_timer = 0
        self.live_timer = 0
        self.live_at = 0.0
        self.asked = 0.0
        self.inside = False  # the pointer is on the panel: nothing may close it but a click or Esc
        self.monitor = None

        win = self.win = Gtk.Window()
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "bardeck")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, 0)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        visual = win.get_screen().get_rgba_visual()
        if visual is not None:
            win.set_visual(visual)
        win.set_app_paintable(True)
        self.area = Gtk.DrawingArea()
        win.add(self.area)
        self.area.connect("draw", self.on_draw)
        win.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                       | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        win.connect("enter-notify-event", self.on_enter)
        win.connect("leave-notify-event", self.on_leave)
        win.connect("motion-notify-event", self.on_motion)
        win.connect("button-press-event", self.on_press)
        win.connect("key-press-event", self.on_key)
        win.connect("delete-event", lambda *_: self.hide() or True)

    # -- drawing ---------------------------------------------------------------

    def scales(self) -> set[int]:
        display = Gdk.Display.get_default()
        return {display.get_monitor(i).get_scale_factor() for i in range(display.get_n_monitors())} or {1}

    def picture(self, panel: Panel, scale: int):
        """A drawn-ahead panel's picture, and its hits."""
        key = (panel.name, panel.state(), scale)
        if key not in self.cache:
            if core.TRACE and self.shown:
                core.log(f"drawing {key} now (not drawn ahead)")
            w, h = panel.size()
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w * scale, h * scale)
            surf.set_device_scale(scale, scale)
            hits = core.Hits()
            panel.draw(cairo.Context(surf), hits)
            self.cache[key] = (surf, hits)
        return self.cache[key]

    def invalidate(self, name: str) -> None:
        """New data for a panel: drop its pictures; redraw it now when it is open,
        or draw it ahead when it is drawn ahead."""
        for key in [k for k in self.cache if k[0] == name]:
            del self.cache[key]
        panel = self.panels.get(name)
        if panel is None:
            return
        if self.shown and self.panel is panel:
            self.area.queue_draw()
        elif panel.drawn_ahead and not (self.shown and self.panel is panel):
            panel.opened()
            for scale in self.scales():
                self.picture(panel, scale)

    def on_draw(self, _w, cr) -> bool:
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if not self.shown or self.panel is None:
            return False
        p = self.panel
        pw, _ = p.size()
        width = self.win.get_allocated_width()
        # The strip's centre comes in the bar window's coordinates, which start
        # core.BAR_MARGIN_X into the output.
        x = (width - pw - 8) if self.center is None else self.center + core.BAR_MARGIN_X - pw / 2
        self.origin = (int(min(max(x, 8), max(8, width - pw - 8))), 6)
        cr.translate(*self.origin)
        if p.drawn_ahead:
            surf, self.hits = self.picture(p, self.win.get_scale_factor())
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
        else:
            self.hits = core.Hits()
            p.draw(cr, self.hits)
        if core.TRACE and self.asked:
            core.log(f"{p.name}: drawn {(time.perf_counter() - self.asked) * 1000:.0f} ms after the "
                     f"{'click' if self.pinned else 'hover'}")
            self.asked = 0.0
        return False

    # -- showing ---------------------------------------------------------------

    @staticmethod
    def monitor_at(mx: int, my: int):
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            if (g.x, g.y) == (mx, my):
                return mon
        return None

    def show(self, panel: Panel, center: float | None, monitor, pinned: bool) -> None:
        self.cancel_hide()
        if pinned and not self.pinned:
            self.pinned = True
            GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        if self.shown and monitor is not None and monitor != self.monitor:
            self.hide()  # a strip on another output: open there, not on the old one
            if pinned:
                self.pinned = True
                GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        if center is not None:
            self.center = center
        if self.shown:
            if panel is not self.panel:  # hovered the next strip: swap in place
                if self.panel is not None:
                    self.panel.closed()
                self.panel = panel
                panel.opened()
                self.area.queue_draw()
            return
        self.panel = panel
        panel.opened()
        if monitor is not None:
            GtkLayerShell.set_monitor(self.win, monitor)
            self.monitor = monitor
        self.shown, self.asked, self.inside = True, time.perf_counter(), False
        self.win.show_all()
        if not self.live_timer:
            self.live_timer = GLib.timeout_add(1000, self._live)

    def _live(self) -> bool:
        if not self.shown:
            self.live_timer = 0
            return False
        p = self.panel
        now = time.monotonic()
        if p is not None and p.live and now - self.live_at >= p.live - 0.05:
            self.live_at = now
            self.area.queue_draw()
        return True

    def hide(self) -> None:
        self.cancel_hide()
        if not self.shown:
            return
        self.shown = self.inside = False
        self.win.hide()
        if self.panel is not None:
            self.panel.closed()
        if self.pinned:
            self.pinned = False
            GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.NONE)
        p = self.panel
        if p is not None and p.drawn_ahead:
            # Browsing (a past week) changed the state: have the default picture ready again.
            GLib.idle_add(lambda: self.invalidate(p.name) or False)

    def hide_soon(self) -> None:
        if self.shown and not self.pinned and not self.inside and not self.hide_timer:
            self.hide_timer = GLib.timeout_add(self.HIDE_GRACE_MS, self._hide_timeout)

    def _hide_timeout(self) -> bool:
        self.hide_timer = 0
        if not self.pinned and not self.inside:
            self.hide()
        return False

    def cancel_hide(self) -> None:
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = 0

    def message(self, verb: str, strip: str, center: float | None, monitor) -> bool:
        """A strip's enter / leave / click. False when the strip has no panel."""
        panel = self.panels.get(strip)
        if verb == "leave":
            self.hide_soon()
            return True
        if panel is None:
            return False
        if verb == "enter":
            self.show(panel, center, monitor, pinned=False)
        elif verb == "click":
            if self.shown and self.pinned and self.panel is panel:
                self.hide()
            else:
                self.show(panel, center, monitor, pinned=True)
        elif verb == "right":  # the panel's other view, pinned (the clock: the year)
            self.show(panel, center, monitor, pinned=True)
            if panel.alternate():
                self.area.queue_draw()
        return True

    # -- input -----------------------------------------------------------------

    def in_panel(self, ex: float, ey: float) -> bool:
        if self.origin is None or self.panel is None:
            return False
        ox, oy = self.origin
        pw, ph = self.panel.size()
        return ox <= ex < ox + pw and oy <= ey < oy + ph

    def track(self, ex: float, ey: float) -> None:
        """The pointer is over the overlay at (ex, ey). On the panel: keep it open. Off it:
        close after the grace, not at once, so the way from the strip to the panel (the
        band above the panel, a diagonal from a strip near the edge) does not close it."""
        self.inside = self.in_panel(ex, ey)
        if self.inside:
            self.cancel_hide()
        elif not self.pinned:
            self.hide_soon()

    def on_enter(self, _w, event) -> bool:
        self.track(event.x, event.y)
        return False

    def on_leave(self, _w, event) -> bool:
        if event.detail != Gdk.NotifyType.INFERIOR:
            self.inside = False
            self.hide_soon()  # up to the bar: maybe onto a strip, which says "enter"
        return False

    def on_motion(self, _w, event) -> bool:
        self.track(event.x, event.y)
        return False

    def on_press(self, _w, event) -> bool:
        if not self.in_panel(event.x, event.y):
            self.hide()
            return True
        ox, oy = self.origin
        action = self.hits.at(event.x - ox, event.y - oy)
        if action is None:
            self.show(self.panel, None, None, pinned=True)
            return True
        close = action()
        if close:
            self.hide()
        else:
            # The action changed state (a profile, a VPN): show it soon.
            GLib.timeout_add(400, lambda: self.area.queue_draw() and False)
            if self.panel is not None and self.panel.drawn_ahead:
                self.invalidate(self.panel.name)
        return True

    def on_key(self, _w, event) -> bool:
        key = Gdk.keyval_name(event.keyval) or ""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if key in ("Escape", "q") or (ctrl and key == "g"):
            self.hide()
            return True
        if self.panel is not None and self.panel.key(key, ctrl):
            self.area.queue_draw()
            return True
        return False
