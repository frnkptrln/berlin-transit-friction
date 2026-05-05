import pytest
pytest.importorskip("pydantic")
from datetime import datetime, timezone
from transit_friction.normalize.events import stable_event_id, classify_category, estimate_severity
from transit_friction.normalize.schema import FrictionEvent


def test_stable_event_id():
    t = datetime(2026,1,1,tzinfo=timezone.utc)
    a = stable_event_id("s","delay","U2","Alex","Delay",t)
    b = stable_event_id("s","delay","U2","Alex","Delay",t)
    assert a == b


def test_classify_category():
    assert classify_category("Train cancelled") == "cancellation"
    assert classify_category("10 min delay") == "delay"


def test_estimate_severity_range():
    v = estimate_severity("delay", "minor delay")
    assert 0 <= v <= 4


def test_friction_event_validation():
    ev = FrictionEvent(event_id="1", source="x", collected_at=datetime.now(timezone.utc), category="delay", severity=2, title="t", confidence=0.5)
    assert ev.event_id == "1"
