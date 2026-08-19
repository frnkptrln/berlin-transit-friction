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
from .monitoring import Monitoring, SourceMonitoring, from_fault_listings

#: Causes of not knowing, kept apart. "We were not polling" and "the source does
#: not cover this station" are different blindnesses with different remedies,
#: and summing them into one coverage number hides both.
CAUSE_NOT_MONITORED = "not_monitored"
CAUSE_ROSTER_INCOMPLETE = "roster_incomplete"
CAUSE_MONITORING_STALE = "monitoring_stale"
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
            "monitoring": self.diagnostics.get("monitoring", {}),
            "unmatched_source_ids": list(self.unmatched_source_ids)[:50],
            "out_of_scope_source_ids": list(self.out_of_scope_source_ids)[:50],
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
    monitoring: Monitoring | None = None,
    monitored_stations: set[str] | None = None,
    roster_complete: bool = False,
    source_current_seconds: float | None = None,
    as_of: datetime | None = None,
    population_id: str = "",
) -> Accounting:
    """Account for every frame station-second in a window.

    ``monitoring`` carries per-source, typed evidence of which stations each
    status source can speak about. Without it, every station is presumed
    unmonitored — the honest default, not a pessimistic one.

    ``monitored_stations`` and ``roster_complete`` are a convenience for the
    single-source case; they build a ``Monitoring`` internally. Passing
    ``roster_complete=False`` with a set of stations means exactly what a
    broken-lifts page gives us: proof the source covers those stations, and no
    evidence whatsoever that any of them is working.
    """
    equipped = sorted(population.equipped_keys)
    denominator = denominator_seconds(population, days, equipped)
    reference = as_of or window_end

    if monitoring is None:
        stations = set(monitored_stations or ())
        if roster_complete:
            source = SourceMonitoring(
                source_id="default",
                evidence={
                    key: ("roster_entry", reference) for key in stations
                },
                roster_complete=True,
            )
        else:
            source = from_fault_listings("default", stations, reference)
        monitoring = Monitoring(sources={"default": source})

    equipped_set = set(equipped)
    covered = {
        key: kind
        for key, kind in monitoring.covered(reference).items()
        if key in equipped_set
    }
    eligible = monitoring.known_ok_eligible(reference) & equipped_set
    stale = monitoring.stale(reference) & equipped_set
    monitored_in_frame = sorted(covered)

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

    # Account per station, so the three states partition the denominator exactly.
    # Aggregating first double-counted outage seconds as unknown, which put the
    # ceiling at 1.0 for a reason that was arithmetic rather than ignorance.
    unknown: dict[str, float] = {}
    out_seconds = out_min = out_max = 0.0
    known_ok = 0.0
    for station in equipped:
        station_denominator = denominator_seconds(population, days, [station])
        if station_denominator <= 0:
            continue
        # An outage outside a station's service hours is clamped here, not
        # globally: the numerator has to sit inside its own denominator.
        station_out = min(
            union_seconds(intervals.get(station, [])), station_denominator
        )
        out_seconds += station_out
        out_min += min(union_seconds(intervals_min.get(station, [])), station_denominator)
        out_max += min(union_seconds(intervals_max.get(station, [])), station_denominator)

        rest = station_denominator - station_out
        if rest <= 0:
            continue
        if station in stale:
            cause = CAUSE_MONITORING_STALE
        elif station not in covered:
            cause = CAUSE_NOT_MONITORED
        elif station not in eligible:
            cause = CAUSE_ROSTER_INCOMPLETE
        else:
            known_ok += rest
            continue
        unknown[cause] = unknown.get(cause, 0.0) + rest

    if source_current_seconds is not None and known_ok > 0:
        watched = max(0.0, min(known_ok, source_current_seconds - out_seconds))
        if known_ok - watched > 0:
            unknown[CAUSE_SOURCE_NOT_CURRENT] = (
                unknown.get(CAUSE_SOURCE_NOT_CURRENT, 0.0) + (known_ok - watched)
            )
        known_ok = watched

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
        diagnostics={"monitoring": monitoring.to_dict(reference)},
    )
