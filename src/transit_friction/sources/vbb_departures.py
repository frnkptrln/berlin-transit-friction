from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from transit_friction.config import BASE_DIR, DATA_DIR, OUTPUT_ROOT
from transit_friction.storage import write_json_gz, write_jsonl

BASE = "https://v6.vbb.transport.rest"


def load_watchlist_stops() -> list[dict]:
    payload = json.loads((BASE_DIR / "config/watchlist_stops.yml").read_text(encoding="utf-8"))
    return payload.get("stops", [])


def _normalize_departure(stop: dict, dep: dict, observed_at: str) -> dict:
    planned_when = dep.get("plannedWhen")
    when = dep.get("when")
    delay = dep.get("delay")
    return {
        "observed_at": observed_at,
        "source": "vbb_departures",
        "stop_id": stop["stop_id"],
        "stop_name": stop["label"],
        "line_name": (dep.get("line") or {}).get("name"),
        "product": (dep.get("line") or {}).get("product"),
        "direction": dep.get("direction"),
        "trip_id": (dep.get("trip") or {}).get("id"),
        "planned_when": planned_when,
        "when": when,
        "delay_seconds": delay,
        "cancelled": bool(dep.get("cancelled")),
        "platform": dep.get("platform"),
        "planned_platform": dep.get("plannedPlatform"),
        "remarks": dep.get("remarks") or [],
        "realtime_data_updated_at": dep.get("prognosisType") or dep.get("provenance"),
    }


def collect(now: datetime | None = None) -> tuple[list[str], list[dict]]:
    now = now or datetime.now(timezone.utc)
    observed_at = now.isoformat()
    day = now.strftime("%Y-%m-%d")
    bronze_files = []
    rows = []
    for stop in load_watchlist_stops():
        url = f"{BASE}/stops/{stop['stop_id']}/departures"
        r = requests.get(url, params={"duration": 30, "remarks": "true", "language": "de"}, timeout=20)
        payload = r.json() if r.ok else {"departures": []}
        departures = payload.get("departures", []) if isinstance(payload, dict) else []
        raw_path = DATA_DIR / "bronze/vbb_departures" / now.strftime("%Y/%m/%d") / f"{stop['stop_id']}_{now.strftime('%H%M%S')}.json.gz"
        write_json_gz(raw_path, {"observed_at": observed_at, "stop": stop, "payload": payload, "status_code": r.status_code})
        bronze_files.append(str(raw_path.relative_to(OUTPUT_ROOT)))
        rows.extend(_normalize_departure(stop, d, observed_at) for d in departures)
    silver_path = DATA_DIR / "silver/departure_observations" / f"{day}.jsonl"
    if rows:
        write_jsonl(silver_path, rows, append=True)
    return bronze_files, rows
