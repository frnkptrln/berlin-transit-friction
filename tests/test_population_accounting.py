"""The interval, and why it is an interval.

These tests encode the one decision the whole denominator rests on: unobserved
station-time is bounded, never deleted and never withheld. Deleting it produces
a conditional mean that reads reassuringly; withholding it produces a blank page
that reads reassuringly. Both are the same error.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from test_population_frame import archive  # noqa: F401 - fixture reuse

from transit_friction.events.detect import ObservedEntity, SourceSnapshot, detect
from transit_friction.events.episodes import build_episodes
from transit_friction.population.accounting import (
    CAUSE_NOT_MONITORED,
    CAUSE_ROSTER_INCOMPLETE,
    account,
)
from transit_friction.population.crosswalk import build_crosswalk
from transit_friction.population.frame import derive_population

DAY = date(2026, 6, 8)
WS = datetime(2026, 6, 8, 0, 0, tzinfo=timezone.utc)
WE = WS + timedelta(days=1)
ALEX = "900100003"
GESUND = "900007102"


def _episodes(outages: dict[str, tuple[int, int]]):
    """Drive real snapshots through the detector so the episodes are real."""
    states, cursor, pending, transitions = {}, None, {}, []
    for step in range(0, 1440, 5):
        entities = tuple(
            ObservedEntity(
                source_native_id=f"L{station}",
                entity_type="elevator",
                station_id=station,
                station_name=station,
            )
            for station, (start, end) in outages.items()
            if start <= step < end
        )
        at = WS + timedelta(minutes=step)
        snapshot = SourceSnapshot(
            source_id="brokenlifts", run_id=f"r{step}", attempted_at=at,
            observed_at=at, source_updated_at=at - timedelta(minutes=1),
            outcome="ok", complete=True, entities=entities,
            advertised_count=len(entities),
        )
        result = detect(snapshot, states, cursor, pending)
        states, cursor, pending = result.states, result.cursor, result.pending
        transitions.extend(result.transitions)
    return build_episodes(transitions, as_of=WE)


def _account(archive, outages, **kwargs):  # noqa: F811
    population = derive_population(archive)
    episodes = _episodes(outages)
    seen = sorted({e.station_id for e in episodes if e.station_id})
    crosswalk = build_crosswalk(population, seen)
    monitored = {
        crosswalk.resolutions[i].station_key
        for i in seen
        if crosswalk.resolutions[i].matched
    }
    kwargs.setdefault("monitored_stations", monitored)
    return account(
        population=population, crosswalk=crosswalk, episodes=episodes,
        days=[DAY], window_start=WS, window_end=WE, as_of=WE,
        population_id="test", **kwargs,
    )


def test_the_floor_is_always_true_and_the_ceiling_bounds_it(archive):  # noqa: F811
    result = _account(archive, {ALEX: (8 * 60, 17 * 60)})
    assert 0 < result.share_low < result.share_high <= 1.0
    assert result.out_seconds > 0


def test_without_a_roster_nothing_is_known_to_be_fine(archive):  # noqa: F811
    """A station we have never seen reported on is not a station we know is fine.

    This is why the interval is uninformative today: it is the true state of
    knowledge, not a defect.
    """
    result = _account(archive, {ALEX: (8 * 60, 17 * 60)})
    assert result.known_ok_seconds == 0
    assert result.share_high == 1.0
    assert result.point_estimate() is None
    # With nothing known-good, every second that was not an outage is unknown,
    # so the interval spans everything above the floor. This identity is the
    # whole claim: p_hi = 1 and unknown = 1 - p_lo, exactly.
    assert result.unknown_share == pytest.approx(1 - result.share_low)


def test_unmonitored_stations_widen_the_interval_instead_of_vanishing(archive):  # noqa: F811
    """The alternative — dividing by the stations we can see — understates."""
    result = _account(archive, {ALEX: (8 * 60, 17 * 60)})
    assert result.equipped_station_count == 3
    assert result.monitored_station_count == 1
    assert result.unknown_by_cause[CAUSE_NOT_MONITORED] > 0
    assert CAUSE_ROSTER_INCOMPLETE in result.unknown_by_cause


def test_a_complete_roster_lets_time_be_known_good(archive):  # noqa: F811
    result = _account(
        archive, {ALEX: (8 * 60, 17 * 60)},
        monitored_stations={
            "de:11000:900100003", "de:11000:900007102", "de:12054:900230999"
        },
        roster_complete=True,
    )
    assert result.known_ok_seconds > 0
    assert result.share_high < 1.0
    assert result.point_estimate() is not None


def test_the_point_estimate_lies_inside_the_interval(archive):  # noqa: F811
    result = _account(
        archive, {ALEX: (8 * 60, 17 * 60)},
        monitored_stations={
            "de:11000:900100003", "de:11000:900007102", "de:12054:900230999"
        },
        roster_complete=True,
    )
    point = result.point_estimate()
    assert result.share_low <= point <= result.share_high


def test_the_point_estimate_is_withheld_when_too_much_is_unknown(archive):  # noqa: F811
    result = _account(
        archive, {ALEX: (8 * 60, 17 * 60)},
        monitored_stations={"de:11000:900100003"},
        roster_complete=True,
    )
    assert result.unknown_share > 0.10
    assert result.point_estimate() is None


def test_a_quiet_fully_watched_window_reports_zero_not_nothing(archive):  # noqa: F811
    result = _account(
        archive, {},
        monitored_stations={
            "de:11000:900100003", "de:11000:900007102", "de:12054:900230999"
        },
        roster_complete=True,
    )
    assert result.out_seconds == 0
    assert result.share_low == 0.0
    assert result.point_estimate() == 0.0


def test_two_lifts_at_one_station_do_not_double_its_time(archive):  # noqa: F811
    one = _account(archive, {ALEX: (8 * 60, 17 * 60)})
    population = derive_population(archive)
    episodes = _episodes({ALEX: (8 * 60, 17 * 60)})
    doubled = episodes + [e for e in episodes]
    crosswalk = build_crosswalk(population, [ALEX])
    both = account(
        population=population, crosswalk=crosswalk, episodes=doubled, days=[DAY],
        window_start=WS, window_end=WE, as_of=WE, population_id="test",
        monitored_stations={"de:11000:900100003"},
    )
    assert both.out_seconds == pytest.approx(one.out_seconds)


def test_an_outage_at_an_unplaceable_station_never_lowers_the_rate(archive):  # noqa: F811
    """Discarding what we could not attribute is the most flattering error."""
    result = _account(archive, {"900555555": (8 * 60, 17 * 60)})
    assert result.out_seconds == 0, "it cannot enter a denominator it is not in"
    assert result.unmatched_source_ids == ("900555555",)
    assert result.match_rate == 0.0


def test_an_out_of_scope_station_is_reported_not_pooled(archive):  # noqa: F811
    result = _account(archive, {"900999001": (8 * 60, 17 * 60)})
    assert result.out_of_scope_source_ids == ("900999001",)
    assert result.unmatched_source_ids == ()


def test_out_time_can_never_exceed_the_denominator(archive):  # noqa: F811
    result = _account(archive, {ALEX: (0, 1440), GESUND: (0, 1440)})
    assert result.out_seconds <= result.denominator_seconds
    assert result.share_low <= 1.0


def test_the_published_shape_states_its_unit_and_its_population(archive):  # noqa: F811
    payload = _account(archive, {ALEX: (8 * 60, 17 * 60)}).to_dict()
    assert payload["unit"] == "share_of_frame_elevator_station_service_hours"
    assert payload["population_id"] == "test"
    assert payload["point_estimate"] is None
    assert payload["denominator_hours"] > 0
    assert payload["unknown_hours_by_cause"]
    assert payload["equipped_station_count"] == 3
    assert payload["stations_without_elevator_edge"] == 1


def test_out_hours_carry_their_bounds(archive):  # noqa: F811
    result = _account(archive, {ALEX: (8 * 60, 17 * 60)})
    assert result.out_seconds_min <= result.out_seconds <= result.out_seconds_max
