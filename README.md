# Transit Friction

> **Status: legacy prototype paused on 2026-07-10.**

The automated collectors and published dashboard have been stopped. The historical output must not be interpreted as a measure of Berlin public transport reliability.

The exact pre-pause state is preserved on the [`legacy-v0` branch](https://github.com/frnkptrln/berlin-transit-friction/tree/legacy-v0).

## Why collection was paused

The prototype combined fundamentally different observations—GTFS-RT stop-time updates, disruption notices, elevator signals, journey probes, and source availability—under one undefined “friction” count.

A review found that:

- event IDs included the collection timestamp, so the same condition became a new event on every poll;
- lifecycle state was not persisted between GitHub Actions runners;
- repeated observations were counted as distinct disruptions;
- GTFS-RT output was capped without a population denominator or static-GTFS join;
- the BrokenLifts collector detected a keyword on the landing page rather than individual outages;
- dead wrapper endpoints kept running and committing failures;
- map positions could be assigned without an observed location.

The resulting daily counts, rankings, scores, and trends are therefore methodologically invalid. The legacy manifests may still be useful for a postmortem of the pipeline itself, but not for claims about transit quality.

See [docs/legacy-assessment.md](docs/legacy-assessment.md) for the assessment and reboot criteria.

## Proposed reboot

The repository will only resume collection around one bounded question:

> **How does elevator availability change the accessible topology of Berlin public transport over time?**

The first valid version will focus on structured elevator-outage lifecycles:

- stable asset and station identities;
- explicit `first_seen_at`, `last_seen_at`, and `resolved_at`;
- no resolution when a source fetch fails or is incomplete;
- outage duration and recurrence rather than poll counts;
- source freshness and coverage kept separate from transport conditions;
- compact daily publication instead of committing every raw poll;
- no map or network claim without observed coordinates and topology.

## Publication gates

Scheduled collection stays disabled until all of the following are true:

1. fixture-backed parser tests pass;
2. event identity is stable across repeated snapshots;
3. state persists across independent runs;
4. a failed source cannot resolve active outages;
5. aggregates have explicit definitions and coverage;
6. a shadow run has been reviewed before public publication.

## Boundaries

Public data only. No passenger tracking, individual movement analysis, private or social-media scraping, fabricated geolocation, or unsupported precision.
