"""Dialogue state: "ещё" excludes past variants, "убери второе" keeps the others,
a new interest drops the old filters."""

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


def say(client, query, dialog=None, **extra):
    r = client.post("/api/chat", json={**BAYTEREK, "query": query, "when": WHEN, "provider": "offline",
                                       "dialog": dialog, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def ids(r):
    return [i["poi_id"] for i in r["items"]]


def test_more_never_repeats_what_was_shown(client):
    first = say(client, "Хочу выпить кофе")
    assert first["dialog"]["items"] == ids(first) and len(ids(first)) == 3
    second = say(client, "Ещё", first["dialog"])
    third = say(client, "ещё варианты", second["dialog"])
    seen = ids(first) + ids(second) + ids(third)
    assert len(seen) == len(set(seen)) == 9
    assert all(i["category"] == "food_drink" for i in second["items"] + third["items"])
    assert set(third["dialog"]["shown"]) == set(seen)


def test_remove_the_second_keeps_the_others_in_order(client):
    first = say(client, "Хочу выпить кофе")
    a, b, c = ids(first)
    r = say(client, "Убери второе", first["dialog"])
    assert ids(r) == [a, c]
    assert "остальные оставил" in r["answer"]
    # The removed place does not come back with the next "ещё".
    more = say(client, "Ещё", r["dialog"])
    assert b not in ids(more) and a not in ids(more) and c not in ids(more)


def test_refinements_stay_until_a_new_interest(client):
    first = say(client, "Хочу выпить кофе")
    closer = say(client, "Ближе", first["dialog"])
    assert closer["dialog"]["filters"]["max_walk"] == 15
    assert all(i["route"]["duration_min"] <= 15 for i in closer["items"])
    more = say(client, "Ещё", closer["dialog"])
    assert all(i["route"]["duration_min"] <= 15 for i in more["items"])
    assert any(c["label"] == "Действует" for c in more["considered"])
    # A new interest is a new search: the filters and the shown list are dropped.
    museum = say(client, "А теперь хочу в музей", more["dialog"])
    assert museum["dialog"]["filters"] == {} and museum["dialog"]["shown"] == ids(museum)
    assert museum["items"] and all(i["category"] == "culture" for i in museum["items"])


def test_without_cafes_replaces_them(client):
    first = say(client, "Куда сходить с ребёнком")
    r = say(client, "Без кафе", first["dialog"])
    assert r["items"] and all(i["category"] != "food_drink" for i in r["items"])
    assert r["dialog"]["filters"]["exclude_categories"] == ["food_drink"]


def test_new_interest_switches_off_a_contradicting_category_chip(client):
    r = say(client, "Хочу в музей", category="food_drink")
    assert r["cleared_category"] == "food_drink"
    assert r["items"] and all(i["category"] == "culture" for i in r["items"])
    assert any(c["label"] == "Фильтр снят" for c in r["considered"])
    # A chip that fits the request stays on.
    r = say(client, "Хочу выпить кофе", category="food_drink")
    assert r["cleared_category"] is None
