"""Questions about one place, answered only from what the dataset knows.

Every answer carries a certainty (yes / likely / unknown / no) and the evidence it rests on.
Nothing is generated: a question the data cannot answer says so instead of guessing.
"""

import re
from datetime import timedelta
from .hours import DAYS, hours_status, parse_when
from .query import content_query, fold
from .service import ATTR_LABEL, REVIEW_INTENTS, evidence, mentions

TOPICS = {
    "hours": r"до скольки|во сколько|закрыва|закроет|откро|открыт|работает|режим|график|часы|\bhours?\b|\bopen\b|\bclose|жұмыс|ашық|қашан",
    "price": r"бесплат|цен[аыу]|стоит|стоимост|билет|вход|чек|дорого|дешев|price|ticket|free|cost|тегін|баға",
    "rating": r"рейтинг|оценк|отзыв|хвалят|rating|review|пікір",
    "address": r"адрес|где наход|как найти|как добрат|where is|address|мекенжай",
    "contact": r"телефон|позвон|сайт|номер|phone|website|call|байланыс",
    "events": r"что идёт|что идет|событи|афиш|выставк|концерт|спектакл|мероприят|\bevents?\b|what.?s on|іс-шара",
    "duration": r"сколько времени|сколько займ|надолго|how long|duration|қанша уақыт",
}
SUGGESTIONS = ["hours", "price", "power_outlets", "wifi", "quiet", "accessibility", "kids", "events"]
GENERIC = {"есть", "можно", "здесь", "место", "места", "там", "это"}
DAY_NAMES = {"Mo": "пн", "Tu": "вт", "We": "ср", "Th": "чт", "Fr": "пт", "Sa": "сб", "Su": "вс"}
RATING_WORD = {"yes": "да", "likely": "вероятно", "unknown": "неизвестно", "no": "нет"}


def _answer(topic, text, certainty, evidence_lines=(), source="data"):
    return {
        "topic": topic,
        "answer": text,
        "certainty": certainty,
        "evidence": list(evidence_lines),
        "source": source,
    }


def _span(day):
    return ", ".join(f"{a}–{b}" for a, b in day)


def _hours(p, when):
    dt = parse_when(when)
    schedule = p.get("opening_hours_by_day")
    if not schedule and p.get("opening_hours") == "24/7":
        schedule = {d: [["00:00", "24:00"]] for d in DAYS}
    status = hours_status(p, dt, 0)
    if status["status"] == "closed_reported":
        return _answer("hours", "Источник сообщает, что место закрыто или скоро откроется.", "no", [status["label"]])
    if not isinstance(schedule, dict):
        return _answer(
            "hours",
            "Часов работы в данных нет. Перед визитом уточните их у места.",
            "unknown",
            [p.get("opening_hours") and f"В источнике: {p['opening_hours']}" or "Расписание не опубликовано в данных"],
        )
    today = DAYS[dt.weekday()]
    lines = [f"{DAY_NAMES[d]}: {_span(schedule[d]) if schedule.get(d) else 'выходной'}" for d in DAYS]
    if schedule.get(today):
        text = f"Сегодня ({DAY_NAMES[today]}) {_span(schedule[today])}."
    else:
        text = f"Сегодня ({DAY_NAMES[today]}) по расписанию выходной."
    if status["status"] == "open_by_schedule":
        text += " Сейчас открыто по расписанию."
    elif status["status"] == "closed_by_schedule":
        text += " Сейчас закрыто по расписанию."
        for offset in range(1, 8):
            day = dt + timedelta(days=offset)
            slots = schedule.get(DAYS[day.weekday()]) or []
            if slots:
                text += f" Ближайшее открытие: {DAY_NAMES[DAYS[day.weekday()]]} в {slots[0][0]}."
                break
    if p.get("hours_verified_at"):
        lines.append(f"Часы проверены {str(p['hours_verified_at'])[:10]}")
    # A published schedule is not a live check: holiday changes are unknown.
    return _answer("hours", text, "likely", ["; ".join(lines), "Праздничные изменения не проверены"])


def _price(p):
    if p.get("free_entry") is True:
        return _answer("price", "Вход бесплатный.", "yes", ["Поле free_entry в данных места"])
    for key, label in (("adult_ticket_price", "Взрослый билет"), ("standard_ticket_price", "Билет")):
        price = p.get(key) or {}
        if price.get("amount") is not None:
            text = f"{label}: {price['amount']:g} {price.get('currency') or 'KZT'}."
            return _answer("price", text, "yes", [f"Опубликованная цена ({key})"])
    budget = p.get("estimated_visit_budget") or {}
    if budget.get("amount_min") is not None:
        top = budget.get("amount_max")
        span = f"{budget['amount_min']:g}" + (f"–{top:g}" if top and top != budget["amount_min"] else "")
        text = f"Ориентировочный бюджет на посещение: {span} {budget.get('currency') or 'KZT'}. Это оценка среднего чека, не цена входа."
        return _answer("price", text, "likely", ["Средний чек из источника (estimated_visit_budget)"])
    return _answer("price", "Цен и условий входа в данных нет. Уточните у места.", "unknown", ["Нет опубликованных цен"])


def _rating(p):
    if p.get("rating") is None:
        return _answer("rating", "Рейтинга в данных нет.", "unknown", ["Нет оценок в источниках"])
    count = p.get("ratings_count")
    text = f"Рейтинг {p['rating']:g}" + (f" по {count} оценкам." if count else ".")
    return _answer("rating", text, "yes", ["Оценка из источника (2ГИС/карты); не проверялась нами"])


