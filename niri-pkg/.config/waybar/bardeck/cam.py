"""Cam: Legartis Cam (the fakecam virtual webcam, ~/fakecam) on the bar.

The strip: a webcam, red with "live" while a call has the camera, amber with
"preview" while the control panel previews it, plain in standby (no browser; it
wakes when a call opens the camera), crossed out when turned off (it stays off,
even for a call), dim and crossed out when fakecam does not answer. An ear while
Listen is on, a hand while Gestures are on.

The panel: what the cam app's panel (https://cam.p14s.grining.eu) and `cam` (rofi)
can do that is worth a click in a meeting: Turn on / Turn off, which real camera
(Source), the scene, the camera settings (mirror, framing, close, blur), Listen and
Gestures, the looks and the bursts. Face and text effects stay in `cam`'s board and
the web panel (buttons for both).

How: fakecam's HTTP API on 127.0.0.1:7788 (the same calls `cam` makes), on a
thread of its own, never on the main loop. GET /api/listen (the power state and
Listen; no browser round trip) every 3 s for the strip, and /api/state every 30 s
(Gestures); /api/state every 1.5 s while the panel is open, and once after each click. Never `?preview=1`: that would
wake the camera. A host without ~/fakecam (p340) gets an empty strip: no pill.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

from . import core
from .core import REAL_HOME, Hits, button, heading, text
from .deck import Panel

BASE = os.environ.get("FAKECAM_URL", "http://127.0.0.1:7788")
WEB = "https://cam.p14s.grining.eu"
INSTALLED = os.path.exists(f"{REAL_HOME}/fakecam/fakecam")
STRIP_EVERY = 3.0
PANEL_EVERY = 1.5

GLYPH_CAM = "\U000f05a0"  # webcam
GLYPH_CAM_OFF = "\U000f1737"  # webcam-off
GLYPH_EAR = "\U000f07c5"  # ear-hearing
GLYPH_HAND = "\U000f0e47"  # hand-back-right
GLYPH_POWER = "\U000f0425"
GLYPH_WEB = "\U000f059f"  # web
GLYPH_WAND = "\U000f0068"  # auto-fix: cam's board
LOOKS_PER_ROW = 4
BURSTS_PER_ROW = 10

# power state -> (glyph, tone, strip word, panel words)
POWER = {
    "on air": (GLYPH_CAM, "hit", "live", "on air · a call has the camera"),
    "preview": (GLYPH_CAM, "warn", "preview", "preview · no call has it"),
    "standby": (GLYPH_CAM, "fg", "", "standby · wakes when a call opens it"),
    "off": (GLYPH_CAM_OFF, "dim", "off", "turned off · stays off, even for a call"),
}
CAMERA_ROWS = (
    ("mirror", (("off", "off"), ("camera", "me"), ("all", "all"))),
    ("frame", (("auto", "auto"), ("on", "on"), ("off", "off"))),
    ("close", (("normal", "normal"), ("close", "close"), ("extra", "extra"))),
    ("blur", (("on", "on"), ("off", "off"))),
)


def cam_name(label: str) -> str:
    """"Integrated Camera (30c9:00f4)" -> "Integrated Camera"."""
    name, _, tail = label.rpartition(" (")
    return name if name and len(tail) == 10 and tail[4] == ":" and tail.endswith(")") else label


class Cam:
    """fakecam's state, read and written on a thread of its own."""

    def __init__(self):
        self.up = False  # fakecam answered the last read
        self.power = ""  # on air, preview, standby, off
        self.listen = "off"
        self.full: dict = {}  # the last /api/state (the panel's)
        self.full_at = 0.0
        self.error = ""  # the last click that failed
        self.armed = ""  # "off": Turn off was clicked once while on air
        self.panel_open = False
        self.notify = None
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def watch(self, notify) -> None:
        """notify() on the main loop whenever something changed."""
        self.notify = notify
        if INSTALLED and self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="cam")
            self._thread.start()

    def poke(self) -> None:
        self._wake.set()

    def _changed(self) -> None:
        if self.notify is not None:
            from gi.repository import GLib

            GLib.idle_add(lambda: self.notify() or False)

    def _get(self, path: str) -> dict | None:
        try:
            with urllib.request.urlopen(BASE + path, timeout=4) as res:
                return json.load(res)
        except (OSError, ValueError):
            return None

    def read_now(self, full: bool = True) -> None:
        """One read: the whole state (the panel's) or just the power and Listen (the strip's)."""
        if full:
            st = self._get("/api/state")
            if st is not None:
                self.full, self.full_at = st, time.monotonic()
                self.power, self.listen = st.get("power", ""), st.get("listen", {}).get("mode", "off")
        else:
            st = self._get("/api/listen")
            if st is not None:
                self.power, self.listen = st.get("power", ""), st.get("mode", "off")
        self.up = st is not None
        if self.power != "on air":
            self.armed = ""

    def _loop(self) -> None:
        n = 0
        while True:
            before = (self.up, self.power, self.listen, self.full_at)
            # the whole state while the panel is open, and every 10th read for the strip's hand
            self.read_now(full=self.panel_open or n % 10 == 0)
            n += 1
            if (self.up, self.power, self.listen, self.full_at) != before:
                self._changed()
            self._wake.wait(PANEL_EVERY if self.panel_open else STRIP_EVERY)
            self._wake.clear()

    def post(self, path: str, body: dict) -> None:
        """A click: sent on a thread, then the state read again."""

        def run():
            req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as res:
                    ans = json.load(res)
            except urllib.error.HTTPError as err:
                try:
                    ans = json.load(err)
                except ValueError:
                    ans = {"error": f"HTTP {err.code}"}
            except (OSError, ValueError) as err:
                ans = {"error": f"fakecam: {err}"}
            self.error = "" if ans.get("ok") else str(ans.get("error") or "failed")[:70]
            if self.error:
                core.log(f"cam {path}: {self.error}")
            self.poke()
            self._changed()

        threading.Thread(target=run, daemon=True).start()

    # -- the clicks --------------------------------------------------------------

    def power_to(self, mode: str) -> None:
        # Off in a call puts a "Camera off" card on the call: that one takes a second click.
        if mode == "off" and self.power == "on air" and self.armed != "off":
            self.armed = "off"
            return
        self.armed = ""
        self.post("/api/power", {"mode": mode})

    def start(self) -> None:
        core.spawn(["systemctl", "--user", "start", "fakecam"])
        self.poke()


