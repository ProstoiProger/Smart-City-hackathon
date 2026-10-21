"""Build data/city_audit.json: where the city cannot answer typical requests.

    python scripts/build_city_audit.py

Takes about two minutes on the bundled data.
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.cityaudit import build  # noqa: E402
from backend.service import City  # noqa: E402
from backend.settings import DATA  # noqa: E402


def main():
    city = City()
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 10, 19)
    result = build(city, day, progress=lambda n, total: print(f"\r{n}/{total} cells", end="", flush=True))
    (DATA / "city_audit.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print()
    for s in result["scenarios"]:
        print(s["id"], s["summary"])


if __name__ == "__main__":
    main()
