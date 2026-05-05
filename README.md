# Transit Friction

A small open observatory for making friction in Berlin public transport visible, analyzable, and narratable.

## v0.2 direction: Collect First
This version prioritizes broad, systematic, durable collection of public friction signals over polished dashboards.

## Data layers
- Bronze: `data/bronze/<source>/<YYYY>/<MM>/<DD>/<HHMMSS>.json.gz`
- Silver: `data/silver/friction_events/<YYYY-MM-DD>.jsonl`
- Gold: `data/gold/daily/*.json|*.md`, `site/data/*.json`

## Collected now
- vbb_gtfs_rt (metadata-first, compact)
- brokenlifts (accessibility signal probing)
- vbb_transport_rest departures remarks probe
- bvg_transport_rest departures remarks probe

## Planned/partial
- sbahn disruptions, BVG traffic news, WFS disturbed network, VIZ, static GTFS derived indexes.

## Local run
`python scripts/check_environment.py`
`python scripts/collect_snapshot.py --no-network --dry-run`
`python scripts/build_daily_summary.py`
`python scripts/build_site_data.py`
`python scripts/build_source_health.py`

## Boundaries
Public data only, no passenger tracking, no private/social scraping, no false precision, no crowding claims without direct source data.
