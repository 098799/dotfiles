"""Caffeine: while it is on, the screen neither locks nor goes dark when idle.

How: niri's own org.freedesktop.ScreenSaver.Inhibit, on the session bus, in-process
(no child). niri then marks its idle notifications (ext-idle-notify) inhibited, and
swayidle (niri-idle: lock at 10 min, screens off at 10.5) asks for exactly those
notifications that obey inhibitors, so it never hears that the seat went idle. niri
drops the inhibitor by itself when bardeck's bus connection goes away (the daemon
died), so none is ever left behind. Verified 13 Oct 2026 in niri 26.04's source
(dbus/freedesktop_screensaver.rs → is_fdo_idle_inhibited → refresh_idle_inhibit) and
swayidle 1.9.0's (enable_timeouts registers with obey_inhibitors), and by a test
`swayidle -w timeout 2 …` that fired only after the inhibitor was released.

Not logind's idle inhibitor (`systemd-inhibit --what=idle`): swayidle 1.9.0 means to
honour it, but its read of BlockInhibited fails ("Failed to parse get BlockInhibited
property: Invalid argument", `swayidle -d`, same day), and it enables its timeouts
anyway.

Modes: on until switched off, for an hour, or until the battery drops below 20%
(while discharging). The mode and its end are kept in $XDG_RUNTIME_DIR/bardeck/caffeine,
so a daemon restart (a waybar reload, a theme switch) takes it up again.
"""

from __future__ import annotations

import time

from . import core

SS = "org.freedesktop.ScreenSaver"
SS_PATH = "/org/freedesktop/ScreenSaver"
STATE = f"{core.RUN_DIR}/caffeine"
LOW = 20  # "battery": off when the battery drops below this
HOUR = 3600

# (mode, chip label)
MODES = (("on", "on"), ("hour", "1 h"), ("battery", f"until {LOW}%"))


class Caffeine:
    def __init__(self, sampler):
        self.s = sampler
        self.mode = ""      # "" (off), "on", "hour", "battery"
        self.until = 0.0    # wall clock, for "hour"
        self.cookie = 0     # niri's inhibitor
        self.error = ""
        self.restored = False

    @property
    def on(self) -> bool:
        return bool(self.mode)

    def _call(self, method: str, args, reply: str | None = None):
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        return bus.call_sync(SS, SS_PATH, SS, method, args, GLib.VariantType(reply) if reply else None,
                             Gio.DBusCallFlags.NONE, 1000, None)

    def set(self, mode: str) -> bool:
        """Switch to mode ("" = off). A panel button's action: False keeps the panel."""
        if not mode:
            self.off()
            return False
        if not self.cookie:
            from gi.repository import GLib

            try:
                self.cookie = self._call("Inhibit", GLib.Variant("(ss)", ("bardeck", "caffeine (the bar)")),
                                         "(u)").unpack()[0]
            except GLib.Error as err:
                self.error = (err.message or "failed").rsplit(":", 1)[-1].strip()[:50]
                core.log(f"caffeine: {err.message}")
                return False
        self.mode, self.error = mode, ""
        self.until = time.time() + HOUR if mode == "hour" else 0.0
        self.save()
        return False

    def off(self) -> None:
        if self.cookie:
            from gi.repository import GLib

            try:
                self._call("UnInhibit", GLib.Variant("(u)", (self.cookie,)))
            except GLib.Error as err:  # niri restarted: the inhibitor went with it
                core.log(f"caffeine off: {err.message}")
        self.cookie, self.mode, self.until = 0, "", 0.0
        self.save()

    def battery_low(self) -> bool:
        b = self.s.bat
        try:
            return b.get("status") == "Discharging" and int(b.get("capacity") or 100) < LOW
        except ValueError:
            return False

    def check(self) -> None:
        """Every second (the power strip): end a mode whose time came."""
        if not self.restored:
            self.restore()
        if self.mode == "hour" and time.time() >= self.until:
            self.off()
        elif self.mode == "battery" and self.battery_low():
            self.off()

    def words(self) -> str:
        """How long it stays on, for the panel."""
        if self.mode == "hour":
            return f"{max(1, round((self.until - time.time()) / 60))} min left"
        if self.mode == "battery":
            return f"until the battery is below {LOW}%"
        if self.mode == "on":
            return "until switched off"
        return ""

    def save(self) -> None:
        try:
            with open(STATE, "w") as fh:
                fh.write(f"{self.mode} {self.until:.0f}\n" if self.mode else "")
        except OSError:
            pass

    def restore(self) -> None:
        """Take up the mode a previous daemon had (on the first check: only the daemon checks)."""
        self.restored = True
        parts = core.read(STATE).split()
        if not parts or parts[0] not in dict(MODES):
            return
        until = float(parts[1]) if len(parts) > 1 else 0.0
        if parts[0] == "hour" and until <= time.time():
            self.save()  # it ran out while no daemon ran
            return
        self.set(parts[0])
        if parts[0] == "hour":
            self.until = until
            self.save()
