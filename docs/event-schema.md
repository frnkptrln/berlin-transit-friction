# Event schema

Status: **proposed**. Companion to [data-architecture.md](data-architecture.md).

Two append-only tables form the permanent record:

- `transitions` — an entity's known state changed
- `observations` — we attempted to look at a source, and this is what happened

Neither is derivable from the other. Both are kept forever.

---

## 1. Entities

A **entity** is the thing whose state we track. Not a message, not a frame — a
durable real-world object that a source reports on repeatedly.

| entity_type | example native id | source |
|---|---|---|
| `elevator` | BrokenLifts lift id | brokenlifts |
| `station_accessibility` | DHID / IFOPT station id | brokenlifts |
| `disruption` | operator notice id | bvg_traffic_news, sbahn_disruptions |

### Identity rules

1. `entity_uid = sha256(source_id ‖ entity_type ‖ source_native_id)[:20]`.
2. **The collection timestamp is never an input to the identity.** This was the
   defect that invalidated the entire legacy dataset.
3. If a source does not expose a stable native id, the entity is **not
   ingested**. A synthesised id built from a title, a hash of the description,
   or a position in a list is not identity — it is a rename waiting to happen.
   Such a source may still produce `observations` rows; it produces no
   transitions until it earns a stable key.
4. Identity is per source. The same physical elevator seen through two sources
   is two entities, reconciled (if ever) in the aggregate layer, with the
   mapping recorded explicitly.

---

## 2. State model

The state we record is **epistemic**: it is our knowledge of the entity, not a
claim about the world.

| state | meaning |
|---|---|
| `ok` | observed as working, or absent from a *complete and fresh* outage list |
| `impaired` | observed as broken / disrupted |
| `unknown` | we cannot currently say — coverage lost, source incomplete, source stale |

`unknown` is a first-class state, not a null. Its existence is what stops a
seven-hour collector outage from being silently recorded as seven hours of
working elevators.

### Transition types

| type | from → to | trigger |
|---|---|---|
| `opened` | `ok`/`unknown`/∅ → `impaired` | entity appears in a parsed outage list |
| `closed` | `impaired` → `ok` | entity absent from a **complete, fresh, non-stale** snapshot |
| `unknown_entered` | `ok`/`impaired` → `unknown` | coverage gap exceeded, or source degraded past trust threshold |
| `unknown_exited` | `unknown` → `ok`/`impaired` | coverage restored; `to_state` records what we found |
| `reopened` | `ok` → `impaired` within the merge window | flap correction; continues the previous episode |
| `attributes_changed` | state unchanged | a whitelisted descriptive field changed materially |
| `retired` | any → ∅ | source stopped listing the entity entirely for `retire_after`; the entity, not its state, ended |

`attributes_changed` is whitelist-driven (`station_id`, `station_name`,
`status_text`, `source_url`). Without a whitelist it degenerates into a
per-poll diff stream, i.e. back to archiving frames.

---

## 3. `transitions` schema

| field | type | null | notes |
|---|---|---|---|
| `transition_uid` | string(40) | no | `sha256(entity_uid ‖ to_state ‖ t_latest ‖ evidence)[:20]` — idempotency key |
| `schema_version` | int16 | no | additive changes bump this; breaking changes fork the directory |
| `entity_uid` | string(20) | no | see §1 |
| `entity_type` | dict<string> | no | |
| `source_id` | dict<string> | no | matches `config/sources.yml` |
| `source_native_id` | string | no | kept verbatim for traceability |
| `transition_type` | dict<string> | no | §2 |
| `from_state` | dict<string> | yes | null only for the first transition of an entity |
| `to_state` | dict<string> | no | |
| **`t_earliest`** | ts(µs, UTC) | no | earliest instant the change can have happened |
| **`t_latest`** | ts(µs, UTC) | no | latest instant it can have happened = the observation that revealed it |
| `t_source` | ts(µs, UTC) | yes | the source's own timestamp for the change, if it publishes one |
| `certainty` | dict<string> | no | `observed` \| `bounded` \| `inferred` |
| `evidence` | dict<string> | no | see §4 |
| `observation_id` | string(20) | no | FK → `observations`; the row that justified this transition |
| `prev_observation_id` | string(20) | yes | the last trustworthy look *before* it; defines `t_earliest` |
| `gap_before_s` | int32 | no | seconds between `prev_observation_id` and `observation_id` |
| `episode_id` | string(20) | no | groups `opened … closed` including reopens; stable across the episode |
| `station_id` | string | yes | only when observed, never inferred |
| `station_name` | string | yes | |
| `line_id` | string | yes | only when the source states it |
| `status_text` | string | yes | verbatim from source |
| `quality_flags` | list<dict<string>> | no | e.g. `flapping`, `long_gap`, `debounced`, `late_arrival` |
| `run_id` | string | no | provenance |
| `parser_version` | string | no | provenance |
| `ingested_at` | ts(µs, UTC) | no | wall clock of the writer; **never** used for partitioning or metrics |

