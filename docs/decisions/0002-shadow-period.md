# ADR 0002 — The shadow period: scheduled observation without publication

- **Status:** accepted 2026-10-10; schedules suspended the same day (section 5)
- **Date:** 2026-10-10
- **Question:** how does the observation period that README gate 5 requires
  come about, if scheduled collection is what the gates keep disabled?
- **Decision:** schedule the *rehearsal*, not the publication. The shadow
  runner observes every quarter hour; its sealed days are copied once a day to
  a `shadow-ledger` branch; the served site and the main branch's data layers
  stay untouched until the period has been reviewed.

---

## 1. Context

The [README](../../README.md#legacy-and-publication-boundaries) lists seven
prerequisites for scheduled collection and a public time series. Four are
properties of code and documents and are in place (fixture-backed parsing,
sources never resolving outages on failure, defined units and coverage,
retention-conformant sealing). Two are properties of an observation *period*:
durable state across independent runners with tested recovery (gate 2) and a
reviewed period that includes advancing source versions, openings, closures,
missing responses and recovery (gate 5). Neither can be satisfied by a manual
workflow that nobody triggers. The shadow workflow had never been run.

The paused prototype failed by committing every poll. The replacement
architecture keeps the raw layer out of git and makes the events ledger small
(ADR 0001 projects ~40 MB per year). The shadow runner already writes exactly
that ledger, into an evictable Actions cache, and the README says what is
missing before scheduling: a durable home for the state, and a recovery
exercise.

## 2. Decision

1. **Observation runs on a schedule**: `accessibility shadow observation`
   every 15 minutes (`7,22,37,52 * * * *`), the source's own update cadence.
   Each run observes once into the cached shadow tree and publishes nothing.
   Exit code 2 of the runner (source reachable but not current) is recorded as
   an observation outcome, not treated as a pipeline failure.
2. **The ledger branch is the durable state.** A daily `shadow seal` workflow
   seals closed days, rebuilds the private aggregates, verifies the retention
   contract and copies `events/`, `_manifests/`, `aggregates/`, the private
   site projection and `runs.jsonl` to the orphan branch `shadow-ledger`
   (`scripts/shadow_ledger.py publish`). One commit per day with changes.
   The raw buffer never leaves the cache: it is the 7-day layer.
3. **Recovery is the normal cold start.** When the observation workflow finds
   no events layer in its cache — first run, eviction, a new runner — it
   restores the sealed layers from the ledger branch before observing
   (`scripts/shadow_ledger.py restore`), so state is the fold of the ledger,
   as the architecture requires. What a cold start loses is the unsealed day's
   staging and pending flaps; the run records the gap. Gate 2's "tested
   recovery" is therefore exercised by design whenever the cache is evicted,
   and can be forced by deleting the cache.
4. **Nothing is published.** `site/` on `main`, the Pages deployment and
   `data/` on `main` do not change. The ledger branch carries a README that
   says it is rehearsal data, not evidence.
5. **The two workflows share one concurrency group**, so sealing never
   overlaps a run that could still be appending to the day being sealed.

## 3. Review of the period

The period is reviewed, not just accumulated. Before any publication decision:

- at least **30 sealed days** on the ledger branch;
- `runs.jsonl` covers the expected cadence: count gaps longer than 30 minutes
  and classify them (GitHub scheduling delay, source outage, runner failure);
  GitHub does not guarantee cron timing and disables schedules after 60 days
  without repository activity;
- the ledger shows **openings, closures and at least one source-version
  change** (parser version or DOM change) handled without a manufactured
  transition;
- at least one **cold start** restored from the ledger with the recorded gap;
- the retention check has passed on every seal;
- the aggregates' withheld values (coverage below threshold) are explained by
  the recorded gaps and nothing else.

The review is written as a dated document under `docs/`, like the snapshot
review of 10 September 2026. Only then does a separate decision cover
publication — which still requires the roster/topology validation (gate 7)
for any network-level claim, and the provenance question in
[data-sources.md](../data-sources.md) answered in writing by the operator.

## 4. Consequences

- Actions minutes: ~96 short runs a day plus one seal, on a public repository.
- A new branch with daily commits; the main branch's history is unaffected.
- If the period shows the pipeline is not fit, the ledger branch is deleted
  and nothing public has to be retracted.
- The legacy collector stubs stay disabled; this does not revive them.

## 5. Addendum, 10 October 2026: the first run and the suspension

The schedules went live at 10:39 UTC. A dispatched observation at 10:42 UTC
recorded a single outcome, `http_error`: `https://www.brokenlifts.org/`
answered **403**. A probe from the same runner image ten minutes later showed
why. The HTML pages (`/`, `/stations`, `/robots.txt`) sit behind a Cloudflare
managed challenge (`cf-mitigated: challenge`, "Just a moment…") for requests
from GitHub-hosted runners, whatever the identity: the shadow runner's own
User-Agent, `python-requests`, `curl`, a browser string, the `www` host and
the apex all received 403. The paused prototype still read the same page with
status 200 from GitHub Actions on 10 July 2026; the challenge is newer than
that. Only the RSS feed answered: `https://brokenlifts.org/rss`, 200, 9,445
bytes, 37 items, each with `hafas-nr`, `vbb-name`, `title`, `description`
("Außer Betrieb") and `aufzugs-id` — and no timestamp of any kind. That is
the feed the VBB lists as an open-data service ([data-sources.md](../data-sources.md)).

Two conclusions, and a decision by the operator:

- The rehearsal as designed cannot observe from a hosted runner. Resuming it
  means a feed-based source (new parser, fixture, event identity from
  `aufzugs-id` instead of the page's link IDs) and the written clearance from
  Sozialhelden e.V. that the provenance section already asks for. The gates in
  README are unchanged.
- BrokenLifts publishes the live state and nothing else. The only thing this
  repository could add is the time axis — durations and recurrence — and that
  is exactly the part that needs a run of thirty days and a second party's
  permission. The operator's reading: the live state exists, it does not have
  to be rebuilt here.

Both scheduled workflows were therefore **disabled** in the repository's
Actions settings at 10:50 UTC; the files stay for the record and for a manual
run. The `shadow-ledger` branch holds the one seal of that morning (zero sealed
days, one logged run) and is kept as the record of the attempt. The dispatched
seal did prove the publishing path: cache restore, retention check, orphan
branch, commit — recovery as designed, with nothing to recover. The site and
the September source statement are unaffected.
