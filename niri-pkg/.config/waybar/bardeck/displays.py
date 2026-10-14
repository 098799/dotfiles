"""Displays: the screens niri drives. On the strip a monitor and the count of
screens on; in the panel the arrangement drawn to scale, the selected screen's
settings (on / off, brightness, scale, rotation, VRR, its modes) and
niri-screen-switch's entries as presets.

Reading: niri's IPC socket in-process (ws.niri, the "Outputs" request, ~0.3 ms).
niri's event stream says nothing when a screen's mode or scale changes, so the
strip asks every 2 s (one socket round trip, no program) and the open panel every
second.

Acting: a setting is `niri msg output <name> …` on a thread, its outcome in
`status` on the screen's settings. A preset runs `niri-screen-switch "<entry>"`,
so the script keeps its logic in one place: it waits for an output to go live,
never leaves every screen off, repapers, connects the pad, starts Big Picture.
Brightness is not niri's: the backlight or DDC/CI, on its own worker
(brightness.py), so a slow monitor never holds a niri change back.

Safety: the last screen on cannot be turned off (the chip is disabled, the key
refused), so the laptop never goes off while no other screen is live. A new mode
may leave a screen black: it reverts after REVERT_S unless kept (Enter, or the
"keep" chip), the way desktop settings do. The revert is checked on the strip's
tick, so it happens with the panel closed too."""

from __future__ import annotations

import os
import subprocess
import threading
import time

from . import core
from .audio import slider
from .brightness import STEP as BRIGHT_STEP
from .brightness import Brightness
from .core import Hits, button, heading, rgba, text
from .deck import Panel
from .ws import niri

SWITCH = f"{core.REAL_HOME}/bin/niri-screen-switch"
# niri-screen-switch's outputs.
LAPTOP, EXTERNAL, HDMI = "eDP-1", "DP-1", "HDMI-A-1"
REVERT_S = 15

GLYPH_MONITOR, GLYPH_MULTI, GLYPH_LAPTOP, GLYPH_TV = "\U000f0379", "\U000f037a", "\U000f0322", "\U000f0502"
GLYPH_PAD, GLYPH_EXIT, GLYPH_SOUND = "\U000f0297", "\U000f0206", "\U000f057e"
GLYPH_CHECK = "\U000f012c"
GLYPH_POWER, GLYPH_OFF, GLYPH_UNDO = "\U000f0425", "\U000f0d90", "\U000f099b"

SCALES = (1.0, 1.25, 1.5, 2.0)
TRANSFORMS = (("normal", "normal"), ("90", "90°"), ("180", "180°"), ("270", "270°"))
RATIOS = ((16, 9), (16, 10), (4, 3), (5, 4), (3, 2), (21, 9), (32, 9), (5, 3))

# niri-screen-switch's menu entries, as the panel's presets (presets() adds the
# font faces): (row, ((label, glyph,
# entry, the output it needs or None), …)). The entries must match the script's
# ENTRIES (it refuses an unknown one with exit 2, which shows as "failed").
# A screen preset whose output is not connected is disabled: the script would turn
# the current screen off first and fall back to the laptop. Game is not: the TV
# wakes on its way (tv.py) and only then shows up on HDMI.
PRESETS = (
    ("game", (("game mode", GLYPH_PAD, "Game: TV + sound + pad + Big Picture", None),
              ("game end", GLYPH_EXIT, "Game: end (laptop)", LAPTOP))),
    ("screens", (("laptop", GLYPH_LAPTOP, "Screen: laptop only", LAPTOP),
                 ("ext 1440p", GLYPH_MONITOR, "Screen: external 2560x1440", EXTERNAL),
                 ("ext wide", GLYPH_MONITOR, "Screen: external 3440x1440 (wide)", EXTERNAL),
                 ("ext + laptop", GLYPH_MULTI, "Screen: external + laptop", EXTERNAL),
                 ("HDMI native", GLYPH_TV, "Screen: HDMI only (native)", HDMI),
                 ("HDMI 1440p", GLYPH_TV, "Screen: HDMI 2560x1440", HDMI))),
    ("sound", (("HDMI", GLYPH_SOUND, "Sound: HDMI", None), ("laptop", GLYPH_SOUND, "Sound: laptop", None))),
    ("theme", (("w95", None, "Theme: w95", None), ("dark gruv", None, "Theme: dark-gruv", None),
               ("light gruv", None, "Theme: light-gruv", None),
               ("dark sele", None, "Theme: dark-sele", None),
               ("light sele", None, "Theme: light-sele", None))),
    ("font", (("small", None, "Font: small", None), ("middle", None, "Font: middle", None),
              ("big", None, "Font: big", None), ("huge", None, "Font: huge", None))),
)
TERMFONT = f"{core.REAL_HOME}/bin/termfont"
TERMFONT_STATE = f"{core.REAL_HOME}/.config/termfont"
_presets: tuple | None = None


