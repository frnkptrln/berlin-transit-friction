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

Completeness alone does not license a resolution: the page must also carry a
newer update timestamp than the last one folded into state. A cached or
unchanged page is the previous statement repeated, and repeating a statement is
not evidence that something changed since it was made.

## Lifecycle invariants

1. Asset identity comes from the source asset ID, never from collection time.
2. Repeated observations retain the first-seen time and outage ID.
3. Missing assets resolve only from a complete, fresh snapshot.
4. Failed, malformed, incomplete, or repeated snapshots cannot resolve outages.
5. State is derived from the ledger, so it cannot be lost with a runner.
6. Source time and collector time remain separate.
7. A change is dated as an interval, never as a point.
8. Losing sight of an asset makes it `unknown`, never `ok`.

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

The shadow runner observes the source once and appends whatever changed:

```bash
python scripts/accessibility_shadow.py
```

By default it writes below `.shadow/`, which is ignored by Git. It never commits,
publishes, or schedules a run. Use `--dry-run` to parse and reconcile without
writing. Use `--input-html` for fixture or captured-page validation, and
`--root` to place the shadow tree somewhere else.

It owns no lifecycle logic. Parsing is source-specific
(`accessibility/parser.py`), the translation into the generic vocabulary is one
adapter (`accessibility/adapter.py`), and every decision about what counts as a
change lives in `transit_friction.events` — shared with every future source, so
the shadow runner and a scheduled collector cannot drift apart. See
[event-schema.md](event-schema.md).

There is no state file. Current state is rebuilt each run by folding the
transition ledger, so an interrupted run, a re-run, or a fresh clone all
converge on the same answer. The one thing carried between runs is the debounce
buffer under `.raw/working-state/`, which is not evidence: losing it costs one
extra confirmation cycle and nothing else.

The ledger records transitions only — `opened`, `closed`, `unknown_entered`,
`unknown_exited`, `reopened`. Repeated observations of an unchanged outage write
nothing, so the archive's size reflects what happened rather than how often we
asked.
