"""A walk with a finish, and re-planning it on the go.

The chat builds the first plan; the client then keeps the walk state (start time, budget,
finish, visited and excluded stops, where the walker is) and sends it back with each
event: "здесь закрыто", "потратили ещё 15 минут", "замёрзли", "устали". The server only
recomputes the rest of the walk from that point with the same retrieval, walking graph
and opening-hours checks, keeping the finish and the arrival deadline.
"""

import re
from datetime import timedelta
from itertools import zip_longest
from .comfort import exposure
from .hours import closure, hours_status, parse_when
from .query import COVER, cover_groups
from .routing import meters
from .service import LABELS, read_intents, toward

# Default spare minutes at a finish the walker must reach in time (not for a loop).
DEFAULT_FINISH_RESERVE_MIN = 10
# Walks between stops after "замёрзли" / "устали".
COLD_LEG_MIN = 10
TIRED_LEG_MIN = 8
# Places to sit down and warm up rank higher for a tired walker.
REST_CATEGORIES = {"food_drink", "quiet_spaces", "culture"}
# Fewer minutes than this left for stops: go straight to the finish.
MIN_STOP_WINDOW = 15
# Most stops a route holds (every order of the candidates is checked).
MAX_STOPS = 3
# "Ближе": walks between stops after the edit.
CLOSER_LEG_MIN = 10
# Plan B: within this walk of the stop, of the same kind, or under a roof for outdoor stops.
BACKUP_RADIUS_MIN = 8
INDOOR_BACKUP = {"food_drink", "culture", "shopping", "quiet_spaces", "entertainment", "children"}


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def stops_word(n):
    return f"{n} {plural(n, 'остановка', 'остановки', 'остановок')}"


def clock(start, offset):
    # Rounded like the client's clock, so the text and the itinerary show the same minute.
    return (start + timedelta(minutes=round(offset))).strftime("%H:%M")


def stamp_finish(route, start):
    """Clock times for the finish: when the walker gets there and the deadline."""
    f = (route or {}).get("finish")
    if f:
        f["arrival_at"] = (start + timedelta(minutes=round(f["arrival_offset_min"]))).isoformat(timespec="minutes")
        f["deadline_at"] = (start + timedelta(minutes=route["budget_minutes"])).isoformat(timespec="minutes")
    return route


def finish_place(f):
    return "к началу прогулки" if f["loop"] else f"в «{f['label']}»"


def finish_text(route, start):
    """One honest sentence about the way to the finish (RU, like the rest of the answer)."""
    f = route["finish"]
    n = len(route["stops"])
    arrive, budget, reserve = round(f["arrival_offset_min"]), route["budget_minutes"], f["reserve_min"]
    slack = max(0, round(f["slack_min"]))
    at = clock(start, f["arrival_offset_min"])
    where = finish_place(f)
    if n:
        head = "Круговой маршрут" if f["loop"] else f"Маршрут до «{f['label']}»"
        return (
            f"{head}: {stops_word(n)} по пути, будете {where} ~в {at} (через ~{arrive} мин из {budget}), "
            f"пешком всего ~{round(route['walk_duration_min'])} мин, запас ~{slack} мин."
        )
    walk = round(f["leg"]["duration_min"])
    deadline = clock(start, budget)
    if f["fits"]:
        return (
            f"Остановка по пути до срока {deadline} не помещается. Идите сразу: {where} пешком ~{walk} мин, "
            f"будете ~в {at} с запасом ~{slack} мин."
        )
    if arrive <= budget:
        return (
            f"Успеваете только впритык: {where} пешком ~{walk} мин, будете ~в {at} при сроке {deadline}, "
            f"запас меньше {reserve} мин. Остановки по пути не поместятся."
        )
    return (
        f"Пешком к сроку не успеть: {where} ~{walk} мин по пешеходному графу, будете ~в {at}, а срок — {deadline}. "
        "Остановки по пути не поместятся. Нужен транспорт — его время приложение не проверяет."
    )