def presets() -> tuple:
    """PRESETS plus a "face" row: one chip per font termfont finds installed
    (the script's "Font: <name>" entries). Asked once: fonts change rarely."""
    global _presets
    if _presets is None:
        try:
            out = subprocess.run([TERMFONT, "names"], capture_output=True, text=True, timeout=3).stdout
            names = [n.strip() for n in out.splitlines() if n.strip()]
        except (OSError, subprocess.TimeoutExpired):
            names = []
        faces = tuple((n, None, f"Font: {n}", None) for n in names)
        if faces:
            faces += (("A/B", None, "Font: the one before (A/B)", None),)
        _presets = PRESETS + ((("face", faces),) if faces else ())
    return _presets


def termfont_state(name: str, default: str) -> str:
    try:
        with open(f"{TERMFONT_STATE}/{name}") as f:
            return f.read().strip() or default
    except OSError:
        return default


# ── an output (niri's dict) ──────────────────────────────────────────────────


def live(o: dict) -> bool:
    return o.get("logical") is not None


def hz(refresh: int) -> str:
    return f"{refresh / 1000:.2f}".rstrip("0").rstrip(".")


def mode_arg(m: dict) -> str:
    """As `niri msg outputs` lists it, and `niri msg output … mode` takes it."""
    return f"{m['width']}x{m['height']}@{m['refresh_rate'] / 1000:.3f}"


def ratio(w: int, h: int) -> str:
    r = w / h
    best = min(RATIOS, key=lambda p: abs(p[0] / p[1] - r))
    return f"{best[0]}:{best[1]}" if abs(best[0] / best[1] - r) / r < 0.03 else ""


def transform(o: dict) -> str:
    """niri's transform ("Normal", "_90", "Flipped90", …) as the CLI spells it."""
    t = str((o.get("logical") or {}).get("transform", "Normal")).lower().lstrip("_")
    if t.startswith("flipped") and t != "flipped":
        t = "flipped-" + t[7:].lstrip("-_")
    return t


def current(o: dict) -> dict | None:
    i = o.get("current_mode")
    modes = o.get("modes") or []
    return modes[i] if i is not None and 0 <= i < len(modes) else None


def modes(o: dict) -> list[tuple[dict, bool]]:
    """The output's modes once each (niri lists some twice: other timings), with
    whether it is the current one; niri's order (EDID: best first)."""
    cur = current(o)
    seen, out = set(), []
    for m in o.get("modes") or []:
        k = (m["width"], m["height"], m["refresh_rate"])
        if k in seen:
            continue
        seen.add(k)
        out.append((m, cur is not None and k == (cur["width"], cur["height"], cur["refresh_rate"])))
    return out


def short_model(o: dict) -> str:
    make = (o.get("make") or "").replace(",", " ").split()
    make1 = make[0] if make else ""
    model = o.get("model") or ""
    if make1 and not model.lower().startswith(make1.lower()):
        return f"{make1} {model}".strip()
    return model or make1


def logical_size(o: dict) -> tuple[float, float]:
    """Its size on the layout; an output that is off: its preferred mode at the scale
    niri would likely pick (by pixel density), so it sits beside at about its size."""
    lg = o.get("logical")
    if lg:
        return lg["width"], lg["height"]
    ms = o.get("modes") or []
    m = next((m for m in ms if m.get("is_preferred")), ms[0] if ms else {"width": 1920, "height": 1080})
    phys = (o.get("physical_size") or [0, 0])[0]
    dpi = m["width"] / (phys / 25.4) if phys else 96
    s = 1.0 if dpi < 130 else (1.25 if dpi < 170 else (1.5 if dpi < 220 else 2.0))
    return m["width"] / s, m["height"] / s


# ── the model ────────────────────────────────────────────────────────────────


