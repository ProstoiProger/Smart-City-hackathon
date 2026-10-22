# Download Noto emoji for every emoji used in the frontend: a static SVG for each, and a small
# animated WebP (from Noto Animated Emoji, CC BY 4.0) where Google publishes an animation.
# Usage: python scripts/fetch_noto_emoji.py [extra emoji...]  (needs Pillow and internet)
# Extra emoji are the ones computed at run time (weather): ☀️ ⛅ ❄️ ⛈️ 🌧️ 🌫️ ☁️ 🌤️
import io, json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
SRC = FRONTEND / "src"
OUT = FRONTEND / "public" / "emoji"
EXTRA = sys.argv[1:]
SIZE = 80
BASE = "https://fonts.gstatic.com/s/e/notoemoji/latest/"
OUT.mkdir(parents=True, exist_ok=True)


def is_pic(c):
    o = ord(c)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or o in (0x2139, 0x231A, 0x231B, 0x23F0, 0x23F1, 0x23F3, 0x2B50, 0x2705, 0x26A1)


def used_emoji():
    found = set(EXTRA)
    for path in SRC.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        i = 0
        while i < len(text):
            if is_pic(text[i]) and not (0x1F3FB <= ord(text[i]) <= 0x1F3FF):
                j = i + 1
                while j < len(text) and (text[j] in "️‍" or (text[j - 1] == "‍" and is_pic(text[j]))):
                    j += 1
                found.add(text[i:j])
                i = j
            else:
                i += 1
    return found


def hexname(e, keep_fe0f=False):
    return "_".join(f"{ord(c):x}" for c in e if keep_fe0f or c != "️")


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            return r.read()
    except Exception:
        return None


def valid_webp(path):
    try:
        with Image.open(path) as im:
            im.seek(getattr(im, "n_frames", 1) - 1)
        return True
    except Exception:
        return False


def fetch(e):
    name = hexname(e)
    svg_path, webp_path = OUT / (name + ".svg"), OUT / (name + ".webp")
    if not svg_path.exists():
        svg = get(BASE + name + "/emoji.svg") or get(BASE + hexname(e, True) + "/emoji.svg")
        if not svg:
            return e, None
        svg_path.write_bytes(svg)
    if webp_path.exists() and valid_webp(webp_path):
        return e, {"file": name, "animated": True}
    anim = get(BASE + name + "/512.webp") or get(BASE + hexname(e, True) + "/512.webp")
    if not anim:
        return e, {"file": name, "animated": False}
    im = Image.open(io.BytesIO(anim))
    frames, durations = [], []
    try:
        while True:
            frames.append(im.convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS))
            durations.append(im.info.get("duration", 40))
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    if len(frames) < 2:
        return e, {"file": name, "animated": False}
    # Long animations keep at most ~36 frames, each shown longer: same motion, a smaller file.
    step = max(1, -(-len(frames) // 36))
    if step > 1:
        frames = frames[::step]
        durations = [d * step for d in durations[::step]]
    frames[0].save(webp_path, save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=60, method=4)
    return e, {"file": name, "animated": True}


def main():
    manifest = {}
    with ThreadPoolExecutor(8) as pool:
        for e, entry in pool.map(fetch, sorted(used_emoji())):
            if entry:
                manifest[e] = entry
            print(e, entry and ("anim" if entry["animated"] else "still") or "MISSING", flush=True)
    # Files of emoji no longer used go away.
    keep = {v["file"] for v in manifest.values()}
    for f in OUT.iterdir():
        if f.stem not in keep:
            f.unlink()
    total = sum(f.stat().st_size for f in OUT.iterdir())
    print(len(manifest), "emoji,", round(total / 1024), "KB")
    (SRC / "lib" / "emoji-manifest.json").write_text(json.dumps(dict(sorted(manifest.items())), ensure_ascii=False, indent=0), encoding="utf-8")


if __name__ == "__main__":
    main()
