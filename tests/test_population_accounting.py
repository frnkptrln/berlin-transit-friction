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


# --- the partition ----------------------------------------------------------


def test_the_three_states_partition_the_denominator_exactly(archive):  # noqa: F811
    """The structural claim everything else rests on.

    If OUT, KNOWN_OK and UNKNOWN do not add up to the denominator, the interval
    is not an interval — it is two unrelated numbers.
    """
    for outages, kwargs in [
        ({}, {}),
        ({ALEX: (8 * 60, 17 * 60)}, {}),
        ({ALEX: (0, 1440), GESUND: (0, 1440)}, {}),
        (
            {ALEX: (8 * 60, 17 * 60)},
            {
                "monitored_stations": {
                    "de:11000:900100003", "de:11000:900007102", "de:12054:900230999"
                },
                "roster_complete": True,
            },
        ),
    ]:
        result = _account(archive, outages, **kwargs)
        total = result.out_seconds + result.known_ok_seconds + result.unknown_seconds
        assert total == pytest.approx(result.denominator_seconds), (
            f"states do not partition for {outages} / {kwargs}"
        )


def test_an_outage_outside_service_hours_cannot_exceed_its_own_station(archive):  # noqa: F811
    """The numerator sits inside its own denominator, station by station."""
    result = _account(archive, {ALEX: (0, 1440)})
    alex_hours = result.out_seconds / 3600
    assert alex_hours <= 18.0 + 0.01, "Alexanderplatz runs 05:00 to 23:00"


# --- multi-source monitoring ------------------------------------------------


def test_a_fault_list_can_never_make_a_station_known_good(archive):  # noqa: F811
    """Absence from a broken-lifts page is a default, not an observation."""
    from transit_friction.population.monitoring import Monitoring, from_fault_listings

    population = derive_population(archive)
    monitoring = Monitoring(
        sources={
            "brokenlifts": from_fault_listings(
                "brokenlifts",
                {"de:11000:900100003", "de:11000:900007102", "de:12054:900230999"},
                WE,
            )
        }
    )
    result = account(
        population=population, crosswalk=build_crosswalk(population, [ALEX]),
        episodes=_episodes({ALEX: (8 * 60, 17 * 60)}), days=[DAY],
        window_start=WS, window_end=WE, as_of=WE, monitoring=monitoring,
        population_id="test",
    )
    assert result.monitored_station_count == 3, "it does cover them"
    assert result.known_ok_seconds == 0, "and still cannot vouch for any of them"
    assert result.share_high == 1.0
    assert CAUSE_ROSTER_INCOMPLETE in result.unknown_by_cause


def test_an_inventory_source_can(archive):  # noqa: F811
    from transit_friction.population.monitoring import Monitoring, from_roster

    population = derive_population(archive)
    monitoring = Monitoring(
        sources={
            "inventory": from_roster(
                "inventory",
                {"de:11000:900100003", "de:11000:900007102", "de:12054:900230999"},
                WE,
            )
        }
    )
    result = account(
        population=population, crosswalk=build_crosswalk(population, [ALEX]),
        episodes=_episodes({ALEX: (8 * 60, 17 * 60)}), days=[DAY],
        window_start=WS, window_end=WE, as_of=WE, monitoring=monitoring,
        population_id="test",
    )
    assert result.known_ok_seconds > 0
    assert result.share_high < 1.0
    assert result.point_estimate() is not None


def test_two_sources_combine_without_being_blended(archive):  # noqa: F811
    """One inventory, one fault list. Only the inventory's stations are vouched for."""
    from transit_friction.population.monitoring import (
        Monitoring, from_fault_listings, from_roster,
    )

    population = derive_population(archive)
    monitoring = Monitoring(
        sources={
            "db": from_roster("db", {"de:11000:900007102"}, WE),
            "brokenlifts": from_fault_listings(
                "brokenlifts", {"de:11000:900100003", "de:12054:900230999"}, WE
            ),
        }
    )
    result = account(
        population=population, crosswalk=build_crosswalk(population, [ALEX]),
        episodes=_episodes({ALEX: (8 * 60, 17 * 60)}), days=[DAY],
        window_start=WS, window_end=WE, as_of=WE, monitoring=monitoring,
        population_id="test",
    )
    assert result.monitored_station_count == 3
    assert 0 < result.known_ok_seconds
    assert CAUSE_ROSTER_INCOMPLETE in result.unknown_by_cause, (
        "the two fault-list stations are covered but not known-good"
    )
    detail = result.to_dict()["monitoring"]
    assert detail["stations_by_source"] == {"brokenlifts": 2, "db": 1}
    assert detail["sources_with_complete_roster"] == ["db"]


def test_expired_evidence_becomes_unknown_not_a_silent_zero(archive):  # noqa: F811
    """A source quietly dropping an operator must not read as improvement."""
    from datetime import timedelta as _td

    from transit_friction.population.monitoring import Monitoring, from_roster

    population = derive_population(archive)
    monitoring = Monitoring(
        sources={
            "db": from_roster(
                "db", {"de:11000:900007102"}, WE - _td(days=200)
            )
        }
    )
    result = account(
        population=population, crosswalk=build_crosswalk(population, []),
        episodes=[], days=[DAY], window_start=WS, window_end=WE, as_of=WE,
        monitoring=monitoring, population_id="test",
    )
    assert result.monitored_station_count == 0
    assert result.known_ok_seconds == 0
    assert "monitoring_stale" in result.unknown_by_cause
    assert result.share_high == 1.0


def test_coverage_is_exactly_what_narrows_the_interval(archive):  # noqa: F811
    """The case for measuring every elevator, as an assertion.

    The floor never moves — it is what we positively observed. What coverage
    buys is the ceiling: each station an inventory source vouches for removes
    its service hours from UNKNOWN. With none, the interval spans everything;
    with all of them, it closes and a point estimate becomes expressible.
    """
    from transit_friction.population.monitoring import (
        Monitoring, from_fault_listings, from_roster,
    )

    population = derive_population(archive)
    equipped = sorted(population.equipped_keys)
    episodes = _episodes({ALEX: (8 * 60, 17 * 60)})
    crosswalk = build_crosswalk(population, [ALEX])

    def band(monitoring):
        result = account(
            population=population, crosswalk=crosswalk, episodes=episodes,
            days=[DAY], window_start=WS, window_end=WE, as_of=WE,
            monitoring=monitoring, population_id="test",
        )
        return result.share_low, result.share_high, result.point_estimate()

    none_lo, none_hi, none_pt = band(
        Monitoring(sources={"bl": from_fault_listings("bl", {"de:11000:900100003"}, WE)})
    )
    some_lo, some_hi, some_pt = band(
        Monitoring(sources={
            "bl": from_fault_listings("bl", {"de:11000:900100003"}, WE),
            "inv": from_roster("inv", {equipped[0]}, WE),
        })
    )
    all_lo, all_hi, all_pt = band(
        Monitoring(sources={"inv": from_roster("inv", set(equipped), WE)})
    )

    assert none_lo == some_lo == all_lo, "the floor is what we saw; coverage cannot move it"
    assert none_hi == 1.0
    assert some_hi < none_hi, "each vouched-for station lowers the ceiling"
    assert all_hi < some_hi
    assert none_pt is None and some_pt is None
    assert all_pt is not None, "full coverage is what makes a point estimate expressible"
