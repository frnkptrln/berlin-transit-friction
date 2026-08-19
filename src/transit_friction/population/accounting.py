"""Three-valued station-time accounting, and the interval it produces.

The mistake this module exists to avoid is subtle and symmetric. Given outages
we can see and stations we cannot, there are two tempting moves:

* divide the outages by the stations we *can* see — a conditional mean over a
  set chosen by the outcome, which reads reassuringly and understates;
* publish nothing until coverage is good enough — which also reads
  reassuringly, because an empty dashboard says "no problem" to everyone who
  does not read the footnote.

Both replace an interval with a zero-width claim. So every station-second in the
frame is accounted for as exactly one of OUT, KNOWN_OK or UNKNOWN, and the
result is published as a two-sided interval over the *whole* frame:

    p_lo = OUT / D                    every unknown second was fine
    p_hi = (OUT + UNKNOWN) / D        every unknown second was an outage

Blindness widens the interval instead of deleting the stations it applies to.
A point estimate is offered only when the unknown share is small enough that it
is worth having, and it is provably inside the interval.

**KNOWN_OK requires positive evidence.** A station we have never seen the source
report on is not a station we know is fine. Today, with no station roster from
the source, ``KNOWN_OK`` is structurally unreachable — so ``p_hi`` is 1 and no
point estimate exists. That is not a defect of this code; it is the true state
of our knowledge, and the code says so rather than inventing a denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from ..events.episodes import Episode, union_seconds
from .crosswalk import CrosswalkReport
from .frame import Population

#: Causes of not knowing, kept apart. "We were not polling" and "the source does
#: not cover this station" are different blindnesses with different remedies,
#: and summing them into one coverage number hides both.
CAUSE_NOT_MONITORED = "not_monitored"
CAUSE_ROSTER_INCOMPLETE = "roster_incomplete"
CAUSE_SOURCE_NOT_CURRENT = "source_not_current"
CAUSE_UNMATCHED_JOIN = "unmatched_join"

#: Below this unknown share a point estimate is offered beside the interval.
DEFAULT_MAX_UNKNOWN_SHARE_FOR_POINT = 0.10


@dataclass(frozen=True, slots=True)
class Accounting:
    """One window of station-time, fully accounted for."""

    window_start: datetime
    window_end: datetime
    denominator_seconds: float
    out_seconds: float
    out_seconds_min: float
    out_seconds_max: float
    known_ok_seconds: float
    unknown_by_cause: dict[str, float]
    frame_station_count: int
    equipped_station_count: int
    monitored_station_count: int
    stations_out: tuple[str, ...]
    stations_without_elevator_edge: int
    unmatched_source_ids: tuple[str, ...]
    out_of_scope_source_ids: tuple[str, ...]
    match_rate: float
    population_id: str
    diagnostics: dict = field(default_factory=dict)

    @property
    def unknown_seconds(self) -> float:
        return sum(self.unknown_by_cause.values())

    @property
    def unknown_share(self) -> float:
        if self.denominator_seconds <= 0:
            return 1.0
        return min(1.0, self.unknown_seconds / self.denominator_seconds)

    @property
    def share_low(self) -> float:
        """Every unknown second was fine. A floor, always true."""
        if self.denominator_seconds <= 0:
            return 0.0
        return self.out_seconds / self.denominator_seconds

    @property
    def share_high(self) -> float:
        """Every unknown second was an outage. A ceiling, always true."""
        if self.denominator_seconds <= 0:
            return 1.0
        return min(1.0, (self.out_seconds + self.unknown_seconds) / self.denominator_seconds)

    def point_estimate(
        self,
        max_unknown_share: float = DEFAULT_MAX_UNKNOWN_SHARE_FOR_POINT,
    ) -> float | None:
        """OUT over the time we actually know about — or None.

        Withheld unless the unknown share is small, because over a set selected
        by what we could see it is a conditional mean wearing a network's name.
        """
        if self.unknown_share > max_unknown_share:
            return None
        known = self.out_seconds + self.known_ok_seconds
        if known <= 0:
            return None
        return self.out_seconds / known

    def to_dict(self, max_unknown_share: float = DEFAULT_MAX_UNKNOWN_SHARE_FOR_POINT) -> dict:
        point = self.point_estimate(max_unknown_share)
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "population_id": self.population_id,
            "unit": "share_of_frame_elevator_station_service_hours",
            "denominator_hours": round(self.denominator_seconds / 3600, 3),
            "out_station_hours": round(self.out_seconds / 3600, 3),
            "out_station_hours_min": round(self.out_seconds_min / 3600, 3),
            "out_station_hours_max": round(self.out_seconds_max / 3600, 3),
            "known_ok_hours": round(self.known_ok_seconds / 3600, 3),
            "unknown_hours": round(self.unknown_seconds / 3600, 3),
            "unknown_share": round(self.unknown_share, 4),
            "unknown_hours_by_cause": {
                cause: round(seconds / 3600, 3)
                for cause, seconds in sorted(self.unknown_by_cause.items())
                if seconds > 0
            },
            "share_low": round(self.share_low, 6),
            "share_high": round(self.share_high, 6),
            "point_estimate": None if point is None else round(point, 6),
            "frame_station_count": self.frame_station_count,
            "equipped_station_count": self.equipped_station_count,
            "monitored_station_count": self.monitored_station_count,
            "stations_with_an_outage": len(self.stations_out),
            "stations_without_elevator_edge": self.stations_without_elevator_edge,
            "match_rate": round(self.match_rate, 4),
            "unmatched_source_ids": list(self.unmatched_source_ids)[:50],
            "out_of_scope_source_ids": list(self.out_of_scope_source_ids)[:50],
            **self.diagnostics,
        }


def denominator_seconds(
    population: Population,
    days: list[date],
    stations: list[str] | None = None,
) -> float:
    """Scheduled-service seconds over the equipped frame for a set of days.

    Service time, not clock time. A station is not accountable for its lifts at
    03:00 when nothing runs, and using 24 hours deflates every rate by roughly
    an eighth on a weekday — in one direction, using data already read.
    """
    keys = stations if stations is not None else sorted(population.equipped_keys)
    return sum(
        population.service_seconds(key, day) for key in keys for day in days
    )


def account(
    *,
    population: Population,
    crosswalk: CrosswalkReport,
    episodes: list[Episode],
    days: list[date],
    window_start: datetime,
    window_end: datetime,
    monitored_stations: set[str] | None = None,
    roster_complete: bool = False,
    source_current_seconds: float | None = None,
    as_of: datetime | None = None,
    population_id: str = "",
) -> Accounting:
    """Account for every frame station-second in a window.

    ``monitored_stations`` is the set of station keys we hold positive evidence
    the source reports on. Without it, every station is presumed unmonitored —
    which is the honest default, not a pessimistic one.

    ``roster_complete`` says the source published a complete station roster for
    this window. It is the gate on KNOWN_OK: a station where we watch three of
    sixteen lifts and see all three working is not a station we know is fine.
    """
    equipped = sorted(population.equipped_keys)
    denominator = denominator_seconds(population, days, equipped)

    monitored = set(monitored_stations or ())
    monitored_in_frame = sorted(monitored & set(equipped))

    # OUT — per station, the union of its lifts' intervals inside the window.
    intervals: dict[str, list[tuple[datetime, datetime]]] = {}
    intervals_min: dict[str, list[tuple[datetime, datetime]]] = {}
    intervals_max: dict[str, list[tuple[datetime, datetime]]] = {}
    for episode in episodes:
        resolution = crosswalk.resolutions.get(episode.station_id or "")
        if resolution is None or not resolution.matched:
            continue
        key = resolution.station_key
        if key not in population.equipped_keys:
            continue
        for bound, bucket in (
            ("mid", intervals), ("min", intervals_min), ("max", intervals_max)
        ):
            clipped = episode.clipped_interval(
                window_start, window_end, as_of=as_of, bound=bound
            )
            if clipped:
                bucket.setdefault(key, []).append(clipped)

    out_seconds = sum(union_seconds(v) for v in intervals.values())
    out_min = sum(union_seconds(v) for v in intervals_min.values())
    out_max = sum(union_seconds(v) for v in intervals_max.values())
    # Outage time can only be attributed inside the denominator it belongs to.
    out_seconds = min(out_seconds, denominator)
    out_min = min(out_min, denominator)
    out_max = min(out_max, denominator)

    # KNOWN_OK — only where evidence supports it, which today is nowhere.
    unknown: dict[str, float] = {}
    monitored_seconds = denominator_seconds(population, days, monitored_in_frame)
    unmonitored_seconds = max(0.0, denominator - monitored_seconds)
    if unmonitored_seconds > 0:
        unknown[CAUSE_NOT_MONITORED] = unmonitored_seconds

    remaining = max(0.0, monitored_seconds - out_seconds)
    if not roster_complete:
        known_ok = 0.0
        if remaining > 0:
            unknown[CAUSE_ROSTER_INCOMPLETE] = remaining
    else:
        covered = (
            remaining
            if source_current_seconds is None
            else max(0.0, min(remaining, source_current_seconds - out_seconds))
        )
        known_ok = covered
        if remaining - covered > 0:
            unknown[CAUSE_SOURCE_NOT_CURRENT] = remaining - covered

    unmatched_ids = tuple(
        crosswalk.ids_with_verdict("unmatched_malformed")
        + crosswalk.ids_with_verdict("unmatched_unknown_id")
    )
    if unmatched_ids:
        # A station we could not place is not a station without outages. Its
        # time is already inside one of the buckets above; the marker records
        # that some of what we saw could not be attributed at all.
        unknown[CAUSE_UNMATCHED_JOIN] = unknown.get(CAUSE_UNMATCHED_JOIN, 0.0)

    return Accounting(
        window_start=window_start,
        window_end=window_end,
        denominator_seconds=denominator,
        out_seconds=out_seconds,
        out_seconds_min=out_min,
        out_seconds_max=out_max,
        known_ok_seconds=known_ok,
        unknown_by_cause=unknown,
        frame_station_count=len(population.stations),
        equipped_station_count=len(equipped),
        monitored_station_count=len(monitored_in_frame),
        stations_out=tuple(sorted(intervals)),
        stations_without_elevator_edge=population.diagnostics.get(
            "in_frame_without_elevator_edge", 0
        ),
        unmatched_source_ids=unmatched_ids,
        out_of_scope_source_ids=tuple(crosswalk.ids_with_verdict("out_of_scope")),
        match_rate=crosswalk.match_rate,
        population_id=population_id,
        diagnostics={"roster_complete": roster_complete},
    )
