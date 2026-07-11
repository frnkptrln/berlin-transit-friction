# Accessibility reboot

## Question

> How does elevator availability change the accessible topology of Berlin public transport over time?

The first implementation does not claim to model network reachability. It
establishes the prerequisite: trustworthy elevator-asset outage intervals.

## Source contract

The initial parser reads the public BrokenLifts outage page. The page currently
provides:

- a source update timestamp;
- an advertised active-outage count;
- station identifiers in station links;
- elevator asset identifiers in lift links;
- an explicit alert class for unavailable assets;
- a station-level status description.

A snapshot is complete only if the update timestamp and advertised count are
present, the outage list exists, and the number of unique parsed alert assets
matches the advertised count. Completeness is a property of an observation,
not an assumption about the provider.

## Lifecycle invariants

1. Asset identity comes from the source asset ID, never from collection time.
2. Repeated observations retain the first-seen time and outage ID.
3. Missing assets resolve only from a complete, non-stale snapshot.
4. Failed, malformed, incomplete, or stale snapshots cannot resolve outages.
5. State is versioned and persisted independently of a runner process.
6. Source time and collector time remain separate.

## Metric contract

The first aggregate is outage-hours within an explicit time window. Poll counts
are not a transit metric. Every published aggregate must state its time window,
unit, and observation coverage.

## Deliberately absent

- no scheduled workflow;
- no public live metric;
- no severity score;
- no synthetic coordinate;
- no route or topology impact claim;
- no raw snapshot commits.

Those layers require separate evidence and review.

## One-shot shadow operation

The shadow runner observes the source once, reconciles it with a local versioned
state file, and records only lifecycle transitions plus a compact run summary:

```bash
python scripts/accessibility_shadow.py
```

By default it writes below `.shadow/`, which is ignored by Git. It never commits,
publishes, or schedules a run. Use `--dry-run` to parse and reconcile without
writing state. Use `--input-html` for fixture or captured-page validation.

The transition journal records only `new` and `resolved` changes. Repeated
`ongoing` observations stay in the state file and run summary, avoiding a new
event stream whose size merely reflects polling frequency.
