import itertools
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from .settings import DATA, ROOT, setting
from .hours import closure, parse_when
from .service import ATTR_LABEL, City, LABELS, read_intents, toward, weather_widened
from .routing import MAX_ALLOWED_SNAP_M, MAX_SNAP_M, MIN_SNAP_M, meters
from .providers import PROVIDERS, compass, explain_from_data, select_spoken, spoken_from_data, configured
from .query import (
    NEARBY_RELAXED_MIN,
    NEARBY_WALK_MIN,
    content_query,
    cover_groups,
    finish_cue,
    finish_filler,
    has_deadline,
    language,
    LOOP,
    parse_deadline,
    parse_reserve,
    wants_loop,
    parse_budget,
    parse_time_of_day,
    tokens,
    wants_nearby,
    wants_flight,
    without_tokens,
)
from .weather import current_weather
from .comfort import assess, current_air
from .explain import Trace
from . import cityaudit, placeqa, tours as tour_data
from .group import MAX_MEMBERS, MIN_MEMBERS, clean_members, group_pool
from .photos import main_photo
from . import tts
from . import trip
from .intent import Classifier, read_edit, read_people
from .meet import MEET_INTENT, meet, meeting_line, people_from_text
from .trip import add_backups, backup_text, read_edit_rules
from . import dialog as dialogue
from .trip import DEFAULT_FINISH_RESERVE_MIN, finish_text, stamp_finish

city = None
tours = None
classifier = None
# Assumed when a flight is mentioned but the user gave no buffers of their own: a taxi
# from the centre to the airport and the minimum before a domestic departure.
DEFAULT_TRANSFER_MIN = 30
DEFAULT_AIRPORT_RESERVE_MIN = 60
OFFLINE_SUMMARY = {
    "ru": "Вот что подходит:",
    "kk": "Міне, сәйкес келетіндер:",
    "en": "Here is what fits:",
}


def comfort_summary(comfort, widened=False):
    """One line for the "Учтено" block; the card texts use the factor codes directly."""
    if not comfort["applies"]:
        return "погода и воздух описывают только «сейчас»; для выбранного времени не учитываются"
    names = {
        "frost": "сильный мороз", "cold": "холодно", "heat": "жарко", "wet": "осадки", "storm": "гроза",
        "wind": "сильный ветер", "smog": "плохой воздух",
    }
    shown = [names[f["code"]] for f in comfort["factors"] if f["level"] != "advisory"]
    if not shown:
        return None
    return ", ".join(shown) + ": уличные места ниже в выдаче, ближние и крытые выше" + (
        "; к прогулке добавлены музеи и галереи" if widened else ""
    )


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
# What kind of event the request names, how such an event is written in the listing,
# and which venues hold it: "хочу в театр" must not lead with a walking tour or a stand-up
# that merely happens during the walk. Requests naming no kind ("мероприятия") take any.
EVENT_KINDS = [
    (r"театр|спектакл|\btheat", r"спектакл|театр|пьес|постановк|мюзикл|theat|performance|play\b", {"theatre"}),
    (r"балет|ballet", r"балет|ballet", {"theatre"}),
    (r"\bопер(?:а|у|ы|е|ой|ный)\b|\bopera\b", r"опер|opera", {"theatre", "concert_hall"}),
    (r"концерт|филармон|concert", r"концерт|concert|оркестр|филармон|музык", {"concert_hall", "theatre"}),
    (r"выставк|көрме|exhibition", r"выставк|экспозиц|exhibit|көрме", {"museum", "gallery", "arts_centre"}),
    (r"цирк|circus", r"цирк|circus", {"circus"}),
    (r"стендап|stand-?up", r"стендап|stand-?up", set()),
]


def event_fits(e, query):
    """True when a listed event is the kind the request asks for (or names no kind)."""
    asked = [(text_rx, subs) for rx, text_rx, subs in EVENT_KINDS if re.search(rx, query, re.I)]
    if not asked:
        return True
    text = f"{e.get('name') or ''} {e.get('category') or ''}".strip()
    if text:
        # The listing says what it is: a walking tour starting at a theatre is not a play.
        return any(re.search(text_rx, text, re.I) for text_rx, _ in asked)
    venue = city.byid.get(e.get("venue_poi_id") or "") or {}
    return any(venue.get("subcategory") in subs for _, subs in asked)


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
    global city, tours, classifier
    city = City()
    tours = tour_data.Registry(city.router)
    classifier = Classifier(city.pois, LABELS)
    yield


app = FastAPI(title="Astana Walk — Smart City", version="1.1.0", lifespan=lifespan)
# Phones on mobile data: bundles and answers travel compressed (the JS shrinks ~3.5x).
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)


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
    # Places from the walker's own history (kept in their browser) to leave out: "show me new places".
    exclude_ids: list[str] = Field(default_factory=list, max_length=100)


class GroupMember(BaseModel):
    name: str = Field("", max_length=30)
    wish: str = Field("", max_length=200)


