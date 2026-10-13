"""The weather for the clock panel, from Open-Meteo (no key).

Where: ~/.config/bardeck/location, "lat lon name" (Zürich when there is none).
When: only while the clock panel is open, and at most every FETCH_EVERY seconds,
on a thread of its own with a timeout. The answer is kept in
$XDG_RUNTIME_DIR/bardeck/weather.json, so the panel opens with the last one (and
says how old it is when it is stale) and an offline machine still shows it."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import core

LOCATION = f"{core.REAL_HOME}/.config/bardeck/location"
CACHE = f"{core.RUN_DIR}/weather.json"
DEFAULT = (47.3769, 8.5417, "Zürich")
FETCH_EVERY = 30 * 60
RETRY_EVERY = 3 * 60  # after a failed fetch (offline)
STALE = 90 * 60       # older than this: the panel says the age
TIMEOUT = 8
URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes: (word, day glyph, night glyph).
_SUN, _MOON = "\U000f0599", "\U000f0594"
_PART, _PART_N = "\U000f0595", "\U000f0f31"
_CLOUD, _FOG = "\U000f0590", "\U000f0591"
_RAIN, _POUR, _PRAIN = "\U000f0597", "\U000f0596", "\U000f0f33"
_SNOW, _SNOW_H, _SLEET = "\U000f0598", "\U000f0f36", "\U000f067f"
_STORM, _STORM_R, _HAIL = "\U000f0593", "\U000f067e", "\U000f0592"
WMO = {
    0: ("clear", _SUN, _MOON), 1: ("mostly clear", _SUN, _MOON), 2: ("partly cloudy", _PART, _PART_N),
    3: ("overcast", _CLOUD, _CLOUD), 45: ("fog", _FOG, _FOG), 48: ("rime fog", _FOG, _FOG),
    51: ("light drizzle", _PRAIN, _RAIN), 53: ("drizzle", _RAIN, _RAIN), 55: ("dense drizzle", _RAIN, _RAIN),
    56: ("freezing drizzle", _SLEET, _SLEET), 57: ("freezing drizzle", _SLEET, _SLEET),
    61: ("light rain", _PRAIN, _RAIN), 63: ("rain", _RAIN, _RAIN), 65: ("heavy rain", _POUR, _POUR),
    66: ("freezing rain", _SLEET, _SLEET), 67: ("freezing rain", _SLEET, _SLEET),
    71: ("light snow", _SNOW, _SNOW), 73: ("snow", _SNOW, _SNOW), 75: ("heavy snow", _SNOW_H, _SNOW_H),
    77: ("snow grains", _SNOW, _SNOW), 80: ("showers", _PRAIN, _RAIN), 81: ("showers", _RAIN, _RAIN),
    82: ("violent showers", _POUR, _POUR), 85: ("snow showers", _SNOW, _SNOW), 86: ("snow showers", _SNOW_H, _SNOW_H),
    95: ("thunderstorm", _STORM, _STORM), 96: ("thunderstorm, hail", _HAIL, _HAIL),
    99: ("thunderstorm, hail", _HAIL, _HAIL),
}


def wmo(code, day: bool = True) -> tuple[str, str]:
    """(word, glyph) for a WMO code."""
    word, d, n = WMO.get(int(code or 0), ("?", _CLOUD, _CLOUD))
    return word, d if day else n


def tone(code) -> str:
    """The glyph's colour: sun yellow, rain blue, snow aqua, storms purple."""
    c = int(code or 0)
    if c <= 1:
        return "warn"
    if c >= 95:
        return "purple"
    if c in (71, 73, 75, 77, 85, 86):
        return "aqua"
    if c >= 51:
        return "blue"
    return "fg2"


def location() -> tuple[float, float, str]:
    parts = core.read(LOCATION).split(None, 2)
    try:
        return float(parts[0]), float(parts[1]), (parts[2].strip().strip('"') if len(parts) > 2 else "")
    except (IndexError, ValueError):
        return DEFAULT


class Hour:
    __slots__ = ("at", "temp", "rain", "code", "day")

    def __init__(self, at: datetime, temp: float, rain: int, code: int, day: bool):
        self.at, self.temp, self.rain, self.code, self.day = at, temp, rain, code, day


