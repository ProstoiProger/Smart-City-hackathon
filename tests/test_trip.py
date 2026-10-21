"""A walk with a finish ("через час нужно быть в MEGA") and re-planning it on the go."""

from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.hours import ASTANA
from backend.query import finish_cue, parse_deadline, parse_reserve, tokens, wants_loop

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


def chat(client, query, **extra):
    r = client.post("/api/chat", json={**BAYTEREK, "query": query, "when": WHEN, "provider": "offline", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_finish_words_deadline_and_reserve_parsing():
    toks = tokens("Через час нужно быть в MEGA")
    assert finish_cue(toks, 5, 5)
    assert not finish_cue(tokens("Хочу сходить в MEGA"), 3, 3)
    assert wants_loop("погулять и вернуться к началу") and wants_loop("round trip please")
    start = datetime(2026, 10, 22, 13, 0, tzinfo=ASTANA)
    assert parse_deadline("к 15:00 быть в Хан Шатыре", start) == (120, "к 15:00 (из текста)")
    assert parse_deadline("к 12:00", start)[0] == 0  # already late, not tomorrow
    assert parse_reserve("с запасом 5 минут") == 5 and parse_reserve("без запаса") == 0
    assert parse_reserve("кофе по пути") is None


def test_pdf_example_too_far_on_foot_is_said_honestly(client):
    # Байтерек → MEGA is ~71 min on the walking graph: an hour is not enough on foot.
    r = chat(client, "Я у Байтерека. Через час нужно быть в MEGA. Хочу по пути выпить кофе")
    f = r["mini_route"]["finish"]
    assert f["label"] == "MEGA Silk Way" and not f["fits"]
    assert r["mini_route"]["stops"] == [] and r["items"] == []
    assert "не успеть" in r["answer"] and "MEGA" in r["answer"]
    assert {"label": "Финиш", "value": "MEGA Silk Way (из текста)"} in r["considered"]
    assert r["origin"]["label"] == "Бәйтерек"  # MEGA is the finish, not the start


def test_coffee_on_the_way_counts_the_last_leg_and_reserve(client):
    r = chat(client, "Я у Байтерека. Через 2 часа нужно быть в MEGA. Хочу по пути выпить кофе")
    route = r["mini_route"]
    f = route["finish"]
    assert len(route["stops"]) == 1 and route["stops"][0]["category"] == "food_drink"
    assert f["fits"] and f["reserve_min"] == 10
    stop = route["stops"][0]
    # start → stop → visit → finish, all inside the budget with the reserve.
    assert f["arrival_offset_min"] == pytest.approx(
        stop["arrival_offset_min"] + stop["suggested_visit_duration_min"] + f["leg"]["duration_min"], abs=1
    )
    assert f["arrival_offset_min"] + f["reserve_min"] <= 120
    assert f["arrival_at"].startswith("2026-10-22T") and "MEGA" in r["answer"]
    # MEGA is neither a stop nor what the search looks for.
    assert "MEGA" not in route["session"]["query"] and route["session"]["finish"]["label"] == "MEGA Silk Way"


def test_clock_deadline_and_named_kinds_on_the_way(client):
    r = chat(client, "Я у Байтерека, к 15:00 нужно быть в Хан Шатыре, маршрут: парк, кофе и музей")
    route = r["mini_route"]
    assert r["minutes"] == 120
    assert {s["category"] for s in route["stops"]} >= {"food_drink", "culture", "nature"}
    assert route["finish"]["label"] == "Хан Шатыр" and route["finish"]["fits"]


def test_loop_walk_returns_to_the_start(client):
    r = chat(client, "Погулять 90 минут и вернуться к началу, хочу парк и кофе")
    f = r["mini_route"]["finish"]
    assert f["loop"] and f["reserve_min"] == 0 and f["fits"]
    assert (f["latitude"], f["longitude"]) == (BAYTEREK["latitude"], BAYTEREK["longitude"])
    assert r["mini_route"]["return_trip_included"] is True


def test_finish_from_the_walk_conditions(client):
    r = chat(client, "Хочу выпить кофе", finish_latitude=51.1354512, finish_longitude=71.410753, finish_label="Астана Опера")
    f = r["mini_route"]["finish"]
    assert f["label"] == "Астана Опера" and f["fits"]
    assert len(r["mini_route"]["stops"]) == 1


def test_destination_to_visit_is_not_a_finish(client):
    r = chat(client, "Хочу сходить в Хан Шатыр")
    assert not (r["mini_route"] or {}).get("finish")


@pytest.fixture(scope="module")
def walk(client):
    r = chat(client, "Я у Байтерека, к 15:00 нужно быть в Хан Шатыре, маршрут: парк, кофе и музей")
    return r["mini_route"]


def replan(client, walk, **extra):
    s = walk["session"]
    body = {
        "query": s["query"], "start_at": s["start_at"], "budget": s["budget"], "finish": s["finish"],
        "reserve": s["reserve"], "keep": [p["poi_id"] for p in walk["stops"]], "position": BAYTEREK, **extra,
    }
    r = client.post("/api/replan", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_closed_stop_is_replaced_and_finish_kept(client, walk):
    first = walk["stops"][0]
    # "Здесь закрыто" at the door: the rest of the walk starts at the closed place.
    r = replan(
        client, walk, action="closed", stop_id=first["poi_id"], elapsed=first["arrival_offset_min"],
        position={"latitude": first["latitude"], "longitude": first["longitude"]},
    )
    ids = [s["poi_id"] for s in r["plan"]["stops"]]
    assert r["state"]["position"] == {"latitude": first["latitude"], "longitude": first["longitude"]}
    assert first["poi_id"] not in ids and first["poi_id"] in r["state"]["excluded"]
    assert len(ids) == len(walk["stops"])
    assert r["plan"]["finish"]["label"] == "Хан Шатыр" and r["plan"]["finish"]["fits"]
    assert "закрыто" in r["answer"] and r["changes"]["removed"]


def test_delay_keeps_the_plan_when_it_still_fits(client, walk):
    first = walk["stops"][0]
    r = replan(
        client, walk, action="delay", visited=[first["poi_id"]],
        keep=[s["poi_id"] for s in walk["stops"][1:]],
        elapsed=first["arrival_offset_min"] + first["suggested_visit_duration_min"],
        position={"latitude": first["latitude"], "longitude": first["longitude"]},
    )
    assert r["state"]["remaining_min"] == pytest.approx(
        120 - first["arrival_offset_min"] - first["suggested_visit_duration_min"] - 15, abs=0.5
    )
    f = r["plan"]["finish"]
    assert f["fits"] and f["arrival_offset_min"] <= 120 - 10
    assert all(s["arrival_offset_min"] > first["arrival_offset_min"] for s in r["plan"]["stops"])


def test_cold_keeps_only_places_under_a_roof(client, walk):
    from backend.comfort import exposure

    r = replan(client, walk, action="cold", elapsed=0)
    assert "indoor" in r["state"]["flags"]
    app_city = __import__("backend.app", fromlist=["city"]).city
    assert all(exposure(app_city.byid[s["poi_id"]]) != "outdoor" for s in r["plan"]["stops"])
    assert all(leg["duration_min"] <= 10 for leg in r["plan"]["legs"])


def test_tired_means_one_stop_less_and_short_walks(client, walk):
    r = replan(client, walk, action="tired", elapsed=0)
    assert len(r["plan"]["stops"]) <= len(walk["stops"]) - 1
    assert all(leg["duration_min"] <= 8 for leg in r["plan"]["legs"])
    assert "rest" in r["state"]["flags"]


def test_too_late_goes_straight_to_the_finish_and_says_so(client, walk):
    r = replan(client, walk, action="delay", delay_min=60, elapsed=50)
    assert r["plan"]["stops"] == []
    assert not r["plan"]["finish"]["fits"] and "не успеть" in r["answer"]


def test_replan_rejects_bad_input(client, walk):
    s = walk["session"]
    base = {"query": "", "start_at": s["start_at"], "budget": 120, "position": BAYTEREK}
    assert client.post("/api/replan", json={**base, "action": "fly"}).status_code == 422
    assert client.post("/api/replan", json={**base, "action": "delay", "start_at": "вчера"}).status_code == 422
    assert client.post("/api/replan", json={**base, "action": "delay", "position": {"latitude": 10, "longitude": 10}}).status_code == 422
