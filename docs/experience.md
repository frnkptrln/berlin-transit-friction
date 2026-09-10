# Experience contract

## Purpose

Make one mechanism in Berlin transit barriers understandable: a moving train does
not guarantee a usable door-to-door journey when a lift is required. Let people
compare feasible improvements without pretending to evaluate a real station.

## The three evidence levels

1. **Explanatory model:** every node, edge and setting in `site/journey-model.js`
   is fictional. The six nodes represent street/platform layers at start, target
   and neighbouring station. Edges are directed travel sections, each with cost 1.
   This is not minutes, distance, effort, accessibility certification or a fare.
2. **Reviewed source snapshot:** explicit broken-lift statements from one complete
   BrokenLifts page. Source time, capture time, review time, parser version and
   payload SHA-256 accompany the small site projection. No extrapolation after
   the timestamp. Source area is Berlin-Brandenburg; Berlin is a DHID filter.
3. **Historical metrics:** derived from the observation/transition ledger with
   uncertainty and coverage. No historical values are shipped merely to fill
   this page. The empty projection is intentional and its message is useful.

No data flow connects the real lift list to the fictional route model. A visitor
cannot accidentally turn a source observation into a fabricated Berlin route.

## Model behavior

Default: step-free travel required; target lift failed; no alternative.
A breadth-first traversal uses only available edges and excludes stairs when a
step-free path is required. A second traversal may include unknown edges, but
this only establishes a possible route; it is never labelled confirmed.

| Change | Result |
|---|---|
| Default | No complete step-free route; reachable prefix remains visible |
| Stairs possible | Direct, three sections using the stairs |
| Target lift repaired | Direct, three sections using the lift |
| Accessible neighbour + outside path | Five sections; two extra sections |
| Independent backup lift | Direct, three sections even while first lift fails |
| Target lift unknown, no alternative | Access unconfirmed; no confirmed path |
| Unknown lift plus usable detour | Confirmed detour avoiding the unknown lift |

The alternative assumes the next station, its lift and the outdoor connection
are all usable. The second lift is parallel and independent, not another lift in
a serial access chain. The page explains these assumptions beside the result.

## Interaction and accessibility

Native labelled radios, select and checkboxes support keyboard operation.
An atomic polite result region and a textual ordered route describe the diagram's
meaning without relying on color or vision. Status uses words and symbols. Focus
is visible; reduced-motion preference disables scrolling/transition animation.
Small-screen layout stacks the controls. The SVG's detailed labels may require
zoom; the complete route and outcome are always repeated as normal text.

The source list uses DOM text nodes, validates HTTPS BrokenLifts links, conserves
unique station/asset counts and rejects malformed snapshots. Searching/filtering
cannot change the source-wide timestamp or count. Zero matches means no matching
statement in that snapshot, not working lifts. The page recomputes the age label
without making recurring requests. Over one hour is labelled old, not resolved.

The duration view requires the producer's unit, station-union aggregation marker,
valid consecutive calendar dates, finite ordered bounds, declared source
dependencies and source publication-coverage flags. Missing/unusable data never
becomes a chart at zero. No line connects across withheld days.

## Improvement actions

The page offers model comparisons for repair and independent access, plus actual
support links. The current [VBB-BAV information](https://www.vbb.de/barrierefrei-unterwegs/bav/)
describes route assistance and, where no accessible alternative exists, suitable
transport to an accessible stop. It is not a blanket taxi entitlement. The old
Muva offer is not used as a current recommendation.

Reports to operators need station/access identity, observation time and the
barrier's effect. This project has no report submission backend and sends no
messages on behalf of visitors.
