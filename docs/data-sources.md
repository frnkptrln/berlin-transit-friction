# Data Sources

## 1) VBB transport REST (v6.vbb.transport.rest)
- Name: v6.vbb.transport.rest
- URL: https://v6.vbb.transport.rest/
- Type: JSON REST wrapper
- Provides: stops lookup, departures, journeys, disruptions/realtime-related fields
- Update frequency: near-realtime (service-dependent)
- Limitations: wrapper reliability/rate limits can vary
- Status: implemented (basic endpoints)

## 2) VBB GTFS-Realtime
- Name: VBB GTFS-RT production feed
- URL: https://production.gtfsrt.vbb.de/data
- Type: GTFS-Realtime protobuf feed
- Provides: trip updates / vehicle positions / service alerts (if enabled in feed)
- Update frequency: realtime
- Limitations: protobuf parsing and feed content shape may vary
- Status: implemented (metadata-first), parsing planned

## 3) BVG transport REST
- Name: v6.bvg.transport.rest
- URL: https://v6.bvg.transport.rest/
- Type: JSON REST wrapper
- Provides: BVG-oriented stop/departure/disruption convenience endpoints
- Update frequency: near-realtime
- Limitations: endpoint completeness may vary
- Status: implemented (basic endpoints)

## 4) BVG traffic news
- Name: BVG traffic news page
- URL: https://www.bvg.de/en/connections/traffic-news
- Type: public website
- Provides: narrative service disruption information
- Update frequency: editorial
- Limitations: may rely on dynamic JS, terms/robots constraints
- Status: planned/unreliable (not directly ingested in MVP)

## 5) S-Bahn Berlin disruptions
- Name: S-Bahn public disruption/news sources
- URL: (to be documented per stable source)
- Type: public web/feed
- Provides: line-specific disruption notices
- Update frequency: variable
- Limitations: source stability and access policy uncertain
- Status: planned/blocked until stable source confirmed