class CamStrip:
    name = "cam"

    def __init__(self, cam: Cam):
        self.cam = cam

    def watch(self, notify) -> None:
        self.cam.watch(notify)

    def key(self, variant: str):
        c = self.cam
        return INSTALLED, c.up, c.power, c.listen, (c.full.get("gestures") or {}).get("mode")

    def draw(self, variant: str, scale: int):
        if not INSTALLED:  # no fakecam on this host: nothing on the bar
            surf, _ = core.surface(1, core.BAR_H, scale)
            return surf
        c = self.cam
        cv = core.StripCanvas(scale)
        if not c.up:
            cv.icon(GLYPH_CAM_OFF, "dim", 15, after=0)
            return cv.finish()
        glyph, tone, word, _ = POWER.get(c.power, (GLYPH_CAM, "fg", c.power, ""))
        if c.power == "on air":
            cr = cv.cr
            cr.new_sub_path()
            cr.arc(cv.x + 3.5, core.MID, 3.5, 0, 6.2832)
            cr.set_source_rgba(*core.rgba("hit"))
            cr.fill()
            cv.x += 11
        cv.icon(glyph, tone, 15, after=3 if word and variant == "full" else 0)
        if word and variant == "full":
            cv.text(word, tone, bold=c.power == "on air")
        if c.listen != "off":
            cv.gap(6)
            cv.icon(GLYPH_EAR, "aqua", 13, after=0)
        if (c.full.get("gestures") or {}).get("mode") == "on":
            cv.gap(5)
            cv.icon(GLYPH_HAND, "aqua", 13, after=0)
        return cv.finish()


