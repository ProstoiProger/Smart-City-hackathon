import itertools
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from .settings import DATA, ROOT, setting
from .hours import closure, parse_when
from .service import ATTR_LABEL, City, LABELS, read_intents
from .routing import MAX_ALLOWED_SNAP_M, MAX_SNAP_M, MIN_SNAP_M, meters
from .providers import PROVIDERS, explain_from_data, select, configured
from .query import (
    NEARBY_RELAXED_MIN,
    NEARBY_WALK_MIN,
    content_query,
    cover_groups,
    language,
    parse_budget,
    parse_time_of_day,
    tokens,
    wants_nearby,
    without_tokens,
)
from .weather import current_weather
from .photos import main_photo

city = None
# Assumed when a flight is mentioned but the user gave no buffers of their own: a taxi
# from the centre to the airport and the minimum before a domestic departure.
DEFAULT_TRANSFER_MIN = 30
DEFAULT_AIRPORT_RESERVE_MIN = 60
OFFLINE_SUMMARY = {
    "ru": "Нашёл варианты по вашему запросу. Факты, оценки времени и ограничения приведены в карточках.",
    "kk": "Сұрауыңыз бойынша нұсқалар табылды. Деректер, уақыт пен шектеулер карточкаларда.",
    "en": "Here are options for your request. Facts, time estimates and limits are on the cards.",
}


def city_closed(pid):
    return closure(city.byid[pid])


def is_start_place(p, start, query):
    """The place the user said they are at ("я у Экспо" → "Территория EXPO")."""
    if (p.get("route") or {}).get("duration_min", 99) > 5:
        return False
    toks = tokens(query)
    words = {t for t, _, _ in tokens(start["label"])} | {toks[i][0] for i in start["tokens"]}
    names = [t for t, _, _ in tokens(p["display_name"].split(",")[0]) if len(t) >= 4]
    return any(w.startswith(n) for n in names for w in words)
ROUTE_INTENT = re.compile(
    r"маршрут|прогул|погуля|обойти|несколько мест|серуен|бағыт|\broute\b|\bwalk|itinerary",
    re.I,
)
EVENT_INTENT = re.compile(
    r"концерт|спектакл|театр|выставк|\bшоу\b|мероприят|событи|афиш|фестивал|стендап|stand-?up|цирк|опер|балет|"
    r"іс-шара|көрме|\bevent|concert|exhibition|\bshow\b|theat",
    re.I,
)
GROUP_WORDS = {
    "вдвоём": 2, "вдвоем": 2, "втроём": 3, "втроем": 3, "вчетвером": 4, "впятером": 5, "вшестером": 6,
    "двое": 2, "трое": 3, "четверо": 4, "пятеро": 5, "шестеро": 6,
    "екеуміз": 2, "үшеуміз": 3, "төртеуміз": 4, "бесеуміз": 5,
}
GROUP_NUMBER = re.compile(
    r"(?:нас|компани[яи]\s+из|групп[аы]\s+из|группой\s+из|we\s+are|group\s+of|party\s+of)\s+(\d{1,2})"
    r"|(\d{1,2})\s*(?:человек|чел\b|людей|people|persons|адам)",
    re.I,
)
GROUP_VAGUE = re.compile(r"с друзьями|компани|группой|достармен|with friends|\bfriends\b", re.I)


def detect_group(text):
    """Group size from the request text: explicit number, Russian/Kazakh collective words, or None."""
    m = GROUP_NUMBER.search(text)
    if m:
        return max(1, min(10, int(m.group(1) or m.group(2))))
    lowered = text.casefold()
    words = set(re.findall(r"\w+", lowered))
    for word, size in GROUP_WORDS.items():
        if word in words:
            return size
    # "with friends" without a number: plan for a typical company of 4.
    return 4 if GROUP_VAGUE.search(text) else None


@asynccontextmanager
async def lifespan(app):
    global city
    city = City()
    yield


app = FastAPI(title="Astana Walk — Smart City", version="1.1.0", lifespan=lifespan)


