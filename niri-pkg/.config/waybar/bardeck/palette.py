"""The launcher, in rofi's place on Mod+D: one field, and the best ten of everything
that can be run, opened or focused. A key-opened panel (no strip): `bardeck open
palette`.

Sources (Tab cycles a filter over them):
  apps      the .desktop files of the XDG data dirs (Gio reads them in-process;
            NoDisplay / Hidden / OnlyShowIn are honoured), ranked by the fuzzy score
            and how often each was launched from here (~/.local/state/bardeck/palette.json)
  windows   niri's open windows (its socket): Enter focuses one
  commands  the programs on PATH: with a `>` first, or low in the list when the first
            word names one; run through rofi-run, which decides about a terminal (its
            rules and ~/.config/rofi/run-overrides)
  history   every command line run before, with its arguments ("systemctl suspend",
            "cam help"): rofi's own run history (~/.cache/rofi-4.runcache) and the
            ones run from here. A line whose program is gone is left out.

rofi's history seeds the ranking: its counts (rofi-4.runcache for command lines,
rofi3.druncache for apps) add to the palette's own (palette.json), so what was used
most under rofi comes first here too. Both files are read again when they change
(rofi still runs as Mod+D's fallback). Commands start in the home directory, as
rofi's did (its history has lines like "android/bin/down").
  actions   niri-screen-switch's entries (screens, sound, theme, font), network.sh's,
            vpn.sh's and power-profile.sh's menu entries (core.menu_action), and
            "Open <panel>" for every bardeck panel
  `=`       a calculator (also when the line is plain arithmetic): numbers, + - * / // %
            ^ **, and math's functions; Enter copies the result
  `:`       a web search, or an address to open

Launching goes through niri (its Spawn action, on its socket): the program is
niri's child, with niri's environment and priority. core.spawn would make it the
daemon's, at the daemon's nice 5, which every child inherits.

Keys (the field has them all): Enter run, Ctrl+n / Ctrl+p or the arrows move,
Tab / Shift+Tab the filter, Ctrl+u clear, Ctrl+w or Ctrl+BackSpace a word back,
Ctrl+v paste, Esc close.
"""

from __future__ import annotations

import ast
import json
import math
import os
import queue
import re
import shlex
import subprocess
import threading
import time
import zlib

import cairo

from . import core
from .core import Hits, button, rgba, text
from .deck import Panel
from .displays import GLYPH_MONITOR, GLYPH_PAD, GLYPH_SOUND, SWITCH
from .net import NET_ACTIONS, VPN_CHOICES
from .power import PROFILE
from .ws import action as niri_action
from .ws import niri

ROFI_RUN = f"{core.REAL_HOME}/bin/rofi-run"
FEATURES_MD = f"{core.REAL_HOME}/.config/niri/BAR-FEATURES.md"
STATE = f"{core.REAL_HOME}/.local/state/bardeck/palette.json"
ROFI_RUNCACHE = f"{core.REAL_HOME}/.cache/rofi-4.runcache"  # "COUNT LINE\x1fSHOWN" per line
ROFI_DRUNCACHE = f"{core.REAL_HOME}/.cache/rofi3.druncache"  # "COUNT DESKTOP-ID" per line
SEARCH_URL = "https://www.google.com/search?q={}"
ROWS = 10
# X11 tools from the i3 days, in rofi's history: they do nothing under niri. Still
# found when typed (with a note), never offered on an empty field.
X11_ONLY = {"scrot": "niri's screenshot (Mod+Alt+Shift+S)", "xkill": "", "arandr": "the displays panel",
            "xrandr": "the displays panel", "xdotool": "", "xprop": "", "xev": "", "feh": "", "i3-msg": "",
            "xclip": "wl-copy", "xsel": "wl-copy", "record-window": "niri-record-window"}
COMMANDS_EVERY = 60.0  # seconds a PATH scan is reused

GLYPH_SEARCH, GLYPH_CMD, GLYPH_CALC = "\U000f0349", "\U000f018d", "\U000f00ec"
GLYPH_WEB, GLYPH_GOOGLE, GLYPH_WINDOW = "\U000f059f", "\U000f02ad", "\U000f05af"
GLYPH_PANEL, GLYPH_THEME, GLYPH_FONT = "\U000f056e", "\U000f03d8", "\U000f09a8"
GLYPH_VPN, GLYPH_NOTHING = "\U000f099d", "\U000f0349"

# A row's chip: what the kind is called, and its colour.
KINDS = {"app": ("app", "accent"), "window": ("window", "blue"), "cmd": ("command", "purple"),
         "action": ("action", "orange"), "panel": ("panel", "aqua"), "calc": ("calc", "ok"),
         "web": ("web", "info")}
FILTERS = (("all", None), ("apps", {"app"}), ("windows", {"window"}), ("commands", {"cmd"}),
           ("actions", {"action", "panel"}))
