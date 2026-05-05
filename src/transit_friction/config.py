from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
SUMMARIES_DIR = DATA_DIR / "summaries"
SITE_DATA_DIR = BASE_DIR / "site" / "data"

DEFAULT_TIMEOUT = 20
USER_AGENT = "transit-friction-mvp/0.1"
