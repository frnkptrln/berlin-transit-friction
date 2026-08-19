"""Row types for the two permanent tables.

Validation lives in ``__post_init__`` rather than in the writer, so an invalid
row cannot be constructed at all. The append-only tables are the source of
truth; there is no later pass in which a bad row could be fixed up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .schema import (
    CERTAINTIES,
    CERTAINTY_INFERRED,
    CERTAINTY_OBSERVED,
    CLOSING_EVIDENCE,
    EVIDENCES,
    OPENING_EVIDENCE,
    OUTCOME_OK,
    OUTCOMES,
    SCHEMA_VERSION,
    STATES,
    TRANSITION_CLOSED,
    TRANSITION_CORRECTION,
    TRANSITION_OPENED,
    TRANSITION_TYPES,
)


def require_aware(value: datetime, field_name: str) -> datetime:
    """Reject naive datetimes at the boundary.

    A naive timestamp in a transit dataset is a silent one-hour error twice a
    year, which is exactly the size of the effects we are trying to measure.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True, slots=True)
class Observation:
    """One attempt to look at a source. Written even when the fetch failed."""

    observation_id: str
    run_id: str
    source_id: str
    attempted_at: datetime
    outcome: str
    complete: bool
    trusted_for_resolution: bool
    gap_before_s: int
    observed_at: datetime | None = None
    source_updated_at: datetime | None = None
    entity_count: int | None = None
    advertised_count: int | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    payload_sha256: str | None = None
    warnings: tuple[str, ...] = ()
    collector_version: str = "0.0.0"
    parser_version: str = "0.0.0"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome: {self.outcome}")
        require_aware(self.attempted_at, "attempted_at")
        if self.observed_at is not None:
            require_aware(self.observed_at, "observed_at")
        if self.source_updated_at is not None:
            require_aware(self.source_updated_at, "source_updated_at")
        if self.gap_before_s < 0:
            raise ValueError("gap_before_s must be >= 0")
        if self.trusted_for_resolution and not (
            self.outcome == OUTCOME_OK and self.complete
        ):
            raise ValueError(
                "an observation may only be trusted for resolution when it "
                "succeeded and was complete"
            )
        if self.complete and self.source_updated_at is None:
            raise ValueError("a complete observation needs source_updated_at")

    def to_dict(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "attempted_at": _iso(self.attempted_at),
            "observed_at": _iso(self.observed_at),
            "source_updated_at": _iso(self.source_updated_at),
            "outcome": self.outcome,
            "complete": self.complete,
            "trusted_for_resolution": self.trusted_for_resolution,
            "entity_count": self.entity_count,
            "advertised_count": self.advertised_count,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "payload_sha256": self.payload_sha256,
            "gap_before_s": self.gap_before_s,
            "warnings": list(self.warnings),
            "collector_version": self.collector_version,
            "parser_version": self.parser_version,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Observation":
        return cls(
            observation_id=payload["observation_id"],
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            run_id=payload["run_id"],
            source_id=payload["source_id"],
            attempted_at=_parse(payload["attempted_at"]),
            observed_at=_parse(payload.get("observed_at")),
            source_updated_at=_parse(payload.get("source_updated_at")),
            outcome=payload["outcome"],
            complete=bool(payload["complete"]),
            trusted_for_resolution=bool(payload["trusted_for_resolution"]),
            entity_count=payload.get("entity_count"),
            advertised_count=payload.get("advertised_count"),
            http_status=payload.get("http_status"),
            latency_ms=payload.get("latency_ms"),
            payload_sha256=payload.get("payload_sha256"),
            gap_before_s=int(payload["gap_before_s"]),
            warnings=tuple(payload.get("warnings", ())),
            collector_version=payload.get("collector_version", "0.0.0"),
            parser_version=payload.get("parser_version", "0.0.0"),
        )


@dataclass(frozen=True, slots=True)
class Transition:
    """A change in what we know about one entity.

    ``t_earliest`` and ``t_latest`` bracket the change: it happened after the
    last trustworthy look and no later than the look that revealed it. Polling
    never yields a point in time, and pretending otherwise is how the legacy
    dashboard claimed precision it did not have.
    """

    transition_uid: str
    entity_uid: str
    entity_type: str
    source_id: str
    source_native_id: str
    transition_type: str
    to_state: str
    t_earliest: datetime
    t_latest: datetime
    certainty: str
    evidence: str
    observation_id: str
    gap_before_s: int
    episode_id: str
    from_state: str | None = None
    t_source: datetime | None = None
    prev_observation_id: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    line_id: str | None = None
    status_text: str | None = None
    recorded_at: datetime | None = None
    quality_flags: tuple[str, ...] = ()
    corrects_transition_uid: str | None = None
    correction_reason: str | None = None
    run_id: str = ""
    parser_version: str = "0.0.0"
    ingested_at: datetime | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.transition_type not in TRANSITION_TYPES:
            raise ValueError(f"unknown transition_type: {self.transition_type}")
        if self.to_state not in STATES:
            raise ValueError(f"unknown to_state: {self.to_state}")
        if self.from_state is not None and self.from_state not in STATES:
            raise ValueError(f"unknown from_state: {self.from_state}")
        if self.certainty not in CERTAINTIES:
            raise ValueError(f"unknown certainty: {self.certainty}")
        if self.evidence not in EVIDENCES:
            raise ValueError(f"unknown evidence: {self.evidence}")

        require_aware(self.t_earliest, "t_earliest")
        require_aware(self.t_latest, "t_latest")
        if self.t_earliest > self.t_latest:
            raise ValueError("t_earliest must not be after t_latest")
        if self.t_source is not None:
            require_aware(self.t_source, "t_source")
        if self.recorded_at is not None:
            require_aware(self.recorded_at, "recorded_at")
            if self.recorded_at < self.t_latest:
                raise ValueError("recorded_at cannot precede t_latest")
        if self.ingested_at is not None:
            require_aware(self.ingested_at, "ingested_at")
        if self.gap_before_s < 0:
            raise ValueError("gap_before_s must be >= 0")

        # The invariant the architecture exists to protect. Kept here, in the
        # constructor, so no future collector can route around it.
        if (
            self.transition_type == TRANSITION_CLOSED
            and self.evidence not in CLOSING_EVIDENCE
        ):
            raise ValueError(
                f"a failed, incomplete or stale observation cannot close an "
                f"outage: evidence={self.evidence!r} is not admissible for a "
                f"'closed' transition"
            )
        if (
            self.transition_type == TRANSITION_OPENED
            and self.evidence not in OPENING_EVIDENCE
        ):
            raise ValueError(
                f"evidence={self.evidence!r} is not admissible for an 'opened' "
                f"transition"
            )
        if self.certainty == CERTAINTY_OBSERVED and self.t_source is None:
            if self.t_earliest != self.t_latest:
                raise ValueError(
                    "certainty 'observed' requires either a source timestamp or "
                    "a zero-width bracket"
                )
        if self.transition_type == TRANSITION_CORRECTION:
            if not self.corrects_transition_uid:
                raise ValueError("a correction must name the row it corrects")
            if self.certainty != CERTAINTY_INFERRED and not self.correction_reason:
                raise ValueError("a correction must carry a reason")

    @property
    def causal_key(self) -> tuple[datetime, datetime, str]:
        """Sort key that reproduces the order the detector emitted rows in.

        ``t_latest`` alone is ambiguous: a row can be dated earlier than the run
        that detected it — ``unknown_entered`` is dated at the last trustworthy
        look, which is the same instant as the ``opened`` observed there. Folding
        on ``t_latest`` alone could then apply them in either order and end up
        with the wrong state.
        """
        return (self.recorded_at or self.t_latest, self.t_latest, self.transition_uid)

    @property
    def bracket_seconds(self) -> float:
        """Width of the interval the change is known to lie in."""
        return (self.t_latest - self.t_earliest).total_seconds()

    def to_dict(self) -> dict:
        return {
            "transition_uid": self.transition_uid,
            "schema_version": self.schema_version,
            "entity_uid": self.entity_uid,
            "entity_type": self.entity_type,
            "source_id": self.source_id,
            "source_native_id": self.source_native_id,
            "transition_type": self.transition_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "t_earliest": _iso(self.t_earliest),
            "t_latest": _iso(self.t_latest),
            "t_source": _iso(self.t_source),
            "recorded_at": _iso(self.recorded_at),
            "certainty": self.certainty,
            "evidence": self.evidence,
            "observation_id": self.observation_id,
            "prev_observation_id": self.prev_observation_id,
            "gap_before_s": self.gap_before_s,
            "episode_id": self.episode_id,
            "station_id": self.station_id,
            "station_name": self.station_name,
            "line_id": self.line_id,
            "status_text": self.status_text,
            "quality_flags": list(self.quality_flags),
            "corrects_transition_uid": self.corrects_transition_uid,
            "correction_reason": self.correction_reason,
            "run_id": self.run_id,
            "parser_version": self.parser_version,
            "ingested_at": _iso(self.ingested_at),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Transition":
        return cls(
            transition_uid=payload["transition_uid"],
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            entity_uid=payload["entity_uid"],
            entity_type=payload["entity_type"],
            source_id=payload["source_id"],
            source_native_id=payload["source_native_id"],
            transition_type=payload["transition_type"],
            from_state=payload.get("from_state"),
            to_state=payload["to_state"],
            t_earliest=_parse(payload["t_earliest"]),
            t_latest=_parse(payload["t_latest"]),
            t_source=_parse(payload.get("t_source")),
            recorded_at=_parse(payload.get("recorded_at")),
            certainty=payload["certainty"],
            evidence=payload["evidence"],
            observation_id=payload["observation_id"],
            prev_observation_id=payload.get("prev_observation_id"),
            gap_before_s=int(payload["gap_before_s"]),
            episode_id=payload["episode_id"],
            station_id=payload.get("station_id"),
            station_name=payload.get("station_name"),
            line_id=payload.get("line_id"),
            status_text=payload.get("status_text"),
            quality_flags=tuple(payload.get("quality_flags", ())),
            corrects_transition_uid=payload.get("corrects_transition_uid"),
            correction_reason=payload.get("correction_reason"),
            run_id=payload.get("run_id", ""),
            parser_version=payload.get("parser_version", "0.0.0"),
            ingested_at=_parse(payload.get("ingested_at")),
        )
