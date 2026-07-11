from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .lifecycle import ActiveOutage
from .models import require_aware


def overlap_hours(
    outage: ActiveOutage,
    *,
    window_start: datetime,
    window_end: datetime,
) -> float:
    require_aware(window_start, "window_start")
    require_aware(window_end, "window_end")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")

    interval_start = max(outage.first_seen_at, window_start)
    interval_end = min(outage.resolved_at or window_end, window_end)
    if interval_end <= interval_start:
        return 0.0
    return (interval_end - interval_start).total_seconds() / 3600


def build_window_summary(
    outages: list[ActiveOutage],
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict:
    hours_by_station: dict[str, float] = defaultdict(float)
    active_at_end = 0
    for outage in outages:
        hours_by_station[outage.station_id] += overlap_hours(
            outage,
            window_start=window_start,
            window_end=window_end,
        )
        if outage.first_seen_at < window_end and (
            outage.resolved_at is None or outage.resolved_at >= window_end
        ):
            active_at_end += 1

    total_hours = sum(hours_by_station.values())
    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "unit": "outage-hours",
        "outage_count": len(outages),
        "active_at_window_end": active_at_end,
        "total_outage_hours": round(total_hours, 3),
        "outage_hours_by_station": {
            station_id: round(hours, 3)
            for station_id, hours in sorted(hours_by_station.items())
        },
    }
