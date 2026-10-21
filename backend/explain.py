"""Why a place was left out: a funnel of counts plus one coded reason per near-miss.

Reasons are codes with numbers, never prose: the interface words them in the user's language
and the numbers come from the same checks that dropped the place.
"""

FUNNEL = ("matched", "nearby", "reachable", "open", "answer")
PER_CODE = 3


class Trace:
    def __init__(self):
        self.stages = {}
        self.rejected = {}

    def count(self, stage, n=1):
        self.stages[stage] = self.stages.get(stage, 0) + n

    def reject(self, p, code, rank, distance_m=0.0, **params):
        """Keep the reason a place dropped out; the first reason recorded for a place stands."""
        pid = p["poi_id"]
        if pid in self.rejected:
            return
        self.rejected[pid] = {
            "poi_id": pid,
            "name": (p.get("display_name") or p.get("name") or "").split(",")[0],
            "category": p.get("category"),
            "latitude": p.get("latitude"),
            "longitude": p.get("longitude"),
            "code": code,
            "params": params,
            "rank": (round(rank, 4), -round(distance_m)),
        }

    def forget(self, pid):
        self.rejected.pop(pid, None)

    def merge(self, other):
        for stage, n in other.stages.items():
            self.count(stage, n)
        for pid, row in other.rejected.items():
            self.rejected.setdefault(pid, row)
        return self

    def top(self, limit=6, skip=()):
        """Most relevant near-misses first, at most PER_CODE of one reason."""
        taken, per_code = [], {}
        for row in sorted(self.rejected.values(), key=lambda r: r["rank"], reverse=True):
            if row["poi_id"] in skip or per_code.get(row["code"], 0) >= PER_CODE:
                continue
            per_code[row["code"]] = per_code.get(row["code"], 0) + 1
            taken.append({k: v for k, v in row.items() if k != "rank"})
            if len(taken) == limit:
                break
        return taken

    def funnel(self, answered):
        counts = {**self.stages, "answer": answered}
        return [{"key": k, "count": counts[k]} for k in FUNNEL if k in counts]
