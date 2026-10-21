"""Request understanding for the chat: budget, time of day, "nearby", place mentions.

Plain RU/KK/EN text rules, no model: every decision is reported back to the user
("Учтено: …"), so it has to be explainable in one line.
"""

import re
from datetime import timedelta
from .hours import parse_when

FOLD = str.maketrans("әқғңұүөіһё", "акгнууоихе")


def fold(text):
    return str(text or "").casefold().translate(FOLD)


def tokens(text):
    """(folded word, start, end) for every word of the original text."""
    return [(fold(m.group()), m.start(), m.end()) for m in re.finditer(r"\w+", str(text or ""))]


# Filler words that carry no place meaning. Lexical search over character n-grams
# would otherwise match them against venue names ("хочу" → "Хочу хинкали").
# Category words (кафе, парк, прогулка, бар) stay: they are the query.
STOP_WORDS = {
    fold(w)
    for w in """
    я мы мне нам меня нас ты вы вам вас мой моя моё мое мои наш наша
    хочу хотим хочется хотелось хотел хотела хотели хотите бы
    где куда когда что чтобы то нибудь какой какая какое какие какую каком
    можно нужно надо есть ли сейчас сегодня тут здесь там уже ещё еще очень просто пожалуйста
    рядом недалеко поблизости неподалеку неподалёку близко около возле вокруг напротив
    от до из у в во на с со к ко по за для о об про и или а но же
    подскажи подскажите посоветуй посоветуйте посоветуете порекомендуй порекомендуйте
    найди найти ищу ищем покажи покажите место места месте местечко мест вариант варианты
    сходить пойти зайти попасть посетить провести время посмотреть глянуть увидеть турист туристы
    перед вылетом рейсом
    минут минуты минута мин час часа часов часик полчаса полтора пару пара последние
    пешком идти иду идём идем еду едем буду будем можете можешь
    здание здании здания вход входа нахожусь находимся стою стоим сижу сидим
    мен біз маған бізге менің біздің қайда қай не нені қандай барғым баруға барамын барайық
    болады бола ма ме ба бе ғой керек жақын жерде жанында маңында қасында осы мына сол
    үшін және немесе да де та те сағат жарты іздеймін айтыңыз ұсыныңыз
    i me my we us our you a an the to of in on at for with and or near nearby around close
    where what which some something anything can could would like want get go find looking
    look is are am be there here now today minutes minute min hours hour please recommend
    suggest place places spot see tourist
    """.split()
}


def content_query(text, skip=()):
    """The query without filler words, short numbers and the tokens in `skip` (indexes)."""
    words = [
        t
        for i, (t, _, _) in enumerate(tokens(text))
        if i not in skip and t not in STOP_WORDS and not (t.isdigit() and len(t) <= 3)
    ]
    return " ".join(words)


def without_tokens(text, idx):
    """The text with the words at token indexes `idx` cut out."""
    spans = [(s, e) for i, (_, s, e) in enumerate(tokens(text)) if i in set(idx)]
    out, pos = [], 0
    for s, e in spans:
        out.append(text[pos:s])
        pos = e
    out.append(text[pos:])
    return re.sub(r"\s+", " ", "".join(out)).strip()


def language(text):
    lowered = str(text or "").casefold()
    if re.search(r"[әіңғүұқөһ]", lowered):
        return "kk"
    if re.search(r"[a-z]", lowered) and not re.search(r"[а-яё]", lowered):
        return "en"
    return "ru"


# --- time budget -------------------------------------------------------------

UNIT = r"(мин\w*|minutes?|mins?\b|час\w*|сағат\w*|hours?|hrs?\b)"
WORD_HOURS = [
    (r"час[\s-]*полтора|часа?\s+полтора", 90, "«час-полтора»"),
    (r"полтора\s+час\w*|полтора\b|бір\s+жарым\s+сағат|an?\s+hour\s+and\s+a\s+half", 90, "«полтора часа»"),
    (r"пол\s*часа|полчас\w*|жарты\s+сағат|half\s+an?\s+hour|half\s+hour", 30, "«полчаса»"),
    (r"пар[уыа]\s+час\w*|два\s+часа|двух\s+часов|екі\s+сағат|couple\s+of\s+hours|two\s+hours", 120, "«пару часов»"),
    (r"три\s+часа|трёх\s+часов|трех\s+часов|үш\s+сағат|three\s+hours", 180, "«три часа»"),
    (r"(?:за|на|в\s+течение)\s+час\b|бір\s+сағат|an?\s+hour\b|one\s+hour", 60, "«час»"),
    (r"через\s+час\b|in\s+an?\s+hour\b", 60, "«через час»"),
]


