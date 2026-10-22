import itertools
import math
import json
import re
from datetime import timedelta
import numpy as np
from .settings import DATA
from .index import SearchIndex
from .routing import MAX_SNAP_M, Router, meters
from .comfort import exposure
from .hours import closure, hours_status, parse_when
from .query import STOP_WORDS, content_query, fold, mention_role, tokens

LABELS = {
    "food_drink": "Кафе и рестораны",
    "nature": "Парки и природа",
    "culture": "Музеи и культура",
    "sightseeing": "Достопримечательности",
    "children": "Детям",
    "entertainment": "Развлечения",
    "quiet_spaces": "Тихие пространства",
    "sport": "Спорт",
    "shopping": "Магазины",
    "nightlife": "Вечером",
    "accommodation": "Отели",
    "wellness": "Отдых",
    "infrastructure": "Инфраструктура",
    "other": "Другие места",
}
ART_INTENT = (
    r"рисова|рисун|порисов|живопис|скетч|этюд|пленэр|художеств|изостуд|акварел|"
    r"сурет\s*сал|суретш|\bdraw|\bpaint|sketch|watercolou?r"
)
# Text that marks a place as about art, not just "scenic" or a cooking master class.
ART_PLACE = re.compile(r"художеств|искусств|картин|\bарт\b|арт-|\bart\b|галере|gallery|сурет", re.I)
ART_SUBCATEGORIES = {"gallery", "arts_centre"}
# Drawing outdoors ("порисовать на природе"): parks before galleries.
ART_OUTDOORS = r"природ|на\s+улиц|пленэр|этюд|на\s+свеж\w+\s+воздух|в\s+парк|табиғат|outdoor|outside|plein\s+air"
# A kind of place named in the request: its category, and that kind ranks first in it
# ("хочу в театр" is a theatre, not any culture place nearby).
KIND_INTENTS = [
    (r"театр|спектакл|\bопер(?:а|у|ы|е|ой|ный|ного)\b|\bбалет|филармон|\btheat|\bopera\b|\bballet", ["culture"], {"theatre", "concert_hall"}),
    (r"\bкино\b|кинотеатр|\bфильм|\bcinema|\bmovie|киноға", ["entertainment"], {"cinema"}),
    (r"\bцирк|\bcircus", ["entertainment"], {"circus"}),
]
ALIASES = [
    # Food: venues and words for eating ("покушать корейскую кухню"); not "еду" = "I am going".
    (r"каф|коф|ресторан|поесть|покушать|кушать|поужина|пообеда|позавтрака|\bобед|\bужин|\bзавтрак|перекус|\bеда\b|\bеды\b|\bеду\s+(?:вкусн|попробова)|кухн|тамақ|асхана|cafe|coffee|restaurant|\bfood|\beat\b|cuisine|lunch|dinner|breakfast", ["food_drink"]),
    (r"парк|прогул|погуля|серуен|саябақ|park", ["nature", "sightseeing"]),
    (r"музе|выстав|мұражай|museum", ["culture"]),
    (r"реб[её]н|деть|детск|бала|kids", ["children", "entertainment", "culture"]),
    (r"турис|достопр|посмотр|көрікті|tourist", ["sightseeing", "culture"]),
    (r"ноч|түн|\bnight", ["nightlife", "entertainment"]),
    # Drawing and painting: no art studios in the data, so galleries and art centres
    # (some hold master classes) and scenic parks for sketching outdoors.
    (ART_INTENT, ["culture", "nature"]),
    *((rx, cats) for rx, cats, _ in KIND_INTENTS),
]
# "Something unusual" names no category; used only when nothing more specific is asked
# ("түнде қызықты" stays a night request).
UNUSUAL = (
    r"необычн|интересн|уникальн|удивит|креативн|unusual|interesting|unique|қызықты|ерекше",
    ["sightseeing", "culture", "entertainment"],
)
# Landmarks recognised in the request text (keys of data/landmarks.json).
LANDMARK_PATTERNS = {
    "mega": r"\bmega(?:\s+silk\s+way)?\b|\bмег(?:а|и|е|у|ой)(?:\s+силк\s+уэй)?\b",
    "bayterek": r"байтерек|бәйтерек|bayterek|baiterek",
    "museum": r"национальн.{0,8}музе|ұлттық.{0,8}мұражай",
    "opera": r"астана опера|astana opera",
    "expo": r"\bexpo\b|\bэкспо\b",
    "alem": r"alem\.ai|алем",
}
COFFEE_PLACES = {"coffee_shop", "cafe", "bakery", "confectionery", "cafe_confectionery"}
# Names that are a kind of place, not one place: "Столовая", "Кофейня", "Сквер".
GENERIC_NAMES = {
    "сквер", "фонтан", "аллея", "бульвар", "площадь", "набережная", "магазин", "аптека",
    "киоск фастфуда", "киоск быстрого питания", "точка быстрого питания", "киоск самсы",
    "буфет", "донерная", "шашлычная", "шаверма", "шашлычок", "игровая комната",
    "детская площадка", "спортивная площадка", "кафе", "кофейня", "столовая", "бар",
}


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def event_key(e):
    """Same show listed twice (snapshot and live collection): same title on the same day."""
    return (name_key(e.get("event_name") or ""), str(e.get("event_start") or "")[:10])


LIVE_EVENTS_FILE = "events_live.jsonl"


def load_events():
    """(all events, live-collected ones, snapshot size): newer live records take over from the snapshot."""
    snapshot = read_jsonl(DATA / "events.jsonl")
    live = read_jsonl(DATA / LIVE_EVENTS_FILE)
    seen = {event_key(e) for e in live}
    return [e for e in snapshot if event_key(e) not in seen] + live, live, len(snapshot)


def name_key(text):
    return " ".join(t for t, _, _ in tokens(text))


def read_intents(q):
    """Categories and amenities the request asks for (the same rules rank and explain)."""
    query = q.casefold()
    preferred = set()
    for pattern, cats in ALIASES:
        if re.search(pattern, query):
            preferred.update(cats)
    if not preferred and re.search(UNUSUAL[0], query):
        preferred.update(UNUSUAL[1])
    food_intent = bool(re.search(ALIASES[0][0], query))
    # "кафе" alone narrows to food; "кафе и музей" keeps every named category.
    other_category = any(re.search(rx, query) for rx, _ in ALIASES[1:])
    if food_intent and not other_category and not re.search(r"\bили\b|\bзатем\b|сосын|немесе", query):
        preferred = {"food_drink"}
    wanted = [a for a, rx in REVIEW_INTENTS.items() if re.search(rx, query)]
    if "quiet" in wanted and not preferred:
        preferred.update(["food_drink", "quiet_spaces", "nature"])
    if "laptop_work" in wanted and not preferred:
        preferred.update(["food_drink", "quiet_spaces"])
    return preferred, wanted
