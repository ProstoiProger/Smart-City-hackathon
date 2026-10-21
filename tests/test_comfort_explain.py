import pytest
from fastapi.testclient import TestClient
import backend.app as app_module
from backend.app import app
from backend.comfort import assess, exposure
from backend.hours import parse_when
from backend.explain import Trace

NOW = parse_when("2026-10-21T12:00:00")
MILD = {"available": True, "temperature_c": 14, "feels_like_c": 13, "precipitation_mm": 0, "weather_code": 1, "wind_kmh": 8}
FROST = {"available": True, "temperature_c": -24, "feels_like_c": -31, "precipitation_mm": 0, "weather_code": 3, "wind_kmh": 12}
BAYTEREK = {"latitude": 51.1283, "longitude": 71.4305, "minutes": 90, "provider": "offline"}
REASONS = {
    "ranked_lower", "outdoor_weather", "closed_at_arrival", "no_time", "walk_limit", "no_route",
    "amenity_unconfirmed", "too_far", "similar_shown", "hours_unknown",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def weather(monkeypatch):
    def use(now, air=None):
        monkeypatch.setattr(app_module, "current_weather", lambda: now)
        monkeypatch.setattr(app_module, "current_air", lambda: air or {"available": False})

    return use


def test_assess_frost_is_severe_and_penalises_outdoor():
    c = assess(FROST, {"available": False}, now=NOW)
    assert c["applies"] and c["level"] == "severe"
    assert [f["code"] for f in c["factors"]] == ["frost"]
    assert c["outdoor_penalty"] > assess({**MILD, "wind_kmh": 45}, None, now=NOW)["outdoor_penalty"] > 0


def test_assess_mild_weather_changes_nothing():
    c = assess(MILD, {"available": True, "aqi": 25, "pm2_5": 8}, now=NOW)
    assert c["level"] == "ok" and c["factors"] == [] and c["outdoor_penalty"] == 0


def test_assess_rain_wind_and_smog_are_separate_factors():
    rain = {**MILD, "precipitation_mm": 1.2, "weather_code": 61, "wind_kmh": 45}
    air = {"available": True, "aqi": 92, "pm2_5": 61}
    codes = {f["code"] for f in assess(rain, air, now=NOW)["factors"]}
    assert codes == {"wet", "wind", "smog"}


def test_moderate_air_is_advice_not_a_ranking_change():
    c = assess(MILD, {"available": True, "aqi": 65, "pm2_5": 20}, now=NOW)
    assert c["factors"][0]["level"] == "advisory" and c["outdoor_penalty"] == 0


def test_conditions_describe_only_the_present():
    c = assess(FROST, None, when="2026-11-02T12:00:00", now=NOW)
    assert c["applies"] is False and c["factors"] == []


def test_unavailable_weather_is_not_guessed():
    assert assess({"available": False}, {"available": False}, now=NOW)["factors"] == []


def test_exposure_classes():
    assert exposure({"category": "nature", "subcategory": "park"}) == "outdoor"
    assert exposure({"category": "culture", "subcategory": "museum"}) == "indoor"
    assert exposure({"category": "sightseeing", "subcategory": "mosque"}) == "mixed"
    assert exposure({"category": "food_drink", "subcategory": "cafe", "indoor_outdoor": "both"}) == "mixed"


def test_frost_moves_a_walk_indoors(client, weather):
    weather(MILD)
    mild = client.post("/api/chat", json={"query": "хочу прогуляться", **BAYTEREK}).json()
    weather(FROST)
    frost = client.post("/api/chat", json={"query": "хочу прогуляться", **BAYTEREK}).json()
    assert any(p["exposure"] == "outdoor" for p in mild["items"])
    assert all(p["exposure"] != "outdoor" for p in frost["items"])
    assert frost["comfort"]["level"] == "severe"
    assert any(c["label"] == "Погода и воздух" for c in frost["considered"])
    assert not any(c["label"] == "Погода и воздух" for c in mild["considered"])
    assert any(p.get("comfort") == "indoor" for p in frost["items"])


def test_other_date_ignores_live_weather(client, weather):
    weather(FROST)
    r = client.post(
        "/api/chat", json={"query": "хочу прогуляться", "when": "2030-01-01T12:00:00", **BAYTEREK}
    ).json()
    assert r["comfort"]["applies"] is False
    assert any(p["exposure"] == "outdoor" for p in r["items"])


def test_weather_endpoint_carries_air_and_comfort(client, weather):
    weather(FROST, {"available": True, "aqi": 55, "pm2_5": 14})
    data = client.get("/api/weather").json()
    assert data["air"]["aqi"] == 55 and data["comfort"]["level"] == "severe"


def test_funnel_narrows_and_ends_with_the_answer(client, weather):
    weather(MILD)
    r = client.post("/api/chat", json={"query": "хочу прогуляться", **BAYTEREK}).json()
    counts = [row["count"] for row in r["funnel"]]
    assert [row["key"] for row in r["funnel"]] == ["matched", "nearby", "reachable", "open", "answer"]
    assert counts == sorted(counts, reverse=True) and counts[-1] == len(r["items"])


def test_rejected_places_have_a_known_reason_and_are_not_in_the_answer(client, weather):
    weather(MILD)
    r = client.post("/api/chat", json={"query": "хочу прогуляться", **BAYTEREK}).json()
    shown = {p["poi_id"] for p in r["items"]}
    assert r["rejected"]
    for row in r["rejected"]:
        assert row["code"] in REASONS and row["poi_id"] not in shown and row["name"]
    assert sum(1 for row in r["rejected"] if row["code"] == "ranked_lower") <= 3


def test_no_time_reason_carries_the_numbers(client, weather):
    weather(MILD)
    r = client.post("/api/chat", json={"query": "хочу прогуляться", **{**BAYTEREK, "minutes": 30}}).json()
    row = next(x for x in r["rejected"] if x["code"] in ("no_time", "too_far"))
    assert row["params"]


def test_strict_amenities_explains_unconfirmed_places(client, weather):
    weather(MILD)
    r = client.post(
        "/api/chat",
        json={"query": "кафе с розеткой", "strict_amenities": True, **BAYTEREK},
    ).json()
    codes = {x["code"] for x in r["rejected"]}
    assert "amenity_unconfirmed" in codes
    row = next(x for x in r["rejected"] if x["code"] == "amenity_unconfirmed")
    assert row["params"]["attrs"] == ["розетки"]


def test_trace_keeps_first_reason_and_limits_each_code():
    t = Trace()
    places = [{"poi_id": f"p{i}", "display_name": f"Place {i}"} for i in range(6)]
    for i, p in enumerate(places):
        t.reject(p, "no_time", i)
    t.reject(places[5], "too_far", 99)
    top = t.top(6)
    assert len(top) == 3 and top[0]["poi_id"] == "p5" and top[0]["code"] == "no_time"
    assert all("rank" not in row for row in top)


def pick(city, test):
    return next(p["poi_id"] for p in city.pois if test(p))


def ask(client, pid, question, **extra):
    r = client.post(f"/api/pois/{pid}/ask", json={"question": question, **extra})
    assert r.status_code == 200
    return {a["topic"]: a for a in r.json()["answers"]}


def test_place_qa_unknown_place_is_404(client):
    assert client.post("/api/pois/nope/ask", json={"question": "до скольки?"}).status_code == 404


def test_place_qa_free_entry_is_yes(client):
    pid = pick(app_module.city, lambda p: p.get("free_entry") is True)
    a = ask(client, pid, "вход бесплатный?")["price"]
    assert a["certainty"] == "yes" and a["evidence"]


def test_place_qa_hours_use_schedule_and_never_claim_certainty(client):
    pid = pick(app_module.city, lambda p: p.get("opening_hours_by_day") and p["opening_hours_by_day"].get("Mo"))
    a = ask(client, pid, "До скольки работает?", when="2026-10-19T12:00:00")["hours"]
    assert a["certainty"] == "likely" and "Праздничные изменения не проверены" in a["evidence"]
    assert "Сегодня (пн)" in a["answer"]


def test_place_qa_missing_hours_is_unknown(client):
    pid = pick(app_module.city, lambda p: not p.get("opening_hours_by_day") and p.get("opening_hours") != "24/7")
    assert ask(client, pid, "во сколько закрывается")["hours"]["certainty"] == "unknown"


def test_place_qa_amenity_certainty_follows_the_evidence(client):
    from backend.service import evidence

    city = app_module.city

    def status(p, attr="wifi"):
        return evidence(p, attr, (city.review_signals.get(p["poi_id"]) or {}).get("signals"))[0]

    supported = pick(city, lambda p: status(p) == "supported")
    unknown = pick(city, lambda p: status(p) == "unknown")
    assert ask(client, supported, "есть вайфай?")["wifi"]["certainty"] == "likely"
    assert ask(client, unknown, "есть вайфай?")["wifi"]["certainty"] == "unknown"


def test_place_qa_answers_each_topic_in_one_question(client):
    pid = pick(app_module.city, lambda p: p.get("address"))
    got = ask(client, pid, "где находится и есть ли розетки?")
    assert {"address", "power_outlets"} <= set(got)


def test_place_qa_unanswerable_says_so(client):
    pid = pick(app_module.city, lambda p: p.get("address") and not p.get("semantic_attributes"))
    a = ask(client, pid, "подают ли здесь устрицы по средам")
    assert a["unknown"]["certainty"] == "unknown" and a["unknown"]["source"] == "none"


def test_place_qa_rejects_empty_question(client):
    assert client.post("/api/pois/osm:way:230401645/ask", json={"question": " "}).status_code == 422
