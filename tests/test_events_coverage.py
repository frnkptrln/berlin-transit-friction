"""Zero and null are different values with different renderings."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import Harness, at, lift

from transit_friction.events.coverage import compute_coverage, value_or_null
from transit_friction.events.episodes import build_episodes

L1 = lift()
DAY_START = at(0)
DAY_END = at(1440)


def _polled_all_day(gap_hours: tuple[int, int] | None = None) -> Harness:
    harness = Harness()
    for step in range(0, 1440, 5):
        hour = step // 60
        if gap_hours and gap_hours[0] <= hour < gap_hours[1]:
            continue
        harness.poll(step, [])
    return harness


def test_a_watched_day_with_nothing_wrong_reports_zero():
    harness = _polled_all_day()
    coverage = compute_coverage(harness.observations, "brokenlifts", DAY_START, DAY_END)
    assert coverage.coverage_ratio == pytest.approx(1.0)
    assert coverage.gaps == ()
    assert value_or_null(0, coverage) == 0


def test_an_unwatched_day_reports_null_not_zero():
    coverage = compute_coverage([], "brokenlifts", DAY_START, DAY_END)
    assert coverage.coverage_ratio == 0.0
    assert value_or_null(0, coverage) is None
    assert coverage.publishable() is False


def test_a_partly_watched_day_is_not_publishable():
    harness = _polled_all_day(gap_hours=(9, 17))
    coverage = compute_coverage(harness.observations, "brokenlifts", DAY_START, DAY_END)
    assert coverage.coverage_ratio == pytest.approx(2 / 3, abs=0.01)
    assert coverage.longest_gap_seconds > 8 * 3600 - 1
    assert value_or_null(3, coverage) is None


def test_failed_polls_do_not_count_as_coverage():
    """Attempting is not observing."""
    harness = Harness()
    for step in range(0, 1440, 5):
        harness.poll(step, [], outcome="http_error")
    coverage = compute_coverage(harness.observations, "brokenlifts", DAY_START, DAY_END)
    assert coverage.attempts == 288
    assert coverage.trusted_attempts == 0
    assert coverage.coverage_ratio == 0.0


def test_incomplete_polls_do_not_count_as_coverage():
    harness = Harness()
    for step in range(0, 1440, 5):
        harness.poll(step, [], complete=False)
    coverage = compute_coverage(harness.observations, "brokenlifts", DAY_START, DAY_END)
    assert coverage.coverage_ratio == 0.0


def test_coverage_is_computed_per_source():
    harness = Harness()
    harness.poll(0, [])
    coverage = compute_coverage(
        harness.observations, "bvg_traffic_news", DAY_START, DAY_END
    )
    assert coverage.coverage_ratio == 0.0, "another source's polls prove nothing"


def test_an_observation_before_the_window_anchors_its_start():
    harness = Harness()
    harness.poll(-10, [])
    for step in range(0, 1440, 5):
        harness.poll(step, [])
    coverage = compute_coverage(harness.observations, "brokenlifts", DAY_START, DAY_END)
    assert coverage.coverage_ratio == pytest.approx(1.0)


def test_entity_unknown_time_agrees_with_source_gap_time():
    """One threshold, two consequences — they must not drift apart."""
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    harness.poll(180, [L1])
    for step in range(185, 400, 5):
        harness.poll(step, [L1])

    episode = build_episodes(harness.transitions, as_of=at(400))[0]
    coverage = compute_coverage(
        harness.observations, "brokenlifts", at(0), at(400)
    )
    assert episode.unknown_seconds == coverage.gap_seconds


def test_window_must_be_ordered():
    with pytest.raises(ValueError):
        compute_coverage([], "brokenlifts", DAY_END, DAY_START)


def test_coverage_dict_states_its_window_and_unit():
    harness = _polled_all_day(gap_hours=(2, 4))
    payload = compute_coverage(
        harness.observations, "brokenlifts", DAY_START, DAY_END
    ).to_dict()
    assert payload["window_hours"] == 24.0
    assert len(payload["gaps"]) == 1
    assert payload["gaps"][0]["seconds"] == pytest.approx(2 * 3600, abs=310)


def test_publishing_threshold_sits_where_the_tuning_says():
    """A two-hour gap still publishes; a three-hour one does not."""
    small = compute_coverage(
        _polled_all_day(gap_hours=(2, 4)).observations,
        "brokenlifts",
        DAY_START,
        DAY_END,
    )
    large = compute_coverage(
        _polled_all_day(gap_hours=(2, 5)).observations,
        "brokenlifts",
        DAY_START,
        DAY_END,
    )
    assert small.coverage_ratio > 0.9 and small.publishable() is True
    assert large.coverage_ratio < 0.9 and large.publishable() is False
    assert value_or_null(7, small) == 7
    assert value_or_null(7, large) is None


def test_a_dst_day_reports_its_real_length():
    """23- and 25-hour days must not be compared as if they were 24."""
    short_day = compute_coverage(
        [], "brokenlifts", DAY_START, DAY_START + timedelta(hours=23)
    ).to_dict()
    assert short_day["window_hours"] == 23.0