class Weather:
    """fetch() is safe to call on every draw: it starts a thread only when the data
    is older than FETCH_EVERY and no fetch runs or failed lately."""

    def __init__(self):
        self.data: dict = {}
        self.at = 0.0        # when `data` was fetched (epoch)
        self.loc = DEFAULT
        self.error = ""
        self.busy = False
        self._tried = 0.0
        self.load()

    def load(self) -> None:
        try:
            with open(CACHE) as fh:
                cached = json.load(fh)
            self.data, self.at = cached["data"], float(cached["at"])
            self.loc = tuple(cached.get("loc") or DEFAULT)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def fetch(self, force: bool = False) -> None:
        now = time.time()
        loc = location()
        fresh = now - self.at < FETCH_EVERY and tuple(loc) == tuple(self.loc)
        if self.busy or (fresh and not force) or now - self._tried < (60 if force else RETRY_EVERY):
            return
        self.busy, self._tried = True, now
        threading.Thread(target=self._fetch, args=(loc,), daemon=True).start()

    def _fetch(self, loc: tuple[float, float, str]) -> None:
        q = urllib.parse.urlencode({
            "latitude": loc[0], "longitude": loc[1], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        })
        try:
            req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "bardeck"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
            if "current" not in data:
                raise ValueError(data.get("reason") or "no current weather")
            now = time.time()
            os.makedirs(core.RUN_DIR, exist_ok=True)
            with open(f"{CACHE}.tmp", "w") as fh:
                json.dump({"at": now, "loc": list(loc), "data": data}, fh)
            os.replace(f"{CACHE}.tmp", CACHE)
            self.data, self.at, self.loc, self.error = data, now, loc, ""
        except Exception as err:  # noqa: BLE001 — offline, DNS, a bad answer: keep the old data
            code = getattr(err, "code", None)  # an HTTPError is an OSError too
            self.error = f"HTTP {code}" if code else ("offline" if isinstance(err, OSError) else str(err)[:40])
            core.log(f"weather: {err!r}")
        finally:
            self.busy = False

    # -- what the panel reads --------------------------------------------------

    @property
    def name(self) -> str:
        return self.loc[2] if len(self.loc) > 2 and self.loc[2] else f"{self.loc[0]:.2f}, {self.loc[1]:.2f}"

    @property
    def age(self) -> float:
        return time.time() - self.at if self.at else 0.0

    def now(self) -> datetime:
        """The time where the forecast is (its times are local there, naive)."""
        off = self.data.get("utc_offset_seconds") or 0
        return (datetime.now(timezone.utc) + timedelta(seconds=off)).replace(tzinfo=None)

    def current(self) -> dict:
        return self.data.get("current") or {}

    def today(self) -> dict:
        """Today's min, max, rain chance, sunrise and sunset (the forecast's own day)."""
        d = self.data.get("daily") or {}
        days = d.get("time") or []
        key = self.now().strftime("%Y-%m-%d")
        i = days.index(key) if key in days else 0
        try:
            return {"min": d["temperature_2m_min"][i], "max": d["temperature_2m_max"][i],
                    "rain": d["precipitation_probability_max"][i],
                    "sunrise": d["sunrise"][i][-5:], "sunset": d["sunset"][i][-5:]}
        except (KeyError, IndexError, TypeError):
            return {}

    def hours(self, n: int = 12) -> list[Hour]:
        """The next n hours, from the current one (the forecast's local time)."""
        h = self.data.get("hourly") or {}
        times = h.get("time") or []
        now = self.now().replace(minute=0, second=0, microsecond=0)
        out = []
        for i, t in enumerate(times):
            try:
                at = datetime.fromisoformat(t)
            except ValueError:
                continue
            if at < now:
                continue
            try:
                out.append(Hour(at, h["temperature_2m"][i], h["precipitation_probability"][i] or 0,
                                h["weather_code"][i], bool(h["is_day"][i])))
            except (KeyError, IndexError, TypeError):
                continue
            if len(out) == n:
                break
        return out
