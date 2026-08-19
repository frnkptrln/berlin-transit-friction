# ADR 0001 — Where the time series lives

- **Status:** accepted
- **Date:** 2026-08-19
- **Question:** should `data/events/` be published as a Hugging Face dataset
  instead of living in this git repository?
- **Decision:** **no, not now.** Keep events and aggregates in git. Adopt the
  Hugging Face-compatible layout immediately, so the move is cheap. Revisit
  against the explicit triggers in §5.

---

## 1. Context

The question is usually asked because a data-in-git repo has become painful.
Ours became painful — 536 MB across 28,478 files in the bronze and silver
layers alone — but from committing *frames*, not from committing *history*. The architecture in
[data-architecture.md](../data-architecture.md) removes that cause. The projected
permanent footprint is:

| table | per year |
|---|---|
| `transitions` | ~2 MB |
| `observations` | ~35 MB |
| `aggregates` | ~4 MB |
| **total** | **~40 MB/year** |

Ten years of collection is roughly 400 MB of Parquet — a large-ish but entirely
ordinary git repository. The premise that forces an external host is not
currently true.

Externalising storage is therefore not a size decision here. It is a decision
about distribution, discoverability, and operational surface — and those cut
both ways.

---

## 2. Options

### A. Keep everything in git (recommended)

**For.** One source of truth. Data changes appear in pull-request diffs, which
for an append-only ledger is genuinely readable — a day's transitions are dozens
of rows, and a reviewer can see that a suspicious close arrived with the right
evidence. Code and data version together, so a parser change and the rows it
produced are one commit. Zero extra secrets, zero extra failure modes in the
collector. GitHub Pages already serves the dashboard from the same repo.

**Against.** Repository grows monotonically and forever. Cloning gets slower for
contributors who only want the code. No dataset viewer, no
`load_dataset`-shaped access, low discoverability outside GitHub.

### B. Move the time series to a Hugging Face dataset

**For.** Parquet is the native format; the Hub's viewer and server-side query
work on hive-partitioned Parquet without conversion. `datasets` and DuckDB read
it directly over HTTP. The code repository stays small. Datasets are versioned
and the format is well-suited to an open-data project that wants to be found and
reused.

**Against.** The collector now needs a write token in CI, which is a new secret
and a new class of incident. Provenance splits across two systems: a PR in this
repo no longer shows what the run wrote, so review of the *data* — the thing that
went wrong last time — gets weaker exactly where it should get stronger. Code and
data can drift out of sync. Large files ride on git-lfs with its own quirks. The
dashboard would depend on a third party for its input. And it does not solve a
problem we currently have.

### C. Git as source of truth, Hugging Face as a derived mirror

**For.** Keeps A's review and provenance properties; adds B's reach. The mirror
is one-way, pushes only sealed/immutable partitions, is idempotent by content
hash, and a failure is non-fatal because it is a copy, not the record.

**Against.** Two places to keep consistent, one more workflow, one more secret,
and a public artefact whose licensing must be settled properly (§4).

---

## 3. Decision

**Adopt A now. Design so that C is a one-workflow addition. Do not consider B
until A actually hurts.**

Concretely:

1. `data/events/` and `data/aggregates/` stay in this repository.
2. The on-disk layout is *already* a valid Hugging Face dataset layout —
   hive-partitioned Parquet under a stable root, one row per record, no custom
   loading script. Nothing about publishing later requires a schema change.
3. A `README.md` with the dataset card (YAML `configs`/`data_files` block,
   licence, source attribution, coverage caveats) is written when — and only
   when — the mirror is enabled.
4. Revisit at the triggers in §5, or after 30 days of green shadow operation,
   whichever comes first.

The reasoning behind the ordering: the repository does not yet contain one row
of valid data. Publishing infrastructure before there is anything to publish is
how the last iteration accumulated 536 MB of the wrong thing. Earn the data
first; distribute it second.

---

## 4. Gates before any external publication

These block option C as much as option B, and none of them is a formality.

- **Source terms.** BrokenLifts is community-run; BVG, S-Bahn Berlin and VBB
  each have their own terms. Redistributing a *derived* dataset is a different
  act from polling a public page, and each source must be checked individually
  before its rows leave this repository. The project's MIT licence covers the
  code; it says nothing about the data.
- **Dataset licence and attribution.** A licence must be chosen deliberately
  (CC-BY-4.0 or ODbL are the plausible candidates) and per-source attribution
  stated in the card.
- **A card that carries the caveats.** Coverage ratios, the `null`-vs-`0`
  convention, duration bounds, and known parser limits belong *in* the dataset
  card. A dataset that travels without them will be misread as a reliability
  ranking of Berlin transport — which is exactly the misreading that stopped the
  last version.
- **Thirty days of reviewed shadow output.** Publication gate 6 in
  [README.md](../../README.md) already requires this, and it applies to
  distribution too.

---

## 5. Revisit triggers

Reopen this ADR when any one of these becomes true:

1. `data/events/` exceeds **250 MB**, or any single sealed daily partition
   exceeds **5 MB**;
2. `git clone` of the default branch exceeds **60 s** on a normal connection;
3. a second consumer needs bulk access — a notebook, a paper, another project —
   and is served badly by raw GitHub file URLs;
4. observation volume grows past what the per-year budget in
   [partitioning.md](../partitioning.md) §7 assumes, e.g. after adding sources.

Triggers 1 and 4 are asserted in CI, so this document gets revisited by a failing
build rather than by someone remembering.

---

## 6. Consequences for the ingestion workflows

This section applies whichever option is eventually chosen; the mirror-specific
parts are marked.

**Cadence and commits.** The collector runs frequently but writes rarely. It
appends to the ephemeral JSONL staging buffer and **only commits when a
transition was actually recorded** — dozens of commits per month instead of the
legacy 288 per day. The observation ledger is *not* committed per poll either; it
is sealed with the day. This is what makes data-in-git sustainable at all, and it
is a prerequisite for option A rather than a nice-to-have.

**Workflow set.**

| workflow | cadence | writes | commits |
|---|---|---|---|
| `collect` | every 5 min | `.raw/` only | never |
| `seal` | daily, 03:00 UTC | `date=D` partitions + seal manifest | one commit per day |
| `aggregate` | daily, after seal | `data/aggregates/`, `site/data/` | same commit as seal |
| `rollup` | monthly | `month=M` file, removes absorbed dailies | one commit per month |
| `mirror` *(option C only)* | weekly | Hugging Face dataset repo | none in git |

**Concurrency.** `seal`, `aggregate` and `rollup` share a concurrency group and
never overlap with each other or with a `collect` run that could still be
appending to the day being sealed. The 03:00 UTC grace period exists for this.

**Idempotency.** Every workflow must be safe to re-run. Sealing a sealed day is a
no-op; rolling up a rolled-up month is a no-op; mirroring an already-mirrored
partition is a no-op verified by content hash.

**Ordering (option C).** The mirror only ever pushes partitions that are already
sealed and committed here. It never pushes the hot day, never writes back, and
never gates the dashboard. If the mirror fails, the run is still green and the
next weekly run reconciles.

**Secrets (option C).** `HF_TOKEN` is a repository secret, write-scoped to the
single dataset repo, referenced only by the mirror workflow. It must not be
reachable from any `pull_request` or `pull_request_target` trigger, and the
mirror workflow must not run on forks.

**Failure posture.** A failed `collect` writes an `observations` row with the
failure outcome and exits zero — a source being down is data, not a broken
build. A failed `seal` exits non-zero and leaves the staging buffer intact, so
the day can be sealed on retry; the buffer's 7-day retention is the deadline.