def _minutes(value, unit):
    n = float(value.replace(",", "."))
    return n * 60 if re.match(r"час|сағат|hour|hr", unit, re.I) else n


def parse_budget(text, prefer_hours=False):
    """(minutes, note) from the text or (None, None). A range uses its upper bound:
    the walker allows that much time, and the plan may still finish earlier."""
    text = str(text or "")
    clamp = lambda m: max(10, min(240, int(round(m))))
    m = re.search(
        r"(?:от\s*)?(\d+(?:[.,]\d+)?)\s*(?:[-–—]|до)\s*(\d+(?:[.,]\d+)?)\s*" + UNIT, text, re.I
    )
    if m:
        return clamp(_minutes(m[2], m[3])), f"из текста «{m[0].strip()}», верхняя граница"
    hours = re.search(r"(\d(?:[.,]\d+)?)\s*(?:час\w*|сағат\w*|hours?|hrs?\b)", text, re.I)
    mins = re.search(r"(\d{1,3})\s*(?:мин\w*|minutes?|mins?\b)", text, re.I)
    if hours and (prefer_hours or not mins):
        return clamp(_minutes(hours[1], "час")), f"из текста «{hours[0].strip()}»"
    if mins and int(mins[1]) >= 10:
        return clamp(int(mins[1])), f"из текста «{mins[0].strip()}»"
    for pattern, minutes, label in WORD_HOURS:
        if re.search(pattern, text, re.I):
            return minutes, f"из текста {label}"
    return None, None


# --- time of day ---------------------------------------------------------------

PERIODS = [
    # name, pattern, start hour, end hour (exclusive; may pass midnight)
    ("ночью", r"\bноч\w*|поздн\w+\s+веч\w*|түнде|түнгі|\bnight\w*|tonight|late\s+evening", 22, 4),
    ("вечером", r"вечер\w*|кешке|кешкі|кеште|evening", 18, 24),
    ("утром", r"\bутр(?:ом|о|а)\b|таңертең|таңғы|morning", 7, 12),
    ("днём", r"\bдн[её]м\b|в\s+обед|обеденн\w*|түсте|түстен\s+кейін|afternoon", 12, 17),
]
PERIOD_NOUN = {"ночью": "ночь", "вечером": "вечер", "утром": "утро", "днём": "день"}
TOMORROW = re.compile(r"завтра|ертең|tomorrow", re.I)


def _inside(hour, start, end):
    return start <= hour < end if start < end else hour >= start or hour < end


def parse_time_of_day(text, now=None):
    """(ISO start, note) when the text names a time of day the walk should start in.

    "Вечером" in the evening keeps the current time (ISO is None); a later period today
    starts at its first hour; a period already over today moves to tomorrow.
    """
    now = now or parse_when()
    tomorrow = bool(TOMORROW.search(text or ""))
    for name, pattern, start, end in PERIODS:
        if not re.search(pattern, text or "", re.I):
            continue
        if not tomorrow and _inside(now.hour, start, end):
            return None, f"сейчас — {PERIOD_NOUN[name]}"
        day = now.date()
        if tomorrow or (start < end and now.hour >= end):
            day += timedelta(days=1)
        prefix = "завтра" if day != now.date() else "сегодня"
        return f"{day.isoformat()}T{start:02d}:00:00", f"{prefix} с {start:02d}:00 (из текста: {name})"
    if tomorrow:
        day = now.date() + timedelta(days=1)
        return f"{day.isoformat()}T10:00:00", "завтра с 10:00 (из текста «завтра»)"
    return None, None


# --- "nearby" -------------------------------------------------------------------

NEARBY = re.compile(
    r"рядом\s+со?\s+мной|недалеко(?:\s+от\s+меня)?|поблизости|неподал[её]ку|близко|в\s+шаговой|"
    r"рядом(?!\s+со?\s+\w)|near\s+me|nearby|close\s+by|жақын|маңайда|осы\s+жерде",
    re.I,
)
NEARBY_WALK_MIN = 15
NEARBY_RELAXED_MIN = 25


def wants_nearby(text):
    return bool(NEARBY.search(text or ""))


# --- several kinds of places in one request ---------------------------------------

