"""Tailscale, for the network panel: this node and every peer, read from tailscaled's
local API in-process (an HTTP GET over /var/run/tailscale/tailscaled.sock, ~1 ms),
only while the panel is open, at most every READ_EVERY seconds, on the sampler's
worker thread. When the socket cannot be read, `tailscale status --json` instead.

A ping (the local API's disco ping, or `tailscale ping -c 1`) runs only when asked
(a row's "ping" chip, or `t`), on a thread of its own; its outcome says the latency
and whether the path is direct or through a DERP relay.

Nothing here changes tailscaled's state but `set_exit_node`, and that only when the
user is tailscaled's operator (or root): otherwise the panel says so instead."""

from __future__ import annotations

import http.client
import json
import os
import pwd
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone

from . import core

SOCKET = "/var/run/tailscale/tailscaled.sock"
USER = pwd.getpwuid(os.getuid()).pw_name
READ_EVERY = 5.0
PING_TIMEOUT = 4.0

OS_GLYPH = {"linux": "", "android": "", "macOS": "", "iOS": "", "windows": ""}
OS_OTHER = ""


class Peer:
    __slots__ = ("id", "name", "host", "os", "ip", "online", "seen", "relay", "addr", "active",
                 "exit_option", "exit_node", "me")

    def __init__(self, raw: dict, me: bool = False):
        self.id = raw.get("ID", "")
        self.name = raw.get("HostName") or "?"
        # The MagicDNS name's first label: what ssh and the copy want ("POCO F7 Ultra" → poco-f7-ultra).
        self.host = (raw.get("DNSName") or "").split(".")[0] or self.name
        self.os = raw.get("OS") or ""
        self.ip = next((a for a in raw.get("TailscaleIPs") or [] if ":" not in a), "")
        self.online = bool(raw.get("Online"))
        self.seen = _when(raw.get("LastSeen"))  # epoch seconds, or 0 when unknown
        self.relay = raw.get("Relay") or ""      # its home DERP region
        self.addr = raw.get("CurAddr") or ""      # set while the path is direct
        self.active = bool(raw.get("Active"))     # traffic lately: the path is known
        self.exit_option = bool(raw.get("ExitNodeOption"))
        self.exit_node = bool(raw.get("ExitNode"))
        self.me = me

    @property
    def glyph(self) -> str:
        return OS_GLYPH.get(self.os, OS_OTHER)

    @property
    def shell(self) -> bool:
        """Worth an ssh chip: a computer, not a phone."""
        return self.os not in ("android", "iOS", "")


def _when(stamp: str | None) -> float:
    if not stamp or stamp.startswith("0001"):
        return 0.0
    try:
        # Go writes up to nanoseconds; fromisoformat takes microseconds at most.
        stamp = re.sub(r"(\.\d{6})\d+", r"\1", stamp.replace("Z", "+00:00"))
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return 0.0


class _Conn(http.client.HTTPConnection):
    """HTTP over tailscaled's unix socket."""

    def __init__(self, timeout: float):
        super().__init__("local-tailscaled.sock", timeout=timeout)

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def local_api(method: str, path: str, timeout: float = 2.0, body: bytes | None = None) -> dict:
    conn = _Conn(timeout)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, f"/localapi/v0/{path}", body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        if resp.status != 200:
            raise OSError(f"{resp.status} {data[:120].decode(errors='replace').strip()}")
        return json.loads(data or b"{}")
    finally:
        conn.close()


