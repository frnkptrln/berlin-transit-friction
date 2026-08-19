"""Append-only event layer: state transitions and the ledger of our looking.

See ``docs/data-architecture.md``. Two permanent tables:

``transitions``
    An entity's known state changed.
``observations``
    We attempted to look at a source, and this is what happened.

Neither is derivable from the other, which is why a missing poll reads as
``unknown`` rather than as "nothing was wrong".
"""

from __future__ import annotations

from .aggregates import build_window_summary
from .config import DEFAULT_TUNING, TuningParameters
from .coverage import Coverage, Gap, compute_coverage, value_or_null
from .detect import (
    DetectionResult,
    ObservedEntity,
    PendingChange,
    SourceSnapshot,
    detect,
)
from .episodes import Episode, build_episodes
from .identity import entity_uid, episode_id, observation_id, transition_uid
from .records import Observation, Transition
from .schema import (
    SCHEMA_VERSION,
    STATE_IMPAIRED,
    STATE_OK,
    STATE_UNKNOWN,
)
from .state import (
    EntityState,
    SourceCursor,
    effective_state,
    fold_cursors,
    fold_transitions,
    open_entities,
)

__all__ = [
    "Coverage",
    "DEFAULT_TUNING",
    "DetectionResult",
    "EntityState",
    "Episode",
    "Gap",
    "Observation",
    "ObservedEntity",
    "PendingChange",
    "SCHEMA_VERSION",
    "STATE_IMPAIRED",
    "STATE_OK",
    "STATE_UNKNOWN",
    "SourceCursor",
    "SourceSnapshot",
    "Transition",
    "TuningParameters",
    "build_episodes",
    "build_window_summary",
    "compute_coverage",
    "detect",
    "effective_state",
    "entity_uid",
    "episode_id",
    "fold_cursors",
    "fold_transitions",
    "observation_id",
    "open_entities",
    "transition_uid",
    "value_or_null",
]
