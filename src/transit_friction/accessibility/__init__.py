"""Accessibility-focused reboot of Transit Friction.

Source-specific: parsing the BrokenLifts outage page and adapting it into the
generic event vocabulary. Lifecycle decisions — what counts as a change, what
may close an outage, how flapping is damped — live in
``transit_friction.events`` and are shared with every other source.
"""

from .adapter import SOURCE_ID, to_source_snapshot
from .models import ElevatorOutageObservation, OutageSnapshot
from .parser import parse_brokenlifts_snapshot

__all__ = [
    "ElevatorOutageObservation",
    "OutageSnapshot",
    "SOURCE_ID",
    "parse_brokenlifts_snapshot",
    "to_source_snapshot",
]
