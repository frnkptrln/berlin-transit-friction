# shadow-ledger

Rehearsal data for the accessibility observation (ADR 0002). Written by the
`shadow seal` workflow once a day from the runner's shadow tree; read back by
the `accessibility shadow observation` workflow when its cache is cold.

- `events/`, `_manifests/` — sealed days of transitions and observations
- `aggregates/`, `site/` — private projections for review, not published
- `runs.jsonl` — every observation attempt with its outcome and warnings

This is not evidence about Berlin public transport and is not served anywhere.
It exists so that the observation period can be reviewed against the gates in
README.md before any scheduled publication.
