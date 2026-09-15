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

## Practical primary sources

- [VBB-BAV](https://www.vbb.de/barrierefrei-unterwegs/bav/): support for accessible
  onward travel when a lift is missing or unavailable.
- [S-Bahn lift and escalator notices](https://sbahn.berlin/fahren/bahnhofsuebersicht/barrierefrei-unterwegs/aufzugs-fahrtreppenstoerung/):
  direct operator notices.
- [BVG contact](https://www.bvg.de/de/service-und-kontakt): reporting and support.

The application links to these services. It does not scrape them at runtime or
submit reports.

## Legacy registry

`config/sources.yml` and the old source modules document the paused prototype,
not a promise of active or healthy collectors. GTFS-RT, journey probes, BVG/S-Bahn
notices and other listed sources do not feed this release's public experience.
