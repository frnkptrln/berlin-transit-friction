"""Turn one source snapshot into transitions.

This is where the architecture's promises become behaviour:

* an observation is always recorded, successful or not;
* a change is dated as an interval, never as a point;
* a gap suspends knowledge instead of supplying good news;
* opening is responsive, closing is conservative;
* a source that alternates cannot manufacture episodes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from .config import DEFAULT_TUNING, TuningParameters
from .identity import entity_uid, episode_id, observation_id, transition_uid
from .records import Observation, Transition, require_aware
from .schema import (
    ATTRIBUTE_WHITELIST,
    CERTAINTY_BOUNDED,
    CERTAINTY_OBSERVED,
    EVIDENCE_ABSENT_FROM_COMPLETE_SNAPSHOT,
    EVIDENCE_COVERAGE_LOST,
    EVIDENCE_COVERAGE_RESTORED,
    EVIDENCE_FLAP_CORRECTION,
    EVIDENCE_LISTED_IN_COMPLETE_SNAPSHOT,
    EVIDENCE_SOURCE_DEGRADED,
    EVIDENCE_SOURCE_STALE,
    FLAG_DEBOUNCED,
    FLAG_FLAPPING,
    FLAG_LONG_GAP,
    OUTCOME_INCOMPLETE,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    OUTCOME_STALE,
    STATE_IMPAIRED,
    STATE_OK,
    STATE_UNKNOWN,
    TRANSITION_ATTRIBUTES_CHANGED,
    TRANSITION_CLOSED,
    TRANSITION_OPENED,
    TRANSITION_REOPENED,
    TRANSITION_UNKNOWN_ENTERED,
    TRANSITION_UNKNOWN_EXITED,
)
from .state import EntityState, SourceCursor, _apply


@dataclass(frozen=True, slots=True)
class ObservedEntity:
    """One impaired thing, as a source reported it in a single snapshot."""

    source_native_id: str
    entity_type: str
    station_id: str | None = None
    station_name: str | None = None
    line_id: str | None = None
    status_text: str | None = None
    t_source: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_native_id:
            raise ValueError(
                "a source without a stable native id must not be ingested as an "
                "entity; it may still produce observations"
            )
        if self.t_source is not None:
            require_aware(self.t_source, "t_source")


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """The generic form of "we looked at a source once"."""

    source_id: str
    run_id: str
    attempted_at: datetime
    outcome: str
    complete: bool = False
    observed_at: datetime | None = None
    source_updated_at: datetime | None = None
    entities: tuple[ObservedEntity, ...] = ()
    advertised_count: int | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    payload_sha256: str | None = None
    warnings: tuple[str, ...] = ()
    collector_version: str = "0.0.0"
    parser_version: str = "0.0.0"

    def __post_init__(self) -> None:
        require_aware(self.attempted_at, "attempted_at")
        if self.observed_at is not None:
            require_aware(self.observed_at, "observed_at")

    @property
    def reference_at(self) -> datetime:
        """The time this snapshot speaks about, even when the fetch failed."""
        return self.observed_at or self.attempted_at


@dataclass(frozen=True, slots=True)
class PendingChange:
    """A state change waiting for confirmation.

    Lives in the ephemeral raw layer, never in the ledger. Its timestamps are
    those of the *first* observation that showed the new state, so debouncing
    delays writing without ever distorting dating.

    It has to survive between runs: a collector invoked as a fresh process each
    poll would otherwise never reach a second confirmation, and nothing would
    ever close. Losing it costs one extra confirmation cycle and nothing else,
    which is why it belongs in the 7-day layer rather than in the ledger.
    """

    entity_uid: str
    target_state: str
    count: int
    first_seen_at: datetime
    first_t_earliest: datetime
    first_observation_id: str
    last_seen_at: datetime
    first_prev_observation_id: str | None = None
    entity: ObservedEntity | None = None

    def to_dict(self) -> dict:
        return {
            "entity_uid": self.entity_uid,
            "target_state": self.target_state,
            "count": self.count,
            "first_seen_at": self.first_seen_at.isoformat(),
            "first_t_earliest": self.first_t_earliest.isoformat(),
            "first_observation_id": self.first_observation_id,
            "last_seen_at": self.last_seen_at.isoformat(),
            "first_prev_observation_id": self.first_prev_observation_id,
            "entity": (
                {
                    "source_native_id": self.entity.source_native_id,
                    "entity_type": self.entity.entity_type,
                    "station_id": self.entity.station_id,
                    "station_name": self.entity.station_name,
                    "line_id": self.entity.line_id,
                    "status_text": self.entity.status_text,
                    "t_source": (
                        self.entity.t_source.isoformat()
                        if self.entity.t_source
                        else None
                    ),
                }
                if self.entity is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PendingChange":
        entity = payload.get("entity")
        return cls(
            entity_uid=payload["entity_uid"],
            target_state=payload["target_state"],
            count=int(payload["count"]),
            first_seen_at=datetime.fromisoformat(payload["first_seen_at"]),
            first_t_earliest=datetime.fromisoformat(payload["first_t_earliest"]),
            first_observation_id=payload["first_observation_id"],
            last_seen_at=datetime.fromisoformat(payload["last_seen_at"]),
            first_prev_observation_id=payload.get("first_prev_observation_id"),
            entity=(
                ObservedEntity(
                    source_native_id=entity["source_native_id"],
                    entity_type=entity["entity_type"],
                    station_id=entity.get("station_id"),
                    station_name=entity.get("station_name"),
                    line_id=entity.get("line_id"),
                    status_text=entity.get("status_text"),
                    t_source=(
                        datetime.fromisoformat(entity["t_source"])
                        if entity.get("t_source")
                        else None
                    ),
                )
                if entity
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DetectionResult:
    observation: Observation
    transitions: tuple[Transition, ...]
    states: dict[str, EntityState]
    pending: dict[str, PendingChange]
    cursor: SourceCursor
    suppressed_flaps: dict[str, int]
    notes: tuple[str, ...] = ()


def _is_fresh(snapshot: SourceSnapshot, cursor: SourceCursor) -> bool:
    """Is this a new rendering, or the same page served again?

    A page whose own update timestamp has not advanced is the same statement
    about the world as the one before it. Re-reading it cannot be evidence that
    something changed since, so it may never resolve an outage.
    """
    if snapshot.source_updated_at is None:
        return False
    if cursor.last_source_updated_at is None:
        return True
    return snapshot.source_updated_at > cursor.last_source_updated_at


def _is_stuck(
    snapshot: SourceSnapshot,
    tuning: TuningParameters,
) -> bool:
    """Has the source's own clock fallen too far behind to describe now?

    A stuck feed looks exactly like "no disruptions" unless you check. Beyond
    this age the page no longer tells us what is true now, so the fetch stops
    counting as coverage too.
    """
    if snapshot.source_updated_at is None:
        return True
    age = (snapshot.reference_at - snapshot.source_updated_at).total_seconds()
    return age > tuning.max_source_stale_s


def _degradation_evidence(outcome: str) -> str:
    """Why we stopped trusting: a skipped look, a stuck clock, or a bad fetch."""
    if outcome == OUTCOME_STALE:
        return EVIDENCE_SOURCE_STALE
    if outcome == OUTCOME_SKIPPED:
        return EVIDENCE_COVERAGE_LOST
    return EVIDENCE_SOURCE_DEGRADED


def _advance_pending(
    pending: dict[str, PendingChange],
    uid: str,
    target_state: str,
    snapshot: SourceSnapshot,
    t_earliest: datetime,
    obs_id: str,
    prev_obs_id: str | None,
    entity: ObservedEntity | None,
    tuning: TuningParameters,
) -> tuple[PendingChange, bool]:
    existing = pending.get(uid)
    if existing is None or existing.target_state != target_state:
        candidate = PendingChange(
            entity_uid=uid,
            target_state=target_state,
            count=1,
            first_seen_at=snapshot.reference_at,
            first_t_earliest=t_earliest,
            first_observation_id=obs_id,
            first_prev_observation_id=prev_obs_id,
            last_seen_at=snapshot.reference_at,
            entity=entity,
        )
    else:
        candidate = replace(
            existing,
            count=existing.count + 1,
            last_seen_at=snapshot.reference_at,
            entity=entity or existing.entity,
        )

    if target_state == STATE_IMPAIRED:
        need_n, need_s = tuning.confirm_open_n, tuning.confirm_open_s
    else:
        need_n, need_s = tuning.confirm_close_n, tuning.confirm_close_s

    dwell = (candidate.last_seen_at - candidate.first_seen_at).total_seconds()
    confirmed = candidate.count >= need_n and dwell >= need_s
    return candidate, confirmed


def detect(
    snapshot: SourceSnapshot,
    states: dict[str, EntityState],
    cursor: SourceCursor | None = None,
    pending: dict[str, PendingChange] | None = None,
    tuning: TuningParameters = DEFAULT_TUNING,
) -> DetectionResult:
    """Reconcile one snapshot against known state."""
    cursor = cursor or SourceCursor(source_id=snapshot.source_id)
    pending = dict(pending or {})
    next_states = dict(states)
    suppressed: dict[str, int] = {}
    notes: list[str] = []

    reference_at = snapshot.reference_at
    gap_before_s = 0
    if cursor.last_current_at is not None:
        gap_before_s = max(
            0, int((reference_at - cursor.last_current_at).total_seconds())
        )

    # Completeness is a property of one observation, never an assumption about
    # the provider: without the source's own update timestamp we cannot check it.
    complete = snapshot.complete and snapshot.source_updated_at is not None
    fresh = _is_fresh(snapshot, cursor)
    stuck = _is_stuck(snapshot, tuning)

    outcome = snapshot.outcome
    if outcome == OUTCOME_OK and not complete:
        outcome = OUTCOME_INCOMPLETE
    if outcome == OUTCOME_OK and not fresh:
        outcome = OUTCOME_STALE
        notes.append(
            "source has not published a newer version; this snapshot repeats "
            "the previous one and cannot resolve anything"
        )
    if outcome == OUTCOME_OK and stuck:
        outcome = OUTCOME_STALE
        notes.append("source clock is too far behind to describe the present")

    # Three-way, because "we were watching" and "this could resolve something"
    # are different questions with different answers.
    source_current = complete and not stuck and snapshot.outcome == OUTCOME_OK
    trusted = outcome == OUTCOME_OK and complete and fresh

    if (
        snapshot.payload_sha256 is not None
        and snapshot.payload_sha256 == cursor.last_payload_sha256
    ):
        notes.append("payload identical to previous fetch")

    obs_id = observation_id(snapshot.source_id, snapshot.attempted_at, snapshot.run_id)
    observation = Observation(
        observation_id=obs_id,
        run_id=snapshot.run_id,
        source_id=snapshot.source_id,
        attempted_at=snapshot.attempted_at,
        observed_at=snapshot.observed_at,
        source_updated_at=snapshot.source_updated_at,
        outcome=outcome,
        complete=complete,
        source_current=source_current,
        trusted_for_resolution=trusted,
        entity_count=len(snapshot.entities) if snapshot.observed_at else None,
        advertised_count=snapshot.advertised_count,
        http_status=snapshot.http_status,
        latency_ms=snapshot.latency_ms,
        payload_sha256=snapshot.payload_sha256,
        gap_before_s=gap_before_s,
        warnings=tuple(snapshot.warnings) + tuple(notes),
        collector_version=snapshot.collector_version,
        parser_version=snapshot.parser_version,
    )

    prev_obs_id = cursor.last_trusted_observation_id
    t_earliest = cursor.last_trusted_at or reference_at
    transitions: list[Transition] = []

    def _flags(state: EntityState | None, at: datetime, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
        flags = list(extra)
        if gap_before_s > tuning.max_trust_gap_s:
            flags.append(FLAG_LONG_GAP)
        previous = state.recent_transition_count(at, tuning.flap_quarantine_window_s) if state else 0
        if previous + 1 >= tuning.flap_quarantine_n:
            flags.append(FLAG_FLAPPING)
        return tuple(dict.fromkeys(flags))

    def _emit(
        *,
        uid: str,
        entity_type: str,
        native_id: str,
        transition_type: str,
        to_state: str,
        from_state: str | None,
        evidence: str,
        episode: str,
        at_earliest: datetime,
        at_latest: datetime,
        observation_ref: str,
        prev_observation_ref: str | None,
        t_source: datetime | None = None,
        station_id: str | None = None,
        station_name: str | None = None,
        line_id: str | None = None,
        status_text: str | None = None,
        extra_flags: tuple[str, ...] = (),
        current: EntityState | None = None,
        certainty: str | None = None,
    ) -> None:
        if certainty is None:
            certainty = CERTAINTY_OBSERVED if t_source is not None else CERTAINTY_BOUNDED
            if certainty == CERTAINTY_BOUNDED and at_earliest == at_latest:
                certainty = CERTAINTY_OBSERVED
        row = Transition(
            transition_uid=transition_uid(uid, to_state, at_latest, evidence),
            entity_uid=uid,
            entity_type=entity_type,
            source_id=snapshot.source_id,
            source_native_id=native_id,
            transition_type=transition_type,
            from_state=from_state,
            to_state=to_state,
            t_earliest=at_earliest,
            t_latest=at_latest,
            t_source=t_source,
            recorded_at=reference_at,
            certainty=certainty,
            evidence=evidence,
            observation_id=observation_ref,
            prev_observation_id=prev_observation_ref,
            gap_before_s=gap_before_s,
            episode_id=episode,
            station_id=station_id,
            station_name=station_name,
            line_id=line_id,
            status_text=status_text,
            quality_flags=_flags(current, at_latest, extra_flags),
            run_id=snapshot.run_id,
            parser_version=snapshot.parser_version,
        )
        transitions.append(row)
        next_states[uid] = _apply(next_states.get(uid), row)

    source_states = {
        uid: state
        for uid, state in states.items()
        if state.source_id == snapshot.source_id
    }

    def _enter_unknown(evidence: str) -> None:
        """Stop claiming to know the state of entities with a running episode.

        Only impaired entities are affected. An entity we believe is fine and
        cannot see is handled by coverage: nothing about it is being measured,
        so the observation ledger is the right place to record the blind spot.
        An impaired entity has a running duration that can no longer be bounded,
        so it must go unknown.

        The row is dated at the last trustworthy look, not at now: that is the
        moment we stopped knowing, and it is the same boundary
        ``compute_coverage`` uses, so entity-level unknown time and source-level
        gap time always agree.
        """
        lapsed = cursor.last_current_at or cursor.last_trusted_at or reference_at
        for uid, state in sorted(source_states.items()):
            if state.state != STATE_IMPAIRED:
                continue
            _emit(
                uid=uid,
                entity_type=state.entity_type,
                native_id=state.source_native_id,
                transition_type=TRANSITION_UNKNOWN_ENTERED,
                to_state=STATE_UNKNOWN,
                from_state=state.state,
                evidence=evidence,
                episode=state.episode_id or episode_id(uid, reference_at),
                at_earliest=lapsed,
                at_latest=lapsed,
                observation_ref=obs_id,
                prev_observation_ref=prev_obs_id,
                station_id=state.station_id,
                station_name=state.station_name,
                line_id=state.line_id,
                status_text=state.status_text,
                current=state,
                certainty=CERTAINTY_BOUNDED,
            )
            pending.pop(uid, None)

    if not trusted:
        # A degraded look tells us nothing about the world. Within tolerance we
        # simply wait; beyond it we stop claiming to know.
        if gap_before_s > tuning.max_trust_gap_s:
            _enter_unknown(_degradation_evidence(outcome))
        return DetectionResult(
            observation=observation,
            transitions=tuple(transitions),
            states=next_states,
            pending=pending,
            cursor=replace(
                cursor,
                last_attempt_at=snapshot.attempted_at,
                last_current_at=(
                    reference_at if source_current else cursor.last_current_at
                ),
                last_current_observation_id=(
                    obs_id if source_current else cursor.last_current_observation_id
                ),
                last_payload_sha256=snapshot.payload_sha256
                or cursor.last_payload_sha256,
            ),
            suppressed_flaps=suppressed,
            notes=tuple(notes),
        )

    if gap_before_s > tuning.max_trust_gap_s:
        # The gap happened whether or not this snapshot is good. Recording it
        # before reading the snapshot is what keeps ``unknown_seconds`` honest
        # for episodes that span a collector outage.
        _enter_unknown(EVIDENCE_COVERAGE_LOST)

    observed: dict[str, ObservedEntity] = {}
    for entity in snapshot.entities:
        uid = entity_uid(snapshot.source_id, entity.entity_type, entity.source_native_id)
        observed[uid] = entity

    for uid, entity in sorted(observed.items()):
        current = next_states.get(uid)
        state_name = current.state if current else None

        if state_name == STATE_IMPAIRED:
            if uid in pending and pending[uid].target_state == STATE_OK:
                pending.pop(uid)
                suppressed[uid] = suppressed.get(uid, 0) + 1
            changed = {
                name: getattr(entity, name, None)
                for name in ATTRIBUTE_WHITELIST
                if hasattr(entity, name)
                and getattr(entity, name, None) is not None
                and getattr(entity, name, None) != getattr(current, name, None)
            }
            if changed:
                _emit(
                    uid=uid,
                    entity_type=entity.entity_type,
                    native_id=entity.source_native_id,
                    transition_type=TRANSITION_ATTRIBUTES_CHANGED,
                    to_state=STATE_IMPAIRED,
                    from_state=STATE_IMPAIRED,
                    evidence=EVIDENCE_LISTED_IN_COMPLETE_SNAPSHOT,
                    episode=current.episode_id or episode_id(uid, reference_at),
                    at_earliest=t_earliest,
                    at_latest=reference_at,
                    observation_ref=obs_id,
                    prev_observation_ref=prev_obs_id,
                    station_id=entity.station_id,
                    station_name=entity.station_name,
                    line_id=entity.line_id,
                    status_text=entity.status_text,
                    current=current,
                )
            continue

        if state_name == STATE_UNKNOWN:
            # Regaining sight is not a change in the world, so it is not
            # debounced. The episode continues: it never ended.
            _emit(
                uid=uid,
                entity_type=entity.entity_type,
                native_id=entity.source_native_id,
                transition_type=TRANSITION_UNKNOWN_EXITED,
                to_state=STATE_IMPAIRED,
                from_state=STATE_UNKNOWN,
                evidence=EVIDENCE_COVERAGE_RESTORED,
                episode=current.episode_id or episode_id(uid, reference_at),
                at_earliest=t_earliest,
                at_latest=reference_at,
                observation_ref=obs_id,
                prev_observation_ref=prev_obs_id,
                station_id=entity.station_id,
                station_name=entity.station_name,
                line_id=entity.line_id,
                status_text=entity.status_text,
                current=current,
            )
            pending.pop(uid, None)
            continue

        candidate, confirmed = _advance_pending(
            pending, uid, STATE_IMPAIRED, snapshot, t_earliest, obs_id,
            prev_obs_id, entity, tuning,
        )
        if not confirmed:
            pending[uid] = candidate
            continue
        pending.pop(uid, None)

        reopen = (
            current is not None
            and current.closed_at_latest is not None
            and (candidate.first_seen_at - current.closed_at_latest).total_seconds()
            <= tuning.reopen_merge_window_s
        )
        extra = (FLAG_DEBOUNCED,) if candidate.count > 1 else ()
        _emit(
            uid=uid,
            entity_type=entity.entity_type,
            native_id=entity.source_native_id,
            transition_type=TRANSITION_REOPENED if reopen else TRANSITION_OPENED,
            to_state=STATE_IMPAIRED,
            from_state=state_name,
            evidence=(
                EVIDENCE_FLAP_CORRECTION
                if reopen
                else EVIDENCE_LISTED_IN_COMPLETE_SNAPSHOT
            ),
            episode=(
                current.closed_episode_id
                if reopen and current and current.closed_episode_id
                else episode_id(uid, candidate.first_seen_at)
            ),
            at_earliest=candidate.first_t_earliest,
            at_latest=candidate.first_seen_at,
            observation_ref=candidate.first_observation_id,
            prev_observation_ref=candidate.first_prev_observation_id,
            t_source=entity.t_source,
            station_id=entity.station_id,
            station_name=entity.station_name,
            line_id=entity.line_id,
            status_text=entity.status_text,
            extra_flags=extra,
            current=current,
        )

    for uid in sorted(source_states):
        state = next_states.get(uid) or source_states[uid]
        if uid in observed or state.state == STATE_OK:
            continue

        if uid in pending and pending[uid].target_state == STATE_IMPAIRED:
            pending.pop(uid)
            suppressed[uid] = suppressed.get(uid, 0) + 1

        candidate, confirmed = _advance_pending(
            pending, uid, STATE_OK, snapshot, t_earliest, obs_id,
            prev_obs_id, None, tuning,
        )
        if not confirmed:
            pending[uid] = candidate
            continue
        pending.pop(uid, None)

        was_unknown = state.state == STATE_UNKNOWN
        extra = (FLAG_DEBOUNCED,) if candidate.count > 1 else ()
        _emit(
            uid=uid,
            entity_type=state.entity_type,
            native_id=state.source_native_id,
            transition_type=(
                TRANSITION_UNKNOWN_EXITED if was_unknown else TRANSITION_CLOSED
            ),
            to_state=STATE_OK,
            from_state=state.state,
            evidence=(
                EVIDENCE_COVERAGE_RESTORED
                if was_unknown
                else EVIDENCE_ABSENT_FROM_COMPLETE_SNAPSHOT
            ),
            episode=state.episode_id or episode_id(uid, candidate.first_seen_at),
            at_earliest=candidate.first_t_earliest,
            at_latest=candidate.first_seen_at,
            observation_ref=candidate.first_observation_id,
            prev_observation_ref=candidate.first_prev_observation_id,
            station_id=state.station_id,
            station_name=state.station_name,
            line_id=state.line_id,
            status_text=state.status_text,
            extra_flags=extra,
            current=state,
        )

    return DetectionResult(
        observation=observation,
        transitions=tuple(transitions),
        states=next_states,
        pending=pending,
        cursor=replace(
            cursor,
            last_attempt_at=snapshot.attempted_at,
            last_current_at=reference_at,
            last_current_observation_id=obs_id,
            last_trusted_at=reference_at,
            last_trusted_observation_id=obs_id,
            last_source_updated_at=snapshot.source_updated_at
            or cursor.last_source_updated_at,
            last_payload_sha256=snapshot.payload_sha256 or cursor.last_payload_sha256,
        ),
        suppressed_flaps=suppressed,
        notes=tuple(notes),
    )
