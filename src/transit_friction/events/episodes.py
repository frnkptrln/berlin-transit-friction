"""Episodes: the fold from transitions to intervals.

Not stored as truth. Rebuilt on demand from the ledger, because the ledger keeps
what we believed and when, while this view keeps the best current reading.

Every duration here is a range. Polling cannot produce a point, so an episode
reports ``duration_min`` and ``duration_max`` and a midpoint estimate, and an
episode that spent time in ``unknown`` says how much.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .records import Transition
from .schema import (
    STATE_OK,
    STATE_UNKNOWN,
    TRANSITION_CORRECTION,
    TRANSITION_REOPENED,
    TRANSITION_UNKNOWN_ENTERED,
    TRANSITION_UNKNOWN_EXITED,
)


@dataclass(frozen=True, slots=True)
class Episode:
    """One continuous impairment, including any internal loss of sight."""

    episode_id: str
    entity_uid: str
    entity_type: str
    source_id: str
    source_native_id: str
    opened_t_earliest: datetime
    opened_t_latest: datetime
    closed_t_earliest: datetime | None
    closed_t_latest: datetime | None
    duration_min_s: float
    duration_max_s: float | None
    unknown_intervals: tuple[tuple[datetime, datetime], ...]
    internal_ok_seconds: float
    reopen_count: int
    station_id: str | None = None
    station_name: str | None = None
    line_id: str | None = None
    quality_flags: tuple[str, ...] = ()

    @property
    def ongoing(self) -> bool:
        return self.closed_t_latest is None

    @property
    def unknown_seconds(self) -> float:
        return sum(
            (end - start).total_seconds() for start, end in self.unknown_intervals
        )

    def unknown_seconds_in(
        self,
        window_start: datetime,
        window_end: datetime,
    ) -> float:
        """Blind time inside one window.

        An episode spanning a week must not report a Tuesday outage as having
        made Thursday uncertain, so the intervals are clipped rather than
        summed whole.
        """
        total = 0.0
        for start, end in self.unknown_intervals:
            lo, hi = max(start, window_start), min(end, window_end)
            if hi > lo:
                total += (hi - lo).total_seconds()
        return total

    @property
    def duration_point_s(self) -> float | None:
        """Midpoint of the bracket — only meaningful together with the bounds."""
        if self.duration_max_s is None:
            return None
        return (self.duration_min_s + self.duration_max_s) / 2

    @property
    def certain(self) -> bool:
        """False if any part of the episode was unobserved."""
        return self.unknown_seconds == 0 and not self.ongoing

    def _extent(self, bound: str, as_of: datetime | None) -> tuple[datetime, datetime]:
        """The shortest, midpoint, or longest reading of this episode's extent."""
        if bound == "min":
            start = self.opened_t_latest
            end = self.closed_t_earliest
        elif bound == "max":
            start = self.opened_t_earliest
            end = self.closed_t_latest
        else:
            start = self.opened_t_earliest + (
                self.opened_t_latest - self.opened_t_earliest
            ) / 2
            end = (
                None
                if self.closed_t_earliest is None
                else self.closed_t_earliest
                + (self.closed_t_latest - self.closed_t_earliest) / 2
            )
        return start, end

    def overlap_seconds(
        self,
        window_start: datetime,
        window_end: datetime,
        as_of: datetime | None = None,
        bound: str = "mid",
    ) -> float:
        """Seconds of this episode falling inside a window.

        ``bound`` picks which reading of the brackets to use. The default
        midpoint is the only choice that does not systematically bias durations
        up or down; ``min`` and ``max`` give the range the observations actually
        support, which is what an honest chart plots around the line.
        """
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        start, end = self._extent(bound, as_of)
        if end is None:
            end = as_of or window_end
        lo, hi = max(start, window_start), min(end, window_end)
        return max(0.0, (hi - lo).total_seconds())

    def overlap_bounds(
        self,
        window_start: datetime,
        window_end: datetime,
        as_of: datetime | None = None,
    ) -> tuple[float, float, float]:
        """(shortest, midpoint, longest) seconds inside a window."""
        return (
            self.overlap_seconds(window_start, window_end, as_of, "min"),
            self.overlap_seconds(window_start, window_end, as_of, "mid"),
            self.overlap_seconds(window_start, window_end, as_of, "max"),
        )


