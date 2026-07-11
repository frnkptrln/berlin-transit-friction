from dataclasses import replace
from datetime import datetime, timedelta, timezone

from transit_friction.accessibility.aggregates import build_window_summary
from transit_friction.accessibility.lifecycle import ActiveOutage


START = datetime(2026, 7, 10, tzinfo=timezone.utc)


def outage(asset_id: str, station_id: str, start_hours: float, end_hours=None):
    first_seen = START + timedelta(hours=start_hours)
    return ActiveOutage(
        outage_id=f"outage-{asset_id}",
        asset_id=asset_id,
        station_id=station_id,
        station_name=f"Station {station_id}",
        status_text="Außer Betrieb",
        source_url="https://www.brokenlifts.org/",
        first_seen_at=first_seen,
        last_seen_at=first_seen,
        source_updated_at=first_seen,
        resolved_at=(START + timedelta(hours=end_hours)) if end_hours else None,
    )


def test_summary_uses_outage_hours_with_explicit_window():
    summary = build_window_summary(
        [
            outage("1", "A", 1, 3),
            outage("2", "A", 2, 5),
            outage("3", "B", 4),
        ],
        window_start=START,
        window_end=START + timedelta(hours=6),
    )

    assert summary["unit"] == "outage-hours"
    assert summary["total_outage_hours"] == 7.0
    assert summary["outage_hours_by_station"] == {"A": 5.0, "B": 2.0}
    assert summary["active_at_window_end"] == 1