class Displays:
    def __init__(self):
        self.outputs: dict[str, dict] = {}  # replaced whole on each read
        self.focused = ""
        self.read_at = 0.0
        self.frozen = False  # renders with fake data: no reads
        self.status: dict[str, tuple[str, str]] = {}  # output name or "preset" -> (tone, words)
        self.running = ""  # the preset entry running now
        # A mode change waiting to be kept: (output, the mode to go back to, deadline).
        self.pending: tuple[str, str, float] | None = None
        self.bright = Brightness()
        self._busy = threading.Lock()

    def read(self, max_age: float = 0.0, focus: bool = False) -> None:
        if self.frozen or time.monotonic() - self.read_at < max_age:
            return
        outs = niri("Outputs")
        if isinstance(outs, dict):
            self.outputs = outs
            self.read_at = time.monotonic()
        if focus:
            f = niri("FocusedOutput")
            self.focused = f.get("name", "") if isinstance(f, dict) else ""

    def order(self) -> list[str]:
        """Live outputs left to right, then the ones that are off."""
        on = sorted((n for n, o in self.outputs.items() if live(o)),
                    key=lambda n: (self.outputs[n]["logical"]["x"], self.outputs[n]["logical"]["y"]))
        return on + sorted(n for n, o in self.outputs.items() if not live(o))

    def live_names(self) -> list[str]:
        return [n for n, o in self.outputs.items() if live(o)]

    def can_off(self, name: str) -> bool:
        """Only when another screen stays on: never all of them off, so never the
        laptop while no external screen is live."""
        return name in self.live_names() and len(self.live_names()) > 1

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    # -- acting (a thread each) -------------------------------------------------

    def _run(self, key: str, argv: list[str], doing: str, done=None) -> bool:
        """argv on a thread, one at a time; `doing` on the row while it runs, the error
        after. done(ok) runs on the thread when it ended. False when something runs."""
        if not self._busy.acquire(blocking=False):
            self.status[key] = ("warn", "busy: one change at a time")
            return False
        self.status[key] = ("warn", doing)

        def body():
            ok = False
            try:
                r = subprocess.run(argv, capture_output=True, text=True, timeout=180,
                                   env=dict(os.environ, HOME=core.REAL_HOME), stdin=subprocess.DEVNULL)
                ok = r.returncode == 0
                if ok:
                    self.status.pop(key, None)
                else:
                    err = (r.stderr or r.stdout).strip().splitlines()
                    self.status[key] = ("hit", (err[-1] if err else f"failed (exit {r.returncode})")[:60])
            except Exception as err:
                self.status[key] = ("hit", short_error(err))
                core.log(f"displays {key}: {err!r}")
            finally:
                self._busy.release()
                self.read_at = 0.0  # the next draw reads the new state
            if done is not None:
                done(ok)

        threading.Thread(target=body, daemon=True).start()
        return True

    def apply(self, name: str, *args: str, words: str = "applying") -> bool:
        """`niri msg output <name> <args>`. Refuses to turn off the last screen on."""
        if args == ("off",) and not self.can_off(name):
            self.status[name] = ("hit", "the only screen on: it stays on")
            return False
        return self._run(name, ["niri", "msg", "output", name, *args], words)

    def set_mode(self, name: str, m: dict) -> bool:
        o = self.outputs.get(name) or {}
        old = current(o)
        if not live(o) or old is None or mode_arg(old) == mode_arg(m):
            return False
        back = mode_arg(old)

        def done(ok: bool) -> None:
            if ok:
                self.pending = (name, back, time.monotonic() + REVERT_S)

        return self._run(name, ["niri", "msg", "output", name, "mode", mode_arg(m)], "setting the mode", done)

    def keep(self) -> None:
        self.pending = None

    def revert(self) -> None:
        if self.pending is None:
            return
        name, back, _ = self.pending
        if self._run(name, ["niri", "msg", "output", name, "mode", back], "going back"):
            self.pending = None
            self.status[name] = ("warn", "going back")

    def expire(self) -> None:
        """The pending mode's time is up: go back (retried while something runs)."""
        if self.pending is not None and time.monotonic() >= self.pending[2] and not self.busy:
            self.revert()

    def preset(self, entry: str) -> None:
        def done(ok: bool) -> None:
            self.running = ""

        self.running = entry  # before the thread starts: it may end first
        if not self._run("preset", [SWITCH, entry], f"running {entry}", done):
            self.running = ""

    def settle(self) -> None:
        """A new opening: forget past outcomes, keep what still runs."""
        self.status = {k: v for k, v in self.status.items() if v[0] == "warn" and self.busy}

    def preset_on(self, entry: str) -> bool:
        """Whether the screens are as the script's layout leaves them."""
        on = set(self.live_names())

        def size(name):
            m = current(self.outputs.get(name) or {})
            return (m["width"], m["height"]) if m else None

        if entry.startswith("Font: "):
            # termfont's state: the face's menu name and the size name.
            want = entry[len("Font: "):]
            return want in (termfont_state("name", "Ubuntu Mono"), termfont_state("size", "small"))
        return {
            "Screen: laptop only": on == {LAPTOP},
            "Screen: external 2560x1440": on == {EXTERNAL} and size(EXTERNAL) == (2560, 1440),
            "Screen: external 3440x1440 (wide)": on == {EXTERNAL} and size(EXTERNAL) == (3440, 1440),
            "Screen: external + laptop": on == {EXTERNAL, LAPTOP},
            "Screen: HDMI only (native)": on == {HDMI} and bool((current(self.outputs[HDMI]) or {}).get("is_preferred")),
            "Screen: HDMI 2560x1440": on == {HDMI} and size(HDMI) == (2560, 1440),
        }.get(entry, False)


def short_error(err: Exception) -> str:
    msg = getattr(err, "message", None) or str(err)
    return msg.rsplit(":", 1)[-1].strip()[:40] or "failed"


# ── the strip ────────────────────────────────────────────────────────────────


