"""Where Astana cannot answer a typical request.

The assistant itself asks a handful of everyday requests from the middle of every populated ~1 km
cell, on the real data, at a fixed moment. A cell where nothing fits, or where the nearest fit is
far away, is a gap in the city's supply, not a mistake of the user. Results go to data/city_audit.json.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import Counter
from .comfort import assess
from .hours import ASTANA, parse_when
from .service import evidence
from .routing import meters

LAT_STEP = 0.009
LON_STEP = 0.0145
MIN_PLACES = 3
FAR_MIN = 15
SKIP_CATEGORIES = {"accommodation", "infrastructure", "other"}
FROST = {
    "available": True,
    "temperature_c": -22,
    "feels_like_c": -28,
    "precipitation_mm": 0,
    "weather_code": 3,
    "wind_kmh": 10,
}
# How a cell is named: the nearest well-known place, bigger kinds preferred over a statue.
LANDMARK_WEIGHT = {
    "mall": 0.6, "park": 0.7, "stadium": 0.8, "museum": 0.8, "theatre": 0.8, "concert_hall": 0.8,
    "monument": 1.0, "attraction": 1.0, "place_of_worship": 1.1,
}


@dataclass(frozen=True)
class Scenario:
    id: str
    query: str
    weekday: int  # Monday = 0
    hour: int
    minute: int
    minutes: int = 60
    attrs: tuple = ()  # amenities an answer must have: confirmed or supported counts
    strict: bool = False  # only data-confirmed amenities count as covered, reviews alone are a guess
    covered: bool = False  # the place must not be out in the open
    open_only: bool = False
    frost: bool = False
    category: str | None = None
    events: bool = False


SCENARIOS = (
    Scenario("kids_evening", "с ребёнком", 4, 18, 30, covered=True),
    Scenario("work_quiet", "тихо поработать кофе розетка", 1, 15, 0, attrs=("quiet", "power_outlets")),
    Scenario("step_free", "на коляске погулять", 5, 13, 0, attrs=("accessibility",), strict=True),
    Scenario("night", "что открыто ночью", 4, 23, 30, open_only=True),
    Scenario("frost", "погреться и поесть", 1, 13, 0, covered=True, frost=True, category="food_drink"),
    Scenario("events", "что идёт вечером", 4, 19, 0, minutes=120, events=True),
)
BY_ID = {s.id: s for s in SCENARIOS}


def moment(s, day):
    """The next `s.weekday` on or after `day`, at the scenario's time, Astana time."""
    d = day + timedelta(days=(s.weekday - day.weekday()) % 7)
    return datetime(d.year, d.month, d.day, s.hour, s.minute, tzinfo=ASTANA)


def cells(city):
    """Populated ~1 km cells with their places (transport and lodging do not make a neighbourhood)."""
    out = {}
    for p in city.pois:
        if not p.get("recommendation_eligible", True) or p.get("category") in SKIP_CATEGORIES:
            continue
        key = (round(p["latitude"] / LAT_STEP), round(p["longitude"] / LON_STEP))
        out.setdefault(key, []).append(p)
    return {k: v for k, v in out.items() if len(v) >= MIN_PLACES}


def centroid(places):
    return (
        sum(p["latitude"] for p in places) / len(places),
        sum(p["longitude"] for p in places) / len(places),
    )


def label(origin, places):
    best = None
    for p in places:
        weight = LANDMARK_WEIGHT.get(p.get("subcategory"))
        name = (p.get("display_name") or "").split(",")[0]
        if weight is None or not name:
            continue
        d = meters(origin, (p["latitude"], p["longitude"]))
        if d <= 1200 and (best is None or d * weight < best[0]):
            best = (d * weight, name)
    if best:
        return best[1]
    streets = Counter(
        s for p in places if (s := (p.get("address") or "").split(",")[0].strip()) and sum(c.isalpha() for c in s) >= 3
    )
    if streets:
        return streets.most_common(1)[0][0]
    named = max(places, key=lambda p: p.get("ratings_count") or 0)
    return (named.get("display_name") or "").split(",")[0] or None


