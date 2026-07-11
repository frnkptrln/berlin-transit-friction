from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from .lifecycle import ActiveOutage, load_state, reconcile, save_state
from .models import OutageSnapshot
from .parser import DEFAULT_SOURCE_URL, parse_brokenlifts_snapshot


@dataclass(frozen=True, slots=True)
class ShadowPaths:
    state: Path
    transitions: Path
    runs: Path


def fetch_snapshot(
    *,
    url: str = DEFAULT_SOURCE_URL,
    observed_at: datetime | None = None,
    timeout: float = 20,
    get: Callable = requests.get,
) -> OutageSnapshot:
    observed_at = observed_at or datetime.now(timezone.utc)
    try:
        response = get(
            url,
            timeout=timeout,
            headers={"User-Agent": "transit-friction-accessibility-shadow/0.1"},
        )
        response.raise_for_status()
    except Exception as exc:
        return OutageSnapshot.failed(
            source_url=url,
            observed_at=observed_at,
            warning=f"source fetch failed: {exc}",
        )

    return parse_brokenlifts_snapshot(
        response.text,
        observed_at=observed_at,
        source_url=url,
    )


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _transition_record(
    transition: str,
    outage: ActiveOutage,
    recorded_at: datetime,
) -> dict:
    return {
        "transition": transition,
        "recorded_at": recorded_at.isoformat(),
        **outage.to_dict(),
    }


def apply_snapshot(
    snapshot: OutageSnapshot,
    *,
    paths: ShadowPaths,
    dry_run: bool = False,
) -> dict:
    active_before = load_state(paths.state)
    result = reconcile(active_before, snapshot)

    summary = {
        "observed_at": snapshot.observed_at.isoformat(),
        "source_updated_at": (
            snapshot.source_updated_at.isoformat()
            if snapshot.source_updated_at
            else None
        ),
        "complete": snapshot.complete,
        "warnings": list(snapshot.warnings),
        "observed_outages": len(snapshot.outages),
        "active_before": len(active_before),
        "active_after": len(result.active),
        "new": len(result.new),
        "ongoing": len(result.ongoing),
        "resolved": len(result.resolved),
        "resolution_allowed": result.resolution_allowed,
        "dry_run": dry_run,
    }

    if dry_run:
        return summary

    save_state(paths.state, result.active)
    transitions = [
        *(
            _transition_record("new", outage, snapshot.observed_at)
            for outage in result.new
        ),
        *(
            _transition_record("resolved", outage, snapshot.observed_at)
            for outage in result.resolved
        ),
    ]
    _append_jsonl(paths.transitions, transitions)
    _append_jsonl(paths.runs, [summary])
    return summary
