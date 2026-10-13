"""The Bluetooth devices BlueZ knows, and pairing a new one: bluetoothctl's scan, pair,
trust, connect, disconnect and remove, done over BlueZ's D-Bus API in-process.

While the devices panel is open, `objs` mirrors BlueZ's objects: one
GetManagedObjects when it opens (async: the reply lands on the main loop), then
BlueZ's own signals keep it current (the Sampler subscribes to them anyway, for the
strip). Nothing is kept while the panel is closed. Discovery (scan) runs only when
asked, SCAN_FOR seconds, and stops when the panel closes: an inquiry makes Bluetooth
audio stutter, so opening the panel never scans by itself.

Pairing needs an agent, for the codes. org.bluez.Agent1 is exported on the bar's
own system-bus connection (the one that calls Pair, so BlueZ asks it), and
registered (RegisterAgent + RequestDefaultAgent) only while a pairing runs:
blueman-applet is the default agent on this machine, and BlueZ gives that role back
to it when ours unregisters (it keeps a stack of default agents). A question the
agent must answer waits in `request` with its Gio.DBusMethodInvocation until the
panel answers it; closing the panel cancels it.

A connect, pair, disconnect or remove runs on a thread of its own and says how it
went in `status`, which the panel shows on the device's row (as wifi.py does)."""

from __future__ import annotations

import re
import threading
import time

from . import core

BLUEZ = "org.bluez"
ADAPTER, DEVICE, BATTERY = "org.bluez.Adapter1", "org.bluez.Device1", "org.bluez.Battery1"
KEPT = (ADAPTER, DEVICE, BATTERY)  # the interfaces the mirror keeps
OM = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
AGENT_PATH = "/eu/grining/bardeck/agent"
CAPABILITY = "KeyboardDisplay"
SCAN_FOR = 25  # seconds of discovery per scan
# Device1 properties that change with every advertisement while anything scans: they
# move no strip, so the Sampler does not re-read BlueZ for them (noise()).
NOISE = {"RSSI", "TxPower", "ManufacturerData", "ServiceData", "AdvertisingFlags", "AdvertisingData"}

AGENT_XML = """<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode">
      <arg type="o" direction="in"/><arg type="s" direction="out"/>
    </method>
    <method name="DisplayPinCode">
      <arg type="o" direction="in"/><arg type="s" direction="in"/>
    </method>
    <method name="RequestPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="out"/>
    </method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation">
      <arg type="o" direction="in"/><arg type="u" direction="in"/>
    </method>
    <method name="RequestAuthorization">
      <arg type="o" direction="in"/>
    </method>
    <method name="AuthorizeService">
      <arg type="o" direction="in"/><arg type="s" direction="in"/>
    </method>
    <method name="Cancel"/>
  </interface>
</node>"""


class BtDevice:
    """One device as the list shows it."""

    __slots__ = ("path", "mac", "name", "named", "icon", "paired", "trusted", "connected", "rssi",
                 "battery", "adapter")

    def __init__(self, path: str, dev: dict, bat: dict | None):
        self.path = path
        self.mac = dev.get("Address", "")
        self.named = "Name" in dev
        self.name = dev.get("Alias") or dev.get("Name") or self.mac
        self.icon = dev.get("Icon", "")
        self.paired = bool(dev.get("Paired") or dev.get("Bonded"))
        self.trusted = bool(dev.get("Trusted"))
        self.connected = bool(dev.get("Connected"))
        self.rssi = dev.get("RSSI")  # only while it is seen by a scan
        self.battery = int(bat["Percentage"]) if bat and "Percentage" in bat else None
        self.adapter = dev.get("Adapter", "")

    @property
    def signal(self) -> int | None:
        """RSSI as 0-100: -95 dBm and weaker is 0, -45 dBm and stronger 100."""
        return None if self.rssi is None else max(0, min(100, (int(self.rssi) + 95) * 2))


