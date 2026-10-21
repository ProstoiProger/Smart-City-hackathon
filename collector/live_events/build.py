"""Turn page-level events into records in the app's events schema and link each to a known venue."""

import hashlib
import re
from datetime import datetime, timedelta, timezone

ASTANA = timezone(timedelta(hours=5))
VENUE_CATEGORIES = {"culture", "entertainment", "children", "sightseeing", "sport", "shopping", "nightlife", "quiet_spaces"}
MAX_GEO_MATCH_M = 150
HOUSE = re.compile(r"\b(\d{1,4}\s*[а-яa-z]?)\b")
NAME_NOISE = {"имени", "им", "ж", "г", "the", "астана", "астаны"}
STREET_WORDS = re.compile(r"\b(ул|улица|пр|проспект|просп|пр-т|бульвар|бул|шоссе|микрорайон|мкр|площадь)\b\.?", re.I)


def norm(text):
    return re.sub(r"[^\wәіңғүұқөһ]+", " ", (text or "").casefold().replace("ё", "е")).strip()


class Venues:
    """Eligible places by normalised name and street address."""

    def __init__(self, pois, meters):
        self.meters = meters
        self.pois = [p for p in pois if p.get("recommendation_eligible", True)]
        self.by_name = {}
        for p in self.pois:
            if p.get("category") not in VENUE_CATEGORIES:
                continue
            key = norm((p.get("display_name") or "").split(",")[0])
            if len(key) >= 5:
                self.by_name.setdefault(key, []).append(p)
        self.tokens = {}
        for key, ps in self.by_name.items():
            for p in ps:
                self.tokens[p["poi_id"]] = (p, self._words(key))
        self.addresses = [(norm(STREET_WORDS.sub(" ", p["address"])), p) for p in self.pois if p.get("address")]

    @staticmethod
    def _words(text):
        return {w for w in norm(text).split() if len(w) >= 3 and w not in NAME_NOISE}

    def overlap(self, text):
        """The place whose name shares most words with `text` (at least two, at most one word missing)."""
        words = self._words(text)
        best = None
        for p, theirs in self.tokens.values():
            shared = len(words & theirs)
            if shared >= 2 and shared >= len(theirs) - 1 and (best is None or shared > best[0]):
                best = (shared, p)
        return best[1] if best else None

    def match(self, venue, address, geo, title):
        if geo:
            near = [
                (self.meters((geo["latitude"], geo["longitude"]), (p["latitude"], p["longitude"])), p)
                for p in self.pois
                if p.get("category") in VENUE_CATEGORIES
            ]
            near = [x for x in near if x[0] <= MAX_GEO_MATCH_M]
            if near:
                return min(near, key=lambda x: x[0])[1], "publisher_coordinates_matched_to_venue"
        for text in (venue, title):
            key = norm(text)
            if key in self.by_name:
                return self.by_name[key][0], "matched_public_venue_point_not_verified_entrance"
        haystack = f" {norm(venue)} {norm(title)} "
        hits = [p for key, ps in self.by_name.items() if f" {key} " in haystack for p in ps]
        if hits:
            best = max(hits, key=lambda p: len(p.get("display_name") or ""))
            return best, "matched_public_venue_point_not_verified_entrance"
        by_words = self.overlap(venue)
        if by_words:
            return by_words, "matched_public_venue_point_not_verified_entrance"
        if address:
            street = norm(STREET_WORDS.sub(" ", address))
            number = HOUSE.search(street)
            if number:
                for text, p in self.addresses:
                    if number.group(1) in text.split() and street.replace(number.group(1), "").strip() in text:
                        if p.get("category") in VENUE_CATEGORIES:
                            return p, "matched_street_address_not_verified_entrance"
        return None, None


def iso(value):
    """('ISO string', 'datetime' | 'day') for a schema.org date or date-time, in Astana time."""
    value = value.strip()
    if len(value) <= 10:
        return value, "day"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10], "day"
    dt = dt.replace(tzinfo=ASTANA) if dt.tzinfo is None else dt.astimezone(ASTANA)
    return dt.isoformat(), "datetime"


def record(raw, source, venues, collected_at):
    start, precision = iso(raw["start"])
    end = iso(raw["end"])[0] if raw.get("end") else None
    event_id = "live:" + hashlib.sha1(f"{raw['url']}|{start}".encode()).hexdigest()[:20]
    place, method = venues.match(raw.get("venue"), raw.get("address"), raw.get("geo"), raw["name"])
    coords = (
        {"latitude": place["latitude"], "longitude": place["longitude"]}
        if place
        else raw.get("geo")
    )
    status = (raw.get("status") or "").rsplit("/", 1)[-1] or None
    price = dict(raw["price"], observed_at=collected_at) if raw.get("price") else None
    return {
        "event_id": event_id,
        "event_name": raw["name"],
        "event_start": start,
        "event_end": end,
        "date_precision": precision,
        "timezone": "Asia/Qyzylorda",
        "event_location": (place or {}).get("display_name", "").split(",")[0] or raw.get("venue"),
        "event_address": raw.get("address"),
        "event_coordinates": coords,
        "location_coordinate_method": method if place else ("publisher_coordinates" if coords else None),
        "venue_poi_id": place["poi_id"] if place else None,
        "event_description": (raw.get("description") or "")[:600] or None,
        "event_category": None,
        "event_price": price,
        "registration_url": raw.get("ticket_url") or raw["url"],
        "event_age_group": raw.get("age"),
        "event_status": status,
        "listing_period_status": "upcoming_or_ongoing",
        "event_verified_at": None,
        "collected_at": collected_at,
        "source_url": raw["url"],
        "source_name": source["title"],
        "source_id": source["id"],
        "license": None,
        "verification_note": "Опубликованный анонс, собран автоматически; проведение и наличие билетов не подтверждены.",
    }
