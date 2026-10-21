"""Where a company should meet: everyone starts somewhere else.

"Я у EXPO, Алина у Хан Шатыра, Данияр у Байтерека. Где встретиться?" Each person's walk
to every candidate is computed on the walking graph from their own start. The best place
keeps the longest walk short (nobody should walk an hour while the others walk five
minutes) and then the total; the place still has to fit the wish and be open on arrival.
Starts are taken from the text only: no positions are stored or sent to the model.
"""

import re
from datetime import timedelta
from .hours import hours_status, parse_when
from .query import STOP_WORDS, fold, tokens
from .routing import meters

MEET_INTENT = re.compile(
    r"встрет|встреч|собраться|соберёмся|соберемся|пересеч|сойтись|увидеться|кездес|\bmeet", re.I
)
# Words between a person and their place: "Алина сейчас у Хан Шатыра".
PLACE_BEFORE = {fold(w) for w in "у возле около из от в на рядом близ at near by from in сейчас уже стоит сидит находится будет".split()}
SELF = {fold(w) for w in "я мы мен біз i we".split()}
FIRST_PERSON = re.compile(r"(?<!\w)(?:я|мы|мне|нам|нас|мен|біз|бізге|i|we|us)(?!\w)", re.I)
# Longest walk to the meeting place worth suggesting on foot.
MAX_WALK_MIN = 90
FAR_WALK_MIN = 40
DEFAULT_WISH = "кафе кофейня"


def people_from_text(city, text, origin=None, origin_label=None):
    """[{name, self, point, place}] for the people the text places somewhere ("Алина у
    Хан Шатыра"); the asker without a place in the text stands at the map start."""
    toks = tokens(text)
    people = []
    for m in city.mentions(text):
        if not m["point"]:
            continue
        j = m["tokens"][0] - 1
        while j >= 0 and toks[j][0] in PLACE_BEFORE:
            j -= 1
        if j < 0:
            continue
        word, s, e = toks[j]
        original = text[s:e]
        if word in SELF:
            people.append({"name": "Вы", "self": True, "point": m["point"], "place": m["label"]})
        elif original[:1].isupper() and word not in STOP_WORDS and len(word) >= 2:
            people.append({"name": original, "self": False, "point": m["point"], "place": m["label"]})
    if origin and not any(p["self"] for p in people) and FIRST_PERSON.search(text):
        people.insert(0, {"name": "Вы", "self": True, "point": origin, "place": origin_label or "точка старта"})
    seen, out = set(), []
    for p in people:
        if p["name"] not in seen:
            seen.add(p["name"])
            out.append(p)
    return out


def meet(city, people, query, intent, when, no_steps=False, max_snap_m=150, limit=3):
    """Best meeting places for `people`, each with every person's walk and route."""
    start = parse_when(when)
    states = []
    for p in people:
        state = city.router.paths(p["point"], no_steps, max_minutes=MAX_WALK_MIN, max_snap_m=max_snap_m)
        states.append(state)
    lost = [p["name"] for p, st in zip(people, states) if st is None]
    if lost:
        return {"items": [], "lost": lost}
    centre = (
        sum(p["point"][0] for p in people) / len(people),
        sum(p["point"][1] for p in people) / len(people),
    )
    spread = max(meters(centre, p["point"]) for p in people)
    found = city.search(
        query or DEFAULT_WISH, None, None, MAX_WALK_MIN, when, distinct_names=True, limit=400,
        intent=intent, group_size=len(people),
    )
    # Places around the middle of the company; the walking graph decides the rest.
    nearby = [c for c in found if meters(centre, (c["latitude"], c["longitude"])) <= spread + 1500][:60]
    ranked = []
    for c in nearby:
        point = (c["latitude"], c["longitude"])
        routes = [city.router.route(p["point"], point, no_steps, st) for p, st in zip(people, states)]
        if any(r is None for r in routes):
            continue
        walks = [r["duration_min"] for r in routes]
        longest = max(walks)
        stay = c.get("suggested_visit_duration_min") or 30
        status = hours_status(city.byid[c["poi_id"]], start + timedelta(minutes=longest), stay)
        if status["status"] in ("closed_by_schedule", "closed_reported"):
            continue
        score = c.get("search_score", 0) * 0.5 - longest / 30 - 0.3 * (sum(walks) / len(walks)) / 30
        ranked.append((score, c, routes, walks, status))
    ranked.sort(key=lambda t: t[0], reverse=True)
    items = []
    for score, c, routes, walks, status in ranked[:limit]:
        item = dict(c)
        item["hours_status"] = status
        item["route"] = None
        item["meeting"] = [
            {"name": p["name"], "self": p["self"], "place": p["place"], "walk_min": max(1, round(w))}
            for p, w in zip(people, walks)
        ]
        item["meeting_routes"] = routes
        item["warnings"] = list(item.get("warnings") or []) + (
            [f"Кому-то идти дольше {FAR_WALK_MIN} мин — возможно, удобнее транспорт (его время не проверяется)."]
            if max(walks) > FAR_WALK_MIN
            else []
        )
        items.append(item)
    return {"items": items, "lost": []}


def meeting_line(item):
    """"Вы — 12 мин, Алина — 17 мин, Данияр — 9 мин"."""
    return ", ".join(f"{m['name']} — {m['walk_min']} мин" for m in item["meeting"])
