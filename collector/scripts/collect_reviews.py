"""First page of public 2GIS reviews per dataset branch.

Targeted pass for RAG attributes: only the reviews already embedded in the public
`/firm/{id}/tab/reviews` HTML (React Query state). Pagination links are never
followed or stored: they carry an access parameter of the site's internal API.
Author profiles, names and photos are not saved. One request per second, and the
run stops on any access check, 401/403 or repeated 429 instead of working around it.

    python -m scripts.collect_reviews --pilot 10
    python -m scripts.collect_reviews --limit 500
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
APP_DATA = ROOT.parent / "data"
OUT = ROOT / "output" / "reviews_2gis"
PAGE_URL = "https://2gis.kz/astana/firm/{}/tab/reviews"
USER_AGENT = "AstanaWalkHackathon/1.0 (reviews first page; 1 req/s)"
STATE_MARK = "__REACT_QUERY_STATE__"
MAX_BYTES = 8_000_000
MIN_INTERVAL = 1.0
BRANCH_RE = re.compile(r"\d{10,20}")
FIRM_LINK_RE = re.compile(r"https://2gis\.kz/[^?#]*/firm/(\d{10,20})(?:[/?#]|$)")
# Branch outcomes that need no further request on a resumed run.
TERMINAL = {"complete_first_page", "no_public_reviews_as_reported", "only_unrated_reviews_not_collected"}


class StopRun(RuntimeError):
    """Access was refused or checked; continuing would mean working around it."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def branch_ids_of(poi):
    """Numeric 2GIS branch ids from identity fields only, never from free text."""
    found = []
    for value in (
        (poi.get("external_ids") or {}).get("2gis"),
        poi.get("raw_2gis_id"),
        poi["poi_id"][5:] if poi["poi_id"].startswith("dgis:") else None,
    ):
        value = str(value or "").strip()
        # Visit Astana records store the 2GIS identity as a firm link.
        link = FIRM_LINK_RE.match(value)
        if link:
            value = link.group(1)
        if BRANCH_RE.fullmatch(value) and value not in found:
            found.append(value)
    return found


def build_targets(source_path, aliases_path):
    aliases = json.loads(Path(aliases_path).read_text(encoding="utf-8"))
    targets = {}
    with open(source_path, encoding="utf-8") as f:
        for line in f:
            poi = json.loads(line)
            for bid in branch_ids_of(poi):
                t = targets.setdefault(
                    bid,
                    {
                        "branch_id": bid,
                        "source_poi_ids": [],
                        "canonical_poi_ids": [],
                        "name": poi.get("display_name") or poi.get("name"),
                        "category": poi.get("category"),
                        "ratings_count": poi.get("ratings_count"),
                    },
                )
                if poi["poi_id"] not in t["source_poi_ids"]:
                    t["source_poi_ids"].append(poi["poi_id"])
                canonical = aliases.get(poi["poi_id"])
                if canonical and canonical not in t["canonical_poi_ids"]:
                    t["canonical_poi_ids"].append(canonical)
                if (poi.get("ratings_count") or 0) > (t["ratings_count"] or 0):
                    t["ratings_count"] = poi["ratings_count"]
    return list(targets.values())


_JS_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _js_string_literal(text, start):
    """Raw body of the quoted JS string literal starting at text[start]."""
    quote = text[start]
    if quote not in "'\"":
        raise ValueError("no string literal")
    k = start + 1
    while k < len(text):
        c = text[k]
        if c == "\\":
            k += 2
        elif c == quote:
            return text[start + 1 : k]
        else:
            k += 1
    raise ValueError("unterminated string literal")


def decode_js_string(raw):
    """Decode JS string escapes without evaluating any page script."""
    out = []
    k = 0
    while k < len(raw):
        c = raw[k]
        if c != "\\":
            out.append(c)
            k += 1
            continue
        n = raw[k + 1]
        if n == "u" and raw[k + 2 : k + 3] == "{":
            end = raw.index("}", k)
            out.append(chr(int(raw[k + 3 : end], 16)))
            k = end + 1
        elif n == "u":
            out.append(chr(int(raw[k + 2 : k + 6], 16)))
            k += 6
        elif n == "x":
            out.append(chr(int(raw[k + 2 : k + 4], 16)))
            k += 4
        elif n in "\r\n":
            k += 2  # line continuation
        else:
            out.append(_JS_SIMPLE.get(n, n))
            k += 2
    # 😀 pairs arrive as two surrogates; join them into one character.
    return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16")


