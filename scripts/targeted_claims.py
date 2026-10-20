"""Extract primary product cards from saved operator pages, preserving subvenue scope."""

from pathlib import Path
import hashlib
import html
import json
import re


def plain(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def build(root, source):
    raw = source.parent / "raw"
    index = json.loads((raw / "extended_index.json").read_text(encoding="utf-8"))
    urls = {
        "https://ailand.kz/ru/attractions/ocean-ru/": "official:ailand_oceanarium",
        "https://ailand.kz/ru/attractions/jungle-ru/": "official:ailand_jungle",
    }
    claims = []
    for row in index:
        if row["url"] not in urls or not row.get("path"):
            continue
        path = source.parent.parent / row["path"]
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8")
        metadata = path.with_suffix(path.suffix + ".meta.json")
        date = (
            json.loads(metadata.read_text(encoding="utf-8")).get("collected_at")
            if metadata.exists()
            else "2026-10-19"
        )
        for card in re.findall(
            r"<article\b[^>]*class=[\"\'][^\"\']*tpt-shop__card[^\"\']*[\"\'][^>]*>(.*?)</article>",
            body,
            re.S | re.I,
        ):
            title = re.search(r"<h3\b[^>]*>(.*?)</h3>", card, re.S | re.I)
            price = re.search(
                r"<p\b[^>]*class=[\"\'][^\"\']*tpt-shop__card-price[^\"\']*[\"\'][^>]*>(.*?)</p>",
                card,
                re.S | re.I,
            )
            if not title or not price:
                continue
            label = plain(title[1])
            text = plain(price[1])
            digits = re.sub(r"\D", "", text)
            if not digits or "₸" not in text:
                continue
            kind = (
                "child_entry_ticket"
                if "Детский" in label
                else "standard_entry_ticket" if "Стандарт" in label else None
            )
            if not kind:
                continue
            claims.append(
                {
                    "poi_id": urls[row["url"]],
                    "kind": kind,
                    "label": label,
                    "amount": int(digits),
                    "currency": "KZT",
                    "source_url": row["url"],
                    "collected_at": date,
                    "snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "scope": "named_subvenue_product_card",
                    "age_bounds": None,
                    "note": "Standard is the operator label; adult age eligibility is not inferred.",
                }
            )
    (root / "data" / "targeted_primary_claims.json").write_text(
        json.dumps(claims, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return claims
