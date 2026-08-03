"""w95tray — the notification area, as an XEmbed system tray host.

Windows 95 called it the notification area and put it in the sunken well at the
right of the taskbar, left of the clock. This is that well, doing the job for
real: nm-applet, the Nextcloud client, syncthing and Slack all put their icons
here.

Nothing else on this machine hosts a tray. i3's own tray lives in i3bar, and
Windows 95 mode deliberately has no `bar {}` block -- w95bar replaces it -- so
before this, `_NET_SYSTEM_TRAY_S0` had no owner at all and every one of those
apps silently had nowhere to draw. (Check with
`xprop -root _NET_SYSTEM_TRAY_S0`, or see `Tray.owner` below.)

## Why Xlib and not GTK

The freedesktop System Tray protocol needs three things GTK3 cannot do from
Python:

* own an X *selection* (`_NET_SYSTEM_TRAY_S<screen>`) on a window of our own,
* receive raw `ClientMessage` events on that window, and
* broadcast a `MANAGER` message so apps that are *already running* dock
  themselves without being restarted.

`Gdk.Window.add_filter` -- the one hook that would give raw X events -- is not
introspectable, so PyGObject cannot see ClientMessages at all. python-xlib does
all three, and its display has a `fileno()`, so it joins the GLib main loop as
an ordinary IO watch rather than needing a thread.

The embedding half stays GTK: `Gtk.Socket` is a proper XEmbed host, so each
docked icon becomes a normal widget in the well and gets laid out, sized and
styled like everything else in the bar.

## Deliberate omissions

`_NET_SYSTEM_TRAY_VISUAL` is *not* advertised. It tells clients they may use a
32-bit ARGB visual, which only renders correctly under a compositing manager --
and this desktop is i3 with no compositor, so promising it would get us icons
with black boxes where the transparency should be. Without it clients fall back
to the default visual and paint their own background, which on silver is what
Win95 icons looked like anyway.

StatusNotifierItem (the DBus tray) is not implemented. Every tray-capable app on
this box falls back to XEmbed when no StatusNotifierWatcher is on the bus, and
none is, so XEmbed alone covers all of them. If something ever only speaks
StatusNotifier, the answer is `snixembed` in front of this, not a second
protocol in here.
"""

import sys

try:
    from Xlib import X, Xatom, display as xdisplay, error as xerror
    from Xlib.protocol import event as xevent, request as xrequest
    HAVE_XLIB = True
except ImportError:                                  # pragma: no cover
    HAVE_XLIB = False

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

# From the spec's systray.h.
SYSTEM_TRAY_REQUEST_DOCK = 0
SYSTEM_TRAY_BEGIN_MESSAGE = 1
SYSTEM_TRAY_CANCEL_MESSAGE = 2

_ORIENTATION_HORZ = 0


