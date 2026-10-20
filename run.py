"""Run the bundled production frontend and API on the same local origin."""

from pathlib import Path
import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    if not (Path(__file__).parent / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("Frontend missing. Run: cd frontend; npm ci; npm run build")
    print(f"Astana Walk: http://{args.host}:{args.port}")
    # No access log: users may use coordinates in requests; no persistent chat store.
    uvicorn.run("backend.app:app", host=args.host, port=args.port, access_log=False)
