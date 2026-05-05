#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from transit_friction.config import SUMMARIES_DIR, SITE_DATA_DIR
from transit_friction.output.json_export import write_json

files = sorted(SUMMARIES_DIR.glob("*.json"))
daily = []
for f in files:
    obj = json.loads(f.read_text(encoding="utf-8"))
    daily.append({"date": f.stem, "total_events": obj.get("total_events", 0)})
latest = daily[-1] if daily else {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "total_events": 0}
write_json(SITE_DATA_DIR / "daily-index.json", daily)
write_json(SITE_DATA_DIR / "latest.json", {"generated_at": datetime.now(timezone.utc).isoformat(), **latest})
write_json(SITE_DATA_DIR / "line-stats.json", [])
print("site data built")