def _address(p):
    if not p.get("address"):
        return _answer("address", "Адреса в данных нет; точка есть на карте.", "unknown", [f"Координаты {p['latitude']:.5f}, {p['longitude']:.5f}"])
    return _answer("address", p["address"] + ".", "yes", ["Адрес из источника"])


def _contact(p):
    parts = [x for x in (p.get("phone") and f"Телефон: {p['phone']}", p.get("website") and f"Сайт: {p['website']}") if x]
    if not parts:
        return _answer("contact", "Телефона и сайта в данных нет.", "unknown", ["Контакты не опубликованы в источниках"])
    return _answer("contact", ". ".join(parts) + ".", "yes", ["Контакты из источника"])


def _events(city, p, when):
    today = parse_when(when).date().isoformat()
    rows = []
    for e in city.events:
        if e.get("venue_poi_id") != p["poi_id"]:
            continue
        if str(e.get("event_status") or "").endswith(("EventCancelled", "EventPostponed")):
            continue
        if (e.get("event_end") or e.get("event_start") or "") < today:
            continue
        rows.append(e)
    rows.sort(key=lambda e: e.get("event_start") or "")
    if not rows:
        return _answer("events", "В афише на ближайшие дни событий здесь нет.", "unknown", ["Снимок афиши от 19.10.2026; отсутствие записи не доказывает, что событий нет"])
    text = "; ".join(f"{e.get('event_name')} — {str(e.get('event_start'))[:16].replace('T', ' ')}" for e in rows[:3])
    return _answer("events", text + ".", "likely", ["Опубликованный анонс: проведение и билеты не подтверждены"])


def _duration(p):
    minutes = p.get("suggested_visit_duration_min")
    if not minutes:
        return _answer("duration", "Типичное время визита в данных не указано.", "unknown", [])
    return _answer("duration", f"Обычно около {minutes} мин.", "likely", ["Оценка по типу места, не измерение"])


def _amenity(p, key, signals):
    kind, signal = evidence(p, key, signals)
    label = ATTR_LABEL[key]
    quote = next((q for q in (signal or {}).get("quotes", []) if q["polarity"] == "positive"), None)
    if kind == "confirmed":
        return _answer(key, f"Да: {label}.", "yes", ["Поле в данных места"])
    if kind == "supported":
        against = signal["negative"] + signal["mixed"]
        proof = [f"Отзывы 2ГИС: {mentions(signal['positive'])} за" + (f", {against} против" if against else "")]
        if quote:
            proof.append(f"«{quote['text']}»")
        return _answer(key, f"Вероятно: {label} (по отзывам).", "likely", proof, "reviews")
    if kind == "single_mention":
        proof = ["Одно упоминание в отзывах"] + ([f"«{quote['text']}»"] if quote else [])
        return _answer(key, f"Неизвестно: {label} упомянуто один раз, этого мало для вывода.", "unknown", proof, "reviews")
    if kind == "mixed":
        return _answer(key, f"Неизвестно: отзывы расходятся по поводу «{label}».", "unknown", [f"{signal['positive']} за, {signal['negative'] + signal['mixed']} против"], "reviews")
    if kind == "contradicted":
        return _answer(key, f"Скорее нет: {label} (по отзывам).", "no", [f"{signal['negative']} против, {signal['positive']} за"], "reviews")
    return _answer(key, f"Неизвестно: про «{label}» в данных ничего нет.", "unknown", ["Нет поля в данных и нет упоминаний в отзывах"])


def _attributes(p, question):
    """Free-form fallback: published venue attributes that share a word stem with the question."""
    stems = [w[:5] for w in content_query(question).split() if len(w) >= 4 and w not in GENERIC]
    pool = [*(p.get("semantic_attributes") or []), *(f["feature"] for f in p.get("children_facilities") or [])]
    hits = [a for a in pool if any(s in fold(a.casefold()) for s in (fold(x) for x in stems))]
    if not hits:
        return None
    return _answer("attributes", "Да, в данных места указано: " + ", ".join(hits[:3]) + ".", "yes", ["Атрибуты места из источника"])


def answer(city, poi_id, question, when=None):
    """Answers for every topic found in the question; one 'unknown' answer if none is."""
    p = city.byid[poi_id]
    q = question.casefold()
    signals = (city.review_signals.get(p["poi_id"]) or {}).get("signals")
    out = []
    for topic, pattern in TOPICS.items():
        if re.search(pattern, q):
            out.append(
                {
                    "hours": lambda: _hours(p, when),
                    "price": lambda: _price(p),
                    "rating": lambda: _rating(p),
                    "address": lambda: _address(p),
                    "contact": lambda: _contact(p),
                    "events": lambda: _events(city, p, when),
                    "duration": lambda: _duration(p),
                }[topic]()
            )
    for key, pattern in REVIEW_INTENTS.items():
        if re.search(pattern, q):
            out.append(_amenity(p, key, signals))
    if not out:
        found = _attributes(p, question)
        out.append(
            found
            or _answer(
                "unknown",
                "В данных об этом месте ответа нет. Лучше уточнить у самого места.",
                "unknown",
                ["Вопрос не совпал с известными полями места"],
                "none",
            )
        )
    return {
        "poi_id": p["poi_id"],
        "name": (p.get("display_name") or "").split(",")[0],
        "question": question,
        "answers": out,
        "note": "Ответы собраны из данных и отзывов, без генерации. Отзывы и расписание не равны проверке на месте.",
    }
