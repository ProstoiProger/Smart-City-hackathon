"""Weather and air quality as walking-comfort rules.

Live conditions describe the present only: they change the ranking just for a walk that starts
about now. Every factor is a code plus numbers; the interface words it in the user's language.
"""

from datetime import datetime, timezone
import threading
import time
import httpx
from .hours import parse_when

AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AIR_SOURCE = "Open-Meteo, CAMS"
NOW_WINDOW_S = 3 * 3600
SEVERITY = {"advisory": 0, "harsh": 1, "severe": 2}
# Ranking shifts per level: outdoor places lose score, covered ones gain, walking time weighs more.
OUTDOOR_PENALTY = (0.0, 0.3, 0.7)
INDOOR_BONUS = (0.0, 0.1, 0.2)
TRAVEL_WEIGHT = (1.0, 2.0, 3.0)

OUTDOOR = {
    "nature": {"park", "garden", "common"},
    "sightseeing": {"monument", "memorial", "attraction", "artwork", "locations", "viewpoint"},
    "sport": {"stadium", "sports_pitch", "track", "fitness_station"},
    "entertainment": {"amusement_ride"},
}
MIXED = {"place_of_worship", "mosque", "spirituality"}

_air = None
_air_expires = 0
_lock = threading.Lock()


def exposure(p):
    """'outdoor', 'indoor' or 'mixed' (partly covered) for a place."""
    declared = p.get("indoor_outdoor")
    if declared in ("indoor", "outdoor"):
        return declared
    if declared == "both":
        return "mixed"
    sub = p.get("subcategory")
    if sub in MIXED:
        return "mixed"
    if sub in OUTDOOR.get(p.get("category"), ()):
        return "outdoor"
    return "indoor"


def current_air():
    """Current modelled air quality for the city centre; failures are reported, never guessed."""
    global _air, _air_expires
    with _lock:
        if _air is not None and time.monotonic() < _air_expires:
            return _air
        now = datetime.now(timezone.utc)
        base = {"source": AIR_SOURCE, "source_url": "https://open-meteo.com/en/docs/air-quality-api"}
        try:
            response = httpx.get(
                AIR_URL,
                params={
                    "latitude": 51.13,
                    "longitude": 71.43,
                    "current": "pm2_5,european_aqi",
                    "timezone": "UTC",
                },
                timeout=5,
            )
            response.raise_for_status()
            values = response.json()["current"]
            observed = datetime.fromisoformat(values["time"]).replace(tzinfo=timezone.utc)
            stale = abs((now - observed).total_seconds()) > 7200
            aqi = values.get("european_aqi")
            _air = {
                **base,
                "available": not stale and aqi is not None,
                "stale": stale,
                "pm2_5": values.get("pm2_5"),
                "aqi": aqi,
                "valid_at": observed.isoformat(),
                "fetched_at": now.isoformat(),
            }
            _air_expires = time.monotonic() + 900
        except Exception:
            _air = {**base, "available": False, "stale": False, "fetched_at": now.isoformat()}
            _air_expires = time.monotonic() + 60
        return _air


def _factor(code, level, **params):
    return {"code": code, "level": level, "params": params}


def assess(weather, air, when=None, now=None):
    """What the present conditions mean for a walk starting at `when`.

    Returns {"applies", "level", "factors", ...}. Factors are listed even when they do not
    change the ranking (level "advisory"), so the answer can still mention them.
    """
    now = now or parse_when()
    try:
        start = parse_when(when) if when else now
    except (ValueError, TypeError):
        start = now
    if abs((start - now).total_seconds()) > NOW_WINDOW_S:
        return {"applies": False, "level": "none", "factors": [], "reason": "not_now"}
    factors = []
    if weather and weather.get("available"):
        feels = weather.get("feels_like_c")
        if feels is None:
            feels = weather.get("temperature_c")
        if feels is not None:
            if feels <= -15:
                factors.append(_factor("frost", "severe", temp=round(feels)))
            elif feels <= -5:
                factors.append(_factor("cold", "harsh", temp=round(feels)))
            elif feels >= 36:
                factors.append(_factor("heat", "severe", temp=round(feels)))
            elif feels >= 32:
                factors.append(_factor("heat", "harsh", temp=round(feels)))
        code = weather.get("weather_code")
        rain = weather.get("precipitation_mm") or 0
        stormy = code in (95, 96, 99) or (code in (65, 67, 75, 82, 86) and rain >= 2)
        wet = rain >= 0.2 or code in range(51, 68) or code in range(71, 78) or code in range(80, 87) or code in (95, 96, 99)
        if wet:
            factors.append(_factor("storm" if stormy else "wet", "severe" if stormy else "harsh"))
        wind = weather.get("wind_kmh") or 0
        if wind >= 60:
            factors.append(_factor("wind", "severe", wind=round(wind)))
        elif wind >= 40:
            factors.append(_factor("wind", "harsh", wind=round(wind)))
    if air and air.get("available"):
        aqi = air.get("aqi")
        pm = air.get("pm2_5")
        if aqi is not None and aqi >= 100:
            factors.append(_factor("smog", "severe", aqi=round(aqi), pm=round(pm) if pm is not None else None))
        elif aqi is not None and aqi >= 80:
            factors.append(_factor("smog", "harsh", aqi=round(aqi), pm=round(pm) if pm is not None else None))
        elif aqi is not None and aqi >= 60:
            factors.append(_factor("smog", "advisory", aqi=round(aqi), pm=round(pm) if pm is not None else None))
    level = max((SEVERITY[f["level"]] for f in factors), default=0)
    return {
        "applies": True,
        "level": ("advisory", "harsh", "severe")[level] if factors else "ok",
        "score_level": level,
        "factors": factors,
        "outdoor_penalty": OUTDOOR_PENALTY[level],
        "indoor_bonus": INDOOR_BONUS[level],
        "travel_weight": TRAVEL_WEIGHT[level],
    }