class ChatRequest(SearchRequest):
    query: str = Field(min_length=1, max_length=1500)
    provider: Literal["offline", "gemini"] | None = None
    airport_transfer_min: int | None = Field(None, ge=0, le=240)
    airport_reserve_min: int | None = Field(None, ge=0, le=240)
    # None: build a mini-route when the request asks for a walk/route; True/False forces it.
    mini_route: bool | None = None
    # Group mode: each member's own wish; the answer is the best compromise for all of them.
    members: list[GroupMember] | None = Field(None, max_length=MAX_MEMBERS)
    # Where the walk must end by the end of the budget (a place named in the text wins).
    finish_latitude: float | None = Field(None, ge=50.8, le=51.5)
    finish_longitude: float | None = Field(None, ge=71.0, le=71.9)
    finish_label: str | None = Field(None, max_length=120)
    # True: come back to the start ("вернуться к началу").
    finish_loop: bool = False
    # Spare minutes at the finish; None: from the text or the default.
    finish_reserve_min: int | None = Field(None, ge=0, le=60)
    # The walk on screen: a message may edit it ("второе замени", "без кафе").
    route: "RouteContext | None" = None
    # The last list answer: "ещё", "убери второе" refine it (see backend/dialog.py).
    dialog: "DialogState | None" = None

    @model_validator(mode="after")
    def validate_finish(self):
        if (self.finish_latitude is None) != (self.finish_longitude is None):
            raise ValueError("Укажите обе координаты финиша")
        return self


class Point(BaseModel):
    latitude: float = Field(ge=50.8, le=51.5)
    longitude: float = Field(ge=71.0, le=71.9)
    label: str = Field("", max_length=120)


class FinishPoint(Point):
    loop: bool = False


class RouteContext(BaseModel):
    """The walk the client keeps: the plan's session and what happened on the way."""

    query: str = Field("", max_length=1500)
    start_at: str
    start: Point | None = None
    budget: int = Field(ge=10, le=240)
    elapsed: float = Field(0, ge=0, le=480)
    position: Point
    finish: FinishPoint | None = None
    reserve: int = Field(0, ge=0, le=60)
    keep: list[str] = Field(default_factory=list, max_length=3)
    visited: list[str] = Field(default_factory=list, max_length=30)
    excluded: list[str] = Field(default_factory=list, max_length=30)
    flags: list[Literal["indoor", "rest"]] = Field(default_factory=list, max_length=2)
    # The request as read by Gemini for the first plan (session.intent); checked again here.
    intent: dict | None = None
    category: str | None = None
    open_only: bool = False
    strict_amenities: bool = False
    no_steps: bool = False
    max_snap_m: int = Field(MAX_SNAP_M, ge=MIN_SNAP_M, le=MAX_ALLOWED_SNAP_M)
    group_size: int | None = Field(None, ge=1, le=10)

    @model_validator(mode="after")
    def validate_start(self):
        try:
            parse_when(self.start_at)
        except (ValueError, TypeError):
            raise ValueError("Неверная дата: требуется ISO 8601")
        return self


class ReplanRequest(RouteContext):
    """The walk state plus what just happened: a closed stop, a delay, cold, tiredness,
    or plan B taken instead of a stop ("swap")."""

    action: Literal["closed", "delay", "cold", "tired", "swap"]
    stop_id: str | None = Field(None, max_length=200)
    replacement_id: str | None = Field(None, max_length=200)
    delay_min: int = Field(15, ge=5, le=60)


class DialogState(BaseModel):
    """What the conversation is about, kept by the client between messages."""

    query: str = Field("", max_length=1500)
    intent: dict | None = None
    items: list[str] = Field(default_factory=list, max_length=10)
    shown: list[str] = Field(default_factory=list, max_length=120)
    filters: dict = Field(default_factory=dict)


ChatRequest.model_rebuild()


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
        # Server voice; without it the browser's own speech synthesis is used.
        "tts": {"provider": "elevenlabs" if tts.configured() else None},
    }


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    lang: Literal["ru", "kk", "en"] = "ru"


@app.post("/api/tts")
def text_to_speech(req: TTSRequest):
    """MP3 of the text via ElevenLabs; 503 tells the client to use the browser voice."""
    try:
        audio = tts.synthesize(req.text, req.lang)
    except tts.TTSError as exc:
        # Messages are composed in tts.py and never carry the key or provider bodies.
        raise HTTPException(503, str(exc)) from None
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/weather")
def weather():
    now = current_weather()
    air = current_air()
    return {**now, "air": air, "comfort": assess(now, air)}


@app.get("/api/tours")
def tour_list(lang: str = "ru"):
    return {"items": tour_data.cards(tours.tours, lang)}


@app.get("/api/tours/{tour_id}")
def tour_detail(tour_id: str, lang: str = "ru"):
    detail = tours.detail(tour_id, lang)
    if detail is None:
        raise HTTPException(404, "Прогулка не найдена")
    return detail


@app.get("/api/city/audit")
def city_audit():
    audit = cityaudit.load(DATA / "city_audit.json")
    if audit is None:
        raise HTTPException(404, "Аудит города не построен: python scripts/build_city_audit.py")
    return audit


@app.get("/api/events")
def events():
    rows = city.events
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
        "all_snapshot_records": city.events_snapshot,
        "live_collected": len(city.events_live),
        "live_collected_at": max((e.get("collected_at") or "" for e in city.events_live), default=None),
        "live_verified": False,
        "note": "Публикации источников, не проверка фактического проведения или отмены.",
    }


