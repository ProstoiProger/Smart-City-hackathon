"""Verify hashes and execute delivered code from a fresh, safe ZIP extraction."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def run(project, args):
    result = subprocess.run(
        [sys.executable, "-X", "utf8", *args],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    extraction = Path(
        tempfile.mkdtemp(prefix="astana_walk_v2_verify_", dir=archive.parent)
    )
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name in z.namelist():
            target = (extraction / name).resolve()
            if not target.is_relative_to(extraction.resolve()):
                raise ValueError("ZIP member escapes extraction directory")
        z.extractall(extraction)
    project = extraction / "smart_city_app"
    manifest = (project / "SHA256SUMS.txt").read_text(encoding="utf-8")
    verified = 0
    for line in manifest.splitlines():
        expected, name = line.split("  ", 1)
        path = (project / name).resolve()
        assert path.is_relative_to(project.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
        verified += 1
    assert not list(project.rglob(".env"))
    backend_tests = run(project, ["-m", "pytest", "tests", "-q"])
    collector_tests = run(project / "collector", ["-m", "pytest", "tests", "-q"])
    indexes = json.loads(run(project, ["scripts/verify_delivery.py"]))
    smoke = json.loads(
        run(
            project,
            [
                "-c",
                """
import json
from fastapi.testclient import TestClient
from backend.app import app
with TestClient(app) as c:
    health=c.get('/api/health').json()
    assert health=={'ok':True,'pois':7431}
    page=c.get('/')
    assert page.status_code==200 and '<html' in page.text
    places=c.post('/api/search',json={'query':'Байтерек','limit':3,'when':'2026-10-19T12:00:00+05:00'}).json()
    assert any('бәйтерек' in p['display_name'].casefold() or 'байтерек' in p['display_name'].casefold() for p in places['items'])
    ocean=c.get('/api/pois/official:ailand_oceanarium').json()
    assert ocean['standard_ticket_price']['amount']==5600 and ocean['child_ticket_price']['amount']==4400
    assert ocean['adult_ticket_price'] is None
    flight=c.post('/api/chat',json={'query':'У меня 2 часа до вылета','provider':'offline'}).json()
    fc=flight['flight_context']
    assert fc['needs_buffers'] and fc['buffers_source']=='default_assumption' and fc['walk_budget_minutes']==30
    assert all(p['total_duration_min']<=30 for p in flight['items'])
    print(json.dumps({'health':health,'frontend':'served','named_search':'passed','subvenue_prices':'passed','flight_guard':'passed'}))
""",
            ],
        )
    )
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "archive": str(archive),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "extracted_to": str(project),
        "zip_crc": "passed",
        "sha256_files_verified": verified,
        "backend_pytest": backend_tests,
        "collector_pytest": collector_tests,
        "indexes": indexes,
        "smoke": smoke,
        "environment": "existing installed dependencies; not a fresh dependency installation",
    }
    target = archive.with_suffix(".verification.json")
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
