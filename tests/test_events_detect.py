"""The detector's promises, one test per documented guarantee."""

from __future__ import annotations

import pytest
from conftest import Harness, at, lift

from transit_friction.events.config import TuningParameters
from transit_friction.events.records import Transition
from transit_friction.events.schema import (
    CERTAINTY_BOUNDED,
    CERTAINTY_OBSERVED,
    EVIDENCE_COVERAGE_RESTORED,
    EVIDENCE_FLAP_CORRECTION,
    EVIDENCE_SOURCE_DEGRADED,
    EVIDENCE_SOURCE_STALE,
    FLAG_FLAPPING,
    FLAG_LONG_GAP,
    STATE_IMPAIRED,
    STATE_OK,
    STATE_UNKNOWN,
)

L1 = lift()


# --- opening ----------------------------------------------------------------


def test_first_complete_snapshot_opens_an_outage(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    assert harness.types == ["opened"]
    assert harness.only_state().state == STATE_IMPAIRED


def test_repeated_observation_does_not_produce_a_new_event(harness: Harness):
    """The defect that invalidated the legacy dataset.

    A three-day outage polled every five minutes is two rows, not 864.
    """
    harness.poll(0, [])
    for step in range(1, 289):
        harness.poll(step * 5, [L1])
    assert harness.types == ["opened"]
    assert len(harness.observations) == 289


def test_open_is_dated_as_an_interval(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    row = harness.transitions[0]
    assert row.t_earliest == at(0)
    assert row.t_latest == at(5)
    assert row.bracket_seconds == 300
    assert row.certainty == CERTAINTY_BOUNDED


def test_source_supplied_change_time_collapses_uncertainty(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [lift(t_source=at(2))])
    row = harness.transitions[0]
    assert row.certainty == CERTAINTY_OBSERVED
    assert row.t_source == at(2)


def test_incomplete_snapshot_cannot_open(harness: Harness):
    """A partial list says nothing about what is missing from it."""
    harness.poll(0, [L1], complete=False)
    assert harness.transitions == []
    assert harness.states == {}


# --- closing ----------------------------------------------------------------


def test_close_requires_confirmation_and_dwell(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    assert harness.types == ["opened"], "one absence is not enough"
    harness.poll(15, [])
    assert harness.types == ["opened"], "dwell time not yet satisfied"
    harness.poll(20, [])
    assert harness.types == ["opened", "closed"]


def test_close_is_dated_at_the_first_absence_not_the_confirmation(harness: Harness):
    """Debounce delays writing, never dating."""
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    harness.poll(15, [])
    harness.poll(20, [])
    closed = harness.transitions[-1]
    assert closed.t_latest == at(10)
    assert closed.t_earliest == at(5)
    assert "debounced" in closed.quality_flags


@pytest.mark.parametrize(
    "kwargs",
    [
        {"outcome": "http_error"},
        {"outcome": "timeout"},
        {"outcome": "parse_error"},
        {"complete": False},
    ],
)
def test_a_degraded_snapshot_can_never_close_an_outage(harness: Harness, kwargs):
    """The invariant the whole architecture exists to protect."""
    harness.poll(0, [])
    harness.poll(5, [L1])
    for step in range(2, 8):
        harness.poll(5 * step, [], **kwargs)
    assert harness.types == ["opened"]
    assert harness.only_state().state in {STATE_IMPAIRED, STATE_UNKNOWN}
    assert not any(row.to_state == STATE_OK for row in harness.transitions)


def test_a_stale_source_cannot_close_an_outage(harness: Harness):
    """A feed whose own clock stopped looks exactly like "nothing is wrong"."""
    frozen = at(-90)
    harness.poll(0, [L1], source_updated_at=frozen)
    assert harness.types == ["opened"]
    for step in range(1, 6):
        harness.poll(5 * step, [], source_updated_at=frozen)
    assert harness.types == ["opened"]
    assert harness.observations[-1].outcome == "stale"
    assert harness.observations[-1].trusted_for_resolution is False


def test_closing_evidence_cannot_be_forged():
    """Even a hand-built row is rejected at construction."""
    with pytest.raises(ValueError, match="cannot close an outage"):
        Transition(
            transition_uid="x",
            entity_uid="e",
            entity_type="elevator",
            source_id="brokenlifts",
            source_native_id="L1",
            transition_type="closed",
            to_state=STATE_OK,
            t_earliest=at(0),
            t_latest=at(5),
            certainty=CERTAINTY_BOUNDED,
            evidence=EVIDENCE_SOURCE_DEGRADED,
            observation_id="o",
            gap_before_s=300,
            episode_id="ep",
        )


# --- gaps -------------------------------------------------------------------


def test_a_long_gap_makes_state_unknown_not_ok(harness: Harness):
    """A gap suspends knowledge; it never supplies good news."""
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    assert harness.types == ["opened", "unknown_entered"]
    row = harness.transitions[-1]
    assert row.to_state == STATE_UNKNOWN
    assert row.evidence == EVIDENCE_SOURCE_DEGRADED
    assert row.from_state == STATE_IMPAIRED


def test_a_short_failure_does_not_flip_state(harness: Harness):
    """Within tolerance we simply wait rather than thrashing."""
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [], outcome="timeout")
    assert harness.types == ["opened"]
    assert harness.only_state().state == STATE_IMPAIRED


def test_gap_evidence_names_the_reason(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [L1], complete=False)
    assert harness.transitions[-1].evidence == EVIDENCE_SOURCE_DEGRADED

    other = Harness()
    other.poll(0, [])
    other.poll(5, [L1])
    other.poll(200, [L1], source_updated_at=at(4))
    assert other.transitions[-1].evidence == EVIDENCE_SOURCE_STALE


def test_regaining_sight_records_what_was_found(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    harness.poll(125, [L1])
    assert harness.types == ["opened", "unknown_entered", "unknown_exited"]
    restored = harness.transitions[-1]
    assert restored.to_state == STATE_IMPAIRED
    assert restored.evidence == EVIDENCE_COVERAGE_RESTORED
    assert restored.episode_id == harness.transitions[0].episode_id, (
        "the outage never ended, so the episode continues"
    )


def test_recovery_finding_the_outage_gone_still_debounces(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    harness.poll(125, [])
    harness.poll(130, [])
    harness.poll(135, [])
    assert harness.types[-1] == "unknown_exited"
    assert harness.transitions[-1].to_state == STATE_OK
    assert harness.only_state().state == STATE_OK


def test_a_gap_widens_the_bracket_of_what_follows(harness: Harness):
    """After two hours blind, the change is known only to two hours."""
    harness.poll(0, [])
    harness.poll(120, [L1])
    row = harness.transitions[0]
    assert row.bracket_seconds == 7200
    assert FLAG_LONG_GAP in row.quality_flags
    assert row.gap_before_s == 7200


# --- flapping ---------------------------------------------------------------


def test_alternating_source_does_not_manufacture_outages(harness: Harness):
    """The classic flap: present, absent, present, absent..."""
    harness.poll(0, [])
    harness.poll(5, [L1])
    for step in range(2, 20):
        harness.poll(5 * step, [] if step % 2 == 0 else [L1])
    assert harness.types == ["opened"], harness.types
    assert sum(harness.suppressed.values()) > 0


def test_reopen_inside_the_window_continues_the_episode(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    harness.poll(15, [])
    harness.poll(20, [])
    assert harness.types == ["opened", "closed"]
    harness.poll(25, [L1])
    assert harness.types == ["opened", "closed", "reopened"]
    reopened = harness.transitions[-1]
    assert reopened.evidence == EVIDENCE_FLAP_CORRECTION
    assert reopened.episode_id == harness.transitions[0].episode_id


def test_reopen_outside_the_window_is_a_new_episode(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    harness.poll(15, [])
    harness.poll(20, [])
    harness.poll(70, [L1])
    assert harness.types == ["opened", "closed", "opened"]
    assert harness.transitions[-1].episode_id != harness.transitions[0].episode_id


def test_persistent_flapping_is_quarantined(harness: Harness):
    """Six state changes in a day is a source problem, not an elevator."""
    tuning = TuningParameters(confirm_close_n=1, confirm_close_s=0)
    flappy = Harness(tuning=tuning)
    flappy.poll(0, [])
    for step in range(1, 20):
        flappy.poll(60 * step, [L1] if step % 2 else [])
    flags = [row.quality_flags for row in flappy.transitions]
    assert any(FLAG_FLAPPING in item for item in flags)
    assert FLAG_FLAPPING in flappy.transitions[-1].quality_flags


def test_suppressed_flap_is_counted_not_hidden(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [])
    harness.poll(15, [L1])
    assert harness.types == ["opened"]
    assert sum(harness.suppressed.values()) == 1


# --- attributes -------------------------------------------------------------


def test_whitelisted_attribute_change_is_recorded(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [lift(status_text="out of service")])
    harness.poll(10, [lift(status_text="under repair")])
    assert harness.types == ["opened", "attributes_changed"]
    assert harness.transitions[-1].status_text == "under repair"


def test_unchanged_attributes_produce_nothing(harness: Harness):
    harness.poll(0, [])
    harness.poll(5, [lift(status_text="out of service")])
    harness.poll(10, [lift(status_text="out of service")])
    assert harness.types == ["opened"]


# --- observations -----------------------------------------------------------


def test_an_observation_is_written_even_when_the_fetch_fails(harness: Harness):
    """Absence of evidence is recorded as such."""
    harness.poll(0, [], outcome="http_error")
    harness.poll(5, [], outcome="timeout")
    assert len(harness.observations) == 2
    assert [row.outcome for row in harness.observations] == ["http_error", "timeout"]
    assert not any(row.trusted_for_resolution for row in harness.observations)


def test_observation_records_the_gap_it_followed(harness: Harness):
    harness.poll(0, [])
    harness.poll(120, [])
    assert harness.observations[-1].gap_before_s == 7200


def test_incomplete_snapshot_is_never_trusted(harness: Harness):
    harness.poll(0, [L1], complete=False)
    observation = harness.observations[-1]
    assert observation.outcome == "incomplete"
    assert observation.trusted_for_resolution is False


def test_identical_payload_is_noted(harness: Harness):
    harness.poll(0, [], payload_sha256="abc")
    result = harness.poll(5, [], payload_sha256="abc")
    assert any("identical" in note for note in result.observation.warnings)


# --- multiple entities ------------------------------------------------------


def test_entities_are_tracked_independently(harness: Harness):
    a, b = lift("L1"), lift("L2", station_id="S2", station_name="Zoo")
    harness.poll(0, [])
    harness.poll(5, [a])
    harness.poll(10, [a, b])
    harness.poll(15, [b])
    harness.poll(20, [b])
    harness.poll(25, [b])
    assert harness.types == ["opened", "opened", "closed"]
    closed = harness.transitions[-1]
    assert closed.source_native_id == "L1"
    assert len(harness.states) == 2