### Time is a bracket, not a point

This is the core of the schema. A transition observed by polling is never known
to the second; it is known to lie in an interval:

```
   last trustworthy look          the look that revealed the change
   ─────────┬───────────────────────────────┬─────────
        t_earliest                       t_latest
            └────── the change happened somewhere in here ──────┘
```

- Normal 5-minute cadence: `t_latest − t_earliest ≈ 300 s`. Fine.
- After a two-hour collector failure: `t_latest − t_earliest = 7200 s`. The
  outage may have begun any time in those two hours.

`t_source` collapses the bracket when the source publishes its own change time;
then `certainty = observed`. Otherwise `certainty = bounded`, and every duration
computed downstream is a **range**:

```
duration_min = t_earliest(close) − t_latest(open)
duration_max = t_latest(close)   − t_earliest(open)
```

Aggregates publish `duration_min`, `duration_max`, and a point estimate
(midpoint) — always all three. A single number with the uncertainty discarded is
how the legacy dashboard claimed precision it never had.

`certainty = inferred` is reserved for rows written by policy rather than
observation (`retired`, and nothing else at present). Inferred rows are excluded
from duration metrics by default.

---

## 4. `evidence` — why we believe the transition

| evidence | applies to | meaning |
|---|---|---|
| `listed_in_complete_snapshot` | `opened` | entity present in a snapshot that passed the completeness check |
| `absent_from_complete_snapshot` | `closed` | entity absent, snapshot complete **and** fresh |
| `source_explicit_resolution` | `closed` | source itself reported resolution (`t_source` set) |
| `coverage_lost` | `unknown_entered` | gap exceeded `max_trust_gap_s` |
| `source_degraded` | `unknown_entered` | fetch failed, parse failed, or completeness check failed |
| `source_stale` | `unknown_entered` | `source_updated_at` did not advance for `max_source_stale_s` |
| `coverage_restored` | `unknown_exited` | first trustworthy observation after a gap |
| `flap_correction` | `reopened` | re-impaired inside `reopen_merge_window_s` |
| `retention_policy` | `retired` | entity unlisted for `retire_after`; carries `certainty = inferred` |

**The hard rule.** `closed` may only ever carry `absent_from_complete_snapshot`
or `source_explicit_resolution`. There is no evidence value that lets a failure,
a timeout, a parse error, an incomplete list, or a stale feed close an outage.
This is the schema-level expression of the invariant already implemented in
`accessibility/lifecycle.py` and it must survive every future source.

A snapshot is **complete** when the source's own update timestamp is present,
its advertised count is present, and the number of distinct parsed entities
equals that count. It is **fresh** when `source_updated_at` is newer than the
newest `source_updated_at` already folded into state. Completeness is a property
of one observation, never an assumption about the provider.

---

## 5. Flapping

A source that alternates between two states across consecutive polls will, in a
naive design, manufacture unlimited outages. Four mechanisms, applied in order:

### 5.1 Asymmetric confirmation (hysteresis)