def extract_state(html):
    """React Query state embedded as `__REACT_QUERY_STATE__ = JSON.parse('...')`."""
    i = html.find(STATE_MARK)
    if i < 0:
        return None
    m = re.compile(r"\s*=\s*JSON\.parse\(\s*").match(html, i + len(STATE_MARK))
    if not m:
        return None
    return json.loads(decode_js_string(_js_string_literal(html, m.end())))


def find_review_page(state, branch_id):
    """First reviews page of exactly this branch, located by query key, not index."""
    for q in state.get("queries") or []:
        key = q.get("queryKey") or []
        if not (
            len(key) >= 2
            and key[0] == "fetchEntityReviews"
            and isinstance(key[1], list)
            and key[1][:2] == [branch_id, "branch"]
        ):
            continue
        pages = ((q.get("state") or {}).get("data") or {}).get("pages") or []
        if pages and isinstance(pages[0], dict) and "items" in pages[0]:
            return pages[0], key[1]
    return None, None


def _clean_dt(value):
    return value if isinstance(value, str) and value else None


def normalize(item, target, collected_at, stream):
    text = item.get("text") if isinstance(item.get("text"), str) else None
    hidden = bool(item.get("is_hidden"))
    if hidden:
        text = None  # hidden content is never added to the corpus
    answer = item.get("official_answer")
    url = item.get("url") if isinstance(item.get("url"), str) else ""
    trust = ((item.get("trust_factors") or {}).get("trust_info") or {})
    return {
        "source": "2gis_public_reviews",
        "branch_id": target["branch_id"],
        "source_poi_ids": target["source_poi_ids"],
        "canonical_poi_ids": target["canonical_poi_ids"],
        "review_id": str(item.get("id")),
        "text": text,
        "text_empty": not (text or "").strip(),
        "rating": item.get("rating"),
        "date_created": _clean_dt(item.get("date_created")),
        "date_edited": _clean_dt(item.get("date_edited")),
        "is_rated": item.get("is_rated"),
        "is_hidden": hidden,
        "provider": item.get("provider"),
        "trust_caption": trust.get("confirmed_caption") if isinstance(trust, dict) else None,
        "likes_count": item.get("likes_count"),
        "stream": stream,
        "first_page_only": True,
        "source_page_url": PAGE_URL.format(target["branch_id"]),
        "review_url": url if url.startswith("https://") and "2gis." in url else None,
        "collected_at": collected_at,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        "operator_answer": (
            {"text": answer.get("text"), "date_created": _clean_dt(answer.get("date_created"))}
            if isinstance(answer, dict) and answer.get("text")
            else None
        ),
    }


def parse_page(html, final_url, target, collected_at):
    """Return (status, reviews, branch_summary) for a fetched reviews page."""
    bid = target["branch_id"]
    path = requests.utils.urlparse(final_url).path
    if f"/firm/{bid}" not in path:
        # /museum is 2GIS's unsupported-browser page; anything else is an unexpected redirect.
        return ("unsupported_browser_page" if path.startswith("/museum") else "redirected"), [], {"final_path": path}
    try:
        state = extract_state(html)
    except (ValueError, json.JSONDecodeError):
        return "schema_changed", [], {"detail": "state not parseable"}
    if state is None:
        return "schema_changed", [], {"detail": "state missing"}
    page, key = find_review_page(state, bid)
    if page is None:
        return "schema_changed", [], {"detail": "reviews query missing"}
    stream = {"sort_by": key[-1] if key and isinstance(key[-1], str) else None, "query_key": key}
    items = page.get("items") or []
    foreign = [i for i in items if str((i.get("object") or {}).get("id")) != bid]
    reviews = [
        normalize(i, target, collected_at, stream)
        for i in items
        if str((i.get("object") or {}).get("id")) == bid
    ]
    summary = {
        "total": page.get("total"),
        "total_for_request": page.get("totalForRequest"),
        "rating": page.get("rating"),
        "org_rating": page.get("orgRating"),
        "has_more": page.get("hasMore"),
        "items_on_page": len(items),
        "foreign_items_dropped": len(foreign),
        "hidden": sum(r["is_hidden"] for r in reviews),
        "with_text": sum(not r["text_empty"] for r in reviews),
        "with_operator_answer": sum(r["operator_answer"] is not None for r in reviews),
    }
    if not items:
        if page.get("total") == 0:
            return "no_public_reviews_as_reported", [], summary
        if page.get("totalForRequest") == 0:
            # Only unrated reviews exist; they are outside the embedded rated stream.
            return "only_unrated_reviews_not_collected", [], summary
        return "schema_changed", [], summary
    return "complete_first_page", reviews, summary