PANEL_TITLES = (("audio", "Audio"), ("net", "Network"), ("dev", "Devices"), ("disp", "Displays"),
                ("sys", "System"), ("power", "Power"), ("notif", "Notifications"), ("clock", "Calendar"),
                ("quota", "Claude quota"), ("clip", "Clipboard"))
SWITCH_GLYPHS = {"Game": GLYPH_PAD, "Screen": GLYPH_MONITOR, "Sound": GLYPH_SOUND, "Theme": GLYPH_THEME,
                 "Font": GLYPH_FONT}
TILE_TONES = ("blue", "aqua", "purple", "orange", "ok", "warn")
FIELD_CODES = {"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m"}
ARITHMETIC = re.compile(r"^[\d\s.+\-*/%^()]*\d[\d\s.+\-*/%^()]*$")
URLISH = re.compile(r"^(https?://\S+|[\w-]+(\.[\w-]+)+(:\d+)?(/\S*)?)$")


# ── matching ──────────────────────────────────────────────────────────────────


def _score(s: str, pos: list[int], prefix: bool) -> float:
    sc, prev = 0.0, -2
    for k, i in enumerate(pos):
        sc += 1
        if i == 0 or not s[i - 1].isalnum() or (s[i].isupper() and s[i - 1].islower()):
            sc += 8 if k == 0 else 5  # a word's first letter
        if i == prev + 1:
            sc += 4
        elif k:
            sc -= min(3.0, (i - prev - 1) * 0.3)
        prev = i
    sc -= pos[0] * 0.15 + (len(s) - len(pos)) * 0.02  # early, and short names, first
    return sc + (10 if prefix else 0)


def fuzzy(q: str, s: str) -> tuple[float, list[int]] | None:
    """q's letters in order in s, any case: (score, where they matched), the best of a
    few starts; None when they do not all appear."""
    if not q:
        return 0.0, []
    ql, sl = q.lower(), s.lower()
    it = iter(sl)
    if not all(c in it for c in ql):
        return None
    best = None
    start = sl.find(ql[0])
    for _ in range(8):
        if start < 0:
            break
        pos, j = [start], start
        for c in ql[1:]:
            j = sl.find(c, j + 1)
            if j < 0:
                break
            pos.append(j)
        if len(pos) < len(ql):
            break
        sc = _score(s, pos, sl.startswith(ql))
        if best is None or sc > best[0]:
            best = (sc, pos)
        start = sl.find(ql[0], start + 1)
    return best


def marked(s: str, pos: list[int], tone: str) -> str:
    """Pango markup: s escaped, the letters at pos in `tone`, bold."""
    from gi.repository import GLib

    hit = set(pos)
    colour = core.PALETTE.get(tone, tone)
    out, i = [], 0
    while i < len(s):
        j = i
        while j < len(s) and (j in hit) == (i in hit):
            j += 1
        chunk = GLib.markup_escape_text(s[i:j], -1)
        out.append(f'<span foreground="{colour}" weight="bold">{chunk}</span>' if i in hit else chunk)
        i = j
    return "".join(out)


# ── the calculator ────────────────────────────────────────────────────────────

MATH = {n: getattr(math, n) for n in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sinh",
                                       "cosh", "tanh", "log", "log10", "log2", "exp", "floor", "ceil",
                                       "factorial", "hypot", "degrees", "radians", "gcd", "lcm", "comb",
                                       "perm", "trunc")}
MATH.update(abs=abs, round=round, min=min, max=max)
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a ** b}


def _big(a, b) -> bool:
    """Would a ** b take long to compute (or print)?"""
    if isinstance(b, int) and isinstance(a, int) and abs(a) > 1:
        return abs(b) * math.log2(abs(a)) > 20_000
    return isinstance(b, (int, float)) and abs(b) > 10_000 and isinstance(a, int) and abs(a) > 1


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in CONSTANTS:
        return CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and _big(a, b):
            raise ValueError("too big")
        if isinstance(node.op, ast.Mult) and isinstance(a, int) and isinstance(b, int) and \
                a.bit_length() + b.bit_length() > 70_000:
            raise ValueError("too big")
        return _BIN[type(node.op)](a, b)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in MATH
            and not node.keywords):
        args = [_eval(a) for a in node.args]
        if node.func.id in ("factorial", "comb", "perm") and any(abs(a) > 3000 for a in args):
            raise ValueError("too big")
        return MATH[node.func.id](*args)
    raise ValueError("not arithmetic")


def calc(expr: str) -> str:
    """The value of an arithmetic line, as text. ValueError (with a short reason)
    when it is not one. `^` is a power, as on a calculator."""
    expr = expr.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not expr:
        raise ValueError("type a sum")
    try:
        v = _eval(ast.parse(expr, mode="eval"))
    except SyntaxError:
        raise ValueError("incomplete") from None
    except ZeroDivisionError:
        raise ValueError("division by zero") from None
    except (TypeError, OverflowError, RecursionError) as err:
        raise ValueError(str(err).split(":")[0][:40] or "no value") from None
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.12g}"
    s = str(v)
    return s if len(s) <= 40 else f"{v:.10e}"


