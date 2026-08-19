#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1]/"src"))
from transit_friction.health import build_source_health
from transit_friction.config import OUTPUT_ROOT as BASE
manifests=list((BASE/"data/manifests").glob("**/*.json"))
objs=[json.loads(m.read_text()) for m in manifests]
health=build_source_health(objs)
today=datetime.now(timezone.utc).strftime("%Y-%m-%d")
out=BASE/"data/gold/source-health"/f"{today}.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(health,indent=2))
site_data=BASE/"site/data"; site_data.mkdir(parents=True, exist_ok=True)
(site_data/"source-health.json").write_text(json.dumps(health,indent=2))
print("health built")