def replan(city, s, intent=None):
    """Rest of the walk after an event; `s` is the ReplanRequest, `intent` the wish as
    Gemini read it for the first plan (None: the word rules read `s.query`)."""
    byid = city.byid
    name = lambda pid: (byid[pid].get("display_name") or "").split(",")[0]
    flags = set(s.flags)
    excluded, visited = set(s.excluded), set(s.visited)
    keep = [i for i in dict.fromkeys(s.keep) if i in byid and i not in excluded | visited]
    pos = (s.position.latitude, s.position.longitude)
    elapsed = float(s.elapsed)
    target = len(keep)
    require = ()
    notes = []
    if s.action == "closed":
        cid = s.stop_id if s.stop_id in byid else (keep[0] if keep else None)
        if cid:
            excluded.add(cid)
            if cid in keep:
                keep.remove(cid)  # the count stays: a replacement is looked for
            else:
                target += 1
            pos = (byid[cid]["latitude"], byid[cid]["longitude"])
            notes.append(f"«{name(cid)}» закрыто — убрал из плана и ищу замену рядом.")
    elif s.action == "delay":
        elapsed += s.delay_min
        notes.append(f"Учёл ещё {s.delay_min} мин.")
    elif s.action == "cold":
        flags.add("indoor")
        outside = [k for k in keep if exposure(byid[k]) == "outdoor"]
        keep = [k for k in keep if k not in outside]
        notes.append(
            f"Замёрзли: дальше только места под крышей и переходы до {COLD_LEG_MIN} мин"
            + (f"; «{'», «'.join(name(k) for k in outside)}» на улице — ищу замену." if outside else ".")
        )
    elif s.action == "tired":
        flags.add("rest")
        target = max(0, target - 1)
        notes.append(
            f"Устали: на одну остановку меньше, переходы до {TIRED_LEG_MIN} мин, выше места, где можно посидеть."
        )
    elif s.action == "swap":
        # Plan B taken: the backup replaces the stop, the other stops stay as they are.
        old, new = s.stop_id, s.replacement_id
        if old in keep and new in byid and new not in excluded | visited:
            keep[keep.index(old)] = new
            excluded.add(old)
            require = tuple(keep)
            notes.append(f"Вместо «{name(old)}» — запасной вариант «{name(new)}».")
    return rebuild(
        city, s, intent, pos=pos, elapsed=elapsed, keep=keep, target=target,
        excluded=excluded, visited=visited, flags=flags, notes=notes, require=require,
    )


