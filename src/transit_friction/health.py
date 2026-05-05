from __future__ import annotations
from collections import defaultdict

def build_source_health(manifests: list[dict]):
    state = defaultdict(lambda: {"last_success":None,"last_failure":None,"consecutive_failures":0,"average_response_time_ms":0,"last_status_code":None,"parser_status":"unknown","last_event_count":0,"last_warning":None,"_dur":[]})
    for m in manifests:
        for s in m.get("source_results", []):
            x = state[s["source_id"]]
            x["last_status_code"] = s.get("status_code")
            x["parser_status"] = s.get("parser_status", "unknown")
            x["last_event_count"] = s.get("event_count", 0)
            if s.get("warnings"):
                x["last_warning"] = s["warnings"][-1]
            if s.get("duration_ms") is not None:
                x["_dur"].append(s.get("duration_ms",0))
            if s.get("success"):
                x["last_success"] = m.get("finished_at")
                x["consecutive_failures"] = 0
            else:
                x["last_failure"] = m.get("finished_at")
                x["consecutive_failures"] += 1
    for v in state.values():
        d=v.pop("_dur")
        v["average_response_time_ms"] = int(sum(d)/len(d)) if d else 0
    return dict(state)
