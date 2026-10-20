"""Conservative entity resolution, typed taxonomy and source-backed RAG attributes.

Source records remain in source_pois.jsonl. Candidate pairs are not automatically
treated as identical branches. Every merge is logged and reversible by source ids.
"""

import collections
import copy
import json
import math
import re
from pathlib import Path
import unicodedata

TAXONOMY = {
    "cafe": ("cafe", "Кафе", ["кафе"]),
    "coffee_shop": ("coffee_shop", "Кофейня", ["кофейни", "точки кофе"]),
    "restaurant": ("restaurant", "Ресторан", ["рестораны"]),
    "fast_food": ("fast_food", "Быстрое питание", ["быстрое питание"]),
    "museum": ("museum", "Музей", ["музеи", "interactive_museum"]),
    "park": ("park", "Парк", ["парки"]),
    "garden": ("garden", "Сад", ["сады"]),
    "mall": (
        "mall",
        "Торговый центр",
        ["торговые центры", "торгово-развлекательные центры"],
    ),
    "bar": ("bar", "Бар", ["бары"]),
    "pub": ("pub", "Паб", ["пабы"]),
    "playground": ("playground", "Детская площадка", ["детские площадки"]),
    "pitch": ("sports_pitch", "Спортплощадка", []),
    "hotel": ("hotel", "Отель", ["гостиницы"]),
    "library": ("library", "Библиотека", ["библиотеки"]),
    "coworking": ("coworking", "Коворкинг", ["коворкинг"]),
    "artwork": ("artwork", "Арт-объект", []),
    "aquarium": ("aquarium", "Океанариум", ["океанариумы"]),
    "information": ("tourist_information", "Туристическая информация", []),
    "mosque": ("mosque", "Мечеть", ["мечети"]),
    "airport": ("airport", "Аэропорт", []),
}

EXTRA = {
    "bakery": ("Пекарня", ["Пекарни"]),
    "confectionery": ("Кондитерская", ["Кондитерские изделия"]),
    "cafe_confectionery": ("Кафе-кондитерская", ["Кафе-кондитерские"]),
    "canteen": ("Столовая", ["Столовые"]),
    "cooking_shop": ("Кулинария", ["Кулинарии"]),
    "pizzeria": ("Пиццерия", ["Пиццерии"]),
    "sushi": ("Суши-бар", ["Суши-бары"]),
    "cinema": ("Кинотеатр", ["Кинотеатры"]),
    "theatre": ("Театр", ["Театры"]),
    "gallery": ("Художественная галерея", ["Художественные выставки"]),
    "swimming_pool": ("Бассейн", ["Бассейны"]),
    "fitness_centre": ("Фитнес-клуб", ["Фитнес-клубы", "Тренажёрные залы"]),
    "stadium": ("Стадион", ["Стадионы"]),
    "nightclub": ("Ночной клуб", ["Ночные клубы"]),
    "indoor_play": ("Детский игровой зал", ["Детские игровые залы"]),
    "amusement_arcade": ("Игровые автоматы", ["Детские развлекательные автоматы"]),
    "bowling_alley": ("Боулинг", ["Боулинг"]),
    "billiards": ("Бильярд", ["Бильярдные залы"]),
    "karaoke": ("Караоке", ["Караоке-залы"]),
    "virtual_reality": ("Виртуальная реальность", ["Центры виртуальной реальности"]),
    "sauna": ("Баня и сауна", ["Бани и сауны", "public_bath"]),
    "greenhouse": ("Оранжерея", ["Оранжерея"]),
    "parking": ("Паркинг", ["Паркинги"]),
    "viewpoint": ("Смотровая площадка", ["Смотровые площадки"]),
    "concert_hall": ("Концертный зал", ["Концертные залы"]),
    "circus": ("Цирк", ["Цирк"]),
    "amusement_ride": ("Аттракционы", ["Аттракционы"]),
    "spa": ("SPA", ["SPA-процедуры"]),
    "trampoline": ("Батутный центр", ["Батутные центры"]),
    "toilets": ("Туалет", ["Туалеты"]),
    "coffee_vending": ("Кофейный автомат", ["Кофейные автоматы"]),
    "monument": ("Памятник", ["monuments"]),
    "attraction": ("Достопримечательность", ["sights"]),
}
for code, (label, values) in EXTRA.items():
    TAXONOMY[code] = (code, label, values)
