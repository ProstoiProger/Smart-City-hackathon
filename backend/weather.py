"""Current modelled city weather from Open-Meteo; never reuse an old snapshot as live."""

from datetime import datetime, timezone
import threading
import time
import httpx

_cache = None
_expires = 0
_lock = threading.Lock()


def current_weather():
    global _cache, _expires
    with _lock:
        if _cache is not None and time.monotonic() < _expires:
            return _cache
        now = datetime.now(timezone.utc)
        try:
            response = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": 51.13,
                    "longitude": 71.43,
                    "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                    "wind_speed_unit": "kmh",
                    "timezone": "UTC",
                },
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            values = data["current"]
            observed = datetime.fromisoformat(values["time"]).replace(
                tzinfo=timezone.utc
            )
            stale = abs((now - observed).total_seconds()) > 7200
            _cache = {
                "available": not stale,
                "stale": stale,
                "source": "Open-Meteo",
                "source_url": "https://open-meteo.com/en/docs",
                "weather_kind": "current_model_estimate",
                "fetched_at": now.isoformat(),
                "valid_at": observed.isoformat(),
                "city": "Астана",
                "temperature_c": values.get("temperature_2m"),
                "feels_like_c": values.get("apparent_temperature"),
                "precipitation_mm": values.get("precipitation"),
                "wind_kmh": values.get("wind_speed_10m"),
                "weather_code": values.get("weather_code"),
                "note": "Оценка погодной модели для центра города; не измерение у выбранного входа.",
            }
            _expires = time.monotonic() + 300
        except Exception:
            _cache = {
                "available": False,
                "stale": False,
                "source": "Open-Meteo",
                "source_url": "https://open-meteo.com/en/docs",
                "fetched_at": now.isoformat(),
                "note": "Актуальную погоду получить не удалось. Старый снимок не используется.",
            }
            _expires = time.monotonic() + 30
        return _cache