@app.post("/api/search")
def search(req: SearchRequest):
    intent = classifier.classify(req.query) if setting("LLM_PROVIDER", "offline") == "gemini" else None
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
        intent=intent,
        exclude=set(req.exclude_ids),
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


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    when: str | None = None

    @model_validator(mode="after")
    def validate_when(self):
        if self.when:
            try:
                parse_when(self.when)
            except (ValueError, TypeError):
                raise ValueError("Неверная дата: требуется ISO 8601")
        return self


@app.post("/api/pois/{poi_id:path}/ask")
def ask_place(poi_id: str, req: AskRequest):
    if poi_id not in city.byid:
        raise HTTPException(404, "Место не найдено")
    return placeqa.answer(city, poi_id, req.question, req.when)


@app.post("/api/plan")
def plan(req: PlanRequest):
    if req.origin() is None:
        raise HTTPException(422, "Выберите начало маршрута на карте")
    if any(pid not in city.byid for pid in req.poi_ids):
        raise HTTPException(404, "Место не найдено")
    return city.plan(
        req.poi_ids, req.origin(), req.minutes, req.when, req.no_steps, req.max_snap_m
    )


@app.post("/api/replan")
def replan(req: ReplanRequest):
    """Rest of a walk after "здесь закрыто", "+15 минут", "замёрзли" or "устали"."""
    intent = classifier.clean(req.intent) if req.intent else None
    return trip.replan(city, req, intent)


def _interleave(lists):
    """Round-robin merge without duplicates: each named kind of place reaches the top."""
    out, seen = [], set()
    for row in itertools.zip_longest(*lists):
        for p in row:
            if p and p["poi_id"] not in seen:
                seen.add(p["poi_id"])
                out.append(p)
    return out


def route_items(route, lang):
    """Route stops as chat cards, with data-based "why" and "what to do"."""
    items = []
    for stop in route["stops"]:
        item = dict(stop)
        pick = explain_from_data(stop, lang, stop.get("suggested_visit_duration_min"))
        item.update(why=pick["why"], what_to_do=pick["what_to_do"], events=[], warnings=list(stop.get("warnings") or []))
        item["explanation"] = {
            "generated": False, "template": True, "basis": pick["basis"],
            "note": "«Почему» и «что делать» собраны по шаблону из данных места, без генерации; «что делать» — идея, а не проверенный факт.",
        }
        items.append(item)
    return items


def edit_answer(req, provider, lang):
    """The current route changed by the message, or None when the message is a new request."""
    ctx = req.route
    names = [
        ((city.byid[i].get("display_name") or "").split(",")[0], city.byid[i].get("category"))
        for i in ctx.keep
        if i in city.byid
    ]
    said_group = detect_group(req.query) if GROUP_NUMBER.search(req.query) or any(
        w in req.query.casefold() for w in GROUP_WORDS
    ) else None
    ops = read_edit(classifier, req.query, names) if provider == "gemini" else None
    source = "Gemini"
    if ops is None:
        ops, source = read_edit_rules(req.query, len(names), said_group), "по словам запроса"
    if not ops["is_edit"]:
        return None
    intent = classifier.clean(ctx.intent) if ctx.intent else None
    out = trip.edit(city, ctx, ops, intent, lang)
    route = out["plan"]
    group = out["state"]["group_size"]
    if route:
        route["session"] = {
            "query": ctx.query, "start_at": ctx.start_at,
            "start": ctx.start.model_dump() if ctx.start else ctx.position.model_dump(),
            "budget": ctx.budget, "finish": ctx.finish.model_dump() if ctx.finish else None,
            "reserve": ctx.reserve, "category": ctx.category, "group_size": group, "intent": ctx.intent,
        }
    items = route_items(route, lang) if route else []
    start = ctx.start or ctx.position
    spoken = spoken_from_data(items, lang, route, (start.latitude, start.longitude)) if items else out["answer"]
    return {
        "answer": out["answer"],
        "spoken": spoken,
        "items": items,
        "provider_requested": provider,
        "provider_used": "offline",
        "warnings": [],
        "origin": {"latitude": start.latitude, "longitude": start.longitude, "label": None},
        "steps": [{"action": "Правка маршрута", "result": f"разбор: {source}; время, часы работы и пешие отрезки проверены заново"}],
        "mini_route": route,
        "events": [],
        "group": {"size": group, "from_text": True} if group and group > 1 else None,
        "considered": [
            {"label": "Правка маршрута", "value": out["answer"].split(" Новый план")[0] + f" (разбор: {source})"},
            {"label": "Осталось времени", "value": f"{max(0, round(out['state']['remaining_min']))} мин"},
        ],
        "when": ctx.start_at,
        "minutes": ctx.budget,
        "generated_facts": False,
        "generated_text": False,
        "edit": out["changes"],
        "trip_state": out["state"],
        "dialog": {"query": ctx.query, "intent": ctx.intent, "items": [s["poi_id"] for s in items],
                   "shown": [s["poi_id"] for s in items], "filters": {}},
    }