def fit_kind(city, item, s):
    """'sure' (data confirms), 'likely' (reviews or unknown hours) or None (does not fit)."""
    if s.covered and item.get("exposure") == "outdoor":
        return None
    p = city.byid[item["poi_id"]]
    signals = (city.review_signals.get(p["poi_id"]) or {}).get("signals")
    kinds = [evidence(p, a, signals)[0] for a in s.attrs]
    if any(k not in ("confirmed", "supported") for k in kinds):
        return None
    # Requested amenities are confirmed by the place's own data; without any, the schedule is the proof.
    sure = (
        all(k == "confirmed" for k in kinds)
        if s.attrs
        else item["hours_status"]["status"] == "open_by_schedule"
    )
    return "sure" if sure else "likely"


def ask(city, s, origin, at):
    """(options, confirmed, nearest walk minutes, best names) for one scenario at one origin."""
    if s.events:
        found = city.events_nearby(origin, at.isoformat(), s.minutes, max_snap_m=300, limit=20)
        found = [e for e in found if e["walk_min"] is not None and not e.get("late")]
        return (
            len(found),
            len(found),
            min((e["walk_min"] for e in found), default=None),
            [e["name"] for e in found[:2]],
        )
    comfort = assess(FROST, {"available": False}, now=at) if s.frost else None
    items = city.search(
        s.query, s.category, origin, s.minutes, at.isoformat(), s.open_only, False, 12, False,
        distinct_names=True, max_snap_m=300, comfort=comfort,
    )
    fits = [(i, fit_kind(city, i, s)) for i in items]
    fits = [(i, k) for i, k in fits if k]
    return (
        len(fits),
        sum(1 for _, k in fits if k == "sure"),
        min((i["route"]["duration_min"] for i, _ in fits if i.get("route")), default=None),
        [i["display_name"].split(",")[0] for i, _ in fits[:2]],
    )


def level(row, s):
    """none: nothing fits; guess: only reviews fit where data must confirm; far: nearest fit is far."""
    if not row["options"]:
        return "none"
    if s.strict and not row["confirmed"]:
        return "guess"
    return "far" if (row["nearest_min"] or 0) > FAR_MIN else "ok"


def build(city, day, progress=None):
    grid = cells(city)
    out_cells = []
    for n, ((_, _), places) in enumerate(sorted(grid.items())):
        origin = centroid(places)
        if city.router.paths(origin, False, max_minutes=5, max_snap_m=300) is None:
            continue
        row = {
            "lat": round(origin[0], 5),
            "lon": round(origin[1], 5),
            "label": label(origin, places),
            "places": len(places),
            "results": {},
        }
        for s in SCENARIOS:
            options, confirmed, nearest, best = ask(city, s, origin, moment(s, day))
            r = {
                "options": options,
                "confirmed": confirmed,
                "nearest_min": round(nearest) if nearest is not None else None,
                "best": best,
            }
            r["level"] = level(r, s)
            row["results"][s.id] = r
        out_cells.append(row)
        if progress:
            progress(n + 1, len(grid))
    summary = {}
    for s in SCENARIOS:
        counts = Counter(c["results"][s.id]["level"] for c in out_cells)
        summary[s.id] = {k: counts[k] for k in ("none", "guess", "far", "ok")} | {"cells": len(out_cells)}
    return {
        "generated_for": day.isoformat(),
        "cell_step": {"lat": LAT_STEP, "lon": LON_STEP},
        "scenarios": [
            {
                "id": s.id,
                "request": s.query,
                "when": moment(s, day).isoformat(),
                "strict": s.strict,
                "summary": summary[s.id],
            }
            for s in SCENARIOS
        ],
        "cells": out_cells,
        "coverage": coverage(city),
    }


def coverage(city):
    """How complete the data behind every answer is: what the audit can and cannot see."""
    eligible = [p for p in city.pois if p.get("recommendation_eligible", True)]
    n = len(eligible)

    def share(test):
        return sum(1 for p in eligible if test(p))

    return {
        "places": n,
        "with_hours": share(lambda p: p.get("opening_hours_by_day") or p.get("opening_hours")),
        "with_rating": share(lambda p: p.get("rating") is not None),
        "with_accessibility": share(lambda p: p.get("wheelchair_accessible") is not None),
        "with_review_signals": share(lambda p: p["poi_id"] in city.review_signals),
        "with_price": share(lambda p: p.get("estimated_visit_budget") or p.get("free_entry") is not None),
        "events": len(city.events),
    }


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def reference_day(city):
    return parse_when("2026-10-19T12:00:00").date()