class Request:
    """A question from BlueZ's pairing, waiting for the panel.

    kind: "pin" / "passkey" (type it), "confirm" (do both show `code`?), "show" (type
    `code` on the device; `entered` keys so far). invocation is None for "show": BlueZ
    asked nothing, it only says what to type."""

    __slots__ = ("kind", "path", "invocation", "code", "entered")

    def __init__(self, kind: str, path: str, invocation=None, code: str = "", entered: int = 0):
        self.kind, self.path, self.invocation, self.code, self.entered = kind, path, invocation, code, entered


class Bluez:
    def __init__(self, sampler):
        self.s = sampler
        self.objs: dict | None = None  # path -> {interface: props}; None while closed
        self.status: dict[str, tuple[str, str]] = {}  # device path -> (tone, words)
        self.request: Request | None = None
        self.pairing = ""          # the device a pairing runs for
        self.scan_until = 0.0      # our discovery's end (monotonic); 0 = we do not scan
        self._scan_timer = 0
        self._agent_id = 0         # the export's registration id
        self._owner = ""           # bluetoothd's unique bus name: the only caller the agent answers
        self._busy: set[str] = set()

    # -- the mirror (main loop) ------------------------------------------------

    def open(self) -> None:
        """The panel opened: mirror BlueZ until it closes."""
        from gi.repository import Gio, GLib

        self.objs = {}

        def done(bus, res, _data=None):
            try:
                objs = bus.call_finish(res).unpack()[0]
            except Exception as err:
                core.log(f"bluez: {err!r}")
                return
            if self.objs is not None:
                self.objs = keep(objs)

        self.s._bus().call(BLUEZ, "/", OM, "GetManagedObjects", None, GLib.VariantType("(a{oa{sa{sv}}})"),
                           Gio.DBusCallFlags.NONE, 2000, None, done, None)

    def load(self) -> None:
        """The mirror, read now (renders and tests: no main loop to wait on)."""
        self.objs = keep(self.s._dbus(BLUEZ, "/", OM, "GetManagedObjects", None, "(a{oa{sa{sv}}})")[0])

    def close(self) -> None:
        """The panel closed: stop our scan, cancel a pairing and its question."""
        self.stop_scan()
        if self.pairing:
            self.cancel_pairing()
        self.objs = None

    def watch(self, bus) -> None:
        """On the main loop: BlueZ's signals keep the mirror current while it is kept."""
        from gi.repository import Gio

        for iface, member in ((PROPS, "PropertiesChanged"), (OM, "InterfacesAdded"), (OM, "InterfacesRemoved")):
            bus.signal_subscribe(BLUEZ, iface, member, None, None, Gio.DBusSignalFlags.NONE, self._signal)

    def _signal(self, _bus, _sender, path, _iface, member, params, *_data) -> None:
        objs = self.objs
        if objs is None:
            return
        args = params.unpack()
        if member == "PropertiesChanged":
            iface, changed, gone = args
            if iface in KEPT and path in objs:
                props = objs[path].setdefault(iface, {})
                props.update(changed)
                for key in gone:
                    props.pop(key, None)
        elif member == "InterfacesAdded":
            obj, ifaces = args
            kept = {k: v for k, v in ifaces.items() if k in KEPT}
            if kept:
                objs.setdefault(obj, {}).update(kept)
        elif member == "InterfacesRemoved":
            obj, ifaces = args
            if obj in objs:
                for iface in ifaces:
                    objs[obj].pop(iface, None)
                if DEVICE not in objs[obj] and ADAPTER not in objs[obj]:
                    del objs[obj]
                    self.status.pop(obj, None)

    # -- what the panel reads --------------------------------------------------

    def adapter(self) -> tuple[str, dict]:
        for path, ifs in (self.objs or {}).items():
            if ADAPTER in ifs:
                return path, ifs[ADAPTER]
        return "", {}

    @property
    def discovering(self) -> bool:
        return bool(self.adapter()[1].get("Discovering"))

    def devices(self, unnamed: bool = False) -> list[BtDevice]:
        """Connected first, then paired (by name), then the ones a scan found (by
        signal). A found device with no name only when `unnamed`."""
        out = []
        for path, ifs in (self.objs or {}).items():
            dev = ifs.get(DEVICE)
            if dev is None:
                continue
            d = BtDevice(path, dev, ifs.get(BATTERY))
            if d.paired or d.connected or d.named or unnamed or path == self.pairing:
                out.append(d)
        return sorted(out, key=lambda d: (not d.connected, not d.paired, not d.named,
                                          -(d.rssi if d.rssi is not None else -999), d.name.lower()))

    def unnamed_count(self) -> int:
        return sum(1 for ifs in (self.objs or {}).values()
                   if DEVICE in ifs and "Name" not in ifs[DEVICE]
                   and not ifs[DEVICE].get("Paired") and not ifs[DEVICE].get("Connected"))

    def settle(self) -> None:
        """Forget the outcomes of past attempts (a new opening): keep what still runs."""
        self.status = {k: v for k, v in self.status.items() if v[0] == "warn"}

    # -- scanning ----------------------------------------------------------------

    def scan(self) -> None:
        """Start a scan of SCAN_FOR seconds, or stop ours."""
        if self.scan_until:
            self.stop_scan()
            return
        path, props = self.adapter()
        if not path or not props.get("Powered"):
            return
        from gi.repository import GLib

        self.scan_until = time.monotonic() + SCAN_FOR
        self._scan_timer = GLib.timeout_add_seconds(SCAN_FOR, lambda: self.stop_scan() or False)

        def go():
            try:
                self._call(path, ADAPTER, "StartDiscovery")
            except Exception:
                self.scan_until = 0.0  # no countdown for a scan that did not start
                raise

        self._run("", go, quiet=True)

    def stop_scan(self) -> None:
        if not self.scan_until:
            return
        self.scan_until = 0.0
        if self._scan_timer:
            from gi.repository import GLib

            GLib.source_remove(self._scan_timer)
            self._scan_timer = 0
        path = self.adapter()[0] or "/org/bluez/hci0"
        self._run("", lambda: self._call(path, ADAPTER, "StopDiscovery"), quiet=True)

    # -- acting (a thread each) -------------------------------------------------

    def _call(self, path: str, iface: str, method: str, args=None, timeout: float = 2.0):
        from gi.repository import Gio, GLib

        params = GLib.Variant(*args) if args else None
        return self.s._bus().call_sync(BLUEZ, path, iface, method, params, None, Gio.DBusCallFlags.NONE,
                                       int(timeout * 1000), None).unpack()

    def _run(self, path: str, fn, quiet: bool = False) -> None:
        def body():
            if path and path in self._busy:
                self.status[path] = ("warn", "busy")
                return
            self._busy.add(path)
            try:
                fn()
            except Exception as err:
                if not quiet:
                    self.status[path] = ("hit", f"failed: {short_error(err)}")
                core.log(f"bluez {path or 'adapter'}: {err!r}")
            finally:
                self._busy.discard(path)
                self.s.poke()

        threading.Thread(target=body, daemon=True).start()

    def activate(self, d: BtDevice) -> None:
        """A click on a row: connect a paired device, pair (trust, connect) a new one."""
        if d.connected or self.status.get(d.path, ("",))[0] == "warn":
            return
        if d.paired:
            self.connect(d)
        else:
            self.pair(d)

    def connect(self, d: BtDevice) -> None:
        self.status[d.path] = ("warn", "connecting")

        def go():
            self._call(d.path, DEVICE, "Connect", timeout=30)
            self.status.pop(d.path, None)  # the row's mark says it

        self._run(d.path, go)

    def disconnect(self, d: BtDevice) -> None:
        self.status[d.path] = ("warn", "disconnecting")

        def go():
            self._call(d.path, DEVICE, "Disconnect", timeout=10)
            self.status.pop(d.path, None)

        self._run(d.path, go)

    def forget(self, d: BtDevice) -> None:
        """bluetoothctl's remove: unpair, and BlueZ forgets the device."""
        adapter = d.adapter or self.adapter()[0]
        self.status[d.path] = ("warn", "removing")

        def go():
            self._call(adapter, ADAPTER, "RemoveDevice", ("(o)", (d.path,)), timeout=10)
            self.status.pop(d.path, None)

        self._run(d.path, go)

    def pair(self, d: BtDevice) -> None:
        """Pair with our agent registered, then trust and connect: bluetoothctl's
        `pair`, `trust`, `connect` in one go."""
        if self.pairing:
            self.status[d.path] = ("warn", "busy")  # one pairing at a time
            return
        self.export()
        self.pairing = d.path
        self.request = None
        self.status[d.path] = ("warn", "pairing")

        def go():
            from gi.repository import GLib

            registered = False
            try:
                self._owner = self.s._dbus("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                           "GetNameOwner", ("(s)", (BLUEZ,)))[0]
                self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                           ("(os)", (AGENT_PATH, CAPABILITY)))
                registered = True
                self._call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", ("(o)", (AGENT_PATH,)))
                self._call(d.path, DEVICE, "Pair", timeout=90)
            finally:
                if registered:
                    try:
                        self._call("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent", ("(o)", (AGENT_PATH,)))
                    except Exception:  # bluetoothd went away, or it released us first
                        pass
                self.pairing = ""
                self.drop_request("org.bluez.Error.Canceled")
            self.status[d.path] = ("warn", "connecting")
            self._call(d.path, PROPS, "Set", ("(ssv)", (DEVICE, "Trusted", GLib.Variant("b", True))))
            self._call(d.path, DEVICE, "Connect", timeout=30)
            self.status.pop(d.path, None)

        self._run(d.path, go)

    def cancel_pairing(self) -> None:
        path = self.pairing
        self.drop_request("org.bluez.Error.Canceled")
        if path:
            self._run("", lambda: self._call(path, DEVICE, "CancelPairing"), quiet=True)

    # -- the agent (BlueZ calls it on the main loop) -----------------------------

    def export(self) -> None:
        """Export org.bluez.Agent1 at AGENT_PATH (once; BlueZ calls it only while registered)."""
        if self._agent_id:
            return
        from gi.repository import Gio

        info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
        self._agent_id = self.s._bus().register_object(AGENT_PATH, info, self._agent_call, None, None)

    def _agent_call(self, _bus, sender, _path, _iface, method, params, inv, *_data) -> None:
        if self._owner and sender != self._owner:
            inv.return_dbus_error("org.bluez.Error.Rejected", "only bluetoothd may ask")
            return
        args = params.unpack()
        dev = args[0] if args else ""
        if core.TRACE:
            core.log(f"agent: {method}{args!r}")
        if method in ("Release", "Cancel"):
            if method == "Cancel":
                self.drop_request("org.bluez.Error.Canceled")
            inv.return_value(None)
        elif method in ("RequestAuthorization", "AuthorizeService"):
            if self.allowed(dev):
                inv.return_value(None)
            else:
                inv.return_dbus_error("org.bluez.Error.Rejected", "not the device being paired")
        elif dev != self.pairing:  # a code for some other device: not ours to answer
            inv.return_dbus_error("org.bluez.Error.Rejected", "not the device being paired")
        elif method in ("RequestPinCode", "RequestPasskey"):
            self.drop_request("org.bluez.Error.Canceled")
            self.request = Request("pin" if method == "RequestPinCode" else "passkey", dev, inv)
        elif method == "RequestConfirmation":
            self.drop_request("org.bluez.Error.Canceled")
            self.request = Request("confirm", dev, inv, code=f"{args[1]:06d}")
        elif method in ("DisplayPinCode", "DisplayPasskey"):
            code = args[1] if method == "DisplayPinCode" else f"{args[1]:06d}"
            self.request = Request("show", dev, None, code=code, entered=args[2] if len(args) > 2 else 0)
            inv.return_value(None)
        else:
            inv.return_dbus_error("org.bluez.Error.Rejected", f"{method} is not handled")

    def allowed(self, path: str) -> bool:
        """Authorize the device being paired, and paired or trusted ones."""
        if path == self.pairing:
            return True
        ifs = (self.objs or {}).get(path)
        try:
            dev = ifs[DEVICE] if ifs else self.s._props(BLUEZ, path, DEVICE)
        except Exception:
            return False
        return bool(dev.get("Trusted") or dev.get("Paired"))

    def answer(self, value: str = "") -> bool:
        """Reply to the waiting question: the PIN or passkey typed, or yes to a
        confirmation. False when the value cannot be the answer."""
        from gi.repository import GLib

        r = self.request
        if r is None or r.invocation is None:
            return False
        if r.kind == "pin":
            if not 1 <= len(value) <= 16:
                return False
            r.invocation.return_value(GLib.Variant("(s)", (value,)))
        elif r.kind == "passkey":
            if not value.isdigit() or int(value) > 999999:
                return False
            r.invocation.return_value(GLib.Variant("(u)", (int(value),)))
        else:
            r.invocation.return_value(None)
        self.request = None
        return True

    def drop_request(self, error: str = "org.bluez.Error.Rejected") -> None:
        """Say no to the waiting question (Rejected: the user said no; Canceled: gone)."""
        r, self.request = self.request, None
        if r is not None and r.invocation is not None:
            r.invocation.return_dbus_error(error, "the user said no" if error.endswith("Rejected") else "canceled")


