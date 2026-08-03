"""Start menu, Run… and Shut Down… — the parts of the shell that pop up."""

import os
import shlex
import shutil
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

import w95conf  # noqa: E402
import w95draw  # noqa: E402


def spawn(cmd):
    """Detach a child so it survives the shell being restarted."""
    subprocess.Popen(
        cmd if isinstance(cmd, list) else ["/bin/sh", "-c", cmd],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _style(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return widget


def elide(text, limit=34):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MenuItem(Gtk.Button):
    """One Start-menu row: glyph, label, optional submenu arrow."""

    def __init__(self, label, glyph=None, submenu=False, big=False, on_click=None):
        super().__init__()
        self.rows_factory = None  # set by StartMenu for rows that fly out
        self.set_relief(Gtk.ReliefStyle.NONE)
        # The Start menu highlights what the pointer is on, nothing else. As a
        # focusable button the first row took focus the instant the menu
        # opened and sat there navy — "Programs" permanently lit, looking
        # selected when it was not. Nothing here is keyboard-driven (the menu
        # handles only Escape), so the focusable state has no use to lose.
        self.set_can_focus(False)
        _style(self, "w95-item")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon_size = w95conf.BIG_ICON_SIZE if big else w95conf.ICON_SIZE
        box.pack_start(w95draw.Glyph(glyph or "window", icon_size), False, False, 0)
        lab = Gtk.Label(label=label, xalign=0)
        if big:
            lab.set_markup('<span font_desc="W95FA %d">%s</span>'
                           % (w95conf.BIG_FONT_PT, GLib.markup_escape_text(label)))
        box.pack_start(lab, True, True, 0)
        if submenu:
            box.pack_end(w95draw.Glyph("arrow", max(12, w95conf.ICON_SIZE - 4)),
                         False, False, 0)
        self.add(box)
        if on_click:
            self.connect("clicked", lambda *_: on_click())


class Popup(Gtk.Window):
    """Base for anything that appears over the desktop: undecorated, on top,
    and self-closing when it loses the pointer grab or takes Escape."""

    def __init__(self, css, modal_grab=True):
        super().__init__(type=Gtk.WindowType.POPUP if modal_grab else Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.connect("key-press-event", self._key)

    def _key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.dismiss()
            return True
        return False

    def dismiss(self):
        Gdk.pointer_ungrab(Gdk.CURRENT_TIME)
        Gdk.keyboard_ungrab(Gdk.CURRENT_TIME)
        self.destroy()


SUBMENU_DELAY = 220  # ms of hover before a submenu flies out, as in the original


class Flyout(Gtk.Window):
    """A submenu panel that opens beside the row that owns it.

    Deliberately grab-*less*. The Start menu holds one seat grab with
    owner_events=True, so pointer events over this window are still delivered
    normally (same application) while a click anywhere outside still reaches
    the parent and tears the whole stack down. The old Programs window took a
    second grab of its own after the parent had already dismissed itself,
    which is why submenus behaved like a separate, misplaced window.
    """

    MAX_HEIGHT = 620

    def __init__(self, rows, scrolling=False):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        frame = _style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "w95-menu")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_border_width(2)
        for row in rows:
            box.pack_start(row, False, False, 0)
        if scrolling:
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_size_request(250, min(self.MAX_HEIGHT, 26 * len(rows) + 8))
            scroller.add(box)
            frame.pack_start(scroller, True, True, 0)
        else:
            frame.pack_start(box, True, True, 0)
        self.add(frame)

    def pop_beside(self, panel_x, panel_y, panel_w, row_y, max_bottom):
        """Right of the parent panel, level with the hovered row — flipping to
        the left and sliding up only as far as the screen actually forces."""
        self.show_all()
        w, h = self.get_size()
        screen = Gdk.Screen.get_default()
        geo = screen.get_monitor_geometry(screen.get_primary_monitor())
        x = panel_x + panel_w - 3
        if x + w > geo.x + geo.width:
            x = max(geo.x, panel_x - w + 3)
        y = min(panel_y + row_y, max_bottom - h)
        self.move(x, max(geo.y, y))


class StartMenu(Popup):
    def __init__(self, css, anchor_x, anchor_y, on_close=None):
        super().__init__(css)
        self.on_close = on_close
        self.css = css
        self._anchor_y = anchor_y
        self._pos = (anchor_x, anchor_y)
        self._sub = None
        self._sub_owner = None
        self._sub_timer = 0

        frame = _style(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), "w95-menu")
        frame.pack_start(w95draw.Banner(max(26, w95conf.BAR_HEIGHT - 8)), False, False, 0)

        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        items.set_border_width(2)
        items.set_size_request(max(190, w95conf.BIG_FONT_PT * 15), -1)

        self._add(items, MenuItem("Programs", "folder", submenu=True, big=True),
                  self._programs_rows)
        self._add(items, MenuItem("Documents", "folder", submenu=True, big=True),
                  self._documents_rows)
        self._add(items, MenuItem("Settings", "gear", submenu=True, big=True),
                  self._settings_rows)
        self._add(items, MenuItem("Find", "find", submenu=True, big=True),
                  self._find_rows)
        self._add(items, MenuItem("Help", "help", big=True,
                                  on_click=lambda: self._run_and_close(
                                      "x-terminal-emulator -e man i3 || xterm -e man i3")))
        self._add(items, MenuItem("Run...", "run", big=True,
                                  on_click=lambda: self._later(lambda: RunDialog(css).show_all())))
        items.pack_start(_style(Gtk.Box(), "w95-sep"), False, False, 0)
        self._add(items, MenuItem("Shut Down...", "shutdown", big=True,
                                  on_click=lambda: self._later(lambda: ShutdownDialog(css).show_all())))

        frame.pack_start(items, True, True, 0)
        self.add(frame)
        self.show_all()

        _, h = self.get_size()
        self._pos = (anchor_x, anchor_y - h)
        self.move(*self._pos)
        self._grab()

    def _add(self, box, item, rows_factory=None):
        item.rows_factory = rows_factory
        item.connect("enter-notify-event", self._hover, item)
        if rows_factory is not None:
            # Clicking the parent row opens it immediately, without the delay.
            item.connect("clicked", lambda _b, i=item: self._open_submenu(i))
        box.pack_start(item, False, False, 0)

    def _grab(self):
        """Pointer grab so a click anywhere outside dismisses the menu —
        exactly how the real Start menu behaves.

        Deferred, and checked. `show_all()` only *queues* the map, so at the
        point this is called the server has usually not mapped the window yet
        and the grab comes back GDK_GRAB_NOT_VIEWABLE. Nothing looked at that
        return value, so the failure was silent and total: with no grab, a
        click outside the menu went to whatever was underneath it and the menu
        just stayed on screen — which is exactly the bug this replaces.
        """
        self.connect("button-press-event", self._maybe_dismiss)
        self._grab_tries = 0
        GLib.timeout_add(20, self._try_grab)

    def _try_grab(self):
        window = self.get_window()
        status = None
        if window is not None and window.is_viewable():
            seat = Gdk.Display.get_default().get_default_seat()
            status = seat.grab(window, Gdk.SeatCapabilities.ALL, True,
                               None, None, None, None)
            if status == Gdk.GrabStatus.SUCCESS:
                return False
        self._grab_tries += 1
        if self._grab_tries < 25:      # keep trying for ~half a second
            return True
        print("w95menu: could not grab the pointer (%s); clicking outside the "
              "menu will not close it" % status, file=sys.stderr)
        return False

    def _maybe_dismiss(self, _w, ev):
        alloc = self.get_allocation()
        if not (0 <= ev.x <= alloc.width and 0 <= ev.y <= alloc.height):
            self.dismiss()
            return True
        return False

    def dismiss(self):
        self._close_submenu()
        if self.on_close:
            self.on_close()
        super().dismiss()

    def _key(self, _w, ev):
        """Escape closes the open submenu first, then the menu itself."""
        if ev.keyval == Gdk.KEY_Escape:
            if self._sub is not None:
                self._close_submenu()
            else:
                self.dismiss()
            return True
        return False

    # ── submenus ────────────────────────────────────────────────────────
    def _hover(self, _w, _ev, item):
        if self._sub_timer:
            GLib.source_remove(self._sub_timer)
            self._sub_timer = 0
        if item.rows_factory is None:
            # Moving onto a plain row retracts whatever was open, like Win95.
            self._close_submenu()
        elif self._sub_owner is not item:
            self._sub_timer = GLib.timeout_add(SUBMENU_DELAY, self._hover_fire, item)
        return False

    def _hover_fire(self, item):
        self._sub_timer = 0
        self._open_submenu(item)
        return False

    def _open_submenu(self, item):
        if self._sub is not None and self._sub_owner is item:
            return
        self._close_submenu()
        rows, scrolling = item.rows_factory()
        if not rows:
            return
        sub = Flyout(rows, scrolling=scrolling)
        row_y = (item.translate_coordinates(self, 0, 0) or (0, 0))[1]
        sub.pop_beside(self._pos[0], self._pos[1],
                       self.get_allocation().width, row_y, self._anchor_y)
        self._sub, self._sub_owner = sub, item

    def _close_submenu(self):
        if self._sub_timer:
            GLib.source_remove(self._sub_timer)
            self._sub_timer = 0
        if self._sub is not None:
            self._sub.destroy()
            self._sub = None
        self._sub_owner = None

    def _leaf(self, label, glyph, cmd):
        """A submenu row that runs something and closes the whole stack."""
        return MenuItem(elide(label), glyph, on_click=lambda: self._run_and_close(cmd))

    def _programs_rows(self):
        apps = sorted(
            (a for a in Gio.AppInfo.get_all() if a.should_show()),
            key=lambda a: a.get_display_name().lower(),
        )
        return [
            MenuItem(elide(a.get_display_name()), "window",
                     on_click=lambda x=a: self._later(lambda: x.launch(None, None)))
            for a in apps
        ], True

    def _documents_rows(self):
        rows = [self._leaf("Home", "folder", self._open_cmd("~"))]
        for name in ("Desktop", "Documents", "Downloads"):
            if os.path.isdir(os.path.expanduser("~/" + name)):
                rows.append(self._leaf(name, "folder", self._open_cmd("~/" + name)))
        recent = Gtk.RecentManager.get_default().get_items()
        recent.sort(key=lambda i: i.get_visited(), reverse=True)
        if recent:
            rows.append(_style(Gtk.Box(), "w95-sep"))
        for item in recent[:12]:
            rows.append(MenuItem(
                elide(item.get_display_name()), "doc",
                on_click=lambda u=item.get_uri(): self._run_and_close(
                    "xdg-open %s" % shlex.quote(u))))
        return rows, False

    def _settings_rows(self):
        # Only offer a control panel we can actually open — a row that does
        # nothing is worse than a row that isn't there.
        candidates = [
            ("Display", "gear", "arandr"),
            ("Sounds", "gear", "pavucontrol"),
            ("Network", "gear", "nm-connection-editor"),
            ("Printers", "gear", "system-config-printer"),
            ("Bluetooth", "gear", "blueman-manager"),
        ]
        rows = [self._leaf(label, glyph, cmd)
                for label, glyph, cmd in candidates
                if shutil.which(cmd.split()[0])]
        rows.append(_style(Gtk.Box(), "w95-sep"))
        rows.append(self._leaf("Taskbar & Start Menu", "window",
                               "x-terminal-emulator -e ${EDITOR:-vi} "
                               "~/.config/w95/settings"))
        rows.append(self._leaf("Window Manager (i3 config)", "window",
                               "x-terminal-emulator -e ${EDITOR:-vi} "
                               "~/.config/i3/config"))
        rows.append(self._leaf("Leave Windows 95", "shutdown", "w95-switch off"))
        return rows, False

    def _find_rows(self):
        return [
            self._leaf("Files or Folders...", "find",
                       "rofi -show filebrowser || rofi -show run"),
            self._leaf("Programs...", "find", "rofi -show drun"),
            self._leaf("Windows...", "find", "rofi -show window"),
        ], False

    @staticmethod
    def _open_cmd(path):
        return "xdg-open %s" % shlex.quote(os.path.expanduser(path))

    def _later(self, fn):
        """Close first, then act — otherwise the grab eats the new window."""
        self.dismiss()
        GLib.timeout_add(30, lambda: (fn(), False)[1])

    def _run_and_close(self, cmd):
        self._later(lambda: spawn(cmd))

class Dialog(Gtk.Window):
    """A Win95 dialog box: gradient title bar, X button, beveled body.
    We draw our own decoration because i3 won't give us a gradient one."""

    def __init__(self, css, title, glyph=None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_skip_taskbar_hint(True)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        outer = _style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "w95-dialog")
        outer.set_border_width(3)

        bar = _style(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4), "w95-title")
        bar.pack_start(w95draw.Glyph(glyph or "window", 14), False, False, 0)
        bar.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
        close = _style(Gtk.Button(), "w95-titlebtn")
        close.add(w95draw.title_glyph("close"))
        close.connect("clicked", lambda *_: self.destroy())
        bar.pack_end(close, False, False, 0)
        # Dragging the fake title bar has to move the real window ourselves.
        evb = Gtk.EventBox()
        evb.add(bar)
        evb.connect("button-press-event", self._begin_drag)
        outer.pack_start(evb, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.set_border_width(9)
        outer.pack_start(self.body, True, True, 0)
        self.add(outer)
        self.connect("key-press-event", lambda _w, e:
                     self.destroy() if e.keyval == Gdk.KEY_Escape else False)

    def _begin_drag(self, _w, ev):
        self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        return True

    def buttons(self, *specs):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_halign(Gtk.Align.END)
        for i, (label, cb) in enumerate(specs):
            b = _style(Gtk.Button(label=label), "w95-btn")
            if i == 0:
                _style(b, "w95-default")
                b.set_can_default(True)
            b.set_size_request(75, 23)
            b.connect("clicked", lambda _b, c=cb: c())
            row.pack_start(b, False, False, 0)
        self.body.pack_end(row, False, False, 0)
        return row


class RunDialog(Dialog):
    def __init__(self, css):
        super().__init__(css, "Run", "run")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top.pack_start(w95draw.Glyph("run", 32), False, False, 0)
        top.pack_start(Gtk.Label(
            label="Type the name of a program, folder, or document,\n"
                  "and Windows will open it for you.", xalign=0), True, True, 0)
        self.body.pack_start(top, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Open:"), False, False, 0)
        self.entry = _style(Gtk.Entry(), "w95-entry")
        self.entry.set_size_request(260, 22)
        self.entry.connect("activate", lambda *_: self._go())
        row.pack_start(self.entry, True, True, 0)
        self.body.pack_start(row, False, False, 0)

        self.buttons(("OK", self._go), ("Cancel", self.destroy),
                     ("Browse...", lambda: spawn("xdg-open ~")))
        self.connect("show", lambda *_: self.entry.grab_focus())

    def _go(self):
        cmd = self.entry.get_text().strip()
        if cmd:
            spawn(cmd)
        self.destroy()


class ShutdownDialog(Dialog):
    """i3 session control, wearing the 'It is now safe…' hat."""

    CHOICES = [
        ("Log off (exit i3)", "i3-msg exit"),
        ("Restart i3 in place", "i3-msg restart"),
        ("Restart the computer", "systemctl reboot"),
        ("Shut down the computer", "systemctl poweroff"),
        ("Suspend the computer", "systemctl suspend"),
    ]

    def __init__(self, css):
        super().__init__(css, "Shut Down Windows", "shutdown")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top.pack_start(w95draw.Glyph("shutdown", 40), False, False, 0)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        col.pack_start(Gtk.Label(label="Are you sure you want to:", xalign=0), False, False, 0)
        group = None
        self.choice = self.CHOICES[0][1]
        for label, cmd in self.CHOICES:
            radio = Gtk.RadioButton.new_with_label_from_widget(group, label)
            group = group or radio
            radio.connect("toggled", lambda b, c=cmd: self._pick(b, c))
            col.pack_start(radio, False, False, 0)
        top.pack_start(col, True, True, 0)
        self.body.pack_start(top, False, False, 0)
        self.buttons(("Yes", self._go), ("No", self.destroy))

    def _pick(self, button, cmd):
        if button.get_active():
            self.choice = cmd

    def _go(self):
        cmd = self.choice
        self.destroy()
        GLib.timeout_add(60, lambda: (spawn(cmd), False)[1])
