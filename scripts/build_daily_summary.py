#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from transit_friction.config import OUTPUT_ROOT as BASE
ap=argparse.ArgumentParser(); ap.add_argument("--date"); a=ap.parse_args()
date=a.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

rows=_read_jsonl(BASE/"data/silver/friction_events"/f"{date}.jsonl")
deps=_read_jsonl(BASE/"data/silver/departure_observations"/f"{date}.jsonl")
jours=_read_jsonl(BASE/"data/silver/journey_observations"/f"{date}.jsonl")

worst=max(jours, key=lambda x: x.get("delay_delta_min") or 0, default=None)
cancelled=[j for j in jours if j.get("cancellation_present")]
delayed_stations=Counter(d.get("stop_name") for d in deps if (d.get("delay_seconds") or 0) > 0)

summary={"date":date,"total_events":len(rows),"events_by_source":dict(Counter(r.get("source") for r in rows)),"events_by_category":dict(Counter(r.get("category") for r in rows)),"events_by_line":dict(Counter(r.get("line") for r in rows if r.get("line"))),"accessibility_friction":sum(1 for r in rows if r.get("category")=="elevator_or_accessibility_issue"),"state_counts":dict(Counter(r.get("event_state","unknown") for r in rows)),"severe": [r for r in rows if int(r.get("severity",0))>=3][:10],"connection_watchlist_count":len(jours),"worst_relation_by_delay_delta":worst,"relations_with_cancellations":[{"relation_id":r.get("relation_id"),"relation_label":r.get("relation_label")} for r in cancelled],"stations_with_most_delayed_departures":delayed_stations.most_common(5),"data_coverage":{"friction_events":len(rows),"departure_observations":len(deps),"journey_observations":len(jours)},"limitations":"BrokenLifts is included as a side-channel signal, not the primary service quality metric."}
outj=BASE/"data/gold/daily"/f"{date}.json"; outj.parent.mkdir(parents=True,exist_ok=True); outj.write_text(json.dumps(summary,indent=2),encoding="utf-8")

md=[f"# Transit Friction Daily — {date}","","## Connection watchlist",f"- Journey observations: {len(jours)}",f"- Departure observations: {len(deps)}",""]
md += ["## Worst observed relation by delay delta", f"- {(worst or {}).get('relation_label','n/a')}: {(worst or {}).get('delay_delta_min','n/a')} min", ""]
md += ["## Relations with cancellations"] + ([f"- {x.get('relation_label')}" for x in cancelled] or ["- None observed"]) + [""]
md += ["## Stations with most delayed departures"] + ([f"- {k}: {v}" for k,v in delayed_stations.most_common(5)] or ["- None observed"]) + [""]
md += ["## Data coverage", f"- Friction events: {len(rows)}", f"- Departure observations: {len(deps)}", f"- Journey observations: {len(jours)}", "", "## Accessibility side-channel", "- BrokenLifts remains collected as an accessibility signal and is not the main metric."]
(BASE/"data/gold/daily"/f"{date}.md").write_text("\n".join(md),encoding="utf-8")
print("built",date)
