"""Server-side speech synthesis with ElevenLabs.

The browser asks /api/tts and gets audio; the API key never leaves the server.
All languages use Eleven v3 (the only model with Kazakh, and the most natural Russian).
Repeated phrases (tour stops, the same answer) come from a small in-memory cache.
Without a key, or on any error, the client falls back to the browser's own voice.
"""

import hashlib
import re
import threading
from collections import OrderedDict
import httpx
from .settings import setting

API = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # premade multilingual voice; see voice_for()
DEFAULT_MODEL = {"ru": "eleven_v3", "kk": "eleven_v3", "en": "eleven_v3"}
OUTPUT_FORMAT = "mp3_44100_128"
MAX_CHARS = 2500  # well inside every model's per-request limit; longer text is cut at a sentence
CACHE_SIZE = 64

_cache: "OrderedDict[str, bytes]" = OrderedDict()
_lock = threading.Lock()


class TTSError(RuntimeError):
    """Safe message only: never includes the key or the provider response body."""


def configured():
    return bool(setting("ELEVENLABS_API_KEY"))


def clean(text):
    text = re.sub(r"[*_#`>]+", "", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > MAX_CHARS // 2 else cut


def model_for(lang):
    lang = lang if lang in DEFAULT_MODEL else "ru"
    return setting(f"ELEVENLABS_MODEL_{lang.upper()}", DEFAULT_MODEL[lang])


def voice_for(lang):
    """Separate voices per language (ELEVENLABS_VOICE_ID_RU / _KK / _EN); the shared
    ELEVENLABS_VOICE_ID, then the premade default, fill in what is not set."""
    lang = lang if lang in DEFAULT_MODEL else "ru"
    return (
        setting(f"ELEVENLABS_VOICE_ID_{lang.upper()}")
        or setting("ELEVENLABS_VOICE_ID")
        or DEFAULT_VOICE
    )


def synthesize(text, lang="ru", timeout=None):
    """MP3 bytes for the text, or TTSError."""
    key = setting("ELEVENLABS_API_KEY")
    if not key:
        raise TTSError("ELEVENLABS_API_KEY не задан")
    text = clean(text)
    if not text:
        raise TTSError("Пустой текст")
    voice = voice_for(lang)
    if not re.fullmatch(r"[A-Za-z0-9]+", voice):
        raise TTSError(f"Недопустимый голос ElevenLabs для языка {lang}")
    model = model_for(lang)
    cache_key = hashlib.sha256(f"{voice}|{model}|{lang}|{text}".encode()).hexdigest()
    with _lock:
        if cache_key in _cache:
            _cache.move_to_end(cache_key)
            return _cache[cache_key]
    body = {"text": text, "model_id": model}
    if lang in ("ru", "kk", "en"):
        # Enforces the language for models that accept it; ignored by those that do not.
        body["language_code"] = lang
    try:
        with httpx.Client(timeout=timeout or float(setting("TTS_TIMEOUT_SECONDS", "30"))) as client:
            response = client.post(
                API.format(voice=voice),
                params={"output_format": OUTPUT_FORMAT},
                headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                json=body,
            )
    except httpx.HTTPError:
        raise TTSError("Сетевая ошибка при обращении к ElevenLabs") from None
    if response.status_code == 401:
        raise TTSError("ElevenLabs: неверный ключ (HTTP 401)")
    if response.status_code == 429:
        raise TTSError("ElevenLabs: превышен лимит (HTTP 429)")
    if response.status_code != 200 or not response.headers.get("content-type", "").startswith("audio/"):
        raise TTSError(f"ElevenLabs: HTTP {response.status_code}")
    audio = response.content
    with _lock:
        _cache[cache_key] = audio
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return audio
