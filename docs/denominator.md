# The denominator

Status: **implemented for the population and the join; the roster is not yet
available**, which is why no point estimate is published today.

Companion to [event-schema.md](event-schema.md) and [partitioning.md](partitioning.md).

## The problem with 216 hours

An absolute outage figure answers no question a reader has. "216 outage-hours at
Alexanderplatz" could be catastrophic or unremarkable depending on how many
lifts exist, how many stations there are, and how long the network runs. The
legacy prototype's central failure was a count with no denominator; replacing it
with a *different* count is not progress.

But the obvious fix is a trap. Dividing observed outages by the stations we can
observe produces a conditional mean over a set chosen by the outcome — it looks
precise and it understates, because the stations nobody reports on contribute
zero. And withholding the figure until coverage is good enough produces a blank
page, which also reads as "no problem". **Both replace an interval with a
zero-width claim.**

## The shape of the answer

Every station-second in the frame is accounted for as exactly one of:

| state | meaning |
|---|---|
| `OUT` | at least one monitored lift at the station was reported out |
| `KNOWN_OK` | we hold positive evidence the source covers this station, the source was current, and nothing was reported out |
| `UNKNOWN` | everything else |

and the result is published as a two-sided interval over the **whole** frame:

```
p_lo = OUT / D                  every unknown second was fine
p_hi = (OUT + UNKNOWN) / D      every unknown second was an outage
```

Blindness widens the interval instead of deleting the stations it applies to. A
point estimate `OUT / (OUT + KNOWN_OK)` is offered only when the unknown share
is below 10 %, and is provably inside the interval.

Beside the interval sits a tier of **floors** — positively observed counts and
hours — published under no coverage gate at all, because more blindness cannot
make a positive observation false.

### What this produces today

Run against the real feed with the current source, one Monday, two stations
reporting:

```
denominator            5 554.7 station-hours   (263 stations × ~21.1 h service)
out                       27.0 station-hours
known_ok                   0.0
unknown                 5 527.6   not_monitored 5 511.4 · roster_incomplete 16.2
share                  [0.49 %, 100 %]
point estimate         withheld
```

An interval from 0.49 % to 100 % is useless as a headline — and it is the
correct output. It says we can see two of 263 stations. The alternative,
`27.0 / (2 × 21.1) = 64 %`, is a precise-looking number about two lifts wearing
a network's name.

**`KNOWN_OK` is structurally unreachable until the source publishes a station
roster.** That is not a defect in the code; it is the state of our knowledge.

## Why one source is not enough

Neither operator's stations are a majority of the frame:

| scope | elevator-equipped |
|---|---|
| U-Bahn only | 118 |
| S-Bahn only | 119 |
| both (interchange) | 26 |
| **total** | **263** |

A source covering only S-Bahn stations reaches 145 of 263 (55 %); only U-Bahn,
144 of 263 (55 %). **Measuring every elevator needs both.** At the 26 interchange
stations either operator's source might name the station while the lifts belong
to the other, so coverage there has to be established per station, not assumed
from the station's lines.

### What coverage actually buys

Measured on the real population, one day, two stations reporting outages:

| monitoring | interval | point estimate |
|---|---|---|
| fault list naming 2 stations | [0.41 %, 100 %] | withheld |
| + an S-Bahn inventory (145) | [0.41 %, 44.1 %] | withheld |
| + both inventories (263) | [0.41 %, 0.4 %] | 0.41 % |

The floor never moves — it is what we positively observed, and no amount of
blindness makes it false. What coverage buys is the **ceiling**. This is also
why the kind of source matters more than the number of them: a fault list can
lower nothing.

## Source kinds, and why the difference decides everything

| kind | can open an outage | can make a station known-good |
|---|---|---|
| inventory with per-facility state | yes | **yes**, while it is current and complete |
| fault list ("what is broken now") | yes | **never** |