def rebuild(
    city, s, intent, *, pos, elapsed, keep, target, excluded, visited, flags, notes,
    require=(), drop_categories=(), extra_query="", max_leg=None, group_size=None,
):
    """The rest of a walk from `pos` after `elapsed` minutes: `keep` are the planned stops
    to prefer, `require` the ones that must stay, `target` how many stops to aim for.
    Re-planning, edits in words and plan B swaps all end here, with the same checks."""
    byid = city.byid
    name = lambda pid: (byid[pid].get("display_name") or "").split(",")[0]
    start = parse_when(s.start_at)
    remaining = s.budget - elapsed
    now = start + timedelta(minutes=elapsed)
    when = now.isoformat()
    finish = s.finish.model_dump() if s.finish else None
    reserve = s.reserve if finish else 0
    legs_cap = [m for m in (
        TIRED_LEG_MIN if "rest" in flags else COLD_LEG_MIN if "indoor" in flags else None, max_leg,
    ) if m]
    max_leg = min(legs_cap) if legs_cap else None
    group_size = group_size or s.group_size
    drop = set(drop_categories)
    skip = excluded | visited
    keep = [k for k in keep if k not in skip and byid[k].get("category") not in drop or k in require]
    target = min(MAX_STOPS, max(target, len(require)))

    def allowed(p):
        return (
            p["poi_id"] not in skip
            and p.get("category") not in drop
            and not ("indoor" in flags and exposure(byid[p["poi_id"]]) == "outdoor")
        )

    def find(query, its_intent=None, category=None):
        return [
            p
            for p in city.search(
                query, category or s.category, pos, int(remaining), when, s.open_only, s.no_steps, 40,
                s.strict_amenities, distinct_names=True, max_snap_m=s.max_snap_m,
                group_size=group_size, max_walk_min=max_leg, intent=its_intent if query else None,
            )
            if allowed(p)
        ]

    route = None
    if target > 0 and remaining - reserve >= MIN_STOP_WINDOW:
        pool = find(extra_query) if extra_query else []
        seen = {p["poi_id"] for p in pool}
        # The kinds the walk was asked for together stay in it after any change.
        wished = (
            intent["categories"] if intent and intent["combine"]
            else [] if intent else [cat for _, cat in cover_groups(s.query)]
        )
        wished = [c for c in wished if c not in drop]
        cover = sorted(read_intents(extra_query)[0])[:1] if extra_query else wished[:target]
        if wished:
            for row in zip_longest(*[find(s.query, intent, c) for c in wished]):
                for p in row:
                    if p and p["poi_id"] not in seen:
                        seen.add(p["poi_id"])
                        pool.append(p)
        pool += [p for p in find(s.query, intent) if p["poi_id"] not in seen]
        if len(pool) < target and s.query:
            # The original wish ("парк и кофе") may have nothing indoors or close enough:
            # any good place nearby is better than no plan.
            seen = {p["poi_id"] for p in pool}
            pool += [p for p in find("") if p["poi_id"] not in seen]
        shown = {p["poi_id"] for p in pool}
        kept = [
            city.venue_candidate(k, pos, int(remaining), when, s.no_steps, s.max_snap_m, reason="Остаётся из вашего плана")
            for k in dict.fromkeys([*require, *keep])
            if k not in shown
        ]
        pool = [c for c in kept if c] + pool
        if "rest" in flags:
            for p in pool:
                if p.get("category") in REST_CATEGORIES:
                    p["search_score"] = p.get("search_score", 0) + 0.15
            pool.sort(key=lambda p: p.get("search_score", 0), reverse=True)
        if finish:
            pinned = [p for p in pool if p["poi_id"] in require]
            pool = pinned + [p for p in toward(pool, pos, finish, remaining - reserve) if p["poi_id"] not in require]
        route = city.mini_route(
            pool, pos, int(remaining), when, s.no_steps, s.max_snap_m, prefer=set(keep),
            finish=finish, reserve=reserve, sizes=tuple(range(target, 0, -1)), max_leg=max_leg,
            require=require, cover=cover,
        )
        if route is None and require:
            notes.append("С закреплёнными местами маршрут в оставшееся время не складывается — подобрал без них.")
            route = city.mini_route(
                pool, pos, int(remaining), when, s.no_steps, s.max_snap_m, prefer=set(keep),
                finish=finish, reserve=reserve, sizes=tuple(range(target, 0, -1)), max_leg=max_leg,
            )
    if route is None and finish:
        route = city.direct_route(pos, finish, max(0, int(remaining)), reserve, s.no_steps, s.max_snap_m)
    if route and not route.get("covers_requested", True):
        notes.append(route["warnings"][0])

    if route:
        # Offsets count from the start of the whole walk, like the first plan.
        for stop in route["stops"]:
            stop["arrival_offset_min"] = round(stop["arrival_offset_min"] + elapsed)
        route["total_duration_min"] = round(route["total_duration_min"] + elapsed, 1)
        route["budget_minutes"] = s.budget
        if route.get("finish"):
            f = route["finish"]
            f["arrival_offset_min"] = round(f["arrival_offset_min"] + elapsed, 1)
            f["slack_min"] = round(s.budget - f["arrival_offset_min"], 1)
            f["fits"] = f["arrival_offset_min"] + reserve <= s.budget
        stamp_finish(route, start)
        add_backups(city, route, pos, start, s.budget, reserve, s.no_steps, s.max_snap_m, skip)

    new_ids = [st["poi_id"] for st in (route or {}).get("stops", [])]
    if route and new_ids:
        seq = " → ".join(name(i) for i in new_ids)
        if route.get("finish"):
            f = route["finish"]
            seq += " → " + ("старт" if f["loop"] else f["label"])
            tail = f" Финиш ~в {clock(start, f['arrival_offset_min'])}, запас ~{max(0, round(f['slack_min']))} мин."
        else:
            tail = f" Всего ~{round(route['total_duration_min'])} из {s.budget} мин."
        # Unchanged against the plan the walker had, not against what is left after the edit.
        before = [k for k in dict.fromkeys(s.keep) if k in byid and k not in visited]
        same = new_ids == before and not require
        line = ("План прежний, всё ещё успеваете: " if same else "Новый план: ") + seq + "." + tail
    elif route:
        line = finish_text(route, start)
        if route["finish"]["fits"]:
            line = "Остановок больше не помещается. " + line.split(". ", 1)[-1]
    else:
        line = f"В оставшиеся ~{max(0, round(remaining))} мин новых остановок не помещается — прогулку можно заканчивать."

    return {
        "answer": " ".join(notes + [line]),
        "plan": route,
        "changes": {
            "removed": [name(k) for k in s.keep if k in byid and k not in new_ids],
            "added": [name(i) for i in new_ids if i not in s.keep],
        },
        "state": {
            "elapsed": round(elapsed, 1),
            "position": {"latitude": pos[0], "longitude": pos[1]},
            "excluded": sorted(excluded),
            "visited": sorted(visited),
            "flags": sorted(flags),
            "group_size": group_size,
            "now": now.isoformat(timespec="minutes"),
            "remaining_min": round(remaining, 1),
        },
    }


