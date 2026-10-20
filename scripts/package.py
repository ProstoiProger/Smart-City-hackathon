"""Create a clean source+data delivery; never include .env, caches or node_modules."""

from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "test-results",
    "playwright-report",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="astana_walk_full_project_v2.zip")
    args = parser.parse_args()
    if Path(args.name).name != args.name or not args.name.endswith(".zip"):
        raise ValueError("Archive name must be a plain .zip filename")
    out = ROOT.parent / "output" / args.name
    out.parent.mkdir(exist_ok=True)
    files = [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not (set(p.relative_to(ROOT).parts) & EXCLUDE)
        and (not p.name.startswith(".env") or p.name == ".env.example")
        and not p.name.endswith((".log", ".tmp"))
    ]
    # Compare known local credential values without displaying or copying them.
    secrets = []
    for env in [
        ROOT / ".env",
        ROOT.parent / ".env",
        ROOT.parent.parent / "AFM_project" / ".env",
    ]:
        if env.exists():
            for line in env.read_text(encoding="utf-8-sig").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                value = value.strip().strip("\"'")
                if (
                    any(
                        x in key.upper() for x in ("KEY", "TOKEN", "SECRET", "PASSWORD")
                    )
                    and len(value) >= 12
                ):
                    secrets.append(value.encode())
    checks = []
    for p in sorted(files):
        content = p.read_bytes()
        if any(secret in content for secret in secrets):
            raise RuntimeError(
                "Known credential found in delivery file: " + str(p.relative_to(ROOT))
            )
        checks.append(
            hashlib.sha256(content).hexdigest() + "  " + p.relative_to(ROOT).as_posix()
        )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            z.write(p, "smart_city_app/" + p.relative_to(ROOT).as_posix())
        z.writestr("smart_city_app/SHA256SUMS.txt", "\n".join(checks) + "\n")
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert not any(
            n.endswith("/.env") or "/node_modules/" in n for n in z.namelist()
        )
    report = {
        "path": str(out),
        "files": len(files) + 1,
        "bytes": out.stat().st_size,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "known_credentials_scan": "passed",
        "zip_crc": "passed",
    }
    out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
