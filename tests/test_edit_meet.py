"""Plan B next to each stop, editing a route in plain words, a meeting place for a company."""

import pytest
from fastapi.testclient import TestClient
import backend.app as app_module
from backend.app import app
from backend.routing import meters
from backend.trip import BACKUP_RADIUS_MIN, read_edit_rules

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


@pytest.fixture(scope="module")
def walk(client):
    return chat(client, "Погулять 2 часа: парк, кофе и музей")["mini_route"]


def context(route, **extra):
    s = route["session"]
    return {**s, "elapsed": 0, "position": s["start"], "keep": [x["poi_id"] for x in route["stops"]],
            "visited": [], "excluded": [], "flags": [], **extra}


# --- plan B ---------------------------------------------------------------------------------

def test_plan_b_is_near_the_stop_of_the_same_kind_or_under_a_roof(walk):
    backed = [s for s in walk["stops"] if s.get("backup")]
    assert backed
    for s in backed:
        b = s["backup"]
        assert b["poi_id"] not in {x["poi_id"] for x in walk["stops"]}
        assert b["walk_from_stop_min"] <= BACKUP_RADIUS_MIN + 2
        assert meters((s["latitude"], s["longitude"]), (b["latitude"], b["longitude"])) <= BACKUP_RADIUS_MIN * 80
        assert b["category"] == s["category"] or b["kind"] == "indoor"
        assert isinstance(b["fits"], bool) and b["hours_status"]["status"] != "closed_by_schedule"
    cafe = next(s for s in walk["stops"] if s["category"] == "food_drink")
    assert cafe["backup"]["category"] == "food_drink"


def test_taking_plan_b_swaps_one_stop_and_keeps_the_rest(client, walk):
    stop = next(s for s in walk["stops"] if s.get("backup"))
    r = client.post("/api/replan", json={**context(walk), "action": "swap", "stop_id": stop["poi_id"],
                                         "replacement_id": stop["backup"]["poi_id"]}).json()
    ids = [s["poi_id"] for s in r["plan"]["stops"]]
    assert stop["backup"]["poi_id"] in ids and stop["poi_id"] not in ids
    others = [s["poi_id"] for s in walk["stops"] if s is not stop]
    assert set(others) <= set(ids)
    assert "запасной вариант" in r["answer"]


# --- edits in words -------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Первое место оставь, второе замени", {"keep": [1], "replace": [2]}),
    ("Последнее убери", {"remove": [3]}),
    ("Без кафе", {"exclude_categories": ["food_drink"]}),
    ("Ещё варианты, но ближе", {"more": True, "closer": True}),
    ("Добавь музей", {"add": "музей"}),
])
def test_edit_words_are_read_without_a_model(text, expected):
    ops = read_edit_rules(text, 3)
    assert ops["is_edit"]
    for key, value in expected.items():
        assert ops[key] == value


def test_a_new_request_is_not_an_edit():
    assert not read_edit_rules("Хочу кафе поближе к опере", 3)["is_edit"]
    assert not read_edit_rules("Где поесть корейскую кухню?", 3)["is_edit"]


def test_keep_the_first_replace_the_second(client, walk):
    first, second = walk["stops"][0], walk["stops"][1]
    r = chat(client, "Первое место оставь, второе замени", route=context(walk))
    ids = [s["poi_id"] for s in r["mini_route"]["stops"]]
    assert first["poi_id"] in ids and second["poi_id"] not in ids
    assert r["edit"] and r["trip_state"]["excluded"] == [second["poi_id"]]
    assert r["mini_route"]["session"]["start_at"] == walk["session"]["start_at"]
    assert r["items"] and all(i["why"] for i in r["items"])


def test_without_cafes_and_company_size(client, walk):
    r = chat(client, "Без кафе", route=context(walk))
    assert r["mini_route"]["stops"] and all(s["category"] != "food_drink" for s in r["mini_route"]["stops"])
    r = chat(client, "Теперь нас четверо", route=context(walk))
    assert r["group"]["size"] == 4 and r["mini_route"]["session"]["group_size"] == 4


def test_closer_caps_the_walks_and_says_what_is_missing(client, walk):
    r = chat(client, "Ещё варианты, но ближе", route=context(walk))
    route = r["mini_route"]
    assert not {s["poi_id"] for s in route["stops"]} & {s["poi_id"] for s in walk["stops"]}
    assert all(leg["duration_min"] <= 10 for leg in route["legs"][1:])


def test_a_new_question_during_a_walk_is_answered_as_new(client, walk):
    r = chat(client, "Хочу в театр", route=context(walk))
    assert "edit" not in r and r["items"]


# --- meeting place -------------------------------------------------------------------------

def test_meeting_place_for_three_people_from_three_starts(client):
    r = chat(client, "Я у EXPO, Алина у Хан Шатыра, Данияр у Байтерека. Где встретиться, чтобы всем было удобно?")
    assert r["items"] and r["meeting"]["people"][0]["name"] == "Вы"
    assert [p["name"] for p in r["meeting"]["people"]] == ["Вы", "Алина", "Данияр"]
    first = r["items"][0]
    walks = [m["walk_min"] for m in first["meeting"]]
    assert len(walks) == 3 and max(walks) <= 60
    assert len(first["meeting_routes"]) == 3
    assert "Вы —" in r["answer"] and "Алина —" in r["answer"]
    # Fairness: the best place keeps the longest walk shorter than the far side of the city.
    assert max(walks) < 63  # EXPO → Байтерек on foot


def test_meeting_without_my_place_uses_the_map_start(client):
    r = chat(client, "Алина у Хан Шатыра, Данияр у Национального музея. Где нам встретиться попить кофе?")
    names = [p["name"] for p in r["meeting"]["people"]]
    assert names == ["Вы", "Алина", "Данияр"]
    assert all(i["category"] == "food_drink" for i in r["items"])


def test_meeting_people_read_by_the_model(client, monkeypatch):
    monkeypatch.setattr(app_module, "read_people", lambda q: {
        "is_meeting": True, "wish": "",
        "people": [{"name": "Вы", "place": "EXPO"}, {"name": "Алина", "place": "Хан Шатыр"}],
    })
    r = client.post("/api/chat", json={**BAYTEREK, "query": "мы с Алиной хотим встретиться, я на экспо, она в хан шатыре",
                                       "when": WHEN, "provider": "gemini"}).json()
    assert [p["name"] for p in r["meeting"]["people"]] == ["Вы", "Алина"]
    assert r["items"] and any("Gemini" in c["value"] for c in r["considered"])


def test_one_person_is_not_a_meeting(client):
    r = chat(client, "Где встретиться у Байтерека?")
    assert "meeting" not in r