Absence from a fault list is a default, not an observation. The 2011 Sozialhelden
codebase makes this concrete: its parser writes a "working" event for every lift
*absent* from the fetched page. We may take coverage and outages from such a
source; we may never take its silence as health.

Monitoring evidence is therefore typed per source per station, and it **expires**
(90 days by default). A station whose evidence goes stale moves to `UNKNOWN`, not
to a structural zero in the numerator — otherwise a source quietly dropping an
operator's feed would read as the network improving.

## The frame — which stations count

A station is in the frame when both hold:

1. **Service:** served by a trip whose route matches an `(agency_id, route_type)`
   pair — `796/400` (BVG U-Bahn) or `1/109` (S-Bahn Berlin).
2. **Equipment:** at least one `pathways.txt` row with `pathway_mode=5` has an
   endpoint at the station.

Measured against the VBB feed for service 2026-06-02 … 2026-12-12:

| set | stations | elevator-equipped |
|---|---|---|
| BVG U-Bahn | 170 | 144 |
| S-Bahn Berlin | 168 | 145 |
| **union** | **311** | **263** |

48 in-scope stations have pathway data and no elevator edge; 0 have no pathway
data at all. The two are counted separately and must stay separate: the first is
evidence about the station, the second is evidence about the feed.

**Agency-scoped, not route-type-scoped.** `route_type=109` alone pulls in
Mitteldeutsche Regiobahn stations hundreds of kilometres away. **Not
geographic either:** an "all Berlin stations" denominator divides elevator
outages by tram stops that have no elevator to lose.

## The denominator is service time, not clock time

First to last departure per station per service day, taken from `stop_times.txt`.
Measured over the 263 equipped stations on sample days in the feed:

| day | median span | Σ span ÷ Σ 24 h |
|---|---|---|
| Monday | 21.1 h | 0.880 |
| Friday | 23.3 h | 0.958 |
| Saturday | 24.2 h | 0.987 |
| Sunday | 21.9 h | 0.899 |

A 24-hour denominator deflates the weekday rate by about an eighth, in one
direction, using data the ingest already reads. Saturday exceeds 24 h because a
service day runs past midnight, which is why spans are stored per
`(station, service_id)` and expanded per date rather than assumed.

A station with no scheduled service on a date contributes zero denominator that
day and stays in the frame, so a construction closure cannot improve the rate by
removing the stations most likely to have a lift out.

## The join

The source names stations with bare DHID numbers; the feed names them with
prefixed ids whose platforms hang off a parent station.

**Source side.** Exactly three shapes are accepted and canonicalised to nine
digits: `9\d{8}` (identity), `9000\d{8}` → `9 + s[4:]`, `9\d{6}` → `9 + 00 + s[1:]`.
Anything else **raises**. Blind slicing is specifically avoided: the feed's own
pathway node ids are plain 12-digit values like `000300001054`, and none of the
13,617 of them begins with `9000`, so slicing would turn a node id into a
plausible station number.

**Feed side.** Follow `parent_station` (bounded at depth 4; the current feed's
deepest chain is 1), then take `de:<ags>:<number>` of the root. Grouping by the
numeric component alone splits real stations into false siblings that each look
like they have no elevator — `de:11000:900003200` (a Hauptbahnhof platform)
declares its parent as `de:11000:900003201`.

**Never rebuild a key as `"de:11000:" + number`.** S Potsdam Hauptbahnhof is
`de:12054:900230999` and Brandenburg S-Bahn stations are in scope.

### Inconsistent parenting is a defect, not an ambiguity

Five station numbers in the current feed have some platform rows carrying a
`parent_station` and others orphaned, all under one name. The feed has told us
the answer once; the orphans follow it. These are resolved deterministically and
counted (`parenting_defects_resolved`), not treated as fatal — refusing the
release over them would block a perfectly usable feed, and all five are tram
stops that never enter the frame anyway. A number that points at two *different*
stations has no determinate answer and does block.

### Nothing is dropped

