"""Group mode: every member states a wish, nobody should leave unhappy.

The group score leans on the least satisfied member (0.7 * worst + 0.3 * average), so a place that
suits one person perfectly and another not at all ranks below one that works for everybody.
Each member's fit is explained with the same evidence labels as the cards.
"""

import re
from .query import content_query
from .service import ATTR_LABEL, LABELS, evidence, read_intents

MAX_MEMBERS = 6
MIN_MEMBERS = 2
WORST_WEIGHT = 0.7
# What the evidence for a requested amenity is worth to a member.
EVIDENCE_VALUE = {
    "confirmed": 1.0,
    "supported": 0.85,
    "single_mention": 0.35,
    "unknown": 0.2,
    "mixed": 0.15,
    "contradicted": 0.0,
}
CERTAINTY = {"confirmed": "yes", "supported": "likely", "contradicted": "no"}
LEVEL_MATCH, LEVEL_PARTIAL = 0.75, 0.4


class Member:
    def __init__(self, name, wish):
        self.name = name
        self.wish = wish
        self.preferred, self.wanted = read_intents(wish) if wish else (set(), [])
        self.text = content_query(wish) if wish else ""

    @property
    def neutral(self):
        """No wish: this member is happy with anything the others agree on."""
        return not self.wish


def clean_members(raw):
    """Members with a usable name and wish text; blank names get 'Участник N'."""
    out = []
    for i, m in enumerate(raw or []):
        wish = re.sub(r"\s+", " ", (m.get("wish") or "")).strip()
        name = re.sub(r"\s+", " ", (m.get("name") or "")).strip() or f"Участник {i + 1}"
        out.append(Member(name[:30], wish[:200]))
    return out[:MAX_MEMBERS]


def member_fit(city, p, member, lexical):
    """(score 0..1, marks) of one place for one member."""
    if member.neutral:
        return 1.0, []
    signals = (city.review_signals.get(p["poi_id"]) or {}).get("signals")
    marks, parts = [], []
    if member.preferred:
        ok = p.get("category") in member.preferred
        parts.append((0.6, 1.0 if ok else 0.0))
        marks.append({"label": LABELS.get(p.get("category"), "Другое"), "certainty": "yes" if ok else "no"})
    attrs = []
    for a in member.wanted:
        kind, _ = evidence(p, a, signals)
        attrs.append(EVIDENCE_VALUE.get(kind, 0.2))
        marks.append({"label": ATTR_LABEL[a], "certainty": CERTAINTY.get(kind, "unknown")})
    if attrs:
        parts.append((0.4, sum(attrs) / len(attrs)))
    text = min(1.0, lexical * 2)
    if parts:
        weight = sum(w for w, _ in parts)
        base = sum(w * v for w, v in parts) / weight
        return min(1.0, base + 0.15 * text * (1 - base)), marks
    return text, marks


def level(score):
    return "match" if score >= LEVEL_MATCH else "partial" if score >= LEVEL_PARTIAL else "none"


def group_score(scores):
    return WORST_WEIGHT * min(scores) + (1 - WORST_WEIGHT) * sum(scores) / len(scores)


def group_pool(city, members, origin, minutes, when, open_only, no_steps, limit, strict, max_snap_m, trace=None):
    """Candidates for the whole group, best compromise first, each with `group_fit` per member."""
    pool = {}
    for m in members:
        if m.neutral:
            continue
        for item in city.search(
            m.wish, None, origin, minutes, when, open_only, no_steps, 30, strict,
            distinct_names=True, max_snap_m=max_snap_m, group_size=len(members), trace=trace,
        ):
            pool.setdefault(item["poi_id"], item)
    if not pool:
        for item in city.search(
            "", None, origin, minutes, when, open_only, no_steps, 30, strict,
            distinct_names=True, max_snap_m=max_snap_m, group_size=len(members), trace=trace,
        ):
            pool.setdefault(item["poi_id"], item)
    index = {p["poi_id"]: i for i, p in enumerate(city.pois)}
    lexical = {id(m): city.index.scores(m.text) for m in members if m.text}
    ranked = []
    for item in pool.values():
        p = city.byid[item["poi_id"]]
        fits = []
        for m in members:
            scores = lexical.get(id(m))
            score, marks = member_fit(city, p, m, float(scores[index[p["poi_id"]]]) if scores is not None else 0.0)
            fits.append((m, score, marks))
        worst = min(s for _, s, _ in fits)
        total = group_score([s for _, s, _ in fits])
        item["group_score"] = round(total, 3)
        item["group_fit"] = [
            {"name": m.name, "wish": m.wish, "level": level(s), "marks": marks[:3]} for m, s, marks in fits
        ]
        # The group score decides; the search score only breaks ties between similar compromises.
        walk = (item.get("route") or {}).get("duration_min") or 0
        item["search_score"] = round(total + 0.05 * item.get("search_score", 0) - 0.08 * walk / max(minutes, 1), 4)
        item["group_worst"] = round(worst, 3)
        item["_member_scores"] = [s for _, s, _ in fits]
        ranked.append(item)
    ranked.sort(key=lambda it: it["search_score"], reverse=True)
    picked = cover_everyone(ranked, len(members))
    for item in picked:
        item.pop("_member_scores", None)
    return picked[:limit]


def cover_everyone(ranked, size, picks=3):
    """Best compromise first; if it leaves someone out, the next picks go to the people left out."""
    if not ranked:
        return []
    chosen = [ranked[0]]
    rest = ranked[1:]
    while rest and len(chosen) < picks:
        left_out = [
            i for i in range(size) if all(c["_member_scores"][i] < LEVEL_PARTIAL for c in chosen)
        ]
        if not left_out:
            break
        best = max(rest, key=lambda it: (sum(it["_member_scores"][i] for i in left_out), it["search_score"]))
        if all(best["_member_scores"][i] < LEVEL_PARTIAL for i in left_out):
            break
        chosen.append(best)
        rest.remove(best)
    return chosen + rest
