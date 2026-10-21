"""Dialogue state for the chat's place lists: follow-ups change the last answer in place.

The client keeps what the conversation is about (the wish, the places on screen, every
place already shown, the refinements in force) and sends it back with the next message.
"Ещё" brings places not shown yet; "убери второе" drops that one and keeps the others in
their order; "без кафе", "ближе", "нас четверо" refine the same wish and stay in force for
the next "ещё". A message with a new interest is a new search: the old refinements and
the list of shown places are dropped. Routes on screen are edited by trip.edit().
"""

from .providers import explain_from_data
from .service import LABELS
from .query import NEARBY_WALK_MIN

# How many places a list answer shows.
LIST_SIZE = 3


def _name(city, pid):
    return (city.byid[pid].get("display_name") or "").split(",")[0]


def refine(city, ctx, ops, *, origin, minutes, when, no_steps, max_snap_m, open_only, strict, intent, lang):
    """The last list changed by a follow-up. `ctx` is the DialogState, `ops` as read by
    intent.read_edit() or trip.read_edit_rules() for that list."""
    byid = city.byid
    current = [i for i in dict.fromkeys(ctx.items) if i in byid]
    shown = set(ctx.shown) | set(current)
    filters = {
        "exclude_categories": list(ctx.filters.get("exclude_categories") or []),
        "max_walk": ctx.filters.get("max_walk"),
        "group_size": ctx.filters.get("group_size"),
    }
    at = lambda k: current[k - 1] if 1 <= k <= len(current) else None
    pinned = {p for p in (at(k) for k in ops["keep"]) if p}
    removed = {p for p in (at(k) for k in ops["remove"]) if p} - pinned
    replaced = {p for p in (at(k) for k in ops["replace"]) if p} - pinned - removed
    notes = []
    for c in ops["exclude_categories"]:
        if c not in filters["exclude_categories"]:
            filters["exclude_categories"].append(c)
    if ops["closer"]:
        filters["max_walk"] = NEARBY_WALK_MIN
        notes.append(f"Только места до {NEARBY_WALK_MIN} мин пешком.")
    if ops["group_size"]:
        filters["group_size"] = ops["group_size"]
        notes.append(f"Подбираю на компанию из {ops['group_size']} человек.")
    if ops["more"]:
        replaced |= set(current) - pinned - removed
    excluded_kinds = set(filters["exclude_categories"])
    if ops["exclude_categories"]:
        notes.append("Без мест: " + ", ".join(LABELS.get(c, c).lower() for c in sorted(excluded_kinds)) + ".")
    kept_objects = {}
    for pid in current:
        if pid in removed or pid in replaced:
            continue
        obj = city.venue_candidate(pid, origin, minutes, when, no_steps, max_snap_m, reason="Остаётся из прошлого ответа")
        walk = ((obj or {}).get("route") or {}).get("duration_min") or 0
        # A refinement applies to the places kept too: a café goes with "без кафе",
        # a far place with "ближе" — they are replaced, not silently kept.
        if obj is None or (pid not in pinned and (
            byid[pid].get("category") in excluded_kinds or (filters["max_walk"] and walk > filters["max_walk"])
        )):
            replaced.add(pid)
            continue
        kept_objects[pid] = obj

    def find(query, its_intent):
        return [
            p
            for p in city.search(
                query, None, origin, minutes, when, open_only, no_steps, 40, strict,
                distinct_names=True, max_snap_m=max_snap_m, group_size=filters["group_size"],
                max_walk_min=filters["max_walk"], intent=its_intent if query else None,
            )
            if p["poi_id"] not in shown and p.get("category") not in excluded_kinds
        ]

    added = find(ops["add"], None)[:1] if ops["add"] else []
    fresh = [p for p in find(ctx.query, intent) if p["poi_id"] not in {a["poi_id"] for a in added}]
    out, fill = [], iter(fresh)
    for pid in current:
        if pid in removed:
            continue
        if pid in replaced:
            nxt = next(fill, None)
            if nxt:
                out.append(nxt)
            continue
        out.append(kept_objects[pid])
    out += added
    if not current:
        out = fresh[:LIST_SIZE]

    if removed:
        notes.insert(0, "Убрал " + ", ".join(f"«{_name(city, i)}»" for i in removed) + ", остальные оставил.")
    if pinned:
        notes.insert(0, "Оставил " + ", ".join(f"«{_name(city, i)}»" for i in pinned) + ".")
    new_ids = [p["poi_id"] for p in out]
    got = [i for i in new_ids if i not in current]
    missing = len(replaced) - len([i for i in got if i not in {a["poi_id"] for a in added}])
    if ops["more"] or replaced:
        notes.append(
            ("Новые варианты, которых вы ещё не видели: " + ", ".join(f"«{_name(city, i)}»" for i in got) + "." if got else "")
            + (" Больше подходящих мест, которых вы ещё не видели, рядом нет — измените время, место старта или запрос."
               if missing > 0 else "")
        )
    if added:
        notes.append(f"Добавил «{_name(city, added[0]['poi_id'])}».")
    elif ops["add"]:
        notes.append(f"Подходящего места для «{ops['add']}» рядом не нашлось.")

    items = []
    for p in out:
        item = dict(p)
        pick = explain_from_data(p, lang, p.get("suggested_visit_duration_min"))
        item.update(why=pick["why"], what_to_do=pick["what_to_do"], events=[])
        item["explanation"] = {
            "generated": False, "template": True, "basis": pick["basis"],
            "note": "«Почему» и «что делать» собраны по шаблону из данных места, без генерации; «что делать» — идея, а не проверенный факт.",
        }
        items.append(item)
    state = {
        "query": ctx.query,
        "intent": ctx.intent,
        "items": new_ids,
        "shown": sorted(shown | set(new_ids)),
        "filters": filters,
    }
    return {"answer": " ".join(n for n in notes if n).strip() or "Подборка обновлена.", "items": items, "dialog": state}
