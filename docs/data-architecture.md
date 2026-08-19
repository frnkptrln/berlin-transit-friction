# Data architecture

Status: **accepted** 2026-08-19, written before collection resumes. No collector
may be re-enabled until the contracts below are implemented and tested.

This document is the umbrella. The details live in:

- [event-schema.md](event-schema.md) — what a transition is, flapping, gaps
- [partitioning.md](partitioning.md) — Parquet layout, sealing, rollup
- [../RETENTION.md](../RETENTION.md) — what is kept, how long, why
- [decisions/0001-timeseries-hosting.md](decisions/0001-timeseries-hosting.md) — Hugging Face or not

## The principle

**We do not archive frames. We archive state transitions.**

A GTFS-RT frame, a BrokenLifts page, a disruption list — these are *renderings
of a current state*, produced on a schedule that we chose. Archiving them
produces a corpus whose size is a function of our polling frequency and whose
content is 99 % repetition. The legacy prototype did exactly this:

| layer | size | files | what it actually contains |
|---|---|---|---|
| `data/bronze` | 115 MB | 28,412 | one compressed frame per source per poll |
| `data/silver` | 421 MB | 66 | ~6.4 MB **per day**; 25,710 rows on 2026-05-23 |

Every row in that silver file carries `"event_state": "new"` and an
`event_id` derived from the collection timestamp. The same delayed trip became a
new event on every poll. Ten months of that is roughly 2.3 GB/year describing
maybe a few thousand real-world occurrences.

The replacement stores the *edges*, not the *samples*. A single elevator outage
lasting three days is two rows, not 864.

## The three layers

```
  ┌─ raw ──────────────┐   ephemeral, 7 days, never in git history
  │ fetched payloads   │   exists only so a run can diff "now" vs "last known"
  └────────┬───────────┘
           │  detect edges
  ┌────────▼───────────┐   forever, append-only, immutable once sealed
  │ events             │
  │  ├─ transitions    │   state changed: outage opened / closed / became unknown
  │  └─ observations   │   we looked: outcome, completeness, coverage gap
  └────────┬───────────┘
           │  fold + window
  ┌────────▼───────────┐   forever, derived, reproducible from events alone
  │ aggregates         │   daily + monthly metrics; drives the dashboard
  └────────────────────┘
```

Three properties hold across the whole stack:

1. **Events are the source of truth.** Aggregates are a pure function of
   events. Deleting `data/aggregates/` entirely must be repairable by a rebuild,
   and a rebuild must be bit-reproducible for closed periods.
2. **Raw is disposable.** Nothing downstream may require a raw payload that is
   older than the retention window. If a fact matters, it is in an event row.
3. **Absence of evidence is recorded as such.** `observations` is a peer table
   of `transitions`, not telemetry. A metric computed without consulting it is
   invalid, because a poll that never happened and a poll that found nothing
   wrong are indistinguishable in the transition stream alone.

## Why `observations` is not optional

This is the single most important structural decision here, and it is why the
events layer has two tables instead of one.

The transition stream is sparse by design: if nothing changed, nothing is
written. But "nothing was written between 02:00 and 09:00" has two readings:

- the network was fine for seven hours, or
- the collector was down for seven hours.

Nothing in the transition stream separates those. The observation ledger does:
one row per source per attempt, recording whether we reached the source, whether
the response was complete, and how long it had been since the last trustworthy
look. Coverage is then a computed property of a time window, and every published
aggregate carries it.

The corollary is a hard rule, enforced in the schema and repeated in every
document here: **a failed, incomplete, or stale observation can never close an
outage.** An outage that we stopped being able to see does not end — it becomes
`unknown`, and the ledger says so explicitly.

## State is derived, not stored

The legacy pipeline lost lifecycle state between GitHub Actions runners (see
[AUDIT.md](../AUDIT.md), critical gap 3). The fix is not a better state file. The
fix is that **current state is a fold over the transition ledger** — the last
transition per entity *is* its state. A run rebuilds working state by reading the
last 30 days of transitions (a few hundred KB) before it fetches anything.

Consequences:

- no mutable `state.json` in git history;
- a lost runner, a re-run, or a fresh clone converges to the same state;
- state can never silently disagree with the published history, because it is
  the same bytes.

Debounce bookkeeping (see [event-schema.md](event-schema.md)) is the one thing
that is *not* recoverable this way. It is deliberately confined to the raw layer:
losing it costs one extra confirmation cycle and nothing else.

## What this architecture refuses to answer

- It does not model network reachability or trip-level impact. Those need a
  static GTFS join and a population denominator, neither of which exists yet.
- It does not produce a severity score. Severity in the legacy model was a
  constant chosen by the collector, not an observation.
- It does not count polls. `total_events: 14878` for a single day was a
  measurement of our cron schedule, not of Berlin.
