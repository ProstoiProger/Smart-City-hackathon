"""Conservative schedule checks in Astana time; unsupported schedules stay unknown."""

from datetime import datetime, timedelta, timezone
import re

ASTANA = timezone(timedelta(hours=5))
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def parse_when(value=None):
    if value is None:
        return datetime.now(ASTANA)
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=ASTANA) if dt.tzinfo is None else dt.astimezone(ASTANA)


def closure(p):
    s = str(p.get("operational_status") or "").lower()
    return any(
        w in s for w in ("closed", "opening_soon", "removed_from_provider")
    ) or bool(p.get("_provider_closure"))


def _minute(s):
    h, m = map(int, s.split(":"))
    if not 0 <= h <= 24 or not 0 <= m < 60 or (h == 24 and m):
        raise ValueError("time")
    return h * 60 + m


def hours_status(p, when=None, stay=0):
    if closure(p):
        return {
            "status": "closed_reported",
            "label": "Источник сообщает о закрытии / скором открытии",
        }
    dt = (
        parse_when(when)
        if isinstance(when, (str, type(None)))
        else when.astimezone(ASTANA)
    )
    schedule = p.get("opening_hours_by_day")
    if not schedule and p.get("opening_hours") == "24/7":
        schedule = {d: [["00:00", "24:00"]] for d in DAYS}
    if not isinstance(schedule, dict):
        return {"status": "unknown", "label": "Часы работы не подтверждены"}
    intervals = []
    try:
        for offset in (-1, 0):
            day = dt.date() + timedelta(days=offset)
            for a, b in schedule.get(DAYS[day.weekday()], []):
                start, end = _minute(a), _minute(b)
                if end <= start:
                    end += 1440
                base = datetime.combine(day, datetime.min.time(), tzinfo=ASTANA)
                intervals.append(
                    (base + timedelta(minutes=start), base + timedelta(minutes=end))
                )
        end = dt + timedelta(minutes=stay)
        if any(a <= dt < b and end <= b for a, b in intervals):
            return {
                "status": "open_by_schedule",
                "label": "По опубликованному расписанию; праздничные изменения не проверены",
            }
        return {
            "status": "closed_by_schedule",
            "label": "Не подходит по опубликованному расписанию",
        }
    except (ValueError, TypeError, KeyError):
        return {"status": "unknown", "label": "Формат расписания требует уточнения"}
