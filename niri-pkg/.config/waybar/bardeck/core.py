"""Shared ground for every strip and panel: palette, text, shapes, files, signals.

A *strip* is one pill on the bar. bardeck draws it to
$XDG_RUNTIME_DIR/bardeck/<name>-<variant>.png and bar-strip.so (a waybar CFFI
module) shows it. A *panel* is what opens under a strip on hover: drawn by the
Deck (deck.py) on a layer-shell overlay.
"""

from __future__ import annotations

import hashlib
import math
import os
import pwd
import signal
import subprocess
import sys

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir  # agent shells run with a fake $HOME
RUN_DIR = f"{os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'}/bardeck"
SCRIPTS = f"{REAL_HOME}/scripts"  # the i3blocks scripts (i3-pkg), whose menus the panels reuse
# bar-strip.so reloads a strip's PNG on this signal when the file changed.
SIGNAL = 16
# The bar's height (config.jsonc "height"); every strip is drawn this tall.
BAR_H = 26
FONT = "Ubuntu Mono"
ICON_FONT = "UbuntuMono Nerd Font Propo"
TRACE = bool(os.environ.get("BARDECK_TRACE"))

# The palette follows the desktop theme (~/bin/theme writes ~/.config/theme/state,
# "dark gruvbox" / "light selenized" / …): the roles of the bar come from the same
# ~/.config/i3/colors.d/<palette>-<mode>.conf i3 and the old bar used, and the
# status colours (green / yellow / red …) from STATUS, tuned per theme for contrast:
# the light themes need the darker shades. load_theme() fills PALETTE in place.
THEME_STATE = f"{REAL_HOME}/.config/theme/state"
COLORS_D = f"{REAL_HOME}/.config/i3/colors.d"
_SOLARIZED = {"ok": "#859900", "warn": "#b58900", "hit": "#dc322f", "orange": "#cb4b16",
              "blue": "#268bd2", "aqua": "#2aa198", "purple": "#d33682"}
STATUS = {
    ("gruvbox", "dark"): {"ok": "#b8bb26", "warn": "#fabd2f", "hit": "#fb4934", "orange": "#fe8019",
                          "blue": "#83a598", "aqua": "#8ec07c", "purple": "#d3869b"},
    ("gruvbox", "light"): {"ok": "#79740e", "warn": "#b57614", "hit": "#9d0006", "orange": "#af3a03",
                           "blue": "#076678", "aqua": "#427b58", "purple": "#8f3f71"},
    ("selenized", "dark"): _SOLARIZED,
    ("selenized", "light"): _SOLARIZED,
}
PALETTE: dict[str, str] = {}
THEME = ("dark", "gruvbox")
PILL_ALPHA = 0.94
SHADOW = {"dark": 0.35, "light": 0.14}
PILL_R = 7


