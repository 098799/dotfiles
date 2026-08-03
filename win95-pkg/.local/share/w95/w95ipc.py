"""Minimal i3 IPC client — stdlib only, no python-i3ipc dependency.

Two objects: `I3.command()/get_tree()/...` for request/reply on one socket,
and `I3.subscribe()` which spins a second socket in a thread and hands every
event to a callback on the GLib main loop.
"""

import json
import os
import socket
import struct
import subprocess
import threading

MAGIC = b"i3-ipc"
HDR = struct.Struct("=6sII")

RUN_COMMAND = 0
GET_WORKSPACES = 1
SUBSCRIBE = 2
GET_OUTPUTS = 3
GET_TREE = 4


def socket_path():
    """Find the i3 owning *this* DISPLAY.

    `i3 --get-socketpath` reads $I3SOCK first and so happily hands back the
    socket of a different i3 when several are running (e.g. a nested Xephyr
    session). The root-window property is the authoritative per-display
    answer, so try that before falling back.
    """
    try:
        out = subprocess.check_output(
            ["xprop", "-root", "-notype", "I3_SOCKET_PATH"],
            stderr=subprocess.DEVNULL,
        ).decode()
        if '"' in out:
            path = out.split('"')[1]
            if os.path.exists(path):
                return path
    except (OSError, subprocess.CalledProcessError):
        pass

    p = os.environ.get("I3SOCK")
    if p and os.path.exists(p):
        return p
    return subprocess.check_output(["i3", "--get-socketpath"]).decode().strip()


class _Conn:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)

    def send(self, mtype, payload=""):
        data = payload.encode()
        self.sock.sendall(HDR.pack(MAGIC, len(data), mtype) + data)

    def _recv_exactly(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("i3 closed the IPC socket")
            buf += chunk
        return buf

    def recv(self):
        magic, length, mtype = HDR.unpack(self._recv_exactly(HDR.size))
        if magic != MAGIC:
            raise ConnectionError("bad IPC magic %r" % magic)
        return mtype, json.loads(self._recv_exactly(length) or "null")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class I3:
    def __init__(self):
        self.path = socket_path()
        self.conn = _Conn(self.path)
        self.lock = threading.Lock()

    def _rpc(self, mtype, payload=""):
        with self.lock:
            self.conn.send(mtype, payload)
            _, reply = self.conn.recv()
            return reply

    def command(self, cmd):
        return self._rpc(RUN_COMMAND, cmd)

    def get_tree(self):
        return self._rpc(GET_TREE)

    def get_workspaces(self):
        return self._rpc(GET_WORKSPACES)

    def get_outputs(self):
        return self._rpc(GET_OUTPUTS)

    def subscribe(self, events, on_event):
        """Run a dedicated listener socket in a daemon thread.

        `on_event(name, payload)` is called from that thread — callers are
        expected to bounce onto their own main loop.
        """

        def run():
            while True:
                try:
                    conn = _Conn(self.path)
                    conn.send(SUBSCRIBE, json.dumps(events))
                    conn.recv()  # subscribe ack
                    while True:
                        mtype, payload = conn.recv()
                        if mtype & 0x80000000:
                            idx = mtype & 0x7FFFFFFF
                            name = events[idx] if idx < len(events) else str(idx)
                            on_event(name, payload)
                except Exception:
                    # i3 restarted (or is mid-reload); wait it out and re-attach.
                    import time

                    time.sleep(0.5)

        threading.Thread(target=run, daemon=True).start()


def walk(node):
    """Yield every node in an i3 tree, depth first."""
    yield node
    for kid in node.get("nodes", []) + node.get("floating_nodes", []):
        yield from walk(kid)


# Parts of the Win95 shell that happen to be windows. The taskbar itself lands
# in a dockarea and is filtered below, but the System Monitor's drop-down panel
# is an ordinary floating window as far as i3 is concerned. It does set
# _NET_WM_STATE_SKIP_TASKBAR — which is exactly what this is — but i3's IPC
# tree does not report window state, so the instance name is what we have.
SHELL_INSTANCES = {"w95-sysmon-drop"}


def windows(tree):
    """Every real client window, tagged with the workspace it lives on.

    Scratchpad residents come back with workspace ``None`` — that is how the
    taskbar knows a window is "minimised".
    """
    out = []

    def visit(node, ws):
        if node.get("type") == "workspace":
            ws = node.get("name")
            if ws == "__i3_scratch":
                ws = None
        if node.get("type") == "dockarea":
            return  # panels and trays are not tasks — that includes us
        instance = (node.get("window_properties") or {}).get("instance")
        if node.get("window") and node.get("name") is not None \
                and instance not in SHELL_INSTANCES:
            node = dict(node)
            node["_ws"] = ws
            out.append(node)
        for kid in node.get("nodes", []) + node.get("floating_nodes", []):
            visit(kid, ws)

    visit(tree, None)
    return out
