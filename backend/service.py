import itertools
import json
import re
from datetime import timedelta
import numpy as np
from .settings import DATA
from .index import SearchIndex
from .routing import MAX_SNAP_M, Router, meters
from .hours import closure, hours_status, parse_when

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
ALIASES = [
    (r"каф|коф|ресторан|поесть|тамақ|асхана|cafe|coffee", ["food_drink"]),
    (r"парк|прогул|погуля|серуен|саябақ|park", ["nature", "sightseeing"]),
    (r"музе|выстав|мұражай|museum", ["culture"]),
    (r"реб[её]н|деть|детск|бала|kids", ["children", "entertainment", "culture"]),
    (r"турис|достопр|посмотр|көрікті|tourist", ["sightseeing", "culture"]),
    (r"ноч|түн|\bnight", ["nightlife", "entertainment"]),
]
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
        events_path = DATA / "events.jsonl"
        self.events = (
            [json.loads(l) for l in events_path.open(encoding="utf-8")]
            if events_path.exists()
            else []
        )

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

    def origin_from_message(self, message):
        patterns = {
            "mega": r"mega|мега",
            "bayterek": r"байтерек|бәйтерек|bayterek",
            "museum": r"национальн.{0,8}музе|ұлттық.{0,8}мұражай",
            "opera": r"астана опера|astana opera",
            "alem": r"alem\.ai|алем",
        }
        for key, pattern in patterns.items():
            if re.search(pattern, message, re.I):
                lm = self.landmarks[key]
                return (lm["lat"], lm["lon"]), lm["name"]
        # Actual POI names can locate the search, without persisting a user address.
        for p in self.pois:
            name = p.get("display_name") or ""
            if len(name) > 7 and name.casefold() in message.casefold():
                return (p["latitude"], p["longitude"]), name
        return None, None

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
    ):
        scores = self.index.scores(q)
        group = group_size if group_size and group_size >= 3 else None
        query = q.casefold()
        preferred = set()
        for pattern, cats in ALIASES:
            if re.search(pattern, query):
                preferred.update(cats)
        food_intent = bool(re.search(ALIASES[0][0], query))
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
        # "кафе" alone narrows to food; "кафе и музей" keeps every named category.
        other_category = any(re.search(rx, query) for rx, _ in ALIASES[1:])
        if food_intent and not other_category and not re.search(r"\bили\b|\bзатем\b|сосын|немесе", query):
            preferred = {"food_drink"}
        wanted = [a for a, rx in REVIEW_INTENTS.items() if re.search(rx, query)]
        need_quiet = "quiet" in wanted
        need_free = bool(re.search(r"бесплат|тегін|\bfree\b", query))
        if need_quiet and not preferred:
            preferred.update(["food_drink", "quiet_spaces", "nature"])
        if "laptop_work" in wanted and not preferred:
            preferred.update(["food_drink", "quiet_spaces"])
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
            if strict_amenities and (
                any(
                    evidence(p, a, signals)[0] not in ("confirmed", "supported")
                    for a in strict_attrs
                )
                or (child_room and not family_matches)
            ):
                continue
            if (
                origin
                and meters(origin, (p["latitude"], p["longitude"])) > minutes * 75
            ):
                continue
            score = float(scores[i])
            fold = (
                lambda s: re.sub(r"[^\w]+", " ", s.casefold())
                .translate(str.maketrans("әқғңұүөіё", "акгнууоие"))
                .strip()
            )
            if q and any(
                fold(q) == fold(a.split(",")[0])
                for a in p.get("aliases") or [p.get("display_name", "")]
            ):
                score += 1.5
            if p.get("rating_bayesian") is not None:
                score += max(0, (p["rating_bayesian"] - 3) / 2) * 0.035
            if (
                q
                and not preferred
                and self.index.backend == "tfidf"
                and float(scores[i]) <= 0
            ):
                continue
            if preferred:
                if p.get("category") not in preferred:
                    continue
                score += 0.3
            for a in wanted:
                kind, _ = evidence(p, a, signals)
                score += 0.3 if kind == "confirmed" else REVIEW_BOOST.get(kind, 0.0)
            if child_room and family_matches:
                score += 0.3
            if not q and p.get("category") in ("sightseeing", "nature", "culture"):
                score += 0.15
            if group:
                # Companies of 3+: venues that publish group seating rank higher;
                # single-person quiet spaces (libraries, coworking) rank lower.
                if group_features(p):
                    score += 0.15
                if p.get("category") == "quiet_spaces":
                    score -= 0.2
            results.append((score, p))
        results.sort(key=lambda t: t[0], reverse=True)
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
                continue
            travel = route["duration_min"] if route else 0
            stay = p.get("suggested_visit_duration_min") or DEFAULT_STAY.get(
                p.get("category"), 30
            )
            if travel + stay > minutes:
                continue
            arrival = dt + timedelta(minutes=travel)
            status = hours_status(p, arrival, stay)
            if status["status"] == "closed_by_schedule":
                continue
            if open_only and status["status"] != "open_by_schedule":
                continue
            obj = self.public(p, arrival, stay)
            obj["search_score"] = round(score - (travel / minutes) * 0.08, 4)
            obj["route"] = route
            obj["total_duration_min"] = round(travel + stay, 1)
            obj["reasons"] = (
                ["Подходит по категории и запросу"]
                if preferred
                else ["Найдено по тексту описания"]
            )
            obj["warnings"] = []
            if p.get("semantic_attributes"):
                stems = [w[:5] for w in re.findall(r"[a-zа-яёәіңғүұқөһ]{4,}", query)]
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
        for item in out:
            group = self.byid[item["poi_id"]].get(
                "recommendation_diversity_group", item["poi_id"]
            )
            # Chat recommendations show one branch per chain name; the list keeps all.
            name = item["display_name"].casefold() if distinct_names else None
            if group in seen or (name and name in seen):
                continue
            seen.update([group, name] if name else [group])
            diverse.append(item)
        return diverse[:limit]

    def venue_candidate(self, pid, origin, minutes, when, no_steps=False, max_snap_m=MAX_SNAP_M):
        """An event venue as a chat candidate, with the same route/hours fields as search results."""
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
            reasons=["Площадка опубликованного события"],
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
    ):
        """Published events the walker can catch during this walk.

        Timed events must start inside the walk window and be reachable on foot
        before they start; day-range listings (exhibitions) count while they run.
        Listings are announcements, not confirmations: cancelled/past ones are skipped.
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
            if timed and walk is not None and start + timedelta(minutes=walk) > ev_start:
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
                    "price_from": price.get("amount_min"),
                    "currency": price.get("currency"),
                    "age_group": e.get("event_age_group"),
                    "source_url": e.get("registration_url") or e.get("source_url"),
                    "source_name": e.get("source_name"),
                    "note": "Опубликованный анонс: проведение и наличие билетов не подтверждены.",
                }
            )
        found.sort(key=lambda x: (x["walk_min"] is None, x["start"] or "", x["walk_min"] or 0))
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
    ):
        """Best ordered set of up to `size` candidates that fits the time budget together.

        Unlike plan(), the stops are chosen here: every ordered sequence of the top
        `pool` candidates is checked on the walking graph (travel between stops, visit
        estimates, opening hours at arrival). The best one maximizes relevance and
        category variety and, among equal sets, walks less. Falls back to 2 stops.
        """
        if not origin:
            return None
        cands = [
            self.byid[c["poi_id"]]
            for c in candidates[:pool]
            if c["poi_id"] in self.byid and not closure(self.byid[c["poi_id"]])
        ]
        if len(cands) < 2:
            return None
        relevance = {c["poi_id"]: c.get("search_score", 0) for c in candidates}
        start = parse_when(when)
        points = [origin] + [(p["latitude"], p["longitude"]) for p in cands]
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
                    if route:
                        legs[(i, j)] = route
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

        best = None
        for count in (size, 2):
            for seq in itertools.permutations(range(1, len(points)), count):
                if not varied(seq):
                    continue
                elapsed, prev, arrivals, used = 0.0, 0, [], []
                for j in seq:
                    leg = legs.get((prev, j))
                    if leg is None:
                        break
                    arrival = elapsed + leg["duration_min"]
                    status = hours_status(cands[j - 1], start + timedelta(minutes=arrival), stay[j])
                    elapsed = arrival + stay[j]
                    if elapsed > minutes or status["status"] in ("closed_reported", "closed_by_schedule"):
                        break
                    arrivals.append(arrival)
                    used.append(leg)
                    prev = j
                else:
                    ids = [cands[j - 1]["poi_id"] for j in seq]
                    value = (
                        sum(relevance.get(pid, 0) for pid in ids)
                        + 0.12 * len({cands[j - 1].get("category") for j in seq})
                        + 0.4 * sum(pid in prefer for pid in ids)
                        - 0.25 * repeats(seq)
                        - 0.002 * sum(leg["duration_min"] for leg in used)
                    )
                    if best is None or value > best[0]:
                        best = (value, seq, used, arrivals, elapsed)
            if best:
                break
        if not best:
            return None
        _, seq, used, arrivals, elapsed = best
        stops = []
        for j, arrival in zip(seq, arrivals):
            stop = self.public(cands[j - 1], start + timedelta(minutes=arrival), stay[j])
            stop["arrival_offset_min"] = round(arrival)
            stops.append(stop)
        walk = sum(leg["duration_min"] for leg in used)
        return {
            "kind": "mini_route",
            "stops": stops,
            "legs": used,
            "total_duration_min": round(elapsed, 1),
            "walk_duration_min": round(walk, 1),
            "budget_minutes": minutes,
            "return_trip_included": False,
            "warnings": [
                "Порядок и время рассчитаны по пешеходному графу OSM; маршрут без возвращения к началу.",
                "Время посещения — оценка; часы и доступность требуют уточнения.",
            ],
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