| verdict | meaning | effect |
|---|---|---|
| `matched` | resolved to a frame station | hours land on the station |
| `unmatched_malformed` | fails all three shapes | hours published as unmatched; id listed |
| `unmatched_unknown_id` | well-formed, not in this population | same |
| `out_of_scope` | a real station outside the frame | own dimension, own metric, gates nothing |

`out_of_scope` is kept apart from the unmatched verdicts on purpose: it means the
join worked and told us the frame predicate is too narrow. Suppressing a
measurement whenever the frame turns out to be wrong is how a frame stays wrong.

An unattributable outage never lowers the rate — it cannot enter a denominator it
is not in, and it is published as its own quantity.

## Storage

```
data/reference/population/population=<content-hash>/stations.parquet
                                                   /manifest.json
```

Keyed on **content**, not on a release date or an archive hash: two archives
yielding the same stations under the same predicate are the same denominator,
and a fix to the frame predicate writes a new population rather than trying to
overwrite an immutable one. A window's population is selected by the feed's own
service span, so a stalled adoption cannot silently serve last year's
denominator.

Reference tables are deliberately **not** in the event-table registry: an events
sealer that could see one could seal it into a partition claiming to be an event
log.

## What cannot be published from this data

| forbidden | why |
|---|---|
| anything worded "step-free" | `signposted_as` is empty on all 1,544 elevator pathway rows, so the feed cannot say whether two lifts are redundant or serial |
| a rate per *elevator* counted from `pathways.txt` | measured: 1,328 directed edges over the 263 stations, 664 distinct links, 401 links on the U-Bahn alone — against BVG's published 204 lifts across 143 U-Bahn stations. Even the tighter count overshoots by a factor of two, because a lift serving three levels yields more than one link |
| journey, OD-pair or network-reachability metrics | needs a step-free path model that does not exist; this is the legacy "map position without an observed location" defect in a new form |
| a denominator from `wheelchair_boarding` | all 497 Berlin `location_type=1` rows carry `'0'` — "no information" |
| ridership-weighted variants | no station-level ridership source exists for Berlin; stated as a limitation, never approximated |

An availability percentage is also deliberately not the headline. At 97.5 % per
lift a four-lift journey is step-free about 90 % of the time — availability
averages over machines while harm is a maximum over a chain, so its complement
reads reassuringly by construction.

## Corroboration of the frame

The U-Bahn side is independently confirmed. BVG publishes **204 working lifts
across 143 U-Bahn stations** (2025); this derivation finds **144 of 170** frame
U-Bahn stations elevator-equipped — a match within one station, against a
different frame (BVG counts 175 U-Bahnhöfe in total, we count only those served
by a BVG U-Bahn route in the feed).

The S-Bahn side cannot be checked the same way. S-Bahn Berlin reports roughly
161 of 168 stations as step-free, against our 145 of 168 elevator-equipped — but
BVG's own wording explains the gap: *"fast 90 Prozent durch eine **Rampe oder**
einen Aufzug stufenlos erreichbar"*. Step-free includes ramps and level boarding.
Of the 23 S-Bahn frame stations with no elevator edge, most are surface-level
suburban and Brandenburg stops (Borgsdorf, Schönfließ, Strausberg ×3,
Mühlenbeck-Mönchmühle) where a platform at grade needs no lift at all.

So the two figures are not in conflict; they measure different things — which is
exactly why nothing here is worded "step-free". A denominator audit against the
VBB station-access dataset would settle it directly, and is cheaper than any
status source.

## Verified, and not

Every GTFS figure here was measured directly from a VBB archive
(MobilityData mirror, service window 2026-06-02 … 2026-12-12) and reproduced
independently by `scripts/derive_population.py`. Not verified: that this archive
still matches what VBB serves, the source's licence terms for redistribution,
and whether the outage source publishes a station roster at all — which is the
single fact that decides whether a point estimate ever becomes available.