class Fetcher:
    def __init__(self, max_requests):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"})
        self.max_requests = max_requests
        self.requests_made = 0
        self._last = 0.0

    def _wait(self, seconds=MIN_INTERVAL):
        delay = self._last + seconds - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def get(self, url):
        """(html, final_url) or raises StopRun / returns (None, status) on soft failure."""
        for attempt in range(3):
            if self.requests_made >= self.max_requests:
                return None, "partial_local_limit"
            self._wait(MIN_INTERVAL * (1 if attempt == 0 else 5 * attempt))
            self.requests_made += 1
            try:
                with self.session.get(url, timeout=(10, 30), stream=True) as r:
                    if r.status_code in (401, 403):
                        raise StopRun(f"HTTP {r.status_code}: access refused")
                    if r.status_code == 429:
                        retry = r.headers.get("Retry-After", "")
                        if attempt == 0 and retry.isdigit() and int(retry) <= 120:
                            self._wait(int(retry))
                            continue
                        raise StopRun("HTTP 429: rate limited")
                    if r.status_code >= 500:
                        continue
                    if r.status_code != 200 or "html" not in r.headers.get("Content-Type", ""):
                        return None, f"http_{r.status_code}"
                    body = b""
                    for chunk in r.iter_content(1 << 16):
                        body += chunk
                        if len(body) > MAX_BYTES:
                            return None, "response_too_large"
                    return body.decode(r.encoding or "utf-8", errors="replace"), r.url
            except requests.RequestException:
                continue  # exception text may contain URLs; never print it
        return None, "partial_network_error"


def looks_like_access_check(html):
    """A real check page has no app state and asks to prove you are human."""
    return STATE_MARK not in html and re.search(r"captcha|проверк[аи] доступа|не робот", html, re.I) is not None


def pilot_targets(targets, n):
    """Diverse sample: zero, small, mid, large review counts across categories."""
    by = sorted(targets, key=lambda t: t["ratings_count"] or 0)
    picks, seen = [], set()

    def take(pred):
        for t in by:
            if t["branch_id"] not in seen and pred(t):
                picks.append(t)
                seen.add(t["branch_id"])
                return

    take(lambda t: not t["ratings_count"])
    take(lambda t: 0 < (t["ratings_count"] or 0) < 20)
    take(lambda t: 20 <= (t["ratings_count"] or 0) < 50)
    for cat in ("culture", "children", "quiet_spaces", "nightlife", "entertainment", "food_drink", "sightseeing"):
        take(lambda t, c=cat: t["category"] == c and (t["ratings_count"] or 0) > 100)
    take(lambda t: t["branch_id"] == "70000001091792646")  # Tary Astana, checked manually
    return picks[:n]


def read_jsonl(path):
    """Split on \\n only: str.splitlines() would also break on U+2028 inside review texts."""
    if not path.exists():
        return
    with open(path, encoding="utf-8", newline="\n") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_done(status_path):
    return {row["branch_id"]: row["status"] for row in read_jsonl(status_path)}