| direction | required confirmations | required dwell | rationale |
|---|---|---|---|
| → `impaired` (open) | 1 | 0 s | a real outage should surface immediately; a false open is visible and cheap to correct |
| → `ok` (close) | 2 consecutive | ≥ 600 s | a false close **splits one outage into several**, inflating counts and deflating durations — the expensive error |

The asymmetry is deliberate. Under-counting outages is a smaller lie than
inventing them.

### 5.2 Debounce must not distort time

A pending change waits in the raw-layer working state, **not** in the ledger.
When it is finally committed, the row's `t_earliest`/`t_latest` are those of the
**first** observation that showed the new state — not the confirming one. The
debounce delays *writing*, never *dating*. The row carries `quality_flags:
["debounced"]` so the delay is auditable.

If a pending change reverses before confirming, nothing is ever written. Those
non-events are counted per entity per day in the aggregate layer as
`suppressed_flaps`, so suppression is visible rather than silent.

### 5.3 Reopen merging

If an entity returns to `impaired` within `reopen_merge_window_s` (default
1800 s) of a `closed`, we do not open a new episode. We write a `reopened` row
carrying the **same `episode_id`** and `evidence = flap_correction`.

Because the tables are append-only, the earlier `closed` row is never edited. The
episode view (§7) folds the log and treats the closed interval as an internal
gap of one continuous episode. The ledger keeps the full history of what we
believed and when; the view keeps the best current reading. Both are needed —
the first for auditing, the second for metrics.

### 5.4 Quarantine

Per entity, over a rolling 24 h: if committed transitions ≥ 6, the entity is
flagged `flapping`. Effects:

- subsequent rows carry `quality_flags: ["flapping"]`;
- the entity is **excluded from headline aggregates** and reported separately
  under `data_quality`;
- it is not deleted, not suppressed, and not silently dropped.

Six state changes in a day is almost never an elevator. It is a parser or a
source problem, and it belongs in the data-quality report, not in a claim about
accessibility.

### 5.5 Tuning parameters

All thresholds live in one versioned config block; changing one is a change to
the measurement and must appear in the changelog and in the aggregate metadata.

| parameter | default | governs |
|---|---|---|
| `confirm_open_n` / `confirm_open_s` | 1 / 0 | §5.1 |
| `confirm_close_n` / `confirm_close_s` | 2 / 600 | §5.1 |
| `reopen_merge_window_s` | 1800 | §5.3 |
| `flap_quarantine_n` / `_window_s` | 6 / 86400 | §5.4 |
| `max_trust_gap_s` | 1800 | §6 |
| `max_source_stale_s` | 3600 | §6 |
| `retire_after_s` | 2592000 (30 d) | §2 |

Every aggregate file records the parameter set that produced it. Recomputing a
historical window with different thresholds produces a *different, separately
labelled* aggregate — it never overwrites the old one.

---

## 6. Missing polls

### 6.1 `observations` schema

One row per source per attempt. Written **even when the fetch fails** — that is
the entire point.

| field | type | null | notes |
|---|---|---|---|
| `observation_id` | string(20) | no | `sha256(source_id ‖ attempted_at ‖ run_id)[:20]` |
| `schema_version` | int16 | no | |
| `run_id` | string | no | |
| `source_id` | dict<string> | no | |
| `attempted_at` | ts(µs, UTC) | no | when we started the request |
| `observed_at` | ts(µs, UTC) | yes | when the response landed; null if none did |
| `source_updated_at` | ts(µs, UTC) | yes | the source's own timestamp |
| `outcome` | dict<string> | no | `ok` \| `incomplete` \| `stale` \| `parse_error` \| `http_error` \| `timeout` \| `skipped` |
| `complete` | bool | no | completeness check result (§4) |
| `trusted_for_resolution` | bool | no | `complete ∧ fresh ∧ ¬stale` — the only rows that may justify a `closed` |
| `entity_count` | int32 | yes | distinct entities parsed |
| `advertised_count` | int32 | yes | count the source claims |
| `http_status` | int16 | yes | |
| `latency_ms` | int32 | yes | |
| `payload_sha256` | string(64) | yes | content hash of the fetched payload |
| `gap_before_s` | int32 | no | since the previous `trusted_for_resolution` row for this source |
| `warnings` | list<string> | no | |
| `collector_version` / `parser_version` | string | no | |

