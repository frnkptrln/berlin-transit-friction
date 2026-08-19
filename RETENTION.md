# Retention

Status: **accepted** 2026-08-19. Binding for every write once collection
resumes; nothing may be written to a path this document does not cover.

What is kept, for how long, and why. If a layer is not listed here, it must not
exist. If a retention period is not stated here, nothing may be written to that
path.

Companion documents: [docs/data-architecture.md](docs/data-architecture.md),
[docs/event-schema.md](docs/event-schema.md),
[docs/partitioning.md](docs/partitioning.md).

---

## Summary

| layer | path | format | retention | in git? | rebuildable |
|---|---|---|---|---|---|
| raw | `.raw/` | as fetched + JSONL staging | **7 days** | **no** — gitignored | no (and that is fine) |
| events | `data/events/` | Parquet, append-only | **forever** | yes | no — this is the source of truth |
| aggregates | `data/aggregates/` | Parquet, derived | **forever** | yes | yes, from events alone |
| site data | `site/data/` | JSON projection | current only | yes | yes, from aggregates |
| reference | `data/reference/` | Parquet, immutable per version | **forever** | yes | only while the source archive is obtainable |
| manifests | `data/_manifests/` | JSON | **forever** | yes | no — they are the integrity chain |

---

## raw — 7 days, ephemeral, never in git history

**Contents.** Fetched payloads exactly as received (GTFS-RT protobuf, HTML,
JSON), the JSONL staging buffer for the day being collected, and the run's
working state (including debounce bookkeeping).

**Retention: 7 days.** Deleted by age on every run; the directory is in
`.gitignore` and CI fails if any path under it is ever staged.

**Why 7 days.** One week is what a human needs to debug a parser regression:
long enough to reproduce "why did Tuesday's snapshot look wrong", short enough
that nobody starts treating it as an archive. It also matches the default
GitHub Actions artifact retention, so a CI run that uploads a failing payload
for inspection expires on the same clock.

**Why not in git.** This is the central lesson of the paused prototype. Raw
frames were committed on every poll: 28,412 files and 115 MB in `data/bronze`,
plus 421 MB of re-emitted normalisation in `data/silver` — 66 days of collection
producing 536 MB of near-duplicate content that could not answer a single
question about when an outage started or ended. Committed raw data grows
monotonically, is never read, cannot be removed without rewriting history, and
makes every clone slower forever.

**What is lost, and why it is acceptable.** After 7 days the exact bytes of a
source response are gone. What survives is everything that was *derived* from
them: the transitions, and — in `observations` — the outcome, completeness,
counts, latency, and `payload_sha256` of every single fetch. We keep the
fingerprint and discard the body. If a parser bug is found later, it can be
identified from the observation ledger but not retroactively fixed for old
periods; the correct response is a `correction` row, not a rewrite.

**Explicit non-goal.** Raw is not a research corpus. Anyone wanting a GTFS-RT
frame archive should collect one deliberately, with its own budget and its own
retention policy, not as a side effect of this project.

---

## events — forever, append-only, immutable

**Contents.** `transitions` (an entity's state changed) and `observations` (we
looked at a source, here is what happened). Both defined in
[docs/event-schema.md](docs/event-schema.md).

**Retention: forever.** No expiry, no downsampling, no thinning of old periods.

**Why forever.** The whole question — *how does elevator availability change the
accessible topology of Berlin transport over time* — is a question about time.
A retention window on the event log would cap the maximum answerable timespan at
that window. The layer is also small enough that "forever" costs single-digit
megabytes per year (see [docs/partitioning.md](docs/partitioning.md) §7); the
argument for deleting it would have to be something other than size.

**Why both tables are forever.** `observations` is roughly ten times the volume
of `transitions` and is often mistaken for telemetry that could be aged out.
It cannot be. Without it, a period with no transitions is ambiguous between "the
network was fine" and "we were not looking", and every historical metric loses
its coverage denominator. Deleting old observations would retroactively convert
honest gaps into apparent good news — precisely the failure this architecture
exists to prevent.

**Immutability.** A sealed daily partition and a rolled-up monthly file are never
edited. Corrections are new rows. The only permitted file-level operation is the
verified 30-day rollup ([docs/partitioning.md](docs/partitioning.md) §5), which
preserves every absorbed file's hash and row count in
`data/_manifests/rollup/`.

**Rollup schedule.** Daily partitions for a month are merged into one monthly
file once the newest day in that month is ≥ 30 days old. Rows are unchanged;
only the container changes.

---

## aggregates — forever, derived, recomputable

