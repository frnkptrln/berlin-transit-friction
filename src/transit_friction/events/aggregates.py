"""Window metrics derived from episodes and coverage.

Every number here is accompanied by the coverage that produced it, and is
``None`` rather than ``0`` when the window was not watched well enough to
support it. A count that cannot distinguish "nothing broke" from "nobody
looked" is not a measurement.

Outage-hours, not poll counts: the unit has to be a property of the world, not
of our cron schedule.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from .config import DEFAULT_TUNING, TuningParameters
from .coverage import Coverage
from .episodes import Episode, union_seconds
from .records import require_aware
from .schema import FLAG_FLAPPING

UNIT = "outage-hours"

#: Storage is partitioned in UTC; meaning is reported in Berlin local time.
REPORTING_TZ = ZoneInfo("Europe/Berlin")


def local_day_window(
    day: date,
    tz: ZoneInfo = REPORTING_TZ,
) -> tuple[datetime, datetime]:
    """Midnight to midnight in the reporting timezone, as UTC instants.

    Berlin has a 23-hour day and a 25-hour day every year. A daily rate computed
    over a fixed 24-hour window is wrong on both, and comparing them to each
    other is wrong twice, which is why every summary carries ``window_hours``
    rather than assuming it.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = start + timedelta(days=1)
    # Adding a day in local time then normalising is what makes the DST jump
    # appear as a 23- or 25-hour window instead of being silently discarded.
    end = datetime(end.year, end.month, end.day, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def local_month_window(
    year: int,
    month: int,
    tz: ZoneInfo = REPORTING_TZ,
) -> tuple[datetime, datetime]:
    """First to first, in the reporting timezone."""
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _publishable(
    coverages: dict[str, Coverage],
    depends_on: frozenset[str],
    tuning: TuningParameters,
) -> bool:
    """A metric is only as trustworthy as the least-watched source it depends on.

    ``depends_on`` is the set of sources whose observations actually feed this
    metric — not every source that happens to be in the ledger. The distinction
    is not academic: with the previous ``all(coverages.values())`` a single
    once-daily reference ingest scored coverage 0.0 (nothing clears the 30-minute
    trust gap) and nulled every elevator figure on the dashboard, for a reason
    with nothing to do with elevators.

    A source a metric depends on but has no coverage for is a missing
    denominator, not a pass: the metric is unpublishable.
    """
    if not depends_on:
        return False
    return all(
        source in coverages and coverages[source].publishable(tuning)
        for source in depends_on
    )


def build_window_summary(
    episodes: list[Episode],
    coverages: dict[str, Coverage],
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime | None = None,
    depends_on: Iterable[str] | None = None,
    tuning: TuningParameters = DEFAULT_TUNING,
) -> dict:
    """Summarise one window, stating its unit, coverage and uncertainty.

    ``depends_on`` names the observation sources this metric is computed from.
    It defaults to every source in ``coverages``, which is right only when the
    caller has already narrowed the dict to the metric's own sources.
    """
    require_aware(window_start, "window_start")
    require_aware(window_end, "window_end")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")

    window_hours = (window_end - window_start).total_seconds() / 3600

    # Flapping entities stay in the record but out of the headline: six state
    # changes in a day is a source problem, not an elevator.
    #
    # But the flag alone is not enough to delete an episode. Quality flags are
    # unioned across every transition in an episode, so one bouncing sensor
    # during a technician's visit would otherwise erase a three-week outage and
    # report it as a single "quarantined episode" — an exclusion pushing the
    # headline down by weeks. An episode is quarantined only when its own shape
    # is intermittent: it must carry the flag AND have actually reopened.
    def _quarantined(episode: Episode) -> bool:
        return (
            FLAG_FLAPPING in episode.quality_flags
            and episode.reopen_count >= tuning.quarantine_min_reopens
        )

    headline = [episode for episode in episodes if not _quarantined(episode)]
    quarantined = [
        episode
        for episode in episodes
        if _quarantined(episode)
        and (
            episode.overlap_seconds(window_start, window_end, as_of=as_of) > 0
            or episode.unknown_seconds_in(window_start, window_end) > 0
        )
    ]
    # An exclusion that does not report what it removed is indistinguishable
    # from an absence of outages. These hours are published, with the stations.
    quarantined_intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    quarantined_names: dict[str, str] = {}
    for episode in quarantined:
        clipped = episode.clipped_interval(window_start, window_end, as_of=as_of)
        if clipped:
            station = episode.station_id or "unknown"
            quarantined_intervals[station].append(clipped)
            if episode.station_name:
                quarantined_names.setdefault(station, episode.station_name)
    quarantined_hours = sum(
        union_seconds(v) for v in quarantined_intervals.values()
    ) / 3600

    # Per station, the intervals its lifts were out — kept as intervals so they
    # can be unioned. Summing them would answer "lift-hours lost" while wearing
    # the label "station-hours", which is eight times too large at a station
    # with eight lifts out together.
    intervals_by_station: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    intervals_min: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    intervals_max: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    names_by_station: dict[str, str] = {}
    lift_seconds = 0.0
    unobserved_seconds = 0.0
    uncertain = 0
    active_at_end = 0
    touching = 0
    for episode in headline:
        seconds = episode.overlap_seconds(window_start, window_end, as_of=as_of)
        blind = episode.unknown_seconds_in(window_start, window_end)
        if seconds <= 0 and blind <= 0:
            # An episode that neither ran nor blinded us during this window is
            # not part of it. Counting every episode ever seen would report the
            # same figure on a day when nothing happened.
            continue
        touching += 1
        if seconds > 0:
            station = episode.station_id or "unknown"
            if episode.station_name:
                names_by_station.setdefault(station, episode.station_name)
            lift_seconds += seconds
            for bound, bucket in (
                ("mid", intervals_by_station),
                ("min", intervals_min),
                ("max", intervals_max),
            ):
                clipped = episode.clipped_interval(
                    window_start, window_end, as_of=as_of, bound=bound
                )
                if clipped:
                    bucket[station].append(clipped)
        if blind > 0:
            unobserved_seconds += blind
            uncertain += 1
        if episode.ongoing or (
            episode.closed_t_latest and episode.closed_t_latest >= window_end
        ):
            active_at_end += 1

    hours_by_station = {
        station: union_seconds(intervals) / 3600
        for station, intervals in intervals_by_station.items()
    }
    total_seconds = sum(hours_by_station.values()) * 3600
    total_seconds_min = sum(
        union_seconds(v) for v in intervals_min.values()
    )
    total_seconds_max = sum(
        union_seconds(v) for v in intervals_max.values()
    )

    dependencies = frozenset(depends_on if depends_on is not None else coverages)
    publishable = _publishable(coverages, dependencies, tuning)

    def _value(value):
        return value if publishable else None

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_hours": round(window_hours, 4),
        "unit": UNIT,
        "station_hours_are_unions": True,
        "publishable": publishable,
        "episode_count": _value(touching),
        "active_at_window_end": _value(active_at_end),
        # Station-hours: a station counts once however many of its lifts are out.
        "total_outage_hours": _value(round(total_seconds / 3600, 3)),
        # Lift-hours: the same time summed per lift. A different question, kept
        # under a different name so the two can never be confused.
        "total_lift_outage_hours": _value(round(lift_seconds / 3600, 3)),
        # The bounds are not decoration. Polling cannot date a change to the
        # second, so the honest figure is a range and the point estimate is the
        # midpoint of it.
        "total_outage_hours_min": _value(round(total_seconds_min / 3600, 3)),
        "total_outage_hours_max": _value(round(total_seconds_max / 3600, 3)),
        "outage_hours_by_station": _value(
            {
                station: round(hours, 3)
                for station, hours in sorted(hours_by_station.items())
            }
        ),
        "station_names": dict(sorted(names_by_station.items())),
        "episodes_with_unobserved_time": _value(uncertain),
        "unobserved_outage_hours": _value(round(unobserved_seconds / 3600, 3)),
        "coverage": {
            source: coverage.to_dict(tuning)
            for source, coverage in sorted(coverages.items())
        },
        "data_quality": {
            "quarantined_flapping_episodes": len(quarantined),
            "quarantined_station_hours": round(quarantined_hours, 3),
            "quarantined_stations": {
                station: quarantined_names.get(station, station)
                for station in sorted(quarantined_intervals)
            },
            "sources_used": sorted(dependencies),
            "sources_observed": sorted(coverages),
            "sources_with_episodes": sorted(
                {episode.source_id for episode in headline}
            ),
        },
        "tuning_fingerprint": tuning.fingerprint(),
    }
