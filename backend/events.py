"""Recheck the publisher for one existing event; never equate absence of cancellation with confirmation."""

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import threading
import time
from urllib.parse import urlparse, urljoin
import httpx

ALLOWED = {"ticketon.kz", "www.ticketon.kz", "visitastana.kz", "www.visitastana.kz"}
_cache = {}
_lock = threading.Lock()


class SchemaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.buff = []
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.active = True
            self.buff = []

    def handle_data(self, data):
        if self.active:
            self.buff.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.active = False
            try:
                self.nodes.append(json.loads("".join(self.buff)))
            except (ValueError, TypeError):
                pass


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def event_claim(body, original):
    parser = SchemaParser()
    parser.feed(body)
    nodes = [
        n
        for root in parser.nodes
        for n in walk(root)
        if "Event" in str(n.get("@type", ""))
    ]
    day = (original.get("event_start") or "")[:10]
    matches = [n for n in nodes if str(n.get("startDate", ""))[:10] == day]
    if not matches:
        return {
            "occurrence_identified": False,
            "publisher_status": None,
            "note": "Страница доступна, но нужное событие/дату в разметке подтвердить не удалось.",
        }
    node = matches[0]
    status = node.get("eventStatus")
    return {
        "occurrence_identified": True,
        "publisher_status": status,
        "publisher_start": node.get("startDate"),
        "publisher_end": node.get("endDate"),
        "cancelled_as_reported": str(status).endswith("EventCancelled"),
        "note": "Статус опубликован источником; проведение независимо не подтверждено.",
    }


def fetch_publisher_page(url):
    if (
        urlparse(url or "").scheme != "https"
        or urlparse(url or "").hostname not in ALLOWED
    ):
        raise ValueError("unsupported publisher")
    with httpx.Client(timeout=8, follow_redirects=False) as client:
        for _ in range(4):
            response = client.get(url, headers={"User-Agent": "AstanaWalkDemo/1.1"})
            if response.status_code in (301, 302, 303, 307, 308):
                new = urljoin(url, response.headers.get("location", ""))
                if (
                    urlparse(new).scheme != "https"
                    or urlparse(new).hostname not in ALLOWED
                ):
                    raise ValueError("redirect outside publisher allowlist")
                url = new
                continue
            response.raise_for_status()
            if len(response.content) > 4000000:
                raise ValueError("publisher page too large")
            return url, response.text, datetime.now(timezone.utc).isoformat()
        raise ValueError("redirect loop")


def recheck(original):
    key = original["event_id"]
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    stamp = datetime.now(timezone.utc).isoformat()
    url = original.get("registration_url") or original.get("source_url")
    result = {
        "event_id": key,
        "source_url": url,
        "publisher_rechecked_at": stamp,
        "independently_confirmed": False,
        "live_verified": False,
        "source_page_available": False,
    }
    if (
        urlparse(url or "").scheme != "https"
        or urlparse(url or "").hostname not in ALLOWED
    ):
        return {
            **result,
            "note": "Источник не поддерживает автоматическую проверку. Откройте ссылку организатора.",
        }
    try:
        final, body, stamp = fetch_publisher_page(url)
        result.update(
            {
                "source_url": final,
                "publisher_rechecked_at": stamp,
                "source_page_available": True,
                **event_claim(body, original),
            }
        )
    except Exception:
        result["note"] = (
            "Источник сейчас недоступен. Событие не считается подтвержденным; исходная запись сохранена."
        )
    with _lock:
        _cache[key] = (time.monotonic() + 900, result)
    return result
