"""Deterministic identifiers.

The one rule that matters: **the collection timestamp is never an input to an
entity's identity.** Deriving ``event_id`` from the collection time is what made
the legacy dataset count the same condition as a new event on every poll, and
invalidated ten months of collection.

Transition and observation identifiers *do* include a timestamp, because they
identify one specific recorded fact rather than a durable object. They exist to
make re-running an ingestion idempotent.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

_SEPARATOR = "|"


def _digest(*parts: str, length: int = 20) -> str:
    payload = _SEPARATOR.join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def entity_uid(source_id: str, entity_type: str, source_native_id: str) -> str:
    """Stable identity of a tracked object.

    Depends only on which source reported it, what kind of thing it is, and the
    id the source itself uses. Nothing else. A source without a stable native id
    must not be ingested as an entity at all.
    """
    if not source_id or not entity_type or not source_native_id:
        raise ValueError("entity identity requires source, type and native id")
    return _digest(source_id, entity_type, source_native_id)


def transition_uid(
    entity_uid_value: str,
    to_state: str,
    t_latest: datetime,
    evidence: str,
) -> str:
    """Idempotency key for one recorded transition."""
    return _digest(entity_uid_value, to_state, t_latest.isoformat(), evidence)


def observation_id(source_id: str, attempted_at: datetime, run_id: str) -> str:
    """Idempotency key for one attempt to look at a source."""
    return _digest(source_id, attempted_at.isoformat(), run_id)


def episode_id(entity_uid_value: str, opened_at: datetime) -> str:
    """Identity of a continuous impairment episode.

    Time-bound by nature, unlike an entity: an episode *is* an interval. Reopens
    inside the merge window keep the original id so a flapping source cannot
    manufacture episodes.
    """
    return _digest("episode", entity_uid_value, opened_at.isoformat())
