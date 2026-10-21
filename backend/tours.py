"""Guided walks: hand-made routes with sourced facts (data/tours.yaml).

Every fact carries a link to the page it was checked against. Legs between stops follow the
OSM walking graph; where no path exists the leg is a straight line and says so, never a fake route.
"""

from pathlib import Path
from urllib.parse import urlparse
import yaml
from pydantic import BaseModel, Field
from .routing import MAX_ALLOWED_SNAP_M, meters
from .settings import DATA

TOURS_FILE = DATA / "tours.yaml"
LANGS = ("ru", "kk", "en")
STRAIGHT_DETOUR = 1.3
WALK_M_PER_MIN = 75
SOURCE_NAMES = {
    "wikipedia.org": "Википедия", "tengrinews.kz": "Tengrinews", "inform.kz": "Kazinform", "kazinform.kz": "Kazinform",
    "informburo.kz": "Informburo", "astana.gov.kz": "Акимат Астаны", "gov.kz": "gov.kz", "egemen.kz": "Egemen",
    "akorda.kz": "Акорда", "khanshatyr.com": "Хан Шатыр", "expo2017astana.com": "EXPO-2017",
    "openstreetmap.org": "OpenStreetMap", "sxodim.com": "sxodim", "t.me": "Telegram", "kursiv.media": "Kursiv",
    "zakon.kz": "Zakon.kz", "nur.kz": "NUR.KZ", "vlast.kz": "Vlast.kz", "24.kz": "24KZ", "khabar.kz": "Khabar",
    "astanabotsad.kz": "Ботанический сад", "2gis.kz": "2ГИС",
}


class Text(BaseModel):
    ru: str
    kk: str | None = None
    en: str | None = None

    def get(self, lang):
        return (getattr(self, lang, None) or self.ru).strip()


class Fact(Text):
    source: str


class Hours(Text):
    source: str | None = None


class Stop(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    name: Text
    lat: float = Field(ge=50.9, le=51.4)
    lon: float = Field(ge=71.1, le=71.8)
    coord_source: str | None = None
    radius_m: int = Field(80, ge=30, le=200)
    outdoor: bool = True
    facts: list[Fact] = Field(min_length=1)
    tip: Text | None = None


class Tour(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    title: Text
    subtitle: Text
    duration_min: int = Field(ge=10, le=300)
    distance_km: float = Field(gt=0, le=15)
    outdoor: bool = True
    best_season: Text | None = None
    hours: Hours | None = None
    stops: list[Stop] = Field(min_length=2)


def source_name(url):
    host = (urlparse(url).hostname or "").removeprefix("www.")
    for domain, name in SOURCE_NAMES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def load(path: Path | None = None):
    path = path or TOURS_FILE
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tours = [Tour.model_validate(t) for t in raw.get("tours", raw)]
    if len({t.id for t in tours}) != len(tours):
        raise ValueError("duplicate tour id")
    return {t.id: t for t in tours}


def lang_of(value):
    return value if value in LANGS else "ru"


def cards(tours, lang):
    lang = lang_of(lang)
    return [
        {
            "id": t.id,
            "title": t.title.get(lang),
            "subtitle": t.subtitle.get(lang),
            "duration_min": t.duration_min,
            "distance_km": t.distance_km,
            "outdoor": t.outdoor,
            "stops": len(t.stops),
            "facts": sum(len(s.facts) for s in t.stops),
        }
        for t in tours.values()
    ]


def _leg(router, a, b):
    """Walking leg between two stops on the OSM graph, or a labelled straight line."""
    start, end = (a.lat, a.lon), (b.lat, b.lon)
    state = router.paths(start, False, max_minutes=120, max_snap_m=MAX_ALLOWED_SNAP_M)
    route = router.route(start, end, False, state) if state is not None else None
    if route:
        # The graph path starts and ends at snapped nodes; the stop itself may be up to 300 m off it.
        return {
            "geometry": [list(start), *route["geometry"], list(end)],
            "origin_snap_m": route.get("origin_snap_m"),
            "destination_snap_m": route.get("destination_snap_m"),
            "duration_min": route["duration_min"],
            "network_distance_m": route["network_distance_m"],
            "network": True,
        }
    straight = meters(start, end)
    return {
        "geometry": [list(start), list(end)],
        "duration_min": round(straight * STRAIGHT_DETOUR / WALK_M_PER_MIN, 1),
        "network_distance_m": round(straight),
        "network": False,
    }


class Registry:
    """Tours loaded once; the legs of each are routed on first request and kept."""

    def __init__(self, router, path: Path | None = None):
        self.router = router
        self.tours = load(path)
        self._legs = {}

    def detail(self, tour_id, lang):
        tour = self.tours.get(tour_id)
        if tour is None:
            return None
        lang = lang_of(lang)
        if tour_id not in self._legs:
            self._legs[tour_id] = [_leg(self.router, a, b) for a, b in zip(tour.stops, tour.stops[1:])]
        legs = self._legs[tour_id]
        return {
            "id": tour.id,
            "title": tour.title.get(lang),
            "subtitle": tour.subtitle.get(lang),
            "duration_min": tour.duration_min,
            "distance_km": tour.distance_km,
            "outdoor": tour.outdoor,
            "best_season": tour.best_season.get(lang) if tour.best_season else None,
            "hours": (
                {"text": tour.hours.get(lang), "source": tour.hours.source} if tour.hours else None
            ),
            "stops": [
                {
                    "id": s.id,
                    "name": s.name.get(lang),
                    "latitude": s.lat,
                    "longitude": s.lon,
                    "radius_m": s.radius_m,
                    "outdoor": s.outdoor,
                    "coord_source": s.coord_source,
                    "facts": [
                        {"text": f.get(lang), "source": f.source, "source_name": source_name(f.source)}
                        for f in s.facts
                    ],
                    "tip": s.tip.get(lang) if s.tip else None,
                }
                for s in tour.stops
            ],
            "legs": legs,
            "walk_min": round(sum(leg["duration_min"] for leg in legs)),
            "network_legs": sum(1 for leg in legs if leg["network"]),
            "note": "Факты проверены по ссылкам; маршрут между точками строится по пешеходному графу OSM.",
        }
