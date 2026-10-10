#!/usr/bin/env python3
"""Move the shadow period's durable layers between the runner and its ledger branch.

The rehearsal (ADR 0002) keeps its working tree in an evictable Actions cache
and its durable record on the ``shadow-ledger`` branch. Two directions:

  restore   copy the ledger's sealed events, manifests and aggregates into a
            shadow tree that has none (a cold runner), so the fold of the
            ledger gives the next observation its state
  publish   copy the shadow tree's sealed layers, aggregates, private site
            projection and run log into a checkout of the ledger branch, and
            say whether anything changed

Neither direction touches the published ``site/`` of the main branch. The raw
buffer (``raw/``) is never copied: it is the 7-day layer and stays in the cache.
"""
from __future__ import annotations

import argparse
import filecmp
import json
from pathlib import Path
import shutil
import sys

DURABLE = ("events", "_manifests", "aggregates", "site")
RUN_LOG = "runs.jsonl"

LEDGER_README = """# shadow-ledger

Rehearsal data for the accessibility observation (ADR 0002). Written by the
`shadow seal` workflow once a day from the runner's shadow tree; read back by
the `accessibility shadow observation` workflow when its cache is cold.

- `events/`, `_manifests/` — sealed days of transitions and observations
- `aggregates/`, `site/` — private projections for review, not published
- `runs.jsonl` — every observation attempt with its outcome and warnings

This is not evidence about Berlin public transport and is not served anywhere.
It exists so that the observation period can be reviewed against the gates in
README.md before any scheduled publication.
"""


def copy_tree(source: Path, target: Path) -> int:
    """Copy source over target, returning how many files were new or changed."""
    changed = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if destination.is_file() and filecmp.cmp(path, destination, shallow=False):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        changed += 1
    return changed


def restore(ledger: Path, shadow: Path) -> int:
    if (shadow / "events").is_dir():
        print("shadow tree already has an events layer; nothing restored")
        return 0
    restored = 0
    for layer in ("events", "_manifests", "aggregates"):
        if (ledger / layer).is_dir():
            restored += copy_tree(ledger / layer, shadow / layer)
    print(f"restored {restored} files from the ledger into {shadow}")
    return 0


def publish(shadow: Path, ledger: Path) -> int:
    ledger.mkdir(parents=True, exist_ok=True)
    changed = 0
    for layer in DURABLE:
        if (shadow / layer).is_dir():
            changed += copy_tree(shadow / layer, ledger / layer)
    log = shadow / RUN_LOG
    if log.is_file():
        target = ledger / RUN_LOG
        if not (target.is_file() and filecmp.cmp(log, target, shallow=False)):
            shutil.copyfile(log, target)
            changed += 1
    readme = ledger / "README.md"
    if not readme.is_file() or readme.read_text() != LEDGER_README:
        readme.write_text(LEDGER_README)
        changed += 1
    summary = {
        "changed_files": changed,
        "sealed_days": sorted(p.name for p in (ledger / "events").glob("**/date=*")) if (ledger / "events").is_dir() else [],
        "runs_logged": sum(1 for _ in (ledger / RUN_LOG).open()) if (ledger / RUN_LOG).is_file() else 0,
    }
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("restore", help="fill a cold shadow tree from a ledger checkout")
    r.add_argument("--ledger", type=Path, required=True)
    r.add_argument("--shadow", type=Path, required=True)
    p = sub.add_parser("publish", help="copy the shadow tree's durable layers into a ledger checkout")
    p.add_argument("--shadow", type=Path, required=True)
    p.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "restore":
        return restore(args.ledger, args.shadow)
    return publish(args.shadow, args.ledger)


if __name__ == "__main__":
    sys.exit(main())
