"""Tuning parameters for transition detection.

Changing any value here changes the measurement, not just the code. Every
aggregate records :meth:`TuningParameters.fingerprint` so a published number can
always be traced back to the thresholds that produced it. See
``docs/event-schema.md`` section 5.5.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class TuningParameters:
    # Opening is responsive, closing is conservative: a false close splits one
    # outage into several, which inflates counts and deflates durations.
    confirm_open_n: int = 1
    confirm_open_s: int = 0
    confirm_close_n: int = 2
    confirm_close_s: int = 600

    # An entity returning to impaired inside this window continues the previous
    # episode instead of starting a new one.
    reopen_merge_window_s: int = 1800

    flap_quarantine_n: int = 6
    flap_quarantine_window_s: int = 86400

    # Beyond this gap we stop claiming to know an entity's state.
    max_trust_gap_s: int = 1800
    # A source whose own timestamp has not advanced for this long is stuck, which
    # is not the same as "nothing is wrong".
    max_source_stale_s: int = 3600

    retire_after_s: int = 2592000
    min_publish_coverage: float = 0.9

    def __post_init__(self) -> None:
        if self.confirm_open_n < 1 or self.confirm_close_n < 1:
            raise ValueError("confirmation counts must be >= 1")
        if self.confirm_open_s < 0 or self.confirm_close_s < 0:
            raise ValueError("confirmation dwell times must be >= 0")
        if self.max_trust_gap_s <= 0:
            raise ValueError("max_trust_gap_s must be > 0")
        if not 0 <= self.min_publish_coverage <= 1:
            raise ValueError("min_publish_coverage must be within [0, 1]")

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


DEFAULT_TUNING = TuningParameters()
