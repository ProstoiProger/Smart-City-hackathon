"""Bounded publisher refresh: one request per unique event URL, no confirmed-visit claims."""

from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import threading
from urllib.parse import urlparse
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.events import ALLOWED, fetch_publisher_page, event_claim


def main():
    events = [
        json.loads(l) for l in (ROOT / "data/events.jsonl").open(encoding="utf-8")
    ]
    groups = defaultdict(list)
    for event in events:
        groups[event.get("registration_url") or event.get("source_url")].append(event)
    paused = threading.Event()

    def collect(pair):
        url, rows = pair
        stamp = datetime.now(timezone.utc).isoformat()
        status = "unsupported_publisher"
        body = None
        if urlparse(url or "").hostname in ALLOWED and not paused.is_set():
            try:
                url, body, stamp = fetch_publisher_page(url)
                status = "retrieved"
            except httpx.HTTPStatusError as exc:
                status = "http_" + str(exc.response.status_code)
                if exc.response.status_code in (403, 429):
                    paused.set()
            except Exception:
                status = "source_unavailable"
        elif paused.is_set():
            status = "deferred_after_publisher_rejection"
        results = []
        for event in rows:
            result = {
                "event_id": event["event_id"],
                "source_url": url,
                "publisher_rechecked_at": stamp,
                "fetch_status": status,
                "source_page_available": body is not None,
                "independently_confirmed": False,
                "live_verified": False,
            }
            if body is not None:
                result.update(event_claim(body, event))
            else:
                result["note"] = (
                    "Источник не проверен; исходный анонс не считается подтверждением проведения."
                )
            results.append(result)
        return results

    checks = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed(
            [pool.submit(collect, pair) for pair in groups.items()]
        ):
            checks += future.result()
            if len(checks) % 10 == 0:
                print(
                    "Event records reviewed:", len(checks), "/", len(events), flush=True
                )
    byid = {c["event_id"]: c for c in checks}
    for event in events:
        check = byid[event["event_id"]]
        event["publisher_recheck"] = check
        if check.get("occurrence_identified") and check.get("publisher_status"):
            event["event_status"] = check["publisher_status"]
            event["event_status_observed_at"] = check["publisher_rechecked_at"]
    for filename, rows in [
        ("events.jsonl", events),
        ("event_publisher_checks.jsonl", checks),
    ]:
        with (ROOT / "data" / filename).open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
    report = {
        "records": len(events),
        "unique_source_urls": len(groups),
        "fetch_status_counts": dict(Counter(c["fetch_status"] for c in checks)),
        "occurrences_identified": sum(
            c.get("occurrence_identified", False) for c in checks
        ),
        "cancelled_as_reported": sum(
            c.get("cancelled_as_reported", False) for c in checks
        ),
        "independently_confirmed": 0,
    }
    (ROOT / "qa/event_refresh_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
