from __future__ import annotations
import hashlib
from datetime import datetime, timezone
import requests
from transit_friction.config import DEFAULT_TIMEOUT, USER_AGENT

GTFS_URL = "https://production.gtfsrt.vbb.de/data"


def fetch_gtfs_rt_metadata() -> dict:
    headers = {"User-Agent": USER_AGENT}
    collected_at = datetime.now(timezone.utc).isoformat()
    try:
        r = requests.get(GTFS_URL, headers=headers, timeout=DEFAULT_TIMEOUT)
        payload = r.content or b""
        return {
            "collected_at": collected_at,
            "status_code": r.status_code,
            "content_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    except Exception as e:
        return {
            "collected_at": collected_at,
            "status_code": None,
            "content_length": 0,
            "sha256": None,
            "error": str(e),
        }
