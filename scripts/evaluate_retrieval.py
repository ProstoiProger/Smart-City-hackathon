"""Frozen product regression cases; reports are not general relevance estimates."""

import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np


def main():
    home = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=home)
    parser.add_argument(
        "--output", type=Path, default=home / "qa/retrieval_current.json"
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.project.resolve()))
    from backend.service import City

    cases = json.loads((home / "qa/rag_cases.json").read_text(encoding="utf-8"))
    city = City()
    results = []
    for case in cases:
        start = time.perf_counter()
        items = city.search(case["query"], when=case["when"], limit=case["limit"])
        latency = (time.perf_counter() - start) * 1000
        expected = {city.id_aliases.get(i, i) for i in case["expected_any_id"]}
        found = {p["poi_id"] for p in items}
        correct = (
            bool(items)
            and (not expected or bool(expected & found))
            and (
                not case["allowed_categories"]
                or all(p["category"] in case["allowed_categories"] for p in items)
            )
        )
        results.append(
            {
                "query": case["query"],
                "passed": correct,
                "latency_ms": round(latency, 2),
                "ids": [p["poi_id"] for p in items],
                "names": [p["display_name"] for p in items],
            }
        )
    report = {
        "backend": "tfidf",
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "pass_rate": sum(r["passed"] for r in results) / len(results),
        "p95_ms_including_first_query": round(
            float(np.percentile([r["latency_ms"] for r in results], 95)), 2
        ),
        "evaluation_kind": "fixed_product_regression_not_general_quality_benchmark",
        "results": results,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "backend": "tfidf",
                "passed": report["passed"],
                "cases": len(results),
                "failed": [r["query"] for r in results if not r["passed"]],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