def _hex(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def mix(a: str, b: str, t: float) -> str:
    """t of the way from colour a to colour b, as #rrggbb."""
    ca, cb = _hex(a), _hex(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def theme_key() -> tuple[str, str]:
    """(mode, palette) of the desktop theme; BARDECK_THEME="light gruvbox" overrides."""
    raw = os.environ.get("BARDECK_THEME") or read(THEME_STATE, "dark gruvbox")
    parts = raw.split()
    mode = parts[0] if parts and parts[0] in ("dark", "light") else "dark"
    palette = parts[1] if len(parts) > 1 else "gruvbox"
    return mode, palette


def load_theme() -> tuple[str, str]:
    """Fill PALETTE for the current theme. Returns (mode, palette)."""
    global THEME
    mode, palette = theme_key()
    roles = {}
    for line in read(f"{COLORS_D}/{palette}-{mode}.conf").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "set" and parts[1].startswith("$") and parts[2].startswith("#"):
            roles[parts[1][1:]] = parts[2][:7].lower()
    if "bg_main" not in roles:  # an unknown theme (win95): the bar stays gruvbox-dark
        mode, palette = "dark", "gruvbox"
        roles = {"bg_main": "#282828", "bg_alt": "#3c3836", "title_fg": "#ebdbb2", "fg_main": "#a89984",
                 "fg_dim": "#7c6f64", "accent": "#98971a", "accent_fg": "#fbf1c7", "sep": "#504945",
                 "info": "#458588", "urgent": "#b16286"}
    status = STATUS.get((palette, mode)) or STATUS[("gruvbox", mode if mode in ("dark", "light") else "dark")]
    bg, bg1, sep = roles["bg_main"], roles["bg_alt"], roles.get("sep", roles["bg_alt"])
    PALETTE.clear()
    PALETTE.update({
        "bg": bg, "bg1": bg1, "bg2": sep, "bg3": mix(sep, roles["fg_dim"], 0.5),
        "fg": roles["fg_main"], "fg2": mix(roles["fg_main"], roles["title_fg"], 0.5),
        "title": roles["title_fg"],
        # The brightest text: the clock. On a light bar that is the darkest one.
        "bright": roles.get("accent_fg", roles["title_fg"]) if mode == "dark" else roles["title_fg"],
        "dim": roles["fg_dim"], "accent": roles["accent"], "info": roles.get("info", status["blue"]),
        "urgent": roles.get("urgent", status["purple"]), "sep": sep, "alt": bg1,
        # The pill's rim: the second background on dark, the separator on light, where
        # the second background is too close to the wallpaper's cream.
        "rim": bg1 if mode == "dark" else sep,
        **status,
        "pace": status["blue"], "max": status["purple"], "team": status["blue"],
    })
    THEME = (mode, palette)
    return THEME


def theme_css() -> str:
    """The colours style.css takes for the native pills (audio, tray)."""
    p = PALETTE
    return (f"/* written by bardeck for the theme {' '.join(THEME)}; see style.css */\n"
            f"@define-color pill_bg {p['bg']};\n@define-color pill_rim {p['rim']};\n"
            f"@define-color pill_shadow rgba(0, 0, 0, {SHADOW[THEME[0]]});\n"
            f"@define-color fg_main {p['fg']};\n@define-color title_fg {p['title']};\n"
            f"@define-color red {p['hit']};\n@define-color green {p['ok']};\n")


def rgba(name, alpha: float = 1.0) -> tuple[float, float, float, float]:
    if isinstance(name, tuple):
        return name if len(name) == 4 else (*name, alpha)
    h = PALETTE.get(name, name)
    return int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255, alpha


def level(v: float, warn: float, hit: float) -> str:
    return "hit" if v >= hit else ("warn" if v >= warn else "ok")


def log(*args) -> None:
    print("bardeck:", *args, file=sys.stderr, flush=True)


# ── text ─────────────────────────────────────────────────────────────────────

_FONTS: dict[tuple, Pango.FontDescription] = {}


def _desc(size: float, bold: bool, family: str) -> Pango.FontDescription:
    key = (size, bold, family)
    if key not in _FONTS:
        d = Pango.FontDescription.from_string(f"{family} {'Bold' if bold else ''}")
        d.set_absolute_size(size * Pango.SCALE)
        _FONTS[key] = d
    return _FONTS[key]


def layout(cr, s: str, size: float, bold: bool = False, family: str = FONT, markup: bool = False,
           width: float | None = None):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(_desc(size, bold, family))
    if markup:
        lay.set_markup(s, -1)
    else:
        lay.set_text(s, -1)
    if width is not None:
        lay.set_width(int(width * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay


def text(cr, x: float, y: float, s: str, size: float, colour, *, bold: bool = False,
         align: float = 0.0, family: str = FONT, markup: bool = False,
         width: float | None = None, valign: float | None = None) -> float:
    """Draw s with its top-left at (x, y); align 0.5 centres, 1 right-aligns.
    valign: y is then the line's middle (0.5). Returns the drawn width."""
    lay = layout(cr, s, size, bold, family, markup, width)
    w, h = lay.get_pixel_size()
    if valign is not None:
        y -= h * valign
    cr.move_to(x - w * align, y)
    cr.set_source_rgba(*rgba(colour))
    PangoCairo.show_layout(cr, lay)
    return w


def icon(cr, x: float, y: float, glyph: str, size: float, colour, *, align: float = 0.0,
         valign: float | None = 0.5) -> float:
    """A Nerd Font glyph, centred on y by default."""
    return text(cr, x, y, glyph, size, colour, family=ICON_FONT, align=align, valign=valign)


def text_w(cr, s: str, size: float, bold: bool = False, family: str = FONT) -> float:
    return layout(cr, s, size, bold, family).get_pixel_size()[0]


# ── shapes ───────────────────────────────────────────────────────────────────


def rrect(cr, x, y, w, h, r) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def pill(cr, w: float, h: float = BAR_H) -> None:
    """The strip's own background: the same pill style.css gives the native modules.

    A rim, and outside it a faint dark ring, so the pill keeps its shape on any
    wallpaper: on the light themes the pill is the colour of the cream wallpapers."""
    rrect(cr, 0.5, 0.5, w - 1, h - 1, PILL_R + 0.5)
    cr.set_source_rgba(*rgba("#000000", SHADOW[THEME[0]]))
    cr.set_line_width(1)
    cr.stroke()
    rrect(cr, 1.5, 1.5, w - 3, h - 3, PILL_R - 0.5)
    cr.set_source_rgba(*rgba("bg", PILL_ALPHA))
    cr.fill_preserve()
    cr.set_source_rgba(*rgba("rim"))
    cr.stroke()


def spark(cr, x, y, w, h, values, colour, *, top: float = 100.0, fill: float = 0.35,
          line: float = 1.2) -> None:
    """A filled sparkline of values (oldest first) in the box; None = no reading."""
    vals = [v for v in values]
    if not vals:
        return
    n = len(vals)
    step = w / max(1, n - 1)
    pts = [(x + i * step, y + h - max(0.0, min(top, v)) / top * h)
           for i, v in enumerate(vals) if v is not None]
    if len(pts) < 2:
        return
    cr.move_to(pts[0][0], y + h)
    for p in pts:
        cr.line_to(*p)
    cr.line_to(pts[-1][0], y + h)
    cr.close_path()
    cr.set_source_rgba(*rgba(colour, fill))
    cr.fill()
    cr.move_to(*pts[0])
    for p in pts[1:]:
        cr.line_to(*p)
    cr.set_source_rgba(*rgba(colour))
    cr.set_line_width(line)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.stroke()


def bar(cr, x, y, w, h, frac: float, colour, track="bg1", r: float | None = None) -> None:
    r = h / 2 if r is None else r
    rrect(cr, x, y, w, h, r)
    cr.set_source_rgba(*rgba(track))
    cr.fill()
    if frac > 0:
        rrect(cr, x, y, max(h, w * min(1.0, frac)), h, r)
        cr.set_source_rgba(*rgba(colour))
        cr.fill()


def human_bytes(n: float, per_s: bool = False) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if abs(n) < 1000 or unit == "T":
            s = f"{n:.0f}{unit}" if unit == "B" or n >= 100 else f"{n:.1f}{unit}"
            return s + ("/s" if per_s else "")
        n /= 1024
    return ""


def dur(sec: float) -> str:
    sec = max(0, int(sec))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d{h:02d}h"
    if h:
        return f"{h}h{m:02d}"
    return f"{m}m"


# ── surfaces and files ───────────────────────────────────────────────────────


def surface(w: float, h: float, scale: int):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(math.ceil(w * scale)), int(math.ceil(h * scale)))
    cr = cairo.Context(s)
    cr.scale(scale, scale)
    return s, cr


_WRITTEN: dict[str, bytes] = {}


def write_png(path: str, surf) -> bool:
    """Write atomically, and only when the picture changed (bar-strip.so reloads on mtime)."""
    surf.flush()
    digest = hashlib.blake2b(bytes(surf.get_data()), digest_size=16).digest()
    if _WRITTEN.get(path) == digest and os.path.exists(path):
        return False
    tmp = f"{path}.tmp"
    surf.write_to_png(tmp)
    os.replace(tmp, path)
    _WRITTEN[path] = digest
    return True


_WAYBARS: tuple[float, list[int]] = (0.0, [])


def waybar_pids() -> list[int]:
    """This user's waybar processes. A scan reads every /proc/<pid>/comm (thousands on
    this machine: it was most of the daemon's CPU when it ran every second), so the
    answer is kept a minute; signal_waybar rescans when a pid is gone."""
    global _WAYBARS
    import time

    if time.monotonic() - _WAYBARS[0] < 60 and _WAYBARS[1]:
        return _WAYBARS[1]
    pids = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as fh:
                if fh.read().strip() != "waybar":
                    continue
            if os.stat(f"/proc/{pid}").st_uid == os.getuid():
                pids.append(int(pid))
        except OSError:
            continue
    _WAYBARS = (time.monotonic(), pids)
    return pids


def signal_waybar(sig: int | None = None) -> None:
    """Default: the strips' reload signal (SIGRTMIN+SIGNAL)."""
    global _WAYBARS
    sig = signal.SIGRTMIN + SIGNAL if sig is None else sig
    for pid in waybar_pids():
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            _WAYBARS = (0.0, [])


def read(path: str, default: str = "") -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return default


# ── running things ───────────────────────────────────────────────────────────


def spawn(argv: list[str]) -> None:
    """Fire and forget, detached from the daemon."""
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def terminal(cmd: str, hold: bool = True) -> None:
    """A shell command in a new alacritty; hold = wait for Enter at the end."""
    if hold:
        cmd = f"{cmd}; read -rp 'Press enter to close...'"
    spawn(["alacritty", "-e", "bash", "-c", cmd])


_SHIM_DIR = f"{RUN_DIR}/shim"


def menu_action(script: str, button: int, choice: str | None = None) -> None:
    """Run an i3blocks script's click, as if its rofi menu returned `choice`.

    The scripts own their actions (vpn.sh's wg-quick lines, network.sh's speedtest);
    the panels' buttons reuse them instead of copying them. A `rofi` shim on PATH
    answers the menu with $BARDECK_CHOICE, and a stub xdotool keeps the scripts'
    `eval $(xdotool getmouselocation --shell)` quiet."""
    os.makedirs(_SHIM_DIR, exist_ok=True)
    for name, body in (("rofi", 'cat >/dev/null; printf "%s\\n" "$BARDECK_CHOICE"\n'),
                       ("xdotool", "echo X=0; echo Y=0\n")):
        path = f"{_SHIM_DIR}/{name}"
        if not os.path.exists(path):
            with open(path, "w") as fh:
                fh.write("#!/bin/sh\n" + body)
            os.chmod(path, 0o755)
    env = dict(os.environ, HOME=REAL_HOME, BLOCK_BUTTON=str(button), BARDECK_CHOICE=choice or "",
               PATH=f"{_SHIM_DIR}:{os.environ.get('PATH', '/usr/bin:/bin')}")
    subprocess.Popen([f"{SCRIPTS}/{script}"], env=env, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── panel widgets ────────────────────────────────────────────────────────────


class Hits:
    """Click targets a panel draw collects: (x, y, w, h, action)."""

    def __init__(self):
        self.items: list[tuple[float, float, float, float, object]] = []

    def add(self, x, y, w, h, action) -> None:
        self.items.append((x, y, w, h, action))

    def at(self, px: float, py: float):
        for x, y, w, h, action in reversed(self.items):
            if x <= px < x + w and y <= py < y + h:
                return action
        return None


def button(cr, hits: Hits, x: float, y: float, label: str, action, *, on: bool = False,
           tone: str = "accent", w: float | None = None, h: float = 22, size: float = 12,
           glyph: str | None = None) -> float:
    """A rounded chip; `on` fills it. Returns its width."""
    tw = text_w(cr, label, size)
    gw = text_w(cr, glyph, size + 2, family=ICON_FONT) + 5 if glyph else 0
    w = w or tw + gw + 18
    rrect(cr, x + 0.5, y + 0.5, w - 1, h - 1, h / 2)
    if on:
        cr.set_source_rgba(*rgba(tone))
        cr.fill()
    else:
        cr.set_source_rgba(*rgba("bg1"))
        cr.fill_preserve()
        cr.set_source_rgba(*rgba("bg2"))
        cr.set_line_width(1)
        cr.stroke()
    fg = "bg" if on else "title"
    cx = x + (w - tw - gw) / 2
    if glyph:
        icon(cr, cx, y + h / 2, glyph, size + 2, fg)
    text(cr, cx + gw, y + h / 2, label, size, fg, bold=on, valign=0.5)
    hits.add(x, y, w, h, action)
    return w


def heading(cr, x: float, y: float, s: str, w: float | None = None) -> None:
    text(cr, x, y, s.upper(), 11, "dim", bold=True)
    if w:
        tw = text_w(cr, s.upper(), 11, bold=True)
        cr.rectangle(x + tw + 8, y + 7, w - tw - 8, 1)
        cr.set_source_rgba(*rgba("bg2"))
        cr.fill()


def panel_frame(cr, w: float, h: float) -> None:
    rrect(cr, 0.5, 0.5, w - 1, h - 1, 10)
    cr.set_source_rgba(*rgba("bg", 0.97))
    cr.fill_preserve()
    cr.set_source_rgba(*rgba("bg2"))
    cr.set_line_width(1)
    cr.stroke()


def graph(cr, x, y, w, h, series: list[tuple[list, str]], *, top: float = 100.0,
          grid: tuple = (25, 50, 75), label_fmt=None) -> None:
    """A panel graph: rounded well, grid lines, several sparklines over each other."""
    rrect(cr, x, y, w, h, 4)
    cr.set_source_rgba(*rgba("bg1", 0.6))
    cr.fill()
    cr.set_line_width(1)
    cr.set_source_rgba(*rgba("bg2"))
    for g in grid:
        gy = round(y + h - g / top * h) + 0.5
        cr.move_to(x + 2, gy)
        cr.line_to(x + w - 2, gy)
    cr.set_dash([1, 3])
    cr.stroke()
    cr.set_dash([])
    cr.save()
    rrect(cr, x, y, w, h, 4)
    cr.clip()
    for values, colour in series:
        spark(cr, x, y + 2, w, h - 2, values, colour, top=top, fill=0.22, line=1.3)
    cr.restore()


class StripCanvas:
    """Lay a strip out left to right, then cut it to size inside its pill.

        c = StripCanvas(scale)
        c.icon("", "fg"); c.text("23%", "ok"); c.gap()
        surf = c.finish()
    """

    PAD = 9
    GAP = 10

    def __init__(self, scale: int, max_w: int = 1400):
        self.scale = scale
        self.surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max_w * scale, BAR_H * scale)
        self.surf.set_device_scale(scale, scale)
        self.cr = cairo.Context(self.surf)
        self.x = float(self.PAD)
        self.mid = BAR_H / 2

    def gap(self, g: float | None = None) -> None:
        self.x += self.GAP if g is None else g

    def text(self, s: str, colour, size: float = 13, bold: bool = False) -> float:
        w = text(self.cr, self.x, self.mid, s, size, colour, bold=bold, valign=0.5)
        self.x += w
        return w

    def icon(self, glyph: str, colour, size: float = 15, after: float = 4) -> float:
        w = icon(self.cr, self.x, self.mid, glyph, size, colour)
        self.x += w + after
        return w

    def finish(self):
        w = int(math.ceil(self.x + self.PAD))
        final = cairo.ImageSurface(cairo.FORMAT_ARGB32, w * self.scale, BAR_H * self.scale)
        final.set_device_scale(self.scale, self.scale)
        cr = cairo.Context(final)
        pill(cr, w)
        cr.set_source_surface(self.surf, 0, 0)
        cr.rectangle(0, 0, w, BAR_H)
        cr.fill()
        return final


load_theme()