# ── what a row runs ───────────────────────────────────────────────────────────


def run_argv(argv: list[str]) -> None:
    """Start argv as niri's child (see the module's docstring); core.spawn without niri."""
    if not (os.environ.get("NIRI_SOCKET") and niri({"Action": {"Spawn": {"command": argv}}}) is not None):
        core.spawn(argv)


def exec_argv(info) -> list[str]:
    """A .desktop file's Exec as argv: its field codes dropped or filled in."""
    raw = info.get_string("Exec") or info.get_commandline() or ""
    try:
        words = shlex.split(raw)
    except ValueError:
        words = raw.split()
    out = []
    for w in words:
        if w in FIELD_CODES:
            continue
        if w == "%i":
            icon = info.get_string("Icon")
            out += ["--icon", icon] if icon else []
            continue
        w = w.replace("%%", "\0").replace("%c", info.get_name() or "").replace("%k", info.get_filename() or "")
        w = re.sub(r"%[fFuUdDnNvmi]", "", w).replace("\0", "%")
        if w:
            out.append(w)
    return out


def launch_app(info) -> bool:
    argv = exec_argv(info)
    if not argv:
        return False
    workdir = info.get_string("Path")
    if workdir:
        argv = ["env", "-C", workdir, *argv]
    run_argv([ROFI_RUN, "--term", *argv] if info.get_boolean("Terminal") else argv)
    return True


