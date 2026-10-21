import json
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
import backend.app as app_module
from backend.app import app
from backend import cityaudit
from backend.group import LEVEL_PARTIAL, clean_members, cover_everyone, group_score, level
from backend.hours import ASTANA
from backend.routing import meters
from backend.service import event_key, load_events
from collector.live_events import jsonld
from collector.live_events.__main__ import upcoming
from collector.live_events.build import Venues, iso, record

MEGA = {"latitude": 51.089, "longitude": 71.407, "minutes": 120, "provider": "offline"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def offline_conditions(monkeypatch):
    monkeypatch.setattr(app_module, "current_weather", lambda: {"available": False})
    monkeypatch.setattr(app_module, "current_air", lambda: {"available": False})


def chat(client, members, query="куда сходим", **extra):
    return client.post("/api/chat", json={"query": query, "members": members, **MEGA, **extra})


WISHES = [
    {"name": "Айгерим", "wish": "кофе и тихо"},
    {"name": "Данияр", "wish": "что-то необычное"},
    {"name": "Мира", "wish": "с розеткой поработать"},
]


def test_group_answer_explains_fit_for_every_member(client):
    data = chat(client, WISHES).json()
    assert data["group"]["size"] == 3 and [m["name"] for m in data["group"]["members"]] == ["Айгерим", "Данияр", "Мира"]
    assert data["items"]
    for item in data["items"]:
        assert [f["name"] for f in item["group_fit"]] == ["Айгерим", "Данияр", "Мира"]
        assert all(f["level"] in ("match", "partial", "none") for f in item["group_fit"])
        assert "каждому" in item["why"]
    assert any(c["label"] == "Компания" for c in data["considered"])


def test_group_covers_a_member_the_best_place_leaves_out(client):
    data = chat(client, WISHES).json()
    for f in data["items"][0]["group_fit"]:
        covered = any(
            next(x for x in item["group_fit"] if x["name"] == f["name"])["level"] != "none" for item in data["items"]
        )
        assert covered, f"{f['name']} is left out of every pick"


def test_group_needs_two_members_with_a_wish(client):
    solo = chat(client, [{"name": "Один", "wish": "кофе"}]).json()
    assert solo["group"] is None or "members" not in solo["group"]
    blank = chat(client, [{"name": "А", "wish": ""}, {"name": "Б", "wish": ""}]).json()
    assert blank["group"] is None or "members" not in blank["group"]


def test_group_is_capped_at_six_members(client):
    many = [{"name": f"Гость {i}", "wish": "кофе"} for i in range(7)]
    assert chat(client, many).status_code == 422


def test_group_blank_names_get_a_default():
    members = clean_members([{"name": "  ", "wish": "кофе"}, {"name": "Данияр", "wish": " парк "}])
    assert members[0].name == "Участник 1" and members[1].wish == "парк"


def test_group_score_leans_on_the_least_happy():
    assert group_score([1.0, 1.0, 0.0]) < group_score([0.6, 0.6, 0.6])
    assert level(0.8) == "match" and level(0.5) == "partial" and level(0.1) == "none"


def test_cover_everyone_gives_the_left_out_member_a_pick():
    ranked = [
        {"poi_id": "a", "search_score": 0.9, "_member_scores": [1.0, 0.0]},
        {"poi_id": "b", "search_score": 0.8, "_member_scores": [0.9, 0.1]},
        {"poi_id": "c", "search_score": 0.1, "_member_scores": [0.0, 0.9]},
    ]
    assert [r["poi_id"] for r in cover_everyone(ranked, 2)[:2]] == ["a", "c"]
    assert LEVEL_PARTIAL > 0


def test_tours_list_and_detail(client):
    items = client.get("/api/tours?lang=kk").json()["items"]
    assert {t["id"] for t in items} == {"botanical", "nurzhol", "independence", "expo"}
    detail = client.get("/api/tours/nurzhol?lang=ru").json()
    assert len(detail["legs"]) == len(detail["stops"]) - 1
    for stop in detail["stops"]:
        assert stop["facts"] and all(f["source"].startswith("http") and f["source_name"] for f in stop["facts"])
    for leg, a, b in zip(detail["legs"], detail["stops"], detail["stops"][1:]):
        # Legs run from stop to stop, along the walking graph where a path exists.
        assert leg["geometry"][0] == [a["latitude"], a["longitude"]]
        assert leg["geometry"][-1] == [b["latitude"], b["longitude"]]
        assert leg["duration_min"] > 0


def test_tour_language_falls_back_to_russian(client):
    ru = client.get("/api/tours/expo?lang=ru").json()
    odd = client.get("/api/tours/expo?lang=zz").json()
    assert odd["title"] == ru["title"]
    assert client.get("/api/tours/nope").status_code == 404


def test_city_audit_file_is_served_and_consistent(client):
    audit = client.get("/api/city/audit").json()
    assert [s["id"] for s in audit["scenarios"]] == [s.id for s in cityaudit.SCENARIOS]
    assert audit["cells"] and audit["coverage"]["places"] > 1000
    for s in audit["scenarios"]:
        total = sum(s["summary"][k] for k in ("none", "guess", "far", "ok"))
        assert total == s["summary"]["cells"] == len(audit["cells"])
    for cell in audit["cells"][:20]:
        for r in cell["results"].values():
            assert r["level"] in ("none", "guess", "far", "ok")
            assert (r["options"] == 0) == (r["level"] == "none")


def test_audit_levels():
    s = cityaudit.BY_ID["step_free"]
    assert cityaudit.level({"options": 0, "confirmed": 0, "nearest_min": None}, s) == "none"
    assert cityaudit.level({"options": 2, "confirmed": 0, "nearest_min": 4}, s) == "guess"
    assert cityaudit.level({"options": 2, "confirmed": 1, "nearest_min": 30}, s) == "far"
    assert cityaudit.level({"options": 2, "confirmed": 1, "nearest_min": 5}, s) == "ok"


def test_audit_asks_from_a_cell(client):
    city = app_module.city
    cells = cityaudit.cells(city)
    places = max(cells.values(), key=len)
    origin = cityaudit.centroid(places)
    day = datetime(2026, 10, 19, tzinfo=ASTANA).date()
    options, confirmed, nearest, best = cityaudit.ask(
        city, cityaudit.BY_ID["night"], origin, cityaudit.moment(cityaudit.BY_ID["night"], day)
    )
    assert options >= confirmed >= 0 and len(best) <= 2
    assert cityaudit.moment(cityaudit.BY_ID["night"], day).weekday() == 4


EVENT_PAGE = """<html><head>
<script type="application/ld+json">{"@context":"http://schema.org","@type":"Article","headline":"x"}</script>
<script type="application/ld+json">{"@context":"http://schema.org","@type":"Event","name":"Концерт Платина",
"startDate":"2026-12-11T20:00:00+05:00","endDate":"2026-12-11T22:00:00+05:00",
"url":"https://sxodim.com/astana/event/platina",
"eventStatus":"https://schema.org/EventScheduled",
"location":{"@type":"Place","name":"Концерт Платина","address":{"@type":"PostalAddress",
"streetAddress":"Nova, {ZW}улица Достык, 3"}},
"offers":{"@type":"Offer","price":"8000","priceCurrency":"KZT","availability":"https://schema.org/InStock",
"url":"https://tickets.example/platina"}}</script>
</head><body></body></html>"""

EVENT_PAGE = EVENT_PAGE.replace("{ZW}", chr(0x200B))
LISTING = '<a href="/astana/event/a">A</a><a href="https://sxodim.com/astana/event/b/">B</a><a href="/astana/news/c">C</a>'


def test_jsonld_reads_event_price_and_venue_from_address():
    [e] = jsonld.extract(EVENT_PAGE, "https://sxodim.com/astana/event/platina")
    assert e["name"] == "Концерт Платина" and e["start"].startswith("2026-12-11T20:00")
    assert e["venue"] == "Nova" and e["address"] == "улица Достык, 3"
    assert e["price"]["amount_min"] == 8000.0 and e["ticket_url"] == "https://tickets.example/platina"


def test_listing_links_keep_only_event_pages():
    got = jsonld.links(LISTING, "https://sxodim.com/astana/afisha", r"^https://sxodim\.com/astana/event/[a-z0-9-]+/?$")
    assert got == ["https://sxodim.com/astana/event/a", "https://sxodim.com/astana/event/b/"]


def test_record_links_a_known_venue_and_keeps_the_publisher_price():
    pois = [
        {"poi_id": "p1", "display_name": "Nova night club", "category": "nightlife", "latitude": 51.13, "longitude": 71.43,
         "address": "улица Достык, 3"},
        {"poi_id": "p2", "display_name": "Кофейня", "category": "food_drink", "latitude": 51.1, "longitude": 71.4},
    ]
    [raw] = jsonld.extract(EVENT_PAGE, "https://sxodim.com/astana/event/platina")
    row = record(raw, {"id": "s", "title": "Sxodim"}, Venues(pois, meters), "2026-10-21T00:00:00+00:00")
    assert row["venue_poi_id"] == "p1" and row["event_coordinates"] == {"latitude": 51.13, "longitude": 71.43}
    assert row["event_price"]["amount_min"] == 8000.0 and row["date_precision"] == "datetime"
    assert row["event_id"].startswith("live:") and row["source_name"] == "Sxodim"
    assert "не подтверждены" in row["verification_note"]


def test_record_without_a_known_venue_has_no_coordinates():
    [raw] = jsonld.extract(EVENT_PAGE, "https://sxodim.com/astana/event/platina")
    row = record(raw, {"id": "s", "title": "Sxodim"}, Venues([], meters), "t")
    assert row["venue_poi_id"] is None and row["event_coordinates"] is None


def test_dates_and_past_events():
    assert iso("2026-12-11")[1] == "day" and iso("2026-12-11T20:00:00+05:00")[1] == "datetime"
    now = datetime(2026, 10, 21, 12, 0, tzinfo=ASTANA)
    assert upcoming({"event_start": "2026-10-20", "event_end": "2026-10-21"}, now)
    assert not upcoming({"event_start": "2026-10-19", "event_end": "2026-10-20"}, now)
    assert not upcoming({"event_start": "2026-10-21T09:00:00+05:00"}, now)


def test_live_events_replace_the_snapshot_copy_of_the_same_show(tmp_path, monkeypatch):
    import backend.service as service

    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event_id": "old", "event_name": "Концерт  «Платина»", "event_start": "2026-12-11T20:00:00+05:00"}) + "\n"
        + json.dumps({"event_id": "keep", "event_name": "Другое", "event_start": "2026-12-12"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "events_live.jsonl").write_text(
        json.dumps({"event_id": "new", "event_name": "Концерт Платина", "event_start": "2026-12-11T20:00:00+05:00"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "DATA", tmp_path)
    events, live, snapshot = load_events()
    assert [e["event_id"] for e in events] == ["keep", "new"] and len(live) == 1 and snapshot == 2
    assert event_key({"event_name": "A b", "event_start": "2026-01-01T10:00"}) == ("a b", "2026-01-01")


def test_events_endpoint_reports_live_collection(client):
    data = client.get("/api/events").json()
    assert data["live_collected"] == len(app_module.city.events_live)
    assert data["all_snapshot_records"] == app_module.city.events_snapshot
    assert data["live_verified"] is False