def weather_widened(preferred, comfort, category):
    """In bad weather a plain walk request ("прогулка", "парк") also considers museums and galleries."""
    return bool(
        comfort
        and comfort.get("applies")
        and comfort["score_level"] >= 1
        and not category
        and preferred
        and preferred <= {"nature", "sightseeing"}
    )


DEFAULT_STAY = {
    "food_drink": 35,
    "nature": 25,
    "culture": 45,
    "sightseeing": 20,
    "children": 35,
    "entertainment": 40,
    "shopping": 40,
    "sport": 45,
}
# Shortest visit still worth recommending when the budget is tight: a coffee,
# a lap of a square, a quick look at a monument. Museums and shows need more.
MIN_STAY = {
    "food_drink": 15,
    "nature": 15,
    "sightseeing": 10,
    "culture": 30,
    "children": 20,
    "entertainment": 30,
    "shopping": 15,
    "sport": 30,
    "nightlife": 30,
    "quiet_spaces": 20,
    "wellness": 45,
}
VISIBLE = (
    "poi_id",
    "display_name",
    "name_ru",
    "name_kk",
    "name_en",
    "latitude",
    "longitude",
    "address",
    "category",
    "subcategory",
    "short_description",
    "website",
    "phone",
    "opening_hours",
    "opening_hours_by_day",
    "last_updated_at",
    "hours_verified_at",
    "rating",
    "ratings_count",
    "power_outlets",
    "quiet_place",
    "wifi_available",
    "playground",
    "interactive_exhibits",
    "wheelchair_accessible",
    "free_entry",
    "adult_ticket_price",
    "child_ticket_price",
    "estimated_visit_budget",
    "suggested_visit_duration_min",
    "reservation_required",
    "booking_required",
    "access_restrictions",
    "age_restrictions",
    "temporary_closure",
    "operational_status",
    "sources",
    "pricing",
    "visit_rules",
    "closure_assessment",
    "_provider_closure",
    "subcategory_label",
    "semantic_attributes",
    "provider_attributes",
    "source_record_ids",
    "rating_bayesian",
    "quiet_place_scope",
    "power_outlets_scope",
    "indoor_outdoor",
    "laptop_friendly",
    "grounded_description",
    "description_type",
    "children_facilities",
    "entrance_accessible",
    "wheelchair_accessibility_scope",
    "opening_hours_evidence",
    "standard_ticket_price",
    "ticket_options",
    "ramps",
    "elevators",
)


def confirmed_signal(p, key):
    scope = str(p.get(key + "_scope") or "").casefold()
    return p.get(key) is True and not any(
        x in scope for x in ["single", "testimonial", "review", "отзыв"]
    )


# Query intents that review evidence (data/review_signals.jsonl) can answer.
REVIEW_INTENTS = {
    "power_outlets": r"розет|қуат|outlet|заряд",
    "quiet": r"тих|спокой|тыныш|quiet",
    "laptop_work": r"ноутбук|поработ|работать|учиться|позаниматься|laptop|коворк",
    "wifi": r"wi-?fi|вай.?фай|интернет",
    "kids": r"реб[её]н|\bдет(?:и|ей|ям|ьми|ск)|kids|балалар|\bбала\b",
    "interactive": r"интерактив|\bvr\b|мастер.?класс",
    "accessibility": r"коляск|пандус|инвалид|без ступен|wheelchair",
    "view": r"панорам|смотров|красив.{0,10}вид|вид на",
}
# Dataset fields that already confirm the same property.
CONFIRMED_FIELD = {
    "power_outlets": "power_outlets",
    "quiet": "quiet_place",
    "laptop_work": "laptop_friendly",
    "wifi": "wifi_available",
    "kids": "playground",
    "interactive": "interactive_exhibits",
    "accessibility": "wheelchair_accessible",
    "view": "scenic_view",
}
ATTR_LABEL = {
    "power_outlets": "розетки",
    "quiet": "тихая обстановка",
    "laptop_work": "удобно работать с ноутбуком",
    "wifi": "Wi-Fi",
    "kids": "удобно с детьми",
    "interactive": "интерактив",
    "accessibility": "доступность для коляски",
    "view": "красивый вид",
}
# Search terms appended to a POI document when reviews support the attribute.
REVIEW_TERMS = {
    "power_outlets": "розетка зарядка по отзывам",
    "quiet": "тихо спокойно по отзывам",
    "laptop_work": "ноутбук поработать по отзывам",
    "wifi": "Wi-Fi интернет по отзывам",
    "kids": "с детьми детская по отзывам",
    "interactive": "интерактив по отзывам",
    "accessibility": "пандус коляска лифт по отзывам",
    "view": "вид панорама по отзывам",
}
# Published 2GIS venue attributes that indicate seating for a company.
GROUP_FEATURES = ("VIP-зал", "Кабинки", "Проведение банкетов", "Корпоративные обеды")


def group_features(p):
    attrs = set(p.get("semantic_attributes") or [])
    return [f for f in GROUP_FEATURES if f in attrs]


def group_cost(p, size):
    """Rough total for the group from a published per-person price; None when unknown."""
    for key, basis in (
        ("adult_ticket_price", "adult_ticket"),
        ("standard_ticket_price", "standard_ticket"),
    ):
        price = p.get(key) or {}
        if price.get("amount") is not None:
            return {"size": size, "amount": price["amount"] * size, "currency": price.get("currency") or "KZT", "basis": basis}
    budget = p.get("estimated_visit_budget") or {}
    if budget.get("amount_min") is not None:
        return {"size": size, "amount": budget["amount_min"] * size, "currency": budget.get("currency") or "KZT", "basis": "average_check"}
    if p.get("free_entry") is True:
        return {"size": size, "amount": 0, "currency": "KZT", "basis": "free_entry"}
    return None


REVIEW_BOOST = {"supported": 0.3, "single_mention": 0.08, "mixed": 0.0, "contradicted": -0.35}