def write_report(out, targets_total, source_sha):
    latest = load_done(out / "branch_status.jsonl")
    reviews = {}
    rows = 0
    for r in read_jsonl(out / "reviews_2gis.jsonl"):
        rows += 1
        reviews[(r["branch_id"], r["review_id"])] = r
    statuses = {}
    for s in latest.values():
        statuses[s] = statuses.get(s, 0) + 1
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "first embedded reviews page per branch only; pagination not followed",
        "source_pois_sha256": source_sha,
        "target_branches": targets_total,
        "branches_attempted": len(latest),
        "branches_not_started": targets_total - len(latest),
        "branch_statuses": statuses,
        "review_rows_written": rows,
        "unique_reviews": len(reviews),
        "unique_review_ids_global": len({k[1] for k in reviews}),
        "reviews_with_text": sum(not r["text_empty"] for r in reviews.values()),
        "hidden_reviews_skipped_text": sum(r["is_hidden"] for r in reviews.values()),
        "with_operator_answer": sum(r["operator_answer"] is not None for r in reviews.values()),
        "complete": False,
        "complete_note": "First page only: branches with has_more=true have more public reviews that were intentionally not collected.",
    }
    (out / "review_collection_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=str(APP_DATA / "source_pois.jsonl"))
    ap.add_argument("--aliases", default=str(APP_DATA / "poi_aliases.json"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--pilot", type=int, help="collect a diverse sample of N branches")
    ap.add_argument("--branch-ids", nargs="*")
    ap.add_argument("--limit", type=int, help="max branches this run")
    ap.add_argument("--max-requests", type=int, default=6000)
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source_sha = sha256_file(args.source)
    targets = build_targets(args.source, args.aliases)
    with open(out / "review_targets.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"source_pois_sha256": source_sha, "targets": len(targets)}) + "\n")
        for t in targets:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    if args.branch_ids:
        wanted = set(args.branch_ids)
        queue = [t for t in targets if t["branch_id"] in wanted]
    elif args.pilot:
        queue = pilot_targets(targets, args.pilot)
    else:
        # Most-reviewed places first: they carry most of the attribute evidence.
        queue = sorted(targets, key=lambda t: -(t["ratings_count"] or 0))
    done = load_done(out / "branch_status.jsonl")
    queue = [t for t in queue if done.get(t["branch_id"]) not in TERMINAL]
    if args.limit:
        queue = queue[: args.limit]

    fetcher = Fetcher(args.max_requests)
    started = time.monotonic()
    stop_reason = None
    with open(out / "reviews_2gis.jsonl", "a", encoding="utf-8") as rf, open(
        out / "branch_status.jsonl", "a", encoding="utf-8"
    ) as sf:
        for n, target in enumerate(queue, 1):
            collected_at = datetime.now(timezone.utc).isoformat()
            try:
                html, final = fetcher.get(PAGE_URL.format(target["branch_id"]))
            except StopRun as exc:
                stop_reason = str(exc)
                status, reviews, summary = "blocked_access", [], {"detail": stop_reason}
            else:
                if html is None:
                    status, reviews, summary = final, [], {}
                elif looks_like_access_check(html):
                    status, reviews, summary = "blocked_access", [], {"detail": "access check page"}
                    stop_reason = "access check page"
                else:
                    status, reviews, summary = parse_page(html, final, target, collected_at)
                    if status == "unsupported_browser_page":
                        stop_reason = "unsupported browser page"
            # Reviews and their branch status are flushed together so a resume never loses a page.
            for r in reviews:
                rf.write(json.dumps(r, ensure_ascii=False) + "\n")
            rf.flush()
            sf.write(
                json.dumps(
                    {"branch_id": target["branch_id"], "status": status, "fetched_at": collected_at,
                     "reviews_saved": len(reviews), **summary},
                    ensure_ascii=False,
                )
                + "\n"
            )
            sf.flush()
            print(
                f"[{n}/{len(queue)}] {target['branch_id']} {status} saved={len(reviews)} "
                f"total={summary.get('total')} {(target['name'] or '')[:40]}",
                flush=True,
            )
            if stop_reason or status == "partial_local_limit":
                break
    report = write_report(out, len(targets), source_sha)
    elapsed = time.monotonic() - started
    print(json.dumps({**report["branch_statuses"], "requests": fetcher.requests_made,
                      "seconds": round(elapsed, 1), "stopped": stop_reason}, ensure_ascii=False))
    return 1 if stop_reason else 0


if __name__ == "__main__":
    sys.exit(main())