COVER = [
    ("кафе", r"каф|коф|ресторан|поесть|покушать|кушать|поужина|пообеда|позавтрака|\bобед|\bужин|\bзавтрак|перекус|\bеда\b|\bеды\b|\bеду\s+(?:вкусн|попробова)|кухн|тамақ|асхана|cafe|coffee|restaurant|\bfood|\beat\b|cuisine|lunch|dinner|breakfast", "food_drink"),
    ("парк", r"парк|сквер|саябақ|\bpark", "nature"),
    ("музей", r"музе|выстав|галере|мұражай|көрме|museum|gallery|exhibit", "culture"),
    ("детям", r"детск\w*\s+площад|реб[её]н|\bдет(?:и|ей|ям|ьми)\b|балалар|баламен|\bkids?\b|children", "children"),
    ("достопримечательность", r"достопр|памятник|монумент|смотров|көрікті|sights?\b|landmark|monument", "sightseeing"),
]
JOIN = re.compile(r"\s(?:и|или|а\s+потом|потом|затем|плюс|және|немесе|сосын|and|or|then|plus)\s|,|\+", re.I)


def cover_groups(text):
    """[(label, category)] when the request names two or more kinds of places joined
    by "и/или/затем": "музей и кофе" must not become two cafés."""
    text = str(text or "")
    if re.search(r"детск.{0,8}(?:комнат|угол|меню)|балалар.{0,10}(?:бөлме|мәзір)", text, re.I):
        # "кафе с детской комнатой" is one kind of place with a feature.
        return []
    found = [(label, cat) for label, rx, cat in COVER if re.search(rx, text, re.I)]
    return found if len(found) >= 2 and JOIN.search(text) else []


# --- start point or destination ------------------------------------------------------

ORIGIN_BEFORE = {
    fold(w)
    for w in "возле около рядом недалеко неподалеку неподалёку напротив у от из близ вблизи "
    "near at around by from outside beside".split()
}
DESTINATION_BEFORE = {fold(w) for w in "в во на до к ко to into visit посетить".split()}
SELF = {
    fold(w)
    for w in "я мы сейчас нахожусь находимся стою стоим сижу сидим уже тут здесь "
    "i im i'm we am are мен біз".split()
}
ORIGIN_AFTER = re.compile(r"^(?:жаны|маңы|касы|жакын|тур(?:мын|мыз)|отыр)")
DESTINATION_AFTER = re.compile(r"^(?:бар(?:а|у|г|ы)|карай)")
KK_DATIVE = {"га", "ге", "ка", "ке", "на", "не"}


def mention_role(toks, first, last, suffix=""):
    """'origin' (я у/возле/от X, X жанындамын), 'destination' (сходить в X, X-ға барамын)
    or None when the text does not say."""
    after = [t for t, _, _ in toks[last + 1 : last + 3]]
    if after and ORIGIN_AFTER.match(after[0]):
        return "origin"
    if suffix in KK_DATIVE or (after and DESTINATION_AFTER.match(after[0])):
        return "destination"
    before = [t for t, _, _ in toks[max(0, first - 4) : first]]
    for i in range(len(before) - 1, max(-1, len(before) - 4), -1):
        word = before[i]
        if word in ORIGIN_BEFORE:
            return "origin"
        if word in DESTINATION_BEFORE:
            # "я в Хан Шатыре" is where I am; "сходить в Хан Шатыр" is where I go.
            return "origin" if any(w in SELF for w in before[:i]) else "destination"
    return None


# --- flight soon? ----------------------------------------------------------------------

# Words that mean "I have a flight to catch". "Аэропорт" alone is a place ("я в аэропорту,
# хочу поесть"), so only going *to* the airport counts.
FLIGHT = re.compile(
    # \b at the start: "рейс" must not match inside "корейскую".
    r"\bвылет\w*|\bрейс\w*|\bflights?\b|\bflying\b|\bұш(?:у|амын|атын|ар)\w*|"
    r"(?:ехать|еду|поехать|выезжать|успеть)\s+в\s+аэропорт\b|в\s+аэропорт\s+через|"
    r"әуежайға|to\s+the\s+airport",
    re.I,
)
NEGATION_BEFORE = {fold(w) for w in "нет не без никакого никакой ни no not without dont".split()}
NEGATION_AFTER = {fold(w) for w in "нет не жоқ емес".split()}


def wants_flight(text):
    """True when the request mentions a flight to catch, ignoring negated mentions:
    "у меня нет вылета", "не лечу", "рейса нет", "no flight", "рейс жоқ"."""
    text = str(text or "")
    toks = tokens(text)
    for m in FLIGHT.finditer(text):
        idx = [i for i, (_, s, e) in enumerate(toks) if s < m.end() and e > m.start()]
        if not idx:
            continue
        before = [t for t, _, _ in toks[max(0, idx[0] - 2) : idx[0]]]
        after = [t for t, _, _ in toks[idx[-1] + 1 : idx[-1] + 3]]
        if any(w in NEGATION_BEFORE for w in before) or any(w in NEGATION_AFTER for w in after):
            continue
        return True
    return False


