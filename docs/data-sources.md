# Data sources

## Implemented accessibility source

[BrokenLifts](https://brokenlifts.org/) aggregates public lift disruption signals.
Its current scope is Berlin-Brandenburg. The current parser supports the German
server-rendered list and the preserved legacy fixture; an unrecognized language
or changed layout fails closed rather than fabricating a complete response.

The source's update timestamp, advertised broken count, explicit broken-lift
links, source asset IDs, DHID station IDs and station names support a dated
provider statement. The page's advertised total is not a validated population.
The new paginated [all-station directory](https://brokenlifts.org/stations) may
support a future versioned roster after complete enumeration and checking.

[Snapshot review, 10 September 2026](snapshot-review-2026-09-10.md) records the
current format and observed identities. Old and new asset IDs require an explicit
crosswalk before any historical continuity claim.

## Provenance and licence of the BrokenLifts data

Checked on 10 October 2026 against the live site.

- **Operator.** [Sozialhelden e.V.](https://www.sozialhelden.de/) (imprint:
  Andreasstraße 10, 10243 Berlin, `info@sozialhelden.de`). Concept, code and
  design by the Projektbüro Henkelhiedl; started as an open-source project at
  Random Hacks of Kindness Berlin in November 2011, relaunched in October 2014.
- **Upstream data.** The site names BVG, DB InfraGO and VBB as providers and
  says it polls the S-Bahn and BVG lift-disruption information every fifteen
  minutes. The VBB's own method note
  ([Aufzugsverfügbarkeit im VBB, 27 July 2020](https://unternehmen.vbb.de/fileadmin/user_upload/VBB/Dokumente/Verkehrsverbund/aufzugsverfuegbarkeit/aufzugsverfuegbarkeit-im-vbb-online.pdf))
  reads lift status every five minutes from the public DB interface *FaSta*.
  DB's FaSta (station facilities status) is published on the DB API marketplace
  under CC BY 4.0 — the same licence the VBB applies to
  [its own open datasets](https://unternehmen.vbb.de/digitale-services/datensaetze/).
- **The VBB lists BrokenLifts as a service.** Its *Digitale Services* page,
  under the sentence that all information is available free of charge as open
  data, links `brokenlifts.org/rss` as the
  [RSS feed for lift disruptions](https://unternehmen.vbb.de/digitale-services/aufzugsstoerungen-rss-feed/).
- **No licence text on brokenlifts.org.** Neither the start page, the *Über das
  Projekt* page nor the imprint states a licence or terms of use for the data
  or the page; the only reservation is a disclaimer on accuracy.

What follows for this repository: the facts (which lift is out of service when)
originate in CC BY 4.0 data, and the aggregator is promoted by the VBB as an open
service, so reading the public page at a low rate and publishing derived
intervals with attribution is defensible; but it is not an explicit permission
from Sozialhelden, and archival or a public time series goes beyond what the
RSS feed is advertised for. Before scheduled collection starts, ask Sozialhelden
e.V. in writing whether archival and publication of derived outage intervals is
acceptable, and whether the RSS feed is the preferred interface. The
attribution on the served pages names the operator and the three data
providers; keep it when the station-level pages come.

## Access from hosted runners (10 October 2026)

Probed from a GitHub-hosted runner (`ubuntu-24.04`), see ADR 0002, section 5:

| URL | Answer |
|---|---|
| `https://brokenlifts.org/`, `https://www.brokenlifts.org/` | 403, Cloudflare managed challenge, for every User-Agent tried (the shadow runner's own, `python-requests`, `curl`, a browser string) |
| `https://brokenlifts.org/stations`, `/robots.txt` | 403, the same challenge |
| `https://brokenlifts.org/rss` | **200**, `text/html; charset=UTF-8` despite being RSS 2.0, 9,445 bytes, no `Last-Modified`/`ETag`, `cf-cache-status: DYNAMIC` |
| `https://www.brokenlifts.org/rss` | 301 to the apex |

The feed (`<description>brokenlifts.org Rss-feed for HaCon</description>`,
`language de-DE`) carries one `<item>` per lift that is out of service, with
`<hafas-nr>` (VBB stop number), `<vbb-name>`, `<title>` (the lift's location
text), `<description>` ("Außer Betrieb") and `<aufzugs-id>`. It carries no
timestamps, no "since", no channel build date and no total count; the state is
whatever the feed says at the moment of the request. A feed-based source would
take its event identity from `aufzugs-id` and its station identity from
`hafas-nr`, and would have to carry the observation time itself. Reading the
feed is what the VBB advertises it for; archiving and publishing a time series
derived from it is the question to put to Sozialhelden e.V. first.

## Practical primary sources

- [VBB-BAV](https://www.vbb.de/barrierefrei-unterwegs/bav/): support for accessible
  onward travel when a lift is missing or unavailable.
- [S-Bahn lift and escalator notices](https://sbahn.berlin/fahren/bahnhofsuebersicht/barrierefrei-unterwegs/aufzugs-fahrtreppenstoerung/):
  direct operator notices.
- [BVG contact](https://www.bvg.de/de/service-und-kontakt): reporting and support.

The application links to these services. It does not scrape them at runtime or
submit reports.

## Legacy registry

`config/sources.yml` documents the paused prototype's source list, not a
promise of active or healthy collectors; the prototype's source modules were
removed from the active tree on 2026-10-10 (see
[the cleanup record](legacy-data-cleanup.md#legacy-code)). GTFS-RT, journey probes, BVG/S-Bahn
notices and other listed sources do not feed this release's public experience.
