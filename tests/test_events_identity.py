"""Identity must not depend on when we happened to look."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from transit_friction.events.detect import ObservedEntity
from transit_friction.events.identity import (
    entity_uid,
    episode_id,
    observation_id,
    transition_uid,
)

T = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def test_entity_identity_is_stable_across_observations():
    """The legacy defect: an id derived from collection time.

    The same elevator observed on 288 polls must be one entity, not 288.
    """
    ids = {
        entity_uid("brokenlifts", "elevator", "L1")
        for _ in range(288)
    }
    assert len(ids) == 1


def test_entity_identity_separates_sources_types_and_natives():
    base = entity_uid("brokenlifts", "elevator", "L1")
    assert base != entity_uid("vbb_gtfs_rt", "elevator", "L1")
    assert base != entity_uid("brokenlifts", "station_accessibility", "L1")
    assert base != entity_uid("brokenlifts", "elevator", "L2")


@pytest.mark.parametrize(
    "args",
    [("", "elevator", "L1"), ("brokenlifts", "", "L1"), ("brokenlifts", "elevator", "")],
)
def test_entity_identity_requires_every_part(args):
    with pytest.raises(ValueError):
        entity_uid(*args)


def test_entity_without_native_id_is_refused():
    """A source without a stable key produces observations, not entities."""
    with pytest.raises(ValueError, match="stable native id"):
        ObservedEntity(source_native_id="", entity_type="elevator")


def test_transition_uid_is_an_idempotency_key():
    uid = entity_uid("brokenlifts", "elevator", "L1")
    same = transition_uid(uid, "impaired", T, "listed_in_complete_snapshot")
    assert same == transition_uid(uid, "impaired", T, "listed_in_complete_snapshot")
    assert same != transition_uid(uid, "ok", T, "listed_in_complete_snapshot")
    assert same != transition_uid(
        uid, "impaired", T + timedelta(minutes=5), "listed_in_complete_snapshot"
    )
    assert same != transition_uid(uid, "impaired", T, "flap_correction")


def test_observation_id_distinguishes_attempts():
    assert observation_id("brokenlifts", T, "run-1") != observation_id(
        "brokenlifts", T, "run-2"
    )
    assert observation_id("brokenlifts", T, "run-1") == observation_id(
        "brokenlifts", T, "run-1"
    )


def test_episode_id_is_bound_to_its_opening():
    uid = entity_uid("brokenlifts", "elevator", "L1")
    assert episode_id(uid, T) != episode_id(uid, T + timedelta(hours=1))
