"""Rich factual contexts, recommendation diversity and explicit evidence backlog.

Descriptions generated here are deterministic summaries of existing facts, not
independent publisher prose. Nearby same-brand groups never merge their facts.
"""

import collections
import hashlib
import json
import re


def write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def refine(root, canonical, records, aliases, candidates, name_fn, dist_fn, address_fn):
    out = root / "data"
    byid = {p["poi_id"]: p for p in canonical}
    raw = {p["poi_id"]: p for p in records}
    counts = collections.Counter()
    backlog = []
    ticket_claims = (
        json.loads((out / "targeted_primary_claims.json").read_text(encoding="utf-8"))
        if (out / "targeted_primary_claims.json").exists()
        else []
    )
    for p in canonical:
        osm = p.get("raw_osm_tags") or {}
        translated = {
            "surface": {
                "asphalt": "асфальт",
                "grass": "трава",
                "concrete": "бетон",
                "paved": "твёрдое покрытие",
                "sand": "песок",
                "artificial_turf": "искусственный газон",
            },
            "sport": {
                "soccer": "футбол",
                "basketball": "баскетбол",
                "tennis": "теннис",
                "volleyball": "волейбол",
                "swimming": "плавание",
                "fitness": "фитнес",
                "running": "бег",
            },
        }
        osm_features = []
        for key, values in translated.items():
            if not osm.get(key):
                continue
            parts = [
                values.get(x.strip(), x.strip().replace("_", " "))
                for x in str(osm[key]).split(";")
            ]
            osm_features.append(
                ("Вид спорта: " if key == "sport" else "Покрытие: ") + ", ".join(parts)
            )
        if osm.get("lit") == "yes":
            osm_features.append(
                "Освещение отмечено в OSM; текущее состояние не проверено"
            )
        if osm.get("covered") == "yes":
            osm_features.append("Навес или крыша отмечены в OSM")
        p["semantic_attributes"] = list(
            dict.fromkeys((p.get("semantic_attributes") or []) + osm_features)
        )
        if osm.get("access") in ("no", "private") and osm.get("foot") not in (
            "yes",
            "designated",
            "permissive",
        ):
            p["recommendation_eligible"] = False
            p["recommendation_exclusion_reason"] = (
                "OSM explicitly restricts public access"
            )
            counts["restricted_pois_excluded"] += 1
        standard = p.get("adult_ticket_price")
        if isinstance(standard, dict) and standard.get("ticket_type") == "Стандарт":
            p["standard_ticket_price"] = standard
            p["adult_ticket_price"] = None
            p["ticket_price_interpretation"] = (
                "operator standard ticket; adult age category not explicitly stated"
            )
        own_tickets = [t for t in ticket_claims if t["poi_id"] == p["poi_id"]]
        if own_tickets:
            p["ticket_options"] = own_tickets
            for t in own_tickets:
                field = (
                    "child_ticket_price"
                    if t["kind"] == "child_entry_ticket"
                    else "standard_ticket_price"
                )
                p[field] = {
                    "amount": t["amount"],
                    "currency": t["currency"],
                    "ticket_type": t["label"],
                    "source_url": t["source_url"],
                    "valid_until": None,
                }
                p.setdefault("sources", [])
                if not any(s.get("url") == t["source_url"] for s in p["sources"]):
                    p["sources"].append(
                        {
                            "name": "Ailand: официальный билет",
                            "url": t["source_url"],
                            "collected_at": t["collected_at"],
                        }
                    )
            p["free_entry"] = False
            p["pricing"] = {
                "status": "has_published_subvenue_ticket_prices",
                "entries": own_tickets,
                "price_document_ids": [],
                "complete_menu_or_all_tariffs_verified": False,
            }
            counts["subvenues_with_explicit_ticket_cards"] += 1
        attrs = p.get("provider_attributes") or []
        tags = {a.get("tag"): a for a in attrs if a.get("tag")}
        important = (
            "wifi",
            "accessible",
            "inclusive",
            "kids",
            "children",
            "working",
            "indoor",
            "outdoor",
            "avg_price",
            "lunch_cost",
            "food_service_food_",
        )
        priority = [
            a["name"]
            for a in attrs
            if any(k in (a.get("tag") or "") for k in important)
        ]
        p["semantic_attributes"] = list(
            dict.fromkeys(priority + (p.get("semantic_attributes") or []))
        )
        family = []
        for tag, label in [
            ("food_service_details_food_kids_menu", "Детское меню"),
            ("food_service_infrastructure_kids_room", "Детский уголок"),
            ("food_service_infrastructure_kids_playroom", "Детская комната"),
            (
                "food_service_infrastructure_children_entertainment",
                "Аниматоры или мастер-классы",
            ),
            ("malls_kids_playground_mall", "Детская игровая зона"),
        ]:
            if tag in tags:
                family.append(
                    {
                        "feature": label,
                        "source_url": tags[tag]["source_url"],
                        "collected_at": tags[tag].get("collected_at"),
                        "independently_verified": False,
                    }
                )
        p["children_facilities"] = family
        if p.get("wheelchair_accessible") is True and "entrance" in str(
            p.get("wheelchair_accessibility_scope") or ""
        ):
            p["entrance_accessible"] = True
        if p["poi_id"] == "osm:way:240860325":
            source = {
                "name": "Visit Astana",
                "url": "https://visitastana.kz/kz/about-city/what-to-see/ziret-s-ltan-meshiti/",
                "collected_at": "2026-10-19",
            }
            p["opening_hours"] = "Mo-Su 06:00-20:00"
            p["opening_hours_by_day"] = {
                d: [["06:00", "20:00"]]
                for d in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
            }
            p["is_24_7"] = False
            p["hours_verified_at"] = None
            p["source_hours_checked_at"] = "2026-10-19"
            p["opening_hours_evidence"] = {
                "source_url": source["url"],
                "evidence": "Күнделікті сағат 06:00-ден 20:00-ге дейін",
                "kind": "published_visitor_schedule",
                "physically_verified": False,
                "collected_at": "2026-10-19",
            }
            p.setdefault("sources", [])
            if not any(s.get("url") == source["url"] for s in p["sources"]):
                p["sources"].append(source)
            p["opening_hours_conflicts"] = [
                {
                    "source_url": "https://welcome.kz/ru/info-cities/astana/hazret-sultan-mosque",
                    "claim": "24/7",
                    "resolution": "prefer_current_city_tourism_visitor_schedule; religious access may differ",
                }
            ]
            counts["new_primary_schedules"] += 1
        summary = []
        category = (
            p.get("subcategory_label") or p.get("subcategory") or p.get("category")
        )
        if category:
            summary.append(f"{p.get('display_name')}: {category}.")
        details = [
            a
            for a in p.get("semantic_attributes") or []
            if not re.search(r"оплата|расч[её]т|перевод с карты", a, re.I)
        ]
        if details:
            summary.append("В каталоге указаны: " + ", ".join(details[:8]) + ".")
        for key, label in [
            ("wifi_available", "Wi-Fi"),
            ("power_outlets", "розетки"),
            ("ramps", "пандус"),
            ("entrance_accessible", "доступный вход"),
        ]:
            if p.get(key) is True:
                summary.append(f"По сведениям источника: {label}.")
        if family:
            summary.append(
                "Для посетителей с детьми указаны: "
                + ", ".join(x["feature"] for x in family)
                + "."
            )
        if p.get("indoor_outdoor") in ("indoor", "outdoor", "both"):
            summary.append(
                {
                    "indoor": "Указано размещение в помещении.",
                    "outdoor": "Указано размещение на открытом воздухе.",
                    "both": "Указаны крытые и открытые зоны.",
                }[p["indoor_outdoor"]]
            )
        p["grounded_description"] = " ".join(summary)
        p["description_provenance"] = {
            "method": "deterministic_attribute_summary",
            "independent_source_prose": False,
            "source_record_ids": p.get("source_record_ids", []),
            "source_urls": list(
                dict.fromkeys(
                    s.get("url") for s in p.get("sources", []) if s.get("url")
                )
            ),
        }
        if p.get("description_type") == "derived_template" and (
            details
            or family
            or p.get("wifi_available") is True
            or p.get("ramps") is True
        ):
            p["description_original"] = p.get("short_description")
            p["short_description"] = p["grounded_description"]
            p["description_type"] = "attribute_grounded_summary"
            counts["richer_factual_summaries"] += 1
        counts["with_child_facilities"] += bool(family)
        counts["with_grounded_attributes"] += bool(details)
        counts["with_branch_prices"] += bool((p.get("pricing") or {}).get("entries"))
        counts["with_published_constraints"] += bool(
            (p.get("visit_rules") or {}).get("constraints")
        )
        required = ["opening_hours", "indoor_outdoor", "wheelchair_accessible"]
        if p.get("category") in ("food_drink", "quiet_spaces"):
            required += [
                "power_outlets",
                "quiet_place",
                "wifi_available",
                "estimated_visit_budget",
            ]
        if p.get("category") in ("culture", "entertainment", "children"):
            required += ["adult_ticket_price", "child_ticket_price", "age_restrictions"]
        missing = [k for k in required if p.get(k) is None]
        if missing:
            backlog.append(
                {
                    "poi_id": p["poi_id"],
                    "name": p.get("display_name"),
                    "category": p.get("category"),
                    "missing_fields": missing,
                    "website": p.get("website"),
                    "phone": p.get("phone"),
                    "source_urls": [s.get("url") for s in p.get("sources") or []],
                    "next_action": "check operator branch page or obtain explicit venue confirmation; no contact messages sent",
                }
            )
    # Near-brand groups are a diversity rule, NOT entity-resolution evidence.
    groups = collections.defaultdict(list)
    for p in canonical:
        if p.get("name_is_source_backed"):
            groups[(name_fn(p), p.get("category"))].append(p)
    parent = {p["poi_id"]: p["poi_id"] for p in canonical}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for members in groups.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if dist_fn(a, b) <= 150:
                    parent[find(b["poi_id"])] = find(a["poi_id"])
    for p in canonical:
        p["recommendation_diversity_group"] = find(p["poi_id"])
    review = []
    for pair in candidates:
        a, b = raw[pair["left"]], raw[pair["right"]]
        ca, cb = aliases[pair["left"]], aliases[pair["right"]]
        roles = re.compile(
            r"зал\s*[№#]?\s*\d|автоэкспресс|drive.?thru|пункт выдачи|навынос", re.I
        )
        units = bool(
            roles.search(
                (a.get("display_name") or "") + " " + (b.get("display_name") or "")
            )
        )
        if ca == cb:
            decision = "already_same_canonical_entity"
        elif address_fn(a, b) and units:
            decision = "separate_service_units_at_same_address"
        elif address_fn(a, b):
            decision = "same_address_identity_not_proven_keep_facts_separate"
        elif a.get("address") and b.get("address"):
            decision = "different_or_unmatched_addresses_keep_separate"
        else:
            decision = "insufficient_identity_evidence_keep_separate"
        review.append(
            {
                **pair,
                "canonical_left": ca,
                "canonical_right": cb,
                "decision": decision,
                "review_method": "deterministic_names_addresses_roles_and_source_id_review",
                "physically_verified": False,
                "sources_left": [s.get("url") for s in a.get("sources") or []],
                "sources_right": [s.get("url") for s in b.get("sources") or []],
                "duplicate_recommendation_suppressed": parent.get(ca) is not None
                and find(ca) == find(cb),
            }
        )
    write_jsonl(out / "duplicate_review_decisions.jsonl", review)
    write_jsonl(out / "missing_data_backlog.jsonl", backlog)
    return {
        **dict(counts),
        "candidate_pairs_reviewed": len(review),
        "candidate_decisions": dict(collections.Counter(x["decision"] for x in review)),
        "unknown_fields_preserved": True,
        "backlog_records": len(backlog),
        "nearby_brand_diversity": "one suggestion per same-brand 150m group; facts never transferred between unresolved entities",
    }
