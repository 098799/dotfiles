"""The Wi-Fi networks in range, and joining one: nmtui's "Activate a connection",
done over NetworkManager's D-Bus API in-process.

The sampler's worker thread calls read() while the network panel is open (the list
costs a GetAll per access point, ~1 ms each); nothing runs while it is closed. A
connect, disconnect or forget runs on a thread of its own and says how it went in
`status`, which the panel shows on the network's row.

Joining: a saved profile is activated as it is. A new network gets a new profile
with the password the panel asks for (WPA-PSK or SAE, from the access point's
flags); NetworkManager completes the rest. When that fails, the profile it made is
deleted again, so a wrong password is never kept. Enterprise (802.1X) and WEP go to
nmtui in a terminal: they need more than one field."""

from __future__ import annotations

import threading
import time

from . import core

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"

# NM80211ApSecurityFlags (WpaFlags / RsnFlags) and NM80211ApFlags.
KEY_PSK, KEY_8021X, KEY_SAE, KEY_OWE, KEY_OWE_TM = 0x100, 0x200, 0x400, 0x800, 0x1000
AP_PRIVACY = 0x1
# NMActiveConnectionState and NMDeviceState.
AC_ACTIVATED, AC_DEACTIVATED = 2, 4
DEV_NEED_AUTH = 60
# NMDeviceStateReason values that mean the password was wrong (or missing).
SECRET_REASONS = {7, 8, 9, 10, 11}

SAVED_EVERY = 30.0  # seconds between re-reads of the saved profiles while open


class Network:
    """One SSID: every access point that sends it, merged."""

    __slots__ = ("ssid", "strength", "bands", "flags", "wpa", "rsn", "ap", "saved", "active")

    def __init__(self, ssid: str):
        self.ssid = ssid
        self.strength = 0
        self.bands: set[str] = set()
        self.flags = self.wpa = self.rsn = 0
        self.ap = "/"        # the strongest access point's object path
        self.saved = ""      # the saved profile's object path, or ""
        self.active = False

    @property
    def keys(self) -> int:
        return self.wpa | self.rsn

    @property
    def open(self) -> bool:
        return not (self.flags & AP_PRIVACY) or bool(self.keys & (KEY_OWE | KEY_OWE_TM))

    @property
    def enterprise(self) -> bool:
        return bool(self.keys & KEY_8021X)

    @property
    def wep(self) -> bool:
        return bool(self.flags & AP_PRIVACY) and not self.keys

    @property
    def security(self) -> str:
        if self.open:
            return "OWE" if self.keys & (KEY_OWE | KEY_OWE_TM) else "open"
        if self.enterprise:
            return "802.1X"
        if self.wep:
            return "WEP"
        if self.keys & KEY_SAE and self.keys & KEY_PSK:
            return "WPA2/3"
        if self.keys & KEY_SAE:
            return "WPA3"
        return "WPA2" if self.rsn else "WPA"


def band(freq: int) -> str:
    return "6" if freq >= 5925 else ("5" if freq >= 4900 else "2.4")


