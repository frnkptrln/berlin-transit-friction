"""Window metrics state their unit, their coverage, and their uncertainty."""

from __future__ import annotations

import pytest
from conftest import Harness, at, lift

from transit_friction.events.aggregates import build_window_summary
from transit_friction.events.coverage import compute_coverage
from transit_friction.events.episodes import build_episodes

L1 = lift()
L2 = lift("L2", station_id="S2", station_name="Zoo")


def _watched_day(entities_by_step) -> Harness:
    harness = Harness()
    for step in range(0, 1440, 5):
        harness.poll(step, entities_by_step(step))
    return harness


def _summary(harness: Harness, **kwargs) -> dict:
    window_start, window_end = at(0), at(1440)
    coverage = compute_coverage(
        harness.observations, "brokenlifts", window_start, window_end
    )
    return build_window_summary(
        build_episodes(harness.transitions, as_of=window_end),
        {"brokenlifts": coverage},
        window_start=window_start,
        window_end=window_end,
        as_of=window_end,
        **kwargs,
    )


def test_the_unit_is_outage_hours_not_poll_counts():
    harness = _watched_day(lambda step: [L1] if 60 <= step < 300 else [])
    summary = _summary(harness)
    assert summary["unit"] == "outage-hours"
    assert summary["total_outage_hours"] == pytest.approx(4.0, abs=0.1)
    assert summary["episode_count"] == 1


def test_hours_are_attributed_to_the_station_that_was_observed():
    harness = _watched_day(
        lambda step: ([L1] if 60 <= step < 180 else []) + ([L2] if step < 120 else [])
    )
    summary = _summary(harness)
    hours = summary["outage_hours_by_station"]
    assert set(hours) == {"S1", "S2"}
    assert hours["S1"] == pytest.approx(2.0, abs=0.1)
    assert hours["S2"] == pytest.approx(2.0, abs=0.1)


def test_a_quiet_watched_day_reports_zero_not_null():
    """The first row of the table in docs/event-schema.md section 6.3."""
    harness = _watched_day(lambda step: [])
    summary = _summary(harness)
    assert summary["publishable"] is True
    assert summary["total_outage_hours"] == 0
    assert summary["episode_count"] == 0
    assert summary["outage_hours_by_station"] == {}


def test_an_unwatched_day_suppresses_every_value():
    harness = Harness()
    for step in range(0, 1440, 5):
        if 9 * 60 <= step < 20 * 60:
            continue
        harness.poll(step, [L1] if 60 <= step < 300 else [])
    summary = _summary(harness)
    assert summary["publishable"] is False
    assert summary["total_outage_hours"] is None
    assert summary["episode_count"] is None
    assert summary["coverage"]["brokenlifts"]["coverage_ratio"] < 0.9


def test_coverage_travels_with_the_number():
    harness = _watched_day(lambda step: [L1] if 60 <= step < 300 else [])
    summary = _summary(harness)
    assert summary["coverage"]["brokenlifts"]["window_hours"] == 24.0
    assert summary["coverage"]["brokenlifts"]["publishable"] is True
    assert summary["tuning_fingerprint"]


def test_episodes_with_blind_spots_are_counted_separately():
    """A one-hour blind spot still publishes, but the episode is marked."""
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    for step in range(10, 70, 5):
        harness.poll(step, [], outcome="http_error")
    for step in range(70, 1440, 5):
        harness.poll(step, [L1])
    summary = _summary(harness)
    assert summary["publishable"] is True
    assert summary["episodes_with_unobserved_time"] == 1
    assert summary["episode_count"] == 1


def test_a_dst_day_states_its_real_length():
    harness = _watched_day(lambda step: [])
    coverage = compute_coverage(harness.observations, "brokenlifts", at(0), at(1380))
    summary = build_window_summary(
        [],
        {"brokenlifts": coverage},
        window_start=at(0),
        window_end=at(1380),
    )
    assert summary["window_hours"] == 23.0
    assert summary["data_quality"]["sources_used"] == ["brokenlifts"]


def test_window_must_be_ordered():
    with pytest.raises(ValueError):
        build_window_summary([], {}, window_start=at(100), window_end=at(0))
