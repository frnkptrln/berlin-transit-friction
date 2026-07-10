"""Accessibility-focused reboot of Transit Friction.

The package is intentionally independent from the legacy friction-event model.
It models observed elevator outages as intervals with explicit source coverage.
"""

from .lifecycle import ActiveOutage, ReconcileResult, reconcile
from .models import ElevatorOutageObservation, OutageSnapshot
from .parser import parse_brokenlifts_snapshot

__all__ = [
    "ActiveOutage",
    "ElevatorOutageObservation",
    "OutageSnapshot",
    "ReconcileResult",
    "parse_brokenlifts_snapshot",
    "reconcile",
]
