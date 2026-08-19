"""Resolving outage-source station ids against a derived population.

The rule that shapes this module: **nothing is dropped.** An outage at a station
we cannot place is not evidence that nothing happened there — it is evidence we
cannot attribute, and it has to leave a mark. Silently discarding it lowers
every rate by exactly the amount we failed to understand, which is the most
flattering possible error.

Four verdicts, kept apart on purpose. Two mean the join is broken; one means the
join worked and told us our scope predicate is too narrow; that one must never
gate anything, because suppressing a measurement whenever the frame turns out to
be wrong is how a frame stays wrong.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .frame import Population
from .identity import IdentityError, canonical_station_number

MATCHED = "matched"
UNMATCHED_MALFORMED = "unmatched_malformed"
UNMATCHED_UNKNOWN_ID = "unmatched_unknown_id"
OUT_OF_SCOPE = "out_of_scope"

#: Dimension keys used when the hours cannot be attributed to a frame station.
DIMENSION_UNMATCHED = "__unmatched__"
DIMENSION_OUT_OF_SCOPE = "__out_of_scope__"
DIMENSION_UNATTRIBUTED = "__unattributed__"


@dataclass(frozen=True, slots=True)
class Resolution:
    source_station_id: str
    verdict: str
    station_key: str | None = None
    station_number: str | None = None
    station_name: str | None = None
    reason: str | None = None

    @property
    def matched(self) -> bool:
        return self.verdict == MATCHED

    def to_dict(self) -> dict:
        return {
            "source_station_id": self.source_station_id,
            "verdict": self.verdict,
            "station_key": self.station_key,
            "station_number": self.station_number,
            "station_name": self.station_name,
            "reason": self.reason,
        }


def resolve(population: Population, source_station_id: str) -> Resolution:
    """Place one outage-source station id, or say precisely why we cannot."""
    try:
        number = canonical_station_number(source_station_id)
    except IdentityError as exc:
        return Resolution(source_station_id, UNMATCHED_MALFORMED, reason=str(exc))

    key = population.index.by_number.get(number)
    if key is None:
        return Resolution(
            source_station_id,
            UNMATCHED_UNKNOWN_ID,
            station_number=number,
            reason="well-formed, but no station in this population carries it",
        )

    station = population.stations.get(key)
    if station is None:
        return Resolution(
            source_station_id,
            OUT_OF_SCOPE,
            station_key=key,
            station_number=number,
            reason="a real station in the feed, outside the frame predicate",
        )

    return Resolution(
        source_station_id,
        MATCHED,
        station_key=key,
        station_number=number,
        station_name=station.name,
    )


@dataclass(frozen=True, slots=True)
class CrosswalkReport:
    """What the join did, as levels rather than as a ratio with its inputs gone."""

    resolutions: dict[str, Resolution]
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def distinct_source_station_ids_seen(self) -> int:
        return len(self.resolutions)

    @property
    def match_rate(self) -> float:
        """Matched share of distinct source ids. Zero ids is zero, not one."""
        if not self.resolutions:
            return 0.0
        return self.counts.get(MATCHED, 0) / len(self.resolutions)

    def ids_with_verdict(self, verdict: str) -> list[str]:
        return sorted(
            r.source_station_id for r in self.resolutions.values() if r.verdict == verdict
        )

    def dimension_for(self, source_station_id: str) -> str:
        """Where this station's hours are published."""
        resolution = self.resolutions.get(source_station_id)
        if resolution is None or resolution.verdict == UNMATCHED_MALFORMED:
            return DIMENSION_UNMATCHED
        if resolution.verdict == UNMATCHED_UNKNOWN_ID:
            return DIMENSION_UNMATCHED
        if resolution.verdict == OUT_OF_SCOPE:
            return DIMENSION_OUT_OF_SCOPE
        return resolution.station_key or DIMENSION_UNATTRIBUTED

    def to_dict(self) -> dict:
        return {
            "distinct_source_station_ids_seen": self.distinct_source_station_ids_seen,
            "matched": self.counts.get(MATCHED, 0),
            "unmatched_malformed": self.counts.get(UNMATCHED_MALFORMED, 0),
            "unmatched_unknown_id": self.counts.get(UNMATCHED_UNKNOWN_ID, 0),
            "out_of_scope": self.counts.get(OUT_OF_SCOPE, 0),
            "match_rate": round(self.match_rate, 4),
            "unmatched_ids": (
                self.ids_with_verdict(UNMATCHED_MALFORMED)
                + self.ids_with_verdict(UNMATCHED_UNKNOWN_ID)
            )[:50],
            "out_of_scope_stations": [
                {
                    "source_station_id": r.source_station_id,
                    "station_key": r.station_key,
                }
                for r in sorted(
                    (r for r in self.resolutions.values() if r.verdict == OUT_OF_SCOPE),
                    key=lambda r: r.source_station_id,
                )
            ][:50],
        }


def build_crosswalk(
    population: Population,
    source_station_ids: list[str],
) -> CrosswalkReport:
    """Resolve every distinct source station id seen in a window."""
    resolutions = {
        station_id: resolve(population, station_id)
        for station_id in sorted(set(source_station_ids))
    }
    return CrosswalkReport(
        resolutions=resolutions,
        counts=dict(Counter(r.verdict for r in resolutions.values())),
    )
