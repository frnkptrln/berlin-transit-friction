from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from transit_friction.config import STATE_DIR, SILVER_DIR

ACTIVE_EVENTS_PATH = STATE_DIR / "active_events.json"


def load_active_events() -> dict:
    if not ACTIVE_EVENTS_PATH.exists():
        return {}
    try:
        return json.loads(ACTIVE_EVENTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_active_events(events_dict: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_EVENTS_PATH.write_text(json.dumps(events_dict, indent=2, ensure_ascii=False), encoding="utf-8")


def append_resolved_events(resolved_events: list[dict], now: datetime):
    if not resolved_events:
        return
    month_str = now.strftime("%Y-%m")
    resolved_path = SILVER_DIR / "resolved_events" / f"{month_str}.jsonl"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with resolved_path.open("a", encoding="utf-8") as f:
        for ev in resolved_events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def process_lifecycle(source_id: str, new_events: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """
    Compare new events against active events for a specific source.
    Returns (active_events_for_source, resolved_events_for_source).
    Updates the global active_events.json file.
    """
    active_events = load_active_events()
    
    # We only want to reconcile events for the specific source being collected
    source_active = {eid: ev for eid, ev in active_events.items() if ev.get("source") == source_id}
    new_events_dict = {ev["event_id"]: ev for ev in new_events}
    
    resolved_events = []
    current_active_for_source = []

    # 1. Check for resolved events (in active, but not in new)
    for eid, ev in source_active.items():
        if eid not in new_events_dict:
            ev["event_state"] = "resolved"
            ev["resolved_at"] = now.isoformat()
            resolved_events.append(ev)
            del active_events[eid]
            
    # 2. Process new and ongoing events
    for eid, new_ev in new_events_dict.items():
        if eid in active_events:
            # Ongoing
            active = active_events[eid]
            active["last_seen_at"] = now.isoformat()
            active["event_state"] = "ongoing"
            # Update severity if changed
            if new_ev.get("severity") is not None:
                active["severity"] = new_ev["severity"]
            # Keep first_seen_at from original
            new_ev["first_seen_at"] = active.get("first_seen_at", new_ev["first_seen_at"])
            new_ev["event_state"] = "ongoing"
            active_events[eid] = active
            current_active_for_source.append(active)
        else:
            # New
            new_ev["first_seen_at"] = now.isoformat()
            new_ev["last_seen_at"] = now.isoformat()
            new_ev["event_state"] = "new"
            active_events[eid] = new_ev
            current_active_for_source.append(new_ev)

    save_active_events(active_events)
    append_resolved_events(resolved_events, now)
    
    return current_active_for_source, resolved_events
