# Transit Friction

A small open observatory for making friction in Berlin public transport visible, analyzable, and narratable.

## Motivation
Berlin’s public transport reliability is experienced daily as small moments of uncertainty: cancelled trains, broken lifts, replacement buses, overcrowding, missing information, and delays. This project collects public signals to make those frictions more visible.

## What this project does
- Collects public transit reliability signals from public APIs/feeds.
- Normalizes them into a transparent `FrictionEvent` schema.
- Builds daily summaries and lightweight site data for storytelling.
- Archives snapshots in Git for reproducibility.

## What this project does not do
- Track individual passengers.
- Use private or non-public data.
- Claim perfect measurement of lived passenger experience.
- Replace official operational reporting.

## Data sources
See `docs/data-sources.md` for source-by-source details and current status.

## How GitHub Actions collect data
- `collect.yml` runs every 30 minutes (UTC cron) and on manual trigger.
- It collects a snapshot, updates normalized data, builds summaries/site JSON, and commits changes if any.
- `daily-summary.yml` runs once daily and rebuilds summary artifacts.

## Local usage
Install:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Collect:
```bash
python scripts/collect_snapshot.py
```

Build summary:
```bash
python scripts/build_daily_summary.py
```

Build site data:
```bash
python scripts/build_site_data.py
```

## Current limitations
- GTFS-RT is currently collected as metadata-first (status/content hash) for low storage overhead.
- Source endpoint behavior can change; failures are logged and runs degrade gracefully.
- Crowding is not directly measured in this MVP.

## Ethical boundaries
- Public data only.
- No personal-data collection or passenger-level movement analysis.
- No scraping private accounts or social media by default.
- No naming/shaming staff.
- Explicit uncertainty where signals are incomplete.
