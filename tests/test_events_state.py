"""State is a fold over the ledger, not a file that can drift from it."""

from __future__ import annotations

import random

from conftest import Harness, at, lift

from transit_friction.events.config import DEFAULT_TUNING
from transit_friction.events.records import Transition
from transit_friction.events.schema import (
    CERTAINTY_BOUNDED,
    EVIDENCE_MANUAL_CORRECTION,
    STATE_IMPAIRED,
    STATE_OK,
    STATE_UNKNOWN,
    TRANSITION_CORRECTION,
)
from transit_friction.events.state import (
    effective_state,
    fold_cursors,
    fold_transitions,
    open_entities,
)

L1 = lift()


def _outage_history() -> Harness:
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(10, [lift(status_text="lift out")])
    return harness


def test_fold_reproduces_the_state_the_detector_carried():
    """A lost runner must converge on the same answer as a live one."""
    harness = _outage_history()
    rebuilt = fold_transitions(harness.transitions)
    assert set(rebuilt) == set(harness.states)
    for uid, state in rebuilt.items():
        assert state.state == harness.states[uid].state
        assert state.episode_id == harness.states[uid].episode_id
        assert state.since_latest == harness.states[uid].since_latest


def test_fold_survives_rows_that_share_a_timestamp():
    """Regression: ``unknown_entered`` is dated at the last trustworthy look.

    That is the same instant as the ``opened`` observed there, so folding on
    ``t_latest`` alone could apply the two in either order and leave the entity
    impaired when it should be unknown.
    """
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    opened, entered = harness.transitions[0], harness.transitions[1]
    assert opened.t_latest == entered.t_latest, "the collision this guards against"
    assert entered.recorded_at > opened.recorded_at

    for seed in range(20):
        shuffled = list(harness.transitions)
        random.Random(seed).shuffle(shuffled)
        folded = fold_transitions(shuffled)
        assert next(iter(folded.values())).state == STATE_UNKNOWN


def test_fold_is_independent_of_input_order():
    harness = _outage_history()
    shuffled = list(harness.transitions)
    random.Random(7).shuffle(shuffled)
    assert fold_transitions(shuffled) == fold_transitions(harness.transitions)


def test_fold_survives_replayed_rows():
    """Re-reading a partition twice must not double-count."""
    harness = _outage_history()
    doubled = list(harness.transitions) * 2
    assert fold_transitions(doubled) == fold_transitions(harness.transitions)


def test_a_correction_is_applied_without_erasing_the_mistake():
    harness = _outage_history()
    mistake = harness.transitions[0]
    correction = Transition(
        transition_uid="correction-1",
        entity_uid=mistake.entity_uid,
        entity_type=mistake.entity_type,
        source_id=mistake.source_id,
        source_native_id=mistake.source_native_id,
        transition_type=TRANSITION_CORRECTION,
        from_state=STATE_IMPAIRED,
        to_state=STATE_OK,
        t_earliest=at(30),
        t_latest=at(30),
        certainty=CERTAINTY_BOUNDED,
        evidence=EVIDENCE_MANUAL_CORRECTION,
        observation_id="manual",
        gap_before_s=0,
        episode_id=mistake.episode_id,
        corrects_transition_uid=mistake.transition_uid,
        correction_reason="parser misread the alert class",
    )
    ledger = harness.transitions + [correction]
    folded = fold_transitions(ledger)
    assert next(iter(folded.values())).state == STATE_OK
    assert mistake in ledger, "the ledger keeps the mistake"


def test_staleness_is_evaluated_when_reading_not_when_writing():
    """An entity nobody has looked at for two days is unknown, not impaired."""
    harness = _outage_history()
    state = harness.only_state()
    assert state.state == STATE_IMPAIRED
    assert effective_state(state, at(20)) == STATE_IMPAIRED
    assert effective_state(state, at(60 * 48)) == STATE_UNKNOWN


def test_open_entities_filters_to_impaired():
    harness = _outage_history()
    assert len(open_entities(harness.states)) == 1
    harness.poll(15, [])
    harness.poll(20, [])
    harness.poll(25, [])
    assert open_entities(harness.states) == {}


def test_cursor_fold_tracks_the_last_trustworthy_look():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [], outcome="http_error")
    harness.poll(10, [])
    cursors = fold_cursors(harness.observations)
    cursor = cursors["brokenlifts"]
    assert cursor.last_trusted_at == at(10)
    assert cursor.last_attempt_at == at(10)


def test_cursor_fold_ignores_untrusted_observations():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [], outcome="timeout")
    harness.poll(10, [], complete=False)
    cursor = fold_cursors(harness.observations)["brokenlifts"]
    assert cursor.last_trusted_at == at(0)


def test_effective_state_leaves_unknown_alone():
    harness = Harness()
    harness.poll(0, [])
    harness.poll(5, [L1])
    harness.poll(120, [], outcome="http_error")
    state = harness.only_state()
    assert state.state == STATE_UNKNOWN
    assert effective_state(state, at(121), DEFAULT_TUNING) == STATE_UNKNOWN
