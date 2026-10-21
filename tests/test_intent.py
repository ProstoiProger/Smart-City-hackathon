"""The request read by Gemini (backend/intent.py): catalogue checks and the search it drives.
No real Gemini calls: the model's answer is substituted."""

import pytest
from fastapi.testclient import TestClient
import backend.app as app_module
from backend import intent as intent_module
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


def test_model_answer_is_kept_inside_the_catalogue(client):
    clf = app_module.classifier
    out = clf.clean({
        "categories": ["culture", "spaceships"],
        "subcategories": ["gallery", "ice_rink", "unicorn"],
        "amenities": ["quiet", "teleport"],
        "keywords": "  галерея   искусств ",
        "setting": "underwater",
        "combine": True,
        "note": "рисование",
    })
    assert out["categories"] == ["culture", "sport"]  # ice_rink brings its category in
    assert out["subcategories"] == ["gallery", "ice_rink"]
    assert out["amenities"] == ["quiet"]
    assert out["keywords"] == "галерея искусств" and out["setting"] == "any"
    assert "theatre" in clf.catalog and "Художественная галерея" in clf.catalog


def test_without_a_key_the_rules_read_the_request(client, monkeypatch):
    monkeypatch.setattr(intent_module, "configured", lambda provider: False)
    assert app_module.classifier.classify("хочу рисовать") is None


def test_classify_caches_and_survives_model_errors(client, monkeypatch):
    clf = app_module.classifier
    calls = []

    def fake(prompt, schema, **kw):
        calls.append(prompt)
        assert prompt.endswith("на каток") and schema["properties"]["subcategories"]["items"]["enum"]
        return {"categories": ["sport"], "subcategories": ["ice_rink"], "amenities": [], "keywords": "каток",
                "setting": "any", "combine": False, "note": "каток"}

    monkeypatch.setattr(intent_module, "configured", lambda provider: True)
    monkeypatch.setattr(intent_module, "gemini_json", fake)
    clf.cache.clear()
    assert clf.classify("Хочу  на каток")["subcategories"] == ["ice_rink"]
    assert clf.classify("хочу на каток")["subcategories"] == ["ice_rink"]
    assert len(calls) == 1

    def broken(*a, **kw):
        raise intent_module.ProviderError("Gemini: превышена квота (HTTP 429)")

    monkeypatch.setattr(intent_module, "gemini_json", broken)
    assert clf.classify("хочу в боулинг") is None


ART = {"categories": ["culture"], "subcategories": ["gallery", "arts_centre"], "amenities": [],
       "keywords": "галерея искусств", "setting": "indoor", "combine": False,
       "note": "рисование: галереи и центры искусств"}


def test_chat_searches_by_the_read_intent(client, monkeypatch):
    seen = []
    monkeypatch.setattr(app_module.classifier, "classify", lambda q: seen.append(q) or ART)
    # The model writes no text here: it fails, so the data templates answer.
    monkeypatch.setattr("backend.providers.configured", lambda provider: False)
    r = client.post("/api/chat", json={**BAYTEREK, "query": "Я у Байтерека, а я бы хотел рисовать",
                                       "when": WHEN, "provider": "gemini"}).json()
    assert seen and "Байтерек" not in seen[0]  # the start is not part of the wish
    assert r["items"] and all(i["subcategory"] in ("gallery", "arts_centre") for i in r["items"])
    assert {"label": "Понял запрос", "value": "рисование: галереи и центры искусств (разбор: Gemini)"} in r["considered"]


def test_offline_chat_does_not_call_the_model(client, monkeypatch):
    monkeypatch.setattr(app_module.classifier, "classify", lambda q: pytest.fail("model called offline"))
    r = client.post("/api/chat", json={**BAYTEREK, "query": "а я бы хотел рисовать", "when": WHEN,
                                       "provider": "offline"}).json()
    # The word rules still know drawing: galleries, not restaurants.
    assert r["items"] and all(i["category"] != "food_drink" for i in r["items"])
    assert not any(c["label"] == "Понял запрос" for c in r["considered"])


def test_replan_keeps_the_read_intent(client, monkeypatch):
    monkeypatch.setattr(app_module.classifier, "classify", lambda q: ART)
    monkeypatch.setattr("backend.providers.configured", lambda provider: False)
    r = client.post("/api/chat", json={**BAYTEREK, "query": "Погулять 2 часа: хочу рисовать", "when": WHEN,
                                       "provider": "gemini", "mini_route": True}).json()
    s = r["mini_route"]["session"]
    assert s["intent"]["subcategories"] == ["gallery", "arts_centre"]
    first = r["mini_route"]["stops"][0]
    body = {
        "query": s["query"], "start_at": s["start_at"], "budget": s["budget"], "intent": s["intent"],
        "action": "closed", "stop_id": first["poi_id"], "elapsed": first["arrival_offset_min"],
        "position": {"latitude": first["latitude"], "longitude": first["longitude"]},
        "keep": [x["poi_id"] for x in r["mini_route"]["stops"]],
    }
    out = client.post("/api/replan", json=body).json()
    assert out["plan"]["stops"]
    assert all(x["category"] == "culture" for x in out["plan"]["stops"])
