from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from transit_friction.config import BASE_DIR
from transit_friction.storage import write_json_gz, write_jsonl

BASE = "https://v6.vbb.transport.rest"


def load_watchlist_journeys() -> list[dict]:
    payload = json.loads((BASE_DIR / "config/watchlist_journeys.yml").read_text(encoding="utf-8"))
    return payload.get("relations", [])


def _to_min(iso_duration: str | None) -> float | None:
    if not iso_duration:
        return None
    try:
        h = m = 0
        t = iso_duration.replace("PT", "")
        if "H" in t:
            h, t = t.split("H", 1)
        if "M" in t:
            m = t.split("M", 1)[0]
        return int(h or 0) * 60 + int(m or 0)
    except Exception:
        return None


def _journey_metrics(journey: dict) -> dict:
    legs = journey.get("legs") or []
    delays = [int(l.get("arrivalDelay") or 0) for l in legs] + [int(l.get("departureDelay") or 0) for l in legs]
    cancelled_count = sum(1 for l in legs if l.get("cancelled"))
    lines = [((l.get("line") or {}).get("name")) for l in legs if l.get("line")]
    remarks = [r.get("text") for r in (journey.get("remarks") or []) if isinstance(r, dict) and r.get("text")]
    planned = _to_min(journey.get("plannedDuration"))
    realtime = _to_min(journey.get("duration"))
    delta = (realtime - planned) if (planned is not None and realtime is not None) else None
    missing_rt = int(any((l.get("arrivalDelay") is None and l.get("departureDelay") is None) for l in legs))
    return {
        "planned_duration_min": planned,
        "realtime_duration_min": realtime,
        "duration_delta_min": delta,
        "transfers": journey.get("transfers"),
        "number_of_legs": len(legs),
        "cancelled_leg_count": cancelled_count,
        "max_leg_delay_seconds": max(delays) if delays else 0,
        "total_leg_delay_seconds": sum(delays),
        "lines_used": [x for x in lines if x],
        "remarks": remarks,
        "delay_delta_min": delta or 0,
        "transfer_risk": bool((journey.get("transfers") or 0) >= 2 and (max(delays) if delays else 0) > 180),
        "cancellation_present": cancelled_count > 0,
        "missing_realtime_data": bool(missing_rt),
        "journey_friction_score": max(0, (delta or 0)) + cancelled_count * 10 + (((max(delays) if delays else 0) / 60.0)),
    }


def collect(now: datetime | None = None) -> tuple[list[str], list[dict]]:
    now = now or datetime.now(timezone.utc)
    observed_at = now.isoformat()
    day = now.strftime("%Y-%m-%d")
    bronze_files = []
    rows = []
    for rel in load_watchlist_journeys():
        r = requests.get(
            f"{BASE}/journeys",
            params={"from": rel["from"], "to": rel["to"], "results": 3, "stopovers": "true", "remarks": "true", "language": "de"},
            timeout=20,
        )
        payload = r.json() if r.ok else {"journeys": []}
        journeys = payload.get("journeys", []) if isinstance(payload, dict) else []
        raw_path = BASE_DIR / "data/bronze/vbb_journeys" / now.strftime("%Y/%m/%d") / f"{rel['id']}_{now.strftime('%H%M%S')}.json.gz"
        write_json_gz(raw_path, {"observed_at": observed_at, "relation": rel, "payload": payload, "status_code": r.status_code})
        bronze_files.append(str(raw_path.relative_to(BASE_DIR)))
        for j in journeys:
            row = {"relation_id": rel["id"], "relation_label": rel["label"], "observed_at": observed_at, **_journey_metrics(j), "refresh_token": payload.get("refreshToken")}
            rows.append(row)
    silver_path = BASE_DIR / "data/silver/journey_observations" / f"{day}.jsonl"
    if rows:
        write_jsonl(silver_path, rows, append=True)
    return bronze_files, rows