def copy_text(s: str) -> None:
    try:
        subprocess.Popen(["wl-copy", "--", s], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as err:
        core.log(f"palette: wl-copy: {err!r}")


# ── rows ──────────────────────────────────────────────────────────────────────


class Item:
    """One row: what it shows, how it ranks, what Enter does (run() → True: close)."""

    __slots__ = ("kind", "key", "name", "sub", "extra", "gicon", "glyph", "run", "score", "pos", "rank")

    def __init__(self, kind: str, key: str, name: str, sub: str = "", *, extra: str = "", gicon=None,
                 glyph: str = "", run=None, rank: float = 0.0):
        self.kind, self.key, self.name, self.sub, self.extra = kind, key, name, sub, extra
        self.gicon, self.glyph, self.run, self.rank = gicon, glyph, run, rank
        self.score, self.pos = 0.0, []

    def __repr__(self):
        return f"Item({self.kind} {self.name!r} {self.score:.1f})"


class Usage:
    """How often each row was run from here, and when last: the ranking's memory."""

    def __init__(self, path: str = STATE):
        self.path = path
        self.counts: dict[str, int] = {}
        self.last: dict[str, float] = {}
        self.mtime = -1.0
        self.seed: dict[str, int] = {}  # rofi's counts, by the same keys ("run:LINE", "app:ID")
        self._seed_at: tuple = ()

    def load(self) -> None:
        self.load_rofi()
        try:
            mtime = os.stat(self.path).st_mtime
            if mtime == self.mtime:
                return
            with open(self.path) as fh:
                raw = json.load(fh)
            self.counts = {k: int(v) for k, v in raw.get("counts", {}).items()}
            self.last = {k: float(v) for k, v in raw.get("last", {}).items()}
            self.mtime = mtime
        except (OSError, ValueError, AttributeError):
            pass

    def load_rofi(self) -> None:
        """rofi's run and drun history, when either file changed."""
        stamp = []
        for path in (ROFI_RUNCACHE, ROFI_DRUNCACHE):
            try:
                stamp.append(os.stat(path).st_mtime)
            except OSError:
                stamp.append(None)
        if tuple(stamp) == self._seed_at:
            return
        seed: dict[str, int] = {}
        for path, prefix in ((ROFI_RUNCACHE, "run:"), (ROFI_DRUNCACHE, "app:")):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        count, _, rest = line.rstrip("\n").partition(" ")
                        rest = rest.split("\x1f", 1)[0].strip()
                        if rest and count.isdigit():
                            seed[prefix + rest] = seed.get(prefix + rest, 0) + int(count)
            except OSError:
                continue
        self.seed, self._seed_at = seed, tuple(stamp)

    def total(self, key: str) -> int:
        return self.counts.get(key, 0) + self.seed.get(key, 0)

    def bump(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1
        self.last[key] = time.time()
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(f"{self.path}.tmp", "w") as fh:
                json.dump({"counts": self.counts, "last": self.last}, fh)
            os.replace(f"{self.path}.tmp", self.path)
            self.mtime = os.stat(self.path).st_mtime
        except OSError as err:
            core.log(f"palette: {self.path}: {err!r}")

    def bonus(self, key: str) -> float:
        return 3.0 * math.log2(1 + self.total(key))


class Icons:
    """App icons, found in the icon theme on the main loop (fast) and drawn from their
    files on a thread of their own (an SVG takes 10-40 ms): SVG with librsvg, PNG with
    cairo, both in-process (GdkPixbuf would go through glycin, a loader process)."""

    def __init__(self, loaded):
        self.loaded = loaded  # called on the main loop when an icon arrives
        self.done: dict[tuple, cairo.ImageSurface | None] = {}
        self.files: dict[tuple, str | None] = {}
        self.q: queue.Queue = queue.Queue()
        self._thread = None
        self._told = False

    def file(self, gicon, px: int) -> str | None:
        key = (gicon.to_string() if gicon is not None else "", px)
        if key not in self.files:
            path = None
            if gicon is not None:
                from gi.repository import Gtk

                info = Gtk.IconTheme.get_default().lookup_by_gicon(gicon, px, Gtk.IconLookupFlags.FORCE_SIZE)
                path = info.get_filename() if info is not None else None
            self.files[key] = path
        return self.files[key]

    def get(self, gicon, px: int):
        path = self.file(gicon, px)
        if path is None:
            return None
        key = (path, px)
        if key not in self.done:
            self.done[key] = None
            self.q.put(key)
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, daemon=True, name="palette-icons")
                self._thread.start()
        return self.done[key]

    def _work(self) -> None:
        from gi.repository import GLib

        while True:
            path, px = self.q.get()
            try:
                self.done[(path, px)] = self.render(path, px)
            except Exception as err:
                if core.TRACE:
                    core.log(f"palette: icon {path}: {err!r}")
            if not self._told:
                self._told = True
                GLib.idle_add(self._tell)

    def _tell(self) -> bool:
        self._told = False
        self.loaded()
        return False

    @staticmethod
    def render(path: str, px: int):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        cr = cairo.Context(surf)
        if path.endswith(".svg"):
            import gi

            gi.require_version("Rsvg", "2.0")
            from gi.repository import Rsvg

            handle = Rsvg.Handle.new_from_file(path)
            vp = Rsvg.Rectangle()
            vp.x, vp.y, vp.width, vp.height = 0, 0, px, px
            handle.render_document(cr, vp)
        elif path.endswith(".png"):
            src = cairo.ImageSurface.create_from_png(path)
            w, h = src.get_width(), src.get_height()
            k = px / max(w, h, 1)
            cr.translate((px - w * k) / 2, (px - h * k) / 2)
            cr.scale(k, k)
            cr.set_source_surface(src, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_BEST)
            cr.paint()
        else:
            return None  # xpm & co.: the letter tile
        surf.flush()
        return surf


# ── the panel ─────────────────────────────────────────────────────────────────


class PalettePanel(Panel):
    name = "palette"
    W = 620
    ROW_H = 34
    ICON = 20
    TOP = 92  # the rows start here: the field, the filter chips
    typing = True  # Panel.typing: the field has every key, always

    def __init__(self, usage: Usage | None = None):
        self.usage = usage or Usage()
        self.icons = Icons(lambda: self.redraw())
        self.buf = ""
        self.filter = 0
        self.sel = 0
        self.hovered = -1
        self.note = ""
        self.apps: list[Item] = []
        self.windows: list[Item] = []
        self.actions: list[Item] = []
        self.history: list[Item] = []
        self.switch_entries: list[str] | None = None
        self._commands: tuple[float, dict[str, str]] = (0.0, {})  # name -> its PATH directory
        self._results: tuple[tuple, list[Item]] | None = None
        self.rows: list[tuple[float, float, int]] = []
        self.gen = 0  # bumped when the sources change: the results are worked out again

    # -- sources ---------------------------------------------------------------

    def opened(self) -> None:
        self.buf, self.filter, self.sel, self.hovered, self.note = "", 0, 0, -1, ""
        self.usage.load()
        try:
            self.apps = self.load_apps()
        except Exception as err:  # a bad .desktop file must not cost the launcher
            core.log(f"palette: apps: {err!r}")
        self.windows = self.load_windows()
        self.actions = self.load_actions()
        self.history = self.load_history()
        self.gen += 1
        self._results = None

    def closed(self) -> None:
        self.windows = []
        self._results = None

    def load_apps(self) -> list[Item]:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        out = []
        for info in Gio.AppInfo.get_all():
            if not info.should_show():  # NoDisplay, OnlyShowIn / NotShowIn (Hidden ones are not listed)
                continue
            argv = exec_argv(info)
            exe = os.path.basename(argv[0]) if argv else ""
            generic = info.get_generic_name() or ""
            words = " ".join([generic, exe, info.get_id() or "", *(info.get_keywords() or [])])
            out.append(Item("app", f"app:{info.get_id()}", info.get_name() or exe, generic or exe, extra=words,
                            gicon=info.get_icon(), run=lambda info=info: launch_app(info)))
        return out

    def load_windows(self) -> list[Item]:
        wins = niri("Windows") or []
        spaces = {w.get("id"): w for w in (niri("Workspaces") or [])}
        out = []
        for w in sorted(wins, key=lambda w: not w.get("is_focused")):
            app = w.get("app_id") or ""
            ws = spaces.get(w.get("workspace_id")) or {}
            where = ws.get("name") or (str(ws["idx"]) if "idx" in ws else "")
            out.append(Item("window", "", w.get("title") or app or "window",
                            " · ".join(x for x in (app, f"ws {where}" if where else "") if x),
                            extra=app, gicon=self.app_gicon(app), glyph=GLYPH_WINDOW, rank=2.0,
                            run=lambda wid=w.get("id"): niri_action("FocusWindow", id=wid) or True))
        return out

    @staticmethod
    def app_gicon(app_id: str):
        """The icon of the app whose .desktop file is named like the app id, as ws does."""
        from gi.repository import Gio

        for cand in dict.fromkeys((app_id, app_id.lower(), app_id.split(".")[-1].lower())):
            if not cand:
                continue
            try:
                info = Gio.DesktopAppInfo.new(f"{cand}.desktop")
            except TypeError:
                info = None
            if info is not None and info.get_icon() is not None:
                return info.get_icon()
        return None

    def load_actions(self) -> list[Item]:
        if self.switch_entries is None:
            try:
                out = subprocess.run([SWITCH, "--list"], capture_output=True, text=True, timeout=2).stdout
                self.switch_entries = [line.strip() for line in out.splitlines() if line.strip()]
            except (OSError, subprocess.TimeoutExpired):
                self.switch_entries = []
        items = []
        for entry in self.switch_entries:
            items.append(Item("action", f"act:{entry}", entry, "niri-screen-switch",
                              glyph=SWITCH_GLYPHS.get(entry.split(":")[0], GLYPH_MONITOR),
                              run=lambda e=entry: core.spawn([SWITCH, e]) or True))
        for label, glyph in NET_ACTIONS:
            items.append(Item("action", f"act:net:{label}", f"Network: {label}", "network.sh", glyph=glyph,
                              run=lambda c=label: core.menu_action("network.sh", 3, c) or True))
        for label, choice, iface in VPN_CHOICES:
            items.append(Item("action", f"act:vpn:{choice}", f"VPN: {choice}", "vpn.sh", glyph=GLYPH_VPN,
                              run=lambda c=choice: core.menu_action("vpn.sh", 3, c) or True))
        for prof, (glyph, _short, _tone) in PROFILE.items():
            items.append(Item("action", f"act:power:{prof}", f"Power profile: {prof}", "power-profile.sh",
                              glyph=glyph, run=lambda p=prof: core.menu_action("power-profile.sh", 1, p) or True))
        # The short list of what the bar can do (13 Oct 2026; the daily tips read it too).
        items.append(Item("action", "act:bar-features", "Bar features: what the bar can do",
                          "BAR-FEATURES.md · the short list", extra="help tips cheat sheet keys", glyph=GLYPH_PANEL, rank=20.0,
                          run=lambda: run_argv(["sh", "-c", f'emacsclient -c "{FEATURES_MD}" || xdg-open "{FEATURES_MD}"'])
                          or True))
        panels = self.deck.panels if self.deck is not None else {}
        for name, title in PANEL_TITLES:
            if name in panels or self.deck is None:
                items.append(Item("panel", f"panel:{name}", f"Open {title}", f"bardeck panel · {name}",
                                  extra=name, glyph=GLYPH_PANEL,
                                  run=lambda n=name: (self.deck.open(n) if self.deck else None) and False))
        return items

    def load_history(self) -> list[Item]:
        """Every command line run before (rofi's history and this palette's), as a row
        of its own; the ones whose program is gone are left out."""
        keys = {k for k in (*self.usage.seed, *self.usage.counts) if k.startswith("run:")}
        out = []
        for key in keys:
            line = key[4:]
            word = line.split()[0] if line.split() else ""
            if not word or not self.resolves(word):
                continue
            n = self.usage.total(key)
            item = self.command_item(line, word)
            item.sub = f"history · run {n}×" if n else "history"
            if os.path.basename(word) in X11_ONLY:
                instead = X11_ONLY[os.path.basename(word)]
                item.sub += " · X11 only" + (f": use {instead}" if instead else ": nothing on niri")
            item.extra = line
            out.append(item)
        return out

    def resolves(self, word: str) -> bool:
        """A program on PATH, or a path (relative to home, as rofi ran it) that exists."""
        if "/" in word:
            return os.access(os.path.join(core.REAL_HOME, os.path.expanduser(word)), os.X_OK)
        return word in self.commands()

    def commands(self) -> dict[str, str]:
        """Every program on PATH (name -> its directory, the first one wins, as the
        shell finds it), scanned at most once a minute, and only when asked."""
        at, names = self._commands
        if time.monotonic() - at < COMMANDS_EVERY and names:
            return names
        found: dict[str, str] = {}
        for d in os.environ.get("PATH", "/usr/bin").split(":"):
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if not e.name.startswith(".") and e.name not in found:
                            found[e.name] = d
            except OSError:
                continue
        names = dict(sorted(found.items()))
        self._commands = (time.monotonic(), names)
        return names

    def command_item(self, line: str, name: str, rank: float = 0.0) -> Item:
        rest = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
        shown = f"{name} {rest}".strip()

        def go():
            try:
                argv = [name, *shlex.split(rest)]
            except ValueError:
                argv = [name, *rest.split()]
            # From the home directory, as rofi ran it ("android/bin/down" is relative to it).
            run_argv(["env", "-C", core.REAL_HOME, ROFI_RUN, *argv])
            return True

        where = self.commands().get(name, "").replace(core.REAL_HOME, "~")
        # The key is the whole line: the history keeps "cam help" apart from "cam ship".
        return Item("cmd", f"run:{shown}", shown, where, glyph=GLYPH_CMD, run=go, rank=rank)

    # -- ranking ---------------------------------------------------------------

    def results(self) -> list[Item]:
        key = (self.buf, self.filter, self.gen)
        if self._results is None or self._results[0] != key:
            self._results = (key, self.rank())
        return self._results[1]

    def rank(self) -> list[Item]:
        q = self.buf.strip()
        kinds = FILTERS[self.filter][1]
        if self.buf.startswith("="):
            return [self.calc_item(self.buf[1:], strict=True)]
        if self.buf.startswith(":"):
            return self.web_items(self.buf[1:].strip())
        if self.buf.startswith(">"):
            return self.command_items(self.buf[1:].strip())

        pool = [i for i in (*self.apps, *self.windows, *self.actions, *self.history)
                if kinds is None or i.kind in kinds]
        out: list[Item] = []
        if not q:
            # Nothing typed: the most used first, then the windows, then the apps by name.
            for i in pool:
                i.score, i.pos = self.usage.bonus(i.key) + (1 if i.kind == "window" else 0), []
            used = sorted((i for i in pool if self.usage.total(i.key) and "X11 only" not in i.sub),
                          key=lambda i: (-self.usage.total(i.key), -self.usage.last.get(i.key, 0)))
            rest = sorted((i for i in pool if not self.usage.total(i.key) and i.kind != "cmd"),
                          key=lambda i: (i.kind != "window", i.kind != "app", i.name.lower()))
            return (used + rest)[:ROWS]
        words = q.lower().split()
        for i in pool:
            m = fuzzy(q, i.name)
            # The other words (generic name, keywords, the program): each typed word
            # as it is, not fuzzy; in a long keyword list almost anything is a subsequence.
            alt = 4.0 * len(words) if i.extra and all(w in i.extra.lower() for w in words) else None
            if m is None and alt is None:
                continue
            if m is not None and (alt is None or m[0] >= alt):
                i.score, i.pos = m[0], m[1]
            else:
                i.score, i.pos = alt, []
            i.score += i.rank + self.usage.bonus(i.key)
            out.append(i)
        out.sort(key=lambda i: -i.score)
        if kinds is None and ARITHMETIC.match(q) and any(c in q for c in "+-*/%^") and q[0] not in "-+":
            try:
                out.insert(0, self.calc_item(q))
            except ValueError:
                pass
        word = q.split()[0]
        if (kinds is None or "cmd" in kinds) and len(out) < ROWS and len(word) >= 2:
            # Low in the list: the programs whose name starts with the first word.
            names = [n for n in self.commands() if n.startswith(word)]
            names.sort(key=lambda n: (-self.usage.total(f"run:{n}"), len(n), n))
            have = {i.key for i in out}
            for n in names:
                if len(out) >= ROWS:
                    break
                it = self.command_item(q, n, rank=-50.0)
                if it.key in have:  # the history has this very line already
                    continue
                it.pos = list(range(len(word)))
                out.append(it)
        if not out and kinds is None:
            out = self.web_items(q)
        return out[:ROWS]

    def command_items(self, line: str) -> list[Item]:
        if not line:  # `>` alone: the history, most run first
            return sorted((i for i in self.history if "X11 only" not in i.sub),
                          key=lambda i: -self.usage.total(i.key))[:ROWS]
        word = line.split()[0]
        scored = []
        for n in self.commands():
            m = fuzzy(word, n)
            if m is not None:
                scored.append((m[0] + (20 if n == word else 0) + self.usage.bonus(f"run:{n}"), n, m[1]))
        scored.sort(key=lambda t: (-t[0], len(t[1])))
        out = []
        for sc, n, pos in scored[:ROWS]:
            it = self.command_item(line, n)
            it.score, it.pos = sc, pos
            out.append(it)
        return out

    def calc_item(self, expr: str, strict: bool = False) -> Item:
        try:
            value = calc(expr)
        except ValueError as err:
            if not strict:
                raise
            return Item("calc", "", f"= {expr.strip() or '…'}", str(err), glyph=GLYPH_CALC)
        return Item("calc", "", f"= {value}", f"{expr.strip()} · Enter copies it", glyph=GLYPH_CALC,
                    run=lambda: copy_text(value) or True)

    def web_items(self, q: str) -> list[Item]:
        if not q:
            return [Item("web", "", "search the web…", "type what to look for", glyph=GLYPH_GOOGLE)]
        if URLISH.match(q):
            url = q if "://" in q else f"https://{q}"
            return [Item("web", "", f"open {url}", "in the browser", glyph=GLYPH_WEB,
                         run=lambda: run_argv(["xdg-open", url]) or True)]
        from urllib.parse import quote_plus

        url = SEARCH_URL.format(quote_plus(q))
        return [Item("web", "", f"search Google for “{q}”", "in the browser", glyph=GLYPH_GOOGLE,
                     run=lambda: run_argv(["xdg-open", url]) or True)]

    # -- acting ----------------------------------------------------------------

    def activate(self, item: Item) -> bool:
        """Run a row. True when the panel should close."""
        if item.run is None:
            return False
        try:
            close = item.run()
        except Exception as err:
            self.note = f"{item.name}: {err}"[:80]
            core.log(f"palette: {item.name}: {err!r}")
            return False
        if item.key:
            self.usage.bump(item.key)
            self.gen += 1
        return close is not False

    def enter(self) -> None:
        res = self.results()
        if 0 <= self.sel < len(res) and self.activate(res[self.sel]):
            self.close()

    # -- input -----------------------------------------------------------------

    def edited(self) -> None:
        self.sel, self.hovered, self.note = 0, -1, ""

    def text_key(self, key: str, char: str, ctrl: bool) -> bool:
        n = len(self.results())
        if key in ("Return", "KP_Enter"):
            self.enter()
        elif key == "Down" or (ctrl and key == "n"):
            self.sel = min(n - 1, self.sel + 1)
        elif key == "Up" or (ctrl and key == "p"):
            self.sel = max(0, self.sel - 1)
        elif key == "Page_Down":
            self.sel = min(n - 1, self.sel + ROWS // 2)
        elif key == "Page_Up":
            self.sel = max(0, self.sel - ROWS // 2)
        elif key in ("Tab", "ISO_Left_Tab"):
            self.filter = (self.filter + (-1 if key == "ISO_Left_Tab" else 1)) % len(FILTERS)
            self.edited()
        elif ctrl and key in ("BackSpace", "w"):
            self.buf = re.sub(r"\S*\s*$", "", self.buf.rstrip()) if self.buf.strip() else ""
            self.edited()
        elif key == "BackSpace":
            self.buf = self.buf[:-1]
            self.edited()
        elif ctrl and key == "u":
            self.buf = ""
            self.edited()
        elif ctrl and key in ("v", "y"):
            self.paste()
            self.edited()
        elif char and not ctrl:
            self.buf += char
            self.edited()
        else:
            return False  # Esc: the Deck closes the panel
        return True

    def paste(self) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk

        got = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""
        self.buf += " ".join(got.split())

    def hover(self, x: float, y: float) -> bool:
        idx = next((i for y0, y1, i in self.rows if y0 <= y < y1 and 0 <= x < self.W), -1)
        if idx != self.hovered:
            self.hovered = idx
            return True
        return False

    def scroll(self, down: bool) -> bool:
        n = len(self.results())
        sel = max(0, min(n - 1, self.sel + (1 if down else -1)))
        if sel == self.sel:
            return False
        self.sel = sel
        return True

    def click(self, item: Item) -> bool:
        return self.activate(item)

    def pick_filter(self, i: int) -> bool:
        self.filter = i
        self.edited()
        return False

    # -- drawing ---------------------------------------------------------------

    def size(self):
        n = max(1, len(self.results()))
        return self.W, self.TOP + n * self.ROW_H + 8 + 24

    def draw(self, cr, hits: Hits) -> None:
        W, P = self.W, 16
        H = self.size()[1]
        core.panel_frame(cr, W, H)
        res = self.results()
        self.sel = max(0, min(self.sel, len(res) - 1))
        self.draw_field(cr, P, 12)

        # The filters, and how many rows there are.
        x, y = P - 4, 58
        for i, (label, _kinds) in enumerate(FILTERS):
            x += button(cr, hits, x, y, label, lambda i=i: self.pick_filter(i), on=i == self.filter,
                        tone="accent", h=20, size=11) + 6
        if self.note:
            text(cr, W - P, y + 10, self.note, 11, "hit", align=1, valign=0.5, width=W - x - P - 8)
        else:
            mode = {"=": "calculator", ":": "web", ">": "commands on PATH"}.get(self.buf[:1], "")
            if mode:
                text(cr, W - P, y + 10, mode, 11, "dim", align=1, valign=0.5)

        y = self.TOP
        self.rows = []
        if not res:
            text(cr, W / 2, y + self.ROW_H / 2, "nothing matches", 12, "dim", align=0.5, valign=0.5)
        dev = abs(cr.user_to_device_distance(1, 0)[0]) or 1.0
        for i, item in enumerate(res):
            self.draw_row(cr, hits, P, y, i, item, dev)
            self.rows.append((y, y + self.ROW_H, i))
            y += self.ROW_H
        hint = "Enter run · Tab filter · ↑↓ Ctrl+n/p · > command · = calc · : web · Esc close"
        text(cr, W / 2, H - 20, hint, 10, "dim", align=0.5)

    def draw_field(self, cr, P: float, y: float) -> None:
        x0, fw, fh = P - 6, self.W - 2 * P + 12, 38
        core.rrect(cr, x0 + 0.5, y + 0.5, fw - 1, fh - 1, 9)
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("accent"))
        cr.set_line_width(1.3)
        cr.stroke()
        mid = y + fh / 2
        glyph = {"=": GLYPH_CALC, ":": GLYPH_WEB, ">": GLYPH_CMD}.get(self.buf[:1], GLYPH_SEARCH)
        core.icon(cr, x0 + 12, mid, glyph, 17, "accent")
        tx, room = x0 + 40, fw - 52
        shown = self.buf
        while len(shown) > 1 and core.text_w(cr, shown, 17) > room - 4:
            shown = shown[1:]  # the end of a long line stays in sight
        tw = text(cr, tx, mid, shown, 17, "title", valign=0.5) if shown else 0
        if not shown:
            text(cr, tx + 4, mid, "run, open, find a window…", 15, "dim", valign=0.5)
        cr.rectangle(tx + tw + 1, y + 9, 1.5, fh - 18)  # the caret
        cr.set_source_rgba(*rgba("accent"))
        cr.fill()

    def draw_row(self, cr, hits: Hits, P: float, y: float, i: int, item: Item, dev: float) -> None:
        W, H = self.W, self.ROW_H
        x0, rw, mid = P - 6, W - 2 * P + 12, y + H / 2
        picked = i == self.sel or i == self.hovered
        if picked:
            core.rrect(cr, x0, y + 1, rw, H - 2, 7)
            cr.set_source_rgba(*rgba("bg1"))
            cr.fill()
            if i == self.sel:  # the keyboard's mark: a bar at the left edge
                core.rrect(cr, x0 + 1, y + 8, 3, H - 16, 1.5)
                cr.set_source_rgba(*rgba("accent"))
                cr.fill()
        if item.run is not None:
            hits.add(x0, y, rw, H, lambda: self.click(item))
        else:
            hits.add(x0, y, rw, H, lambda: False)

        # The icon: the app's, a glyph, or a letter tile.
        s = self.ICON
        ix = P + 4
        surf = self.icons.get(item.gicon, math.ceil(s * dev)) if item.gicon is not None else None
        if surf is not None:
            cr.save()
            cr.translate(ix, mid - s / 2)
            k = s / surf.get_width()
            cr.scale(k, k)
            cr.set_source_surface(surf, 0, 0)
            cr.paint()
            cr.restore()
        elif item.glyph and item.kind != "app":
            core.icon(cr, ix + s / 2, mid, item.glyph, 17, KINDS[item.kind][1], align=0.5)
        else:
            tone = TILE_TONES[zlib.crc32(item.name.lower().encode()) % len(TILE_TONES)]
            core.rrect(cr, ix + 1, mid - s / 2 + 1, s - 2, s - 2, 5)
            cr.set_source_rgba(*rgba(tone, 0.85))
            cr.fill()
            text(cr, ix + s / 2, mid, (item.name[:1] or "?").upper(), 12, "bg", bold=True, align=0.5, valign=0.5)

        # The chip on the right, then the name and what it is, in the room left.
        label, tone = KINDS[item.kind]
        cw = core.text_w(cr, label, 10) + 12
        cx = x0 + rw - 8 - cw
        core.rrect(cr, cx + 0.5, mid - 8.5, cw - 1, 17, 8.5)
        cr.set_source_rgba(*rgba(tone, 0.14 if picked else 0.08))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba(tone, 0.6))
        cr.set_line_width(1)
        cr.stroke()
        text(cr, cx + cw / 2, mid, label, 10, tone, align=0.5, valign=0.5)

        tx = ix + s + 12
        room = cx - tx - 10
        name = marked(item.name, item.pos, "warn") if item.pos else None
        from gi.repository import GLib

        nw = text(cr, tx, mid, name if name is not None else GLib.markup_escape_text(item.name, -1), 14,
                  "title" if picked else "fg2", bold=False, markup=True, valign=0.5, width=room * 0.7)
        if item.sub and room - nw > 40:
            text(cr, tx + nw + 10, mid + 1, item.sub, 11, "dim", valign=0.5, width=room - nw - 10)
