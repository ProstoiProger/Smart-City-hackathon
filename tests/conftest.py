import pytest
from backend import intent


@pytest.fixture(autouse=True)
def no_live_intent_model(monkeypatch):
    """Tests never ask the real Gemini to read a request: a developer's .env may set
    LLM_PROVIDER=gemini with a key. Tests of the reader substitute the model's answer."""

    def offline(*args, **kwargs):
        raise intent.ProviderError("intent model disabled in tests")

    monkeypatch.setattr(intent, "gemini_json", offline)