TAXONOMY["coffee_shop"][2].append("coffee")
TAXONOMY["aquarium"][2].append("Океанариум")
for code, label in {
    "community_centre": "Общественный центр",
    "place_of_worship": "Религиозный объект",
    "sports_centre": "Спортивный центр",
    "apartment": "Апартаменты",
    "hostel": "Хостел",
    "ice_rink": "Каток",
    "fitness_station": "Площадка для тренировок",
    "sports_hall": "Спортивный зал",
    "picnic_site": "Место для пикника",
    "ice_cream": "Мороженое",
    "memorial": "Мемориал",
    "escape_game": "Квест",
    "guest_house": "Гостевой дом",
    "yes": "Неуточнённый объект",
    "track": "Спортивная дорожка",
    "dance": "Танцы",
    "food_court": "Фудкорт",
    "arts_centre": "Центр искусств",
    "motel": "Мотель",
    "bandstand": "Эстрада",
    "theme_park": "Парк развлечений",
    "beach_resort": "Пляжный комплекс",
    "chalet": "Гостевой домик",
    "childcare": "Присмотр за детьми",
    "resort": "Курортный комплекс",
    "bench": "Скамейка",
    "common": "Общая зелёная территория",
    "water_park": "Аквапарк",
    "archaeological_site": "Археологический объект",
    "golf_course": "Поле для гольфа",
    "caravan_site": "Стоянка для автодомов",
    "castle": "Историческое здание",
    "boundary_stone": "Межевой знак",
    "bleachers": "Трибуны",
    "dog_park": "Площадка для собак",
    "spirituality": "Духовное наследие",
    "leisure": "Досуг",
    "locations": "Городской объект",
    "jungle_exhibition": "Экспозиция джунглей",
}.items():
    TAXONOMY.setdefault(code, (code, label, []))


def clean(s):
    s = unicodedata.normalize("NFKC", str(s or "")).casefold().replace("ё", "е")
    return re.sub(r"[^\w]+", " ", s).strip()


def name(p):
    s = p.get("name") or p.get("name_ru") or p.get("display_name") or ""
    return clean(s.split(",")[0])


def dist(a, b):
    la, lo, lb, ln = map(
        math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"])
    )
    h = (
        math.sin((lb - la) / 2) ** 2
        + math.cos(la) * math.cos(lb) * math.sin((ln - lo) / 2) ** 2
    )
    return 12742000 * math.asin(min(1, math.sqrt(h)))


def dgis_ids(p):
    ids = set()
    if p["poi_id"].startswith("dgis:"):
        ids.add(p["poi_id"].split(":", 1)[1])
    for k, v in (p.get("external_ids") or {}).items():
        if "2gis" in k or "dgis" in k:
            ids.add(str(v))
    return ids


def named(p):
    if p.get("raw_osm_tags"):
        return any(
            p["raw_osm_tags"].get(k)
            for k in ["name", "name:ru", "name:kk", "name:en", "official_name"]
        )
    return bool(
        p.get("name_ru") or p.get("name") or p.get("display_name")
    ) and not re.search(r"\((?:node|way|relation)/\d+\)", p.get("display_name", ""))


def address_key(p):
    s = clean(p.get("address")).translate(str.maketrans("қғңұүәөі", "кгнууаои"))
    numbers = re.findall(r"\b\d+[a-zа-я]?(?:/\d+)?\b", s)
    stop = {
        "астана",
        "г",
        "улица",
        "ул",
        "проспект",
        "пр",
        "даңғылы",
        "дангылы",
        "көшесі",
        "кошеси",
        "шоссе",
        "көш",
        "район",
    }
    tokens = {
        t
        for t in s.split()
        if not any(x.isdigit() for x in t) and t not in stop and len(t) > 2
    }
    return numbers[-1] if numbers else None, tokens


