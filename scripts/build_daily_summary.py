#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from transit_friction.config import NORMALIZED_DIR, SUMMARIES_DIR
from transit_friction.analysis.daily_summary import summarize_events
from transit_friction.output.markdown_report import build_markdown
from transit_friction.output.json_export import write_json

now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
src = NORMALIZED_DIR / f"{now}.jsonl"
events = []
if src.exists():
    for line in src.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
summary = summarize_events(events)
write_json(SUMMARIES_DIR / f"{now}.json", summary)
(SUMMARIES_DIR / f"{now}.md").write_text(build_markdown(now, summary), encoding="utf-8")
print(f"built summary for {now} ({len(events)} events)")
