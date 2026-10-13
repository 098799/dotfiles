"""The weather for the clock panel, from MeteoSwiss (the MeteoSwiss app's own
forecast service, no key): the local forecast for a Swiss postcode.

Where: ~/.config/bardeck/location, one of "8001 name" (a postcode), "lat lon name"
(the nearest postcode centre), or nothing (Zürich 8001). A place that is not a
postcode is found in MeteoSwiss's open-data list of forecast points, fetched once
and kept in $XDG_RUNTIME_DIR/bardeck/meteoswiss-points.json.
When: only while the clock panel is open, and at most every FETCH_EVERY seconds,
on a thread of its own with a timeout. The answer is kept in
$XDG_RUNTIME_DIR/bardeck/weather.json, so the panel opens with the last one (and
says how old it is when it is stale) and an offline machine still shows it."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import threading
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from . import core

LOCATION = f"{core.REAL_HOME}/.config/bardeck/location"
CACHE = f"{core.RUN_DIR}/weather.json"
POINTS_CACHE = f"{core.RUN_DIR}/meteoswiss-points.json"
DEFAULT = ("8001", "Zürich")
DEFAULT_POINT = (800100, "Zürich")  # MeteoSwiss's point for postcode 8001
FETCH_EVERY = 30 * 60
RETRY_EVERY = 3 * 60  # after a failed fetch (offline)
STALE = 90 * 60       # older than this: the panel says the age
TIMEOUT = 8
URL = "https://app-prod-ws.meteoswiss-app.ch/v1/plzDetail?plz={}"
POINTS_URL = ("https://data.geo.admin.ch/ch.meteoschweiz.ogd-local-forecasting/"
              "ogd-local-forecasting_meta_point.csv")
SWISS = ZoneInfo("Europe/Zurich")

# MeteoSwiss weather symbols: 1-42 by day, the same number + 100 by night. The
# words are short forms of MeteoSwiss's own English texts (weather-symbols.html).
_SUN, _MOON = "\U000f0599", "\U000f0594"
_PART, _PART_N = "\U000f0595", "\U000f0f31"
_CLOUD, _FOG = "\U000f0590", "\U000f0591"
_RAIN, _POUR, _PRAIN = "\U000f0597", "\U000f0596", "\U000f0f33"
_SNOW, _SNOW_H, _SLEET = "\U000f0598", "\U000f0f36", "\U000f067f"
_STORM, _STORM_R = "\U000f0593", "\U000f067e"
KINDS = {  # kind: (day glyph, night glyph, tone)
    "clear": (_SUN, _MOON, "warn"), "mostly": (_PART, _PART_N, "warn"), "part": (_PART, _PART_N, "fg2"),
    "cloud": (_CLOUD, _CLOUD, "fg2"), "fog": (_FOG, _FOG, "fg2"),
    "shower": (_PRAIN, _RAIN, "blue"), "rain": (_RAIN, _RAIN, "blue"), "pour": (_POUR, _POUR, "blue"),
    "sleet": (_SLEET, _SLEET, "blue"), "snow": (_SNOW, _SNOW, "aqua"), "snow_h": (_SNOW_H, _SNOW_H, "aqua"),
    "storm": (_STORM, _STORM, "purple"), "storm_r": (_STORM_R, _STORM_R, "purple"),
}
SYMBOLS = {  # day number: (word, kind)
    1: ("sunny", "clear"), 2: ("mostly sunny", "mostly"), 3: ("partly sunny", "part"),
    4: ("overcast", "cloud"), 5: ("very cloudy", "cloud"),
    6: ("isolated showers", "shower"), 7: ("isolated sleet", "sleet"), 8: ("snow showers", "snow"),
    9: ("some showers", "rain"), 10: ("some sleet", "sleet"), 11: ("some snow showers", "snow"),
    12: ("chance of storms", "storm"), 13: ("possible storms", "storm"),
    14: ("light rain", "rain"), 15: ("light sleet", "sleet"), 16: ("light snow", "snow"),
    17: ("intermittent rain", "rain"), 18: ("intermittent sleet", "sleet"), 19: ("intermittent snow", "snow"),
    20: ("steady rain", "pour"), 21: ("frequent sleet", "sleet"), 22: ("heavy snow", "snow_h"),
    23: ("slight chance of storms", "storm"), 24: ("thunderstorms", "storm"), 25: ("severe storms", "storm_r"),
    26: ("high clouds", "part"), 27: ("low stratus", "fog"), 28: ("fog", "fog"),
    29: ("scattered showers", "shower"), 30: ("scattered snow showers", "snow"), 31: ("scattered sleet", "sleet"),
    32: ("some showers", "shower"), 33: ("frequent rain", "pour"), 34: ("frequent snow", "snow_h"),
    35: ("overcast and dry", "cloud"), 36: ("slightly stormy", "storm"), 37: ("stormy snow showers", "storm"),
    38: ("thundery showers", "storm_r"), 39: ("thundery snow showers", "storm"),
    40: ("slightly stormy", "storm"), 41: ("slightly stormy", "storm"), 42: ("thundery snow showers", "storm"),
}
NIGHT_WORDS = {1: "clear", 2: "mostly clear", 3: "partly cloudy"}


def symbol(code) -> tuple[str, str, str]:
    """(word, glyph, tone) for a MeteoSwiss symbol number."""
    c = int(code or 0)
    night = c > 100
    day = c - 100 if night else c
    word, kind = SYMBOLS.get(day, ("?", "cloud"))
    glyph_d, glyph_n, tone = KINDS[kind]
    return (NIGHT_WORDS.get(day, word) if night else word), (glyph_n if night else glyph_d), tone


def location() -> tuple[str, str]:
    """(place, name): the place is a postcode or "lat lon" (DEFAULT when unset)."""
    parts = core.read(LOCATION).split()
    if parts and parts[0].isdigit():
        return parts[0], " ".join(parts[1:]).strip('"')
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        return DEFAULT
    return f"{lat} {lon}", " ".join(parts[2:]).strip('"')


def _points() -> list[tuple[int, str, str, float, float]]:
    """MeteoSwiss's postcode forecast points: (id, postcode, name, lat, lon)."""
    try:
        with open(POINTS_CACHE) as fh:
            return [tuple(p) for p in json.load(fh)]
    except (OSError, ValueError):
        pass
    req = urllib.request.Request(POINTS_URL, headers={"User-Agent": "bardeck"})
    with urllib.request.urlopen(req, timeout=TIMEOUT * 3) as resp:
        rows = csv.DictReader(io.StringIO(resp.read().decode("cp1252")), delimiter=";")
        points = [(int(r["point_id"]), r["postal_code"], r["point_name"],
                   float(r["point_coordinates_wgs84_lat"]), float(r["point_coordinates_wgs84_lon"]))
                  for r in rows if r["point_type_id"] == "2"]
    os.makedirs(core.RUN_DIR, exist_ok=True)
    with open(f"{POINTS_CACHE}.tmp", "w") as fh:
        json.dump(points, fh)
    os.replace(f"{POINTS_CACHE}.tmp", POINTS_CACHE)
    return points


