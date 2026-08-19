"""Vocabulary and validation rules for the events layer.

The enumerations here are the schema. In particular :data:`CLOSING_EVIDENCE`
encodes the invariant the whole architecture exists to protect: a failed,
incomplete, or stale observation can never close an outage.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# --- entity state -----------------------------------------------------------

STATE_OK = "ok"
STATE_IMPAIRED = "impaired"
STATE_UNKNOWN = "unknown"

STATES = frozenset({STATE_OK, STATE_IMPAIRED, STATE_UNKNOWN})

# --- transitions ------------------------------------------------------------

TRANSITION_OPENED = "opened"
TRANSITION_CLOSED = "closed"
TRANSITION_UNKNOWN_ENTERED = "unknown_entered"
TRANSITION_UNKNOWN_EXITED = "unknown_exited"
TRANSITION_REOPENED = "reopened"
TRANSITION_ATTRIBUTES_CHANGED = "attributes_changed"
TRANSITION_RETIRED = "retired"
TRANSITION_CORRECTION = "correction"

TRANSITION_TYPES = frozenset(
    {
        TRANSITION_OPENED,
        TRANSITION_CLOSED,
        TRANSITION_UNKNOWN_ENTERED,
        TRANSITION_UNKNOWN_EXITED,
        TRANSITION_REOPENED,
        TRANSITION_ATTRIBUTES_CHANGED,
        TRANSITION_RETIRED,
        TRANSITION_CORRECTION,
    }
)

# --- certainty --------------------------------------------------------------

CERTAINTY_OBSERVED = "observed"
CERTAINTY_BOUNDED = "bounded"
CERTAINTY_INFERRED = "inferred"

CERTAINTIES = frozenset({CERTAINTY_OBSERVED, CERTAINTY_BOUNDED, CERTAINTY_INFERRED})

# --- evidence ---------------------------------------------------------------

EVIDENCE_LISTED_IN_COMPLETE_SNAPSHOT = "listed_in_complete_snapshot"
EVIDENCE_ABSENT_FROM_COMPLETE_SNAPSHOT = "absent_from_complete_snapshot"
EVIDENCE_SOURCE_EXPLICIT_RESOLUTION = "source_explicit_resolution"
EVIDENCE_COVERAGE_LOST = "coverage_lost"
EVIDENCE_SOURCE_DEGRADED = "source_degraded"
EVIDENCE_SOURCE_STALE = "source_stale"
EVIDENCE_COVERAGE_RESTORED = "coverage_restored"
EVIDENCE_FLAP_CORRECTION = "flap_correction"
EVIDENCE_RETENTION_POLICY = "retention_policy"
EVIDENCE_MANUAL_CORRECTION = "manual_correction"

EVIDENCES = frozenset(
    {
        EVIDENCE_LISTED_IN_COMPLETE_SNAPSHOT,
        EVIDENCE_ABSENT_FROM_COMPLETE_SNAPSHOT,
        EVIDENCE_SOURCE_EXPLICIT_RESOLUTION,
        EVIDENCE_COVERAGE_LOST,
        EVIDENCE_SOURCE_DEGRADED,
        EVIDENCE_SOURCE_STALE,
        EVIDENCE_COVERAGE_RESTORED,
        EVIDENCE_FLAP_CORRECTION,
        EVIDENCE_RETENTION_POLICY,
        EVIDENCE_MANUAL_CORRECTION,
    }
)

#: The only evidence values that may accompany a ``closed`` transition. There is
#: deliberately no value here for a timeout, a parse error, an incomplete list,
#: or a stale feed. A gap suspends knowledge; it never supplies good news.
CLOSING_EVIDENCE = frozenset(
    {
        EVIDENCE_ABSENT_FROM_COMPLETE_SNAPSHOT,
        EVIDENCE_SOURCE_EXPLICIT_RESOLUTION,
    }
)

#: Only a complete snapshot may open an outage, for the same reason: partial
#: lists are not evidence about the entities missing from them.
OPENING_EVIDENCE = frozenset(
    {
        EVIDENCE_LISTED_IN_COMPLETE_SNAPSHOT,
        EVIDENCE_FLAP_CORRECTION,
        EVIDENCE_COVERAGE_RESTORED,
    }
)

# --- observation outcomes ---------------------------------------------------

OUTCOME_OK = "ok"
OUTCOME_INCOMPLETE = "incomplete"
OUTCOME_STALE = "stale"
OUTCOME_PARSE_ERROR = "parse_error"
OUTCOME_HTTP_ERROR = "http_error"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_SKIPPED = "skipped"

OUTCOMES = frozenset(
    {
        OUTCOME_OK,
        OUTCOME_INCOMPLETE,
        OUTCOME_STALE,
        OUTCOME_PARSE_ERROR,
        OUTCOME_HTTP_ERROR,
        OUTCOME_TIMEOUT,
        OUTCOME_SKIPPED,
    }
)

# --- quality flags ----------------------------------------------------------

FLAG_FLAPPING = "flapping"
FLAG_LONG_GAP = "long_gap"
FLAG_DEBOUNCED = "debounced"
FLAG_CORRECTED = "corrected"

# --- attribute change whitelist --------------------------------------------

#: Without a whitelist, ``attributes_changed`` degenerates into a per-poll diff
#: stream, which is archiving frames again by another name.
ATTRIBUTE_WHITELIST = ("station_id", "station_name", "status_text", "source_url")
