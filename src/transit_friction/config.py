from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
SUMMARIES_DIR = DATA_DIR / "summaries"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
MANIFESTS_DIR = DATA_DIR / "manifests"
SITE_DATA_DIR = BASE_DIR / "site" / "data"
STATE_DIR = DATA_DIR / "state"

DEFAULT_TIMEOUT = 20
USER_AGENT = "transit-friction/0.2"
