"""w95sysmon — the System Monitor's window.

One page. Windows 95 would have made this a property sheet with six tabs, and
the first version did — but a monitor you summon with a keystroke exists to be
read at a glance, and a tab is a thing you have to go and find. So the Win95
chrome stays and the tabs go: a row of scrolling charts across the top, then
every group box the tabs used to hold, laid out in a grid that reflows to the
width it is given.

Built out of the same two bevels as the rest of the shell (see w95.css) and fed
by w95stat. This module owns presentation only: every number it draws and every
action its buttons fire lives in w95stat, so the two can be reasoned about —
and tested — separately.

Four things worth knowing before reading on:

* **The toggle is a hide, not an exit.** The process stays resident so the
  second keypress is instant. Hidden, it pauses polling: a monitor nobody is
  looking at has no business running `checkupdates` on a timer.

* **Fast things tick, slow things poll.** Anything from /proc or /sys is
  sampled on the GTK main loop once a second — cheap, and it has to be regular
  because it is what the charts are made of. Anything that forks
  (`bluetoothctl`, `pactl`, the block scripts, curl to the Claude API) goes
  through w95stat.Poller onto a worker thread. Nothing that can block is ever
  called from a draw handler or a click handler.

* **A failed probe keeps the last good value.** w95stat returns None when a
  script times out, and a field that blanks itself every time the Bluetooth
  daemon is slow is worse than one that is briefly stale.

* **A control never writes a value the system already has.** Every radio and
  check box on this page is *both* an input and an output — polled state writes
  into it, and it writes into the system. That loop is how an early version of
  this file silently changed the machine's power profile at startup: GTK emits
  ::toggled for programmatic changes too, so a sync looked exactly like a
  click. Guard flags help, but the guarantee is `_commit()` below: re-read the
  authority first, and do nothing if it already agrees.
"""

import math
import os
import subprocess
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

import w95conf  # noqa: E402
import w95draw  # noqa: E402
import w95menu  # noqa: E402
import w95stat  # noqa: E402

# The five colours, as cairo triples, plus the phosphors the charts use.
FACE = (0.753, 0.753, 0.753)
HILITE = (1.0, 1.0, 1.0)
SHADOW = (0.502, 0.502, 0.502)
NAVY = (0.0, 0.0, 0.502)
TEAL = (0.0, 0.502, 0.502)
MAROON = (0.502, 0.0, 0.0)
GREEN = (0.0, 1.0, 0.0)
DKGREEN = (0.0, 0.31, 0.0)
YELLOW = (1.0, 1.0, 0.0)
CYAN = (0.0, 1.0, 1.0)

# sysmon.exe's Options ▸ Chart ▸ Update Interval, with the settings it had.
SPEEDS = [("_Fast (0.5 sec)", 500), ("_Normal (1 sec)", 1000),
          ("_Slow (5 sec)", 5000), ("_Paused", 0)]
DEFAULT_SPEED = 1000

CHART_SAMPLES = 150     # about 2½ minutes of history at Normal speed
CHART_HEIGHT = 110      # a floor, not a size — the charts grow into the slack
PANEL_WIDTH = 430       # the width a panel wants; the grid reflows around it
SLIDE_MS = 130          # how long the drop-down takes to arrive


def style(widget, *classes):
    ctx = widget.get_style_context()
    for name in classes:
        ctx.add_class(name)
    return widget


def label(text="", xalign=0.0, bold=False, dim=False, chars=0):
    widget = Gtk.Label(xalign=xalign)
    widget.set_markup("<b>%s</b>" % GLib.markup_escape_text(text) if bold
                      else GLib.markup_escape_text(text))
    if dim:
        style(widget, "w95-key")
    if chars:
        widget.set_width_chars(chars)
    return widget


def button(text, on_click, width=84):
    btn = style(Gtk.Button(label=text), "w95-btn")
    btn.set_size_request(width, 22)
    btn.connect("clicked", lambda *_: on_click())
    return btn


