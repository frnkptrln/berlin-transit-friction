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
from datetime import datetime

from .config import DEFAULT_TUNING, TuningParameters
from .coverage import Coverage
from .episodes import Episode
from .records import require_aware
from .schema import FLAG_FLAPPING

UNIT = "outage-hours"


def _publishable(
    coverages: dict[str, Coverage],
    tuning: TuningParameters,
) -> bool:
    """A metric is only as trustworthy as the least-watched source behind it.

    Publishability depends on the sources the metric *depends on*, never on the
    sources that happened to produce an episode. Deriving it from the episodes
    would make a fully watched day with nothing broken indistinguishable from a
    day nobody watched — which is the one confusion this whole layer exists to
    prevent.
    """
    if not coverages:
        return False
    return all(coverage.publishable(tuning) for coverage in coverages.values())


def build_window_summary(
    episodes: list[Episode],
    coverages: dict[str, Coverage],
    *,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime | None = None,
    tuning: TuningParameters = DEFAULT_TUNING,
) -> dict:
    """Summarise one window, stating its unit, coverage and uncertainty."""
    require_aware(window_start, "window_start")
    require_aware(window_end, "window_end")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")

    window_hours = (window_end - window_start).total_seconds() / 3600

    # Flapping entities stay in the record but out of the headline: six state
    # changes in a day is a source problem, not an elevator.
    headline = [
        episode
        for episode in episodes
        if FLAG_FLAPPING not in episode.quality_flags
    ]
    quarantined = [episode for episode in episodes if episode not in headline]

    hours_by_station: dict[str, float] = defaultdict(float)
    total_seconds = 0.0
    uncertain = 0
    active_at_end = 0
    for episode in headline:
        seconds = episode.overlap_seconds(window_start, window_end, as_of=as_of)
        if seconds <= 0:
            continue
        hours_by_station[episode.station_id or "unknown"] += seconds / 3600
        total_seconds += seconds
        if not episode.certain:
            uncertain += 1
        if episode.ongoing or (
            episode.closed_t_latest and episode.closed_t_latest >= window_end
        ):
            active_at_end += 1

    publishable = _publishable(coverages, tuning)

    def _value(value):
        return value if publishable else None

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_hours": round(window_hours, 4),
        "unit": UNIT,
        "publishable": publishable,
        "episode_count": _value(len(headline)),
        "active_at_window_end": _value(active_at_end),
        "total_outage_hours": _value(round(total_seconds / 3600, 3)),
        "outage_hours_by_station": _value(
            {
                station: round(hours, 3)
                for station, hours in sorted(hours_by_station.items())
            }
        ),
        "episodes_with_unobserved_time": _value(uncertain),
        "coverage": {
            source: coverage.to_dict(tuning)
            for source, coverage in sorted(coverages.items())
        },
        "data_quality": {
            "quarantined_flapping_episodes": len(quarantined),
            "sources_used": sorted(coverages),
            "sources_with_episodes": sorted(
                {episode.source_id for episode in headline}
            ),
        },
        "tuning_fingerprint": tuning.fingerprint(),
    }
