# Legacy assessment

Date: 2026-07-10  
Reviewed state: `main` at `fce147726a8e148bb8fc5ab4f6d9a3925958fae9`  
Preserved as: `legacy-v0`

## Decision

The v0 collectors, aggregations, and public dashboard are paused. Their outputs are not valid measurements of Berlin public transport reliability.

This is a measurement-model failure, not merely an incomplete dashboard.

## Evidence

At the review point the repository was approximately 300 MB and had accumulated 2,546 commits after the last substantial feature commit on 2026-05-09.

The published daily index contained:

- 66 days;
- 813,800 records labelled as events;
- an average of 12,330 events per day;
- 6,177 events on 2026-07-09, all labelled `new`;
- 6,164 of those records derived from GTFS-RT delay observations;
- zero departure observations and zero journey observations on that date.

The published station ranking was empty and the live-map GeoJSON contained no features.

## Root causes

### 1. Event identity depended on observation time

`stable_event_id()` accepted a time value, while collectors passed the current collection time. A condition observed twice therefore received two IDs.

The lifecycle layer could not distinguish persistence from recurrence.

### 2. Lifecycle state did not survive a runner

The state manager wrote `data/state/active_events.json`, but collection workflows did not stage `data/state`. Every GitHub Actions checkout started without the previous state.

This explains why every record in the reviewed daily summary was labelled `new`.

### 3. Observations were presented as incidents

GTFS-RT stop-time updates with a delay of at least five minutes were appended on every successful poll. A delayed trip could create multiple records across stops and polls.

There was no denominator for:

- total scheduled trips;
- total observed trips;
- total stop-time updates;
- feed coverage;
- Berlin-only coverage.

Counts therefore changed with polling frequency, runner success, feed ordering, and feed size.

### 4. GTFS-RT output was truncated before aggregation

The collector capped normalized records at 1,000. It did not join route and stop IDs to the current static GTFS schedule before publication.

Rankings consequently used internal identifiers and a changing prefix of the feed rather than a defined population.

### 5. The accessibility signal did not represent outages

The BrokenLifts collector searched a landing-page excerpt for the words `lift` or `aufzug`. Because the site is about elevators, a generic potential-outage record was produced without identifying an asset, station, or actual outage.

### 6. Sources with permanent failures remained active

The reviewed source-health output showed 1,562 consecutive failures for each of the VBB and BVG `transport.rest` probes. The workflows nevertheless continued polling, waiting on timeouts, and committing failure metadata.

### 7. Source health was not guaranteed to be chronological

Manifest files were globbed without an explicit sort, while the health reducer treated iteration order as time order. Fields such as last success, last failure, and consecutive failures were therefore not defined robustly.

### 8. Geospatial output could fabricate locations

When an event could not be matched to a small hard-coded station dictionary, the site builder randomly jittered it around Berlin centre. Synthetic coordinates were not marked as synthetic.

### 9. Operational success was allowed to mask dependency failure

Several workflows used `pip install ... || true` and an initial `git pull --rebase ... || true`. This allowed execution to continue after setup or synchronization failures.

## What remains useful

The following ideas may be reused after redesign:

- explicit raw, normalized, and aggregate layers;
- run manifests;
- public-data and privacy boundaries;
- a static, dependency-light publication layer;
- source fixtures and schema validation;
- the legacy manifests as evidence for a pipeline postmortem.

Historical v0 transit counts, scores, rankings, lifecycle states, and trends must not be reused as service-quality evidence.

## Reboot question

> How does elevator availability change the accessible topology of Berlin public transport over time?

The first version should model elevator assets and observed outage intervals. Network-level consequences are a later layer and require verified station topology.

## Minimum domain model

### Asset

- stable source asset ID;
- station ID and source station name;
- optional operator and connection description;
- optional verified coordinates;
- source URL.

### Observation

- source timestamp;
- collector timestamp;
- source freshness;
- asset status;
- raw record hash;
- completeness indicator.

### Outage

- stable outage ID derived from asset identity and the beginning of a status interval;
- `first_seen_at`;
- `last_seen_at`;
- `resolved_at`;
- resolution reason;
- uncertainty and observation gaps.

A failed or incomplete snapshot must never resolve an active outage.

## Initial aggregates

Only aggregates with explicit units and coverage are allowed:

- active outage count at observation time;
- outage-hours per day and station;
- completed outage duration distribution;
- recurring outages per asset and station;
- source freshness and observation coverage.

Poll counts are operational telemetry and remain separate.

## Publication gates

Scheduled collection remains disabled until:

1. parser fixtures cover normal, empty, malformed, and incomplete snapshots;
2. stable identity survives repeated equivalent snapshots;
3. state survives a new process and clean checkout;
4. source failure and incomplete snapshots cannot resolve outages;
5. aggregation tests cover interval boundaries and open outages;
6. published metrics include unit, time window, and coverage;
7. a shadow run is manually reviewed;
8. the public site contains no synthetic location or unsupported severity.

## Storage policy

Git is for code, schemas, small fixtures, compact aggregates, and documentation.

Raw polling snapshots must not be committed every few minutes. During shadow operation they should use short-lived workflow artifacts or external object storage. At most one compact, reviewed publication update should reach the repository per day.