def resolve(place: str) -> tuple[int, str]:
    """(MeteoSwiss point id, its name) for a postcode or "lat lon"."""
    if place == DEFAULT[0]:
        return DEFAULT_POINT
    points = _points()
    if place.isdigit():
        hits = sorted(p for p in points if p[1] == place)
        if not hits:
            raise ValueError(f"no MeteoSwiss forecast for {place}")
        return hits[0][0], hits[0][2]
    lat, lon = map(float, place.split())
    k = math.cos(math.radians(lat))
    best = min(points, key=lambda p: (p[3] - lat) ** 2 + ((p[4] - lon) * k) ** 2)
    if math.hypot(best[3] - lat, (best[4] - lon) * k) > 0.25:  # ~25 km: not in Switzerland
        raise ValueError("outside Switzerland")
    return best[0], best[2]


class Hour:
    __slots__ = ("at", "temp", "rain", "code")

    def __init__(self, at: datetime, temp: float, rain: int, code: int):
        self.at, self.temp, self.rain, self.code = at, temp, rain, code


class Weather:
    """fetch() is safe to call on every draw: it starts a thread only when the data
    is older than FETCH_EVERY and no fetch runs or failed lately."""

    def __init__(self):
        self.data: dict = {}
        self.at = 0.0        # when `data` was fetched (epoch)
        self.loc = DEFAULT   # (place, name) as location() gives it
        self.point = DEFAULT_POINT
        self.error = ""
        self.busy = False
        self._tried = 0.0
        self.load()

    def load(self) -> None:
        try:
            with open(CACHE) as fh:
                cached = json.load(fh)
            # All or nothing: a cache from the Open-Meteo version has no "point", and
            # taking only its time would make it look fresh with nothing to show.
            data, at = cached["data"], float(cached["at"])
            loc, point = tuple(cached["loc"]), tuple(cached["point"])
            if not (data.get("currentWeather") or {}).get("time"):
                return
            self.data, self.at, self.loc, self.point = data, at, loc, point
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

    def fetch(self, force: bool = False) -> None:
        now = time.time()
        loc = location()
        fresh = now - self.at < FETCH_EVERY and tuple(loc) == tuple(self.loc)
        if self.busy or (fresh and not force) or now - self._tried < (60 if force else RETRY_EVERY):
            return
        self.busy, self._tried = True, now
        threading.Thread(target=self._fetch, args=(loc,), daemon=True).start()

    def _fetch(self, loc: tuple[str, str]) -> None:
        try:
            point = resolve(loc[0])
            req = urllib.request.Request(URL.format(point[0]), headers={"User-Agent": "bardeck"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read())
            if not (data.get("currentWeather") or {}).get("time"):
                raise ValueError("no current weather")
            now = time.time()
            os.makedirs(core.RUN_DIR, exist_ok=True)
            with open(f"{CACHE}.tmp", "w") as fh:
                json.dump({"at": now, "loc": list(loc), "point": list(point), "data": data}, fh)
            os.replace(f"{CACHE}.tmp", CACHE)
            self.data, self.at, self.loc, self.point, self.error = data, now, loc, point, ""
        except Exception as err:  # noqa: BLE001 — offline, DNS, a bad answer: keep the old data
            code = getattr(err, "code", None)  # an HTTPError is an OSError too
            self.error = f"HTTP {code}" if code else ("offline" if isinstance(err, OSError) else str(err)[:40])
            core.log(f"weather: {err!r}")
        finally:
            self.busy = False

    # -- what the panel reads --------------------------------------------------

    @property
    def name(self) -> str:
        return self.loc[1] or self.point[1]

    @property
    def age(self) -> float:
        return time.time() - self.at if self.at else 0.0

    def _series(self, name: str, step: int) -> list[tuple[datetime, object]]:
        """A graph series as (local start time, value); step is its spacing in hours.
        Times are counted in epoch seconds, so a DST change cannot shift them."""
        g = self.data.get("graph") or {}
        start = g.get("start", 0) / 1000
        return [(datetime.fromtimestamp(start + i * step * 3600, SWISS), v)
                for i, v in enumerate(g.get(name) or [])]

    @staticmethod
    def _at(series: list, t: datetime, step: int):
        """The value of the series slot that holds time t (None when outside it)."""
        for at, v in series:
            if 0 <= t.timestamp() - at.timestamp() < step * 3600:
                return v
        return None

    def current(self) -> dict:
        """The measured-and-nowcast weather: temp, code, and this hour's wind and gusts."""
        cur = self.data.get("currentWeather") or {}
        if not cur:
            return {}
        now = datetime.now(SWISS)
        return {"temp": cur.get("temperature"), "code": cur.get("iconV2") or cur.get("icon"),
                "wind": self._at(self._series("windSpeed1h", 1), now, 1),
                "gust": self._at(self._series("gustSpeed1h", 1), now, 1)}

    def today(self) -> dict:
        """Today's min, max and the highest 3-hourly chance of rain."""
        today = datetime.now(SWISS).date()
        days = [d for d in self.data.get("forecast") or [] if d.get("dayDate") == today.isoformat()]
        if not days:
            return {}
        probs = [v or 0 for at, v in self._series("precipitationProbability3h", 3) if at.date() == today]
        return {"min": days[0]["temperatureMin"], "max": days[0]["temperatureMax"],
                "rain": round(max(probs)) if probs else 0}

    def hours(self, n: int = 12) -> list[Hour]:
        """The next n hours, from the current one. The symbol and the chance of rain
        are 3-hourly: each slot holds the 3 hours from its start."""
        codes = self._series("weatherIcon3hV2", 3) or self._series("weatherIcon3h", 3)
        probs = self._series("precipitationProbability3h", 3)
        now = datetime.now(SWISS).replace(minute=0, second=0, microsecond=0)
        out = []
        for at, temp in self._series("temperatureMean1h", 1):
            if at < now or temp is None:
                continue
            code = self._at(codes, at, 3)
            if code is None:
                break
            out.append(Hour(at, temp, round(self._at(probs, at, 3) or 0), code))
            if len(out) == n:
                break
        return out
