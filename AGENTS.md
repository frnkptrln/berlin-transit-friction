# Working in this repository

An observatory for lift outages in Berlin public transport: an explanatory
static site, a reviewed source statement, and an observation pipeline whose
scheduled rehearsal is suspended (ADR 0002, section 5).

## Checks

```bash
python -m pip install -r requirements.txt
python -m pytest -q
node --test tests/test_journey_model.cjs tests/test_scenario_model.cjs
python scripts/check_site.py          # served pages, assets, anchors, JSON, legacy isolation
python scripts/check_retention.py     # RETENTION.md is binding for every write
node tests/scenario-browser.cjs       # with Playwright Chromium
```

## Frozen material and rules

- `RETENTION.md` decides what may be written where. `site/data/` holds only
  reviewed projections; raw captures are never committed.
- `data/` on `main` is empty until a shadow period has been reviewed. The
  `shadow-ledger` branch is written only by the `shadow seal` workflow, which
  is disabled; do not re-enable the schedules without the operator's decision.
- `legacy-v0` is the preserved pre-pause state; it is read, never changed.
  The paused collector workflows stay as disabled stubs.
- The six-node network of the experience is fictional and says so; nothing on
  the site claims a real travel time, route or current lift state.
- The BrokenLifts data has no licence text; keep the operator and provider
  attribution on every served page (see `docs/data-sources.md`).

## Working alongside other agents

Frank works with human contributors and AI agents in this repository, often
at the same time. Agents using any model or provider are welcome. The
repository is their shared channel for coordination.

- Work on your own branch (`<agent>/…`, for example `codex/…` or
  `claude/…`). Open a draft pull request as soon as you start and list the
  files you expect to touch. Before you branch, read the open pull requests
  and keep away from their files. Never push to another agent's branch, and
  never to `main` directly.
- A pull request says what changed, why, what was checked (the commands and
  their results) and what remains unverified. Fix a failing check; do not
  weaken or skip it.
- Attribution is optional. Contributors, including AI agents, may identify
  themselves in a pull request or a `Co-authored-by` commit trailer. Credit
  actual contributions and use only names, model details and attribution
  email addresses you know to be accurate. If no attribution email is known,
  use the pull request description. No fixed agent, model or provider name
  is required.
- No status files, task lists or progress notes in the repository. The pull
  requests and the history are the record.
- Frozen material (below) is not edited in place. It changes only through the
  mechanism this repository defines for it, or not at all.
