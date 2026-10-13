"""The daily tip: one feature of the bar a day, as a notification, so the many
things built on 13 Oct 2026 are not forgotten.

The tips are the `- **Title** — how` lines of ~/.config/niri/BAR-FEATURES.md (the
short list Tomek reads), so the two never drift apart. Once a day, at the first
check after HOUR, the next line goes to the notification daemon over D-Bus
(org.freedesktop.Notifications, in-process: no notify-send); after the last one
the tips stop. Do Not Disturb holds the popup like any other.

State: ~/.local/state/bardeck/tips.json {"next": N, "date": "YYYY-MM-DD"}.
Delete it to start again; {"off": true} stops the tips.
"""

from __future__ import annotations

import html
import json
import os
import re
from datetime import date, datetime

from . import core

FEATURES = f"{core.REAL_HOME}/.config/niri/BAR-FEATURES.md"
STATE = f"{core.REAL_HOME}/.local/state/bardeck/tips.json"
HOUR = 9               # no tip before 09:00
CHECK_EVERY_S = 600    # the daemon asks this often; a tip goes out once a day
TIP = re.compile(r"^- \*\*(.+?)\*\*\s*(?:—\s*)?(.*)$")


def tips(path: str = FEATURES) -> list[tuple[str, str]]:
    """(title, how) for every `- **Title** — how` line, in the file's order."""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = TIP.match(line.strip())
                if m:
                    out.append((m.group(1).rstrip(" .:"), m.group(2).strip()))
    except OSError:
        pass
    return out


def load(path: str = STATE) -> dict:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(state: dict, path: str = STATE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(f"{path}.tmp", "w") as fh:
        json.dump(state, fh)
    os.replace(f"{path}.tmp", path)


def markup(s: str) -> str:
    """dunst takes markup: escape, then `code` in monospace."""
    return re.sub(r"`([^`]+)`", r"<tt>\1</tt>", html.escape(s, quote=False))


def notify(summary: str, body: str, timeout_ms: int = 20000) -> bool:
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                      "org.freedesktop.Notifications", "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("bar tips", 0, "dialog-information", summary, body,
                                                      [], {}, timeout_ms)),
                      None, Gio.DBusCallFlags.NONE, 2000, None)
        return True
    except Exception as err:
        core.log(f"tips: {err!r}")
        return False


def check(now: datetime | None = None, state_path: str = STATE, features: str = FEATURES) -> bool:
    """Send today's tip when one is due. True when one went out."""
    now = now or datetime.now()
    state = load(state_path)
    if state.get("off") or now.hour < HOUR or state.get("date") == now.date().isoformat():
        return False
    all_tips = tips(features)
    n = int(state.get("next", 0))
    if n >= len(all_tips):
        return False
    title, how = all_tips[n]
    body = markup(how)
    if n == len(all_tips) - 1:
        body += "\n\n<i>That was the last tip. All of them: Mod+D → bar features.</i>"
    if not notify(f"Bar tip {n + 1}/{len(all_tips)}: {title}", body):
        return False  # try again at the next check
    save({"next": n + 1, "date": now.date().isoformat()}, state_path)
    return True


def start_tomorrow(state_path: str = STATE) -> None:
    """The first install: no tip today (the features are fresh), the first one tomorrow."""
    if not os.path.exists(state_path):
        save({"next": 0, "date": date.today().isoformat()}, state_path)