# --- plan B next to every stop ----------------------------------------------------------

def add_backups(city, route, origin, start, budget, reserve, no_steps, max_snap_m, skip=()):
    """For each stop, a backup within a short walk of it: another café for a café, a place
    under a roof for an outdoor stop. `backup.fits` says whether the whole walk still fits
    the budget (and the finish deadline) when the backup is taken instead."""
    stops, legs = route.get("stops") or [], route.get("legs") or []
    if not stops:
        return route
    f = route.get("finish")
    used = {s["poi_id"] for s in stops} | set(skip)
    points = [origin] + [(s["latitude"], s["longitude"]) for s in stops]
    end = f["arrival_offset_min"] if f else route["total_duration_min"]
    limit = budget - (reserve if f else 0)
    states = {}

    def state(point, minutes):
        key = (point, minutes)
        if key not in states:
            states[key] = city.router.paths(point, no_steps, max_minutes=minutes, max_snap_m=max_snap_m)
        return states[key]

    for i, stop in enumerate(stops):
        here = points[i + 1]
        near = state(here, BACKUP_RADIUS_MIN)
        if near is None or i >= len(legs):
            continue
        place = city.byid[stop["poi_id"]]
        outdoor = exposure(place) == "outdoor"
        nxt = points[i + 2] if i + 1 < len(stops) else ((f["latitude"], f["longitude"]) if f else None)
        leg_in = legs[i]["duration_min"]
        leg_out = (legs[i + 1]["duration_min"] if i + 1 < len(legs) else f["leg"]["duration_min"] if f else 0)
        options = []
        for p in city.pois:
            if p["poi_id"] in used or not p.get("recommendation_eligible", True) or closure(p):
                continue
            if meters(here, (p["latitude"], p["longitude"])) > BACKUP_RADIUS_MIN * 80:
                continue
            if outdoor:
                if exposure(p) == "outdoor" or p.get("category") not in INDOOR_BACKUP:
                    continue
            elif p.get("category") != place.get("category"):
                continue
            score = (0.3 if p.get("subcategory") == place.get("subcategory") else 0) + max(
                0, ((p.get("rating_bayesian") or 3) - 3) / 2
            ) * 0.3
            options.append((score, p))
        options.sort(key=lambda t: t[0], reverse=True)
        best = None
        for score, p in options[:10]:
            point = (p["latitude"], p["longitude"])
            walk = city.router.route(here, point, no_steps, near)
            into = city.router.route(points[i], point, no_steps, state(points[i], 60))
            if walk is None or into is None:
                continue
            # Back from the backup to the next point: the reverse walk is a close estimate.
            out = city.router.route(nxt, point, no_steps, state(nxt, 60)) if nxt else None
            if nxt and out is None:
                continue
            delta = into["duration_min"] + (out["duration_min"] if out else 0) - leg_in - leg_out
            arrival = stop["arrival_offset_min"] - leg_in + into["duration_min"]
            visit = stop["suggested_visit_duration_min"]
            status = hours_status(p, start + timedelta(minutes=arrival), visit)
            if status["status"] in ("closed_by_schedule", "closed_reported"):
                continue
            fits = end + delta <= limit
            key = (fits, score, -walk["duration_min"])
            if best is None or key > best[0]:
                best = (key, p, walk, delta, status, fits)
        if not best:
            continue
        _, p, walk, delta, status, fits = best
        used.add(p["poi_id"])
        stop["backup"] = {
            "poi_id": p["poi_id"],
            "display_name": p.get("display_name"),
            "category": p.get("category"),
            "subcategory_label": p.get("subcategory_label"),
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "rating": p.get("rating"),
            "walk_from_stop_min": max(1, round(walk["duration_min"])),
            "delta_min": round(delta),
            "fits": fits,
            "hours_status": status,
            "kind": "indoor" if outdoor else "same",
        }
    return route


