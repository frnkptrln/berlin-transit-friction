"""One non-publishing observation of the accessibility source.

The runner owns no lifecycle logic of its own. It fetches, adapts, rebuilds
state by folding the transition ledger, hands the snapshot to the detector, and
appends whatever came back. Everything that decides what counts as a change
lives in ``transit_friction.events``, so the shadow runner and a future
scheduled collector cannot drift apart.

State is not a file the runner keeps. It is the fold of the rows already
written, which is why a fresh clone, a re-run and a lost runner all converge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Callable

import requests

from ..events.config import DEFAULT_TUNING, TuningParameters
from ..events.detect import DetectionResult, detect
from ..events.schema import OUTCOME_HTTP_ERROR, OUTCOME_PARSE_ERROR, OUTCOME_TIMEOUT
from ..events.state import fold_cursors, fold_transitions
from ..events.store import (
    TABLE_OBSERVATIONS,
    TABLE_TRANSITIONS,
    append_rows,
    load_pending,
    load_recent_observations,
    load_recent_transitions,
    save_pending,
    staging_path,
)
from .adapter import SOURCE_ID, payload_digest, to_source_snapshot
from .models import OutageSnapshot
from .parser import DEFAULT_SOURCE_URL, parse_brokenlifts_snapshot

@dataclass(frozen=True, slots=True)
class ShadowPaths:
    """Where a shadow run reads and writes. Never inside the published tree."""

    events_root: Path
    raw_root: Path
    runs: Path

    @classmethod
    def under(cls, root: Path) -> "ShadowPaths":
        return cls(
            events_root=root / "events",
            raw_root=root / "raw",
            runs=root / "runs.jsonl",
        )


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What a single HTTP attempt produced, including the failure case."""

    snapshot: OutageSnapshot
    outcome: str | None = None
    payload_sha256: str | None = None
    http_status: int | None = None
    latency_ms: int | None = None
    attempted_at: datetime | None = None


def fetch_snapshot(
    *,
    url: str = DEFAULT_SOURCE_URL,
    observed_at: datetime | None = None,
    timeout: float = 20,
    get: Callable = requests.get,
) -> FetchResult:
    """Fetch and parse once. A failure is a result, not an exception."""
    attempted_at = observed_at or datetime.now(timezone.utc)
    started = monotonic()
    try:
        response = get(
            url,
            timeout=timeout,
            headers={"User-Agent": "transit-friction-accessibility-shadow/0.1"},
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - the failure is the data
        return FetchResult(
            snapshot=OutageSnapshot.failed(
                source_url=url,
                observed_at=attempted_at,
                warning=f"source fetch failed: {exc}",
            ),
            outcome=OUTCOME_TIMEOUT if isinstance(exc, requests.Timeout) else OUTCOME_HTTP_ERROR,
            http_status=getattr(getattr(exc, "response", None), "status_code", None),
            latency_ms=max(0, int((monotonic() - started) * 1000)),
            attempted_at=attempted_at,
        )

    finished = datetime.now(timezone.utc)
    outcome = None
    try:
        snapshot = parse_brokenlifts_snapshot(
            response.text, observed_at=finished, source_url=url
        )
    except Exception as exc:  # noqa: BLE001 - parser failures are observations too
        snapshot = OutageSnapshot.failed(
            source_url=url,
            observed_at=finished,
            warning=f"source parse failed: {exc}",
        )
        outcome = OUTCOME_PARSE_ERROR
    return FetchResult(
        snapshot=snapshot,
        outcome=outcome,
        payload_sha256=payload_digest(response.text),
        http_status=getattr(response, "status_code", None),
        latency_ms=max(0, int((monotonic() - started) * 1000)),
        attempted_at=attempted_at,
    )


def _summary(result: DetectionResult, *, dry_run: bool) -> dict:
    observation = result.observation
    counts: dict[str, int] = {}
    for row in result.transitions:
        counts[row.transition_type] = counts.get(row.transition_type, 0) + 1

    return {
        "run_id": observation.run_id,
        "source_id": observation.source_id,
        "attempted_at": observation.attempted_at.isoformat(),
        "observed_at": (
            observation.observed_at.isoformat() if observation.observed_at else None
        ),
        "source_updated_at": (
            observation.source_updated_at.isoformat()
            if observation.source_updated_at
            else None
        ),
        "outcome": observation.outcome,
        "complete": observation.complete,
        "source_current": observation.source_current,
        "trusted_for_resolution": observation.trusted_for_resolution,
        "gap_before_s": observation.gap_before_s,
        "observed_entities": observation.entity_count,
        "advertised_count": observation.advertised_count,
        "transitions": counts,
        "impaired_after": sum(
            1 for state in result.states.values() if state.state == "impaired"
        ),
        "unknown_after": sum(
            1 for state in result.states.values() if state.state == "unknown"
        ),
        "pending_confirmation": len(result.pending),
        "suppressed_flaps": sum(result.suppressed_flaps.values()),
        "warnings": list(observation.warnings),
        "notes": list(result.notes),
        "dry_run": dry_run,
    }


def apply_snapshot(
    fetched: FetchResult | OutageSnapshot,
    *,
    paths: ShadowPaths,
    run_id: str | None = None,
    dry_run: bool = False,
    tuning: TuningParameters = DEFAULT_TUNING,
    pending: dict | None = None,
) -> dict:
    """Reconcile one observation against the ledger and append what changed."""
    if isinstance(fetched, OutageSnapshot):
        fetched = FetchResult(snapshot=fetched)

    observed_at = fetched.snapshot.observed_at
    run_id = run_id or f"shadow-{observed_at.isoformat()}"
    snapshot = to_source_snapshot(
        fetched.snapshot,
        run_id=run_id,
        outcome=fetched.outcome,
        attempted_at=fetched.attempted_at,
        payload_sha256=fetched.payload_sha256,
        http_status=fetched.http_status,
        latency_ms=fetched.latency_ms,
    )

    # Transitions are sparse: an outage may stay unchanged for months. A
    # rolling time filter would forget its opening and manufacture a new one.
    transitions = load_recent_transitions(
        paths.events_root, paths.raw_root
    )
    observations = load_recent_observations(
        paths.events_root, paths.raw_root
    )

    if pending is None:
        pending = load_pending(paths.raw_root, SOURCE_ID)

    result = detect(
        snapshot,
        fold_transitions(transitions),
        fold_cursors(observations).get(SOURCE_ID),
        pending,
        tuning,
    )
    summary = _summary(result, dry_run=dry_run)

    if dry_run:
        return summary

    day = snapshot.attempted_at.astimezone(timezone.utc).date()
    # Advance the source cursor only after its transitions are durable. If a
    # write fails, replay still sees the old cursor and can finish the change.
    for row in result.transitions:
        append_rows(
            staging_path(
                paths.raw_root,
                TABLE_TRANSITIONS,
                row.t_latest.astimezone(timezone.utc).date(),
            ),
            [row.to_dict()],
        )
    append_rows(
        staging_path(paths.raw_root, TABLE_OBSERVATIONS, day),
        [result.observation.to_dict()],
    )

    save_pending(paths.raw_root, SOURCE_ID, result.pending)

    paths.runs.parent.mkdir(parents=True, exist_ok=True)
    with paths.runs.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary
