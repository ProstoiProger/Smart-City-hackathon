"""Validate the bundled records, aliases, review signals and the search index."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.service import City  # noqa: E402


def main():
    data = ROOT / "data"
    pois = [json.loads(l) for l in (data / "pois.jsonl").open(encoding="utf-8")]
    source = [
        json.loads(l) for l in (data / "source_pois.jsonl").open(encoding="utf-8")
    ]
    ids = {p["poi_id"] for p in pois}
    aliases = json.loads((data / "poi_aliases.json").read_text(encoding="utf-8"))
    assert len(ids) == len(pois) == 7431
    assert len(source) == len(aliases) == 7570
    assert all(v in ids for v in aliases.values())
    assert all(
        not p.get("recommendation_eligible") or p.get("name_is_source_backed")
        for p in pois
    )
    city = City()
    assert city.index.matrix.shape[0] == len(pois)
    assert all(pid in ids for pid in city.review_signals)
    report = {
        "canonical_pois": len(pois),
        "source_pois": len(source),
        "id_aliases": len(aliases),
        "lexical_index": "passed",
        "pois_with_review_signals": len(city.review_signals),
        "queries": [],
    }
    for q in ["тихое кафе с розеткой для работы", "куда сходить с ребёнком"]:
        found = city.search(q, when="2026-10-19T12:00:00", limit=3)
        report["queries"].append(
            {
                "query": q,
                "results": [
                    {
                        "poi_id": p["poi_id"],
                        "name": p["display_name"],
                        "evidence": p["evidence"],
                        "reasons": p["reasons"],
                    }
                    for p in found
                ],
            }
        )
        assert all(city.byid[p["poi_id"]].get("recommendation_eligible") for p in found)
    target = ROOT / "qa" / "semantic_search.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
