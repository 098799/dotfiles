"""User-tunable bits of the Win95 shell.

Win95 shipped for 640x480. On a 2560x1440 panel a period-accurate 28px
taskbar is a hairline, so every fixed pixel size in the shell is expressed
as a multiple of one number — the taskbar height — which the user owns.

Config lives at ~/.config/w95/settings, `key = value` per line, # comments:

    bar_height = 38      # px, the taskbar; everything else scales off it
    font_size  = 15      # px, overrides the size derived from bar_height
    sysmon_mode = drop   # System Monitor: `drop` (quake panel) or `window`
    sysmon_size = 62     # drop mode: percent of the screen it covers
"""

import os

PATH = os.path.expanduser("~/.config/w95/settings")

DEFAULTS = {
    "bar_height": 38,
    "font_size": 0,  # 0 = derive from bar_height
    "sysmon_mode": "drop",
    "sysmon_size": 62,
}


def _read():
    values = dict(DEFAULTS)
    try:
        with open(PATH) as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                key, sep, value = line.partition("=")
                if not sep:
                    continue
                key = key.strip()
                if key not in values:
                    continue
                # The type of the default decides how the value is read, so a
                # word-valued key like sysmon_mode can live in the same file as
                # the pixel counts without a second parser.
                if isinstance(values[key], str):
                    values[key] = value.strip()
                else:
                    try:
                        values[key] = int(value.strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return values


_V = _read()

# 28 was the real thing at 96dpi/480p; below ~24 the bevels stop reading.
BAR_HEIGHT = max(24, min(96, _V["bar_height"]))
FONT_SIZE = _V["font_size"] or max(12, min(20, round(BAR_HEIGHT * 0.40)))

# Row glyphs and the big Start-menu labels track the same scale, so the menu
# doesn't stay tiny next to a tall bar.
ICON_SIZE = max(16, round(FONT_SIZE * 1.15))
BIG_ICON_SIZE = max(24, round(FONT_SIZE * 1.75))
BIG_FONT_PT = max(11, round(FONT_SIZE * 0.95))

# System Monitor. `drop` is the quake-console panel that slides down from the
# top edge; `window` is an ordinary floating window the WM decorates.
SYSMON_MODE = _V["sysmon_mode"] if _V["sysmon_mode"] in ("drop", "window") else "drop"
SYSMON_SIZE = max(30, min(100, _V["sysmon_size"])) / 100.0


def write(key, value):
    """Persist one setting, leaving the rest of the file — and its comments —
    alone. Rewrites the key in place if it is already there, appends if not.

    This exists so the System Monitor's Options menu can change how it is
    displayed and have the choice survive a restart, without the app needing to
    own (and therefore reformat) a file the user hand-edits.
    """
    line = "%s = %s\n" % (key, value)
    try:
        with open(PATH) as fh:
            lines = fh.readlines()
    except OSError:
        lines = []
    for i, existing in enumerate(lines):
        if existing.split("#", 1)[0].partition("=")[0].strip() == key:
            lines[i] = line
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(line)
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w") as fh:
            fh.writelines(lines)
    except OSError:
        return False
    return True


def scale_css():
    """CSS that layers over w95.css to apply the chosen font size."""
    return ("* { font-size: %dpx; }\n"
            "button.w95-item { padding: %dpx 18px %dpx 4px; }\n"
            % (FONT_SIZE, max(3, FONT_SIZE // 4), max(3, FONT_SIZE // 4))).encode()
