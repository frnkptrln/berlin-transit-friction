"""Paths and shared constants.

``BASE_DIR`` is where the code and its checked-in configuration live.
``OUTPUT_ROOT`` is where a run writes. They are the same in normal operation and
deliberately separable, so a test or a dry run can direct output somewhere
harmless instead of into the working tree. Without that split, running the test
suite writes real artefacts into ``data/`` and ``site/`` — which is how this
repository accumulated output nobody asked for.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

#: Override with ``TRANSIT_FRICTION_OUTPUT_ROOT`` to redirect every write.
OUTPUT_ROOT = Path(os.environ.get("TRANSIT_FRICTION_OUTPUT_ROOT") or BASE_DIR)

DATA_DIR = OUTPUT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
SUMMARIES_DIR = DATA_DIR / "summaries"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
MANIFESTS_DIR = DATA_DIR / "manifests"
SITE_DATA_DIR = OUTPUT_ROOT / "site" / "data"
STATE_DIR = DATA_DIR / "state"

#: The events layer writes here; see docs/partitioning.md.
EVENTS_DIR = DATA_DIR / "events"
AGGREGATES_DIR = DATA_DIR / "aggregates"
EVENT_MANIFESTS_DIR = DATA_DIR / "_manifests"

#: Ephemeral raw layer: 7 days, gitignored, never committed. See RETENTION.md.
RAW_LAYER_DIR = OUTPUT_ROOT / ".raw"

DEFAULT_TIMEOUT = 20
USER_AGENT = "transit-friction/0.2"
