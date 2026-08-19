"""Current state as a fold over the ledger.

The legacy pipeline lost lifecycle state between GitHub Actions runners
(``AUDIT.md``, critical gap 3). The fix is not a better state file: it is that
there is no state file. The last transition per entity *is* its state, so a lost
runner, a re-run, and a fresh clone all converge on the same answer, and working
state can never silently disagree with the published history.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable

from .config import DEFAULT_TUNING, TuningParameters
from .records import Observation, Transition, require_aware
from .schema import (
    STATE_IMPAIRED,
    STATE_OK,
    STATE_UNKNOWN,
    TRANSITION_CLOSED,
    TRANSITION_CORRECTION,
    TRANSITION_RETIRED,
)


@dataclass(frozen=True, slots=True)
class EntityState:
    """What we currently believe about one entity, and how firmly."""

    entity_uid: str
    entity_type: str
    source_id: str
    source_native_id: str
    state: str
    since_earliest: datetime
    since_latest: datetime
    last_observation_id: str
    episode_id: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    line_id: str | None = None
    status_text: str | None = None
    quality_flags: tuple[str, ...] = ()
    closed_at_latest: datetime | None = None
    closed_episode_id: str | None = None
    transition_times: tuple[datetime, ...] = ()
    retired: bool = False

    def __post_init__(self) -> None:
        require_aware(self.since_earliest, "since_earliest")
        require_aware(self.since_latest, "since_latest")

    def recent_transition_count(
        self,
        now: datetime,
        window_s: int,
    ) -> int:
        cutoff = now - timedelta(seconds=window_s)
        return sum(1 for moment in self.transition_times if moment > cutoff)


@dataclass(frozen=True, slots=True)
class SourceCursor:
    """Where a source stood at the end of the observations folded so far."""

    source_id: str
    last_trusted_at: datetime | None = None
    last_trusted_observation_id: str | None = None
    last_source_updated_at: datetime | None = None
    last_payload_sha256: str | None = None
    last_attempt_at: datetime | None = None
    unchanged_since: datetime | None = None


def _apply(state: EntityState | None, transition: Transition) -> EntityState:
    times = ((state.transition_times if state else ()) + (transition.t_latest,))[-32:]

    closed_at_latest = state.closed_at_latest if state else None
    closed_episode_id = state.closed_episode_id if state else None
    if transition.transition_type == TRANSITION_CLOSED:
        closed_at_latest = transition.t_latest
        closed_episode_id = transition.episode_id

    episode_id: str | None = transition.episode_id
    if transition.to_state == STATE_OK:
        episode_id = None

    return EntityState(
        entity_uid=transition.entity_uid,
        entity_type=transition.entity_type,
        source_id=transition.source_id,
        source_native_id=transition.source_native_id,
        state=transition.to_state,
        since_earliest=transition.t_earliest,
        since_latest=transition.t_latest,
        last_observation_id=transition.observation_id,
        episode_id=episode_id,
        station_id=transition.station_id or (state.station_id if state else None),
        station_name=transition.station_name or (state.station_name if state else None),
        line_id=transition.line_id or (state.line_id if state else None),
        status_text=transition.status_text or (state.status_text if state else None),
        quality_flags=transition.quality_flags,
        closed_at_latest=closed_at_latest,
        closed_episode_id=closed_episode_id,
        transition_times=times,
        retired=transition.transition_type == TRANSITION_RETIRED,
    )


def fold_transitions(transitions: Iterable[Transition]) -> dict[str, EntityState]:
    """Rebuild entity state from the transition ledger.

    Corrections are applied by dropping the rows they correct: the ledger keeps
    the mistake, the view does not repeat it.
    """
    rows = sorted(transitions, key=lambda row: row.causal_key)

    corrected = {
        row.corrects_transition_uid
        for row in rows
        if row.transition_type == TRANSITION_CORRECTION and row.corrects_transition_uid
    }
    seen: set[str] = set()

    states: dict[str, EntityState] = {}
    for row in rows:
        if row.transition_uid in corrected:
            continue
        if row.transition_uid in seen:
            continue
        seen.add(row.transition_uid)
        if row.transition_type == TRANSITION_CORRECTION:
            # A correction carries the replacement facts in its own fields.
            states[row.entity_uid] = _apply(states.get(row.entity_uid), row)
            continue
        states[row.entity_uid] = _apply(states.get(row.entity_uid), row)

    return {uid: state for uid, state in states.items() if not state.retired}


def fold_cursors(observations: Iterable[Observation]) -> dict[str, SourceCursor]:
    """Rebuild per-source cursors from the observation ledger."""
    cursors: dict[str, SourceCursor] = {}
    for row in sorted(observations, key=lambda item: item.attempted_at):
        cursor = cursors.get(row.source_id, SourceCursor(source_id=row.source_id))
        unchanged_since = cursor.unchanged_since
        if row.payload_sha256 is not None:
            if row.payload_sha256 != cursor.last_payload_sha256:
                unchanged_since = row.observed_at or row.attempted_at
            elif unchanged_since is None:
                unchanged_since = row.observed_at or row.attempted_at

        cursor = replace(
            cursor,
            last_attempt_at=row.attempted_at,
            last_payload_sha256=row.payload_sha256 or cursor.last_payload_sha256,
            unchanged_since=unchanged_since,
        )
        if row.trusted_for_resolution:
            cursor = replace(
                cursor,
                last_trusted_at=row.observed_at or row.attempted_at,
                last_trusted_observation_id=row.observation_id,
                last_source_updated_at=row.source_updated_at
                or cursor.last_source_updated_at,
            )
        cursors[row.source_id] = cursor
    return cursors


def effective_state(
    state: EntityState,
    now: datetime,
    tuning: TuningParameters = DEFAULT_TUNING,
) -> str:
    """State as it should be *read*, not as it was written.

    Staleness is evaluated at read time. An entity last seen impaired two days
    ago by a source that has been down since is not impaired — it is unknown,
    and a dashboard must say so.
    """
    if state.state == STATE_UNKNOWN:
        return STATE_UNKNOWN
    age = (now - state.since_latest).total_seconds()
    if age > tuning.max_trust_gap_s:
        return STATE_UNKNOWN
    return state.state


def open_entities(states: dict[str, EntityState]) -> dict[str, EntityState]:
    return {
        uid: state for uid, state in states.items() if state.state == STATE_IMPAIRED
    }


def known_ok_entities(states: dict[str, EntityState]) -> dict[str, EntityState]:
    return {uid: state for uid, state in states.items() if state.state == STATE_OK}