def same_address(a, b):
    x, xt = address_key(a)
    y, yt = address_key(b)
    return (
        x is not None
        and x == y
        and bool(xt & yt)
        and len(xt & yt) / max(1, min(len(xt), len(yt))) >= 0.6
    )


def normalize(root, source):
    out = root / "data"
    # The prepared input includes provider closure flags; retain every original record.
    prepared = out / "pois.jsonl"
    records = [json.loads(l) for l in prepared.open(encoding="utf-8")]
    (out / "source_pois.jsonl").write_text(
        prepared.read_text(encoding="utf-8"), encoding="utf-8"
    )
    provider = {}
    for line in (source / "dgis_records.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        provider[str(row["dgis_id"])] = row
    taxonomy = {}
    attr_count = 0
    for p in records:
        p["source_record_ids"] = [p["poi_id"]]
        p["name_is_source_backed"] = bool(named(p))
        raw = p.get("subcategory") or "unknown"
        key = clean(raw)
        match = next(
            (
                value
                for original, value in TAXONOMY.items()
                if key
                in [clean(original), clean(value[0]), *[clean(x) for x in value[2]]]
            ),
            None,
        )
        if match:
            code, label, _ = match
        else:
            # Stable canonical code even for less frequent rubrics, with explicit label.
            import hashlib

            code = (
                raw
                if re.fullmatch(r"[a-z][a-z_]+", raw)
                else "rubric_" + hashlib.sha1(key.encode()).hexdigest()[:10]
            )
            label = raw
        p["subcategory_raw"] = raw
        p["subcategory"] = code
        p["subcategory_label"] = label
        taxonomy[raw] = {"code": code, "label": label}
        attrs = []
        for pid in dgis_ids(p):
            row = provider.get(pid)
            if not row:
                continue
            for group in row["data"].get("attribute_groups", []):
                for a in group.get("attributes", []):
                    if a.get("name"):
                        attrs.append(
                            {
                                "name": a["name"],
                                "tag": a.get("tag"),
                                "group": group.get("name"),
                                "source_url": row["source_url"],
                                "collected_at": row.get("collected_at"),
                            }
                        )
        p["provider_attributes"] = attrs
        attr_count += bool(attrs)
        semantic = [
            a["name"]
            for a in attrs
            if not str(a.get("tag") or "").startswith("general_payment_type")
        ]
        tags = p.get("raw_osm_tags") or {}
        if tags.get("cuisine"):
            semantic.append(
                "Кухня: " + tags["cuisine"].replace(";", ", ").replace("_", " ")
            )
        p["semantic_attributes"] = list(dict.fromkeys(semantic))
        p["aliases"] = list(
            dict.fromkeys(
                [
                    v
                    for v in [
                        p.get("name"),
                        p.get("name_ru"),
                        p.get("name_kk"),
                        p.get("name_en"),
                        p.get("display_name"),
                    ]
                    if v
                ]
            )
        )
    n = len(records)
    parent = list(range(n))
    members = {i: [i] for i in range(n)}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    merges = []
    ambiguous = []

    def join(i, j, reason):
        a, b = find(i), find(j)
        if a == b:
            return
        # Prevent transitive chain merges between separate catalog branches.
        ia = set().union(*(dgis_ids(records[x]) for x in members[a]))
        ib = set().union(*(dgis_ids(records[x]) for x in members[b]))
        if ia and ib and not ia & ib:
            return
        parent[b] = a
        members[a] += members.pop(b)
        merges.append(
            {
                "left": records[i]["poi_id"],
                "right": records[j]["poi_id"],
                "reason": reason,
                "distance_m": round(dist(records[i], records[j]), 1),
            }
        )

    linked = collections.defaultdict(list)
    groups = collections.defaultdict(list)
    for i, p in enumerate(records):
        for pid in dgis_ids(p):
            linked[pid].append(i)
        if p["name_is_source_backed"]:
            groups[name(p)].append(i)
    for inds in linked.values():
        for i in inds[1:]:
            join(inds[0], i, "shared_provider_id")
    for key, inds in groups.items():
        for ix, i in enumerate(inds):
            for j in inds[ix + 1 :]:
                a, b = records[i], records[j]
                d = dist(a, b)
                if d > 250:
                    continue
                if a.get("category") != b.get("category"):
                    continue
                if d <= 40 or (d <= 200 and same_address(a, b)):
                    before = find(i) != find(j)
                    join(
                        i,
                        j,
                        (
                            "same_name_close_coordinates"
                            if d <= 40
                            else "same_name_and_address"
                        ),
                    )
                    if before and find(i) != find(j):
                        ambiguous.append(
                            {
                                "left": a["poi_id"],
                                "right": b["poi_id"],
                                "distance_m": round(d, 1),
                                "reason": "distinct_provider_branches",
                            }
                        )
                elif d <= 150:
                    ambiguous.append(
                        {
                            "left": a["poi_id"],
                            "right": b["poi_id"],
                            "distance_m": round(d, 1),
                            "reason": "name_and_proximity_without_address_confirmation",
                        }
                    )
    canonical = []
    aliases = {}
    conflicts = []
    excluded_merge_fields = {
        "poi_id",
        "sources",
        "source_record_ids",
        "provider_attributes",
        "semantic_attributes",
        "aliases",
        "external_ids",
        "latitude",
        "longitude",
        "raw_osm_tags",
        "rating",
        "ratings_count",
    }
    for inds in members.values():
        cluster = sorted(
            (records[i] for i in inds),
            key=lambda p: (
                p.get("description_type") == "source_text",
                len(p.get("sources") or []),
            ),
            reverse=True,
        )
        p = copy.deepcopy(cluster[0])
        cid = p["poi_id"]
        p["source_record_ids"] = [x["poi_id"] for x in cluster]
        for row in cluster:
            aliases[row["poi_id"]] = cid
        p["aliases"] = list(dict.fromkeys(v for row in cluster for v in row["aliases"]))
        p["semantic_attributes"] = list(
            dict.fromkeys(v for row in cluster for v in row["semantic_attributes"])
        )
        p["provider_attributes"] = [
            a for row in cluster for a in row["provider_attributes"]
        ]
        p["sources"] = list(
            {
                s.get("url", str(s)): s
                for row in cluster
                for s in row.get("sources") or []
            }.values()
        )
        p["external_ids"] = {
            k: v
            for row in cluster[::-1]
            for k, v in (row.get("external_ids") or {}).items()
        }
        for row in cluster[1:]:
            for k, v in row.items():
                if k in excluded_merge_fields or v is None:
                    continue
                if p.get(k) is None:
                    p[k] = v
                elif isinstance(v, bool) and isinstance(p[k], bool) and p[k] != v:
                    conflicts.append(
                        {
                            "poi_id": cid,
                            "field": k,
                            "claims": [
                                {"source_id": cluster[0]["poi_id"], "value": p[k]},
                                {"source_id": row["poi_id"], "value": v},
                            ],
                            "resolution": "unknown",
                        }
                    )
                    p[k] = None
        ratings = [
            x
            for x in cluster
            if isinstance(x.get("rating"), (int, float))
            and 0 < x["rating"] <= 5
            and (x.get("ratings_count") or 0) > 0
        ]
        if ratings:
            best = max(ratings, key=lambda x: x["ratings_count"])
            p["rating"] = best["rating"]
            p["ratings_count"] = best["ratings_count"]
            p["rating_source"] = best.get("rating_source")
            p["rating_source_record_id"] = best["poi_id"]
        closures = [
            r["_provider_closure"] for r in cluster if r.get("_provider_closure")
        ]
        if closures:
            p["_provider_closure"] = closures[0]
        p["name_is_source_backed"] = any(x["name_is_source_backed"] for x in cluster)
        canonical.append(p)
    # Current official information is separate from the closed historical museum.
    closed = json.loads(
        (source / "closed_place_notices.json").read_text(encoding="utf-8")
    )
    (out / "closed_place_notices.json").write_text(
        json.dumps(closed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for p in canonical:
        if p["poi_id"] == "osm:way:240921034":
            p["aliases"] += ["Океанариум Ailand", "Океанариум Думан", "Duman", "Думан"]
            p["semantic_attributes"] += [
                "Океанариум в центре Ailand; часы и цены отдельных аттракционов отличаются"
            ]
        if p["poi_id"] == "official:alem_ai_museum":
            p["aliases"] += ["Музей Сингулярности", "alem ai"]
        if p["poi_id"] == "osm:way:240860325":
            p["aliases"] += [
                "Хазрет Султан",
                "Хазрет Сұлтан",
                "Hazret Sultan",
                "Әзірет Сұлтан",
            ]
            p["name_ru"] = "Мечеть Хазрет Султан"
            p["subcategory"] = "mosque"
            p["subcategory_label"] = "Мечеть"
            p["sources"].append(
                {
                    "name": "Kazakhstan.travel",
                    "url": "https://kazakhstan.travel/ru/attractions/441",
                    "collected_at": "2026-10-19",
                }
            )
    ocean_parent = next(
        p for p in canonical if "osm:way:240921034" in p["source_record_ids"]
    )
    canonical.append(
        {
            "poi_id": "official:ailand_oceanarium",
            "display_name": "Океанариум Ailand (Думан)",
            "name_ru": "Океанариум Ailand",
            "latitude": ocean_parent["latitude"],
            "longitude": ocean_parent["longitude"],
            "address": ocean_parent.get("address"),
            "category": "entertainment",
            "subcategory": "aquarium",
            "subcategory_label": "Океанариум",
            "name_is_source_backed": True,
            "aliases": [
                "Duman oceanarium",
                "Океанариум Думан",
                "Ailand oceanarium",
                "Думан",
            ],
            "short_description": "Океанариум в составе центра Ailand: аквариумы с морскими обитателями и подводный тоннель. Расписание относится к океанариуму, а не ко всем аттракционам центра.",
            "description_type": "source_summary",
            "parent_poi_id": ocean_parent["poi_id"],
            "coordinate_method": "parent_venue_coordinate_not_verified_subvenue_entrance",
            "opening_hours": "Mo-Su 10:00-21:00",
            "opening_hours_by_day": {
                d: [["10:00", "21:00"]]
                for d in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
            },
            "ticket_sales_end": "20:30",
            "suggested_visit_duration_min": 60,
            "website": "https://ailand.kz/ru/attractions/ocean-ru/",
            "source_record_ids": [],
            "sources": [
                {
                    "name": "Ailand: океанариум",
                    "url": "https://ailand.kz/ru/attractions/ocean-ru/",
                    "collected_at": "2026-10-19",
                },
                {
                    "name": "Ailand: график",
                    "url": "https://ailand.kz/ru/schedule-ru/",
                    "collected_at": "2026-10-19",
                },
                {
                    "name": "Visit Astana",
                    "url": "https://visitastana.kz/ru/about-city/what-to-see/okeanarium-ailand/",
                    "collected_at": "2026-10-19",
                },
            ],
        }
    )
    # Airport exists as a context anchor, not a leisure recommendation or verified entrance.
    canonical.append(
        {
            "poi_id": "official:astana_airport",
            "display_name": "Международный аэропорт Нурсултан Назарбаев",
            "name_ru": "Международный аэропорт Нурсултан Назарбаев",
            "latitude": 51.0276,
            "longitude": 71.4668,
            "address": "Астана, проспект Кабанбай батыра, 119",
            "category": "infrastructure",
            "subcategory": "airport",
            "subcategory_label": "Аэропорт",
            "name_is_source_backed": True,
            "recommendation_eligible": False,
            "aliases": ["Аэропорт Астаны", "NQZ", "Astana airport"],
            "short_description": "Аэропорт Астаны. Используется как контекстная точка для поездки перед вылетом. Время регистрации и трансфера рассчитывается отдельно.",
            "description_type": "source_summary",
            "coordinate_method": "existing_public_anchor_approximate_not_verified_entrance",
            "sources": [
                {
                    "name": "Официальный сайт аэропорта",
                    "url": "https://www.nn-airport.kz/index.php?category=contacts",
                    "collected_at": "2026-10-19",
                }
            ],
            "source_record_ids": [],
        }
    )
    taxonomy["airport"] = {"code": "airport", "label": "Аэропорт"}
    counts = collections.Counter()
    for p in canonical:
        p["recommendation_eligible"] = p.get(
            "recommendation_eligible",
            p["name_is_source_backed"] and p.get("category") != "infrastructure",
        )
        n = p.get("ratings_count") or 0
        r = p.get("rating")
        p["rating_bayesian"] = (
            round((n * r + 245 * 4.5) / (n + 245), 4)
            if n and isinstance(r, (int, float)) and 0 < r <= 5
            else None
        )
        counts["named"] += p["name_is_source_backed"]
        counts["recommendation_eligible"] += p["recommendation_eligible"]

    def write(name, rows):
        with (out / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    from targeted_claims import build

    build(root, source)
    from refine_corpus import refine

    refinement = refine(
        root, canonical, records, aliases, ambiguous, name, dist, same_address
    )
    counts["recommendation_eligible"] = sum(
        p.get("recommendation_eligible", False) for p in canonical
    )
    write("pois.jsonl", canonical)
    write("dedup_merge_log.jsonl", merges)
    write("dedup_candidates.jsonl", ambiguous)
    write("merge_conflicts.jsonl", conflicts)
    for filename, obj in [("poi_aliases.json", aliases), ("taxonomy.json", taxonomy)]:
        (out / filename).write_text(
            json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for f in ["events.jsonl"]:
        (out / f).write_text((source / f).read_text(encoding="utf-8"), encoding="utf-8")
    for f in [
        "venue_conditions.jsonl",
        "published_price_items.jsonl",
        "published_visit_rules.jsonl",
        "venue_policy_sources.jsonl",
        "all_venue_enrichment_summary.json",
    ]:
        if (source / f).exists():
            (out / f).write_text(
                (source / f).read_text(encoding="utf-8"), encoding="utf-8"
            )
    report = {
        "input_pois": len(records),
        "canonical_pois": len(canonical),
        "added_context_and_subvenue_pois": 2,
        "merged_records": len(records) + 2 - len(canonical),
        "merge_operations": len(merges),
        "ambiguous_pairs_not_merged": len(ambiguous),
        "source_records_with_2gis_attributes": attr_count,
        "canonical_source_backed_names": counts["named"],
        "recommendation_eligible": counts["recommendation_eligible"],
        "events": sum(
            1 for l in (out / "events.jsonl").open(encoding="utf-8") if l.strip()
        ),
        "taxonomy_raw_values": len(taxonomy),
        "taxonomy_codes": len({v["code"] for v in taxonomy.values()}),
        "rating_prior": {"mean": 4.5, "pseudo_count": 245},
        "refinement": refinement,
        "limitations": [
            "Proximity is not definitive identity; unresolved pairs remain separate.",
            "The two President Park OSM centres are over 1km apart; not auto-merged by name.",
            "Attributes are source claims, not independent verification.",
            "The historical Nur Alem museum is closed; no historic opening hours are applied to alem.ai.",
        ],
    }
    (out / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["pois"] = len(canonical)
    manifest["source_pois"] = len(records)
    manifest["quality_report"] = "quality_report.json"
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
