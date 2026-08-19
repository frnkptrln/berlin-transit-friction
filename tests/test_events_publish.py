"""Publishing keeps the null-versus-zero distinction and announces restatements."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from conftest import Harness, lift

from transit_friction.events.aggregates import build_window_summary, local_day_window
from transit_friction.events.coverage import compute_coverage
from transit_friction.events.episodes import build_episodes
from transit_friction.events.publish import (
    daily_metrics_path,
    site_projection,
    to_metric_rows,
    write_daily_metrics,
)
from transit_friction.events.store import read_parquet

L1 = lift()
DAY = date(2026, 8, 19)


def _summary(*, watched: bool = True, broken: bool = True) -> dict:
    window_start, window_end = local_day_window(DAY)
    harness = Harness()
    minutes = int((window_end - window_start).total_seconds() // 60)
    offset = (window_start - datetime(2026, 8, 19, tzinfo=timezone.utc)).total_seconds()
    base = offset / 60
    for step in range(0, minutes, 5):
        if not watched and 240 <= step < 900:
            continue
        harness.poll(base + step, [L1] if broken and 60 <= step < 300 else [])

    coverage = compute_coverage(
        harness.observations, "brokenlifts", window_start, window_end
    )
    return build_window_summary(
        build_episodes(harness.transitions, as_of=window_end),
        {"brokenlifts": coverage},
        window_start=window_start,
        window_end=window_end,
        as_of=window_end,
    )


def test_rows_carry_their_window_unit_and_coverage():
    rows = to_metric_rows(_summary(), local_date=DAY.isoformat())
    totals = [row for row in rows if row["metric"] == "total_outage_hours"]
    assert len(totals) == 1
    assert totals[0]["unit"] == "outage-hours"
    assert totals[0]["window_hours"] == 24.0
    assert totals[0]["value"] == pytest.approx(4.0, abs=0.2)
    assert totals[0]["publishable"] is True


def test_an_unwatched_window_publishes_nulls_but_still_reports_coverage():
    rows = to_metric_rows(_summary(watched=False), local_date=DAY.isoformat())
    by_metric = {row["metric"]: row for row in rows}
    assert by_metric["total_outage_hours"]["value"] is None
    assert by_metric["episode_count"]["value"] is None
    assert by_metric["coverage_ratio"]["value"] is not None, (
        "coverage is a statement about us, not about Berlin, and is exactly "
        "what a reader needs when everything else is null"
    )
    assert by_metric["coverage_ratio"]["publishable"] is True


def test_a_value_cannot_be_published_below_the_threshold():
    from transit_friction.events.records import DailyMetric

    start, end = local_day_window(DAY)
    with pytest.raises(ValueError, match="coverage threshold"):
        DailyMetric(
            metric_uid="x",
            local_date=DAY.isoformat(),
            window_start=start,
            window_end=end,
            window_hours=24.0,
            metric="total_outage_hours",
            dimension="all",
            dimension_id="",
            unit="outage-hours",
            publishable=False,
            coverage_ratio=0.2,
            aggregate_revision=1,
            tuning_fingerprint="abc",
            value=3.0,
        )


def test_an_unchanged_rebuild_keeps_its_revision(tmp_path):
    rows = to_metric_rows(_summary(), local_date=DAY.isoformat())
    first = write_daily_metrics(rows, DAY, tmp_path)
    second = write_daily_metrics(rows, DAY, tmp_path)
    assert first["aggregate_revision"] == 1 and first["changed"] is True
    assert second["aggregate_revision"] == 1 and second["changed"] is False


def test_a_changed_rebuild_announces_itself(tmp_path):
    write_daily_metrics(
        to_metric_rows(_summary(), local_date=DAY.isoformat()), DAY, tmp_path
    )
    changed = write_daily_metrics(
        to_metric_rows(_summary(broken=False), local_date=DAY.isoformat()),
        DAY,
        tmp_path,
        reason="parser correction",
    )
    assert changed["aggregate_revision"] == 2
    assert changed["reason"] == "parser correction"
    stored = read_parquet(daily_metrics_path(tmp_path, DAY))
    assert {row["aggregate_revision"] for row in stored} == {2}


def test_build_metadata_alone_does_not_bump_the_revision(tmp_path):
    early = to_metric_rows(
        _summary(), local_date=DAY.isoformat(), built_at=datetime(2026, 8, 20, tzinfo=timezone.utc)
    )
    later = to_metric_rows(
        _summary(), local_date=DAY.isoformat(), built_at=datetime(2026, 8, 21, tzinfo=timezone.utc)
    )
    write_daily_metrics(early, DAY, tmp_path)
    assert write_daily_metrics(later, DAY, tmp_path)["changed"] is False


def test_the_site_projection_explains_its_nulls():
    projection = site_projection(
        [
            ("2026-08-18", _summary()),
            ("2026-08-19", _summary(watched=False)),
        ]
    )
    assert projection["days_published"] == 1
    assert projection["days_withheld"] == 1
    assert "does not mean zero" in projection["note"]
    withheld = projection["days"][1]
    assert withheld["total_outage_hours"] is None
    assert withheld["coverage"]["brokenlifts"] < 0.9


def test_station_totals_exclude_days_that_were_not_measured():
    """A day we could not measure must not quietly lower a station's total."""
    watched = _summary()
    blind = _summary(watched=False)
    projection = site_projection([("2026-08-18", watched), ("2026-08-19", blind)])

    assert len(projection["stations"]) == 1
    station = projection["stations"][0]
    assert station["station_id"] == "S1"
    assert station["station_name"] == "Alexanderplatz"
    only_watched = site_projection([("2026-08-18", watched)])["stations"][0]
    assert station["outage_hours"] == only_watched["outage_hours"]
    assert "published days only" in projection["stations_note"]


def test_stations_are_ordered_by_hours():
    watched = _summary()
    projection = site_projection([("2026-08-18", watched)])
    hours = [item["outage_hours"] for item in projection["stations"]]
    assert hours == sorted(hours, reverse=True)


def test_the_projection_carries_the_bounds():
    projection = site_projection([("2026-08-18", _summary())])
    day = projection["days"][0]
    assert day["total_outage_hours_min"] <= day["total_outage_hours"]
    assert day["total_outage_hours"] <= day["total_outage_hours_max"]
