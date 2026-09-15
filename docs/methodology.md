# Methodology

The usable site separates a fictional explanatory model, a dated real source
snapshot, and historical metrics. They cannot substitute for one another.
See [the experience contract](experience.md) and [the reviewed snapshot](snapshot-review-2026-09-10.md).

The legacy Bronze/Silver/Gold friction-count approach is withdrawn. Its historical
output is not evidence of Berlin transit quality. New observations use the
[transition ledger](event-schema.md) and [storage contract](../RETENTION.md).

The first measurement question concerns elevator outages. An explicit source
asset identifier is stable across polls; unchanged or incomplete observations do
not create a new outage or resolve an old one. Failed requests and parsing errors
are observations of source availability, never a transport all-clear.

Daily headline units are **station-hours with at least one observed lift outage**:
interval unions within each station, then sums across stations. Lift-hours are a
separate internal metric. Unknown intervals are excluded from certain lower
bounds and widen the range. Duration midpoints are averages of the bounded
station unions, including uncertainty straddling a day boundary.

Public historical values require sufficient coverage of their declared source
dependencies. Unobserved windows are null. The collection source covers
Berlin-Brandenburg; the current historical projection is not a Berlin-only rate.
A Berlin-only snapshot filter uses DHID identity, not name guessing.

No passenger tracking, crowding inference, invented geographic coordinates,
travel times or network reachability claims are made.
