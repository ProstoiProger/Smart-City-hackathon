from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
DATA = ROOT / "data"


def setting(key, default=""):
    return os.environ.get(key, default).strip()