`payload_sha256` is kept although the payload itself is not. It costs 64 bytes
and answers a question the discarded frames cannot: *was the source actually
updating?* An unchanged hash across hours, combined with a non-advancing
`source_updated_at`, is a **stuck feed** — which looks exactly like "no
disruptions" unless you record it.

### 6.2 Gap semantics

A **gap** is any interval between consecutive `trusted_for_resolution` rows for
a source. Three regimes:

| gap length | treatment |
|---|---|
| ≤ `max_trust_gap_s` (1800 s) | tolerated; widens the time bracket of any transition detected after it |
| > `max_trust_gap_s` | every entity in `impaired` gets `unknown_entered` / `coverage_lost`; on recovery, `unknown_exited` records what was actually found |
| source never seen in a window | the window has **no coverage** for that source; metrics for it are `null`, not `0` |

Note what does *not* happen at any gap length: no outage is closed. A gap
suspends knowledge; it never supplies good news.

### 6.3 The distinction the schema is built to protect

| situation | `outage_count` | `coverage_ratio` | dashboard |
|---|---|---|---|
| polled all day, nothing broken | `0` | `1.0` | "0 outages" |
| collector down all day | `null` | `0.0` | "no data" |
| collector down 09:00–17:00 | `null` | `0.66` | "insufficient coverage" |
| polled all day, 3 outages | `3` | `1.0` | "3 outages" |

`0` and `null` are different values with different renderings. A count is only
ever emitted for a window whose `coverage_ratio ≥ min_publish_coverage` (default
0.9); below that the count field is `null` and `coverage_ratio` explains why.
The dashboard is forbidden from coercing `null` to `0` — a chart that plots a
collector outage as a perfect day is worse than no chart.

Coverage is computed **per source**, then per metric from the sources that metric
depends on. A day with full BrokenLifts coverage and no BVG coverage has an
elevator metric and no disruption metric. There is no repository-wide coverage
number.

---

## 7. Derived views

Neither view is stored as truth; both are folds over the ledger, rebuilt on
demand and cached in the aggregate layer.

**`current_state`** — last transition per `entity_uid`, plus the age of the
observation that produced it. If that age exceeds `max_trust_gap_s`, the entity
renders as `unknown` regardless of its last recorded state. Staleness is
evaluated at read time, not frozen at write time.

**`episodes`** — folds `opened → (reopened)* → closed` into one interval per
`episode_id`, carrying `duration_min`, `duration_max`, `duration_point`,
`unknown_seconds` (time inside the episode when coverage was lost),
`reopen_count`, and inherited `quality_flags`. An episode with
`unknown_seconds > 0` can never be reported as a precise duration.

Open episodes have no `duration_max`. They are reported as "ongoing, at least
`duration_min`" — never closed at the window boundary for tidiness.

---

## 8. Idempotency, corrections, evolution

**Idempotency.** Re-running a day's ingestion must not duplicate rows. Writers
deduplicate on `transition_uid` / `observation_id`; readers keep the row with the
lowest `ingested_at`. Sealing (see [partitioning.md](partitioning.md)) enforces
uniqueness before a partition becomes immutable.

**Corrections.** Sealed rows are never edited or deleted. A correction is a new
row of `transition_type = correction` carrying `corrects_transition_uid` and a
reason. Views apply corrections when folding; the ledger keeps the mistake. A
pipeline that can rewrite its own history cannot be audited, and this project's
whole problem was that nobody could audit it.

**Evolution.** Additive columns bump `schema_version`; readers must tolerate
older rows lacking them. A change in the meaning of an existing column is a
breaking change and forks the directory (`transitions_v2/`) — old partitions stay
readable under their original semantics. Threshold changes (§5.5) are not schema
changes but *are* measurement changes and are recorded in aggregate metadata.
