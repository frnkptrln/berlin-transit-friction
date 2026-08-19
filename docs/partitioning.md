# Partitioning and file layout

Status: **accepted** 2026-08-19. Companion to
[event-schema.md](event-schema.md).

Rules, in order of precedence:

1. Append-only. A sealed file is never rewritten, never edited, never deleted.
2. Parquet for everything permanent.
3. One partition per day while a day is young; one file per month after 30 days.
4. Every immutable file has a manifest with a content hash and a row count.

---

## 1. Layout

```
data/
├── events/
│   ├── transitions/
│   │   ├── date=2026-08-18/transitions.parquet      ← sealed, immutable
│   │   ├── date=2026-08-17/transitions.parquet
│   │   ├── …                                        ← up to 30 daily partitions
│   │   └── month=2026-06/transitions.parquet        ← rolled up, immutable
│   └── observations/
│       ├── date=2026-08-18/observations.parquet
│       └── month=2026-06/observations.parquet
├── aggregates/
│   ├── daily/date=2026-08-18/metrics.parquet
│   ├── monthly/month=2026-06/metrics.parquet
│   └── data_quality/date=2026-08-18/quality.parquet
└── _manifests/
    ├── seal/2026-08-18.json
    └── rollup/2026-06.json

.raw/                       ← gitignored, 7-day retention, never committed
├── payloads/2026-08-18/…
├── staging/transitions-2026-08-18.jsonl
└── working-state.json
```

Hive-style `key=value` directories, because that is what every Parquet reader
(DuckDB, `pyarrow.dataset`, pandas, `datasets`) understands for free — including
the Hugging Face viewer, should
[decisions/0001](decisions/0001-timeseries-hosting.md) ever be revisited.

Daily and monthly partitions of the same table coexist under one root, and the
two key names differ (`date=` vs `month=`) so a naive glob can never load a day
twice — once from its daily file and once from the month that absorbed it.

---

## 2. Why the hot day is not Parquet

Parquet is columnar and immutable-by-nature: appending means rewriting the file
and its footer. A collector running every five minutes would rewrite the day's
file 288 times, which is both the overwrite we forbade and a reliable way to
lose data to a runner killed mid-write.

So writing is two-phase:

| phase | format | location | mutable? |
|---|---|---|---|
| collect | newline-delimited JSON, `O_APPEND` per row | `.raw/staging/` (ephemeral) | append-only, crash-safe |
| seal | Parquet, written once | `data/events/…/date=D/` | immutable forever |

The JSONL staging file is **not a data layer**. It is a write buffer that lives
in the 7-day ephemeral tier and is discarded once sealed. Nothing reads it except
the sealer.

### Sealing (day D, run at 03:00 UTC on D+1)

Run by `scripts/seal_events.py`; the eligibility rules live in
`events/maintenance.py` so they can be tested without a runner.

1. Read `.raw/staging/transitions-D.jsonl`.
2. Validate every row against the schema; reject the seal on any violation
   rather than dropping rows.
3. Deduplicate on `transition_uid`, keeping the lowest `ingested_at`.
4. Sort by `(entity_uid, t_latest)`.
5. Write `date=D/transitions.parquet` **once**, to a temp name, then rename.
6. Write `_manifests/seal/D.json`: row count, `sha256` of the Parquet file,
   min/max `t_latest`, distinct entity count, schema version, tuning parameters,
   sealer version.
7. Commit the Parquet file and its manifest in one commit.

The 3-hour grace period exists so a run that started at 23:58 UTC and finished at
00:01 lands in the right partition before the day closes. Because the partition
key is `t_latest` — the time we *observed* the change — a row for day D can only
be produced during day D. Late arrivals are bounded by the grace window, not
open-ended.

If a fact about day D emerges after D is sealed, it does not reopen D. It becomes
a `correction` row in the current day's partition, pointing at the sealed
`transition_uid` (see [event-schema.md](event-schema.md) §8).

**Empty days are sealed too.** A day with zero transitions gets a zero-row
Parquet file and a manifest. A missing partition would mean "we do not know";
an empty one means "we looked and nothing changed" — and `observations` for the
same day proves which.

---

## 3. Partition key

`date` = the **UTC** calendar date of `t_latest`.

UTC for storage, because Europe/Berlin has 23- and 25-hour days twice a year, and
a partition scheme that silently changes width breaks both reproducibility and
any per-day rate.

Berlin local time is not thereby discarded — it is a **column**. Every row
carries `local_date` (Europe/Berlin) and every daily aggregate is computed over
the *local* day window, which on DST boundaries is 23 or 25 hours long. The
aggregate records `window_hours` explicitly so that "outage-hours per day"
never quietly compares a 23-hour day to a 25-hour one.

Storage is partitioned by UTC. Meaning is reported in Berlin time. Both are
stated on every artefact.

### Why not partition by entity, station, or source

Per-entity or per-station partitioning gives thousands of directories holding a
handful of rows each — the small-file problem, with worse compression and slower
scans than a single sorted file. Sorting by `(entity_uid, t_latest)` *inside* the
file gives the same pruning benefit through row-group statistics, at no cost.

Source is a low-cardinality dictionary column, not a partition, for the same
reason: six values would multiply the file count by six for no query benefit at
this scale.

