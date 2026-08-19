"""Coverage: what the observation ledger is for.

A sparse transition stream cannot distinguish "the network was fine for seven
hours" from "the collector was down for seven hours". This module reads the
observation ledger and answers that question, so that ``0`` and ``null`` can be
different values with different renderings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, TypeVar

from .config import DEFAULT_TUNING, TuningParameters
from .records import Observation

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Gap:
    """An interval during which we could not claim to know anything."""

    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "seconds": round(self.seconds, 3),
        }


@dataclass(frozen=True, slots=True)
class Coverage:
    source_id: str
    window_start: datetime
    window_end: datetime
    covered_seconds: float
    gap_seconds: float
    attempts: int
    trusted_attempts: int
    gaps: tuple[Gap, ...]

    @property
    def window_seconds(self) -> float:
        return (self.window_end - self.window_start).total_seconds()

    @property
    def coverage_ratio(self) -> float:
        if self.window_seconds <= 0:
            return 0.0
        return self.covered_seconds / self.window_seconds

    @property
    def longest_gap_seconds(self) -> float:
        return max((gap.seconds for gap in self.gaps), default=0.0)

    def publishable(self, tuning: TuningParameters = DEFAULT_TUNING) -> bool:
        return self.coverage_ratio >= tuning.min_publish_coverage

    def to_dict(self, tuning: TuningParameters = DEFAULT_TUNING) -> dict:
        return {
            "source_id": self.source_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "window_hours": round(self.window_seconds / 3600, 4),
            "coverage_ratio": round(self.coverage_ratio, 4),
            "covered_seconds": round(self.covered_seconds, 3),
            "gap_seconds": round(self.gap_seconds, 3),
            "longest_gap_seconds": round(self.longest_gap_seconds, 3),
            "attempts": self.attempts,
            "trusted_attempts": self.trusted_attempts,
            "publishable": self.publishable(tuning),
            "gaps": [gap.to_dict() for gap in self.gaps],
        }


def compute_coverage(
    observations: Iterable[Observation],
    source_id: str,
    window_start: datetime,
    window_end: datetime,
    tuning: TuningParameters = DEFAULT_TUNING,
) -> Coverage:
    """How much of a window was actually watched.

    The interval between two consecutive trustworthy observations counts as
    covered when it is no longer than ``max_trust_gap_s``, and as a gap
    otherwise. Binary rather than graded, because that is the same threshold at
    which an entity's state becomes ``unknown`` — one rule, two consequences.
    """
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")

    rows = [row for row in observations if row.source_id == source_id]
    attempts = sum(
        1 for row in rows if window_start <= row.attempted_at < window_end
    )
    trusted_times = sorted(
        row.observed_at or row.attempted_at
        for row in rows
        if row.trusted_for_resolution
    )

    inside = [t for t in trusted_times if window_start <= t <= window_end]
    before = [t for t in trusted_times if t < window_start]
    anchor = before[-1] if before else None

    covered = 0.0
    gaps: list[Gap] = []
    limit = tuning.max_trust_gap_s

    marks: list[datetime] = ([anchor] if anchor else []) + inside
    if not marks:
        return Coverage(
            source_id=source_id,
            window_start=window_start,
            window_end=window_end,
            covered_seconds=0.0,
            gap_seconds=(window_end - window_start).total_seconds(),
            attempts=attempts,
            trusted_attempts=0,
            gaps=(Gap(window_start, window_end),),
        )

    cursor = window_start
    if marks[0] > window_start:
        # Nothing anchored the beginning of the window.
        gaps.append(Gap(window_start, marks[0]))
        cursor = marks[0]

    for previous, current in zip(marks, marks[1:]):
        lo, hi = max(previous, window_start), min(current, window_end)
        if hi <= lo:
            continue
        if (current - previous).total_seconds() <= limit:
            covered += (hi - lo).total_seconds()
        else:
            gaps.append(Gap(lo, hi))
        cursor = hi

    tail_start = max(marks[-1], window_start)
    if window_end > tail_start:
        if (window_end - marks[-1]).total_seconds() <= limit:
            covered += (window_end - tail_start).total_seconds()
        else:
            gaps.append(Gap(tail_start, window_end))

    gap_seconds = (window_end - window_start).total_seconds() - covered
    return Coverage(
        source_id=source_id,
        window_start=window_start,
        window_end=window_end,
        covered_seconds=covered,
        gap_seconds=max(0.0, gap_seconds),
        attempts=attempts,
        trusted_attempts=len(inside),
        gaps=tuple(sorted(gaps, key=lambda gap: gap.start)),
    )


def value_or_null(
    value: T,
    coverage: Coverage,
    tuning: TuningParameters = DEFAULT_TUNING,
) -> T | None:
    """Emit a measurement only if the window was actually watched.

    This is the rule from ``docs/event-schema.md`` section 6.3 in one function:
    a collector outage must render as "no data", never as a perfect day.
    """
    return value if coverage.publishable(tuning) else None
