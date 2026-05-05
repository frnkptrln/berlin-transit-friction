# Data Sources

See `config/sources.yml` for machine-readable registry.

- vbb_gtfs_rt: partial, frequent, compact metadata json.gz, silver events partial, limitation: protobuf parsing optional.
- vbb_transport_rest: partial, frequent, compact json.gz, silver events from remarks/delay/cancel hints.
- bvg_transport_rest: partial, frequent, compact json.gz, silver events from remarks.
- brokenlifts: partial, frequent, compact snapshot json.gz, accessibility events.
- bvg_traffic_news: blocked/planned; stable parser not yet confirmed.
- sbahn_disruptions: planned.
- bvg_disturbed_network_wfs: planned.
- vbb_gtfs_static: planned metadata/index collection.
- viz_public_transport: planned.