class Wifi:
    def __init__(self, sampler):
        self.s = sampler
        self.networks: list[Network] = []  # replaced whole by the worker
        self.status: dict[str, tuple[str, str]] = {}  # ssid -> (tone, words), for the rows
        self.ask: str | None = None  # an SSID whose saved password failed: the panel asks again
        self.scanned_at = 0.0
        self.want_scan = False
        self._device = ""
        self._iface = ""
        self._saved: dict[str, str] = {}
        self._saved_at = 0.0
        self._busy = threading.Lock()

    # -- reading (the sampler's worker thread) ---------------------------------

    def device(self, iface: str) -> str:
        if iface != self._iface or not self._device:
            self._device = self.s._dbus(NM, NM_PATH, NM, "GetDeviceByIpIface", ("(s)", (iface,)))[0]
            self._iface = iface
        return self._device

    def read(self, iface: str, active_ssid: str | None, active_strength: int | None = None) -> None:
        try:
            dev = self.device(iface)
            if self.want_scan:
                self.want_scan = False
                self.scanned_at = time.monotonic()
                try:
                    self.s._dbus(NM, dev, f"{NM}.Device.Wireless", "RequestScan", ("(a{sv})", ({},)))
                except Exception:  # NM refuses a scan right after another one: the list is fresh
                    pass
            if time.monotonic() - self._saved_at > SAVED_EVERY:
                self._saved = self.saved_profiles()
                self._saved_at = time.monotonic()
            aps = self.s._dbus(NM, dev, f"{NM}.Device.Wireless", "GetAllAccessPoints")[0]
        except Exception as err:
            if core.TRACE:
                core.log(f"wifi list: {err!r}")
            return
        nets: dict[str, Network] = {}
        for path in aps:
            try:
                ap = self.s._props(NM, path, f"{NM}.AccessPoint")
            except Exception:  # gone between the list and the read
                continue
            ssid = bytes(ap.get("Ssid", b"")).decode(errors="replace")
            if not ssid:  # hidden
                continue
            n = nets.get(ssid) or nets.setdefault(ssid, Network(ssid))
            strength = int(ap.get("Strength", 0))
            if strength > n.strength:
                n.strength, n.ap = strength, path
            n.bands.add(band(int(ap.get("Frequency", 0))))
            n.flags |= int(ap.get("Flags", 0))
            n.wpa |= int(ap.get("WpaFlags", 0))
            n.rsn |= int(ap.get("RsnFlags", 0))
        for n in nets.values():
            n.saved = self._saved.get(n.ssid, "")
            n.active = n.ssid == active_ssid
            if n.active and active_strength is not None:
                n.strength = active_strength  # the access point in use, as the header says
        # nmtui's order: the one in use, then by signal.
        self.networks = sorted(nets.values(), key=lambda n: (not n.active, -n.strength, n.ssid.lower()))

    def saved_profiles(self) -> dict[str, str]:
        """SSID -> the saved profile's path, for every Wi-Fi profile."""
        out = {}
        for path in self.s._dbus(NM, SETTINGS_PATH, f"{NM}.Settings", "ListConnections")[0]:
            try:
                st = self.s._dbus(NM, path, f"{NM}.Settings.Connection", "GetSettings")[0]
            except Exception:
                continue
            w = st.get("802-11-wireless")
            if st.get("connection", {}).get("type") == "802-11-wireless" and w and w.get("ssid"):
                out[bytes(w["ssid"]).decode(errors="replace")] = path
        return out

    # -- acting (a thread each) -------------------------------------------------

    def _run(self, ssid: str, fn) -> None:
        def body():
            if not self._busy.acquire(blocking=False):
                self.status[ssid] = ("warn", "busy")
                return
            try:
                fn()
            except Exception as err:
                self.status[ssid] = ("hit", short_error(err))
                core.log(f"wifi {ssid}: {err!r}")
            finally:
                self._busy.release()
                self._saved_at = 0.0  # re-read the profiles: one may be new, or gone
                self.s.poke()

        threading.Thread(target=body, daemon=True).start()

    def settle(self) -> None:
        """Forget the outcomes of past attempts (a new opening): keep what still runs."""
        self.status = {k: v for k, v in self.status.items() if v[0] == "warn"}

    def needs_password(self, n: Network) -> bool:
        return not n.saved and not n.open and not n.enterprise and not n.wep

    def connect(self, n: Network, password: str | None = None) -> None:
        """Join n: its saved profile, or a new one (with `password` when it is secured)."""
        if not n.saved and (n.enterprise or n.wep):
            core.spawn(["alacritty", "-e", "nmtui-connect", n.ssid])
            return
        self.status[n.ssid] = ("warn", "connecting")
        self.ask = None

        def go():
            from gi.repository import GLib

            dev = self._device
            created = ""
            if n.saved and password is None:
                active = self.s._dbus(NM, NM_PATH, NM, "ActivateConnection", ("(ooo)", (n.saved, dev, "/")))[0]
            else:
                if n.saved:  # a new password for a saved network: start that profile over
                    self.s._dbus(NM, n.saved, f"{NM}.Settings.Connection", "Delete")
                settings = {}
                if password is not None:
                    mgmt = "sae" if (n.keys & KEY_SAE and not n.keys & KEY_PSK) else "wpa-psk"
                    settings["802-11-wireless-security"] = {"key-mgmt": GLib.Variant("s", mgmt),
                                                            "psk": GLib.Variant("s", password)}
                created, active = self.s._dbus(NM, NM_PATH, NM, "AddAndActivateConnection",
                                               ("(a{sa{sv}}oo)", (settings, dev, n.ap)))
            ok, reason = self.watch(active, n.ssid)
            if ok:
                self.status.pop(n.ssid, None)  # the row's check mark says it
                return
            if created:
                try:
                    self.s._dbus(NM, created, f"{NM}.Settings.Connection", "Delete")
                except Exception:
                    pass
            if reason in SECRET_REASONS:
                self.status[n.ssid] = ("hit", "wrong password?")
                self.ask = n.ssid
            else:
                self.status[n.ssid] = ("hit", "failed")

        self._run(n.ssid, go)

    def watch(self, active: str, ssid: str, limit: float = 45.0) -> tuple[bool, int]:
        """Wait for the activation: (True, 0) when up, else (False, the device's reason)."""
        end = time.monotonic() + limit
        while time.monotonic() < end:
            time.sleep(0.5)
            try:
                state = int(self.s._props(NM, active, f"{NM}.Connection.Active").get("State", 0))
            except Exception:  # the active connection is gone: it failed
                state = AC_DEACTIVATED
            if state == AC_ACTIVATED:
                return True, 0
            dev = self.s._props(NM, self._device, f"{NM}.Device")
            if state == AC_DEACTIVATED:
                return False, int(dev.get("StateReason", (0, 0))[1])
            if int(dev.get("State", 0)) == DEV_NEED_AUTH:
                self.status[ssid] = ("warn", "authenticating")
            self.s.poke()
        return False, 0

    def disconnect(self, n: Network) -> None:
        self.status[n.ssid] = ("warn", "disconnecting")

        def go():
            self.s._dbus(NM, self._device, f"{NM}.Device", "Disconnect")
            self.status.pop(n.ssid, None)

        self._run(n.ssid, go)

    def forget(self, n: Network) -> None:
        if not n.saved:
            return

        def go():
            self.s._dbus(NM, n.saved, f"{NM}.Settings.Connection", "Delete")
            self.status.pop(n.ssid, None)

        self._run(n.ssid, go)


def short_error(err: Exception) -> str:
    msg = getattr(err, "message", None) or str(err)
    return msg.rsplit(":", 1)[-1].strip()[:40] or "failed"