def dialog_answer(req, provider, lang):
    """The last list refined by a follow-up ("ещё", "убери второе", "без кафе"), or None
    when the message is a new interest (then the usual search runs and the state resets)."""
    ctx = req.dialog
    names = [
        ((city.byid[i].get("display_name") or "").split(",")[0], city.byid[i].get("category"))
        for i in ctx.items
        if i in city.byid
    ]
    said_group = detect_group(req.query) if GROUP_NUMBER.search(req.query) or any(
        w in req.query.casefold() for w in GROUP_WORDS
    ) else None
    ops = read_edit(classifier, req.query, names) if provider == "gemini" else None
    source = "Gemini"
    if ops is None:
        ops, source = read_edit_rules(req.query, len(names), said_group), "по словам запроса"
    if not ops["is_edit"]:
        return None
    intent = classifier.clean(ctx.intent) if ctx.intent else None
    origin = req.origin()
    out = dialogue.refine(
        city, ctx, ops, origin=origin, minutes=req.minutes, when=req.when, no_steps=req.no_steps,
        max_snap_m=req.max_snap_m, open_only=req.open_only, strict=req.strict_amenities, intent=intent, lang=lang,
    )
    f = out["dialog"]["filters"]
    in_force = [
        label for on, label in (
            (f.get("exclude_categories"), "без: " + ", ".join(LABELS.get(c, c).lower() for c in f.get("exclude_categories") or [])),
            (f.get("max_walk"), f"до {f.get('max_walk')} мин пешком"),
            (f.get("group_size"), f"компания из {f.get('group_size')}"),
        ) if on
    ]
    considered = [
        {"label": "Уточнение", "value": f"к прошлому ответу (разбор: {source})"},
        {"label": "Запрос", "value": ctx.query or "прежний"},
        {"label": "Уже показано", "value": f"{len(out['dialog']['shown'])} мест — в новых вариантах не повторяются"},
    ]
    if in_force:
        considered.append({"label": "Действует", "value": "; ".join(in_force) + " — до нового запроса"})
    items = out["items"]
    return {
        "answer": out["answer"],
        "spoken": spoken_from_data(items, lang, None, origin) if items else out["answer"],
        "items": items,
        "provider_requested": provider,
        "provider_used": "offline",
        "warnings": [],
        "origin": {"latitude": origin[0], "longitude": origin[1], "label": None} if origin else None,
        "steps": [{"action": "Уточнение подборки", "result": f"разбор: {source}; показанные места исключены, время и часы проверены заново"}],
        "mini_route": None,
        "events": [],
        "group": {"size": f["group_size"], "from_text": True} if f.get("group_size") else None,
        "considered": considered,
        "when": req.when,
        "minutes": req.minutes,
        "generated_facts": False,
        "generated_text": False,
        "dialog": out["dialog"],
    }


SELF_NAMES = {"вы", "я", "мы", "сіз", "мен", "біз", "you", "me", "i", "we"}


