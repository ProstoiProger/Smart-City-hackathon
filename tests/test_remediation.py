import json
import httpx
import pytest
from backend.app import app
from backend.settings import DATA
from backend.events import event_claim, recheck
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_primary_mosque_visitor_schedule(client):
    p = client.get("/api/pois/osm:way:240860325").json()
    assert p["opening_hours_by_day"]["Mo"] == [["06:00", "20:00"]]
    assert p["opening_hours_evidence"]["physically_verified"] is False
    assert p["opening_hours_evidence"]["source_url"].startswith(
        "https://visitastana.kz/"
    )


def test_named_subvenue_ticket_prices_not_assumed_adult(client):
    p = client.get("/api/pois/official:ailand_oceanarium").json()
    assert p["standard_ticket_price"]["amount"] == 5600
    assert p["child_ticket_price"]["amount"] == 4400
    assert p["adult_ticket_price"] is None
    assert {t["kind"] for t in p["ticket_options"]} == {
        "standard_entry_ticket",
        "child_entry_ticket",
    }
    assert (
        client.get("/api/pois/osm:way:240921034").json()["standard_ticket_price"]
        is None
    )


def test_summaries_are_explicitly_derived_and_originals_retained():
    pois = [json.loads(l) for l in (DATA / "pois.jsonl").open(encoding="utf-8")]
    derived = [
        p for p in pois if p.get("description_type") == "attribute_grounded_summary"
    ]
    assert len(derived) > 4000
    assert all(
        not p["description_provenance"]["independent_source_prose"]
        and p.get("description_original")
        for p in derived
    )
    assert sum(1 for l in (DATA / "source_pois.jsonl").open(encoding="utf-8")) == 7570


def test_explicit_children_facilities_ranked_without_inventing(client):
    result = client.post(
        "/api/search",
        json={
            "query": "кафе с детской комнатой",
            "strict_amenities": True,
            "when": "2026-10-20T12:00:00",
        },
    ).json()
    assert result["items"]
    assert all(
        p["category"] == "food_drink" and p["children_facilities"]
        for p in result["items"]
    )
    assert all(
        any("комнат" in f["feature"].casefold() for f in p["children_facilities"])
        for p in result["items"]
    )
    assert all(
        f["source_url"].startswith("https://2gis.kz/")
        for p in result["items"]
        for f in p["children_facilities"]
    )


def test_nearby_same_brand_not_repeated_but_source_facts_not_merged(client):
    pois = {
        p["poi_id"]: p
        for p in (json.loads(l) for l in (DATA / "pois.jsonl").open(encoding="utf-8"))
    }
    result = client.post(
        "/api/search",
        json={"query": "Coffee BOOM", "when": "2026-10-20T12:00:00", "limit": 100},
    ).json()
    groups = [
        pois[p["poi_id"]]["recommendation_diversity_group"] for p in result["items"]
    ]
    assert len(groups) == len(set(groups))
    reviewed = [
        json.loads(l)
        for l in (DATA / "duplicate_review_decisions.jsonl").open(encoding="utf-8")
    ]
    assert len(reviewed) == 124 and all(not r["physically_verified"] for r in reviewed)


def test_entrance_claim_not_full_wheelchair_access(client):
    pois = [json.loads(l) for l in (DATA / "pois.jsonl").open(encoding="utf-8")]
    original = next(p for p in pois if p.get("entrance_accessible") is True)
    card = client.get("/api/pois/" + original["poi_id"]).json()
    assert card["entrance_accessible"] is True and card["wheelchair_accessible"] is None


def test_park_geometries_are_different_not_duplicates():
    review = json.loads(
        (DATA / "president_park_geometry_review.json").read_text(encoding="utf-8")
    )
    assert review["intersects"] is False and review["overlap_ratio"] == 0


def test_cancelled_occurrence_is_publisher_claim_not_physical_confirmation():
    html = (
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "MusicEvent",
                "startDate": "2026-11-01T19:00:00+05:00",
                "eventStatus": "https://schema.org/EventCancelled",
            }
        )
        + "</script>"
    )
    claim = event_claim(html, {"event_start": "2026-11-01"})
    assert (
        claim["cancelled_as_reported"] is True
        and claim["occurrence_identified"] is True
    )
    assert not event_claim(html, {"event_start": "2026-11-02"})["occurrence_identified"]


def test_unavailable_or_untrusted_event_source_never_confirmed(monkeypatch):
    unsupported = recheck(
        {
            "event_id": "unsafe",
            "source_url": "http://127.0.0.1/private",
            "event_start": "2026-11-01",
        }
    )
    assert (
        unsupported["live_verified"] is False
        and not unsupported["source_page_available"]
    )

    def fail(*args, **kwargs):
        raise httpx.ConnectError("simulated unavailable publisher")

    monkeypatch.setattr("backend.events.httpx.Client.get", fail)
    result = recheck(
        {
            "event_id": "test-unavailable-unique",
            "source_url": "https://ticketon.kz/event/example",
            "event_start": "2026-11-01",
        }
    )
    assert result["live_verified"] is False and not result["source_page_available"]


def test_missing_data_backlog_and_price_kind_constraints():
    missing = [
        json.loads(l)
        for l in (DATA / "missing_data_backlog.jsonl").open(encoding="utf-8")
    ]
    assert len(missing) > 7000 and all(p["missing_fields"] for p in missing)
    report = json.loads(
        (DATA / "all_venue_enrichment_summary.json").read_text(encoding="utf-8")
    )
    assert report["all_prices_all_rules_all_statuses_complete"] is False
    assert report["objects_with_branch_price_or_budget"] > 2700


def test_flight_budget_assumes_labelled_buffers_and_deducts_them(client):
    r = client.post(
        "/api/chat",
        json={"query": "До вылета 2 часа, где погулять?", "provider": "offline", "when": "2026-10-20T12:00:00"},
    ).json()
    # Without the user's own buffers the chat assumes 30 + 60 min, says so, and still answers.
    fc = r["flight_context"]
    assert fc["needs_buffers"] and fc["buffers_source"] == "default_assumption"
    assert fc["walk_budget_minutes"] == 30 and r["minutes"] == 30
    assert "30 мин на дорогу" in r["answer"] and any("допущение" in w for w in r["warnings"])
    assert any(c["label"] == "Вылет" for c in r["considered"])
    assert all(p["total_duration_min"] <= 30 for p in r["items"])
    r = client.post(
        "/api/chat",
        json={
            "query": "До вылета 2 часа, где погулять?",
            "provider": "offline",
            "airport_transfer_min": 30,
            "airport_reserve_min": 60,
            "when": "2026-10-20T12:00:00",
        },
    ).json()
    assert r["flight_context"]["walk_budget_minutes"] == 30
    assert r["flight_context"]["buffers_source"] == "user_input"
    assert all(p["total_duration_min"] <= 30 for p in r["items"])


def test_private_osm_access_not_recommended():
    pois = [json.loads(l) for l in (DATA / "pois.jsonl").open(encoding="utf-8")]
    assert all(
        not p["recommendation_eligible"]
        for p in pois
        if p.get("recommendation_exclusion_reason")
    )
