"""Episodes report ranges, because polling cannot produce a point."""

from __future__ import annotations

from conftest import Harness, at, lift

from transit_friction.events.episodes import build_episodes

L1 = lift()


def _poll_every_5_minutes(harness: Harness, present: range, until: int) -> Harness:
    for step in range(0, until + 1, 5):
        harness.poll(step, [L1] if step in present else [])
    return harness


def _closed_outage() -> Harness:
    """Impaired from the poll at 5 through the poll at 55, absent from 60."""
    return _poll_every_5_minutes(Harness(), range(5, 60, 5), 70)


def test_a_closed_outage_has_bounded_duration():
    episodes = build_episodes(_closed_outage().transitions)
    assert len(episodes) == 1
    episode = episodes[0]
    # opened in (0, 5], closed in (55, 60]  ->  between 50 and 60 minutes
    assert episode.duration_min_s == 50 * 60
    assert episode.duration_max_s == 60 * 60
    assert episode.duration_point_s == 55 * 60
    assert episode.certain is True
    assert episode.ongoing is False


def test_an_open_episode_reports_a_floor_not_a_guess():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    episodes = build_episodes(harness.transitions, as_of=at(125))
    episode = episodes[0]
    assert episode.ongoing is True
    assert episode.duration_max_s is None
    assert episode.duration_point_s is None
    assert episode.duration_min_s == 120 * 60


def test_time_spent_unobserved_is_reported():
    """An episode with a blind spot can never be a precise duration."""
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    harness.poll(180, [L1])
    episodes = build_episodes(harness.transitions, as_of=at(185))
    episode = episodes[0]
    # unknown from the last trustworthy look at 5 until sight returned at 180
    assert episode.unknown_seconds == 175 * 60
    assert episode.certain is False
    assert episode.ongoing is True


def test_a_gap_before_a_good_snapshot_still_counts_as_blind():
    """A successful poll does not retroactively make the gap observed."""
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [])
    harness.poll(125, [])
    harness.poll(130, [])
    episode = build_episodes(harness.transitions, as_of=at(135))[0]
    assert episode.unknown_seconds == 115 * 60
    assert episode.certain is False
    assert episode.ongoing is False


def test_a_flap_corrected_reopen_is_one_episode():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    harness.poll(15, [])
    harness.poll(20, [])
    harness.poll(25, [L1])
    episodes = build_episodes(harness.transitions, as_of=at(30))
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.reopen_count == 1
    assert episode.ongoing is True
    assert episode.internal_ok_seconds == 15 * 60


def test_separate_outages_stay_separate():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    harness.poll(15, [])
    harness.poll(20, [])
    harness.poll(70, [L1])
    episodes = build_episodes(harness.transitions, as_of=at(75))
    assert len(episodes) == 2
    assert [episode.ongoing for episode in episodes] == [False, True]


def test_overlap_uses_bracket_midpoints():
    episode = build_episodes(_closed_outage().transitions)[0]
    # midpoint of the opening bracket is 2.5 min, of the closing bracket 57.5 min
    assert episode.overlap_seconds(at(0), at(1440)) == 55 * 60
    assert episode.overlap_seconds(at(0), at(10)) == 7.5 * 60
    assert episode.overlap_seconds(at(100), at(200)) == 0


def test_episodes_carry_station_context_only_when_observed():
    episode = build_episodes(_closed_outage().transitions)[0]
    assert episode.station_id == "S1"
    assert episode.station_name == "Alexanderplatz"
    assert episode.line_id is None


def test_two_entities_produce_two_episodes():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1, lift("L2", station_id="S2", station_name="Zoo")])
    episodes = build_episodes(harness.transitions, as_of=at(10))
    assert len(episodes) == 2
    assert {episode.source_native_id for episode in episodes} == {"L1", "L2"}


def test_a_three_day_outage_is_two_rows_not_eight_hundred():
    """The whole thesis, as an assertion."""
    harness = Harness()
    harness.poll(0, [])
    for step in range(1, 865):
        harness.poll(step * 5, [L1])
    for step in range(865, 869):
        harness.poll(step * 5, [])
    assert len(harness.transitions) == 2
    assert len(build_episodes(harness.transitions)) == 1
