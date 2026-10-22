"""Walk history stays in the browser; the server only receives the ids to leave out
("покажи новое") and never stores them."""

import pytest
from fastapi.testclient import TestClient
from backend.app import app

BAYTEREK = {"latitude": 51.1282882, "longitude": 71.4304546}
WHEN = "2026-10-22T13:00:00"


@pytest.fixture(autouse=True)
def no_live_weather(monkeypatch):
    monkeypatch.setattr("backend.app.current_weather", lambda: {"available": False})
    monkeypatch.setattr("backend.app.current_air", lambda: {"available": False})


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def ids(items):
    return [p["poi_id"] for p in items]


def test_search_leaves_out_visited_places(client):
    body = {**BAYTEREK, "query": "кофе", "when": WHEN, "limit": 10}
    first = ids(client.post("/api/search", json=body).json()["items"])
    assert len(first) >= 3
    again = ids(client.post("/api/search", json={**body, "exclude_ids": first[:2]}).json()["items"])
    assert not set(first[:2]) & set(again)
    assert again[0] == first[2]


def test_chat_leaves_out_visited_places(client):
    body = {**BAYTEREK, "query": "выпить кофе", "when": WHEN, "provider": "offline"}
    first = ids(client.post("/api/chat", json=body).json()["items"])
    assert first
    again = ids(client.post("/api/chat", json={**body, "exclude_ids": first}).json()["items"])
    assert again and not set(first) & set(again)


def test_a_place_named_in_the_request_is_still_found(client):
    body = {**BAYTEREK, "query": "Хан Шатыр", "when": WHEN, "limit": 5}
    found = ids(client.post("/api/search", json=body).json()["items"])
    assert found
    kept = ids(client.post("/api/search", json={**body, "exclude_ids": found[:1]}).json()["items"])
    assert found[0] in kept


def test_exclusion_list_is_bounded(client):
    r = client.post("/api/search", json={**BAYTEREK, "query": "кофе", "exclude_ids": [f"x:{i}" for i in range(101)]})
    assert r.status_code == 422
