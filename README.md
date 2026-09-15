# Transit Friction · Berlin

**Ein Aufzug fehlt. Ein Weg verschwindet.**

Transit Friction makes barriers in public transport understandable and explorable,
so their consequences can inform improvements. The first usable experience focuses
on one bounded question: **what changes when a step-free journey loses a lift?**

The German static site now combines:

- an interactive, explicitly fictional journey network: stairs possible vs a
  continuous step-free route; failed, working or unknown lift; an accessible
  detour; and an independent second lift;
- a **dated, reviewed BrokenLifts source snapshot**, with station search, a
  Berlin-only filter and individual source links; it is never labelled live;
- an outage-duration view that retains missing data and uncertainty instead of
  inventing a time series;
- practical links to BVG, S-Bahn and VBB-BAV, plus explanations of which
  interventions the model can and cannot evaluate.

The route model has no real station topology, travel times or passenger data.
Its costs count **path sections, not minutes**. The source snapshot does not say
that a whole station is inaccessible. Delays, headways and crowding remain separate
questions requiring separate evidence.

## Open and run

No frontend package installation or build is needed:

```bash
python -m http.server 8765 --directory site
```

Open `http://localhost:8765`. The application works on GitHub Pages under the
repository subpath. All scripts, styles and data are local; no third-party script,
map tile, cookie, analytics or runtime source request is used. The source snapshot
is loaded from the site's own data directory. A missing or malformed snapshot
leaves the explanatory model usable and displays an explicit unavailable state.

## Development and checks

Python 3.12+ and Node.js 22+:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
node --test tests/test_journey_model.cjs
python scripts/check_site.py
python scripts/check_retention.py
```

CI runs the Python suite, all route/data-contract tests, static page/asset/anchor
checks and the retention contract. Pages validates the static surface before
uploading it. Automated collection remains disabled.

## Source snapshot and evidence

The bundled observation has source time **10 September 2026, 19:57 Europe/Berlin**;
it was captured at **20:05:56 Europe/Berlin**. All 35 explicit broken-lift links
match 35 unique parsed asset IDs at 25 stations across Berlin-Brandenburg.
The Berlin DHID prefix `de:11000:` identifies 28 of those lifts at 20 stations.
These are counts **in one source statement**, not a network outage rate.

The [snapshot review](docs/snapshot-review-2026-09-10.md) records the checks,
payload fingerprint, observations and remaining gates. The site automatically
marks the snapshot as old when its source timestamp is over one hour old; it
never refreshes the source behind the reader's back.

The publication helper works only on an already captured page and requires a
capture timestamp plus a concrete review note. It rejects incomplete, stale-at-
capture or future-dated observations and writes atomically. Its default output
is private shadow data:

```bash
python scripts/build_accessibility_snapshot.py \
  --input-html .shadow/raw/captures/brokenlifts.html \
  --observed-at '2026-09-10T18:05:56.605304+00:00' \
  --source-url https://brokenlifts.org/ \
  --review-note 'State the checks performed on this exact capture'
```

Use the **actual** capture timestamp and a review of that capture, not the example
timestamp or a copied review statement. Only an explicitly reviewed projection
belongs at `site/data/accessibility-snapshot.json`; raw captures remain ignored.
See [RETENTION.md](RETENTION.md) for storage and expiry.

## Observation pipeline

The unscheduled rehearsal is usable independently of the explanatory site:

```bash
python scripts/accessibility_shadow.py --root .shadow
python scripts/seal_events.py --events-root .shadow/events \
  --manifest-root .shadow/_manifests --raw-root .shadow/raw
python scripts/build_aggregates.py --events-root .shadow/events \
  --raw-root .shadow/raw --aggregates-root .shadow/aggregates \
  --site-root .shadow/site
```

A current unchanged source is a successful observation, but cannot resolve an
outage. Fetch/parse failures remain observations. State is rebuilt from the full
ledger, so outages older than 30 days retain their identity. Missing observations
produce withheld null values, including on a rebuild with no data. Historical
station-hours are interval unions per station; lift-hours are a separate quantity.

Manual workflow `accessibility shadow observation` restores an **evictable** cache,
observes once, seals closed days, builds private aggregates and uploads a review
artifact. Cache retention is sufficient for a rehearsal, **not durable historical
collection**. Before scheduling, choose durable state storage and exercise recovery.

## Legacy and publication boundaries

The previous mixed “friction” prototype was stopped on 10 July 2026. It counted
repeated polls as new events, mixed source failures with transport conditions and
lacked a valid denominator. Its counters, rankings and trends are not transit
quality evidence. The exact historical state is preserved in
[`legacy-v0`](https://github.com/frnkptrln/berlin-transit-friction/tree/legacy-v0).
Unused legacy scripts and misleading JSON are removed from the served `site/`
surface; legacy collectors remain disabled.

The **static explanatory experience and reviewed dated source statement** can be
published now. They neither resume collection nor imply an outage-duration study.
Scheduled collection and public time series still require:

1. fixture-backed source parsing and stable event identity;
2. durable state across independent runners and tested recovery;
3. failed, incomplete, repeated or stale sources never resolving outages;
4. defined units, uncertainty and explicit source coverage;
5. a reviewed observation period including advancing source versions, openings,
   closures, missing responses and recovery;
6. storage and sealing that conform to the accepted retention contract;
7. a separately validated roster/topology before network rates or reachability
   claims. The new paginated BrokenLifts station list is a lead, not that validation.

## Documentation

- [Experience and model contract](docs/experience.md)
- [Accessibility reboot and source contract](docs/accessibility-reboot.md)
- [Methodology](docs/methodology.md) · [Sources](docs/data-sources.md)
- [Data architecture](docs/data-architecture.md) · [Event schema](docs/event-schema.md)
- [Partitioning](docs/partitioning.md) · [Denominator](docs/denominator.md)
- [Legacy assessment](docs/legacy-assessment.md)
- [Storage decision](docs/decisions/0001-timeseries-hosting.md)

Public data only. No passenger tracking, fabricated geolocation or unsupported precision.