def build_episodes(
    transitions: Iterable[Transition],
    as_of: datetime | None = None,
) -> list[Episode]:
    """Group transitions into episodes.

    ``as_of`` bounds the minimum duration of still-open episodes. An open
    episode is never closed at a window boundary for tidiness; it is reported as
    "ongoing, at least ``duration_min_s``".
    """
    rows = sorted(transitions, key=lambda row: row.causal_key)
    corrected = {
        row.corrects_transition_uid
        for row in rows
        if row.transition_type == TRANSITION_CORRECTION and row.corrects_transition_uid
    }

    grouped: dict[str, list[Transition]] = {}
    for row in rows:
        if row.transition_uid in corrected:
            continue
        grouped.setdefault(row.episode_id, []).append(row)

    episodes: list[Episode] = []
    for episode_id_value, group in grouped.items():
        opener = group[0]
        # An episode ends whenever we reach 'ok', whether by observing the entity
        # absent from a complete snapshot ('closed') or by regaining sight after
        # a gap and finding it gone ('unknown_exited').
        closer = group[-1] if group[-1].to_state == STATE_OK else None

        unknown_intervals: list[tuple[datetime, datetime]] = []
        unknown_since: datetime | None = None
        internal_ok_seconds = 0.0
        ok_since: datetime | None = None
        reopen_count = 0
        flags: list[str] = []

        for row in group:
            flags.extend(row.quality_flags)
            if row.transition_type == TRANSITION_UNKNOWN_ENTERED:
                unknown_since = row.t_latest
            elif row.transition_type == TRANSITION_UNKNOWN_EXITED:
                if unknown_since is not None:
                    unknown_intervals.append((unknown_since, row.t_latest))
                    unknown_since = None
                if row.to_state == STATE_UNKNOWN:
                    unknown_since = row.t_latest
            elif row.to_state == STATE_OK:
                ok_since = row.t_latest
            elif row.transition_type == TRANSITION_REOPENED:
                reopen_count += 1
                if ok_since is not None:
                    internal_ok_seconds += (row.t_latest - ok_since).total_seconds()
                    ok_since = None

        reference = as_of or group[-1].t_latest
        if unknown_since is not None and closer is None and reference > unknown_since:
            unknown_intervals.append((unknown_since, reference))

        if closer is None:
            duration_min = max(0.0, (reference - opener.t_latest).total_seconds())
            duration_max = None
            closed_earliest = closed_latest = None
        else:
            closed_earliest, closed_latest = closer.t_earliest, closer.t_latest
            duration_min = max(
                0.0, (closed_earliest - opener.t_latest).total_seconds()
            )
            duration_max = max(
                0.0, (closed_latest - opener.t_earliest).total_seconds()
            )

        episodes.append(
            Episode(
                episode_id=episode_id_value,
                entity_uid=opener.entity_uid,
                entity_type=opener.entity_type,
                source_id=opener.source_id,
                source_native_id=opener.source_native_id,
                opened_t_earliest=opener.t_earliest,
                opened_t_latest=opener.t_latest,
                closed_t_earliest=closed_earliest,
                closed_t_latest=closed_latest,
                duration_min_s=duration_min,
                duration_max_s=duration_max,
                unknown_intervals=tuple(unknown_intervals),
                internal_ok_seconds=internal_ok_seconds,
                reopen_count=reopen_count,
                station_id=opener.station_id,
                station_name=opener.station_name,
                line_id=opener.line_id,
                quality_flags=tuple(dict.fromkeys(flags)),
            )
        )

    return sorted(episodes, key=lambda item: (item.opened_t_latest, item.episode_id))
