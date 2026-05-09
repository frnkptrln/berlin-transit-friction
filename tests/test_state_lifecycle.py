from datetime import datetime, timezone
from transit_friction.normalize.state import process_lifecycle, load_active_events

def test_state_lifecycle(tmp_path, monkeypatch):
    # Mock paths
    import transit_friction.normalize.state as state_mod
    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state_mod, "SILVER_DIR", tmp_path / "silver")
    monkeypatch.setattr(state_mod, "ACTIVE_EVENTS_PATH", tmp_path / "state" / "active_events.json")

    now = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)
    
    # 1. First run, new event
    event1 = {"event_id": "123", "source": "test_src", "title": "Delay", "severity": 1, "first_seen_at": "old"}
    active, resolved = process_lifecycle("test_src", [event1], now)
    
    assert len(active) == 1
    assert active[0]["event_state"] == "new"
    assert active[0]["first_seen_at"] == now.isoformat()
    assert len(resolved) == 0
    
    # 2. Second run, same event
    now2 = datetime(2026, 5, 9, 12, 15, 0, tzinfo=timezone.utc)
    event1_updated = {"event_id": "123", "source": "test_src", "title": "Delay", "severity": 2, "first_seen_at": "ignore_me"}
    active, resolved = process_lifecycle("test_src", [event1_updated], now2)
    
    assert len(active) == 1
    assert active[0]["event_state"] == "ongoing"
    assert active[0]["severity"] == 2
    assert active[0]["first_seen_at"] == now.isoformat() # kept original
    assert active[0]["last_seen_at"] == now2.isoformat()
    assert len(resolved) == 0

    # 3. Third run, event missing (resolved)
    now3 = datetime(2026, 5, 9, 12, 30, 0, tzinfo=timezone.utc)
    active, resolved = process_lifecycle("test_src", [], now3)
    
    assert len(active) == 0
    assert len(resolved) == 1
    assert resolved[0]["event_state"] == "resolved"
    assert resolved[0]["resolved_at"] == now3.isoformat()