---

## 4. File properties

| property | value | why |
|---|---|---|
| compression | `zstd` level 3 | better ratio than snappy, still fast; widely supported |
| dictionary encoding | `entity_uid`, `source_id`, `entity_type`, `transition_type`, `to_state`, `from_state`, `evidence`, `certainty` | these are the bulk of the bytes and are highly repetitive |
| row group size | 128 MB target, one row group in practice | daily files are far below this |
| timestamps | `timestamp[us, tz=UTC]` | µs avoids the float-seconds rounding in the legacy JSONL |
| statistics | enabled on `t_latest`, `entity_uid`, `source_id` | drives predicate pushdown |
| page checksums | enabled | corruption is detected on read, not discovered years later |

`ingested_at` is deliberately excluded from partitioning and from every metric.
It is provenance, not time. `recorded_at` is not provenance — it carries the
causal order the folds depend on (see
[event-schema.md](event-schema.md) §3) — but it is not a partition key either:
rows are partitioned by when the change happened, not by when we noticed.

---

## 5. Rollup: daily → monthly after 30 days

Triggered monthly. A month `M` is eligible once every day in `M` is sealed **and**
the newest day in `M` is at least 30 days old.

1. Read all `date=` partitions belonging to `M`.
2. Assert: no `transition_uid` appears twice; the union row count equals the sum
   of the daily manifest row counts; every daily manifest hash still matches the
   file on disk.
3. Write `month=M/transitions.parquet`, sorted by `(entity_uid, t_latest)`.
4. Write `_manifests/rollup/M.json`: the monthly file's hash and row count, plus
   **the full list of absorbed daily filenames with their original hashes and row
   counts**.
5. Verify the monthly file re-reads to exactly the same row multiset.
6. Only then delete the daily partitions, in the same commit that adds the
   monthly file.

Step 4 is what keeps "never overwrite" honest. The daily files disappear, but
their fingerprints survive forever in the manifest, so any later claim that the
monthly file was tampered with is checkable against 30 independent hashes
recorded at 30 different times.

### Is rollup a violation of append-only?

No, under a precise definition: **no event row is ever mutated, dropped, or
reinterpreted.** Rollup is a lossless, verified, one-way change of *container*,
with the provenance chain preserved. It is the only operation permitted to remove
a file from `data/events/`, it runs alone (concurrency group), and it aborts on
any mismatch rather than proceeding.

The motive is real: 365 tiny Parquet files per table per year is 365 footers,
365 git objects, and a slow scan. Twelve monthly files are not.

---

## 6. Aggregates

Built by `scripts/build_aggregates.py`. Same discipline, different tenancy:

| table | partition | rebuildable? |
|---|---|---|
| `aggregates/daily` | `date=` (Berlin local day) | yes, from events alone |
| `aggregates/monthly` | `month=` | yes |
| `aggregates/data_quality` | `date=` | yes |

Aggregates are the one place where **recomputation is allowed**, because they are
a pure function of the events. But a recomputation that changes a published
number is a visible event in its own right: the new file carries a bumped
`aggregate_revision` and a `recomputed_because` string, and the old values remain
in git history. Silent restatement is not available.

Daily aggregates are stored in long format — one row per
`(local_date, metric, dimension, dimension_id)` — because the dimensions differ
per metric (some per station, some per source, some for the window as a whole)
and because `null` is a first-class outcome that a wide table with typed columns
expresses badly. Each row carries the value, `coverage_ratio`, `window_hours`,
`publishable`, `aggregate_revision` and `tuning_fingerprint`, following the
`null` convention from [event-schema.md](event-schema.md) §6.3.

Coverage metrics are always published, even when everything else in the window
is `null`: they describe our own observation rather than Berlin, and they are
exactly what a reader needs in order to interpret the nulls beside them.

The dashboard reads a small JSON projection of the aggregates (`site/data/`),
generated, never hand-edited.

---

## 7. Expected size

Order-of-magnitude, using the legacy data for calibration:

| table | rows/day | bytes/row (zstd) | per year |
|---|---|---|---|
| `transitions` | 20–80 | ~120 | ~2 MB |
| `observations` | ~1,700 (6 sources × 288 polls) | ~60 | ~35 MB |
| `aggregates` | ~50 | ~200 | ~4 MB |

Against the legacy `data/silver` at 6.4 MB **per day** (2.3 GB/year), the events
layer is roughly two orders of magnitude smaller while being strictly more
informative — it answers "when did this start and stop, and were we watching"
which the frame archive could not.

`observations` dominates, which is correct: the honest part of the record costs
more than the interesting part. If it ever became a problem, the lever is
reducing poll frequency — a real trade-off with a visible cost in bracket
width — never dropping the ledger.

Storage-size checks belong in CI against these budgets, so growth is caught as a
regression.

---

## 8. Reading

- point-in-time state: fold `transitions` over the last 30 days
- a month of history: one file
- a year: twelve files
- "was this metric trustworthy": join to `observations` on `observation_id`

A reader that filters on `t_latest` gets partition pruning from the directory
key and row-group pruning from the statistics, without an index. No database is
required, and none should be introduced: the files are the database.
