# Transit Friction Audit

## Executive summary
**Status: partially implemented.**

The repository has a working MVP scaffold for v0.2 “Collect First” with Bronze/Silver/Gold directories, runnable scripts, workflows, and basic tests. However, live collection is currently blocked in this environment by missing runtime dependencies (`requests`, `pydantic`, `yaml`), several planned sources are unimplemented, and normalization/state-tracking capabilities are still limited.

## Verification commands

| command | result | notes |
|---|---|---|
| `python -m pip install -r requirements.txt` | fail | Proxy/index access failure (`403 Forbidden`), dependencies not installable in this environment. |
| `python scripts/check_environment.py` | pass | Reports missing `requests`, `pydantic`, `yaml`; write permissions OK. |
| `python scripts/collect_snapshot.py --no-network --dry-run` | pass | Manifest emitted; all sources failed gracefully due to `--no-network`/missing requests. |
| `python scripts/build_daily_summary.py` | pass | Built daily output for current date. |
| `python scripts/build_site_data.py` | pass | `ok`. |
| `python scripts/build_source_health.py` | pass | `health built`. |
| `python scripts/check_storage_size.py` | pass | Reports small repository data footprint. |
| `pytest -q` | pass | 4 passed, 1 skipped. |
| `python scripts/collect_snapshot.py --source brokenlifts` | pass (degraded) | Returns success exit with source failure warning (`requests missing`). |
| `python scripts/collect_snapshot.py --source vbb_gtfs_rt` | pass (degraded) | Returns success exit with source failure warning (`requests missing`). |
| `python scripts/collect_snapshot.py --frequent` | pass (degraded) | All frequent sources fail gracefully when requests unavailable. |
| `python scripts/collect_snapshot.py --help` | pass | Required CLI options are present. |

## Implementation checklist

| area | expected | actual | status | notes |
|---|---|---|---|---|
| Repo structure | Full expected tree from spec | Most exists; `src/transit_friction/sources/brokenlifts.py` missing; `data/state/` missing | ⚠️ partial | brokenlifts logic is embedded in `collect_snapshot.py`, not modular collector file. |
| Bronze/Silver/Gold directories | Present and populated by pipeline | Directories exist; runtime writes manifests/gold; no live bronze/silver produced in this env | ⚠️ partial | blocked by missing dependencies/network package install. |
| Manifests | Run manifests with required fields | Manifest includes all requested fields incl. warnings/dependency/raw policy | ✅ implemented | Failure isolation behavior is present. |
| Source health | Build and export site + gold health files | Implemented with core metrics fields | ✅ implemented | Built successfully from manifests. |
| CLI flags | `--source --all --frequent --hourly --daily --no-network --date --dry-run` | All present | ✅ implemented | Verified via `--help`. |
| Workflows | 4 workflows with dispatch + schedules | All four files exist and parse | ✅ implemented | Schedules avoid minute 0. |
| Tests | Broad parser/storage/normalization coverage | Minimal suite (4 passed, 1 skipped) | ⚠️ partial | many expected fixture-based tests missing. |
| Documentation | Scope, policy, limitations, pipeline clearly documented | Core docs exist | ⚠️ partial | implemented/planned source clarity needs tightening vs code reality. |

## Data sources

| source id | config exists | collector exists | live fetch tested | bronze output | silver output | status | notes |
|---|---|---|---|---|---|---|---|
| vbb_gtfs_rt | yes | yes (inline in script + source module present) | degraded only | expected yes | expected limited | ⚠️ partial | current script stores metadata summary; no protobuf raw commit. |
| vbb_fahrinfo_api | no | no | no | no | no | ❌ missing | listed in hourly set but not in config. |
| vbb_transport_rest | yes | yes | degraded only | expected yes | expected yes | ⚠️ partial | extracts remarks-based events. |
| bvg_transport_rest | yes | yes | degraded only | expected yes | expected yes | ⚠️ partial | wrapper API clearly identified in config. |
| brokenlifts | yes | partial (inline only) | degraded only | expected yes | expected yes | ⚠️ partial | no dedicated `sources/brokenlifts.py`. |
| bvg_traffic_news | yes | no | no | no | no | ⚠️ partial | documented blocked/unimplemented. |
| sbahn_disruptions | no | no | no | no | no | ❌ missing | in hourly list but absent in config/collector. |
| bvg_disturbed_network_wfs | no | no | no | no | no | ❌ missing | in hourly list but absent in config/collector. |
| vbb_gtfs_static | no | no | no | no | no | ❌ missing | not represented in code/config. |
| viz_public_transport | no | no | no | no | no | ❌ missing | in hourly list but absent in config/collector. |

## Data pipeline
- **Bronze:** path scheme and gz helpers exist; runtime intended to write `.json.gz` by source/date/time. In this audit run, no bronze files were created because live collection dependencies were unavailable.
- **Silver:** normalized event writing to `data/silver/friction_events/<date>.jsonl` exists, append behavior present.
- **Gold:** daily summary and source health builders run and write outputs; `site/data` artifacts are generated by script.
- **Manifest:** rich manifest schema is implemented with run-level and source-level result fields.
- **Source health:** includes `last_success`, `last_failure`, `consecutive_failures`, `average_response_time_ms`, `last_status_code`, `parser_status`, `last_event_count`, `last_warning`.
- **State tracking:** basic timestamps and event ids exist, but explicit robust new/ongoing/resolved state machine support is limited.

## GitHub Actions
- **Workflow status:** `collect-frequent`, `collect-hourly`, `collect-daily`, `collect-static` all exist with `workflow_dispatch` and cron.
- **Schedule status:** all avoid minute `0`; frequent uses `7,22,37,52 * * * *`.
- **Commit behavior:** frequent workflow commits only when staged diffs exist.
- **Storage safety:** no explicit large-binary guardrails beyond workflow/script conventions.

## Tests
- **Count/results:** `pytest -q` => 4 passed, 1 skipped.
- **Coverage:** basic normalization/storage checks appear present; many expected fixture and failure-mode tests are missing (source-result manifest tests, daily/source-health deeper assertions, and multi-source parser fixtures).

## Documentation
- Docs set exists and generally communicates project intent and ethics constraints.
- Main caveat: source implementation status in docs/config should be synchronized with actual implemented collectors and `collect_snapshot.py` source lists.

## Critical gaps
1. Missing installable runtime dependencies in current environment prevented live pipeline verification.
2. Several required/planned sources are missing from config and collectors (`vbb_fahrinfo_api`, `sbahn_disruptions`, `bvg_disturbed_network_wfs`, `vbb_gtfs_static`, `viz_public_transport`).
3. `brokenlifts` lacks expected modular collector file (`src/transit_friction/sources/brokenlifts.py`).
4. Expected `data/state/` directory missing; limits explicit state tracking expectations.

## Non-critical gaps
1. Test suite coverage is still thin versus requested fixture matrix.
2. Some normalization taxonomy diverges from requested category set (e.g., `crowding_signal`).
3. Repository has both newer bronze/silver/gold paths and legacy `data/raw`, `data/normalized`, `data/summaries` artifacts.
4. Workflow dependency install currently uses `|| true`, masking dependency failures in CI.

## Recommended next PR
**Title:** `chore: align source registry and collectors with v0.2 scope`

**Scope (focused):**
- Synchronize `config/sources.yml`, `collect_snapshot.py` source lists, and actual collector modules.
- Add missing placeholder entries for planned sources with explicit `implemented: false` + limitations.
- Move `brokenlifts` logic into `src/transit_friction/sources/brokenlifts.py` (small refactor only).
- Add minimal tests asserting source registry parity (config vs CLI sets).