class Tailnet:
    """The sampler's worker calls read() while the network panel is open; the panel
    reads the fields (each replaced whole)."""

    def __init__(self):
        self.state = ""            # BackendState: Running, Stopped, NeedsLogin…; "" = not installed / no answer
        self.me: Peer | None = None
        self.peers: list[Peer] = []
        self.tailnet = ""          # the MagicDNS suffix
        self.exit_status = ""      # the exit node in use, by name
        self.operator = False      # may this user change prefs (exit node)?
        self.error = ""
        self.read_at = 0.0
        # ip -> (tone, words) for the row: a ping's outcome, or "pinging…"
        self.pings: dict[str, tuple[str, str]] = {}
        self.via: dict[str, str] = {}  # ip -> "direct" / "relay fra": what a ping found
        self._pinging: set[str] = set()

    # -- reading (the sampler's worker thread) ---------------------------------

    def read(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.read_at < READ_EVERY:
            return
        self.read_at = now
        try:
            if os.access(SOCKET, os.R_OK | os.W_OK):
                st = local_api("GET", "status")
                try:
                    prefs = local_api("GET", "prefs")
                except OSError:
                    prefs = {}
            else:
                out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True,
                                     timeout=3).stdout
                st, prefs = json.loads(out or "{}"), {}
        except (OSError, ValueError, subprocess.TimeoutExpired) as err:
            self.error = f"tailscaled: {err}"[:80]
            self.state, self.me, self.peers, self.tailnet = "", None, [], ""
            return
        self.error = ""
        me = Peer(st.get("Self") or {}, me=True) if st.get("Self") else None
        peers = [Peer(p) for p in (st.get("Peer") or {}).values()]
        # Online first, then by name; offline ones by when they were last seen.
        peers.sort(key=lambda p: (not p.online, p.name.lower() if p.online else -p.seen))
        using = next((p.name for p in peers if p.exit_node), "")
        self.state, self.me, self.peers = st.get("BackendState") or "", me, peers
        self.tailnet = st.get("MagicDNSSuffix") or ""
        self.exit_status = using
        self.operator = os.getuid() == 0 or bool(prefs) and prefs.get("OperatorUser") == USER

    @property
    def exit_options(self) -> list[Peer]:
        return [p for p in self.peers if p.exit_option]

    # -- acting (on demand, threads of their own) ------------------------------

    def ping(self, peer: Peer) -> None:
        ip = peer.ip
        if not ip or ip in self._pinging:
            return
        self._pinging.add(ip)
        self.pings[ip] = ("dim", "pinging")
        threading.Thread(target=self._ping, args=(ip,), daemon=True).start()

    def _ping(self, ip: str) -> None:
        try:
            ms, via = self._ping_api(ip) if os.access(SOCKET, os.R_OK | os.W_OK) else self._ping_cli(ip)
            self.via[ip] = via
            self.pings[ip] = ("ok" if ms < 30 else ("warn" if ms < 120 else "orange"), f"{ms:.0f} ms")
        except Exception as err:  # noqa: BLE001 — any failure is the row's status
            words = str(err) or "no answer"
            self.pings[ip] = ("hit", "timeout" if "timeout" in words.lower() else words[:24])
        finally:
            self._pinging.discard(ip)

    @staticmethod
    def _ping_api(ip: str) -> tuple[float, str]:
        r = local_api("POST", f"ping?ip={ip}&type=disco", timeout=PING_TIMEOUT)
        if r.get("Err"):
            raise OSError(r["Err"])
        via = "direct" if r.get("Endpoint") else (
            f"relay {r.get('DERPRegionCode')}" if r.get("DERPRegionCode") else "relay")
        if r.get("PeerRelay"):
            via = "peer relay"
        return float(r.get("LatencySeconds") or 0) * 1000, via

    @staticmethod
    def _ping_cli(ip: str) -> tuple[float, str]:
        out = subprocess.run(["tailscale", "ping", "-c", "1", "--timeout", f"{PING_TIMEOUT:.0f}s", ip],
                             capture_output=True, text=True, timeout=PING_TIMEOUT + 2).stdout
        # "pong from p340 (100.77.63.74) via 192.168.1.218:41641 in 3ms" / "via DERP(fra) in 40ms"
        m = re.search(r"via (\S+) in ([\d.]+)ms", out)
        if not m:
            raise OSError(out.strip().splitlines()[-1] if out.strip() else "no answer")
        derp = re.match(r"DERP\((\w+)\)", m.group(1))
        return float(m.group(2)), f"relay {derp.group(1)}" if derp else "direct"

    def set_exit_node(self, peer: Peer | None) -> None:
        """Use peer as the exit node (None: none). Only for the operator; the panel
        shows no button otherwise."""
        if not self.operator:
            return
        body = json.dumps({"ExitNodeIDSet": True, "ExitNodeID": peer.id if peer else "",
                           "ExitNodeIPSet": True, "ExitNodeIP": ""}).encode()

        def go():
            try:
                local_api("PATCH", "prefs", body=body)
            except OSError as err:
                self.error = f"exit node: {err}"[:80]
            self.read(force=True)

        threading.Thread(target=go, daemon=True).start()


def copy(s: str) -> None:
    core.spawn(["wl-copy", s])


def ssh(host: str) -> None:
    core.spawn(["alacritty", "-e", "ssh", host])
