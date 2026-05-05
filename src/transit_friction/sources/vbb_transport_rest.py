from __future__ import annotations
import logging
import requests
from transit_friction.config import DEFAULT_TIMEOUT, USER_AGENT

BASE = "https://v6.vbb.transport.rest"
HEADERS = {"User-Agent": USER_AGENT}
log = logging.getLogger(__name__)


def _get(path: str, params: dict | None = None):
    try:
        r = requests.get(f"{BASE}{path}", params=params or {}, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("vbb transport rest failed for %s: %s", path, e)
        return None


def fetch_disruptions():
    return _get("/trips", params={"from": "900000003201", "to": "900000003201", "results": 1})


def fetch_departures_for_stop(stop_id, duration_minutes=60):
    return _get(f"/stops/{stop_id}/departures", params={"duration": duration_minutes})


def fetch_stop(query):
    return _get("/locations", params={"query": query, "results": 5})
