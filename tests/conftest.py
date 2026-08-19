"""Shared helpers for the events-layer tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from transit_friction.events.config import DEFAULT_TUNING, TuningParameters
from transit_friction.events.detect import (
    DetectionResult,
    ObservedEntity,
    SourceSnapshot,
    detect,
)
from transit_friction.events.records import Observation, Transition
from transit_friction.events.state import EntityState, SourceCursor

ORIGIN = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
SOURCE = "brokenlifts"


def at(minutes: float) -> datetime:
    return ORIGIN + timedelta(minutes=minutes)


def lift(
    native_id: str = "L1",
    *,
    station_id: str = "S1",
    station_name: str = "Alexanderplatz",
    status_text: str | None = None,
    t_source: datetime | None = None,
) -> ObservedEntity:
    return ObservedEntity(
        source_native_id=native_id,
        entity_type="elevator",
        station_id=station_id,
        station_name=station_name,
        status_text=status_text,
        t_source=t_source,
    )


@dataclass
class Harness:
    """Drives a sequence of polls through the detector, keeping state."""

    tuning: TuningParameters = DEFAULT_TUNING
    source_id: str = SOURCE
    states: dict[str, EntityState] = field(default_factory=dict)
    cursor: SourceCursor | None = None
    pending: dict = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    suppressed: dict[str, int] = field(default_factory=dict)
    _run: int = 0

    def poll(
        self,
        minutes: float,
        entities: tuple[ObservedEntity, ...] | list[ObservedEntity] = (),
        *,
        outcome: str = "ok",
        complete: bool = True,
        source_updated_at: datetime | None = None,
        source_age_minutes: float = 1,
        payload_sha256: str | None = None,
    ) -> DetectionResult:
        self._run += 1
        moment = at(minutes)
        failed = outcome != "ok"
        snapshot = SourceSnapshot(
            source_id=self.source_id,
            run_id=f"run-{self._run}",
            attempted_at=moment,
            observed_at=None if failed else moment,
            source_updated_at=(
                None
                if failed or not complete
                else (source_updated_at or moment - timedelta(minutes=source_age_minutes))
            ),
            outcome=outcome,
            complete=complete and not failed,
            entities=tuple(entities),
            advertised_count=len(tuple(entities)),
            payload_sha256=payload_sha256,
        )
        result = detect(
            snapshot, self.states, self.cursor, self.pending, self.tuning
        )
        self.states = result.states
        self.cursor = result.cursor
        self.pending = result.pending
        self.transitions.extend(result.transitions)
        self.observations.append(result.observation)
        for uid, count in result.suppressed_flaps.items():
            self.suppressed[uid] = self.suppressed.get(uid, 0) + count
        return result

    @property
    def types(self) -> list[str]:
        return [row.transition_type for row in self.transitions]

    def only_state(self) -> EntityState:
        assert len(self.states) == 1, self.states
        return next(iter(self.states.values()))


@pytest.fixture
def harness() -> Harness:
    return Harness()
