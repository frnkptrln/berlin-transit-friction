# Source snapshot review · 10 September 2026

## Scope and decision

Reviewed a **single dated source statement** for the explanatory site. This is
not approval to schedule a collector, publish duration trends or assert route
reachability. The source data comes from [BrokenLifts](https://brokenlifts.org/).

- Source timestamp: `2026-09-10T19:57:00+02:00`.
- Capture timestamp: `2026-09-10T18:05:56.605304+00:00`.
- HTTP status: 200; final URL: `https://brokenlifts.org/`.
- Payload SHA-256: `2c366454ca93a05855cd38ea4e4309dd9f027bfc1f3d2ac66b24b53e61a1f227`.
- Parser: `brokenlifts-html/2`.
- Site projection: `site/data/accessibility-snapshot.json`.

## Checks performed

The current site uses server-rendered `.broken-count`, `.last-updated`,
`.station-list > ul`, `.station-name a` and explicit
`a.elevator-link.elevator-broken` markers. These differ from the legacy fixture.
The actual page and its parsed output were compared, including every broken link:

| Quantity | Source/DOM | Parsed projection |
|---|---:|---:|
| Explicit broken lift links | 35 | 35 unique source asset IDs |
| Station groups containing those links | 25 | 25 station identities |
| Berlin subset (`de:11000:`) | 20 stations | 28 assets |
| Other station IDs | 5 stations | 7 assets |

All link identities and station groups agree; there are no parser warnings,
missing labels, duplicate assets or advertised/parsed count mismatches. Stations
outside Berlin include Lübbenau, Wittenberge, Birkenstein, Blankenfelde and
Ludwigsfelde-Struveshof. Their observations must not become Berlin-wide counts.

An earlier independent capture at `2026-09-10T17:58:31.350648+00:00` showed the
same source timestamp and same 35 broken IDs. Applying the first capture opened
35 observed episodes in a private shadow tree. Applying the second produced
**no new transitions** and retained all 35; an unchanged source version did not
resolve an outage. Replaying the second capture again produced no transitions.
Raw captures and the shadow ledger are ignored, private working files, not
published research history.

## What is supported

“At the stated source time, BrokenLifts reported these 35 lifts as broken in
Berlin-Brandenburg; 28 have Berlin station identifiers.” Individual source links
let readers examine the actual lifts. Age is visible. These are observations of
a provider's statements, not independent inspections of the facilities.

## What is not supported

- the number of inaccessible stations, lost journeys or affected passengers;
- outage start times, durations, recurrence, a trend or service quality rate;
- a full accessible network or verified station topology;
- continuity between modern and legacy lift identifiers;
- a verified denominator from the source's advertised total alone.

The source now exposes a paginated [station list](https://brokenlifts.org/stations).
It is a useful new lead for a monitored roster. No complete versioned roster,
static-GTFS join or access-path validation was performed in this release.

## Remaining operational gate

A longer shadow period must cover genuinely advancing source updates, observed
openings and closures, failure and recovery, using durable storage. Two captures
of one source version are a useful replay check, **not** that longitudinal study.
The static snapshot can be served with these limits; automatic collection and
public duration publication remain disabled.
