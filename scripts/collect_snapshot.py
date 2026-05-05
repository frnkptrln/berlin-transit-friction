#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from transit_friction.config import RAW_DIR, NORMALIZED_DIR
from transit_friction.normalize.events import classify_category, estimate_severity, stable_event_id
from transit_friction.sources.vbb_transport_rest import fetch_disruptions as vbb_disruptions
from transit_friction.sources.bvg_transport_rest import fetch_disruptions as bvg_disruptions
from transit_friction.sources.vbb_gtfs_rt import fetch_gtfs_rt_metadata


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    now = datetime.now(timezone.utc)
    run_dir = RAW_DIR / now.strftime("%Y/%m/%d/%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"collected_at": now.isoformat(), "sources_attempted": [], "sources_succeeded": [], "sources_failed": [], "event_count": 0, "warnings": []}
    events = []

    sources = {
        "vbb_transport_rest": lambda: vbb_disruptions(),
        "bvg_transport_rest": lambda: bvg_disruptions(),
        "vbb_gtfs_rt": lambda: fetch_gtfs_rt_metadata(),
    }

    for name, fn in sources.items():
        manifest["sources_attempted"].append(name)
        data = fn()
        if data is None:
            manifest["sources_failed"].append(name)
            manifest["warnings"].append(f"{name} returned no data")
            continue
        manifest["sources_succeeded"].append(name)
        save_json(run_dir / f"{name}.json", data)
        if name == "vbb_gtfs_rt":
            continue
        text = json.dumps(data)[:500]
        category = classify_category(text)
        ev = {
            "event_id": stable_event_id(name, category, None, None, f"{name} snapshot", now),
            "source": name,
            "collected_at": now.isoformat(),
            "observed_at": None,
            "valid_from": now.isoformat(),
            "valid_until": None,
            "mode": None,
            "operator": "VBB/BVG",
            "line": None,
            "direction": None,
            "stop_id": None,
            "stop_name": None,
            "category": category,
            "severity": estimate_severity(category, text),
            "title": f"{name} snapshot collected",
            "description": "Automated snapshot-derived friction signal.",
            "raw_reference": str(run_dir / f"{name}.json"),
            "url": None,
            "confidence": 0.4,
            "raw": None,
        }
        events.append(ev)

    day_file = NORMALIZED_DIR / f"{now.strftime('%Y-%m-%d')}.jsonl"
    day_file.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if day_file.exists():
        for line in day_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line).get("event_id"))
    with day_file.open("a", encoding="utf-8") as f:
        for ev in events:
            if ev["event_id"] in existing:
                continue
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    manifest["event_count"] = len(events)
    save_json(run_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
