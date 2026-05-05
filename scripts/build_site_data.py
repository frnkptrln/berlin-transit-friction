#!/usr/bin/env python3
import json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
daily=sorted((BASE/"data/gold/daily").glob("*.json"))
items=[]
for f in daily:
    j=json.loads(f.read_text())
    items.append({"date":j["date"],"total_events":j["total_events"]})
latest=items[-1] if items else {"date":None,"total_events":0}
site=BASE/"site/data"; site.mkdir(parents=True,exist_ok=True)
(site/"daily-index.json").write_text(json.dumps(items,indent=2))
(site/"latest.json").write_text(json.dumps(latest,indent=2))
(site/"line-stats.json").write_text(json.dumps([],indent=2))
print("ok")