def mentions(n):
    return f"{n} упоминани" + ("е" if n % 10 == 1 and n % 100 != 11 else "я" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "й")


def evidence(p, attr, signals):
    """('confirmed' | review status | 'unknown', review signal or None)."""
    field = CONFIRMED_FIELD[attr]
    if confirmed_signal(p, field) if attr in ("power_outlets", "quiet") else p.get(field) is True:
        return "confirmed", None
    s = (signals or {}).get(attr)
    return (s["status"], s) if s else ("unknown", None)


def finish_info(finish, leg, elapsed, minutes, reserve):
    """The end of a walk: when the walker gets there and how much time is left over."""
    arrival = round(elapsed + leg["duration_min"], 1)
    return {
        "label": finish.get("label") or "Финиш",
        "latitude": finish["latitude"],
        "longitude": finish["longitude"],
        "loop": bool(finish.get("loop")),
        "leg": leg,
        "arrival_offset_min": arrival,
        "reserve_min": reserve,
        "slack_min": round(minutes - arrival, 1),
        "fits": arrival + reserve <= minutes,
    }


def toward(pool, origin, finish, minutes):
    """Candidates on the way to the finish. A stop far off the line start -> finish
    cannot fit, and of two equal places the one with the smaller detour ranks higher.
    Straight lines times 1.15 approximate the walking network (Байтерек -> MEGA: 1.14)."""
    goal = (finish["latitude"], finish["longitude"])
    direct = meters(origin, goal)
    out = []
    for p in pool:
        point = (p["latitude"], p["longitude"])
        way = meters(origin, point) + meters(point, goal)
        stay = min(p.get("suggested_visit_duration_min") or 30, MIN_STAY.get(p.get("category"), 15))
        if way * 1.15 / 75 + stay > minutes:
            continue
        detour = (way - direct) / max(1.0, minutes * 75)
        out.append((p.get("search_score", 0) - 0.6 * detour, p))
    out.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in out]


