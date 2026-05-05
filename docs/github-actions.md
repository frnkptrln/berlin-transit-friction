# GitHub Actions

## Time zones and cron
GitHub Actions cron schedules are in **UTC**, not Europe/Berlin local time.

## Workflows
- `collect.yml`: every 30 minutes + manual dispatch.
- `daily-summary.yml`: once daily in the evening Berlin-time approximation via UTC cron.

## Storage tradeoffs
To keep repository growth manageable, MVP collection stores compact raw JSON/metadata and avoids large binary snapshots by default.
