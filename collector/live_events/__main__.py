"""Collect current events from the sources in sources.yaml into data/events_live.jsonl.

    python -m collector.live_events                 # every source
    python -m collector.live_events --source sxodim_afisha --limit 20
    python -m collector.live_events --dry-run       # print, write nothing

The app reads data/events_live.jsonl next to the bundled snapshot and prefers the newer record.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.routing import meters  # noqa: E402
from backend.settings import DATA  # noqa: E402

from . import jsonld  # noqa: E402
from .build import ASTANA, Venues, record  # noqa: E402
from .fetch import FetchError, PoliteFetcher  # noqa: E402

SOURCES = Path(__file__).with_name("sources.yaml")
OUT = DATA / "events_live.jsonl"


def listing_links(fetcher, source, errors):
    links = []
    for n in range(1, max(source.get("pages", 1), 1) + 1):
        url = source["url"] if n == 1 else f"{source['url']}{'&' if '?' in source['url'] else '?'}page={n}"
        try:
            page = fetcher.get(url)
        except FetchError as e:
            errors.append(str(e))
            break
        new = [u for u in jsonld.links(page.text, page.url, source["link_pattern"]) if u not in links]
        if not new:
            break
        links += new
    return links[: source.get("max_items", 30)]


def collect(source, fetcher, venues, limit, collected_at):
    errors, rows = [], []
    urls = listing_links(fetcher, source, errors) if source["kind"] == "listing" else [source["url"]]
    for url in urls[:limit]:
        try:
            page = fetcher.get(url)
        except FetchError as e:
            errors.append(str(e))
            continue
        found = jsonld.extract(page.text, page.url)
        # On an event page the main event is the one pointing at this page, else the first.
        main = [e for e in found if e["url"].rstrip("/") == page.url.rstrip("/")] or found[:1]
        rows += [record(e, source, venues, collected_at) for e in main]
    return rows, errors, len(urls)


def upcoming(row, now):
    end = row.get("event_end") or row["event_start"]
    try:
        stamp = datetime.fromisoformat(end)
    except ValueError:
        return True
    stamp = stamp.replace(tzinfo=ASTANA) if stamp.tzinfo is None else stamp
    # A date-only end means the whole day.
    return stamp >= now if len(end) > 10 else stamp.date() >= now.date()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", help="source id; repeat for several (default: all)")
    ap.add_argument("--limit", type=int, default=1000, help="event pages per source")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests to one host")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sources"]
    if args.source:
        sources = [s for s in sources if s["id"] in args.source]
        if not sources:
            ap.error("no such source")
    pois = [json.loads(line) for line in (DATA / "pois.jsonl").open(encoding="utf-8")]
    venues = Venues(pois, meters)
    fetcher = PoliteFetcher(delay_s=args.delay)
    now = datetime.now(timezone.utc).astimezone(ASTANA)
    collected_at = datetime.now(timezone.utc).isoformat()

    rows = {}
    for source in sources:
        got, errors, pages = collect(source, fetcher, venues, args.limit, collected_at)
        kept = [r for r in got if upcoming(r, now)]
        for r in kept:
            rows.setdefault(r["event_id"], r)
        linked = sum(1 for r in kept if r["venue_poi_id"])
        print(f"{source['id']:<22} pages {pages:>3}  events {len(got):>3}  upcoming {len(kept):>3}  at known venue {linked:>3}  errors {len(errors)}")
        for e in errors[:3]:
            print("   ", e)
    if args.dry_run:
        for r in list(rows.values())[:5]:
            print(r["event_start"], r["event_name"], "|", r["event_location"])
        return 0
    if not rows and args.out.exists():
        print("nothing collected: keeping the previous file")
        return 1
    args.out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sorted(rows.values(), key=lambda r: r["event_start"])),
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} events to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
