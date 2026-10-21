import httpx
import pytest
from fastapi.testclient import TestClient
from backend import tts
from backend.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_cache():
    tts._cache.clear()
    yield
    tts._cache.clear()


def fake_elevenlabs(calls, status=200, content_type="audio/mpeg"):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(
                status,
                content=b"ID3fake-mp3" if status == 200 else b'{"detail":"secret body"}',
                headers={"content-type": content_type},
                request=httpx.Request("POST", url),
            )

    return Client


def test_without_key_the_client_falls_back_to_the_browser_voice(client, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    r = client.post("/api/tts", json={"text": "Привет", "lang": "ru"})
    assert r.status_code == 503 and "ELEVENLABS_API_KEY" in r.json()["detail"]
    assert client.get("/api/meta").json()["tts"] == {"provider": None}


def test_russian_and_kazakh_use_models_that_support_them(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-eleven-key")
    calls = []
    monkeypatch.setattr(tts.httpx, "Client", fake_elevenlabs(calls))
    ru = client.post("/api/tts", json={"text": "**Бәйтерек** — 5 мин пешком", "lang": "ru"})
    kk = client.post("/api/tts", json={"text": "Бәйтерекке жаяу 5 мин", "lang": "kk"})
    assert ru.status_code == kk.status_code == 200
    assert ru.headers["content-type"] == "audio/mpeg" and ru.content == b"ID3fake-mp3"
    (url_ru, sent_ru), (_, sent_kk) = calls
    assert url_ru.startswith("https://api.elevenlabs.io/v1/text-to-speech/")
    assert sent_ru["headers"]["xi-api-key"] == "test-eleven-key"
    assert sent_ru["json"] == {"text": "Бәйтерек — 5 мин пешком", "model_id": "eleven_v3", "language_code": "ru"}
    assert sent_kk["json"]["model_id"] == "eleven_v3" and sent_kk["json"]["language_code"] == "kk"
    assert client.get("/api/meta").json()["tts"] == {"provider": "elevenlabs"}


def test_repeated_phrase_is_cached(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-eleven-key")
    calls = []
    monkeypatch.setattr(tts.httpx, "Client", fake_elevenlabs(calls))
    for _ in range(3):
        assert client.post("/api/tts", json={"text": "Остановка 1", "lang": "ru"}).status_code == 200
    assert len(calls) == 1


def test_provider_errors_do_not_leak_the_key_or_body(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-eleven-key")
    for status, word in ((401, "ключ"), (429, "лимит"), (500, "HTTP 500")):
        monkeypatch.setattr(tts.httpx, "Client", fake_elevenlabs([], status=status, content_type="application/json"))
        r = client.post("/api/tts", json={"text": f"текст {status}", "lang": "ru"})
        assert r.status_code == 503 and word in r.json()["detail"]
        assert "test-eleven-key" not in r.text and "secret body" not in r.text


def test_long_text_is_cut_at_a_sentence():
    text = ("Первое предложение про парк. " * 200).strip()
    cut = tts.clean(text)
    assert len(cut) <= tts.MAX_CHARS and cut.endswith(".")


def test_russian_and_kazakh_use_their_own_voices(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-eleven-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_RU", "ruVoice123")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_KK", "kkVoice456")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    calls = []
    monkeypatch.setattr(tts.httpx, "Client", fake_elevenlabs(calls))
    client.post("/api/tts", json={"text": "Сәлем", "lang": "kk"})
    client.post("/api/tts", json={"text": "Привет", "lang": "ru"})
    assert calls[0][0].endswith("/kkVoice456") and calls[1][0].endswith("/ruVoice123")
    # A language without its own voice uses the shared one, then the premade default.
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_KK")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "sharedVoice")
    assert tts.voice_for("kk") == "sharedVoice" and tts.voice_for("ru") == "ruVoice123"
    monkeypatch.delenv("ELEVENLABS_VOICE_ID")
    assert tts.voice_for("kk") == tts.DEFAULT_VOICE
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_KK", "../bad")
    r = client.post("/api/tts", json={"text": "Сәлем қайта", "lang": "kk"})
    assert r.status_code == 503
