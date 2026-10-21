"""schema.org Event records from a page's JSON-LD: the publisher's own structured announcement."""

import json
import re
from bs4 import BeautifulSoup

EVENT_TYPES = re.compile(r"Event$")
INVISIBLE = re.compile("[" + "".join(map(chr, (0x200B, 0xA0))) + "]+")
ADULT = re.compile(r"(\d{1,2})\s*\+")


def _types(node):
    t = node.get("@type")
    return [t] if isinstance(t, str) else [x for x in t or [] if isinstance(x, str)]


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "subEvent"):
            if key in node:
                yield from _walk(node[key])


def _text(value):
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value")
    if not isinstance(value, str):
        return None
    value = INVISIBLE.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip() or None


def _split_address(address):
    """Publishers often write "Venue name, street, number" in streetAddress: (venue or None, street)."""
    if not address:
        return None, None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 3 or (len(parts) == 2 and not re.search(r"\d", parts[0])):
        return parts[0], ", ".join(parts[1:])
    return None, address


def _offers(node):
    """Cheapest published price and the availability flag; None when the page lists no price."""
    offers = node.get("offers")
    offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
    prices, availability, currency, url = [], None, None, None
    for offer in offers:
        for key in ("price", "lowPrice"):
            try:
                prices.append(float(str(offer.get(key)).replace(",", ".").replace(" ", "")))
            except (TypeError, ValueError):
                pass
        for key in ("highPrice",):
            try:
                prices.append(float(str(offer.get(key)).replace(",", ".")))
            except (TypeError, ValueError):
                pass
        availability = availability or offer.get("availability")
        currency = currency or offer.get("priceCurrency")
        url = url or offer.get("url")
    if not prices and not availability:
        return None
    out = {"currency": currency or "KZT", "availability": availability, "price_type": "published ticket price"}
    if prices:
        out["amount_min"] = min(prices)
        if max(prices) != min(prices):
            out["amount_max"] = max(prices)
    return out, url


def extract(html, page_url):
    """Event dicts found in the page, one per schema.org Event node."""
    soup = BeautifulSoup(html, "lxml")
    found = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (TypeError, ValueError):
            continue
        for node in _walk(data):
            if not any(EVENT_TYPES.search(t) for t in _types(node)):
                continue
            name, start = _text(node.get("name")), _text(node.get("startDate"))
            if not name or not start:
                continue
            location = node.get("location")
            location = location[0] if isinstance(location, list) and location else location
            address = (location or {}).get("address") if isinstance(location, dict) else None
            geo = (location or {}).get("geo") if isinstance(location, dict) else None
            street = _text(address.get("streetAddress")) if isinstance(address, dict) else _text(address)
            offers = _offers(node)
            venue_name = _text(location.get("name")) if isinstance(location, dict) else None
            in_address, street = _split_address(street)
            # Some publishers put the event's own title in the location name; the address then names the venue.
            venue = in_address if in_address and (not venue_name or venue_name.casefold() == name.casefold()) else venue_name
            age = _text(node.get("typicalAgeRange")) or (
                m.group(0).replace(" ", "") if (m := ADULT.search(node.get("name", ""))) else None
            )
            found.append(
                {
                    "name": name,
                    "start": start,
                    "end": _text(node.get("endDate")),
                    "url": _text(node.get("url")) or page_url,
                    "status": _text(node.get("eventStatus")),
                    "description": _text(node.get("description")),
                    "venue": venue,
                    "address": street,
                    "geo": (
                        {"latitude": float(geo["latitude"]), "longitude": float(geo["longitude"])}
                        if isinstance(geo, dict) and geo.get("latitude") and geo.get("longitude")
                        else None
                    ),
                    "price": offers[0] if offers else None,
                    "ticket_url": offers[1] if offers else None,
                    "age": age,
                    "image": (node.get("image") or [None])[0] if isinstance(node.get("image"), list) else node.get("image"),
                }
            )
    return found


def links(html, base_url, pattern):
    """Absolute links on a listing page that match `pattern`, in page order without repeats."""
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "lxml")
    rx = re.compile(pattern)
    out = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if rx.search(url) and url not in out:
            out.append(url)
    return out
