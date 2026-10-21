"""A walk with a finish, and re-planning it on the go.

The chat builds the first plan; the client then keeps the walk state (start time, budget,
finish, visited and excluded stops, where the walker is) and sends it back with each
event: "здесь закрыто", "потратили ещё 15 минут", "замёрзли", "устали". The server only
recomputes the rest of the walk from that point with the same retrieval, walking graph
and opening-hours checks, keeping the finish and the arrival deadline.
"""

from datetime import timedelta
from .comfort import exposure
from .hours import parse_when
from .service import toward

# Default spare minutes at a finish the walker must reach in time (not for a loop).
DEFAULT_FINISH_RESERVE_MIN = 10
# Walks between stops after "замёрзли" / "устали".
COLD_LEG_MIN = 10
TIRED_LEG_MIN = 8
# Places to sit down and warm up rank higher for a tired walker.
REST_CATEGORIES = {"food_drink", "quiet_spaces", "culture"}
# Fewer minutes than this left for stops: go straight to the finish.
MIN_STOP_WINDOW = 15


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

    start = parse_when(s.start_at)
    remaining = s.budget - elapsed
    now = start + timedelta(minutes=elapsed)
    when = now.isoformat()
    finish = s.finish.model_dump() if s.finish else None
    reserve = s.reserve if finish else 0
    max_leg = TIRED_LEG_MIN if "rest" in flags else COLD_LEG_MIN if "indoor" in flags else None
    skip = excluded | visited

    def allowed(p):
        return p["poi_id"] not in skip and not ("indoor" in flags and exposure(byid[p["poi_id"]]) == "outdoor")

    route = None
    if target > 0 and remaining - reserve >= MIN_STOP_WINDOW:
        def find(query):
            return [
                p
                for p in city.search(
                    query, s.category, pos, int(remaining), when, s.open_only, s.no_steps, 40,
                    s.strict_amenities, distinct_names=True, max_snap_m=s.max_snap_m,
                    group_size=s.group_size, max_walk_min=max_leg, intent=intent if query else None,
                )
                if allowed(p)
            ]

        pool = find(s.query)
        if len(pool) < target and s.query:
            # The original wish ("парк и кофе") may have nothing indoors or close enough:
            # any good place nearby is better than no plan.
            seen = {p["poi_id"] for p in pool}
            pool += [p for p in find("") if p["poi_id"] not in seen]
        shown = {p["poi_id"] for p in pool}
        kept = [
            city.venue_candidate(k, pos, int(remaining), when, s.no_steps, s.max_snap_m, reason="Остаётся из вашего плана")
            for k in keep
            if k not in shown
        ]
        pool = [c for c in kept if c] + pool
        if "rest" in flags:
            for p in pool:
                if p.get("category") in REST_CATEGORIES:
                    p["search_score"] = p.get("search_score", 0) + 0.15
            pool.sort(key=lambda p: p.get("search_score", 0), reverse=True)
        if finish:
            pool = toward(pool, pos, finish, remaining - reserve)
        route = city.mini_route(
            pool, pos, int(remaining), when, s.no_steps, s.max_snap_m, prefer=set(keep),
            finish=finish, reserve=reserve, sizes=tuple(range(target, 0, -1)), max_leg=max_leg,
        )
    if route is None and finish:
        route = city.direct_route(pos, finish, max(0, int(remaining)), reserve, s.no_steps, s.max_snap_m)

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

    new_ids = [st["poi_id"] for st in (route or {}).get("stops", [])]
    if route and new_ids:
        seq = " → ".join(name(i) for i in new_ids)
        if route.get("finish"):
            f = route["finish"]
            seq += " → " + ("старт" if f["loop"] else f["label"])
            tail = f" Финиш ~в {clock(start, f['arrival_offset_min'])}, запас ~{max(0, round(f['slack_min']))} мин."
        else:
            tail = f" Всего ~{round(route['total_duration_min'])} из {s.budget} мин."
        same = new_ids == keep
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
            "now": now.isoformat(timespec="minutes"),
            "remaining_min": round(remaining, 1),
        },
    }
