"""Exclusions and dependencies — the two ways a figure gets quietly wrong.

Every rule here was written after the same defect appeared twice: something is
removed from a published number without the removal being visible, so the
reader cannot tell an absence of outages from an absence of looking.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import Harness, at, lift

from transit_friction.events.aggregates import build_window_summary
from transit_friction.events.config import TuningParameters
from transit_friction.events.coverage import compute_coverage
from transit_friction.events.episodes import build_episodes, union_seconds
from transit_friction.events.identity import observation_id
from transit_friction.events.records import Observation
from transit_friction.events.store import arrow_schema

L1 = lift("L1")
WINDOW = (at(0), at(1440))


def _summary(harness: Harness, *, extra_observations=(), depends_on=("brokenlifts",)):
    observations = list(harness.observations) + list(extra_observations)
    coverages = {
        source: compute_coverage(observations, source, *WINDOW)
        for source in sorted({row.source_id for row in observations})
    }
    return build_window_summary(
        build_episodes(harness.transitions, as_of=WINDOW[1]),
        coverages,
        window_start=WINDOW[0],
        window_end=WINDOW[1],
        as_of=WINDOW[1],
        depends_on=depends_on,
    )


def _day(entities_at) -> Harness:
    harness = Harness()
    for step in range(0, 1440, 5):
        harness.poll(step, entities_at(step))
    return harness


# --- dependencies -----------------------------------------------------------


def _reference_observation():
    """One daily reference ingest — a static feed, not a polled source."""
    return Observation(
        observation_id=observation_id("vbb_gtfs", at(30), "g1"),
        run_id="g1",
        source_id="vbb_gtfs",
        attempted_at=at(30),
        observed_at=at(30),
        source_updated_at=at(29),
        outcome="ok",
        complete=True,
        source_current=True,
        trusted_for_resolution=True,
        gap_before_s=0,
    )


def test_an_unrelated_slow_source_does_not_null_the_metric():
    """The hazard that would have arrived with the first static feed.

    A once-daily source can never clear the 30-minute trust gap, so it scores
    coverage 0.0. Gating on every source in the ledger made one such row null
    every elevator figure on the dashboard.
    """
    harness = _day(lambda step: [L1] if 60 <= step < 300 else [])
    alone = _summary(harness)
    with_reference = _summary(harness, extra_observations=[_reference_observation()])

    assert alone["publishable"] is True
    assert with_reference["publishable"] is True
    assert with_reference["total_outage_hours"] == alone["total_outage_hours"]
    assert with_reference["coverage"]["vbb_gtfs"]["coverage_ratio"] == 0.0, (
        "the slow source is still reported, it just does not gate"
    )


def test_a_declared_dependency_without_coverage_is_not_publishable():
    """Silence about a source a metric needs is a missing denominator."""
    harness = _day(lambda step: [L1] if 60 <= step < 300 else [])
    summary = _summary(harness, depends_on=("brokenlifts", "bvg_traffic_news"))
    assert summary["publishable"] is False
    assert summary["total_outage_hours"] is None


def test_the_summary_names_what_it_depended_on():
    harness = _day(lambda step: [])
    summary = _summary(harness, extra_observations=[_reference_observation()])
    assert summary["data_quality"]["sources_used"] == ["brokenlifts"]
    assert summary["data_quality"]["sources_observed"] == ["brokenlifts", "vbb_gtfs"]


def test_no_dependencies_publishes_nothing():
    harness = _day(lambda step: [])
    summary = _summary(harness, depends_on=())
    assert summary["publishable"] is False


# --- station-hours are unions ----------------------------------------------


def test_lifts_out_together_at_one_station_count_once():
    """A station with four lifts out is not four times as inaccessible."""
    lifts = [lift(f"L{k}") for k in range(1, 5)]
    harness = _day(lambda step: lifts if 60 <= step < 300 else [])
    summary = _summary(harness)

    assert summary["total_outage_hours"] == pytest.approx(4.0, abs=0.2)
    assert summary["total_lift_outage_hours"] == pytest.approx(16.0, abs=0.5)
    assert summary["outage_hours_by_station"]["S1"] == pytest.approx(4.0, abs=0.2)
    assert summary["station_hours_are_unions"] is True


def test_lifts_out_at_different_stations_still_add_up():
    """The union must not over-correct: separate stations are separate hours."""
    lifts = [
        lift(f"L{k}", station_id=f"S{k}", station_name=f"Station {k}")
        for k in range(1, 5)
    ]
    harness = _day(lambda step: lifts if 60 <= step < 300 else [])
    summary = _summary(harness)
    assert summary["total_outage_hours"] == pytest.approx(16.0, abs=0.5)
    assert summary["total_lift_outage_hours"] == pytest.approx(16.0, abs=0.5)
    assert len(summary["outage_hours_by_station"]) == 4


def test_partially_overlapping_lifts_are_unioned_not_summed():
    def entities(step):
        out = []
        if 60 <= step < 240:
            out.append(lift("L1"))
        if 180 <= step < 360:
            out.append(lift("L2"))
        return out

    summary = _summary(_day(entities))
    # 60->360 minutes is five hours of station time; the lifts together are six.
    assert summary["total_outage_hours"] == pytest.approx(5.0, abs=0.3)
    assert summary["total_lift_outage_hours"] == pytest.approx(6.0, abs=0.3)


def test_union_seconds_handles_the_shapes_that_matter():
    a, b = at(0), at(60)
    assert union_seconds([]) == 0
    assert union_seconds([(a, b)]) == 3600
    assert union_seconds([(a, b), (a, b)]) == 3600
    assert union_seconds([(at(0), at(60)), (at(30), at(90))]) == 5400
    assert union_seconds([(at(0), at(60)), (at(120), at(180))]) == 7200
    assert union_seconds([(at(0), at(180)), (at(60), at(90))]) == 10800


# --- quarantine -------------------------------------------------------------


def test_one_bad_reading_does_not_delete_a_long_outage():
    """The exclusion that would have understated the record by weeks.

    Quality flags are unioned across an episode's transitions, so a single
    flapping-flagged reading during a long outage used to remove the whole
    episode from the headline.
    """
    harness = Harness()
    harness.poll(0, [])
    for step in range(5, 1440, 5):
        harness.poll(step, [L1])
    # Force the flag on without changing the episode's shape.
    episodes = build_episodes(harness.transitions, as_of=at(1440))
    flagged = [replace(episode, quality_flags=("flapping",)) for episode in episodes]
    coverages = {
        "brokenlifts": compute_coverage(harness.observations, "brokenlifts", *WINDOW)
    }
    summary = build_window_summary(
        flagged, coverages, window_start=WINDOW[0], window_end=WINDOW[1],
        as_of=WINDOW[1], depends_on=["brokenlifts"],
    )
    assert summary["data_quality"]["quarantined_flapping_episodes"] == 0
    assert summary["total_outage_hours"] > 20, (
        "a day-long outage must survive one flagged reading"
    )


def test_a_genuinely_intermittent_asset_is_quarantined_and_its_hours_reported():
    tuning = TuningParameters(confirm_close_n=1, confirm_close_s=0)
    harness = Harness(tuning=tuning)
    harness.poll(0, [])
    for step in range(1, 40):
        harness.poll(step * 20, [L1] if step % 2 else [])

    coverages = {
        "brokenlifts": compute_coverage(harness.observations, "brokenlifts", *WINDOW)
    }
    summary = build_window_summary(
        build_episodes(harness.transitions, as_of=WINDOW[1]),
        coverages, window_start=WINDOW[0], window_end=WINDOW[1],
        as_of=WINDOW[1], depends_on=["brokenlifts"], tuning=tuning,
    )
    quality = summary["data_quality"]
    assert quality["quarantined_flapping_episodes"] >= 1
    assert quality["quarantined_station_hours"] > 0, (
        "an exclusion that does not say what it removed is invisible"
    )
    assert "S1" in quality["quarantined_stations"]


# --- schema safety ----------------------------------------------------------


def test_an_unknown_table_has_no_schema():
    """Falling through to the observations schema would corrupt silently."""
    with pytest.raises(KeyError, match="no parquet schema"):
        arrow_schema("population")