class DispStrip:
    name = "disp"

    def __init__(self, d: Displays):
        self.d = d

    def key(self, variant: str):
        d = self.d
        d.read(max_age=1.5)
        d.expire()
        return (len(d.live_names()), len(d.outputs), d.pending is not None, bool(d.running))

    def draw(self, variant: str, scale: int):
        d = self.d
        c = core.StripCanvas(scale)
        n, total = len(d.live_names()), len(d.outputs)
        tone = "warn" if (d.pending or d.running) else ("title" if n else "hit")
        c.icon(GLYPH_MULTI if n > 1 else GLYPH_MONITOR, tone, 15, after=3)
        c.text(str(n), "title" if n else "hit")
        if variant == "full" and total > n:  # connected but off
            c.text(f"/{total}", "dim", size=11)
        return c.finish()


# ── the panel ────────────────────────────────────────────────────────────────


class DispPanel(Panel):
    """The arrangement (click a screen to select it), its settings, its modes (click
    one, or `i`/`o` and Enter when pinned), the presets."""

    name = "disp"
    live = 1.0
    W = 520
    P = 16
    MAP_H = 150
    ROWS = 6      # mode rows shown; the list scrolls past that
    ROW_H = 24
    CHIP_H = 22
    LABEL_W = 62  # the settings' and presets' label column
    SETTINGS = 4  # rows: power, brightness, scale, rotation
    PENDING_H = 34

    def __init__(self, d: Displays):
        self.d = d
        self.out = ""        # the selected output
        self.sel = -1        # the keyboard's mode row
        self.top = 0
        self.hovered = -1
        self.rows: list[tuple[float, float, int]] = []  # (y0, y1, mode index), for hover
        self.hx = self.hy = -1.0
        self.bright_row = (0.0, 0.0)  # (y0, y1) of the brightness row, for the wheel
        self._preset_rows: int | None = None

    # -- state -----------------------------------------------------------------

    def output(self) -> dict | None:
        return self.d.outputs.get(self.out)

    def modes(self) -> list[tuple[dict, bool]]:
        o = self.output()
        return modes(o) if o else []

    def select(self, name: str) -> bool:
        if name == self.out:
            return False
        self.out = name
        ms = self.modes()
        self.sel = next((i for i, (_, cur) in enumerate(ms) if cur), 0 if ms else -1)
        self.top = 0
        self.follow()
        return False

    def follow(self) -> None:
        n = len(self.modes())
        if self.sel >= 0:
            if self.sel < self.top:
                self.top = self.sel
            elif self.sel >= self.top + self.ROWS:
                self.top = self.sel - self.ROWS + 1
        self.top = max(0, min(self.top, n - self.ROWS))

    def opened(self) -> None:
        self.d.read(focus=True)
        self.d.settle()
        self.out, self.hovered = "", -1
        order = self.d.order()
        self.select(self.d.focused if self.d.focused in self.d.outputs else (order[0] if order else ""))

    def list_h(self) -> float:
        n = len(self.modes())
        return 22 + max(1, min(self.ROWS, n)) * self.ROW_H + (14 if n > self.ROWS else 0) + 8

    def preset_rows(self) -> int:
        """Rows the preset chips take (they wrap). Measured once: the labels are fixed."""
        if self._preset_rows is None:
            import cairo

            cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
            self._preset_rows = sum(len(self.flow(cr, chips)) for _, chips in presets())
        return self._preset_rows

    def flow(self, cr, chips) -> list[list[tuple[float, tuple]]]:
        """The chips of a preset row, wrapped: lines of (x, chip)."""
        x0, right = self.P + self.LABEL_W, self.W - self.P
        lines, x = [[]], x0
        for chip in chips:
            w = self.chip_w(cr, chip[0], chip[1])
            if x + w > right and lines[-1]:
                lines.append([])
                x = x0
            lines[-1].append((x, chip))
            x += w + 6
        return lines

    def size(self):
        h = 52 + 20 + self.MAP_H + 14       # header, the arrangement
        h += self.PENDING_H if self.d.pending else 0
        h += 30 + self.SETTINGS * 28 + 8     # the selected screen and its settings
        h += self.list_h()
        h += 20 + self.preset_rows() * 28 + 8
        return self.W, h

    # -- input -----------------------------------------------------------------

    def step_output(self, by: int) -> None:
        order = self.d.order()
        if not order:
            return
        i = order.index(self.out) if self.out in order else 0
        self.select(order[(i + by) % len(order)])

    def pick_mode(self, i: int) -> bool:
        ms = self.modes()
        o = self.output()
        if not (0 <= i < len(ms)) or o is None:
            return False
        self.sel = i
        if not live(o):
            self.d.status[self.out] = ("warn", "turn it on first")
        elif not ms[i][1]:
            self.d.set_mode(self.out, ms[i][0])
        return False

    def key(self, key: str, ctrl: bool) -> bool:
        n = len(self.modes())
        if key in ("u", "j", "Left"):
            self.step_output(-1)
        elif key in ("p", "semicolon", "Right"):
            self.step_output(1)
        elif key in ("i", "Down") or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key in ("o", "Up") or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key in ("k", "Page_Down") or (ctrl and key == "v"):
            self.sel = min(n - 1, self.sel + self.ROWS // 2)
        elif key in ("l", "Page_Up"):
            self.sel = max(0, self.sel - self.ROWS // 2)
        elif key in ("Return", "KP_Enter"):
            if self.d.pending:
                self.d.keep()
            else:
                self.pick_mode(self.sel)
        elif key == "BackSpace" and self.d.pending:
            self.d.revert()
        elif key in ("minus", "KP_Subtract", "equal", "plus", "KP_Add"):
            return self.step_bright(key in ("equal", "plus", "KP_Add"))
        else:
            return False
        self.follow()
        return True

    def hover(self, x: float, y: float) -> bool:
        self.hx, self.hy = x, y
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    def scroll(self, down: bool) -> bool:
        if self.bright_row[0] <= self.hy < self.bright_row[1]:
            return self.step_bright(not down)
        top = max(0, min(self.top + (1 if down else -1), len(self.modes()) - self.ROWS))
        if top == self.top:
            return False
        self.top = top
        return True

    def step_bright(self, up: bool) -> bool:
        o = self.output()
        if o is None or not live(o):
            return False
        self.d.bright.step(self.out, BRIGHT_STEP if up else -BRIGHT_STEP)
        return True

    def bright_from_pointer(self, x0: float, w: float) -> bool:
        self.d.bright.set(self.out, round(max(0.0, min(1.0, (self.hx - x0) / w)) * 100))
        return False

    # -- drawing ---------------------------------------------------------------

    def draw(self, cr, hits: Hits) -> None:
        d = self.d
        d.read(max_age=0.9, focus=True)
        d.expire()
        if self.out not in d.outputs:  # unplugged while open
            order = d.order()
            self.out = ""
            self.select(order[0] if order else "")
        W, P = self.W, self.P
        core.panel_frame(cr, W, self.size()[1])

        y = 12
        n_on, n_all = len(d.live_names()), len(d.outputs)
        core.icon(cr, P, y + 11, GLYPH_MULTI if n_on > 1 else GLYPH_MONITOR, 22, "title" if n_on else "hit")
        text(cr, P + 30, y, "Displays", 18, "title", bold=True)
        summary = f"{n_on} on" + (f" · {n_all - n_on} off" if n_all > n_on else "")
        st = d.status.get("preset")
        if st:
            words = st[1] + ("." * (1 + int(time.monotonic()) % 3) if st[0] == "warn" and d.running else "")
            text(cr, W - P, y + 4, words, 12, st[0], align=1, width=W - 2 * P - 150)
        else:
            text(cr, W - P, y + 4, summary, 12, "dim", align=1)
        y += 40

        if d.pending:
            y = self.draw_pending(cr, hits, P, y)

        heading(cr, P, y, "arrangement", W - 2 * P)
        y += 20
        self.draw_map(cr, hits, P, y, W - 2 * P, self.MAP_H)
        y += self.MAP_H + 14

        y = self.draw_settings(cr, hits, P, y)
        y = self.draw_modes(cr, hits, P, y)

        heading(cr, P, y, "presets · niri-screen-switch", W - 2 * P)
        y += 20
        for label, chips in presets():
            for li, line in enumerate(self.flow(cr, chips)):
                if li == 0:
                    text(cr, P, y + self.CHIP_H / 2, label, 11, "dim", valign=0.5)
                for x, (name, glyph, entry, needs) in line:
                    ok = needs is None or needs in d.outputs
                    self.chip(cr, hits, x, y, name, lambda e=entry: d.preset(e) or False, glyph=glyph,
                              on=d.preset_on(entry) or d.running == entry, tone="accent",
                              disabled=not ok or d.busy and d.running != entry,
                              why=f"{needs} is not connected" if not ok else "busy", key="preset")
                y += 28

    def draw_pending(self, cr, hits: Hits, P: float, y: float) -> float:
        """The new mode, waiting to be kept."""
        W = self.W
        name, back, deadline = self.d.pending
        left = max(0, int(deadline - time.monotonic() + 0.99))
        core.rrect(cr, P - 6, y - 4, W - 2 * P + 12, self.PENDING_H - 6, 7)
        cr.set_source_rgba(*rgba("warn", 0.16))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("warn", 0.6))
        cr.set_line_width(1)
        cr.stroke()
        mid = y - 4 + (self.PENDING_H - 6) / 2
        text(cr, P + 2, mid, f"{name}: keep the new mode? back to {back.split('@')[0]} in {left} s", 12, "title",
             valign=0.5, width=W - 2 * P - 150)
        right = W - P
        bw = self.chip_w(cr, "back", GLYPH_UNDO)
        right -= button(cr, hits, right - bw, mid - 10, "back", lambda: self.d.revert() or False, h=20, size=11,
                        glyph=GLYPH_UNDO) + 6
        bw = self.chip_w(cr, "keep", GLYPH_CHECK)
        button(cr, hits, right - bw, mid - 10, "keep", lambda: self.d.keep() or False, h=20, size=11,
               glyph=GLYPH_CHECK, on=True, tone="ok")
        return y + self.PENDING_H

    def draw_map(self, cr, hits: Hits, x: float, y: float, w: float, h: float) -> None:
        """Every output to scale at its logical position; the ones that are off beside,
        greyed."""
        d = self.d
        core.rrect(cr, x, y, w, h, 6)
        cr.set_source_rgba(*rgba("bg1", 0.45))
        cr.fill()
        if not d.outputs:
            text(cr, x + w / 2, y + h / 2, "no answer from niri", 12, "dim", align=0.5, valign=0.5)
            return
        boxes = []  # (name, lx, ly, lw, lh, on)
        for name in d.order():
            o = d.outputs[name]
            if live(o):
                lg = o["logical"]
                boxes.append((name, lg["x"], lg["y"], lg["width"], lg["height"], True))
        if boxes:
            x0 = min(b[1] for b in boxes)
            y0 = min(b[2] for b in boxes)
            x1 = max(b[1] + b[3] for b in boxes)
        else:
            x0 = y0 = x1 = 0
        gap = max(240.0, (x1 - x0) * 0.08)
        ox = x1 + (gap if boxes else 0)
        for name in d.order():
            o = d.outputs[name]
            if not live(o):
                lw, lh = logical_size(o)
                boxes.append((name, ox, y0, lw, lh, False))
                ox += lw + gap
        bx1 = max(b[1] + b[3] for b in boxes)
        by1 = max(b[2] + b[4] for b in boxes)
        pad = 10
        k = min((w - 2 * pad) / max(1, bx1 - x0), (h - 2 * pad) / max(1, by1 - y0))
        # Centre the whole drawing in the well.
        cx = x + (w - (bx1 - x0) * k) / 2
        cy = y + (h - (by1 - y0) * k) / 2
        for name, lx, ly, lw, lh, on in boxes:
            rx, ry = cx + (lx - x0) * k + 1.5, cy + (ly - y0) * k + 1.5
            rw, rh = lw * k - 3, lh * k - 3
            self.draw_screen(cr, name, d.outputs[name], rx, ry, rw, rh, on)
            hits.add(rx, ry, rw, rh, lambda n=name: self.select(n))

    def draw_screen(self, cr, name: str, o: dict, x, y, w, h, on: bool) -> None:
        picked, focused = name == self.out, name == self.d.focused and on
        core.rrect(cr, x, y, w, h, 5)
        if on:
            cr.set_source_rgba(*rgba("accent", 0.24) if picked else rgba("bg2"))
        else:
            cr.set_source_rgba(*rgba("accent", 0.10) if picked else rgba("bg", 0.6))
        cr.fill_preserve()
        if focused:
            cr.set_source_rgba(*rgba("accent"))
            cr.set_line_width(2)
        elif on:
            cr.set_source_rgba(*rgba("accent", 0.7) if picked else rgba("bg3"))
            cr.set_line_width(1)
        else:
            cr.set_source_rgba(*rgba("accent", 0.6) if picked else rgba("bg3"))
            cr.set_line_width(1)
            cr.set_dash([3, 3])
        cr.stroke()
        cr.set_dash([])
        m = current(o)
        model = short_model(o)
        # Each line: its texts, longest first; the first that fits the box is drawn.
        lines = [((name,), 12, "title" if on else "fg", True)]
        if model:
            lines.append(((model,), 10, "fg" if on else "dim", False))
        if on and m:
            t = transform(o)
            turn = "" if t == "normal" else (f" · {t}" if t.startswith("flipped") else f" · {t}°")
            res = f"{m['width']}×{m['height']}"
            lines.append(((f"{res} · {hz(m['refresh_rate'])} Hz", res, f"{m['width']}"), 10, "fg2", False))
            lines.append(((f"×{o['logical']['scale']:g}{turn}", f"×{o['logical']['scale']:g}"), 10, "fg2", False))
        else:
            lines.append((("off",), 10, "dim", True))
        # As many lines as the box holds; a small box loses the model first.
        lh = 13
        fit = max(1, int((h - 6) // lh))
        if fit < len(lines) and model:
            lines = [ln for ln in lines if ln[0] != (model,)]
        lines = lines[:fit]
        ty = y + (h - len(lines) * lh) / 2
        for texts, size, tone, bold in lines:
            s = next((t for t in texts if core.text_w(cr, t, size, bold) <= w - 8), texts[-1])
            text(cr, x + w / 2, ty + lh / 2, s, size, tone, bold=bold, align=0.5, valign=0.5, width=max(10, w - 8))
            ty += lh

    def draw_settings(self, cr, hits: Hits, P: float, y: float) -> float:
        d = self.d
        W = self.W
        o = self.output()
        if o is None:
            text(cr, P, y, "no screen", 13, "dim")
            return y + 30 + self.SETTINGS * 28 + 8
        on = live(o)
        nw = text(cr, P, y, self.out, 15, "title", bold=True)
        model = short_model(o)
        tags = model + (" · focused" if self.out == d.focused and on else "")
        st = d.status.get(self.out)
        right = W - P
        if st:
            words = st[1] + ("…" if st[0] == "warn" and d.busy and not st[1].endswith("…") else "")
            right -= text(cr, right, y + 3, words, 12, st[0], align=1, width=W / 2 - P) + 10
        text(cr, P + nw + 10, y + 3, tags, 12, "dim", width=max(20, right - P - nw - 10))
        y += 30
        lx, x0 = P, P + self.LABEL_W
        busy = d.busy

        # power, and VRR on the same line
        text(cr, lx, y + self.CHIP_H / 2, "power", 11, "dim", valign=0.5)
        x = x0
        x += self.chip(cr, hits, x, y, "on", lambda: d.apply(self.out, "on", words="turning on") or False,
                       glyph=GLYPH_POWER, on=on, tone="ok", disabled=busy or on, why="", key=self.out) + 6
        can = d.can_off(self.out)
        x += self.chip(cr, hits, x, y, "off", lambda: d.apply(self.out, "off", words="turning off") or False,
                       glyph=GLYPH_OFF, on=not on, tone="bg3", disabled=busy or not can,
                       why="" if not on else "the only screen on: it stays on", key=self.out) + 6
        if o.get("vrr_supported"):
            vx = W - P - 2 * 44 - 6
            text(cr, vx - 8, y + self.CHIP_H / 2, "VRR", 11, "dim", valign=0.5, align=1)
            vrr = bool(o.get("vrr_enabled"))
            for i, (label, val) in enumerate((("on", True), ("off", False))):
                self.chip(cr, hits, vx + i * 50, y, label,
                          lambda v=val: d.apply(self.out, "vrr", "on" if v else "off", words="VRR") or False,
                          on=vrr == val, tone="ok" if val else "bg3", disabled=busy or not on or vrr == val,
                          why="turn it on first", key=self.out, w=44)
        y += 28

        y = self.draw_bright(cr, hits, lx, x0, y, on)

        # scale
        text(cr, lx, y + self.CHIP_H / 2, "scale", 11, "dim", valign=0.5)
        cur = o["logical"]["scale"] if on else None
        scales = list(SCALES)
        if cur is not None and all(abs(cur - s) > 1e-3 for s in scales):
            scales.append(cur)
            scales.sort()
        x = x0
        for s in scales:
            here = cur is not None and abs(cur - s) < 1e-3
            x += self.chip(cr, hits, x, y, f"{s:g}", lambda s=s: d.apply(self.out, "scale", f"{s:g}",
                                                                          words=f"scale {s:g}") or False,
                           on=here, disabled=busy or not on or here, why="turn it on first", key=self.out,
                           w=max(40, self.chip_w(cr, f"{s:g}", None))) + 6
        if on:
            lg = o["logical"]
            text(cr, W - P, y + self.CHIP_H / 2, f"{lg['width']}×{lg['height']} logical", 11, "dim", align=1,
                 valign=0.5)
        y += 28

        # rotation
        text(cr, lx, y + self.CHIP_H / 2, "rotate", 11, "dim", valign=0.5)
        t = transform(o) if on else None
        x = x0
        for arg, label in TRANSFORMS:
            here = t == arg
            x += self.chip(cr, hits, x, y, label, lambda a=arg: d.apply(self.out, "transform", a,
                                                                        words=f"rotating {a}") or False,
                           on=here, disabled=busy or not on or here, why="turn it on first", key=self.out,
                           w=max(44, self.chip_w(cr, label, None))) + 6
        if t and t.startswith("flipped"):
            self.chip(cr, hits, x, y, t, lambda: False, on=True, disabled=True, why="", key=self.out)
        y += 28
        return y + 8

    def draw_bright(self, cr, hits: Hits, lx: float, x0: float, y: float, on: bool) -> float:
        """The slider (click sets, the wheel steps 5 %, `-` / `=` when pinned) and the %;
        or why there is none."""
        W, P, mid = self.W, self.P, y + self.CHIP_H / 2
        self.bright_row = (y - 3, y + 25)
        text(cr, lx, mid, "bright", 11, "dim", valign=0.5)
        if not on:
            text(cr, x0, mid, "turn it on first", 11, "bg3", valign=0.5)
            return y + 28
        b = self.d.bright
        pct = b.get(self.out, self.d.outputs)
        if pct is None:
            why = b.why.get(self.out, "reading…")
            text(cr, x0, mid, why, 11, "dim", valign=0.5, width=W - P - x0)
            return y + 28
        sw = W - P - x0 - 58
        slider(cr, x0 + 6, mid, sw - 12, pct, False)
        hits.add(x0, y, sw, self.CHIP_H, lambda: self.bright_from_pointer(x0 + 6, sw - 12))
        sending = b.busy == self.out or self.out in b.want
        text(cr, W - P, mid, f"{pct}%", 12, "warn" if sending else "title", align=1, valign=0.5)
        return y + 28

    def draw_modes(self, cr, hits: Hits, P: float, y: float) -> float:
        W = self.W
        ms = self.modes()
        end = y + self.list_h()
        o = self.output()
        on = o is not None and live(o)
        count = f"{len(ms)} modes" + ("" if on or not ms else " · on first")
        cw = text(cr, W - P, y - 1, count, 11, "dim", align=1) + 8 if ms else 0
        heading(cr, P, y, "modes", W - 2 * P - cw - 4)
        y += 22
        self.rows = []
        if not ms:
            text(cr, P + 4, y + 4, "no modes", 12, "dim")
            return end
        self.top = max(0, min(self.top, len(ms) - self.ROWS))
        shown = ms[self.top:self.top + self.ROWS]
        for i, (m, cur) in enumerate(shown, start=self.top):
            self.draw_mode(cr, hits, P, y, i, m, cur, on)
            self.rows.append((y, y + self.ROW_H, i))
            y += self.ROW_H
        more = len(ms) - self.top - len(shown)
        if len(ms) > self.ROWS:
            words = f"▾ {more} more · scroll" if more else f"▴ {self.top} above"
            text(cr, W / 2, y + 1, words, 10, "dim", align=0.5)
        return end

    def draw_mode(self, cr, hits: Hits, P: float, y: float, i: int, m: dict, cur: bool, on: bool) -> None:
        W, H = self.W, self.ROW_H
        x0, rw, mid = P - 6, W - 2 * P + 12, y + H / 2
        picked = i == self.sel or i == self.hovered
        if cur or picked:
            core.rrect(cr, x0, y + 1, rw, H - 2, 7)
            if cur:
                cr.set_source_rgba(*rgba("accent", 0.20))
                cr.fill_preserve()
                cr.set_source_rgba(*rgba("accent", 0.55 if picked else 0.35))
                cr.set_line_width(1)
                cr.stroke()
            else:
                cr.set_source_rgba(*rgba("bg1"))
                cr.fill()
            if i == self.sel:  # the keyboard's mark
                core.rrect(cr, x0 + 1, y + 6, 3, H - 12, 1.5)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
        hits.add(x0, y, rw, H, lambda: self.pick_mode(i))
        dim = not on
        x = P + 4
        res = f"{m['width']} × {m['height']}"
        text(cr, x, mid, res, 13, "dim" if dim else ("title" if cur or picked else "fg2"), bold=cur, valign=0.5)
        x += 116
        text(cr, x, mid, f"{hz(m['refresh_rate'])} Hz", 12, "dim" if dim else "fg", valign=0.5)
        x += 74
        r = ratio(m["width"], m["height"])
        if r:
            text(cr, x, mid, r, 11, "dim", valign=0.5)
        x += 44
        if cur:
            core.icon(cr, x, mid, GLYPH_CHECK, 12, "accent")
            x += 18
        if m.get("is_preferred"):
            bw = core.text_w(cr, "preferred", 9) + 8
            core.rrect(cr, x + 0.5, mid - 7.5, bw, 14, 4)
            cr.set_source_rgba(*rgba("bg2"))
            cr.set_line_width(1)
            cr.stroke()
            text(cr, x + 4.5, mid, "preferred", 9, "dim", valign=0.5)
        if picked and not cur and on:
            text(cr, W - P, mid, "click or Enter: try it", 10, "dim", align=1, valign=0.5)

    # -- chips -----------------------------------------------------------------

    @staticmethod
    def chip_w(cr, label: str, glyph: str | None) -> float:
        gw = core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 5 if glyph else 0
        return core.text_w(cr, label, 11) + gw + 18

    def chip(self, cr, hits: Hits, x, y, label, action, *, glyph=None, on=False, tone="accent",
             disabled=False, why="", key="", w=None) -> float:
        """core.button at the settings' size; a disabled chip is drawn faint and a
        click on it says why (in the status of `key`)."""
        h = self.CHIP_H
        if not disabled or on:
            bw = button(cr, hits, x, y, label, action, on=on, tone=tone, h=h, size=11, glyph=glyph,
                        w=w or self.chip_w(cr, label, glyph))
            if disabled:  # on, and nothing to do: the click does nothing
                hits.items.pop()
                hits.add(x, y, bw, h, lambda: False)
            return bw
        w = w or self.chip_w(cr, label, glyph)
        core.rrect(cr, x + 0.5, y + 0.5, w - 1, h - 1, h / 2)
        cr.set_source_rgba(*rgba("bg2"))
        cr.set_line_width(1)
        cr.set_dash([2, 2])
        cr.stroke()
        cr.set_dash([])
        tw = core.text_w(cr, label, 11)
        gw = core.text_w(cr, glyph, 13, family=core.ICON_FONT) + 5 if glyph else 0
        cx = x + (w - tw - gw) / 2
        if glyph:
            core.icon(cr, cx, y + h / 2, glyph, 13, "bg3")
        text(cr, cx + gw, y + h / 2, label, 11, "bg3", valign=0.5)
        if why:
            hits.add(x, y, w, h, lambda: self.d.status.__setitem__(key, ("warn", why)) or False)
        else:
            hits.add(x, y, w, h, lambda: False)
        return w
