from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from scripts.collect_snapshot import _collect_departure_events


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
