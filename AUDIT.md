# Transit Friction Audit

## Executive summary
**Status: partially implemented (between scaffolded and functional MVP).**

As of **May 5, 2026**, the repository has a functional v0.2 “Collect First” spine: structure, collector CLI, manifesting, Silver normalization, Gold/site builders, source-health aggregation, and passing baseline tests. However, coverage against the requested scope is incomplete: several required sources are not implemented, live fetch verification is blocked by outbound proxy restrictions in this environment, and state-tracking/de-dup behavior remains basic.

## Verification commands

| command | result | notes |
|---|---|---|
| `python -m pip install -r requirements.txt` | pass | Requirements already installed; no install block in this run. |
| `python scripts/check_environment.py` | pass | Reports `yaml` missing; `requests`/`pydantic`/`pytest` OK; write perms OK. |
| `python scripts/collect_snapshot.py --help` | pass | All required CLI options present. |
| `python scripts/collect_snapshot.py --no-network --dry-run` | pass | Graceful degraded manifest; source failures isolated. |
| `python scripts/build_daily_summary.py` | pass | Built current-day daily output. |
| `python scripts/build_site_data.py` | pass | Site data artifacts regenerated. |
| `python scripts/build_source_health.py` | pass | Source health artifact regenerated. |
| `python scripts/check_storage_size.py` | pass | Data footprint small. |
| `pytest -q` | pass | 8 passed. |
| `python scripts/collect_snapshot.py --source brokenlifts` | pass (degraded) | Runtime succeeded; live fetch blocked by proxy `403` tunnel failure. |
| `python scripts/collect_snapshot.py --source vbb_gtfs_rt` | pass (degraded) | Runtime succeeded; live fetch blocked by proxy `403` tunnel failure. |
| `python scripts/collect_snapshot.py --frequent` | pass (degraded) | Runtime succeeded; all live sources blocked by proxy `403` tunnel failure. |

## Implementation checklist

| area | expected | actual | status | notes |
|---|---|---|---|---|
| Repository structure | Full expected files/directories from scope | Most present; `src/transit_friction/sources/brokenlifts.py` missing; `data/state/` missing | ⚠️ partial | `brokenlifts` handled inline in snapshot script. |
| Bronze/Silver/Gold model | Functional layered storage and outputs | Bronze/Silver write code exists; Gold/site build works; no live bronze writes in this environment | ⚠️ partial | Live collection blocked by network proxy. |
| Collection manifest | Full run/source fields and warning capture | Implemented with all requested manifest fields | ✅ implemented | Includes dependency/rate-limit/raw-policy fields. |
| Source health | Gold + site health outputs with key metrics | Implemented and generated | ✅ implemented | Includes last success/failure, avg response, warnings, etc. |
| CLI behavior | Required flags and modes | All required flags found | ✅ implemented | `--source --all --frequent --hourly --daily --no-network --date --dry-run` present. |
| GitHub Actions | Four workflows, dispatch + schedule | All four workflow files exist | ✅ implemented | Schedules present and avoid minute 0. |
| Tests/fixtures | Broad parser + pipeline coverage | Basic coverage only; core fixtures present; many expected scenarios absent | ⚠️ partial | Current suite passes but is narrow. |
| Documentation | Scope, ethics, B/S/G, limitations, ops caveats | Docs set is present and mostly aligned | ⚠️ partial | Needs tighter implemented-vs-planned clarity. |

## Data sources

| source id | config exists | collector exists | live fetch tested | bronze output | silver output | status | notes |
|---|---|---|---|---|---|---|---|
| vbb_gtfs_rt | yes | yes | attempted; blocked | intended yes | intended yes | ⚠️ partial | Graceful failure when proxy blocks or protobuf parser unavailable. |
| vbb_fahrinfo_api | yes | no | no | no | no | ⚠️ partial | Documented/planned but no collector implementation. |
| vbb_transport_rest | yes | yes | attempted; blocked | intended yes | intended yes | ⚠️ partial | Watchlist station probe logic present. |
| bvg_transport_rest | yes | yes | attempted; blocked | intended yes | intended yes | ⚠️ partial | Wrapper usage appears explicit. |
| brokenlifts | yes | partial (inline in script) | attempted; blocked | intended yes | intended yes | ⚠️ partial | Dedicated module file missing from expected tree. |
| bvg_traffic_news | yes | no | no | no | no | ⚠️ partial | Listed/documented but unimplemented. |
| sbahn_disruptions | yes | no | no | no | no | ⚠️ partial | Listed/documented but unimplemented. |
| bvg_disturbed_network_wfs | yes | no | no | no | no | ⚠️ partial | Listed/documented but unimplemented. |
| vbb_gtfs_static | yes | no | no | no | no | ⚠️ partial | Listed/documented but unimplemented. |
| viz_public_transport | yes | no | no | no | no | ⚠️ partial | Listed/documented but unimplemented. |

## Data pipeline
- **Bronze:** Helper/write path exists (`.json.gz` compact snapshots); avoids raw protobuf by policy. Live bronze writes could not be verified due to outbound proxy failures.
- **Silver:** Normalized `friction_events` pipeline exists and is invoked by snapshot flow.
- **Gold:** Daily JSON/Markdown and `site/data/*.json` generation scripts work in this environment.
- **Manifest:** Run manifests include run metadata, per-source results, warnings, dependency warnings, and storage policy.
- **Source health:** Builder produces both `data/gold/source-health/<date>.json` and `site/data/source-health.json`.
- **State tracking:** Present but limited; robust resolved/ongoing inference across runs is still basic.

## GitHub Actions
- **Workflow status:** `collect-frequent.yml`, `collect-hourly.yml`, `collect-daily.yml`, `collect-static.yml` exist and are valid YAML.
- **Schedule status:** Cron schedules avoid minute `0`; frequent cadence uses non-round minute pattern.
- **Commit behavior:** Workflows are set up to commit only changed artifacts.
- **Storage safety:** No aggressive raw binary storage behavior observed; policy aligns with compact snapshots.

## Tests
- **Result:** `pytest -q` passed with **8 passed**.
- **Coverage quality:** Good baseline for storage/normalization/pipeline smoke; insufficient depth for all planned collectors, manifest edge cases, and state-tracking transitions.

## Documentation
- **Strengths:** Purpose, ethics, and public-data posture are documented.
- **Gaps:** Implemented-vs-planned source status and reliability caveats should be kept strictly in sync with actual collectors and runtime behavior.

## Critical gaps
1. Required source set is mostly documented but not implemented (only subset actively collected).
2. `brokenlifts` does not exist as its own collector module file in expected structure.
3. `data/state/` layer expected by scope is missing.
4. Live verification currently blocked by network proxy restrictions (limits confidence in runtime source behavior).
5. De-dup/state transition logic remains lightweight for true multi-run event lifecycle tracking.

## Non-critical gaps
1. Test suite breadth is limited relative to expected fixture/test matrix.
2. Some legacy artifacts/directories coexist with v0.2 layout and may confuse contributors.
3. Source-health metrics are useful but still basic for long-term reliability analytics.

## Recommended next PR
**Title:** `chore: complete v0.2 source registry parity and state scaffolding`

**Scope:**
- Add missing collector stubs/modules (explicitly non-fetching if needed) for documented sources.
- Move `brokenlifts` logic into `src/transit_friction/sources/brokenlifts.py`.
- Add `data/state/` scaffolding and minimal lifecycle-state persistence contract.
- Add parity tests ensuring `config/sources.yml`, CLI source groups, and implemented modules stay synchronized.