def meeting_answer(req, provider, lang):
    """Where a company with different starts should meet, or None when the text names
    fewer than two people with a place."""
    origin = req.origin()
    people, wish, source, lost = None, "", "по словам запроса", []
    read = read_people(req.query) if provider == "gemini" else None
    if read and read["is_meeting"]:
        people, wish, source = [], read["wish"], "Gemini"
        for person in read["people"]:
            is_self = person["name"].casefold() in SELF_NAMES
            spot = next((m for m in city.mentions(person["place"]) if m["point"]), None) if person["place"] else None
            if spot:
                people.append({"name": "Вы" if is_self else person["name"], "self": is_self, "point": spot["point"], "place": spot["label"]})
            elif is_self and origin:
                people.append({"name": "Вы", "self": True, "point": origin, "place": "точка старта"})
            else:
                lost.append(f"{person['name']}: место «{person['place'] or 'не названо'}» не найдено")
    if people is None or len(people) < 2:
        people = people_from_text(city, req.query, origin)
        source = "по словам запроса"
        if not wish:
            names = {tokens(p["name"])[0][0] for p in people if not p["self"] and tokens(p["name"])}
            rest = content_query(without_tokens(req.query, [i for m in city.mentions(req.query) for i in m["tokens"]]))
            rest = " ".join(w for w in rest.split() if w not in names)
            wish = rest if read_intents(rest)[0] else ""
    if len(people) < 2:
        return None
    intent = classifier.classify(wish) if provider == "gemini" and wish else None
    found = meet(city, people, wish, intent, req.when, req.no_steps, req.max_snap_m)
    if found["lost"]:
        text = "Не получилось проложить пеший путь для: " + ", ".join(found["lost"]) + ". Уточните, где они, или выберите точку ближе к дорожкам."
        items = []
    else:
        items = found["items"]
        for item in items:
            pick = explain_from_data(item, lang, item.get("suggested_visit_duration_min"))
            item.update(why=f"Всем недалеко: {meeting_line(item)}. " + pick["why"], what_to_do=pick["what_to_do"], events=[])
            item["explanation"] = {
                "generated": False, "template": True, "basis": ["place_data", "route_time", "opening_hours"],
                "note": "Время пути каждого — по пешеходному графу OSM от его точки; «что делать» — идея, а не проверенный факт.",
            }
        text = (
            f"Удобнее всего встретиться в «{items[0]['display_name'].split(',')[0]}»: {meeting_line(items[0])} пешком."
            + (" Ещё варианты — ниже." if len(items) > 1 else "")
            if items
            else "Места, до которого всем можно дойти пешком и которое открыто к приходу, не нашлось. Попробуйте другое время или уточните, что ищете."
        )
    return {
        "answer": text,
        "spoken": text,
        "items": items,
        "provider_requested": provider,
        "provider_used": "offline",
        "warnings": lost,
        "origin": None,
        "steps": [{"action": "Место встречи", "result": f"{len(people)} чел.; пешие пути от точки каждого по графу OSM; самый долгий путь короче — место выше"}],
        "mini_route": None,
        "events": [],
        "group": {"size": len(people), "from_text": True},
        "considered": [
            {"label": "Кто где", "value": "; ".join(f"{p['name']} — {p['place']}" for p in people) + f" (разбор: {source})"},
            {"label": "Место встречи", "value": wish or "по умолчанию — кафе и кофейни; напишите, если нужно другое"},
            {"label": "Как выбрано", "value": "сначала короче самый долгий путь, потом меньше общий; открыто к приходу"},
        ],
        "meeting": {"people": [{"name": p["name"], "latitude": p["point"][0], "longitude": p["point"][1], "place": p["place"]} for p in people]},
        "when": req.when,
        "minutes": req.minutes,
        "generated_facts": False,
        "generated_text": False,
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    provider = req.provider or setting("LLM_PROVIDER", "offline")
    if provider not in PROVIDERS:
        provider = "offline"
    lang = language(req.query)

    if req.route is not None:
        answer = edit_answer(req, provider, lang)
        if answer:
            return answer
    elif req.dialog is not None and req.dialog.items:
        answer = dialog_answer(req, provider, lang)
        if answer:
            return answer
    if MEET_INTENT.search(req.query):
        answer = meeting_answer(req, provider, lang)
        if answer:
            return answer

    # Where. A place named as the start ("я у Хан Шатыра") wins over the map point; a
    # place named as the goal ("сходить в Хан Шатыр") keeps the map start and becomes
    # a candidate. Without any start, the first named place locates the search.
    origin, origin_label = req.origin(), None
    mentions = city.mentions(req.query)
    # "Через час нужно быть в MEGA": the walk ends there; it is neither the start nor a stop.
    toks = tokens(req.query)
    deadline_said = has_deadline(req.query)
    end = next(
        (
            m
            for m in mentions
            if m["point"]
            and m["role"] != "origin"
            and (finish_cue(toks, m["tokens"][0], m["tokens"][-1]) or (deadline_said and m["role"] == "destination"))
        ),
        None,
    )
    start = next((m for m in mentions if m["role"] == "origin" and m["point"] and m is not end), None)
    if start is None and origin is None:
        start = next((m for m in mentions if m["point"] and m is not end), None)
    if start:
        origin, origin_label = start["point"], start["label"]
        start_note = f"{start['label']} (из текста)" + (
            "" if start["role"] == "origin" else "; ваша точка старта не задана, ищу вокруг этого места"
        )
    elif origin:
        start_note = "точка на карте или выбранный ориентир"
    else:
        start_note = "не задан — пешая доступность не проверена"
    destinations = [m for m in mentions if m is not start and m is not end and m["poi_ids"] and m["role"] != "origin"]
    # The start itself is not what the user looks for: "Я у Экспо" must not return EXPO;
    # nor is the finish ("нужно быть в MEGA" asks for a coffee on the way, not for MEGA).
    cut = (start["tokens"] if start else []) + (end["tokens"] if end else [])
    effective_query = without_tokens(req.query, cut) if cut else req.query

    finish, finish_note = None, None
    if end:
        finish = {"latitude": end["point"][0], "longitude": end["point"][1], "label": end["label"], "loop": False}
        finish_note = f"{end['label']} (из текста)"
    elif origin and (wants_loop(req.query) or req.finish_loop):
        finish = {"latitude": origin[0], "longitude": origin[1], "label": origin_label or "Точка старта", "loop": True}
        finish_note = "возврат к началу " + ("(из текста)" if wants_loop(req.query) else "(из условий прогулки)")
    elif req.finish_latitude is not None:
        finish = {
            "latitude": req.finish_latitude, "longitude": req.finish_longitude,
            "label": req.finish_label or "Финиш", "loop": False,
        }
        finish_note = f"{finish['label']} (из условий прогулки)"
    if finish:
        effective_query = LOOP.sub(" ", effective_query)
        effective_query = without_tokens(effective_query, finish_filler(effective_query))
    if cut or finish:
        # Punctuation left over from cut words ("Я у , к : в , кофе").
        effective_query = re.sub(r"\s+", " ", re.sub(r"(?:^|\s)[,.:;!?—-]+(?=\s|$)", " ", effective_query)).strip()

    # How long and when.
    flight = wants_flight(req.query)
    minutes, budget_note = req.minutes, "из условий прогулки"
    parsed, note = parse_budget(req.query, prefer_hours=flight)
    if parsed:
        minutes, budget_note = parsed, note
    when, when_note = req.when, ("из условий прогулки" if req.when else "сейчас")
    if not req.when:
        text_when, note = parse_time_of_day(req.query)
        when = text_when or when
        when_note = note or when_note
    reserve, reserve_note = 0, None
    if finish:
        deadline, note = parse_deadline(req.query, parse_when(when))
        if deadline is not None:
            minutes, budget_note = max(10, min(240, deadline)), note
        said = parse_reserve(req.query)
        if req.finish_reserve_min is not None:
            reserve, reserve_note = req.finish_reserve_min, "из условий прогулки"
        elif said is not None:
            reserve, reserve_note = said, "из текста"
        elif not finish["loop"]:
            reserve, reserve_note = DEFAULT_FINISH_RESERVE_MIN, "допущение по умолчанию"
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
    # What is asked for, read by Gemini from the request without the start and the finish;
    # without the model (no key, quota, network) the word rules read it.
    intent = classifier.classify(effective_query) if provider == "gemini" and content_query(effective_query) else None

    def asked():
        """(categories, amenities) the request asks for."""
        return (set(intent["categories"]), list(intent["amenities"])) if intent else read_intents(effective_query)

    # A new interest drops an old filter that contradicts it: with the "Кафе" chip on,
    # "хочу в музей" searches museums and the chip is switched off in the interface.
    category, cleared_category = req.category, None
    if category and asked()[0] and category not in asked()[0]:
        category, cleared_category = None, req.category

    route_mode = (
        True
        if finish and origin
        else req.mini_route
        if req.mini_route is not None
        else bool(ROUTE_INTENT.search(req.query))
    )
    members = clean_members([m.model_dump() for m in req.members or []])
    if len(members) < MIN_MEMBERS or all(m.neutral for m in members):
        members = []
    group = len(members) or (req.group_size if req.group_size and req.group_size > 1 else detect_group(req.query))
    event_intent = bool(EVENT_INTENT.search(req.query))
    cover = (
        []
        if category
        else [(LABELS[c].lower(), c) for c in intent["categories"]] if intent and intent["combine"]
        else [] if intent
        else cover_groups(req.query)
    )
    nearby = bool(origin) and not route_mode and not members and wants_nearby(req.query)
    # With a finish more candidates are fetched: those off the way are dropped below.
    limit = 60 if finish and origin else 24 if route_mode and origin else 9

    weather = current_weather()
    comfort = assess(weather, current_air(), when)

    def gather(max_walk):
        trace = Trace()

        def find(category, n):
            return city.search(
                effective_query, category, origin, minutes, when, req.open_only, req.no_steps,
                n, req.strict_amenities, distinct_names=True, max_snap_m=req.max_snap_m,
                group_size=group, max_walk_min=max_walk, comfort=comfort, trace=trace, intent=intent,
                exclude=set(req.exclude_ids),
            )

        if cover:
            # "музей и кофе": candidates of each named kind, so neither crowds the other out.
            return _interleave([find(cat, max(8, limit // len(cover))) for _, cat in cover]), trace
        return find(category, limit), trace

    def evidenced(items):
        # Places whose requested amenities (outlets, quiet…) are confirmed or supported.
        return [p for p in items if p.get("evidence") and all(k in ("confirmed", "supported") for k in p["evidence"].values())]

    walk_note = None
    if members:
        trace = Trace()
        pool = group_pool(
            city, members, origin, minutes, when, req.open_only, req.no_steps, limit, req.strict_amenities,
            req.max_snap_m, trace,
        )
    else:
        pool, trace = gather(NEARBY_WALK_MIN if nearby else None)
    if nearby:
        walk_note = f"до {NEARBY_WALK_MIN} мин пешком — вы написали, что нужно рядом"
        relaxed = None
        if len(pool) < 3:
            relaxed = "подходящих мест меньше трёх"
        elif any(p.get("evidence") for p in pool) and not evidenced(pool[:3]):
            relaxed = "нет мест с подтверждёнными удобствами из запроса"
        if relaxed:
            wider, wider_trace = gather(NEARBY_RELAXED_MIN)
            if len(wider) > len(pool) or evidenced(wider[:3]):
                pool, trace = wider, wider_trace
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
        # Kinds are read from the text without the named place: "Столичный цирк" names
        # a circus, it does not also ask for entertainment in general.
        only_leads = (
            not route_mode and not content_query(req.query, skip)
            and not read_intents(without_tokens(req.query, sorted(skip)))[0]
        )
        pool = leads + ([] if only_leads else [p for p in pool if p["poi_id"] not in lead_ids])

    # Published events the walk can catch: shown when asked for, or when one is a short walk away.
    events = [
        e
        for e in city.events_nearby(
            origin, when, minutes, req.no_steps, req.max_snap_m,
            limit=12 if event_intent else 3, reachable_only=bool(origin), keep_venues={p["poi_id"] for p in leads},
        )
        if (event_fits(e, req.query) if event_intent else e["walk_min"] is not None and e["walk_min"] <= 20)
    ][:3]
    if event_intent:
        # Venues of matching events lead the candidates so the answer can point to them.
        known = {p["poi_id"] for p in pool}
        venues = [
            city.venue_candidate(e["venue_poi_id"], origin, minutes, when, req.no_steps, req.max_snap_m)
            for e in events
            if e["venue_poi_id"] and e["venue_poi_id"] not in known
        ]
        pool = [v for v in venues if v] + pool
    route = None
    if route_mode and origin and finish:
        if end:
            pool = [p for p in pool if p["poi_id"] not in set(end["poi_ids"])]
        pool = toward(pool, origin, finish, minutes - reserve)
        if cover:
            # Each named kind keeps its place among the first candidates after the re-sort.
            kinds = [cat for _, cat in cover]
            pool = _interleave([[p for p in pool if p.get("category") == cat] for cat in kinds]
                               + [[p for p in pool if p.get("category") not in kinds]])
        # "По пути выпить кофе" is one stop; "маршрут до MEGA: музей и кофе" — a walk.
        wanted_stops = (
            3
            if ROUTE_INTENT.search(req.query) or req.mini_route
            else len(cover)
            if cover
            else 1
            if asked()[0] or content_query(effective_query)
            else 2
        )
        route = city.mini_route(
            pool, origin, minutes, when, req.no_steps, req.max_snap_m,
            cover=[cat for _, cat in cover], finish=finish, reserve=reserve,
            sizes=tuple(range(wanted_stops, 0, -1)),
        )
        if route is None:
            route = city.direct_route(origin, finish, minutes, reserve, req.no_steps, req.max_snap_m)
        if route is None:
            warnings.append(f"До «{finish['label']}» не найден пеший путь по графу OSM.")
    elif route_mode and origin:
        route = city.mini_route(
            pool, origin, minutes, when, req.no_steps, req.max_snap_m,
            cover=[cat for _, cat in cover],
        )
    start_at = parse_when(when)
    if route:
        stamp_finish(route, start_at)
        add_backups(city, route, origin, start_at, minutes, reserve, req.no_steps, req.max_snap_m)
        # What the client sends back to re-plan on the go ("здесь закрыто", "устали").
        route["session"] = {
            "query": effective_query,
            "start_at": start_at.isoformat(timespec="minutes"),
            "start": {"latitude": origin[0], "longitude": origin[1]},
            "budget": minutes,
            "finish": {k: finish[k] for k in ("latitude", "longitude", "label", "loop")} if finish else None,
            "reserve": reserve,
            "category": category,
            "group_size": group or None,
            # Re-planning searches the same wish without asking the model again.
            "intent": intent,
        }
    candidates = pool[:9] if not (route and route.get("finish") and not route["stops"]) else []
    if route:
        # Route stops may rank below the top 9; the model must see all of them.
        shown = {p["poi_id"] for p in candidates}
        candidates += [
            next(p for p in pool if p["poi_id"] == s["poi_id"])
            for s in route["stops"]
            if s["poi_id"] not in shown
        ]
    context = {
        "budget_minutes": minutes,
        "when": when,
        "steps_excluded": req.no_steps,
        "weather": weather,
        "flight_context": flight_context,
    }
    if comfort["applies"] and comfort["factors"]:
        context["comfort"] = [{"factor": f["code"], **f["params"]} for f in comfort["factors"]]
    if group:
        context["group_size"] = group
    if members:
        context["group_members"] = [{"name": m.name, "wish": m.wish or None} for m in members]
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
    if route and route.get("finish"):
        f = route["finish"]
        context["finish"] = {
            "label": f["label"],
            "back_to_start": f["loop"],
            "walk_from_last_stop_min": round(f["leg"]["duration_min"]),
            "arrival_after_min": round(f["arrival_offset_min"]),
            "arrival_clock": f["arrival_at"][11:16],
            "reserve_min": f["reserve_min"],
        }
    # Which way each place lies from the start: spoken summaries need it more than a map line.
    for c in candidates:
        c["direction"] = compass(origin, (c.get("latitude"), c.get("longitude")), lang) if origin else None
    if candidates:
        picks, summary, warning, spoken_ai = select_spoken(provider, req.query, candidates, context)
    else:
        # Only the way to the finish: there is nothing for the model to choose.
        picks, summary, warning, spoken_ai = [], None, None, None
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
    # Short text for TTS / screen-reader users: the model's summary, or one built from the data.
    spoken = spoken_ai if generated and spoken_ai else spoken_from_data(selected, lang, route, origin)
    if route and route.get("finish") and not route["stops"]:
        spoken = finish_text(route, start_at)
    chosen = {p["poi_id"] for p in selected}
    for item in pool[:9]:
        if item["poi_id"] in chosen:
            continue
        weather_shift = comfort["applies"] and comfort["score_level"] >= 1 and item.get("comfort") == "outdoor"
        trace.reject(
            item,
            "outdoor_weather" if weather_shift else "ranked_lower",
            item.get("search_score", 0) + 1,
            walk=round((item.get("route") or {}).get("duration_min") or 0),
        )
    text = (
        summary
        or OFFLINE_SUMMARY.get(lang, OFFLINE_SUMMARY["ru"])
        if selected
        else "Подходящих мест с этими условиями не найдено. Измените время, точку старта или фильтры. Неподтверждённые свойства не считаются известными."
    )
    if selected and not origin:
        text += " Выберите начало на карте, чтобы проверить пешую доступность и построить маршрут."
    if route and route.get("finish"):
        text = finish_text(route, start_at) + (" " + text if selected else "")
    elif route:
        text = (
            f"Мини-маршрут: {len(route['stops'])} места за ~{round(route['total_duration_min'])} мин "
            f"из {minutes} (пешком ~{round(route['walk_duration_min'])} мин). " + text
        )
    if members:
        text = (
            f"Подбор для компании из {group} человек: учтено желание каждого, важнее тот, кому подходит меньше всего. "
            + text
        )
    elif group:
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
    if members and selected:
        gaps = [
            f["name"]
            for f in selected[0]["group_fit"]
            if not any(
                next(x for x in item["group_fit"] if x["name"] == f["name"])["level"] != "none" for item in selected
            )
        ]
        if gaps:
            warnings.append(
                "Не всем сразу: " + ", ".join(gaps) + " — под желание не нашлось подходящего места в этих условиях."
            )
        elif all(item["group_worst"] < 0.4 for item in selected):
            warnings.append("Одного места на всех нет: у каждого варианта кому-то подходит слабо, см. «Каждому».")
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
    preferred, wanted = asked()
    comfort_note = comfort_summary(comfort, weather_widened(preferred, comfort, category))
    considered = [
        {"label": "Старт", "value": start_note},
        {"label": "Время", "value": f"{minutes} мин — {budget_note}" + (" минус резервы на вылет" if flight_context else "")},
        {"label": "Когда", "value": when_note},
    ]
    if walk_note:
        considered.append({"label": "Пешком до места", "value": walk_note})
    if intent:
        considered.append({"label": "Понял запрос", "value": (intent["note"] or "разобран Gemini") + " (разбор: Gemini)"})
    elif provider == "gemini" and content_query(effective_query):
        considered.append({"label": "Понял запрос", "value": "по словам запроса (Gemini для разбора недоступен)"})
    if cover:
        considered.append({"label": "Ищу вместе", "value": " + ".join(label for label, _ in cover)})
    elif preferred:
        considered.append({"label": "Категории", "value": ", ".join(LABELS[c].lower() for c in sorted(preferred))})
    if wanted:
        considered.append({"label": "Удобства из запроса", "value": ", ".join(ATTR_LABEL[a] for a in wanted)})
    if destinations:
        considered.append({"label": "Место из запроса", "value": ", ".join(m["label"] for m in destinations[:2])})
    if finish:
        considered.append({"label": "Финиш", "value": finish_note})
        if reserve_note:
            considered.append({"label": "Запас у финиша", "value": f"{reserve} мин — {reserve_note}"})
    if comfort_note:
        considered.append({"label": "Погода и воздух", "value": comfort_note})
    if cleared_category:
        considered.append({
            "label": "Фильтр снят",
            "value": f"«{LABELS.get(cleared_category, cleared_category)}» — запрос о другом",
        })
    if members:
        considered.append(
            {"label": "Компания", "value": f"{group} чел.: " + "; ".join(f"{m.name} — {m.wish or 'без пожеланий'}" for m in members)}
        )
    elif group:
        considered.append(
            {"label": "Компания", "value": f"{group} чел." + (" (из текста)" if not (req.group_size and req.group_size > 1) else "")}
        )
    filters = [
        label
        for on, label in (
            (category, LABELS.get(category or "", "").lower()),
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
    if route_mode and origin and not finish:
        considered.append(
            {"label": "Мини-маршрут", "value": "включён переключателем" if req.mini_route else "запрос про прогулку или маршрут"}
        )
    return {
        "answer": text,
        "spoken": spoken,
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
                    "action": "Маршрут до финиша" if route.get("finish") else "Мини-маршрут",
                    "result": (
                        f"{len(route['stops'])} места, {round(route['total_duration_min'])} из {minutes} мин: "
                        f"порядок и пешие отрезки по графу OSM, часы работы проверены на момент прихода"
                        + (
                            f"; последний отрезок до «{route['finish']['label']}» и запас {route['finish']['reserve_min']} мин учтены"
                            if route.get("finish")
                            else ""
                        )
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
        "group": (
            {"size": group, "from_text": False, "members": [{"name": m.name, "wish": m.wish} for m in members]}
            if members
            else {"size": group, "from_text": not (req.group_size and req.group_size > 1)}
            if group
            else None
        ),
        "considered": considered,
        "when": when,
        "minutes": minutes,
        "generated_facts": False,
        "generated_text": generated,
        "flight_context": flight_context,
        "weather": weather,
        "comfort": {**comfort, "air": current_air()},
        "funnel": trace.funnel(len(selected)),
        "rejected": trace.top(6, skip=chosen),
        # A new search starts a new dialogue state: old refinements and shown places go.
        "dialog": {
            "query": effective_query,
            "intent": intent,
            "items": [p["poi_id"] for p in selected],
            "shown": [p["poi_id"] for p in selected],
            "filters": {},
        },
        "cleared_category": cleared_category,
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

    class EmojiFiles(StaticFiles):
        """Noto emoji images (named by code point, no hash): cached for a week."""

        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=604800"
            return response

    # A fresh build has its own copy; the committed dist does not (see .gitignore).
    emoji_dir = next((d for d in (dist / "emoji", ROOT / "frontend" / "public" / "emoji") if d.exists()), None)
    if emoji_dir:
        app.mount("/emoji", EmojiFiles(directory=emoji_dir), name="emoji")

    # Installable app (PWA): icons, the manifest and the service worker from the build root.
    if (dist / "icons").exists():
        app.mount("/icons", EmojiFiles(directory=dist / "icons"), name="icons")

    if (dist / "manifest.webmanifest").exists():

        @app.get("/manifest.webmanifest", include_in_schema=False)
        def manifest():
            return FileResponse(dist / "manifest.webmanifest", media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})

    if (dist / "sw.js").exists():

        @app.get("/sw.js", include_in_schema=False)
        def service_worker():
            # Always revalidated: a new deploy must reach installed apps on their next start.
            return FileResponse(dist / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/")
    def index():
        # Always revalidate the page: after a rebuild it must point at the new hashed bundle.
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