class Tray:
    """Owns the tray selection and fills `container` with docked icons.

    Constructed but inert until `start()`; `start()` must be called *after* the
    bar's window is realized, because a Gtk.Socket can only adopt a foreign
    window once it has an X window of its own to reparent into.
    """

    def __init__(self, container, icon_size):
        self.container = container
        self.icon_size = icon_size
        self.dpy = None
        self.manager = None
        self.sockets = {}          # client xid -> Gtk.Socket
        self._watch = None
        self.owner = None          # xid of a pre-existing tray, if any

    # ── lifecycle ───────────────────────────────────────────────────────
    def start(self):
        """Acquire the tray selection. Returns True if we are now the tray.

        Every failure path is soft: a taskbar without a notification area is a
        cosmetic loss, and one that refuses to start because python-xlib is
        missing is a broken desktop.
        """
        if not HAVE_XLIB:
            self._note("python-xlib is not installed — no notification area")
            return False
        try:
            self.dpy = xdisplay.Display()
        except Exception as exc:
            self._note("cannot open display (%s)" % exc)
            return False

        screen = self.dpy.screen()
        self.selection_atom = self.dpy.get_atom(
            "_NET_SYSTEM_TRAY_S%d" % self.dpy.get_default_screen())

        existing = self.dpy.get_selection_owner(self.selection_atom)
        if existing != X.NONE:
            # Somebody else is the tray (a stray stalonetray, an i3bar that
            # outlived its config). Refuse rather than fight: two owners means
            # icons scattered between them, at random, per app startup order.
            self.owner = existing
            self._note("another tray already owns the selection — standing down")
            return False

        # The manager window is never mapped. It exists only to hold the
        # selection and to be the address dock requests are sent to.
        self.manager = screen.root.create_window(
            -1, -1, 1, 1, 0, screen.root_depth,
            window_class=X.InputOutput,
            event_mask=X.StructureNotifyMask | X.PropertyChangeMask,
        )
        self.manager.set_wm_name("w95bar notification area")

        # Horizontal, because the taskbar is. Clients read this to decide how to
        # lay out multi-icon groups.
        self.manager.change_property(
            self.dpy.get_atom("_NET_SYSTEM_TRAY_ORIENTATION"),
            Xatom.CARDINAL, 32, [_ORIENTATION_HORZ])

        # A Window method, not a Display one: python-xlib exposes
        # get_selection_owner on the display but set_selection_owner only on the
        # window that is becoming the owner.
        self.manager.set_selection_owner(self.selection_atom, X.CurrentTime)
        self.dpy.sync()
        if self.dpy.get_selection_owner(self.selection_atom) != self.manager:
            self._note("lost the race for the tray selection")
            return False

        # Tell the world. Apps started *before* us are watching the root window
        # for exactly this, and will dock on receipt; without it the tray only
        # ever collects icons from apps launched after the bar.
        screen.root.send_event(
            xevent.ClientMessage(
                window=screen.root,
                client_type=self.dpy.get_atom("MANAGER"),
                data=(32, [X.CurrentTime, self.selection_atom,
                           self.manager.id, 0, 0]),
            ),
            event_mask=X.StructureNotifyMask,
        )
        self.dpy.flush()

        # python-xlib on the GLib loop: no thread, no polling.
        self._watch = GLib.io_add_watch(self.dpy.fileno(), GLib.PRIORITY_DEFAULT,
                                        GLib.IO_IN, self._on_x_ready)
        return True

    def stop(self):
        """Give the selection back, so a replacement bar can take it."""
        if self._watch is not None:
            GLib.source_remove(self._watch)
            self._watch = None
        if self.dpy is not None and self.manager is not None:
            try:
                # Releasing means setting the owner to None, and there is no
                # window method for that -- the request has to be sent by hand.
                xrequest.SetSelectionOwner(
                    display=self.dpy.display, window=X.NONE,
                    selection=self.selection_atom, time=X.CurrentTime)
                self.manager.destroy()
                self.dpy.flush()
            except Exception:
                pass
        self.manager = None

    # ── X events ────────────────────────────────────────────────────────
    def _on_x_ready(self, *_):
        """Drain every queued X event. Must return True to stay subscribed."""
        try:
            while self.dpy.pending_events():
                self._handle(self.dpy.next_event())
        except Exception as exc:                       # never kill the bar
            self._note("error handling X event: %r" % exc)
        return True

    def _handle(self, ev):
        if ev.type == X.ClientMessage:
            if ev.client_type == self.dpy.get_atom("_NET_SYSTEM_TRAY_OPCODE"):
                opcode = ev.data[1][1]
                if opcode == SYSTEM_TRAY_REQUEST_DOCK:
                    self._dock(ev.data[1][2])
                # BEGIN/CANCEL_MESSAGE are the balloon-message half of the
                # spec: the tray is asked to draw the tooltip itself. Nothing
                # on this box has ever sent one, and dunst already handles
                # notifications, so they are accepted and dropped rather than
                # left to look like an unhandled event.
        elif ev.type == X.SelectionClear:
            # Another tray took over (or we are being replaced). Drop the icons
            # rather than holding sockets to windows we no longer manage.
            self._note("tray selection taken by another client")
            for xid in list(self.sockets):
                self._undock(xid)

    # ── docking ─────────────────────────────────────────────────────────
    def _dock(self, xid):
        if not xid or xid in self.sockets:
            return
        socket = Gtk.Socket()
        socket.set_size_request(self.icon_size, self.icon_size)
        socket.set_halign(Gtk.Align.CENTER)
        socket.set_valign(Gtk.Align.CENTER)
        # `plug-removed` returning False lets GTK destroy the socket for us,
        # which is what we want -- but the widget still has to come out of the
        # box, so do both here.
        socket.connect("plug-removed", self._on_plug_removed, xid)
        self.container.add(socket)
        # Realized before add_id, or the reparent has no destination window.
        socket.show()

        # A client can die between asking to dock and us getting here, so the
        # X request may land on a window that no longer exists. Catching it is
        # the difference between one missing icon and the bar exiting.
        handler = xerror.CatchError(xerror.BadWindow)
        try:
            socket.add_id(xid)
            self.dpy.sync()
        except Exception as exc:
            self._note("could not embed 0x%x (%r)" % (xid, exc))
            self.container.remove(socket)
            return
        finally:
            del handler

        self.sockets[xid] = socket
        self.container.show_all()

    def _on_plug_removed(self, socket, xid):
        self._undock(xid)
        return False               # False => GTK destroys the socket

    def _undock(self, xid):
        socket = self.sockets.pop(xid, None)
        if socket is None:
            return
        try:
            self.container.remove(socket)
        except Exception:
            pass

    # ── misc ────────────────────────────────────────────────────────────
    @staticmethod
    def _note(msg):
        print("w95bar/tray: %s" % msg, file=sys.stderr)
