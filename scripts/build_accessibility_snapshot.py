#!/usr/bin/env python3
"""Project one reviewed source capture for the site; never fetch or schedule.

This is a dated source statement, not a network metric or outage lifecycle.
The full capture stays in the ignored shadow directory, subject to retention.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from transit_friction.accessibility.adapter import PARSER_VERSION, payload_digest
from transit_friction.accessibility.parser import parse_brokenlifts_snapshot


def project_snapshot(html: str, *, observed_at: datetime, source_url: str,
                     review_note: str, reviewed_at: datetime | None = None) -> dict:
    if not review_note.strip():
        raise ValueError('A concrete review note is required')
    url = urlparse(source_url)
    if url.scheme != 'https' or url.hostname not in {'brokenlifts.org', 'www.brokenlifts.org'} or url.username or url.password:
        raise ValueError('Expected the public HTTPS BrokenLifts source')
    snapshot = parse_brokenlifts_snapshot(html, observed_at=observed_at, source_url=source_url)
    if not snapshot.complete:
        raise ValueError('Incomplete source capture: ' + '; '.join(snapshot.warnings))
    if snapshot.source_updated_at > observed_at:
        raise ValueError('Source update is in the future relative to the capture')
    if (observed_at - snapshot.source_updated_at).total_seconds() > 3600:
        raise ValueError('Source was already more than one hour old at capture')
    reviewed_at = reviewed_at or datetime.now(timezone.utc)
    if reviewed_at.tzinfo is None or reviewed_at < observed_at:
        raise ValueError('Review must be timezone-aware and follow observation')
    stations = {}
    for outage in snapshot.outages:
        station = stations.setdefault(outage.station_id, {
            'station_id': outage.station_id,
            'station_name': outage.station_name,
            'region': 'berlin' if outage.station_id.startswith('de:11000:') else 'other_or_unknown',
            'assets': [],
        })
        station['assets'].append({'asset_id': outage.asset_id, 'source_url': outage.source_url})
    return {
        'schema_version': 1, 'kind': 'reviewed_source_snapshot',
        'source_name': 'BrokenLifts', 'source_url': source_url,
        'source_scope': 'Berlin-Brandenburg',
        'source_updated_at': snapshot.source_updated_at.isoformat(),
        'observed_at': observed_at.isoformat(), 'reviewed_at': reviewed_at.isoformat(),
        'review_note': review_note.strip(), 'parser_version': PARSER_VERSION,
        'payload_sha256': payload_digest(html), 'complete': True,
        'advertised_outage_count': snapshot.advertised_count,
        'parsed_outage_count': len(snapshot.outages),
        'stations': sorted(stations.values(), key=lambda s: s['station_name'].casefold()),
        'limitations': [
            'One dated source statement, not live information.',
            'Reported lift outages are not a count of inaccessible stations.',
            'No inference about working unlisted lifts, duration, routes or total coverage.',
            'Berlin filter uses the source station DHID prefix de:11000:; other IDs remain unclassified.',
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--input-html', type=Path, required=True)
    parser.add_argument('--observed-at', required=True, help='Actual timezone-aware capture timestamp')
    parser.add_argument('--source-url', default='https://www.brokenlifts.org/')
    parser.add_argument('--review-note', required=True, help='Checks performed on this exact capture')
    parser.add_argument('--output', type=Path, default=Path('.shadow/site/accessibility-snapshot.json'))
    args = parser.parse_args()
    projection = project_snapshot(
        args.input_html.read_text(encoding='utf-8'),
        observed_at=datetime.fromisoformat(args.observed_at), source_url=args.source_url,
        review_note=args.review_note,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(projection, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(args.output)
    print(json.dumps({'output': str(args.output), 'stations': len(projection['stations']),
                      'reported_lifts': projection['parsed_outage_count'],
                      'source_updated_at': projection['source_updated_at']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
