# Legacy data cleanup

Prepared: 2026-09-16. Implements the accepted [retention decision](../RETENTION.md#legacy-data).

The paused prototype's data is retained for the pipeline postmortem described in
[the legacy assessment](legacy-assessment.md). It is not evidence of transport
reliability and does not belong alongside the replacement event model.

## Preservation

The historical state reviewed on 2026-07-10 is commit
[`fce147726a8e148bb8fc5ab4f6d9a3925958fae9`](https://github.com/frnkptrln/berlin-transit-friction/commit/fce147726a8e148bb8fc5ab4f6d9a3925958fae9).
The documentation already called this state `legacy-v0`, but the branch was
missing at the cleanup audit. It is restored at that exact commit before opening
the removal PR.

Every one of the 31,283 removed file paths has the same Git blob SHA in that
historical commit and in the cleanup base
`66939ca620ef4f0224bce44f60a8248be98ab86d`. The recursive tree responses were
complete. The seven directory tree SHAs also match:

| Directory | Files | File bytes | Preserved Git tree SHA |
|---|---:|---:|---|
| `data/bronze` | 28,412 | 6,310,831 | `edb8c3a7f75c69c60658c5c103e61f85495cb3da` |
| `data/gold` | 199 | 1,094,937 | `3bcd9c579b678cc6403de02a8ea22d672b81a712` |
| `data/manifests` | 2,601 | 9,743,942 | `077e87bb9541e3d8260d721a3018121a54bb4407` |
| `data/normalized` | 1 | 0 | `d564d0bc3dd917926892c55e3706cc116d5b165e` |
| `data/raw` | 1 | 0 | `d564d0bc3dd917926892c55e3706cc116d5b165e` |
| `data/silver` | 66 | 441,122,599 | `642a8d14ec62bad2113ae1fbaba5a151b1b1ba46` |
| `data/summaries` | 3 | 395 | `484202ca90ceee9de9b4847588f7b396443a5314` |
| **Total** | **31,283** | **458,272,704** | |

These are the stored file sizes in the inspected tree, not unpacked source sizes
or Git pack sizes. The working tree loses about 458.3 MB; a normal clone retains
the history and its objects. No history is rewritten.

## Inspect or restore historical evidence

Browse the [preserved data](https://github.com/frnkptrln/berlin-transit-friction/tree/legacy-v0/data).
For local analysis, use a separate directory:

```bash
git fetch origin legacy-v0
git worktree add --detach ../transit-friction-legacy origin/legacy-v0
```

Keep the original commit identifier with any postmortem. Do not treat these
records as a historical elevator-outage series.

## Active tree

The seven legacy data directories are removed and ignored. The environment
check creates only current-layout directories. Source code, source fixtures,
event-model contracts, the reviewed site snapshot and the served site remain.
Legacy collection workflows stay disabled; this change does not resume
collection or validate any network-level metric.

## Legacy code

Removed on 2026-10-10 from base commit
[`b124cb279890`](https://github.com/frnkptrln/berlin-transit-friction/commit/b124cb2798906fd2d1576db804e28001ebd02143):
the prototype's collectors (`scripts/collect_snapshot.py`,
`src/transit_friction/sources/`), normalisation (`normalize/`), summaries and
site generators (`build_daily_summary.py`, `build_site_data.py`,
`build_source_health.py`, `analysis/`, `output/`, `health.py`, `storage.py`),
their six tests and six fixtures — 37 files. The `legacy-v0` branch,
missing from the remote at the time of this cleanup, was recreated at the
preserved commit `fce147726a8e`; all seven data directory tree SHAs listed above
match it.

28 of the removed files are byte-identical on `legacy-v0`. These
9 were edited after the pause (output-root override for tests, the
transport.rest fallback); their last state is the base commit above:

- `scripts/build_daily_summary.py` (blob `1a7ed2bb871c`)
- `scripts/build_site_data.py` (blob `3ddd0dbba770`)
- `scripts/build_source_health.py` (blob `9528b4fae65e`)
- `scripts/collect_snapshot.py` (blob `de86bd60d899`)
- `src/transit_friction/sources/bvg_traffic_news.py` (blob `2bbbc72575b7`)
- `src/transit_friction/sources/vbb_departures.py` (blob `0d227c9f44d0`)
- `src/transit_friction/sources/vbb_journeys.py` (blob `327dcb12ec9d`)
- `tests/test_collect_snapshot_transport_rest.py` (blob `81f9213483f9`)
- `tests/test_pipeline_smoke.py` (blob `bf001c4310c1`)

The replacement event model, population frame, accessibility adapter, shadow
observation and the served site do not import any of the removed modules.
`requirements.txt` loses the GTFS-RT and pydantic entries that only the
prototype needed. No data directory changes; collection stays paused.