def button_row(*buttons):
    """Buttons sit at their natural size, left to right — never stretched to
    the width of the panel, which is what packing them straight into a vertical
    box would do."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    row.set_halign(Gtk.Align.START)
    for btn in buttons:
        row.pack_start(btn, False, False, 0)
    return row


def grid(spacing=3):
    table = Gtk.Grid(column_spacing=10, row_spacing=spacing)
    table.set_column_homogeneous(False)
    return table


class Field:
    """One `Name: value` row of a panel."""

    def __init__(self, table, row, name):
        table.attach(label(name, dim=True), 0, row, 1, 1)
        self.value = label("—")
        self.value.set_ellipsize(Pango.EllipsizeMode.END)
        self.value.set_hexpand(True)
        table.attach(self.value, 1, row, 1, 1)

    def set(self, text):
        text = "—" if text in (None, "") else str(text)
        if self.value.get_text() != text:
            self.value.set_text(text)
            # The long ones (a CPU model, an SSID) ellipsize in a 430px panel,
            # so the full string has to survive somewhere.
            self.value.set_tooltip_text(text)


# ── drawn widgets ───────────────────────────────────────────────────────

class Gauge(Gtk.DrawingArea):
    """The Win95 progress bar: a row of discrete blocks, not a smooth fill.

    Resource Meter's three bars were exactly this, and the segmentation is the
    single detail that stops a modern flat progress bar from reading as 2010s
    Material. The block width derives from the height, as it did — the control
    had one look at every size.
    """

    def __init__(self, height=14, colour=NAVY, warn=None, width=-1):
        super().__init__()
        self.fraction = 0.0
        self.colour = colour
        self.warn = warn        # (threshold 0..1, colour) or None
        self.set_size_request(width, height)
        self.connect("draw", self._draw)

    def set_fraction(self, value):
        value = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        if abs(value - self.fraction) > 0.0005:
            self.fraction = value
            self.queue_draw()

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()

        cr.set_source_rgb(*SHADOW)                    # 1px sunken trough
        cr.rectangle(0, 0, w, 1); cr.rectangle(0, 0, 1, h); cr.fill()
        cr.set_source_rgb(*HILITE)
        cr.rectangle(0, h - 1, w, 1); cr.rectangle(w - 1, 0, 1, h); cr.fill()
        cr.set_source_rgb(*FACE)
        cr.rectangle(1, 1, w - 2, h - 2); cr.fill()

        colour = self.colour
        if self.warn and self.fraction >= self.warn[0]:
            colour = self.warn[1]

        inner_w, inner_h = w - 4, h - 4
        block = max(3.0, inner_h * 0.62)
        step = block + 2
        blocks = int(inner_w // step)
        cr.set_source_rgb(*colour)
        for i in range(int(round(blocks * self.fraction))):
            cr.rectangle(2 + i * step, 2, block, inner_h)
        cr.fill()
        return False


class Chart(Gtk.DrawingArea):
    """A scrolling strip chart, drawn the way a period monitor drew one:
    bright traces on black over a dark graticule.

    Auto-ranging is sticky and snaps to a round number. A y-axis that rescales
    on every sample makes a flat line look like activity, which is the one
    thing a monitor must not do.
    """

    def __init__(self, title, series, unit="%", maximum=100.0,
                 height=CHART_HEIGHT, formatter=None):
        super().__init__()
        self.title = title
        self.series = series           # [(w95stat.Series, colour, name)]
        self.unit = unit
        self.fixed_max = maximum
        self.formatter = formatter or (lambda v: "%.0f%s" % (v, unit))
        style(self, "w95-screen")
        self.set_size_request(-1, height)
        self.connect("draw", self._draw)

    def _ceiling(self):
        if self.fixed_max:
            return self.fixed_max
        peak = max([s.peak for s, _, _ in self.series] or [0.0])
        if peak <= 0:
            return 1.0
        # Round up to 1/2/5 × a power of ten, so the scale reads 200 KB/s
        # rather than 137.4 KB/s.
        magnitude = 10 ** math.floor(math.log10(peak))
        for factor in (1, 2, 5, 10):
            if peak <= factor * magnitude:
                return factor * magnitude
        return 10 * magnitude

    def _draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        x0, y0, x1, y1 = 3, 3, w - 3, h - 3
        if x1 <= x0 or y1 <= y0:
            return False

        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.fill()
        cr.save()
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.clip()

        ceiling = self._ceiling()
        cr.set_source_rgb(*DKGREEN)
        cr.set_line_width(1)
        for i in range(1, 4):
            y = y0 + (y1 - y0) * i / 4.0
            cr.move_to(x0, int(y) + 0.5)
            cr.line_to(x1, int(y) + 0.5)
        step = (x1 - x0) / 10.0
        for i in range(1, 10):
            x = x0 + step * i
            cr.move_to(int(x) + 0.5, y0)
            cr.line_to(int(x) + 0.5, y1)
        cr.stroke()

        span = max(2, CHART_SAMPLES)
        for series, colour, _name in self.series:
            values = series.values
            if len(values) < 2:
                continue
            dx = (x1 - x0) / float(span - 1)
            # Right-aligned: the newest sample is always at the right edge, so
            # a chart that has only just started filling grows leftwards
            # instead of jumping when it reaches the end.
            start = x1 - dx * (len(values) - 1)

            def point(index, value):
                return (start + dx * index,
                        y1 - (y1 - y0) * min(1.0, value / ceiling))

            cr.move_to(*point(0, values[0]))
            for i, value in enumerate(values[1:], 1):
                cr.line_to(*point(i, value))
            cr.set_source_rgba(colour[0], colour[1], colour[2], 0.9)
            cr.set_line_width(1.4)
            cr.stroke_preserve()
            cr.line_to(x1, y1)                 # fill under the trace
            cr.line_to(start, y1)
            cr.close_path()
            cr.set_source_rgba(colour[0], colour[1], colour[2], 0.18)
            cr.fill()

        cr.restore()

        size = max(8, w95conf.FONT_SIZE - 4)
        layout = PangoCairo.create_layout(cr)
        parts = ['<span foreground="#c0c0c0">%s</span>'
                 % GLib.markup_escape_text(self.title)]
        for series, colour, name in self.series:
            parts.append('<span foreground="#%02x%02x%02x">%s %s</span>' % (
                int(colour[0] * 255), int(colour[1] * 255), int(colour[2] * 255),
                GLib.markup_escape_text(name), self.formatter(series.latest)))
        layout.set_markup('<span font_desc="W95FA %d">%s</span>'
                          % (size, "   ".join(parts)), -1)
        cr.move_to(x0 + 4, y0 + 2)
        PangoCairo.show_layout(cr, layout)

        layout.set_markup('<span font_desc="W95FA %d" foreground="#008000">%s</span>'
                          % (size, self.formatter(ceiling)), -1)
        tw, _ = layout.get_pixel_size()
        cr.move_to(x1 - tw - 4, y0 + 2)
        PangoCairo.show_layout(cr, layout)
        return False


# ── panels ──────────────────────────────────────────────────────────────

class Panel(Gtk.Frame):
    """A Win95 group box that knows how to refresh itself."""

    TITLE = ""

    def __init__(self, app):
        super().__init__(label=" %s " % self.TITLE)
        self.app = app
        style(self, "w95-group")
        self.set_label_align(0.02, 0.5)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.body.set_border_width(7)
        self.add(self.body)
        self.set_size_request(PANEL_WIDTH, -1)
        self.build()

    def build(self):
        """Populate self.body."""

    def tick(self):
        """Called on every fast sample while visible."""

    def apply(self, key, value):
        """Called when a polled probe named `key` comes back."""

    def commit(self, read, want, write):
        """Apply a control's new value — but only if it is actually new.

        `read` re-reads the authority (sysfs, pactl) at the moment of the
        click. GTK emits ::toggled for programmatic changes as well as real
        ones, so without this check a poll that syncs a radio to the machine's
        state is indistinguishable from a user setting it, and the monitor ends
        up writing back whatever it just read — or worse, whatever the group's
        first member happened to be at construction time.
        """
        try:
            if read() == want:
                return False
        except Exception:
            return False
        write()
        return True


class ResourcesPanel(Panel):
    TITLE = "Resources"

    ROWS = [("Processor", NAVY, (0.90, MAROON)),
            ("Memory", NAVY, (0.90, MAROON)),
            ("Swap file", NAVY, (0.50, MAROON)),
            ("Disk (/)", NAVY, (0.90, MAROON)),
            ("Temperature", TEAL, (0.80, MAROON))]

    def build(self):
        table = grid(4)
        self.gauges = {}
        for row, (name, colour, warn) in enumerate(self.ROWS):
            table.attach(label(name, dim=True), 0, row, 1, 1)
            gauge = Gauge(colour=colour, warn=warn)
            gauge.set_hexpand(True)
            table.attach(gauge, 1, row, 1, 1)
            readout = label("—", chars=15)
            table.attach(readout, 2, row, 1, 1)
            self.gauges[name] = (gauge, readout)
        self.body.pack_start(table, False, False, 0)
        self.body.pack_start(button_row(button("Task Manager", self._htop, 96)),
                             False, False, 0)

    @staticmethod
    def _htop():
        w95stat.term("htop", hold=False)

    def tick(self):
        state = self.app.state
        memory, root = state["memory"], state["disk"]
        temp = state.get("temperature")
        self._set("Processor", state.get("cpu", 0.0) / 100.0,
                  "%.0f%%  %d threads" % (state.get("cpu", 0.0),
                                          state["cpu_info"]["cores"]))
        self._set("Memory", memory["percent"] / 100.0,
                  "%s/%s" % (w95stat.human_bytes(memory["used"]),
                             w95stat.human_bytes(memory["total"])))
        self._set("Swap file", memory["swap_percent"] / 100.0,
                  "%s/%s" % (w95stat.human_bytes(memory["swap_used"]),
                             w95stat.human_bytes(memory["swap_total"]))
                  if memory["swap_total"] else "none")
        self._set("Disk (/)", root["percent"] / 100.0,
                  "%s free" % w95stat.human_bytes(root["free"]))
        self._set("Temperature", (temp or 0) / 100.0,
                  "%.0f °C" % temp if temp is not None else "n/a")

    def _set(self, name, fraction, text):
        gauge, readout = self.gauges[name]
        gauge.set_fraction(fraction)
        if readout.get_text() != text:
            readout.set_text(text)


class ComputerPanel(Panel):
    TITLE = "Computer"

    NAMES = ["Computer", "System", "Processor", "Memory", "Started",
             "Load average", "Keyboard", "Recording"]

    def build(self):
        table = grid()
        self.fields = {name: Field(table, row, name)
                       for row, name in enumerate(self.NAMES)}
        self.body.pack_start(table, False, False, 0)
        self.body.pack_start(button_row(
            button("Keyboard", w95stat.toggle_keyboard_layout, 78),
            button("Boot Log", self._boot_log, 78),
            button("Screenshot", lambda: w95stat.block_action("screenshot", 1), 84),
        ), False, False, 0)

    @staticmethod
    def _boot_log():
        w95stat.term("systemd-analyze blame | head -40")

    def tick(self):
        state = self.app.state
        host, cpu, memory = state["host"], state["cpu_info"], state["memory"]
        self.fields["Computer"].set(host["host"])
        self.fields["System"].set("%s %s" % (host["system"], host["kernel"]))
        self.fields["Processor"].set("%s × %d" % (cpu["model"], cpu["cores"]))
        self.fields["Memory"].set("%s installed" % w95stat.human_bytes(memory["total"]))
        self.fields["Started"].set("%s ago" % w95stat.human_duration(state["uptime"]))
        self.fields["Load average"].set("%.2f   %.2f   %.2f" % state["load"])

    def apply(self, key, value):
        if key != "misc" or not value:
            return
        self.fields["Keyboard"].set("%s layout" % value["layout"])
        self.fields["Recording"].set("recording %s" % value["recording"]
                                     if value["recording"] else "idle")


class StoragePanel(Panel):
    TITLE = "Storage and Updates"

    def build(self):
        table = grid()
        self.fields = {name: Field(table, row, name) for row, name in
                       enumerate(["Volume", "Capacity", "Free space", "Updates"])}
        self.body.pack_start(table, False, False, 0)
        self.gauge = Gauge(colour=NAVY, warn=(0.90, MAROON), height=16)
        self.body.pack_start(self.gauge, False, False, 0)
        self.body.pack_start(button_row(
            button("Disk Usage", lambda: w95stat.term("df -h"), 86),
            button("Update...", lambda: w95stat.term("sudo pacman -Syu"), 86),
        ), False, False, 0)

    def tick(self):
        root = self.app.state["disk"]
        self.fields["Volume"].set("/  (root)")
        self.fields["Capacity"].set(w95stat.human_bytes(root["total"]))
        self.fields["Free space"].set("%s  (%.0f%% used)"
                                      % (w95stat.human_bytes(root["free"]),
                                         root["percent"]))
        self.gauge.set_fraction(root["percent"] / 100.0)

    def apply(self, key, value):
        if key == "updates" and value and value[0] is not None:
            count = value[0].strip()
            self.fields["Updates"].set("%s pending" % count if count else "up to date")


class ConnectionPanel(Panel):
    TITLE = "Connection"

    def build(self):
        table = grid()
        self.fields = {name: Field(table, row, name) for row, name in
                       enumerate(["Adapter", "Network", "Address", "Signal"])}
        self.body.pack_start(table, False, False, 0)
        self.signal = Gauge(colour=TEAL)
        self.body.pack_start(self.signal, False, False, 0)
        self.body.pack_start(button_row(
            button("Networks...", lambda: w95stat.term("nmtui", hold=False), 92),
        ), False, False, 0)

    def apply(self, key, value):
        if key != "network" or not value:
            return
        link = value["link"]
        self.fields["Adapter"].set(
            "%s (%s)" % (link["name"], "wireless" if link["wireless"] else "wired")
            if link else "no adapter up")
        self.fields["Network"].set(value["name"])
        self.fields["Address"].set(link["address"] if link else None)
        strength = value["signal"]
        self.fields["Signal"].set("%d%%" % strength if strength is not None else "n/a")
        self.signal.set_fraction((strength or 0) / 100.0)


class TunnelPanel(Panel):
    TITLE = "Dial-Up Networking"

    def build(self):
        table = grid()
        self.state_field = Field(table, 0, "Tunnel")
        self.body.pack_start(table, False, False, 0)
        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.body.pack_start(self.rows_box, False, False, 0)
        self.rows = {}

    def _row(self, tunnel):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(label(tunnel["name"], bold=True, chars=7), False, False, 0)
        state = label("down")
        row.pack_start(state, True, True, 0)
        action = button("Connect", lambda t=tunnel: self._toggle(t), 88)
        row.pack_end(action, False, False, 0)
        self.rows_box.pack_start(row, False, False, 0)
        row.show_all()
        return {"state": state, "action": action, "up": False}

    def _toggle(self, tunnel):
        row = self.rows.get(tunnel["name"])
        if row and row["up"]:
            w95stat.vpn_down(tunnel["conf"])
        else:
            w95stat.vpn_up(tunnel["conf"])
        # wg-quick runs in a terminal and takes a few seconds to settle.
        GLib.timeout_add_seconds(4, lambda: (self.app.poller.refresh("vpn"), False)[1])

    def apply(self, key, value):
        if key != "vpn" or not value:
            return
        self.state_field.set(value["summary"])
        for tunnel in value["tunnels"]:
            row = self.rows.get(tunnel["name"])
            if row is None:
                row = self.rows[tunnel["name"]] = self._row(tunnel)
            row["up"] = tunnel["up"]
            row["state"].set_text("connected" if tunnel["up"] else "not connected")
            row["action"].set_label("Disconnect" if tunnel["up"] else "Connect")


class BluetoothPanel(Panel):
    TITLE = "Bluetooth"

    def build(self):
        self.power = Gtk.CheckButton(label="Adapter powered on")
        self._power_guard = False
        self.power.connect("toggled", self._toggle_power)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.pack_start(self.power, True, True, 0)
        header.pack_end(button("Manage...",
                               lambda: w95stat.term("bluetoothctl", hold=False), 84),
                        False, False, 0)
        self.body.pack_start(header, False, False, 0)

        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.body.pack_start(self.rows_box, False, False, 0)
        self.rows = {device["mac"]: self._row(device)
                     for device in w95stat.bt_devices()}

    def _row(self, device):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name = label(device["name"], bold=True, chars=7)
        name.set_tooltip_text("%s  (%s)" % (device["mac"], device["kind"]))
        row.pack_start(name, False, False, 0)
        state = label("—", chars=11)
        row.pack_start(state, False, False, 0)
        gauge = Gauge(width=52)
        row.pack_start(gauge, False, False, 0)
        battery = label("", chars=4)
        row.pack_start(battery, False, False, 0)
        action = button("Connect", lambda d=device: self._toggle_device(d), 88)
        row.pack_end(action, False, False, 0)
        self.rows_box.pack_start(row, False, False, 0)
        return {"state": state, "gauge": gauge, "battery": battery,
                "action": action, "connected": False}

    def _toggle_device(self, device):
        row = self.rows.get(device["mac"])
        connect = not (row and row["connected"])
        row["state"].set_text("connecting" if connect else "disconnecting")
        w95stat.bt_connect(device["mac"], connect)
        GLib.timeout_add_seconds(3, self._reprobe)

    def _toggle_power(self, widget):
        if self._power_guard:
            return
        want = widget.get_active()
        self.commit(w95stat.bt_powered, want, lambda: w95stat.bt_power(want))
        GLib.timeout_add_seconds(2, self._reprobe)

    def _reprobe(self):
        self.app.poller.refresh("bluetooth")
        return False

    def apply(self, key, value):
        if key != "bluetooth" or not value:
            return
        self._power_guard = True
        self.power.set_active(value["powered"])
        self._power_guard = False
        for mac, info in value["devices"].items():
            row = self.rows.get(mac)
            if row is None:
                continue
            row["connected"] = info["connected"]
            row["state"].set_text("connected" if info["connected"]
                                  else ("paired" if info["paired"] else "not paired"))
            row["action"].set_label("Disconnect" if info["connected"] else "Connect")
            row["action"].set_sensitive(value["powered"])
            percent = info["battery"]
            row["gauge"].set_fraction((percent or 0) / 100.0)
            row["battery"].set_text("%d%%" % percent if percent is not None else "")


class AudioPanel(Panel):
    TITLE = "Volume Control"

    def build(self):
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.volume.set_draw_value(False)
        self.volume.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.volume.set_hexpand(True)
        # Only push to PulseAudio while the user is actually dragging: the
        # 2-second poll writes the slider back, and without the guard that
        # write would look like a drag and fight the volume keys.
        self._volume_guard = False
        self.volume.connect("value-changed", self._on_volume)
        self.body.pack_start(self.volume, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.readout = label("—", bold=True, chars=12)
        row.pack_start(self.readout, False, False, 0)
        self.mute = Gtk.CheckButton(label="Mute")
        self._mute_guard = False
        self.mute.connect("toggled", self._on_mute)
        row.pack_start(self.mute, False, False, 0)
        row.pack_end(button("Mixer...", lambda: w95stat.spawn(["pavucontrol"]), 78),
                     False, False, 0)
        self.body.pack_start(row, False, False, 0)

        self.body.pack_start(style(Gtk.Box(), "w95-sep"), False, False, 0)
        self.mic_state = label("—", bold=True)
        self.body.pack_start(self.mic_state, False, False, 0)
        self.mic = Gtk.CheckButton(label="Mute microphone   (Super+Space)")
        self._mic_guard = False
        self.mic.connect("toggled", self._on_mic)
        self.body.pack_start(self.mic, False, False, 0)

    def _on_volume(self, scale):
        if self._volume_guard:
            return
        w95stat.set_sink_volume(int(scale.get_value()))
        w95stat.refresh_bar(10)

    def _on_mute(self, widget):
        if self._mute_guard:
            return
        self.commit(lambda: w95stat.sink()["muted"], widget.get_active(),
                    w95stat.toggle_sink_mute)
        w95stat.refresh_bar(10)
        self._resync()

    def _on_mic(self, widget):
        if self._mic_guard:
            return
        self.commit(lambda: w95stat.source()["muted"], widget.get_active(),
                    w95stat.toggle_source_mute)
        w95stat.refresh_bar(11)
        self._resync()

    def _resync(self):
        GLib.timeout_add(250, lambda: (self.app.poller.refresh("audio"), False)[1])

    def apply(self, key, value):
        if key != "audio" or not value:
            return
        sink, source = value["sink"], value["source"]
        self._volume_guard = True
        if abs(self.volume.get_value() - sink["volume"]) >= 1:
            self.volume.set_value(sink["volume"])
        self._volume_guard = False
        self.readout.set_markup("<b>%d%%</b>" % sink["volume"])
        self._mute_guard = True
        self.mute.set_active(sink["muted"])
        self._mute_guard = False
        self._mic_guard = True
        self.mic.set_active(source["muted"])
        self._mic_guard = False
        self.mic_state.set_markup("<b>Microphone is %s</b>"
                                  % ("muted" if source["muted"] else "live"))


class PowerPanel(Panel):
    TITLE = "Power"

    def build(self):
        self.gauge = Gauge(height=18)
        self.body.pack_start(self.gauge, False, False, 0)
        table = grid()
        self.fields = {name: Field(table, row, name) for row, name in
                       enumerate(["Charge", "Status", "Remaining"])}
        self.body.pack_start(table, False, False, 0)
        self.body.pack_start(style(Gtk.Box(), "w95-sep"), False, False, 0)

        self.profiles = {}
        self._profile_guard = False
        self.profile_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.body.pack_start(self.profile_box, False, False, 0)

        self.boost = Gtk.CheckButton(label="CPU frequency boost")
        self._boost_guard = False
        self.boost.connect("toggled", self._on_boost)
        self.body.pack_start(self.boost, False, False, 0)
        self.body.pack_start(button_row(button("Details...", self._details, 80)),
                             False, False, 0)

    @staticmethod
    def _details():
        w95stat.term("upower -i $(upower -e | grep -m1 BAT) || acpi -V")

    def _build_profiles(self, choices):
        # Construction is done behind the guard because creating the first
        # member of a radio group activates it, and the sync that follows would
        # otherwise be indistinguishable from the user having clicked it.
        self._profile_guard = True
        group_widget = None
        for name in choices:
            radio = Gtk.RadioButton.new_with_label_from_widget(group_widget, name)
            group_widget = group_widget or radio
            radio.connect("toggled", self._on_profile, name)
            self.profile_box.pack_start(radio, False, False, 0)
            self.profiles[name] = radio
        self.profile_box.show_all()
        self._profile_guard = False

    def _on_profile(self, widget, name):
        if self._profile_guard or not widget.get_active():
            return
        self.commit(lambda: (w95stat.power_profile() or {}).get("current"), name,
                    lambda: w95stat.set_power_profile(name))
        w95stat.refresh_bar(12)

    def _on_boost(self, widget):
        if self._boost_guard:
            return
        want = widget.get_active()
        self.commit(w95stat.cpu_boost, want, lambda: w95stat.set_cpu_boost(want))
        w95stat.refresh_bar(13)

    def tick(self):
        state = self.app.state
        battery = state.get("battery")
        if battery:
            self.gauge.set_fraction(battery["percent"] / 100.0)
            self.gauge.colour = MAROON if battery["percent"] <= 15 else NAVY
            self.fields["Charge"].set("%d%%" % battery["percent"])
            self.fields["Status"].set(battery["status"])
            if battery["hours"]:
                self.fields["Remaining"].set(
                    "%dh %dm" % (int(battery["hours"]),
                                 int(battery["hours"] % 1 * 60)))
            else:
                self.fields["Remaining"].set(
                    "estimating..." if battery["status"] == "Discharging"
                    else "on AC power")
        else:
            self.fields["Charge"].set("no battery")

        profile = state.get("profile")
        if profile:
            if not self.profiles:
                self._build_profiles(profile["choices"])
            radio = self.profiles.get(profile["current"])
            if radio is not None and not radio.get_active():
                self._profile_guard = True
                radio.set_active(True)
                self._profile_guard = False

        boost = state.get("boost")
        if boost is None:
            self.boost.set_sensitive(False)
        elif boost != self.boost.get_active():
            self._boost_guard = True
            self.boost.set_active(boost)
            self._boost_guard = False


class ClaudePanel(Panel):
    TITLE = "Claude — five-hour window"

    def build(self):
        self.table = grid(4)
        self.body.pack_start(self.table, False, False, 0)
        self.note = label("Fetching...", dim=True)
        self.note.set_ellipsize(Pango.EllipsizeMode.END)
        self.body.pack_start(self.note, False, False, 0)
        self.body.pack_start(button_row(
            button("Switch...", w95stat.claude_switch, 80),
            button("Refresh", self._refresh, 80),
        ), False, False, 0)
        self.rows = {}

    def _refresh(self):
        self.note.set_text("Fetching...")
        self.app.poller.refresh("claude")

    def apply(self, key, value):
        if key != "claude":
            return
        if not value:
            self.note.set_text("No Claude accounts configured.")
            return
        for index, account in enumerate(value):
            row = self.rows.get(account["label"])
            if row is None:
                name = label(account["label"], bold=True, chars=2)
                self.table.attach(name, 0, index, 1, 1)
                gauge = Gauge(colour=NAVY, warn=(0.80, MAROON), height=16)
                gauge.set_hexpand(True)
                self.table.attach(gauge, 1, index, 1, 1)
                readout = label("—", chars=17)
                self.table.attach(readout, 2, index, 1, 1)
                row = self.rows[account["label"]] = {"name": name, "gauge": gauge,
                                                     "readout": readout}
                self.table.show_all()
            percent = account["percent"]
            row["gauge"].set_fraction((percent or 0) / 100.0)
            row["name"].set_markup("<b>%s</b>" % account["label"] if account["active"]
                                   else account["label"])
            text = "%d%%" % percent if percent is not None else "n/a"
            if account["resets"]:
                text += " · %s left" % account["resets"]
            if account["active"]:
                text += " ←"
            row["readout"].set_text(text)
        self.note.set_text("Bold is the account Claude Code is signed in as.")


PANELS = [ResourcesPanel, ComputerPanel, StoragePanel, ConnectionPanel,
          TunnelPanel, BluetoothPanel, AudioPanel, PowerPanel, ClaudePanel]


# ── the window ──────────────────────────────────────────────────────────

class Monitor(Gtk.Window):
    def __init__(self, share, sock, mode=None, hidden=False):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.share = share
        self.mode = mode or w95conf.SYSMON_MODE
        self.visible = False
        self.speed = DEFAULT_SPEED
        self.tick_source = 0
        self.slide_source = 0
        self.state = {}

        self.set_title("System Monitor")
        self.set_wmclass("w95-sysmon" + ("-drop" if self.mode == "drop" else ""),
                         "W95sysmon")
        self.set_role("w95-sysmon")
        self.set_icon_name("utilities-system-monitor")

        self.css = Gtk.CssProvider()
        self.css.load_from_path(os.path.join(share, "w95.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.scale_css = Gtk.CssProvider()
        self.scale_css.load_from_data(w95conf.scale_css())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.scale_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

        if self.mode == "drop":
            # A quake console is not a window you manage: no decoration, above
            # everything, on every workspace, and absent from the pager.
            self.set_decorated(False)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_keep_above(True)
            self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        else:
            self.set_default_size(1180, 720)
            self.set_position(Gtk.WindowPosition.CENTER)

        self._sample_cpu = w95stat.CpuMeter()
        self._sample_net = w95stat.NetMeter()
        self._build()
        self._wire_poller()

        self.connect("delete-event", self._on_delete)
        self.connect("key-press-event", self._on_key)

        # The second press of the keybinding arrives here as a datagram.
        GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, sock.fileno(),
                              GLib.IOCondition.IN, self._on_message, sock)

        # Prime, then start the clock straight away: charting begins at launch,
        # not at the first time the window is looked at. `--hidden` from i3's
        # exec is what makes that worth having — the panel then already knows
        # the last few minutes the first time it is opened.
        self._prime_meters()
        self.sample(full=True)
        self._restart_tick()
        if not hidden:
            self.show_panel()

    # ── chrome ──────────────────────────────────────────────────────────
    def _build(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        if self.mode == "drop":
            style(root, "w95-panel")
            root.set_border_width(2)
            root.pack_start(self._caption(), False, False, 0)
        root.pack_start(self._menubar(), False, False, 0)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        page.set_border_width(7)
        # The charts take the slack. Panels are natural height and the grid is
        # natural height, so whatever is left over after them goes into the
        # scopes — which is the one part of the page that gets better the more
        # room it has, rather than just emptier.
        page.pack_start(self._charts(), True, True, 0)

        # A FlowBox rather than a fixed grid: the same page has to work at
        # 2560px wide as a drop-down panel and at 1180px as a window, and this
        # is the layout that reflows from five columns to three without any
        # arithmetic here about which panel goes where.
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        # Not homogeneous: FlowBox reads that as "every child the same size",
        # rows included, so one tall panel puts a band of empty grey under
        # every short one. The uniform look comes from PANEL_WIDTH instead —
        # every panel asks for the same width, so the columns line up anyway.
        flow.set_homogeneous(False)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(6)
        flow.set_row_spacing(7)
        flow.set_column_spacing(7)
        self.panels = []
        for factory in PANELS:
            panel = factory(self)
            # Without this a FlowBox row stretches every panel to the height of
            # the tallest one in it, so a three-line panel next to Computer's
            # eight becomes a mostly empty box.
            panel.set_valign(Gtk.Align.START)
            flow.add(panel)
            self.panels.append(panel)
        page.pack_start(flow, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(page)
        root.pack_start(scroller, True, True, 0)
        root.pack_end(self._statusbar(), False, False, 0)
        self.add(root)

    def _charts(self):
        self.cpu_series = w95stat.Series(CHART_SAMPLES)
        self.mem_series = w95stat.Series(CHART_SAMPLES)
        self.rx_series = w95stat.Series(CHART_SAMPLES)
        self.tx_series = w95stat.Series(CHART_SAMPLES)
        self.charts = [
            Chart("Processor Usage", [(self.cpu_series, GREEN, "CPU")]),
            Chart("Memory Manager", [(self.mem_series, CYAN, "RAM")]),
            Chart("Network", [(self.rx_series, GREEN, "in"),
                              (self.tx_series, YELLOW, "out")],
                  unit="B/s", maximum=None,
                  formatter=lambda v: w95stat.human_bytes(v) + "/s"),
        ]
        self.chart_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        self.chart_row.set_homogeneous(True)
        for chart in self.charts:
            self.chart_row.pack_start(chart, True, True, 0)
        return self.chart_row

    def _caption(self):
        """The drop panel draws its own title bar; there is no WM one."""
        bar = style(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5),
                    "w95-title")
        bar.pack_start(w95draw.Glyph("window", 14), False, False, 0)
        bar.pack_start(Gtk.Label(label="System Monitor", xalign=0), True, True, 0)
        close = style(Gtk.Button(), "w95-titlebtn")
        close.add(w95draw.title_glyph("close"))
        close.connect("clicked", lambda *_: self.hide_panel())
        bar.pack_end(close, False, False, 0)
        return bar

    def _menubar(self):
        bar = Gtk.MenuBar()

        def action(text, callback, accel=""):
            item = Gtk.MenuItem()
            # A MenuItem builds an AccelLabel of its own the moment it is given
            # a label, and it is a GtkBin — so the child has to go before a row
            # with an accelerator column can go in.
            child = item.get_child()
            if child is not None:
                item.remove(child)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            row.pack_start(Gtk.Label(label=text, use_underline=True, xalign=0),
                           True, True, 0)
            if accel:
                row.pack_end(label(accel, dim=True), False, False, 0)
            item.add(row)
            item.connect("activate", lambda *_: callback())
            return item

        def menu(title, entries):
            item = Gtk.MenuItem(label=title, use_underline=True)
            popup = style(Gtk.Menu(), "w95-menu")
            for entry in entries:
                popup.append(entry if entry is not None else Gtk.SeparatorMenuItem())
            item.set_submenu(popup)
            bar.append(item)

        menu("_File", [
            action("_Refresh Now", self.refresh_all, "F5"),
            None,
            action("_Hide", self.hide_panel, "Esc"),
            action("E_xit", Gtk.main_quit),
        ])

        self.show_charts = Gtk.CheckMenuItem(label="_Charts", use_underline=True)
        self.show_charts.set_active(True)
        self.show_charts.connect("toggled", self._on_charts)
        self.on_top = Gtk.CheckMenuItem(label="Always on _Top", use_underline=True)
        self.on_top.set_active(self.mode == "drop")
        self.on_top.connect("toggled", lambda w: self.set_keep_above(w.get_active()))
        menu("_View", [self.show_charts, self.on_top])

        speeds, group_item = [], None
        for title, interval in SPEEDS:
            item = Gtk.RadioMenuItem(label=title, use_underline=True)
            if group_item is None:
                group_item = item
            else:
                item.join_group(group_item)
            item.set_active(interval == self.speed)
            item.connect("toggled", self._on_speed, interval)
            speeds.append(item)
        menu("_Options", speeds + [None,
             action("Drop-down _panel", lambda: self._set_mode("drop")),
             action("_Window", lambda: self._set_mode("window"))])

        menu("_Help", [action("_About System Monitor...", self._about)])
        return bar

    def _statusbar(self):
        bar = style(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3),
                    "w95-statusbar")
        self.status = style(Gtk.Label(xalign=0), "w95-pane")
        bar.pack_start(self.status, True, True, 0)
        self.status_uptime = style(Gtk.Label(xalign=0), "w95-pane")
        self.status_uptime.set_width_chars(16)
        bar.pack_start(self.status_uptime, False, False, 0)
        self.status_clock = style(Gtk.Label(xalign=0), "w95-pane")
        self.status_clock.set_width_chars(24)
        bar.pack_start(self.status_clock, False, False, 0)
        return bar

    def _about(self):
        dialog = w95menu.Dialog(self.css, "About System Monitor", "window")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        top.pack_start(w95draw.Flag(48), False, False, 0)
        cpu = self.state.get("cpu_info", {})
        host = self.state.get("host", {})
        memory = self.state.get("memory", {})
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        column.pack_start(label("Microsoft Windows 95", bold=True), False, False, 0)
        for line in ("System Monitor  4.00.950",
                     "for i3 %s" % _i3_version(),
                     "",
                     host.get("host", ""),
                     cpu.get("model", ""),
                     "%s RAM" % w95stat.human_bytes(memory.get("total", 0)),
                     "%s %s" % (host.get("system", ""), host.get("kernel", ""))):
            column.pack_start(label(line), False, False, 0)
        top.pack_start(column, True, True, 0)
        dialog.body.pack_start(top, False, False, 0)
        dialog.buttons(("OK", dialog.destroy))
        dialog.show_all()

    # ── polling ─────────────────────────────────────────────────────────
    def _wire_poller(self):
        self.poller = w95stat.Poller(self._dispatch)
        self.poller.add("network", self._probe_network, 10, self._deliver("network"))
        self.poller.add("vpn", self._probe_vpn, 10, self._deliver("vpn"))
        self.poller.add("bluetooth", self._probe_bluetooth, 8, self._deliver("bluetooth"))
        self.poller.add("audio", self._probe_audio, 2, self._deliver("audio"))
        self.poller.add("misc", self._probe_misc, 5, self._deliver("misc"))
        self.poller.add("updates", lambda: w95stat.run_block("updates", timeout=60),
                        900, self._deliver("updates"))
        self.poller.add("claude", w95stat.claude_usage, 180, self._deliver("claude"))
        self.poller.pause(True)
        self.poller.start()

    @staticmethod
    def _dispatch(callback, value):
        GLib.idle_add(callback, value)

    def _deliver(self, key):
        def deliver(value):
            # A probe that timed out returns None; keeping the last good value
            # beats blanking the field every time bluetoothd is slow.
            if value is not None:
                for panel in self.panels:
                    panel.apply(key, value)
            return False
        return deliver

    @staticmethod
    def _probe_network():
        link = w95stat.network_link()
        full, _short, _colour = w95stat.run_block("network")
        return {"link": link, "name": full,
                "signal": w95stat.wifi_signal(link["name"])
                if link and link["wireless"] else None}

    @staticmethod
    def _probe_vpn():
        full, _short, _colour = w95stat.run_block("vpn")
        return {"summary": full or w95stat.vpn_active() or "not connected",
                "tunnels": w95stat.vpn_tunnels()}

    @staticmethod
    def _probe_bluetooth():
        powered = w95stat.bt_powered()
        devices = {}
        for device in w95stat.bt_devices():
            devices[device["mac"]] = (w95stat.bt_info(device["mac"]) if powered
                                      else {"connected": False, "paired": True,
                                            "battery": None})
        return {"powered": powered, "devices": devices}

    @staticmethod
    def _probe_audio():
        return {"sink": w95stat.sink(), "source": w95stat.source()}

    @staticmethod
    def _probe_misc():
        return {"layout": w95stat.keyboard_layout(),
                "recording": w95stat.recording()}

    # ── sampling ────────────────────────────────────────────────────────
    def sample(self, full=None):
        """One pass. `full` adds everything only a visible window needs.

        The charted half runs whether or not anyone is looking, because a strip
        chart whose history begins when you open it is not a strip chart — the
        question it exists to answer is "what happened while I wasn't
        watching". It is also the cheap half: three small reads under
        /proc, microseconds, which is why it can afford to be unconditional.

        Sampling on a fixed interval regardless of visibility is also what
        keeps the x-axis honest. Stop and restart it and the series splices
        two sessions together with no gap drawn between them, while the first
        reading back — both meters here are differential — averages the entire
        absence into one point. A thirty-second CPU burn arrives as a single
        spike, in the wrong place, at the wrong height.
        """
        full = self.visible if full is None else full
        self.state["cpu"] = self._sample_cpu.sample()
        self.state["memory"] = w95stat.memory()
        self.state["temperature"] = w95stat.temperature()
        self.state["rx"], self.state["tx"] = self._sample_net.sample()

        self.cpu_series.push(self.state["cpu"])
        self.mem_series.push(self.state["memory"]["percent"])
        self.rx_series.push(self.state["rx"])
        self.tx_series.push(self.state["tx"])
        if not full:
            return True

        self.state.update({
            "disk": w95stat.disk("/"),
            "uptime": w95stat.uptime_seconds(),
            "load": w95stat.loadavg(),
            "battery": w95stat.battery(),
            "profile": w95stat.power_profile(),
            "boost": w95stat.cpu_boost(),
        })
        self.state.setdefault("cpu_info", w95stat.cpu_info())
        self.state.setdefault("host", w95stat.host_info())

        for chart in self.charts:
            chart.queue_draw()
        for panel in self.panels:
            panel.tick()

        now = time.localtime()
        self.status_clock.set_text(time.strftime("%a %d %b %Y  %H:%M:%S", now))
        self.status_uptime.set_text("Up %s"
                                    % w95stat.human_duration(self.state["uptime"]))
        return True

    def _prime_meters(self):
        """Throw one reading away so the next one means what it says.

        Only needed after Paused, which is the one state that really does stop
        the clock. Both meters are differential, so the first sample after any
        genuine gap covers the whole gap.
        """
        self._sample_cpu.sample()
        self._sample_net.sample()

    def _restart_tick(self):
        if self.tick_source:
            GLib.source_remove(self.tick_source)
            self.tick_source = 0
        if self.speed:
            self.tick_source = GLib.timeout_add(self.speed, self.sample)

    def _on_speed(self, widget, interval):
        if not widget.get_active():
            return
        resuming = interval and not self.speed
        self.speed = interval
        if resuming:
            self._prime_meters()
        self._restart_tick()
        self.status.set_text(
            "Update speed: %s" % ("paused" if not interval
                                  else "%.1f sec" % (interval / 1000.0)))

    def _on_charts(self, widget):
        self.chart_row.set_visible(widget.get_active())

    def refresh_all(self):
        self.sample(full=True)
        self.poller.refresh()
        self.status.set_text("Refreshed.")

    # ── showing and hiding ──────────────────────────────────────────────
    def _workarea(self):
        """The monitor's usable rectangle — struts excluded, so the drop panel
        stops where the taskbar starts instead of hiding behind it."""
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea()

    def show_panel(self):
        if self.mode == "drop":
            area = self._workarea()
            height = int(area.height * w95conf.SYSMON_SIZE)
            self.set_size_request(area.width, height)
            self.resize(area.width, height)
            self.move(area.x, area.y - height)
            self.show_all()
            self.present()
            self._slide(area.x, area.y - height, area.y)
        else:
            self.show_all()
            self.present()
        self.chart_row.set_visible(self.show_charts.get_active())
        self.visible = True
        self.poller.pause(False)
        self.sample(full=True)
        self._restart_tick()
        self.status.set_text("Ready")

    def hide_panel(self):
        if not self.visible:
            return
        self.visible = False
        # The tick keeps running — see sample(). What stops is the poller,
        # which is where the real cost is: bluetoothctl, checkupdates and a
        # curl to the Claude API have no business firing at a hidden window,
        # and unlike the charts they are point-in-time state with no history
        # to miss.
        self.poller.pause(True)
        self.hide()

    def toggle(self):
        # Visible but behind something (or on another screen) means "bring it
        # here", not "put it away" — the key should always end with the monitor
        # in front of you unless it already was.
        if self.visible and self.is_active():
            self.hide_panel()
        elif self.visible:
            self.present()
        else:
            self.show_panel()

    def _slide(self, x, start_y, end_y):
        """Drop the panel in from above.

        i3 honours move requests on floating windows, so this is a real slide;
        it is short enough (~130ms) that a stutter reads as the window arriving
        rather than as lag.
        """
        if self.slide_source:
            GLib.source_remove(self.slide_source)
            self.slide_source = 0
        frames = max(1, SLIDE_MS // 16)
        state = {"frame": 0}

        def step():
            state["frame"] += 1
            progress = min(1.0, state["frame"] / float(frames))
            eased = 1 - (1 - progress) ** 3      # fast off the edge, then settle
            self.move(x, int(start_y + (end_y - start_y) * eased))
            if progress >= 1.0:
                self.slide_source = 0
                return False
            return True

        self.slide_source = GLib.timeout_add(16, step)

    def _set_mode(self, mode):
        """Switch shape, and remember it. Needs a restart, so do that too."""
        if mode == self.mode:
            return
        w95conf.write("sysmon_mode", mode)
        self.status.set_text("Restarting as %s..." % mode)
        GLib.timeout_add(150, lambda: (self._restart(), False)[1])

    def _restart(self):
        script = os.path.expanduser("~/.local/bin/w95-sysmon")
        if not os.path.exists(script):
            script = os.path.realpath(__file__).replace(
                "share/w95/w95sysmon.py", "bin/w95-sysmon")
        # The abstract socket has to be released before the replacement can
        # claim it, so exec rather than spawn-and-quit.
        self.hide()
        try:
            os.execv(script, [script])
        except OSError:
            Gtk.main_quit()

    # ── events ──────────────────────────────────────────────────────────
    def _on_message(self, _fd, _condition, sock):
        try:
            while True:
                sock.recv(64)
        except BlockingIOError:
            pass
        except OSError:
            return True
        self.toggle()
        return True

    def _on_delete(self, *_args):
        # The X button is "put it away", not "quit" — the resident process is
        # what makes the next keypress instant.
        self.hide_panel()
        return True

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.hide_panel()
            return True
        if event.keyval == Gdk.KEY_F5:
            self.refresh_all()
            return True
        return False


def _i3_version():
    try:
        out = subprocess.run(["i3", "--version"], capture_output=True, text=True,
                             timeout=3).stdout
        return out.split("version", 1)[-1].split("(")[0].strip() or "4"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "4"


def run(share, sock, mode=None, hidden=False):
    monitor = Monitor(share, sock, mode=mode, hidden=hidden)
    Gtk.main()
    return monitor
