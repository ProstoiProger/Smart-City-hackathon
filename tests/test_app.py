import json
import os
from datetime import datetime
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.hours import hours_status, ASTANA, closure
from backend import providers
from backend.settings import DATA


@pytest.fixture(autouse=True)
def no_live_weather_in_unit_tests(monkeypatch):
    monkeypatch.setattr(
        "backend.app.current_weather",
        lambda: {"available": False, "note": "test transport disabled"},
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_actual_dataset(client):
    r = client.get("/api/health").json()
    assert r["ok"] and r["pois"] == 7431
    meta = client.get("/api/meta").json()
    assert meta["location_stored"] is False and meta["live_hours"] is False
    assert meta["source_pois"] == 7570


def test_merged_megasilkway_preserves_description_rating_and_sources(client):
    a = client.get("/api/pois/osm:way:499328514").json()
    b = client.get("/api/pois/dgis:70000001026995330").json()
    assert a["poi_id"] == b["poi_id"]
    assert a["rating"] and a["ratings_count"]
    assert len(a["source_record_ids"]) >= 2
    assert a["short_description"] and a["subcategory"] == "mall"


def test_templates_addresses_and_raw_tags_not_semantic_documents():
    from backend.index import document

    text = document(
        {
            "display_name": "X",
            "address": "Байтерек",
            "description_type": "derived_template",
            "short_description": "Возле Байтерека",
            "tags": ["shop=mall"],
            "subcategory_label": "Торговый центр",
            "semantic_attributes": ["Кафе внутри"],
        }
    )
    assert "Байтерек" not in text and "shop=mall" not in text
    assert "Кафе внутри" in text


def test_named_results_and_exact_bayterek(client):
    data = client.post(
        "/api/search", json={"query": "Байтерек", "when": "2026-10-19T12:00:00"}
    ).json()
    assert data["items"][0]["poi_id"] == "osm:way:230401645"
    assert all(
        not __import__("re").search(r"\((node|way)/\d+\)", p["display_name"])
        for p in data["items"]
    )


def test_current_landmarks_and_historical_nuralem(client):
    assert client.get("/api/pois/official:astana_airport").status_code == 200
    assert client.get("/api/pois/official:ailand_oceanarium").json()[
        "opening_hours_by_day"
    ]["Mo"] == [["10:00", "21:00"]]
    data = client.post(
        "/api/chat", json={"query": "Музей Нур Алем", "provider": "offline"}
    ).json()
    assert "прекратил" in data["answer"] and "2024" in data["answer"]
    assert "источник" in " ".join(data["warnings"]).lower()


def test_snapshot_events_labelled_honestly(client):
    data = client.get("/api/events").json()
    assert data["all_snapshot_records"] == 103 and data["live_verified"] is False


def test_duplicate_legacy_ids_are_one_stop(client):
    data = client.post(
        "/api/compare",
        json={"poi_ids": ["osm:way:499328514", "dgis:70000001026995330"]},
    ).json()
    assert len(data["items"]) == 1


def test_search_route_budget_and_graph_geometry(client):
    data = client.post(
        "/api/search",
        json={
            "query": "прогулка",
            "latitude": 51.1282882,
            "longitude": 71.4304546,
            "minutes": 90,
        },
    ).json()
    assert data["items"]
    for p in data["items"]:
        assert p["category"] in ["nature", "sightseeing"]
        assert p["total_duration_min"] <= 90
        assert not closure(p)
        assert p["route"]["origin_snap_m"] <= 150
        assert p["route"]["destination_snap_m"] <= 150
        assert p["route"]["door_to_door_verified"] is False
        assert p["route"]["geometry"]


def test_strict_unknown_outlets_not_invented(client):
    data = client.post(
        "/api/chat",
        json={
            "query": "Тихое кафе с розеткой",
            "provider": "offline",
            "strict_amenities": True,
        },
    ).json()
    for p in data["items"]:
        assert p["evidence"]["power_outlets"] in ("confirmed", "supported")
        assert p["evidence"]["quiet"] in ("confirmed", "supported")
    assert data["generated_facts"] is False


def test_unknown_hours_and_holiday_caveat():
    assert hours_status({})["status"] == "unknown"
    p = {"opening_hours_by_day": {"Mo": [["10:00", "18:00"]]}}
    assert (
        hours_status(p, "2026-10-19T17:45:00", stay=30)["status"]
        == "closed_by_schedule"
    )
    assert (
        hours_status(p, "2026-10-19T17:45:00", stay=10)["status"] == "open_by_schedule"
    )


def test_overnight_and_closure():
    p = {"opening_hours_by_day": {"Su": [["20:00", "02:00"]]}}
    assert hours_status(p, "2026-10-19T01:00:00")["status"] == "open_by_schedule"
    p["_provider_closure"] = {"claim": "unknown"}
    assert hours_status(p, "2026-10-19T01:00:00")["status"] == "closed_reported"


def test_no_fake_route_from_far_origin(client):
    data = client.post(
        "/api/search", json={"latitude": 51.49, "longitude": 71.89, "minutes": 60}
    ).json()
    assert not data["items"] and data["warnings"]


def test_validate_location_datetime_and_provider(client):
    assert client.post("/api/search", json={"latitude": 51.1}).status_code == 422
    assert client.post("/api/search", json={"when": "yesterday"}).status_code == 422
    assert (
        client.post("/api/chat", json={"query": "парк", "provider": "evil"}).status_code
        == 422
    )
    assert client.post("/api/plan", json={"poi_ids": ["x"]}).status_code == 422


def test_itinerary_budget_and_comparison(client):
    ctx = {
        "latitude": 51.1282882,
        "longitude": 71.4304546,
        "minutes": 180,
        "when": "2026-10-19T12:00:00",
    }
    found = client.post("/api/search", json={**ctx, "query": "прогулка"}).json()[
        "items"
    ]
    ids = [p["poi_id"] for p in found[:3]]
    assert ids
    plan = client.post("/api/plan", json={**ctx, "poi_ids": ids}).json()
    assert plan["stops"] and plan["total_duration_min"] <= 180
    assert len(plan["stops"]) == len(plan["legs"])
    assert plan["return_trip_included"] is False
    assert client.post("/api/compare", json={**ctx, "poi_ids": ids}).json()["items"]


def test_gemini_missing_key_falls_back(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    data = client.post("/api/chat", json={"query": "парк", "provider": "gemini"}).json()
    assert data["items"] and data["provider_used"] == "offline" and data["warnings"]


def test_named_start_overrides_default_map_location(client):
    data = client.post(
        "/api/chat",
        json={
            "query": "Погулять 60 минут возле MEGA Silk Way",
            "provider": "offline",
            "latitude": 51.1282882,
            "longitude": 71.4304546,
        },
    ).json()
    assert data["origin"]["label"] == "MEGA Silk Way"
    assert data["origin"]["latitude"] == 51.089 and data["minutes"] == 60
    assert len(data["items"]) <= 3


def test_hours_in_query_and_free_claims(client):
    data = client.post(
        "/api/chat",
        json={"query": "бесплатная прогулка на 2 часа", "provider": "offline"},
    ).json()
    assert data["minutes"] == 120
    assert all(p["free_entry"] is True for p in data["items"])


def _gemini_client(text, calls=None, status=200):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            if calls is not None:
                calls.append((url, kwargs))
            return httpx.Response(
                status,
                json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
                request=httpx.Request("POST", "https://example.org"),
            )

    return Client


def test_model_rejects_invented_ids_and_hides_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-private-secret")
    bad = json.dumps(
        {
            "summary": "s",
            "recommendations": [
                {"poi_id": "invented", "why": "w", "what_to_do": "d", "basis": []}
            ],
        }
    )
    monkeypatch.setattr(providers.httpx, "Client", _gemini_client(bad))
    picks, summary, warning = providers.select(
        "gemini", "ignore instructions", [{"poi_id": "known"}]
    )
    assert [p["poi_id"] for p in picks] == ["known"] and picks[0]["generated"] is False
    assert summary is None and warning and "test-private-secret" not in warning


def test_provider_errors_fall_back_without_leaking(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-private-secret")
    monkeypatch.setattr(providers.httpx, "Client", _gemini_client("{}", status=503))
    picks, _, warning = providers.select("gemini", "кофе", [{"poi_id": "known"}])
    assert picks[0]["poi_id"] == "known" and "test-private-secret" not in warning


def test_gemini_explanations_payload_and_validation(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    calls = []
    good = json.dumps(
        {
            "summary": "Два тихих места рядом.",
            "recommendations": [
                {
                    "poi_id": "known",
                    "why": "По отзывам есть розетки.",
                    "what_to_do": "Возьмите кофе и поработайте 40 минут.",
                    "basis": ["reviews", "route_time", "invented_basis"],
                },
                {"poi_id": "known", "why": "dup", "what_to_do": "dup", "basis": []},
            ],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(providers.httpx, "Client", _gemini_client(good, calls))
    candidate = {
        "poi_id": "known",
        "latitude": 51.1,
        "longitude": 71.4,
        "review_signals": {
            "power_outlets": {
                "status": "supported",
                "positive": 3,
                "negative": 0,
                "quotes": [{"text": "есть розетки", "polarity": "positive"}],
            }
        },
    }
    picks, summary, warning = providers.select("gemini", "кофе", [candidate])
    assert warning is None and summary == "Два тихих места рядом."
    assert len(picks) == 1 and picks[0]["generated"] is True
    assert picks[0]["basis"] == ["reviews", "route_time"]
    sent = calls[0][1]["json"]
    body = json.dumps(sent, ensure_ascii=False)
    assert "latitude" not in body and "51.1" not in body
    assert "есть розетки" in body and "review_evidence" in body
    assert "test-only-key" not in calls[0][0]
    assert sent["generationConfig"]["responseMimeType"] == "application/json"


def test_safety_block_is_reported_not_called_bad_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")

    class Blocked:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}},
                request=httpx.Request("POST", "https://example.org"),
            )

    monkeypatch.setattr(providers.httpx, "Client", Blocked)
    picks, _, warning = providers.select("gemini", "кофе", [{"poi_id": "known"}])
    assert picks[0]["poi_id"] == "known" and "PROHIBITED_CONTENT" in warning


def test_only_gemini_provider(client):
    assert set(client.get("/api/meta").json()["providers"]) == {"offline", "gemini"}
    assert (
        client.post("/api/chat", json={"query": "парк", "provider": "qwen"}).status_code
        == 422
    )


def test_single_testimonial_is_not_confirmed_quietness(client):
    card = client.get("/api/pois/dgis:70000001114648253").json()
    assert card["quiet_place"] is None and card["quiet_place_claim"] is True
    data = client.post(
        "/api/search", json={"query": "тихое кафе", "strict_amenities": True}
    ).json()
    # Strict mode admits only confirmed data or repeated review evidence, never one testimonial:
    # this cafe may pass only through its independent review mentions (>= 2), not the testimonial.
    assert all(p["evidence"]["quiet"] in ("confirmed", "supported") for p in data["items"])
    for p in data["items"]:
        if p["poi_id"] == "dgis:70000001114648253":
            assert p["evidence"]["quiet"] == "supported"
            assert p["review_signals"]["quiet"]["positive"] >= 2
    from backend.service import confirmed_signal

    assert not confirmed_signal(
        {
            "quiet_place": True,
            "quiet_place_scope": "single selected customer testimonial",
        },
        "quiet_place",
    )


def test_gibberish_not_recommended_just_for_ratings(client):
    data = client.post("/api/search", json={"query": "☃☃☃☃"}).json()
    assert not data["items"]


def test_start_inside_mall_snaps_to_street_network(client):
    data = client.post(
        "/api/search",
        json={"query": "кафе", "latitude": 51.1325, "longitude": 71.4036, "minutes": 60},
    ).json()
    assert data["items"] and not data["warnings"]


def test_chat_gives_one_branch_per_chain_and_current_evidence(client):
    data = client.post(
        "/api/chat",
        json={
            "query": "тихое кафе с розеткой поработать",
            "provider": "offline",
            "latitude": 51.1325,
            "longitude": 71.4036,
            "minutes": 60,
        },
    ).json()
    names = [p["display_name"].casefold() for p in data["items"]]
    assert data["items"] and len(names) == len(set(names))
    for p in data["items"]:
        signals = p["review_signals"] or {}
        for attr, kind in p["evidence"].items():
            if kind not in ("confirmed", "unknown"):
                assert signals[attr]["status"] == kind


def test_landmark_start_far_from_street_and_night_intent(client):
    data = client.post(
        "/api/chat",
        json={
            "query": "Түнде қызықты бір нәрсе істегім келеді, Хан Шатыр жанындамын",
            "provider": "offline",
            "when": "2026-10-20T22:00:00",
        },
    ).json()
    assert data["origin"]["label"] == "Хан Шатыр"
    assert data["items"] and all(
        p["category"] in ("nightlife", "entertainment") for p in data["items"]
    )


def test_chat_warns_when_start_is_off_network(client):
    data = client.post(
        "/api/chat",
        json={"query": "кафе", "provider": "offline", "latitude": 51.49, "longitude": 71.89},
    ).json()
    assert not data["items"] and any("Точка старта" in w for w in data["warnings"])


def test_snap_radius_comes_from_the_request(client):
    meta = client.get("/api/meta").json()["snap_radius_m"]
    assert meta == {"default": 150, "min": 30, "max": 300}
    khan = {"query": "кафе", "latitude": 51.1325089, "longitude": 71.4038726, "minutes": 60}
    wide = client.post("/api/search", json={**khan, "max_snap_m": 150}).json()
    narrow = client.post("/api/search", json={**khan, "max_snap_m": 50}).json()
    assert wide["items"] and not wide["warnings"]
    assert not narrow["items"] and "50 м" in narrow["warnings"][0]
    assert all(p["route"]["destination_snap_m"] <= 150 for p in wide["items"])
    assert client.post("/api/search", json={**khan, "max_snap_m": 1000}).status_code == 422
    chat = client.post(
        "/api/chat",
        json={"query": "кафе у Хан Шатыра", "provider": "offline", "max_snap_m": 50},
    ).json()
    assert not chat["items"] and any("50 м" in w for w in chat["warnings"])


def test_walk_request_builds_mini_route_within_budget(client):
    data = client.post(
        "/api/chat",
        json={
            "query": "Хочу прогуляться 90 минут возле Байтерека",
            "provider": "offline",
            "when": "2026-10-20T15:00:00",
        },
    ).json()
    route = data["mini_route"]
    assert route and route["kind"] == "mini_route"
    assert 2 <= len(route["stops"]) <= 3 and len(route["legs"]) == len(route["stops"])
    assert route["total_duration_min"] <= 90 and route["budget_minutes"] == 90
    # The answer lists exactly the route stops, in route order.
    assert [p["poi_id"] for p in data["items"]] == [s["poi_id"] for s in route["stops"]]
    offsets = [s["arrival_offset_min"] for s in route["stops"]]
    assert offsets == sorted(offsets)
    assert all(s["hours_status"]["status"] not in ("closed_by_schedule", "closed_reported") for s in route["stops"])
    assert data["answer"].startswith("Мини-маршрут")
    assert any(s["action"] == "Мини-маршрут" for s in data["steps"])


def test_mini_route_only_on_walk_intent_or_toggle(client):
    base = {"provider": "offline", "when": "2026-10-20T15:00:00", "latitude": 51.089, "longitude": 71.403}
    plain = client.post("/api/chat", json={**base, "query": "Тихое кафе поработать"}).json()
    assert plain["mini_route"] is None
    forced = client.post("/api/chat", json={**base, "query": "Тихое кафе", "mini_route": True, "minutes": 150}).json()
    assert forced["mini_route"] and forced["mini_route"]["total_duration_min"] <= 150
    off = client.post("/api/chat", json={**base, "query": "прогулка", "mini_route": False}).json()
    assert off["mini_route"] is None


def test_mini_route_respects_budget_variety_and_hours():
    from backend.app import city
    from backend.service import City

    origin = (51.1282882, 71.4304546)
    when = "2026-10-20T15:00:00"
    for minutes in (60, 90, 150):
        pool = city.search("", origin=origin, minutes=minutes, when=when, limit=24, distinct_names=True)
        route = city.mini_route(pool, origin, minutes, when)
        if route is None:
            continue
        assert route["total_duration_min"] <= minutes
        stems = [" ".join(s["display_name"].casefold().split()[:2]) for s in route["stops"]]
        assert len(set(stems)) == len(stems)
    assert City.mini_route(city, [], origin, 60, when) is None
    assert city.mini_route(pool, None, 60, when) is None


def test_group_size_from_text():
    from backend.app import detect_group

    cases = {
        "Нас 5, хотим поужинать": 5,
        "компания из 4 человек": 4,
        "идём втроём": 3,
        "нас трое": 3,
        "бесеуміз серуендейміз": 5,
        "we are 3 friends": 3,
        "с друзьями в бар": 4,
        "тихое кафе": None,
        "строение у парка": None,
        "прогулка на 2 часа": None,
    }
    for text, size in cases.items():
        assert detect_group(text) == size, text


def test_group_mode_prefers_company_venues_and_budget(client):
    base = {"provider": "offline", "when": "2026-10-20T19:00:00", "minutes": 120}
    data = client.post("/api/chat", json={**base, "query": "Нас 5, хотим поужинать возле Байтерека"}).json()
    assert data["group"] == {"size": 5, "from_text": True}
    assert data["answer"].startswith("Подбор для компании из 5")
    assert any(s["action"] == "Компания" for s in data["steps"])
    assert any(any("Для компании" in r for r in p["reasons"]) for p in data["items"])
    for p in data["items"]:
        if p.get("group_cost"):
            assert p["group_cost"]["size"] == 5 and p["group_cost"]["amount"] >= 0
        if p["category"] == "food_drink":
            assert any("забронировать" in w for w in p["warnings"])
    # The UI selector overrides the text.
    forced = client.post("/api/chat", json={**base, "query": "поужинать", "group_size": 3}).json()
    assert forced["group"] == {"size": 3, "from_text": False}
    assert client.post("/api/chat", json={**base, "query": "кафе"}).json()["group"] is None


def test_events_are_timed_reachable_and_attached_to_venues(client):
    from backend.app import city
    from backend.hours import parse_when

    when = "2026-10-24T15:30:00"
    circus = (51.1449, 71.4185)
    events = city.events_nearby(circus, when, 120)
    timed = [e for e in events if e["timed"]]
    assert timed, "the circus show at 16:00 is a minute away"
    start = parse_when(when)
    for e in timed:
        ev = parse_when(e["start"])
        assert start <= ev and (ev - start).total_seconds() / 60 >= e["walk_min"]
    # Not reachable before the start: walking 5 minutes to a 15:31 start is impossible.
    assert not [e for e in city.events_nearby(circus, "2026-10-24T15:58:00", 60) if e["timed"] and e["start"].startswith("2026-10-24T16:00") and e["walk_min"] > 2]

    data = client.post(
        "/api/chat",
        json={"query": "Идём в цирк", "provider": "offline", "when": when, "latitude": circus[0], "longitude": circus[1]},
    ).json()
    assert data["events"] and any(s["action"] == "Афиша" for s in data["steps"])
    venue_items = [p for p in data["items"] if p.get("events")]
    assert venue_items and venue_items[0]["events"][0]["venue_poi_id"] == venue_items[0]["poi_id"]
    quiet = client.post("/api/chat", json={"query": "тихое кафе", "provider": "offline", "when": "2026-10-20T10:00:00"}).json()
    assert all((e["walk_min"] or 99) <= 20 for e in quiet["events"])


def test_tight_budget_keeps_nearby_places_with_short_visits(client):
    data = client.post(
        "/api/search",
        json={"latitude": 51.1282882, "longitude": 71.4304546, "minutes": 30, "when": "2026-10-20T15:00:00", "limit": 100},
    ).json()
    # Hundreds of places are within a 15-minute walk; a 30-minute budget must not empty the list.
    assert len(data["items"]) >= 20
    for p in data["items"]:
        assert p["total_duration_min"] <= 30
        if p.get("visit_shortened"):
            assert p["suggested_visit_duration_min"] < p["typical_visit_min"]
            assert any("Короткий визит" in w for w in p["warnings"])
    # A museum still needs at least half an hour inside: no fake 5-minute museum visits.
    museums = client.post(
        "/api/search",
        json={"query": "музей", "latitude": 51.1282882, "longitude": 71.4304546, "minutes": 30},
    ).json()["items"]
    assert all(p["suggested_visit_duration_min"] >= 30 for p in museums if p["category"] == "culture")


def test_every_landmark_start_finds_places_and_more_time_never_means_fewer(client):
    landmarks = client.get("/api/meta").json()["landmarks"]
    for key, lm in landmarks.items():
        counts = []
        for minutes in (30, 60, 120):
            data = client.post(
                "/api/search",
                json={"latitude": lm["lat"], "longitude": lm["lon"], "minutes": minutes, "when": "2026-10-20T15:00:00", "limit": 50},
            ).json()
            assert not data["warnings"], (key, data["warnings"])
            counts.append(len(data["items"]))
        assert counts[0] > 0, key
        assert counts == sorted(counts), (key, counts)


def test_page_is_revalidated_and_bundles_are_immutable(client):
    page = client.get("/")
    assert page.headers["cache-control"] == "no-cache"
    import re as _re

    bundle = _re.search(r"/assets/index-[\w-]+\.js", page.text).group(0)
    assert "immutable" in client.get(bundle).headers["cache-control"]