class Context(BaseModel):
    latitude: float | None = Field(None, ge=50.8, le=51.5)
    longitude: float | None = Field(None, ge=71.0, le=71.9)
    minutes: int = Field(90, ge=10, le=240)
    when: str | None = None
    no_steps: bool = False
    # Max unverified connector from start/places to the walking network, chosen in the UI.
    max_snap_m: int = Field(MAX_SNAP_M, ge=MIN_SNAP_M, le=MAX_ALLOWED_SNAP_M)

    @model_validator(mode="after")
    def validate_context(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Укажите обе координаты")
        if self.when:
            try:
                parse_when(self.when)
            except (ValueError, TypeError):
                raise ValueError("Неверная дата: требуется ISO 8601")
        return self

    def origin(self):
        return (self.latitude, self.longitude) if self.latitude is not None else None


class SearchRequest(Context):
    query: str = Field("", max_length=1500)
    category: str | None = None
    open_only: bool = False
    strict_amenities: bool = False
    limit: int = Field(30, ge=1, le=100)
    # Company size; None lets the chat read it from the text ("нас 4", "втроём").
    group_size: int | None = Field(None, ge=1, le=10)


class ChatRequest(SearchRequest):
    query: str = Field(min_length=1, max_length=1500)
    provider: Literal["offline", "gemini"] | None = None
    airport_transfer_min: int | None = Field(None, ge=0, le=240)
    airport_reserve_min: int | None = Field(None, ge=0, le=240)
    # None: build a mini-route when the request asks for a walk/route; True/False forces it.
    mini_route: bool | None = None


class PlanRequest(Context):
    poi_ids: list[str] = Field(min_length=1, max_length=3)


@app.get("/api/health")
def health():
    return {"ok": city is not None, "pois": len(city.pois) if city else 0}


@app.get("/api/meta")
def meta():
    return {
        "name": "Astana Walk",
        "pois": len(city.pois),
        "search_backend": city.index.backend,
        "categories": LABELS,
        "landmarks": city.landmarks,
        "default_provider": setting("LLM_PROVIDER", "offline"),
        "providers": {
            p: {"configured": configured(p), "connection_tested": False}
            for p in PROVIDERS
        },
        "dataset_date": "2026-10-19",
        "live_hours": False,
        "location_stored": False,
        "snap_radius_m": {
            "default": MAX_SNAP_M,
            "min": MIN_SNAP_M,
            "max": MAX_ALLOWED_SNAP_M,
        },
        "source_pois": 7570,
    }


@app.get("/api/weather")
def weather():
    return current_weather()


@app.get("/api/events")
def events():
    import json

    rows = [json.loads(l) for l in (DATA / "events.jsonl").open(encoding="utf-8")]
    today = parse_when().date().isoformat()
    items = [
        e
        for e in rows
        if (e.get("event_end") or e.get("event_start") or "") >= today
        and not str(e.get("event_status") or "").endswith(
            ("EventCancelled", "EventPostponed")
        )
    ]
    return {
        "items": items,
        "all_snapshot_records": len(rows),
        "live_verified": False,
        "note": "Публикации источников, не проверка фактического проведения или отмены.",
    }


@app.post("/api/search")
def search(req: SearchRequest):
    items = city.search(
        req.query,
        req.category,
        req.origin(),
        req.minutes,
        req.when,
        req.open_only,
        req.no_steps,
        req.limit,
        req.strict_amenities,
        max_snap_m=req.max_snap_m,
        group_size=req.group_size,
    )
    warnings = []
    if (
        req.origin()
        and city.router.paths(req.origin(), req.no_steps, max_snap_m=req.max_snap_m) is None
    ):
        warnings.append(
            f"Начальная точка дальше {req.max_snap_m} м от пешеходного графа. Выберите другую точку на карте или увеличьте радиус привязки."
        )
    return {
        "items": items,
        "count": len(items),
        "warnings": warnings,
        "search_backend": city.index.backend,
    }


@app.get("/api/pois/{poi_id:path}/photo")
def photo(poi_id: str):
    """Main 2GIS photo, checked only when a card is opened (registered before the
    catch-all detail route, whose path converter would otherwise swallow "/photo")."""
    if poi_id not in city.byid:
        raise HTTPException(404, "Место не найдено")
    return main_photo(city.byid[poi_id])


@app.get("/api/pois/{poi_id:path}")
def detail(poi_id: str):
    if poi_id not in city.byid:
        raise HTTPException(404, "Место не найдено")
    return city.public(city.byid[poi_id])


@app.post("/api/compare")
def compare(req: PlanRequest):
    if any(pid not in city.byid for pid in req.poi_ids):
        raise HTTPException(404, "Место не найдено")
    items = []
    state = (
        city.router.paths(req.origin(), req.no_steps, max_snap_m=req.max_snap_m)
        if req.origin()
        else None
    )
    for pid in dict.fromkeys(city.byid[i]["poi_id"] for i in req.poi_ids):
        p = city.byid[pid]
        obj = city.public(p, req.when)
        obj["route"] = (
            city.router.route(
                req.origin(), (p["latitude"], p["longitude"]), req.no_steps, state
            )
            if req.origin() and state is not None
            else None
        )
        items.append(obj)
    return {
        "items": items,
        "note": "Средний чек и входной билет — разные виды цены. Неизвестная цена не означает бесплатное посещение.",
    }


@app.post("/api/plan")
def plan(req: PlanRequest):
    if req.origin() is None:
        raise HTTPException(422, "Выберите начало маршрута на карте")
    if any(pid not in city.byid for pid in req.poi_ids):
        raise HTTPException(404, "Место не найдено")
    return city.plan(
        req.poi_ids, req.origin(), req.minutes, req.when, req.no_steps, req.max_snap_m
    )


def _interleave(lists):
    """Round-robin merge without duplicates: each named kind of place reaches the top."""
    out, seen = [], set()
    for row in itertools.zip_longest(*lists):
        for p in row:
            if p and p["poi_id"] not in seen:
                seen.add(p["poi_id"])
                out.append(p)
    return out


@app.post("/api/chat")
def chat(req: ChatRequest):
    provider = req.provider or setting("LLM_PROVIDER", "offline")
    if provider not in PROVIDERS:
        provider = "offline"
    lang = language(req.query)

    # Where. A place named as the start ("я у Хан Шатыра") wins over the map point; a
    # place named as the goal ("сходить в Хан Шатыр") keeps the map start and becomes
    # a candidate. Without any start, the first named place locates the search.
    origin, origin_label = req.origin(), None
    mentions = city.mentions(req.query)
    start = next((m for m in mentions if m["role"] == "origin" and m["point"]), None)
    if start is None and origin is None:
        start = next((m for m in mentions if m["point"]), None)
    if start:
        origin, origin_label = start["point"], start["label"]
        start_note = f"{start['label']} (из текста)" + (
            "" if start["role"] == "origin" else "; ваша точка старта не задана, ищу вокруг этого места"
        )
    elif origin:
        start_note = "точка на карте или выбранный ориентир"
    else:
        start_note = "не задан — пешая доступность не проверена"
    destinations = [m for m in mentions if m is not start and m["poi_ids"] and m["role"] != "origin"]
    # The start itself is not what the user looks for: "Я у Экспо" must not return EXPO.
    effective_query = without_tokens(req.query, start["tokens"]) if start else req.query

    # How long and when.
    flight = bool(re.search(r"аэропорт|рейс|вылет|flight|әуежай", req.query, re.I))
    minutes, budget_note = req.minutes, "из условий прогулки"
    parsed, note = parse_budget(req.query, prefer_hours=flight)
    if parsed:
        minutes, budget_note = parsed, note
    when, when_note = req.when, ("из условий прогулки" if req.when else "сейчас")
    if not req.when:
        text_when, note = parse_time_of_day(req.query)
        when = text_when or when
        when_note = note or when_note
    total_minutes = minutes

    flight_context = None
    if flight:
        given = req.airport_transfer_min is not None and req.airport_reserve_min is not None
        transfer = req.airport_transfer_min if req.airport_transfer_min is not None else DEFAULT_TRANSFER_MIN
        reserve = req.airport_reserve_min if req.airport_reserve_min is not None else DEFAULT_AIRPORT_RESERVE_MIN
        usable = minutes - transfer - reserve
        flight_context = {
            "total_minutes": minutes,
            "transfer_minutes": transfer,
            "airport_reserve_minutes": reserve,
            "walk_budget_minutes": max(0, usable),
            "buffers_source": "user_input" if given else "default_assumption",
            "needs_buffers": not given,
        }
        if usable < 10:
            return {
                "answer": (
                    f"После {transfer} мин на дорогу до аэропорта и {reserve} мин на регистрацию и досмотр "
                    "времени на прогулку не остаётся. Не планируйте дополнительные остановки."
                ),
                "items": [],
                "provider_requested": provider,
                "provider_used": "offline",
                "warnings": [
                    "Расчёт использует заданные вами резервы."
                    if given
                    else "Резервы — допущение по умолчанию; укажите свои в «Условиях прогулки»."
                ],
                "origin": None,
                "minutes": minutes,
                "steps": [{"action": "Учёт вылета", "result": "Бюджет прогулки меньше 10 минут"}],
                "considered": [
                    {"label": "Время", "value": f"{minutes} мин — {budget_note}"},
                    {"label": "Вылет", "value": f"дорога {transfer} мин + аэропорт {reserve} мин"},
                ],
                "generated_facts": False,
                "flight_context": flight_context,
            }
        minutes = usable

    historical_nur_alem = bool(
        re.search(r"н[уұ]р[\s-]*[аә]лем|nur[\s-]*alem", req.query, re.I)
    )
    if historical_nur_alem:
        effective_query = "интерактивный музей alem.ai"
    route_mode = (
        req.mini_route
        if req.mini_route is not None
        else bool(ROUTE_INTENT.search(req.query))
    )
    group = req.group_size if req.group_size and req.group_size > 1 else detect_group(req.query)
    event_intent = bool(EVENT_INTENT.search(req.query))
    cover = [] if req.category else cover_groups(req.query)
    nearby = bool(origin) and not route_mode and wants_nearby(req.query)
    limit = 24 if route_mode and origin else 9

    def gather(max_walk):
        def find(category, n):
            return city.search(
                effective_query, category, origin, minutes, when, req.open_only, req.no_steps,
                n, req.strict_amenities, distinct_names=True, max_snap_m=req.max_snap_m,
                group_size=group, max_walk_min=max_walk,
            )

        if cover:
            # "музей и кофе": candidates of each named kind, so neither crowds the other out.
            return _interleave([find(cat, max(8, limit // len(cover))) for _, cat in cover])
        return find(req.category, limit)

    def evidenced(items):
        # Places whose requested amenities (outlets, quiet…) are confirmed or supported.
        return [p for p in items if p.get("evidence") and all(k in ("confirmed", "supported") for k in p["evidence"].values())]

    walk_note = None
    pool = gather(NEARBY_WALK_MIN if nearby else None)
    if nearby:
        walk_note = f"до {NEARBY_WALK_MIN} мин пешком — вы написали, что нужно рядом"
        relaxed = None
        if len(pool) < 3:
            relaxed = "подходящих мест меньше трёх"
        elif any(p.get("evidence") for p in pool) and not evidenced(pool[:3]):
            relaxed = "нет мест с подтверждёнными удобствами из запроса"
        if relaxed:
            wider = gather(NEARBY_RELAXED_MIN)
            if len(wider) > len(pool) or evidenced(wider[:3]):
                pool = wider
                walk_note = f"до {NEARBY_RELAXED_MIN} мин пешком: в пределах {NEARBY_WALK_MIN} мин {relaxed}"
    if start:
        pool = [p for p in pool if not is_start_place(p, start, req.query)]

    warnings = []
    # Places the request goes to lead the candidates, with their own route and hours.
    known = {p["poi_id"]: p for p in pool}
    leads = []
    for m in destinations[:2]:
        ids = [i for i in m["poi_ids"] if not city_closed(i)] or m["poi_ids"]
        pid = (
            min(ids, key=lambda i: meters(origin, (city.byid[i]["latitude"], city.byid[i]["longitude"])))
            if origin
            else ids[0]
        )
        if city_closed(pid):
            warnings.append(f"«{m['label']}»: источник сообщает о закрытии или скором открытии.")
            continue
        lead = known.get(pid) or city.venue_candidate(
            pid, origin, minutes, when, req.no_steps, req.max_snap_m, reason="Место из вашего запроса"
        )
        if lead is None:
            warnings.append(f"До «{m['label']}» не найден пеший путь от точки старта по графу OSM.")
            continue
        leads.append(lead)
    if leads:
        lead_ids = {p["poi_id"] for p in leads}
        # "Хочу сходить в Хан Шатыр" asks about that place only; "поесть у Хан Шатыра"
        # or a walk request keeps the other candidates too.
        skip = {i for m in destinations for i in m["tokens"]} | set(start["tokens"] if start else [])
        only_leads = not route_mode and not content_query(req.query, skip) and not read_intents(effective_query)[0]
        pool = leads + ([] if only_leads else [p for p in pool if p["poi_id"] not in lead_ids])

    # Published events the walk can catch: shown when asked for, or when one is a short walk away.
    events = [
        e
        for e in city.events_nearby(
            origin, when, minutes, req.no_steps, req.max_snap_m,
            limit=3, reachable_only=bool(origin), keep_venues={p["poi_id"] for p in leads},
        )
        if event_intent or (e["walk_min"] is not None and e["walk_min"] <= 20)
    ]
    if event_intent:
        # Venues of matching events lead the candidates so the answer can point to them.
        known = {p["poi_id"] for p in pool}
        venues = [
            city.venue_candidate(e["venue_poi_id"], origin, minutes, when, req.no_steps, req.max_snap_m)
            for e in events
            if e["venue_poi_id"] and e["venue_poi_id"] not in known
        ]
        pool = [v for v in venues if v] + pool
    route = (
        city.mini_route(
            pool, origin, minutes, when, req.no_steps, req.max_snap_m,
            cover=[cat for _, cat in cover],
        )
        if route_mode and origin
        else None
    )
    candidates = pool[:9]
    if route:
        # Route stops may rank below the top 9; the model must see all of them.
        shown = {p["poi_id"] for p in candidates}
        candidates += [
            next(p for p in pool if p["poi_id"] == s["poi_id"])
            for s in route["stops"]
            if s["poi_id"] not in shown
        ]
    weather = current_weather()
    context = {
        "budget_minutes": minutes,
        "when": when,
        "steps_excluded": req.no_steps,
        "weather": weather,
        "flight_context": flight_context,
    }
    if group:
        context["group_size"] = group
    if events:
        context["events"] = [
            {k: e[k] for k in ("name", "start", "end", "venue", "venue_poi_id", "walk_min", "late", "price_from", "age_group")}
            for e in events
        ]
    if route:
        context["mini_route"] = [
            {
                "order": i + 1,
                "poi_id": s["poi_id"],
                "walk_min": round(leg["duration_min"]),
                "visit_min": s["suggested_visit_duration_min"],
                "arrival_after_min": s["arrival_offset_min"],
            }
            for i, (s, leg) in enumerate(zip(route["stops"], route["legs"]))
        ]
    picks, summary, warning = select(provider, req.query, candidates, context)
    byid = {p["poi_id"]: p for p in candidates}
    if route:
        # The answer follows the route order; stops the model skipped get data-based text.
        by_pick = {p["poi_id"]: p for p in picks}
        visits = {s["poi_id"]: s["visit_min"] for s in context["mini_route"]}
        picks = [
            by_pick.get(s["poi_id"])
            or {
                "poi_id": s["poi_id"],
                **explain_from_data(byid[s["poi_id"]], lang, visits.get(s["poi_id"])),
                "generated": False,
                "template": True,
            }
            for s in route["stops"]
        ]
    selected = []
    for pick in picks:
        item = dict(byid[pick["poi_id"]])
        item["events"] = [e for e in events if e["venue_poi_id"] == item["poi_id"]]
        item["why"] = pick["why"]
        item["what_to_do"] = pick["what_to_do"]
        item["explanation"] = {
            "generated": pick["generated"],
            "template": bool(pick.get("template")),
            "basis": pick["basis"],
            "note": (
                "Текст «почему» и «что делать» написан Gemini по данным места и отзывам; "
                "«что делать» — идея, а не проверенный факт."
                if pick["generated"]
                else "«Почему» и «что делать» собраны по шаблону из данных места, без генерации; "
                "«что делать» — идея, а не проверенный факт."
            ),
        }
        selected.append(item)
    generated = any(p["generated"] for p in picks)
    text = (
        summary
        or OFFLINE_SUMMARY.get(lang, OFFLINE_SUMMARY["ru"])
        if selected
        else "Подходящих мест с этими условиями не найдено. Измените время, точку старта или фильтры. Неподтверждённые свойства не считаются известными."
    )
    if selected and not origin:
        text += " Выберите начало на карте, чтобы проверить пешую доступность и построить маршрут."
    if route:
        text = (
            f"Мини-маршрут: {len(route['stops'])} места за ~{round(route['total_duration_min'])} мин "
            f"из {minutes} (пешком ~{round(route['walk_duration_min'])} мин). " + text
        )
    if group:
        text = f"Подбор для компании из {group} человек. " + text
    if route_mode and origin and selected and not route:
        text += " Несколько мест вместе не укладываются в это время — показаны отдельные варианты."
    for e in events:
        if e.get("late"):
            text += (
                f" К началу «{e['name']}» в {e['start'][11:16]} пешком не успеть: путь ~{e['walk_min']} мин."
            )
    if events:
        text += " Рядом есть опубликованные события на это время — см. блок «События»."
    elif event_intent:
        text += " Подходящих по времени и пешей доступности событий в афише не найдено."
    if route and not route.get("covers_requested", True):
        text += " " + route["warnings"][0]
    if flight_context:
        text = (
            (
                f"На прогулку остаётся {minutes} мин после заданных вами резервов на трансфер и аэропорт. "
                if not flight_context["needs_buffers"]
                else f"Из {total_minutes} мин я оставил {flight_context['transfer_minutes']} мин на дорогу до аэропорта "
                f"и {flight_context['airport_reserve_minutes']} мин на регистрацию и досмотр — на прогулку {minutes} мин. "
                "Если у вас другие оценки или международный рейс, укажите их в «Условиях прогулки». "
            )
            + text
        )
    warnings = ([warning] if warning else []) + warnings
    if (
        origin
        and city.router.paths(origin, req.no_steps, max_minutes=1, max_snap_m=req.max_snap_m)
        is None
    ):
        warnings.append(
            f"Точка старта дальше {req.max_snap_m} м от пешеходных дорожек: маршрут не построить. Выберите другую точку на карте или увеличьте радиус привязки."
        )
    if historical_nur_alem:
        text = (
            "Прежний Музей энергии будущего Нур Алем прекратил приём посетителей с декабря 2024 года. В здании работает Музей Сингулярности alem.ai; его актуальные условия учитываются отдельно. "
            + text
        )
        warnings.append(
            "Источник о закрытии прежнего музея: https://qazexpocongress.kz/ru/nur-alem/"
        )
    if flight:
        warnings.append(
            (
                "Буферы заданы вами. "
                if not flight_context["needs_buffers"]
                else f"Резервы {flight_context['transfer_minutes']} + {flight_context['airport_reserve_minutes']} мин — допущение по умолчанию. "
            )
            + "Время трансфера и требования авиакомпании не проверяются в реальном времени."
        )

    # What the answer was based on, in one place the user can check ("Учтено: …").
    preferred, wanted = read_intents(effective_query)
    considered = [
        {"label": "Старт", "value": start_note},
        {"label": "Время", "value": f"{minutes} мин — {budget_note}" + (" минус резервы на вылет" if flight_context else "")},
        {"label": "Когда", "value": when_note},
    ]
    if walk_note:
        considered.append({"label": "Пешком до места", "value": walk_note})
    if cover:
        considered.append({"label": "Ищу вместе", "value": " + ".join(label for label, _ in cover)})
    elif preferred:
        considered.append({"label": "Категории", "value": ", ".join(LABELS[c].lower() for c in sorted(preferred))})
    if wanted:
        considered.append({"label": "Удобства из запроса", "value": ", ".join(ATTR_LABEL[a] for a in wanted)})
    if destinations:
        considered.append({"label": "Место из запроса", "value": ", ".join(m["label"] for m in destinations[:2])})
    if group:
        considered.append(
            {"label": "Компания", "value": f"{group} чел." + (" (из текста)" if not (req.group_size and req.group_size > 1) else "")}
        )
    filters = [
        label
        for on, label in (
            (req.category, LABELS.get(req.category or "", "").lower()),
            (req.open_only, "только открытые по расписанию"),
            (req.strict_amenities, "только подтверждённые удобства"),
            (req.no_steps, "без лестниц"),
        )
        if on
    ]
    if filters:
        considered.append({"label": "Фильтры", "value": ", ".join(filters)})
    if flight_context:
        considered.append(
            {
                "label": "Вылет",
                "value": f"дорога {flight_context['transfer_minutes']} мин + аэропорт {flight_context['airport_reserve_minutes']} мин "
                + ("(ваши оценки)" if not flight_context["needs_buffers"] else "(допущение, можно изменить)"),
            }
        )
    if route_mode and origin:
        considered.append(
            {"label": "Мини-маршрут", "value": "включён переключателем" if req.mini_route else "запрос про прогулку или маршрут"}
        )
    return {
        "answer": text,
        "items": selected,
        "provider_requested": provider,
        "provider_used": provider if generated else "offline",
        "warnings": warnings,
        "origin": (
            {"latitude": origin[0], "longitude": origin[1], "label": origin_label}
            if origin
            else None
        ),
        "steps": [
            {
                "action": "Поиск по датасету",
                "result": f"{len(candidates)} кандидатов; индекс {city.index.backend}",
            },
            {
                "action": "Проверка условий",
                "result": "Закрытия, расписание, время пути и посещения",
            },
            {
                "action": "Выбор мест и объяснения",
                "result": (
                    "Gemini: до 3 мест только из найденных кандидатов, текст «почему» и «что делать»"
                    if generated
                    else "Локальный поиск: первые 3 кандидата, объяснения из данных"
                ),
            },
        ]
        + (
            [
                {
                    "action": "Мини-маршрут",
                    "result": (
                        f"{len(route['stops'])} места, {round(route['total_duration_min'])} из {minutes} мин: "
                        f"порядок и пешие отрезки по графу OSM, часы работы проверены на момент прихода"
                    ),
                }
            ]
            if route
            else []
        )
        + (
            [
                {
                    "action": "Компания",
                    "result": (
                        f"{group} человек: выше места с VIP-залом, кабинками или банкетами по данным 2ГИС; "
                        "бюджет на всех по опубликованной цене за одного"
                    ),
                }
            ]
            if group
            else []
        )
        + (
            [
                {
                    "action": "Афиша",
                    "result": f"{len(events)} опубликованных событий во время прогулки и в пешей доступности; проведение не подтверждено",
                }
            ]
            if events
            else []
        ),
        "mini_route": route,
        "events": events,
        "group": {"size": group, "from_text": not (req.group_size and req.group_size > 1)} if group else None,
        "considered": considered,
        "when": when,
        "minutes": minutes,
        "generated_facts": False,
        "generated_text": generated,
        "flight_context": flight_context,
        "weather": weather,
    }


dist = ROOT / "frontend" / "dist"
if dist.exists():

    class HashedAssets(StaticFiles):
        """Vite file names carry a content hash, so they can be cached for good."""

        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    app.mount("/assets", HashedAssets(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        # Always revalidate the page: after a rebuild it must point at the new hashed bundle.
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