class City:
    def __init__(self):
        self.pois = [
            json.loads(l) for l in (DATA / "pois.jsonl").open(encoding="utf-8")
        ]
        self.byid = {p["poi_id"]: p for p in self.pois}
        self.id_aliases = (
            json.loads((DATA / "poi_aliases.json").read_text(encoding="utf-8"))
            if (DATA / "poi_aliases.json").exists()
            else {}
        )
        for old, new in self.id_aliases.items():
            if new in self.byid:
                self.byid[old] = self.byid[new]
        signals_path = DATA / "review_signals.jsonl"
        self.review_signals = {}
        if signals_path.exists():
            with signals_path.open(encoding="utf-8", newline="\n") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        self.review_signals[row["poi_id"]] = row
        for p in self.pois:
            signals = (self.review_signals.get(p["poi_id"]) or {}).get("signals") or {}
            p["_review_labels"] = [
                REVIEW_TERMS[a] for a, sig in signals.items() if sig["status"] == "supported"
            ]
        self.index = SearchIndex(self.pois)
        self.router = Router()
        # Place names a request can mention ("я у Хан Шатыра", "сходить в Столичный цирк").
        generic = {
            name_key(n)
            for n in [*GENERIC_NAMES, *LABELS.values(), *(p.get("subcategory_label") for p in self.pois)]
            if n
        }
        self.names = {}
        for p in self.pois:
            if not p.get("recommendation_eligible", True):
                continue
            key = name_key((p.get("display_name") or "").split(",")[0])
            if len(key.replace(" ", "")) < 5 or key in generic or key in STOP_WORDS:
                continue
            self.names.setdefault(key, []).append(p)
        docs_path = DATA / "venue_policy_sources.jsonl"
        self.venue_docs = (
            {
                d["source_id"]: d
                for d in (json.loads(l) for l in docs_path.open(encoding="utf-8"))
            }
            if docs_path.exists()
            else {}
        )
        self.landmarks = json.loads(
            (DATA / "landmarks.json").read_text(encoding="utf-8")
        )
        self.events, self.events_live, self.events_snapshot = load_events()

    def public(self, p, when=None, stay=0):
        out = {k: p.get(k) for k in VISIBLE}
        if p.get("quiet_place") is True and not confirmed_signal(p, "quiet_place"):
            out["quiet_place_claim"] = True
            out["quiet_place"] = None
        if p.get("entrance_accessible") is True and "entrance" in str(
            p.get("wheelchair_accessibility_scope") or ""
        ):
            out["wheelchair_accessible"] = None
        refs = set(
            (p.get("pricing") or {}).get("price_document_ids", [])
            + (p.get("visit_rules") or {}).get("policy_document_ids", [])
        )
        out["linked_venue_documents"] = [
            self.venue_docs[i] for i in refs if i in self.venue_docs
        ]
        out["display_name"] = p.get("display_name") or p.get("name") or "Без названия"
        out["category_label"] = LABELS.get(p.get("category"), "Другое")
        out["hours_status"] = hours_status(p, when, stay)
        out["suggested_visit_duration_min"] = p.get(
            "suggested_visit_duration_min"
        ) or DEFAULT_STAY.get(p.get("category"), 30)
        out["visit_duration_estimated"] = True
        reviews = self.review_signals.get(p["poi_id"])
        out["review_signals"] = reviews["signals"] if reviews else None
        out["reviews_considered"] = reviews["reviews_considered"] if reviews else None
        return out

    def mentions(self, message):
        """Landmarks and named places in the text, each with its role in the request:
        'origin' ("я у Хан Шатыра"), 'destination' ("сходить в Хан Шатыр") or None.

        Names match whole words; the last word may carry a case ending ("Байтерека",
        "Хан Шатырға"). Generic names ("Кофейня", "Сквер") are not places.
        """
        toks = tokens(message)
        found, taken = [], set()
        for key, pattern in LANDMARK_PATTERNS.items():
            m = re.search(pattern, message, re.I)
            idx = [i for i, (_, s, e) in enumerate(toks) if m and s < m.end() and e > m.start()]
            if not idx or taken & set(idx):
                continue
            lm = self.landmarks[key]
            found.append(
                {"kind": "landmark", "key": key, "label": lm["name"], "point": (lm["lat"], lm["lon"]),
                 "poi_ids": [], "tokens": idx, "role": mention_role(toks, idx[0], idx[-1])}
            )
            taken.update(idx)
        i = 0
        while i < len(toks):
            hit = None
            for n in range(min(5, len(toks) - i), 0, -1):
                span = list(range(i, i + n))
                if taken & set(span):
                    continue
                words = [toks[k][0] for k in span]
                for cut in range(0, 4):
                    last = words[-1][: len(words[-1]) - cut]
                    if len(last) < 3:
                        break
                    key = " ".join(words[:-1] + [last])
                    if key in self.names:
                        hit = (span, key, words[-1][len(last):])
                        break
                if hit:
                    break
            if not hit:
                i += 1
                continue
            span, key, suffix = hit
            if len(span) == 1 and not message[toks[i][1]].isupper():
                # One-word names are often plain words ("Турист", "Мангал"): only a
                # capitalised word in the request counts as the name.
                i += 1
                continue
            pois = sorted(self.names[key], key=lambda p: -(p.get("ratings_count") or 0))
            # A chain with branches across the city locates nothing by name alone.
            single = all(meters((p["latitude"], p["longitude"]), (pois[0]["latitude"], pois[0]["longitude"])) < 300 for p in pois)
            found.append(
                {"kind": "poi", "key": key, "label": pois[0].get("display_name", "").split(",")[0],
                 "point": (pois[0]["latitude"], pois[0]["longitude"]) if single else None,
                 "poi_ids": [p["poi_id"] for p in pois], "tokens": span,
                 "role": mention_role(toks, span[0], span[-1], suffix)}
            )
            taken.update(span)
            i = span[-1] + 1
        return sorted(found, key=lambda m: m["tokens"][0])

    def named_ids(self, q):
        return {pid for m in self.mentions(q) for pid in m["poi_ids"]}

    def search(
        self,
        q="",
        category=None,
        origin=None,
        minutes=90,
        when=None,
        open_only=False,
        no_steps=False,
        limit=30,
        strict_amenities=False,
        distinct_names=False,
        max_snap_m=MAX_SNAP_M,
        group_size=None,
        max_walk_min=None,
        comfort=None,
        trace=None,
        intent=None,
        exclude=(),
    ):
        """`intent` is the request read by Gemini (backend/intent.py); without it the
        rules below read the categories, kinds and amenities from the text. `exclude` are
        places the walker has already been to ("покажи новое"); a place named in the request
        is still found."""
        # Lexical scores ignore filler words: "хочу" must not find "Хочу хинкали".
        if q.strip() and not tokens(q):
            return []  # symbols only, nothing to search for
        # The model's keywords replace the raw wording for the lexical part:
        # "хочу рисовать" is searched as "галерея искусств", not by the letters of "рисовать".
        text = content_query(intent["keywords"]) if intent else content_query(q)
        scores = self.index.scores(text)
        named = self.named_ids(q) if q else set()
        group = group_size if group_size and group_size >= 3 else None
        query = q.casefold()
        preferred, wanted = (set(intent["categories"]), list(intent["amenities"])) if intent else read_intents(q)
        if weather_widened(preferred, comfort, category):
            preferred = preferred | {"culture"}
        child_room = bool(
            re.search(
                r"детск.{0,8}(?:комнат|угол|меню)|балалар.{0,10}(?:бөлме|мәзір)", query
            )
        )
        family_requirements = []
        if re.search(r"детск.{0,8}комнат|балалар.{0,10}бөлм", query):
            family_requirements.append("комнат")
        if re.search(r"детск.{0,8}угол", query):
            family_requirements.append("угол")
        if re.search(r"детск.{0,8}меню|балалар.{0,10}мәзір", query):
            family_requirements.append("меню")
        need_quiet = "quiet" in wanted
        if intent:
            # The model already named the kinds of places; the word rules below stay off.
            wants_art = art_outdoors = coffee_word = wants_coffee = False
            kinds = set(intent["subcategories"])
            setting_wish = intent["setting"]
        else:
            wants_art = bool(re.search(ART_INTENT, query))
            art_outdoors = wants_art and bool(re.search(ART_OUTDOORS, query))
            kinds = set().union(*(subs for rx, _, subs in KIND_INTENTS if re.search(rx, query)))
            coffee_word = bool(re.search(r"коф|coffee", query))
            wants_coffee = coffee_word or bool(re.search(r"кафе|\bcafe", query))
            setting_wish = "any"
        need_free = bool(re.search(r"бесплат|тегін|\bfree\b", query))
        # Strict mode filters on amenities a visitor relies on; kids/view only rank.
        strict_attrs = [
            a
            for a in wanted
            if a in ("power_outlets", "quiet", "laptop_work", "wifi", "interactive", "accessibility")
        ]
        dt = parse_when(when)
        state = (
            self.router.paths(origin, no_steps, max_minutes=minutes, max_snap_m=max_snap_m)
            if origin
            else None
        )
        results = []
        for i, p in enumerate(self.pois):
            if not p.get("recommendation_eligible", True):
                continue
            if closure(p):
                continue
            if p["poi_id"] in exclude and p["poi_id"] not in named:
                continue
            if category and p.get("category") != category:
                continue
            if need_free and p.get("free_entry") is not True:
                continue
            family_matches = all(
                any(
                    need in f["feature"].casefold()
                    for f in p.get("children_facilities") or []
                )
                for need in family_requirements
            )
            signals = (self.review_signals.get(p["poi_id"]) or {}).get("signals")
            score = float(scores[i])
            if q and any(
                name_key(q) == name_key(a.split(",")[0])
                for a in p.get("aliases") or [p.get("display_name", "")]
            ):
                score += 1.5
            # The request names this place ("идём в Столичный цирк").
            if p["poi_id"] in named:
                score += 1.0
            if p.get("rating_bayesian") is not None:
                score += max(0, (p["rating_bayesian"] - 3) / 2) * 0.035
            if (
                text
                and not preferred
                and p["poi_id"] not in named
                and self.index.backend == "tfidf"
                and float(scores[i]) <= 0
            ):
                continue
            if preferred:
                if p.get("category") not in preferred and p["poi_id"] not in named:
                    continue
                score += 0.3
            if kinds and p.get("subcategory") in kinds:
                score += 0.4
            if wants_art:
                # "Хочу рисовать": galleries and art centres first, then art museums;
                # theatres and history museums are culture too but not for drawing.
                # Outdoors ("на природе"), parks lead and galleries follow.
                if art_outdoors and p.get("category") == "nature":
                    score += 0.4
                elif p.get("subcategory") in ART_SUBCATEGORIES:
                    score += 0.15 if art_outdoors else 0.4
                elif p.get("category") == "culture" and ART_PLACE.search(
                    f"{p.get('display_name') or ''} {p.get('short_description') or ''}"
                ):
                    score += 0.25
                elif p.get("category") == "culture":
                    score -= 0.1
            if wants_coffee and p.get("subcategory") in COFFEE_PLACES:
                # "Выпить кофе": a coffee shop, not the nearest doner or a far-off tea house
                # (text scores barely differ); "кафе" asks for any café.
                score += 0.15 if coffee_word and p.get("subcategory") == "coffee_shop" else 0.05 if coffee_word else 0.1
            if strict_amenities:
                missing = [
                    a for a in strict_attrs if evidence(p, a, signals)[0] not in ("confirmed", "supported")
                ]
                if missing or (child_room and not family_matches):
                    if trace is not None:
                        trace.reject(p, "amenity_unconfirmed", score, attrs=[ATTR_LABEL[a] for a in missing])
                    continue
            if trace is not None:
                trace.count("matched")
            for a in wanted:
                kind, _ = evidence(p, a, signals)
                score += 0.3 if kind == "confirmed" else REVIEW_BOOST.get(kind, 0.0)
            if child_room and family_matches:
                score += 0.3
            if not text and p.get("category") in ("sightseeing", "nature", "culture"):
                score += 0.15
            if group:
                # Companies of 3+: venues that publish group seating rank higher;
                # single-person quiet spaces (libraries, coworking) rank lower.
                if group_features(p):
                    score += 0.15
                if p.get("category") == "quiet_spaces":
                    score -= 0.2
            where = exposure(p)
            # "На природе" / "под крышей" said in the request, as read by the model.
            if setting_wish == "outdoor" and where != "indoor":
                score += 0.15
            elif setting_wish == "indoor" and where == "outdoor":
                score -= 0.3
            if comfort and comfort.get("applies"):
                if where == "outdoor":
                    score -= comfort["outdoor_penalty"]
                elif where == "indoor":
                    score += comfort["indoor_bonus"]
            if origin:
                straight = meters(origin, (p["latitude"], p["longitude"]))
                if straight > min(minutes, max_walk_min or minutes) * 75:
                    if trace is not None:
                        trace.reject(p, "too_far", score, straight, km=round(straight / 1000, 1))
                    continue
            results.append((score, p))
            if trace is not None:
                trace.count("nearby")
        results.sort(key=lambda t: t[0], reverse=True)
        if origin:
            # Route the candidates most likely to fit first: with a large budget the
            # top text scores are often far away and would be routed only to be dropped.
            reach = minutes * 75
            results.sort(
                key=lambda t: t[0] - 0.4 * meters(origin, (t[1]["latitude"], t[1]["longitude"])) / reach,
                reverse=True,
            )
        out = []
        # Route only the strongest candidates; search remains responsive with 7,570 POIs.
        for score, p in results[: max(180, limit * 3)]:
            route = (
                self.router.route(
                    origin, (p["latitude"], p["longitude"]), no_steps, state
                )
                if origin and state is not None
                else None
            )
            if origin and not route:
                if trace is not None:
                    trace.reject(p, "no_route", score)
                continue
            travel = route["duration_min"] if route else 0
            if max_walk_min and travel > max_walk_min:
                if trace is not None:
                    trace.reject(p, "walk_limit", score, walk=round(travel), limit=max_walk_min)
                continue  # "рядом": the walk itself is limited, not only the whole budget
            full_stay = p.get("suggested_visit_duration_min") or DEFAULT_STAY.get(
                p.get("category"), 30
            )
            # A tight budget allows a shorter visit instead of dropping the place.
            min_stay = min(full_stay, MIN_STAY.get(p.get("category"), 15))
            if travel + min_stay > minutes:
                if trace is not None:
                    trace.reject(p, "no_time", score, walk=round(travel), visit=min_stay, budget=minutes)
                continue
            if trace is not None:
                trace.count("reachable")
            stay = min(full_stay, math.floor(minutes - travel))
            arrival = dt + timedelta(minutes=travel)
            status = hours_status(p, arrival, stay)
            if status["status"] == "closed_by_schedule":
                if trace is not None:
                    trace.reject(p, "closed_at_arrival", score, at=arrival.strftime("%H:%M"))
                continue
            if open_only and status["status"] != "open_by_schedule":
                if trace is not None:
                    trace.reject(p, "hours_unknown", score)
                continue
            if trace is not None:
                trace.count("open")
            obj = self.public(p, arrival, stay)
            obj["suggested_visit_duration_min"] = stay
            obj["typical_visit_min"] = full_stay
            # Full visits rank above shortened ones; a long walk costs more than it used
            # to (0.08): a 90-minute walk to an equally good place is not a recommendation.
            travel_weight = comfort["travel_weight"] if comfort and comfort.get("applies") else 1.0
            # Among places of the kind the request names ("театр"), the nearer one wins:
            # a theatre 20 minutes away beats one 56 minutes away with "театр" in its name.
            distance_weight = 0.45 if kinds and p.get("subcategory") in kinds else 0.2
            obj["search_score"] = round(
                score - (travel / minutes) * distance_weight * travel_weight - 0.15 * (1 - stay / full_stay), 4
            )
            obj["exposure"] = exposure(p)
            obj["route"] = route
            obj["total_duration_min"] = round(travel + stay, 1)
            obj["reasons"] = (
                ["Подходит по категории и запросу"]
                if preferred
                else ["Найдено по тексту описания"]
            )
            obj["warnings"] = []
            if stay < full_stay:
                obj["visit_shortened"] = True
                obj["warnings"].append(
                    f"Короткий визит: ~{stay} мин (обычно ~{full_stay}) — столько остаётся после дороги."
                )
            if p.get("semantic_attributes"):
                stems = [w[:5] for w in re.findall(r"[a-zа-яёәіңғүұқөһ]{4,}", text)]
                relevant = [
                    a
                    for a in p["semantic_attributes"]
                    if any(w in a.casefold() for w in stems)
                ]
                obj["reasons"].append(
                    "Из атрибутов источника: "
                    + ", ".join((relevant or p["semantic_attributes"])[:3])
                )
            if child_room and not all(
                any(
                    need in f["feature"].casefold()
                    for f in p.get("children_facilities") or []
                )
                for need in family_requirements
            ):
                obj["warnings"].append(
                    "Детская комната или детское меню не подтверждены"
                )
            obj["evidence"] = {}
            signals = (self.review_signals.get(p["poi_id"]) or {}).get("signals")
            for a in wanted:
                kind, s = evidence(p, a, signals)
                obj["evidence"][a] = kind
                label = ATTR_LABEL[a]
                quote = next(
                    (q for q in (s or {}).get("quotes", []) if q["polarity"] == "positive"),
                    None,
                )
                if kind == "confirmed":
                    obj["reasons"].append(f"Данные места: {label}")
                elif kind == "supported":
                    obj["reasons"].append(
                        f"По отзывам 2ГИС: {label} ({mentions(s['positive'])}"
                        + (f", против — {s['negative'] + s['mixed']}" if s["negative"] + s["mixed"] else "")
                        + (f"; «{quote['text']}»" if quote else "")
                        + ")"
                    )
                elif kind == "single_mention":
                    obj["warnings"].append(
                        f"{label.capitalize()}: одно упоминание в отзывах"
                        + (f" («{quote['text']}»)" if quote else "")
                        + ", не подтверждено"
                    )
                elif kind == "contradicted":
                    obj["warnings"].append(
                        f"По отзывам скорее нет: {label} ({s['negative']} против {s['positive']})"
                    )
                elif kind == "mixed":
                    obj["warnings"].append(
                        f"Отзывы расходятся: {label} ({s['positive']} за, {s['negative'] + s['mixed']} против)"
                    )
                elif a in strict_attrs:
                    obj["warnings"].append(f"{label.capitalize()}: нет данных")
            if group:
                features = group_features(p)
                if features:
                    obj["reasons"].append("Для компании: " + ", ".join(features).lower())
                if p.get("category") == "food_drink" and group >= 4:
                    obj["warnings"].append(
                        f"Для компании из {group} человек лучше заранее забронировать стол: вместимость в данных не указана."
                    )
                cost = group_cost(p, group)
                if cost:
                    obj["group_cost"] = cost
            if need_quiet and p.get("quiet_place") is True and not confirmed_signal(
                p, "quiet_place"
            ) and obj["evidence"].get("quiet") == "unknown":
                obj["warnings"].append(
                    "Тишина упомянута в отдельном отзыве; обстановка не измерена и не гарантирована."
                )
            if comfort and comfort.get("applies") and comfort["score_level"] >= 1 and obj["exposure"] != "mixed":
                obj["comfort"] = obj["exposure"]
            if status["status"] == "unknown":
                obj["warnings"].append("Перед посещением уточните часы работы")
            if route:
                obj["reasons"].append(
                    f"Путь и посещение: ориентировочно {obj['total_duration_min']:g} мин"
                )
            out.append(obj)
        out.sort(key=lambda p: p["search_score"], reverse=True)
        diverse = []
        seen = set()
        shown_as = {}
        for item in out:
            group = self.byid[item["poi_id"]].get(
                "recommendation_diversity_group", item["poi_id"]
            )
            # Chat recommendations show one branch per chain name; the list keeps all.
            name = item["display_name"].casefold() if distinct_names else None
            if group in seen or (name and name in seen):
                other = shown_as.get(group) or shown_as.get(name) or ""
                # Another branch of the same chain is not a different place worth explaining.
                if trace is not None and other and other.casefold() != item["display_name"].split(",")[0].casefold():
                    trace.reject(self.byid[item["poi_id"]], "similar_shown", item["search_score"], other=other)
                continue
            seen.update([group, name] if name else [group])
            label = item["display_name"].split(",")[0]
            shown_as[group] = label
            if name:
                shown_as[name] = label
            diverse.append(item)
        return diverse[:limit]

    def venue_candidate(
        self, pid, origin, minutes, when, no_steps=False, max_snap_m=MAX_SNAP_M,
        reason="Площадка опубликованного события",
    ):
        """A place the request points at (event venue, named destination) as a chat
        candidate, with the same route/hours fields as search results."""
        p = self.byid.get(pid)
        if not p or closure(p):
            return None
        state = self.router.paths(origin, no_steps, max_minutes=minutes, max_snap_m=max_snap_m) if origin else None
        route = self.router.route(origin, (p["latitude"], p["longitude"]), no_steps, state) if state is not None else None
        if origin and route is None:
            return None
        travel = route["duration_min"] if route else 0
        stay = p.get("suggested_visit_duration_min") or DEFAULT_STAY.get(p.get("category"), 30)
        obj = self.public(p, parse_when(when) + timedelta(minutes=travel), stay)
        obj.update(
            route=route,
            total_duration_min=round(travel + stay, 1),
            search_score=1.0,
            reasons=[reason],
            warnings=(
                [f"С дорогой и посещением ~{round(travel + stay)} мин: больше бюджета прогулки ({minutes} мин)."]
                if travel + stay > minutes
                else []
            ),
            evidence={},
        )
        return obj

    def events_nearby(
        self,
        origin,
        when=None,
        minutes=90,
        no_steps=False,
        max_snap_m=MAX_SNAP_M,
        limit=3,
        reachable_only=True,
        keep_venues=(),
    ):
        """Published events the walker can catch during this walk.

        Timed events must start inside the walk window and be reachable on foot
        before they start; day-range listings (exhibitions) count while they run.
        Listings are announcements, not confirmations: cancelled/past ones are skipped.
        At `keep_venues` (the place the user is heading to) a show that cannot be
        reached on foot in time is kept and marked `late`, so the answer can say so.
        """
        start = parse_when(when)
        end = start + timedelta(minutes=minutes)
        state = (
            self.router.paths(origin, no_steps, max_minutes=minutes, max_snap_m=max_snap_m)
            if origin
            else None
        )
        found = []
        for e in self.events:
            status = str(e.get("event_status") or "")
            if status.endswith(("EventCancelled", "EventPostponed")) or e.get("listing_period_status") == "past":
                continue
            try:
                ev_start = parse_when(e["event_start"])
                ev_end = parse_when(e["event_end"]) if e.get("event_end") else None
            except (KeyError, TypeError, ValueError):
                continue
            timed = e.get("date_precision") == "datetime"
            if timed:
                if not start <= ev_start <= end:
                    continue
            else:
                # Day-precision ranges (exhibitions): open on the walk date.
                last = (ev_end or ev_start).date()
                if not ev_start.date() <= start.date() <= last:
                    continue
            coords = e.get("event_coordinates") or {}
            venue = self.byid.get(e.get("venue_poi_id") or "")
            point = (
                (coords["latitude"], coords["longitude"])
                if coords.get("latitude") is not None
                else (venue["latitude"], venue["longitude"]) if venue else None
            )
            route = (
                self.router.route(origin, point, no_steps, state)
                if point and state is not None
                else None
            )
            walk = route["duration_min"] if route else None
            late = bool(timed and walk is not None and start + timedelta(minutes=walk) > ev_start)
            if late and (venue or {}).get("poi_id") not in keep_venues:
                continue  # cannot arrive before it begins
            if reachable_only and origin and walk is None:
                continue
            price = e.get("event_price") or {}
            if str(price.get("availability") or "").endswith("SoldOut"):
                continue  # the publisher reports no tickets left
            found.append(
                {
                    "event_id": e["event_id"],
                    "name": e.get("event_name"),
                    "start": e.get("event_start"),
                    "end": e.get("event_end"),
                    "timed": timed,
                    "category": e.get("event_category"),
                    "venue": e.get("event_location") or (venue or {}).get("display_name"),
                    "venue_poi_id": venue["poi_id"] if venue else None,
                    "walk_min": round(walk) if walk is not None else None,
                    "late": late,
                    "price_from": price.get("amount_min"),
                    "currency": price.get("currency"),
                    "age_group": e.get("event_age_group"),
                    "source_url": e.get("registration_url") or e.get("source_url"),
                    "source_name": e.get("source_name"),
                    "note": "Опубликованный анонс: проведение и наличие билетов не подтверждены.",
                }
            )
        found.sort(key=lambda x: (x["venue_poi_id"] not in keep_venues, x["walk_min"] is None, x["start"] or "", x["walk_min"] or 0))
        return found[:limit]

    def mini_route(
        self,
        candidates,
        origin,
        minutes,
        when,
        no_steps=False,
        max_snap_m=MAX_SNAP_M,
        prefer=(),
        size=3,
        pool=16,
        cover=(),
        finish=None,
        reserve=0,
        sizes=None,
        max_leg=None,
        require=(),
    ):
        """Best ordered set of up to `size` candidates that fits the time budget together.

        Unlike plan(), the stops are chosen here: every ordered sequence of the top
        `pool` candidates is checked on the walking graph (travel between stops, visit
        estimates, opening hours at arrival). The best one maximizes relevance and
        category variety and, among equal sets, walks less. Falls back to 2 stops.
        `cover` lists categories the request named together ("музей и кофе"): a route
        must include each of them; only if none fits, the route is built without it.

        `finish` ({latitude, longitude, label, loop}) ends the walk at a point by the end
        of the budget: the last leg to it and `reserve` spare minutes count too, so the
        stops are chosen for the whole way start -> stops -> finish. `sizes` lists the stop
        counts to try in order (default: `size`, then 2); `max_leg` caps each walk between
        stops (tired or cold walkers). `require` lists poi_ids every route must include
        ("первое место оставь"): they are moved to the front of the candidates.
        """
        if not origin:
            return None
        required = set(require)
        # Pinned stops always take part, whatever their rank among the candidates.
        ordered = [c for c in candidates if c["poi_id"] in required] + [c for c in candidates if c["poi_id"] not in required]
        cands = [
            self.byid[c["poi_id"]]
            for c in ordered[: pool + len(required)]
            if c["poi_id"] in self.byid and not closure(self.byid[c["poi_id"]])
        ]
        sizes = tuple(sizes or (size, 2))
        if not cands or len(cands) < min(sizes):
            return None
        relevance = {c["poi_id"]: c.get("search_score", 0) for c in candidates}
        start = parse_when(when)
        points = [origin] + [(p["latitude"], p["longitude"]) for p in cands]
        goal = (finish["latitude"], finish["longitude"]) if finish else None
        stay = [0] + [
            p.get("suggested_visit_duration_min") or DEFAULT_STAY.get(p.get("category"), 30)
            for p in cands
        ]
        # Walking legs between the start and every candidate, both directions.
        legs = {}
        for i, point in enumerate(points):
            state = self.router.paths(point, no_steps, max_minutes=minutes, max_snap_m=max_snap_m)
            if state is None:
                if i == 0:
                    return None
                continue
            for j in range(1, len(points)):
                if j != i:
                    route = self.router.route(point, points[j], no_steps, state)
                    if route and (max_leg is None or route["duration_min"] <= max_leg):
                        legs[(i, j)] = route
            if goal:
                route = self.router.route(point, goal, no_steps, state)
                if route:
                    legs[(i, "F")] = route
        # A walk of three near-identical objects (e.g. three rocket models in one park)
        # is not a route: stops must not share a name stem; a repeated subcategory costs.
        def stem(p):
            words = re.findall(r"\w+", (p.get("display_name") or "").casefold())
            return " ".join(words[:2])

        def varied(seq):
            stems = [stem(cands[j - 1]) for j in seq]
            return len(set(stems)) == len(stems)

        def repeats(seq):
            subs = [cands[j - 1].get("subcategory") for j in seq]
            return len(subs) - len(set(subs))

        # A tight budget may shorten visits to the category minimum (a coffee, a look
        # at a monument), as single-place search does; full visits are preferred.
        short = [0] + [
            min(s, MIN_STAY.get(p.get("category"), 15)) for s, p in zip(stay[1:], cands)
        ]

        def walk_through(seq, stays):
            elapsed, prev, arrivals, used = 0.0, 0, [], []
            for j in seq:
                leg = legs.get((prev, j))
                if leg is None:
                    return None
                arrival = elapsed + leg["duration_min"]
                status = hours_status(cands[j - 1], start + timedelta(minutes=arrival), stays[j])
                elapsed = arrival + stays[j]
                if elapsed > minutes or status["status"] in ("closed_reported", "closed_by_schedule"):
                    return None
                arrivals.append(arrival)
                used.append(leg)
                prev = j
            last = None
            if goal:
                last = legs.get((prev, "F"))
                if last is None or elapsed + last["duration_min"] + reserve > minutes:
                    return None
            return elapsed, arrivals, used, [stays[j] for j in seq], last

        best = None
        direct = legs[(0, "F")]["duration_min"] if goal and (0, "F") in legs else None
        needs = [set(cover), set()] if cover else [set()]
        attempts = [(need, count) for need in needs for count in sizes if 1 <= count and len(need) <= count]
        for need, count in attempts:
            for seq in itertools.permutations(range(1, len(points)), count):
                if not varied(seq):
                    continue
                if need and not need <= {cands[j - 1].get("category") for j in seq}:
                    continue
                if required and not required <= {cands[j - 1]["poi_id"] for j in seq}:
                    continue
                result = walk_through(seq, stay) or walk_through(seq, short)
                if result is None:
                    continue
                elapsed, arrivals, used, visits, last = result
                ids = [cands[j - 1]["poi_id"] for j in seq]
                shortened = sum(v < stay[j] for v, j in zip(visits, seq))
                value = (
                    sum(relevance.get(pid, 0) for pid in ids)
                    + 0.12 * len({cands[j - 1].get("category") for j in seq})
                    + 0.4 * sum(pid in prefer for pid in ids)
                    - 0.25 * repeats(seq)
                    - 0.002 * (sum(leg["duration_min"] for leg in used) + (last["duration_min"] if last else 0))
                    - 0.05 * shortened
                )
                if last is not None and direct is not None:
                    # Toward a finish, every minute of detour off the direct way costs:
                    # "кофе по пути" should not lead away from MEGA.
                    value -= 0.01 * max(0.0, sum(leg["duration_min"] for leg in used) + last["duration_min"] - direct)
                if best is None or value > best[0]:
                    best = (value, seq, used, arrivals, elapsed, need, visits, last)
            if best:
                break
        if not best:
            return None
        _, seq, used, arrivals, elapsed, need, visits, last = best
        missing = [c for c in cover if c not in need]
        stops = []
        for j, arrival, visit in zip(seq, arrivals, visits):
            stop = self.public(cands[j - 1], start + timedelta(minutes=arrival), visit)
            stop["suggested_visit_duration_min"] = visit
            stop["typical_visit_min"] = stay[j]
            if visit < stay[j]:
                stop["visit_shortened"] = True
            stop["arrival_offset_min"] = round(arrival)
            stops.append(stop)
        walk = sum(leg["duration_min"] for leg in used)
        out = {
            "kind": "mini_route",
            "stops": stops,
            "legs": used,
            "total_duration_min": round(elapsed, 1),
            "walk_duration_min": round(walk, 1),
            "budget_minutes": minutes,
            "return_trip_included": False,
            "covers_requested": not missing,
            "warnings": (
                ["Не все названные виды мест помещаются в маршрут по времени и часам работы: "
                 + ", ".join(LABELS.get(c, c).lower() for c in missing) + "."]
                if missing
                else []
            )
            + [
                "Порядок и время рассчитаны по пешеходному графу OSM"
                + ("." if finish else "; маршрут без возвращения к началу."),
                "Время посещения — оценка; часы и доступность требуют уточнения.",
            ],
        }
        if finish:
            out["finish"] = finish_info(finish, last, elapsed, minutes, reserve)
            out["total_duration_min"] = out["finish"]["arrival_offset_min"]
            out["walk_duration_min"] = round(walk + last["duration_min"], 1)
            out["return_trip_included"] = bool(finish.get("loop"))
        return out

    def finish_leg(self, origin, finish, no_steps=False, max_snap_m=MAX_SNAP_M):
        """Walking route from a point straight to the finish, or None."""
        state = self.router.paths(origin, no_steps, max_minutes=480, max_snap_m=max_snap_m)
        if state is None:
            return None
        return self.router.route(origin, (finish["latitude"], finish["longitude"]), no_steps, state)

    def direct_route(self, origin, finish, minutes, reserve=0, no_steps=False, max_snap_m=MAX_SNAP_M):
        """A route with no stops, only the way to the finish. It may not fit the budget:
        `finish.fits` says so, and the answer tells the user honestly."""
        leg = self.finish_leg(origin, finish, no_steps, max_snap_m)
        if leg is None:
            return None
        return {
            "kind": "mini_route",
            "stops": [],
            "legs": [],
            "total_duration_min": round(leg["duration_min"], 1),
            "walk_duration_min": round(leg["duration_min"], 1),
            "budget_minutes": minutes,
            "return_trip_included": bool(finish.get("loop")),
            "covers_requested": True,
            "finish": finish_info(finish, leg, 0, minutes, reserve),
            "warnings": ["Время пути рассчитано по пешеходному графу OSM; транспорт и пробки не учитываются."],
        }

    def plan(self, ids, origin, minutes, when, no_steps=False, max_snap_m=MAX_SNAP_M):
        current = origin
        elapsed = 0
        legs = []
        stops = []
        warnings = []
        remaining = list(
            dict.fromkeys(self.byid[i]["poi_id"] for i in ids if i in self.byid)
        )[:3]
        while remaining:
            options = []
            state = self.router.paths(
                current, no_steps, max_minutes=max(1, minutes - elapsed), max_snap_m=max_snap_m
            )
            for pid in remaining:
                p = self.byid.get(pid)
                if not p or closure(p):
                    continue
                route = (
                    self.router.route(
                        current, (p["latitude"], p["longitude"]), no_steps, state
                    )
                    if state is not None
                    else None
                )
                if route is None:
                    continue
                stay = p.get("suggested_visit_duration_min") or DEFAULT_STAY.get(
                    p.get("category"), 30
                )
                arrival = parse_when(when) + timedelta(
                    minutes=elapsed + route["duration_min"]
                )
                hs = hours_status(p, arrival, stay)
                if elapsed + route["duration_min"] + stay > minutes or hs["status"] in (
                    "closed_reported",
                    "closed_by_schedule",
                ):
                    continue
                options.append((route["duration_min"], p, route, stay, arrival))
            if not options:
                break
            _, p, route, stay, arrival = min(options, key=lambda a: a[0])
            elapsed += route["duration_min"] + stay
            stops.append(self.public(p, arrival, stay))
            legs.append(route)
            remaining.remove(p["poi_id"])
            current = (p["latitude"], p["longitude"])
        if remaining:
            warnings.append(
                "Некоторые места исключены: не хватает времени, нет пути в графе или не подходят часы работы."
            )
        return {
            "stops": stops,
            "legs": legs,
            "total_duration_min": round(elapsed, 1),
            "budget_minutes": minutes,
            "return_trip_included": False,
            "warnings": warnings
            + [
                "Маршрут без возвращения к начальной точке.",
                "Время посещения — оценка; часы и доступность требуют уточнения.",
            ],
        }