def backup_text(stop):
    """"Если здесь не получится — …": one line for the answer and the itinerary."""
    b = stop.get("backup")
    if not b:
        return None
    name = (b["display_name"] or "").split(",")[0]
    what = "под крышей " if b["kind"] == "indoor" else ""
    budget = "в общий бюджет помещается" if b["fits"] else f"выйдет на ~{max(1, b['delta_min'])} мин дольше бюджета"
    return f"Если в «{(stop.get('display_name') or '').split(',')[0]}» не получится — {what}«{name}» в {b['walk_from_stop_min']} мин оттуда, {budget}."


# --- editing a route in plain words --------------------------------------------------------

ORDINALS = [
    (r"перв\w*|1-?(?:е|ю|ое|ую|й)?\b|бірінші\w*|first", 1),
    (r"втор\w*|2-?(?:е|ю|ое|ую|й)?\b|екінші\w*|second", 2),
    (r"трет\w*|3-?(?:е|ю|ее|ью|й)?\b|үшінші\w*|third", 3),
    (r"последн\w*|соңғ\w*|\blast\b", -1),
]
KEEP_WORDS = r"остав|сохран|не\s+трог|нрав|keep|қалдыр"
REPLACE_WORDS = r"замен|помен|смен|другое\s+вместо|друг\w+\s+(?:место|кафе|музей|парк)|replace|change|swap|ауыстыр"
REMOVE_WORDS = r"убер|убра|удал|выкин|не\s+надо|не\s+нужн|remove|drop|skip|алып\s+таста|керек\s+емес"
MORE_WORDS = r"ещ[её]\s+вариант|други[ех]\s+вариант|другой\s+вариант|покажи\s+ещ[её]|другие\s+места|more\s+options|other\s+options|басқа\s+нұсқа"
CLOSER_WORDS = r"ближе|поближе|недалеко|покороче|меньше\s+(?:идти|ходить)|closer|nearer|жақынырақ"
ADD_WORDS = r"добав\w*\s+(?:ещ[её]\s+)?(.+)|\badd\s+(?:a\s+|an\s+)?(.+)|қос\w*\s+(.+)"
WITHOUT = r"(?:без\s+|не\s+хочу\s+(?:в\s+)?|не\s+надо\s+|without\s+|no\s+)(\w+)"


def read_edit_rules(text, count, group=None):
    """Edit operations from plain words, for a route of `count` stops (no model)."""
    low = str(text or "").casefold()
    ops = {"is_edit": False, "keep": [], "replace": [], "remove": [], "exclude_categories": [],
           "closer": False, "more": False, "group_size": group, "add": ""}
    for clause in re.split(r"[,.;!?]|\s(?:а|и|но|and|but)\s", low):
        nums = []
        for rx, n in ORDINALS:
            if re.search(r"(?<!\w)(?:" + rx + r")", clause):
                nums.append(count if n == -1 else n)
        nums = [n for n in nums if 1 <= n <= count]
        if not nums:
            continue
        if re.search(KEEP_WORDS, clause):
            ops["keep"] += nums
        elif re.search(REPLACE_WORDS, clause):
            ops["replace"] += nums
        elif re.search(REMOVE_WORDS, clause):
            ops["remove"] += nums
    for m in re.finditer(WITHOUT, low):
        word = m.group(1)
        for _, rx, cat in COVER:
            if re.search(rx, word) and cat not in ops["exclude_categories"]:
                ops["exclude_categories"].append(cat)
    ops["more"] = bool(re.search(MORE_WORDS, low))
    ops["closer"] = bool(re.search(CLOSER_WORDS, low))
    added = re.search(ADD_WORDS, low)
    if added:
        ops["add"] = next(g for g in added.groups() if g).strip()[:120]
    # "Хочу кафе поближе" is a new request; "поближе" or "ещё ближе" alone edits the route.
    short = len(re.findall(r"\w+", low)) <= 4
    ops["is_edit"] = bool(
        ops["keep"] or ops["replace"] or ops["remove"] or ops["exclude_categories"] or ops["more"]
        or (ops["closer"] and short) or ops["add"] or group
    )
    return ops