class CamPanel(Panel):
    name = "cam"
    W = 470
    ROW = 30

    def __init__(self, cam: Cam):
        self.cam = cam

    def opened(self) -> None:
        self.cam.panel_open = True
        self.cam.error = ""
        self.cam.poke()

    def closed(self) -> None:
        self.cam.panel_open = False
        self.cam.armed = ""

    def size(self):
        st = self.cam.full
        if not self.cam.up or not st:
            return self.W, 100
        h = 12 + 50  # the header
        h += 56  # power
        h += 56  # source
        h += 56 + 30 * (self.scene_rows(st) - 1)  # scene
        h += 20 + self.ROW * len(CAMERA_ROWS) + 10  # camera
        h += 56  # listen + gestures
        looks = (st.get("fx") or {}).get("catalogue", {}).get("looks", [])
        bursts = (st.get("fx") or {}).get("catalogue", {}).get("bursts", [])
        h += 20 + 30 * -(-len(looks) // LOOKS_PER_ROW) + 6
        h += 20 + 32 * -(-len(bursts) // BURSTS_PER_ROW) + 12
        return self.W, h

    def scene_rows(self, st: dict) -> int:
        rows, x = 1, 0.0
        for sc in st.get("scenes", []):
            bw = 6 * len(sc.get("name", "?")) + 18
            if x and x + bw > self.W - 32:
                rows, x = rows + 1, 0.0
            x += bw + 8
        return rows

    def draw(self, cr, hits: Hits) -> None:
        c, W, P = self.cam, self.W, 16
        core.panel_frame(cr, W, self.size()[1])
        st = c.full
        y = 12
        if not c.up or not st:
            core.icon(cr, P, y + 16, GLYPH_CAM_OFF, 26, "dim")
            text(cr, P + 36, y + 2, "Legartis Cam", 18, "title", bold=True)
            text(cr, P + 36, y + 24, "fakecam is not answering on " + BASE.split("//")[-1] if not c.up else "reading…",
                 12, "dim")
            if not c.up:
                button(cr, hits, P, y + 50, "start fakecam", c.start, tone="ok", glyph=GLYPH_POWER)
            return

        # header: the state, the scene
        glyph, tone, _, words = POWER.get(c.power, (GLYPH_CAM, "fg", "", c.power))
        core.icon(cr, P, y + 16, glyph, 28, tone)
        text(cr, P + 40, y - 1, "Legartis Cam", 18, "title", bold=True)
        text(cr, P + 40, y + 22, words, 12, tone if c.power in ("on air", "preview") else "dim")
        x = W - P
        x -= button(cr, hits, x - 70, y + 4, "web", lambda: core.spawn(["xdg-open", WEB]) or True, glyph=GLYPH_WEB,
                    w=70) + 6
        button(cr, hits, x - 80, y + 4, "effects", lambda: core.spawn([f"{REAL_HOME}/bin/cam"]) or True,
               glyph=GLYPH_WAND, w=80)  # cam's board: every face and text effect too
        y += 50

        # power
        note = c.error or ("click again: the call sees a “Camera off” card" if c.armed == "off" else "")
        heading(cr, P, y, "power", W - 2 * P - (text(cr, W - P, y - 2, note, 11, "hit", align=1) + 10 if note else 0))
        y += 20
        x = P
        on = c.power in ("on air", "preview", "standby")
        x += button(cr, hits, x, y, "turn on", lambda: c.power_to("on"), on=on, tone="ok", glyph=GLYPH_POWER) + 8
        x += button(cr, hits, x, y, "click again to turn off" if c.armed == "off" else "turn off",
                    lambda: c.power_to("off"), on=c.power == "off" or c.armed == "off",
                    tone="hit" if c.armed == "off" else "bg3") + 8
        y += 36

        # source: which real camera
        cams = st.get("cameras") or {}
        chosen = (st.get("camera") or {}).get("source", "auto")
        current = cams.get("current", "")
        listed = list(cams.get("list", []))
        right = f"in use: {cam_name(current)}" if current else ("" if listed else "shown once a camera scene ran")
        heading(cr, P, y, "source", W - 2 * P - (text(cr, W - P, y - 2, right, 11, "dim", align=1) + 10 if right else 0))
        y += 20
        x = P
        x += button(cr, hits, x, y, "auto", lambda: c.post("/api/settings", {"source": "auto"}),
                    on=chosen == "auto", glyph=GLYPH_CAM) + 8
        if chosen != "auto" and chosen not in listed:
            listed.append(chosen)
        for label in listed:
            name = cam_name(label) + ("" if label in cams.get("list", []) else " (gone)")
            if x + core.text_w(cr, name, 12) + 18 > W - P:
                break
            x += button(cr, hits, x, y, name, lambda v=label: c.post("/api/settings", {"source": v}),
                        on=chosen == label) + 8
        y += 36

        # scene
        heading(cr, P, y, "scene", W - 2 * P)
        y += 20
        x = P
        for sc in st.get("scenes", []):
            label = sc.get("name", "?")
            bw = core.text_w(cr, label, 12) + 18
            if x > P and x + bw > W - P:
                x, y = P, y + 30
            x += button(cr, hits, x, y, label, lambda n=label: c.post("/api/scene", {"name": n, "params": None}),
                        on=label == st.get("scene")) + 8
        y += 36

        # camera settings
        heading(cr, P, y, "camera", W - 2 * P)
        y += 20
        cam_set = st.get("camera") or {}
        for key, choices in CAMERA_ROWS:
            text(cr, P, y + 4, key, 12, "fg")
            x = P + 70
            for value, label in choices:
                x += button(cr, hits, x, y, label, lambda k=key, v=value: c.post("/api/settings", {k: v}),
                            on=cam_set.get(key) == value, w=64) + 6
            y += self.ROW
        y += 10

        # listen and gestures, side by side
        heading(cr, P, y, "listen", 250)
        heading(cr, P + 290, y, "gestures", W - 2 * P - 290)
        y += 20
        x = P
        lmode = (st.get("listen") or {}).get("mode", "off")
        for value, label in (("off", "off"), ("me", "me"), ("all", "me + call")):
            x += button(cr, hits, x, y, label, lambda v=value: c.post("/api/listen", {"mode": v}), on=lmode == value,
                        tone="aqua" if value != "off" else "bg3", glyph=GLYPH_EAR if value == "me" else None) + 6
        x = P + 290
        gmode = (st.get("gestures") or {}).get("mode", "off")
        for value in ("off", "on"):
            x += button(cr, hits, x, y, value, lambda v=value: c.post("/api/gestures", {"mode": v}), on=gmode == value,
                        tone="aqua" if value == "on" else "bg3", glyph=GLYPH_HAND if value == "on" else None) + 6
        y += 36

        # looks: on until turned off
        fx = st.get("fx") or {}
        on_looks = list(fx.get("looks", []))
        heading(cr, P, y, "looks", W - 2 * P - 60)
        if on_looks:
            button(cr, hits, W - P - 52, y - 5, "all off", lambda: c.post("/api/fx", {"looks": []}), h=18, size=11,
                   w=52)
        y += 20
        bw = (W - 2 * P - (LOOKS_PER_ROW - 1) * 6) / LOOKS_PER_ROW
        for i, e in enumerate(fx.get("catalogue", {}).get("looks", [])):
            x = P + (i % LOOKS_PER_ROW) * (bw + 6)
            yy = y + (i // LOOKS_PER_ROW) * 30
            name = e["name"]
            new = [n for n in on_looks if n != name] if name in on_looks else on_looks + [name]
            button(cr, hits, x, yy, f"{e['icon']} {name}", lambda v=new: c.post("/api/fx", {"looks": v}),
                   on=name in on_looks, tone="purple", w=bw, size=11)
        y += 30 * -(-len(fx.get("catalogue", {}).get("looks", [])) // LOOKS_PER_ROW) + 6

        # bursts: a few seconds, then gone
        heading(cr, P, y, "bursts", W - 2 * P)
        y += 20
        bursts = fx.get("catalogue", {}).get("bursts", [])
        bw = (W - 2 * P - (BURSTS_PER_ROW - 1) * 4) / BURSTS_PER_ROW
        for i, e in enumerate(bursts):
            x = P + (i % BURSTS_PER_ROW) * (bw + 4)
            yy = y + (i // BURSTS_PER_ROW) * 32
            button(cr, hits, x, yy, e["icon"], lambda n=e["name"]: c.post("/api/fx", {"burst": n, "text": ""}),
                   w=bw, h=28, size=15)