# --- where and when the walk must end ------------------------------------------------

# "Через час нужно быть в MEGA", "к 18:00 успеть в Хан Шатыр", "MEGA-да болуым керек":
# the named place is the end of the walk, not a stop to visit.
FINISH_BEFORE = {
    fold(w)
    for w in "быть буду будем успеть успею успеем закончить закончу закончим финиш финишировать "
    "добраться доберусь доберемся оказаться встреча встречаемся ждут прийти приду придем "
    "be end finish reach meet meeting".split()
}
FINISH_AFTER = re.compile(r"^(?:бол(?:у|ам|амыз)|жет(?:у|ем|емиз))")
# Back to the start: a loop walk ends where it began.
LOOP = re.compile(
    r"вернуться\s+(?:к\s+началу|обратно|назад|сюда|туда\s+же|в\s+исходн\w*|на\s+старт|к\s+старту)|"
    r"обратно\s+к\s+(?:началу|старту)|с\s+возвратом|кругов\w*\s+маршрут|по\s+кругу|"
    r"бастапқы\s+нүктеге|кері\s+қайт\w*|қайта\s+орал\w*|"
    r"back\s+to\s+(?:the\s+)?start|round\s+trip|\bloop\b|return\s+to\s+(?:the\s+)?start",
    re.I,
)
DEADLINE = re.compile(
    r"(?:\bк|\bдо|\bby|\bat)\s+(\d{1,2})[:.](\d{2})\b|(?:\bк|\bдо)\s+(\d{1,2})\s+час\w*|"
    r"\b(\d{1,2})[:.](\d{2})\s*-?\s*(?:ге|ға|ке|қа)?\s*дейін",
    re.I,
)
RESERVE = re.compile(
    r"(?:запас\w*|резерв\w*)\s+(?:в\s+)?(\d{1,2})\s*мин|(\d{1,2})\s*мин\w*\s+(?:в\s+|на\s+)?(?:запас|резерв)|"
    r"(\d{1,2})\s*min\w*\s+(?:spare|buffer)|(?:buffer|spare)\s+of\s+(\d{1,2})\s*min",
    re.I,
)
NO_RESERVE = re.compile(r"без\s+запаса|без\s+резерва|no\s+buffer", re.I)
# Words about the deadline itself: they are not what to look for on the way.
FINISH_FILLER = FINISH_BEFORE | {
    fold(w)
    for w in "через нужно надо нужна необходимо потом затем после запас запасом резерв пути "
    "вернуться обратно назад началу старту исходную круговой кругу возвратом "
    "need have by then after way back start керек".split()
}


def finish_filler(text):
    """Token indexes of deadline words and numbers ("через 2 часа нужно быть")."""
    return [i for i, (t, _, _) in enumerate(tokens(text)) if t in FINISH_FILLER or t.isdigit()]


def finish_cue(toks, first, last):
    """True when the words around a mention say the walk must end there."""
    before = [t for t, _, _ in toks[max(0, first - 5) : first]]
    after = [t for t, _, _ in toks[last + 1 : last + 2]]
    return any(w in FINISH_BEFORE for w in before) or bool(after and FINISH_AFTER.match(after[0]))


def wants_loop(text):
    return bool(LOOP.search(str(text or "")))


def has_deadline(text):
    return bool(DEADLINE.search(str(text or "")))


def parse_deadline(text, start):
    """(minutes from `start` to the clock time in the text, note) or (None, None).

    "к 18:00" said at 19:00 means tomorrow is not meant: the result is 0 (already late).
    """
    m = DEADLINE.search(str(text or ""))
    if not m:
        return None, None
    hour = int(m[1] or m[3] or m[4])
    minute = int(m[2] or m[5] or 0)
    if hour > 23 or minute > 59:
        return None, None
    at = start.replace(hour=hour, minute=minute, second=0, microsecond=0)
    minutes = (at - start).total_seconds() / 60
    if minutes < -12 * 60:
        minutes += 24 * 60  # "к 01:00" said late in the evening
    return max(0, int(minutes)), f"к {hour:02d}:{minute:02d} (из текста)"


def parse_reserve(text):
    """Minutes to keep spare at the finish, if the text says so; 0 for "без запаса"."""
    text = str(text or "")
    if NO_RESERVE.search(text):
        return 0
    m = RESERVE.search(text)
    return int(next(g for g in m.groups() if g)) if m else None
