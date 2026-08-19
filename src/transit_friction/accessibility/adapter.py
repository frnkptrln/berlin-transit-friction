"""Bridge from the BrokenLifts parser into the generic events layer.

The parser knows about elevators, alert classes and advertised counts. The
events layer knows about entities, evidence and coverage. This module is the
only place the two vocabularies meet, so adding a second source means writing
another adapter rather than touching the detector.

The division of knowledge matters: *completeness* is the parser's verdict about
the page it read, while *transport failure* is the fetcher's. Neither can infer
the other, so the caller states the outcome and the adapter refuses to guess.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from ..events.detect import ObservedEntity, SourceSnapshot
from ..events.schema import (
    OUTCOME_HTTP_ERROR,
    OUTCOME_INCOMPLETE,
    OUTCOME_OK,
    OUTCOME_PARSE_ERROR,
    OUTCOME_TIMEOUT,
)
from .models import OutageSnapshot

SOURCE_ID = "brokenlifts"
ENTITY_TYPE = "elevator"
PARSER_VERSION = "brokenlifts-html/1"

#: Outcomes where no response body was read, so there is nothing to have
#: observed. The events layer distinguishes "we looked and saw nothing wrong"
#: from "we never got to look", and that distinction starts here.
NO_RESPONSE = frozenset({OUTCOME_HTTP_ERROR, OUTCOME_TIMEOUT})


def payload_digest(payload: str | bytes | None) -> str | None:
    """Fingerprint of a fetched page, kept after the page itself is discarded.

    Costs 64 bytes and answers what the discarded body cannot: whether the
    source was actually updating.
    """
    if payload is None:
        return None
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def to_source_snapshot(
    snapshot: OutageSnapshot,
    *,
    run_id: str,
    outcome: str | None = None,
    attempted_at: datetime | None = None,
    payload_sha256: str | None = None,
    http_status: int | None = None,
    latency_ms: int | None = None,
    collector_version: str = "0.0.0",
) -> SourceSnapshot:
    """Convert one parsed outage page into a generic source snapshot.

    ``outcome`` defaults to what the parser can tell: complete or not. A caller
    that knows the fetch itself failed passes the transport outcome instead.
    """
    if outcome is None:
        outcome = OUTCOME_OK if snapshot.complete else OUTCOME_INCOMPLETE
    if outcome == OUTCOME_PARSE_ERROR and snapshot.complete:
        raise ValueError("a parse error cannot have produced a complete snapshot")

    responded = outcome not in NO_RESPONSE
    entities = tuple(
        ObservedEntity(
            source_native_id=outage.asset_id,
            entity_type=ENTITY_TYPE,
            station_id=outage.station_id,
            station_name=outage.station_name,
            status_text=outage.status_text or None,
        )
        for outage in snapshot.outages
    )

    return SourceSnapshot(
        source_id=SOURCE_ID,
        run_id=run_id,
        attempted_at=attempted_at or snapshot.observed_at,
        observed_at=snapshot.observed_at if responded else None,
        source_updated_at=snapshot.source_updated_at if responded else None,
        outcome=outcome,
        complete=snapshot.complete and responded,
        entities=entities if responded else (),
        advertised_count=snapshot.advertised_count,
        http_status=http_status,
        latency_ms=latency_ms,
        payload_sha256=payload_sha256,
        warnings=snapshot.warnings,
        collector_version=collector_version,
        parser_version=PARSER_VERSION,
    )