def keep(objs: dict) -> dict:
    """The interfaces the mirror needs from GetManagedObjects' answer."""
    out = {}
    for path, ifs in objs.items():
        kept = {k: v for k, v in ifs.items() if k in KEPT}
        if kept:
            out[path] = kept
    return out


def noise(member: str, path: str, params, connected: dict) -> bool:
    """A BlueZ signal that changes nothing the strip shows: an advertisement's RSSI,
    a device a scan found or lost. (Thousands while scanning; each used to cost a
    full re-read.)"""
    try:
        args = params.unpack()
    except Exception:
        return False
    if member == "PropertiesChanged":
        iface, changed, gone = args
        return iface == DEVICE and bool(changed or gone) and set(changed) | set(gone) <= NOISE
    if member == "InterfacesAdded":
        dev = args[1].get(DEVICE)
        return dev is not None and not dev.get("Connected")
    if member == "InterfacesRemoved":
        mac = args[0].rsplit("/dev_", 1)[-1].replace("_", ":") if "/dev_" in args[0] else ""
        return bool(mac) and mac not in connected
    return False


REASONS = {"AuthenticationFailed": "wrong code?", "AuthenticationCanceled": "canceled",
           "AuthenticationRejected": "rejected", "AuthenticationTimeout": "timed out",
           "ConnectionAttemptFailed": "no answer", "NotReady": "Bluetooth is off", "InProgress": "busy",
           "AlreadyExists": "already paired", "DoesNotExist": "gone", "Canceled": "canceled",
           "Rejected": "rejected", "NotAvailable": "not available"}


def short_error(err: Exception) -> str:
    """BlueZ's error as a few words for the row."""
    msg = getattr(err, "message", None) or str(err)
    m = re.search(r"org\.bluez\.Error\.(\w+):?\s*(.*)", msg)
    if m:
        name, detail = m.groups()
        if name in REASONS:
            return REASONS[name]
        if "page-timeout" in detail or "timeout" in detail.lower():
            return "no answer"
        detail = detail.replace("br-connection-", "").replace("le-connection-", "").replace("-", " ")
        return (detail or name)[:28]
    if "Timeout was reached" in msg:
        return "timed out"
    return msg.rsplit(":", 1)[-1].strip()[:28] or "?"
