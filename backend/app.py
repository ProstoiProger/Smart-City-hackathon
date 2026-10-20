import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from .settings import DATA, ROOT, setting
from .hours import parse_when
from .service import City, LABELS
from .routing import MAX_ALLOWED_SNAP_M, MAX_SNAP_M, MIN_SNAP_M
from .providers import PROVIDERS, select, configured
from .weather import current_weather
from .events import recheck

city = None
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


@app.post("/api/events/{event_id}/refresh")
def refresh_event(event_id: str):
    import json

    original = next(
        (
            json.loads(l)
            for l in (DATA / "events.jsonl").open(encoding="utf-8")
            if json.loads(l).get("event_id") == event_id
        ),
        None,
    )
    if original is None:
        raise HTTPException(404, "Событие не найдено")
    return recheck(original)


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


@app.post("/api/chat")
def chat(req: ChatRequest):
    origin = req.origin()
    message_origin, origin_label = city.origin_from_message(req.query)
    if message_origin is not None:
        origin = message_origin
    minutes = req.minutes
    import re

    flight = bool(re.search(r"аэропорт|рейс|вылет|flight|әуежай", req.query, re.I))

    match = re.search(r"(\d{2,3})\s*(?:мин|minute|минут)", req.query, re.I)
    hours_match = re.search(r"(\d(?:[.,]\d+)?)\s*(?:час|сағат|hours?)", req.query, re.I)
    if flight and hours_match:
        minutes = max(10, min(240, int(float(hours_match[1].replace(",", ".")) * 60)))
    elif match:
        minutes = max(10, min(240, int(match.group(1))))
    elif hours_match:
        minutes = max(
            10, min(240, int(float(hours_match.group(1).replace(",", ".")) * 60))
        )
    elif re.search(r"(?:за|на)\s+час\b|бір сағат", req.query, re.I):
        minutes = 60
    provider = req.provider or setting("LLM_PROVIDER", "offline")
    if provider not in PROVIDERS:
        provider = "offline"
    flight_context = None
    if flight:
        if req.airport_transfer_min is None or req.airport_reserve_min is None:
            return {
                "answer": "Для прогулки до вылета нужно оставить время на дорогу до аэропорта, регистрацию и досмотр. Укажите оба резерва в условиях прогулки и повторите запрос. Без них я не предлагаю маршрут, чтобы не занять всё время до рейса.",
                "items": [],
                "provider_requested": provider,
                "provider_used": "offline",
                "warnings": [
                    "Требования авиакомпании и время трансфера нужно проверить отдельно."
                ],
                "origin": None,
                "minutes": minutes,
                "steps": [
                    {"action": "Учет вылета", "result": "Не заданы резервы времени"}
                ],
                "generated_facts": False,
                "flight_context": {"needs_buffers": True, "total_minutes": minutes},
            }
        usable = minutes - req.airport_transfer_min - req.airport_reserve_min
        flight_context = {
            "total_minutes": minutes,
            "transfer_minutes": req.airport_transfer_min,
            "airport_reserve_minutes": req.airport_reserve_min,
            "walk_budget_minutes": max(0, usable),
            "buffers_source": "user_input",
        }
        if usable < 10:
            return {
                "answer": "После резервов на аэропорт и трансфер времени на прогулку не остаётся. Не планируйте дополнительные остановки.",
                "items": [],
                "provider_requested": provider,
                "provider_used": "offline",
                "warnings": ["Расчёт использует заданные вами резервы."],
                "origin": None,
                "minutes": minutes,
                "steps": [
                    {
                        "action": "Учет вылета",
                        "result": "Бюджет прогулки меньше 10 минут",
                    }
                ],
                "generated_facts": False,
                "flight_context": flight_context,
            }
        minutes = usable
    historical_nur_alem = bool(
        re.search(r"н[уұ]р[\s-]*[аә]лем|nur[\s-]*alem", req.query, re.I)
    )
    effective_query = (
        "интерактивный музей alem.ai" if historical_nur_alem else req.query
    )
    route_mode = (
        req.mini_route
        if req.mini_route is not None
        else bool(ROUTE_INTENT.search(req.query))
    )
    group = req.group_size if req.group_size and req.group_size > 1 else detect_group(req.query)
    event_intent = bool(EVENT_INTENT.search(req.query))
    pool = city.search(
        effective_query,
        req.category,
        origin,
        minutes,
        req.when,
        req.open_only,
        req.no_steps,
        24 if route_mode and origin else 9,
        req.strict_amenities,
        distinct_names=True,
        max_snap_m=req.max_snap_m,
        group_size=group,
    )
    # Published events the walk can catch: shown when asked for, or when one is a short walk away.
    events = [
        e
        for e in city.events_nearby(
            origin, req.when, minutes, req.no_steps, req.max_snap_m,
            limit=3, reachable_only=bool(origin),
        )
        if event_intent or (e["walk_min"] is not None and e["walk_min"] <= 20)
    ]
    if event_intent:
        # Venues of matching events lead the candidates so the answer can point to them.
        known = {p["poi_id"] for p in pool}
        venues = [
            city.venue_candidate(e["venue_poi_id"], origin, minutes, req.when, req.no_steps, req.max_snap_m)
            for e in events
            if e["venue_poi_id"] and e["venue_poi_id"] not in known
        ]
        pool = [v for v in venues if v] + pool
    route = (
        city.mini_route(pool, origin, minutes, req.when, req.no_steps, req.max_snap_m)
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
        "when": req.when,
        "steps_excluded": req.no_steps,
        "weather": weather,
        "flight_context": flight_context,
    }
    if group:
        context["group_size"] = group
    if events:
        context["events"] = [
            {k: e[k] for k in ("name", "start", "end", "venue", "venue_poi_id", "walk_min", "price_from", "age_group")}
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
    if route:
        # The answer follows the route order; stops the model skipped keep data-only text.
        by_pick = {p["poi_id"]: p for p in picks}
        picks = [
            by_pick.get(s["poi_id"])
            or {"poi_id": s["poi_id"], "why": None, "what_to_do": None, "basis": [], "generated": False}
            for s in route["stops"]
        ]
    byid = {p["poi_id"]: p for p in candidates}
    selected = []
    for pick in picks:
        item = dict(byid[pick["poi_id"]])
        item["events"] = [e for e in events if e["venue_poi_id"] == item["poi_id"]]
        item["why"] = pick["why"]
        item["what_to_do"] = pick["what_to_do"]
        item["explanation"] = {
            "generated": pick["generated"],
            "basis": pick["basis"],
            "note": (
                "Текст «почему» и «что делать» написан Gemini по данным места и отзывам; "
                "«что делать» — идея, а не проверенный факт."
                if pick["generated"]
                else "Объяснение собрано из данных места без генерации."
            ),
        }
        selected.append(item)
    generated = any(p["generated"] for p in picks)
    text = (
        summary
        or "Нашёл варианты по вашему запросу. Факты, оценки времени и ограничения приведены в карточках."
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
    if events:
        text += " Рядом есть опубликованные события на это время — см. блок «События»."
    elif event_intent:
        text += " Подходящих по времени и пешей доступности событий в афише не найдено."
    if flight_context:
        text = (
            f"На прогулку остаётся {minutes} мин после заданных вами резервов на трансфер и аэропорт. "
            + text
        )
    warnings = [warning] if warning else []
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
            "Буферы заданы вами. Время трансфера и требования авиакомпании не проверяются в реальном времени."
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
        "minutes": minutes,
        "generated_facts": False,
        "generated_text": generated,
        "flight_context": flight_context,
        "weather": weather,
    }


dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(dist / "index.html")
