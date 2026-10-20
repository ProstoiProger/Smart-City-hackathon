"""Main 2GIS photo of a place, looked up only when a visitor opens its card.

2GIS serves a branch's main photo at a stable CDN address (the same value its Places
API returns as external_content[].main_photo_url). We only check that the image
exists and hand the address to the browser with attribution; nothing is downloaded
or stored, and places without a 2GIS branch simply have no photo.
"""

import re
import threading
import time
import httpx

# 68 is the 2GIS region code of Astana in these addresses.
CDN = "https://i{shard}.photo.2gis.com/main/branch/68/{branch}/common"
FIRM = "https://2gis.kz/astana/firm/{branch}"
USER_AGENT = "AstanaWalkHackathon/1.0 (place card photo check)"
TTL_FOUND = 7 * 24 * 3600  # matches the CDN's own max-age
TTL_MISSING = 24 * 3600
TTL_ERROR = 300  # network trouble: retry soon, never cache as "no photo" for long

_BRANCH = re.compile(r"\d{10,20}")
_FIRM_LINK = re.compile(r"/firm/(\d{10,20})")
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def branch_ids(p):
    """2GIS branch ids of a canonical place, from identity fields only."""
    found = []
    values = [(p.get("external_ids") or {}).get("2gis"), p.get("raw_2gis_id")]
    values += [rid[5:] for rid in p.get("source_record_ids") or [] if str(rid).startswith("dgis:")]
    if str(p.get("poi_id", "")).startswith("dgis:"):
        values.append(p["poi_id"][5:])
    for value in values:
        value = str(value or "").strip()
        link = _FIRM_LINK.search(value)
        if link:
            value = link.group(1)
        if _BRANCH.fullmatch(value) and value not in found:
            found.append(value)
    return found


def _probe(branch, client):
    url = CDN.format(shard=int(branch) % 10, branch=branch)
    response = client.head(url, follow_redirects=True)
    if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
        return url
    if response.status_code == 404:
        return None
    raise httpx.HTTPStatusError("unexpected status", request=response.request, response=response)


def main_photo(p, timeout=6.0):
    """{"available": bool, "url", "source", "source_url"} for the place's 2GIS main photo."""
    branches = branch_ids(p)
    if not branches:
        return {"available": False, "reason": "no_2gis_branch"}
    key = branches[0]
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    result, ttl = {"available": False, "reason": "no_photo"}, TTL_MISSING
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            for branch in branches:
                url = _probe(branch, client)
                if url:
                    result = {
                        "available": True,
                        "url": url,
                        "source": "2ГИС",
                        "source_url": FIRM.format(branch=branch),
                    }
                    ttl = TTL_FOUND
                    break
    except httpx.HTTPError:
        result, ttl = {"available": False, "reason": "unavailable"}, TTL_ERROR
    with _lock:
        _cache[key] = (now + ttl, result)
    return result