**Contents.** Daily and monthly metrics (outage-hours, episode counts and
durations with min/max bounds, per-station and per-source breakdowns), plus a
`data_quality` table (coverage ratios, gap intervals, flapping entities,
suppressed flaps).

**Retention: forever.** They are small, they are what the dashboard reads, and
keeping them alongside the events makes every published number traceable to the
rows and the tuning parameters that produced it.

**Why keep them at all, if they are derivable.** Two reasons. They are the
published artefact — the thing a reader cites — so they must be stable and
citable. And their presence in git history is the audit trail: if a number
changes, the diff shows when, and `aggregate_revision` plus `recomputed_because`
show why. A restatement is allowed; a *silent* restatement is not.

**Recomputation.** Permitted at any time and expected after any change to the
tuning parameters in [docs/event-schema.md](docs/event-schema.md) §5.5.
A recomputation writes new values with a bumped revision; the previous values
remain in git history.

---

## site data — current only

`site/data/*.json` is a projection of the current aggregates for the dashboard.
It is regenerated, never hand-edited, and carries no history of its own — the
history is in `data/aggregates/`. It is committed so that GitHub Pages has
something to serve, not because it is a record.

---

## reference — forever, versioned, immutable per version

**Contents.** The denominator population derived from a static GTFS release:
which stations are in scope, which have an elevator, and how long each is in
service. See [docs/denominator.md](docs/denominator.md).

**Retention: forever.** A published rate names the population it was computed
against, so deleting a population would strand every metric row that cites it
and make historical figures uncheckable. It is also tiny — 311 stations is
8 KB of Parquet.

**Why the derived rows and not just a hash.** Keeping only a fingerprint of an
archive nobody can re-fetch is not reproducibility. The rows that formed the
denominator are kept; the archive itself is not committed.

**Versioning.** The partition key is derived from the content — the station rows
plus the frame predicate plus the derivation version. Two archives yielding the
same stations share a population; a change to the predicate writes a new one
rather than overwriting an immutable partition.

**Not in the event-table registry.** Reference data is neither an event stream
nor an aggregate, and the events sealer must not be able to see it: it would
otherwise be sealable into a partition claiming to be an event log.

---

## manifests — forever

`data/_manifests/seal/` and `data/_manifests/rollup/` hold the row counts and
content hashes written at the moment each partition became immutable. They are
tiny and they are the only thing that makes the append-only claim verifiable
after a rollup has removed the daily files. They are never pruned.

---

## Legacy data

The pre-pause `data/bronze`, `data/silver`, `data/gold`, `data/manifests`,
`data/normalized`, `data/raw`, and `data/summaries` trees are **not** covered by
this policy. They were produced by a pipeline whose output
[README.md](README.md) and [docs/legacy-assessment.md](docs/legacy-assessment.md)
describe as methodologically invalid.

Decision: the exact pre-pause state stays preserved on the `legacy-v0` branch.
On the active branch those directories are removed when the new layout lands, in
a single clearly-labelled commit. Removal does not shrink the repository —
history keeps the objects, and rewriting history to reclaim the ~44 MB of packed
git data is not worth breaking every existing clone and reference. The point of
removal is that nobody mistakes invalid legacy output for current data, not disk
space.

Legacy manifests may still be used for a postmortem of the pipeline. They may
not be used for any claim about Berlin transport.

---

## Enforcement

These are CI checks, not conventions. They are implemented in
`src/transit_friction/events/retention.py`, run by `scripts/check_retention.py`,
and executed on every pull request:

1. no path under `.raw/` may be staged, ever;
2. raw files older than 7 days must be absent after a collection run;
3. every file under `data/events/date=…` or `…/month=…` has a manifest whose
   hash matches;
4. a sealed or rolled-up partition may not be modified — a diff touching an
   existing events file fails the build, additions only;
5. `transition_uid` and `observation_id` are unique within and across
   partitions;
6. no aggregate may be published for a window whose `coverage_ratio` is below
   `min_publish_coverage` without an explicit `null` value;
7. layer size budgets from [docs/partitioning.md](docs/partitioning.md) §7 are
   asserted, so unexpected growth fails a build instead of accumulating for
   66 days.

A retention policy that is only written down is the policy the legacy pipeline
had.

---

## Personal data

None of these layers contain personal data. Sources report infrastructure state
(elevators, stations, lines, disruption notices), never passengers. If a source
ever begins to include personal or identifying content, ingestion of that source
stops until the field is dropped at the parser boundary — before it reaches any
layer with a retention period longer than zero. See [docs/ethics.md](docs/ethics.md).
