"""Which stations a status source can actually speak about, and how strongly.

Two status sources are not interchangeable, and the difference decides what may
be published:

**An inventory source** enumerates facilities and reports a state for each. When
it is current and complete, a station it does not flag is a station we have
positive evidence about — it can be ``KNOWN_OK``.

**A fault-list source** publishes only what is currently broken. Absence from
that list is not an observation; it is a default. Such a source can open and
sustain an outage, and can prove it *covers* a station when it names one, but it
can never make a station known-good. Importing its silence as health is the
single most flattering error available to this project.

So monitoring evidence is typed, per source, per station, and it expires. A
station whose evidence has gone stale moves to ``UNKNOWN``, never to a
structural zero in the numerator — otherwise a source quietly dropping half the
network would look like the network improving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: The source enumerates this station as part of an inventory it claims is
#: complete. Only this kind can support KNOWN_OK.
EVIDENCE_ROSTER = "roster_entry"

#: The source reported a state for this station specifically.
EVIDENCE_STATUS = "status_report"

#: The station appeared in a list of current faults. Proves coverage, and
#: nothing about the station when it is absent.
EVIDENCE_FAULT_LISTING = "fault_listing"

#: Strength order. A station's strongest evidence decides what it may support.
EVIDENCE_STRENGTH = {
    EVIDENCE_FAULT_LISTING: 1,
    EVIDENCE_STATUS: 2,
    EVIDENCE_ROSTER: 3,
}

#: How long evidence that a source covers a station stays good. Long enough that
#: a weekly roster does not expire between fetches; short enough that a source
#: silently losing an operator's feed becomes visible within a quarter.
DEFAULT_EVIDENCE_MAX_AGE_S = 90 * 86400


@dataclass(frozen=True, slots=True)
class SourceMonitoring:
    """What one status source demonstrably covers, and how completely."""

    source_id: str
    #: station_key -> (evidence kind, when we last saw it)
    evidence: dict[str, tuple[str, datetime]] = field(default_factory=dict)
    #: True only when the source publishes an inventory it claims is complete
    #: AND we successfully read it for this window.
    roster_complete: bool = False
    #: When the source was last current, if it is a polled source.
    last_current_at: datetime | None = None

    def fresh_stations(
        self,
        as_of: datetime,
        max_age_s: int = DEFAULT_EVIDENCE_MAX_AGE_S,
    ) -> dict[str, str]:
        """Stations with unexpired evidence, mapped to their evidence kind."""
        cutoff = as_of - timedelta(seconds=max_age_s)
        return {
            station: kind
            for station, (kind, seen) in self.evidence.items()
            if seen >= cutoff
        }

    def stale_stations(
        self,
        as_of: datetime,
        max_age_s: int = DEFAULT_EVIDENCE_MAX_AGE_S,
    ) -> set[str]:
        cutoff = as_of - timedelta(seconds=max_age_s)
        return {
            station for station, (_, seen) in self.evidence.items() if seen < cutoff
        }

    def can_support_known_ok(self) -> bool:
        return self.roster_complete


@dataclass(frozen=True, slots=True)
class Monitoring:
    """Every status source's coverage, combined without being blended.

    Sources are kept apart on purpose. "Nobody reports on this station" and
    "a source reports on it but only ever lists faults" are different states of
    knowledge, and collapsing them into a single monitored/unmonitored flag
    loses exactly the distinction that decides whether a rate may be published.
    """

    sources: dict[str, SourceMonitoring] = field(default_factory=dict)
    max_age_s: int = DEFAULT_EVIDENCE_MAX_AGE_S

    def covered(self, as_of: datetime) -> dict[str, str]:
        """Station -> strongest unexpired evidence kind across all sources."""
        strongest: dict[str, str] = {}
        for source in self.sources.values():
            for station, kind in source.fresh_stations(as_of, self.max_age_s).items():
                current = strongest.get(station)
                if current is None or EVIDENCE_STRENGTH[kind] > EVIDENCE_STRENGTH[current]:
                    strongest[station] = kind
        return strongest

    def known_ok_eligible(self, as_of: datetime) -> set[str]:
        """Stations some complete-inventory source vouches for.

        A station only a fault list covers is never here: its silence is a
        default, not an observation.
        """
        eligible: set[str] = set()
        for source in self.sources.values():
            if not source.can_support_known_ok():
                continue
            eligible |= {
                station
                for station, kind in source.fresh_stations(as_of, self.max_age_s).items()
                if EVIDENCE_STRENGTH[kind] >= EVIDENCE_STRENGTH[EVIDENCE_STATUS]
            }
        return eligible

    def stale(self, as_of: datetime) -> set[str]:
        """Stations whose evidence expired everywhere it existed."""
        fresh = set(self.covered(as_of))
        stale: set[str] = set()
        for source in self.sources.values():
            stale |= source.stale_stations(as_of, self.max_age_s)
        return stale - fresh

    def by_source(self, as_of: datetime) -> dict[str, int]:
        return {
            source_id: len(source.fresh_stations(as_of, self.max_age_s))
            for source_id, source in sorted(self.sources.items())
        }

    def to_dict(self, as_of: datetime) -> dict:
        covered = self.covered(as_of)
        kinds: dict[str, int] = {}
        for kind in covered.values():
            kinds[kind] = kinds.get(kind, 0) + 1
        return {
            "stations_covered": len(covered),
            "stations_by_evidence_kind": dict(sorted(kinds.items())),
            "stations_by_source": self.by_source(as_of),
            "stations_known_ok_eligible": len(self.known_ok_eligible(as_of)),
            "stations_with_stale_evidence": len(self.stale(as_of)),
            "sources_with_complete_roster": sorted(
                s for s, m in self.sources.items() if m.can_support_known_ok()
            ),
        }


def from_fault_listings(
    source_id: str,
    station_keys: set[str],
    observed_at: datetime,
) -> SourceMonitoring:
    """Coverage inferred from a fault list — a lower bound, never a roster.

    This is what a "broken lifts" page gives us. It proves the source can speak
    about the stations it named, and says nothing at all about the rest.
    """
    return SourceMonitoring(
        source_id=source_id,
        evidence={key: (EVIDENCE_FAULT_LISTING, observed_at) for key in station_keys},
        roster_complete=False,
    )


def from_roster(
    source_id: str,
    station_keys: set[str],
    observed_at: datetime,
    *,
    complete: bool = True,
    last_current_at: datetime | None = None,
) -> SourceMonitoring:
    """Coverage from an inventory the source publishes.

    ``complete=False`` records an inventory we believe is partial — it still
    beats a fault list for coverage, but it cannot make anything known-good.
    """
    return SourceMonitoring(
        source_id=source_id,
        evidence={key: (EVIDENCE_ROSTER, observed_at) for key in station_keys},
        roster_complete=complete,
        last_current_at=last_current_at,
    )
