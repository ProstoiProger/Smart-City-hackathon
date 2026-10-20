"""Build a portable app dataset from the existing collection, without network calls."""

from pathlib import Path
import argparse
import collections
import hashlib
import json
import shutil
import numpy as np
from scipy.sparse import csr_matrix, save_npz


def read(path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parents[2] / "data"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = root / "data"
    out.mkdir(exist_ok=True)
    source = args.source / "processed"
    pois = list(read(source / "pois.jsonl"))
    fresh = {}
    for f in (args.source / "raw" / "venue_details").glob("*.json"):
        blob = json.loads(f.read_text(encoding="utf-8"))
        for p in blob.get("response", {}).get("result", {}).get("items", []):
            fresh[str(p["id"])] = (p, blob.get("collected_at"))
    flagged = 0
    import re

    for p in pois:
        ids = [str(p.get("poi_id", "")).removeprefix("dgis:")]
        ids.extend(
            str(v)
            for k, v in (p.get("external_ids") or {}).items()
            if "2gis" in k.lower() or "dgis" in k.lower()
        )
        urls = [p.get("source_url") or ""] + [
            s.get("url", "") for s in p.get("sources") or []
        ]
        ids.extend(i for u in urls for i in re.findall(r"/firm/(\d+)", u))
        for pid in ids:
            if pid not in fresh:
                continue
            record, date = fresh[pid]
            flags = record.get("flags") or {}
            temporary = flags.get("temporary_closed")
            if temporary is not None and temporary is not False:
                p["_provider_closure"] = {
                    "claim": temporary,
                    "collected_at": date,
                    "source_url": f"https://2gis.kz/astana/firm/{pid}",
                }
                flagged += 1
                break
            if record.get("is_deleted") is True:
                p["_provider_closure"] = {
                    "claim": "removed_from_provider_catalog",
                    "collected_at": date,
                    "source_url": f"https://2gis.kz/astana/firm/{pid}",
                }
                flagged += 1
                break
    with (out / "pois.jsonl").open("w", encoding="utf-8") as f:
        for p in pois:
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")
    for src, dst in [
        ("demo_landmarks.json", "landmarks.json"),
        ("source_registry.json", "source_registry.json"),
        ("routing_summary.json", "routing_source_summary.json"),
        ("summary.json", "dataset_source_summary.json"),
        ("demo_scenarios.json", "source_demo_scenarios.json"),
    ]:
        if (source / src).exists():
            shutil.copy2(source / src, out / dst)
    nodes = list(read(source / "pedestrian_nodes.jsonl"))
    ids = {n["node_id"]: i for i, n in enumerate(nodes)}
    coords = np.array(
        [[n["latitude"], n["longitude"]] for n in nodes], dtype=np.float64
    )
    rows = []
    cols = []
    seconds = []
    nr = []
    nc = []
    ns = []
    excluded = collections.Counter()
    # Edges are directed. Unresolved conditional/opening constraints are excluded conservatively.
    for e in read(source / "pedestrian_edges.jsonl"):
        if e.get("conditional_access") or e.get("opening_hours"):
            excluded["conditional_or_scheduled"] += 1
            continue
        a, b = ids[e["from_node"]], ids[e["to_node"]]
        t = e["length_m"] / (0.65 if e.get("highway") == "steps" else 1.25)
        rows.append(a)
        cols.append(b)
        seconds.append(t)
        if e.get("highway") != "steps":
            nr.append(a)
            nc.append(b)
            ns.append(t)
    graphdir = out / "graph"
    graphdir.mkdir(exist_ok=True)
    np.save(graphdir / "coordinates.npy", coords)
    for name, r, c, s in [
        ("walking_seconds", rows, cols, seconds),
        ("no_steps_seconds", nr, nc, ns),
    ]:
        save_npz(
            graphdir / (name + ".npz"),
            csr_matrix((s, (r, c)), shape=(len(nodes), len(nodes))),
        )
    report = {
        "pois": len(pois),
        "nodes": len(nodes),
        "directed_edges": len(rows),
        "closure_flags_applied": flagged,
        "excluded_edges": dict(excluded),
        "date": "2026-10-19",
        "all_venue_prices_rules_closures_complete": False,
        "warnings": [
            "Snapshot, not live availability.",
            "Venue conditions remain incomplete.",
            "OSM routes use unverified snaps up to 80m; no verified door-to-door access.",
            "No user data is persisted.",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    from normalize_data import normalize

    normalize(root, source)


if __name__ == "__main__":
    main()