def edit(city, ctx, ops, intent=None, lang="ru"):
    """The current route changed by words: pinned stops stay, replaced and removed ones go,
    excluded kinds of places are dropped, "ближе" caps the walks, a new company size ranks
    places for it. The rest is rebuilt from where the walker is, with all checks."""
    byid = city.byid
    name = lambda pid: (byid[pid].get("display_name") or "").split(",")[0]
    excluded, visited = set(ctx.excluded), set(ctx.visited)
    stops = [i for i in dict.fromkeys(ctx.keep) if i in byid and i not in excluded | visited]
    at = lambda k: stops[k - 1] if 1 <= k <= len(stops) else None
    pinned = [p for p in (at(k) for k in ops["keep"]) if p]
    replaced = {p for p in (at(k) for k in ops["replace"]) if p} - set(pinned)
    removed = {p for p in (at(k) for k in ops["remove"]) if p} - set(pinned)
    drop = set(ops["exclude_categories"])
    if ops["more"]:
        replaced |= set(stops) - set(pinned) - removed
    dropped = {i for i in stops if byid[i].get("category") in drop and i not in pinned}
    excluded |= replaced | removed | dropped
    keep = [i for i in stops if i not in excluded]
    target = len(stops) - len(removed) + (1 if ops["add"] else 0)
    if not stops:
        target = max(target, 1)
    notes = []
    if ops["add"] and len(pinned) >= MAX_STOPS:
        notes.append(
            f"В маршруте не больше {MAX_STOPS} мест, и все они закреплены — чтобы добавить «{ops['add']}», скажите, какое место убрать."
        )
        ops = {**ops, "add": ""}
        target -= 1
    elif ops["add"]:
        # Adding keeps the current stops; a full route gives up its last unpinned stop.
        base = pinned + [k for k in keep if k not in pinned]
        pinned = base[: MAX_STOPS - 1]
        gone = base[MAX_STOPS - 1 :]
        if gone:
            excluded |= set(gone)
            notes.append(
                f"В маршруте не больше {MAX_STOPS} мест — " + ", ".join(f"«{name(i)}»" for i in gone) + " уступает место новому."
            )
    if pinned:
        notes.append("Оставил " + ", ".join(f"«{name(i)}»" for i in pinned) + ".")
    if replaced:
        notes.append("Ищу замену для " + ", ".join(f"«{name(i)}»" for i in replaced) + ".")
    if removed:
        notes.append("Убрал " + ", ".join(f"«{name(i)}»" for i in removed) + ".")
    if drop:
        notes.append("Без мест: " + ", ".join(LABELS.get(c, c).lower() for c in sorted(drop)) + ".")
    if ops["closer"]:
        notes.append(f"Переходы между местами — до {CLOSER_LEG_MIN} мин.")
    if ops["group_size"]:
        notes.append(f"Подбираю на компанию из {ops['group_size']} человек.")
    if ops["add"]:
        notes.append(f"Добавляю: {ops['add']}.")
    out = rebuild(
        city, ctx, intent,
        pos=(ctx.position.latitude, ctx.position.longitude), elapsed=float(ctx.elapsed),
        keep=keep, target=target, excluded=excluded, visited=visited, flags=set(ctx.flags), notes=notes,
        require=tuple(pinned), drop_categories=drop, extra_query=ops["add"],
        max_leg=CLOSER_LEG_MIN if ops["closer"] else None, group_size=ops["group_size"],
    )
    out["ops"] = ops
    return out
