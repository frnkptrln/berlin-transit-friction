from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts.collect_snapshot import _collect_departure_events, _fallback_departures_from_silver


def test_collect_departure_events_uses_delay_when_no_remarks():
    now = datetime.now(timezone.utc)
    departures = [
        {
            "line": {"name": "S1"},
            "stop": {"name": "Berlin Hbf"},
            "delay": 420,
            "cancelled": False,
            "remarks": [],
        }
    ]
    events, sightings = _collect_departure_events("vbb_transport_rest", departures, now)
    assert len(events) == 1
    assert len(sightings) == 1
    assert events[0]["category"] == "delay"
    assert sightings[0]["reason"] == "delay_field"


def test_collect_departure_events_cancellation_overrides_category():
    now = datetime.now(timezone.utc)
    departures = [
        {
            "line": {"name": "U8"},
            "stop": {"name": "Alexanderplatz"},
            "delay": 0,
            "cancelled": True,
            "remarks": [{"text": "Betrieblich bedingt"}],
        }
    ]
    events, sightings = _collect_departure_events("bvg_transport_rest", departures, now)
    assert len(events) == 1
    assert len(sightings) == 1
    assert events[0]["category"] == "cancellation"
    assert sightings[0]["reason"] == "cancelled_field"


def test_fallback_departures_from_silver_reads_today_file(tmp_path, monkeypatch):
    from scripts import collect_snapshot as mod
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    p = tmp_path / "data/silver/departure_observations/2026-05-20.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('\n'.join([
        '{"line_name":"S3","stop_name":"Hbf","delay_seconds":360,"cancelled":false,"remarks":[]}',
        'not-json',
        '{"line_name":"U2","stop_name":"Alex","delay_seconds":0,"cancelled":true,"remarks":[{"text":"x"}]}'
    ]), encoding="utf-8")

    deps = _fallback_departures_from_silver(now)
    assert len(deps) == 2
    assert deps[0]["line"]["name"] == "S3"
    assert deps[1]["cancelled"] is True
