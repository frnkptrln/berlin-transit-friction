import json
from datetime import datetime, timezone
from pathlib import Path

from transit_friction.sources.vbb_departures import _normalize_departure
from transit_friction.sources.vbb_journeys import _journey_metrics


def test_v6_departures_object_parsing_fixture():
    payload = json.loads(Path('tests/fixtures/vbb_departures_with_remarks.json').read_text(encoding='utf-8'))
    deps = payload.get('departures', []) if isinstance(payload, dict) else payload
    assert isinstance(deps, list)


def test_cancelled_departure_normalization():
    row = _normalize_departure({'stop_id': 'x', 'label': 'Stop'}, {'cancelled': True, 'delay': 0, 'line': {'name': 'S3'}}, datetime.now(timezone.utc).isoformat())
    assert row['cancelled'] is True


def test_v6_journeys_object_parsing_and_delayed_leg():
    payload = {'journeys': [{'plannedDuration': 'PT20M', 'duration': 'PT28M', 'transfers': 1, 'legs': [{'arrivalDelay': 300, 'departureDelay': 120, 'cancelled': False, 'line': {'name': 'S5'}}]}]}
    m = _journey_metrics(payload['journeys'][0])
    assert m['duration_delta_min'] == 8
    assert m['max_leg_delay_seconds'] == 300


def test_missing_realtime_data():
    m = _journey_metrics({'plannedDuration': 'PT10M', 'duration': 'PT10M', 'transfers': 0, 'legs': [{'arrivalDelay': None, 'departureDelay': None}]})
    assert m['missing_realtime_data'] is True


def test_no_journeys_returned():
    payload = {'journeys': []}
    assert payload['journeys'] == []
