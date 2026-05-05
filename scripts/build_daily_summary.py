#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser(); ap.add_argument("--date"); a=ap.parse_args()
date=a.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
src=BASE/"data/silver/friction_events"/f"{date}.jsonl"
rows=[]
if src.exists():
    rows=[json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
summary={"date":date,"total_events":len(rows),"events_by_source":dict(Counter(r.get("source") for r in rows)),"events_by_category":dict(Counter(r.get("category") for r in rows)),"events_by_line":dict(Counter(r.get("line") for r in rows if r.get("line"))),"accessibility_friction":sum(1 for r in rows if r.get("category")=="elevator_or_accessibility_issue"),"state_counts":dict(Counter(r.get("event_state","unknown") for r in rows)),"severe": [r for r in rows if int(r.get("severity",0))>=3][:10],"limitations":"This does not measure crowding without direct source data."}
outj=BASE/"data/gold/daily"/f"{date}.json"; outj.parent.mkdir(parents=True,exist_ok=True); outj.write_text(json.dumps(summary,indent=2),encoding="utf-8")
md=[f"# Transit Friction Daily — {date}","","## What we collected",f"- Events: {len(rows)}","","## Source coverage"]
for k,v in summary["events_by_source"].items(): md.append(f"- {k}: {v}")
md += ["","## Events by category"] + [f"- {k}: {v}" for k,v in summary["events_by_category"].items()] + ["","## What this does not measure","- Crowding without source data."]
(BASE/"data/gold/daily"/f"{date}.md").write_text("\n".join(md),encoding="utf-8")
print("built",date)
