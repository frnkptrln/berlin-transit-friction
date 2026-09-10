from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .models import ElevatorOutageObservation, OutageSnapshot

DEFAULT_SOURCE_URL = "https://www.brokenlifts.org/"
BERLIN = ZoneInfo("Europe/Berlin")
ASSET_PATH = re.compile(
    r"^/(?:en/)?station/(?P<station_id>(?:de:\d+:)?\d+)/(?P<asset_id>\d+)$"
)
STATION_PATH = re.compile(
    r"^/(?:en/)?station/(?P<station_id>(?:de:\d+:)?\d+)(?:/\d+)?$"
)
UPDATED_AT = re.compile(
    r"Letzte\s+Aktualisierung\s+am\s+"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4}),\s*"
    r"(?P<hour>\d{2}):(?P<minute>\d{2})\s+Uhr",
    re.IGNORECASE,
)


def _parse_source_updated_at(soup: BeautifulSoup) -> datetime | None:
    for element in soup.select(".broken-update, .last-updated"):
        match = UPDATED_AT.search(element.get_text(" ", strip=True))
        if match:
            values = {key: int(value) for key, value in match.groupdict().items()}
            try:
                return datetime(
                    values["year"],
                    values["month"],
                    values["day"],
                    values["hour"],
                    values["minute"],
                    tzinfo=BERLIN,
                )
            except ValueError:
                # A malformed provider clock is an incomplete observation,
                # never a reason to lose the observation entirely.
                continue
    return None


def _parse_expected_count(soup: BeautifulSoup) -> int | None:
    counter = soup.select_one(".broken-counter, .broken-count")
    if counter is None:
        return None
    text = counter.get_text(strip=True)
    try:
        return int(text) if text.isdigit() else None
    except ValueError:
        return None


def parse_brokenlifts_snapshot(
    html: str,
    *,
    observed_at: datetime,
    source_url: str = DEFAULT_SOURCE_URL,
) -> OutageSnapshot:
    """Parse the current BrokenLifts outage list without inferring missing data.

    A snapshot is complete only when the page exposes a source timestamp, the
    expected outage count, the outage list container, and the parsed unique
    asset count matches the advertised count.
    """

    soup = BeautifulSoup(html, "html.parser")
    source_updated_at = _parse_source_updated_at(soup)
    expected_count = _parse_expected_count(soup)
    # The current source renders a station list with nested elevator lists;
    # the legacy page rendered a flat list. Read the visible, explicit broken
    # classes in either version; never infer a failure from a link alone.
    modern = soup.select_one(".station-list, .broken-count") is not None
    outage_list = soup.select_one(".station-list > ul" if modern else "#broken_list")
    warnings: list[str] = []

    if source_updated_at is None:
        warnings.append("source update timestamp missing")
    if expected_count is None:
        warnings.append("advertised outage count missing")
    if outage_list is None:
        warnings.append("outage list missing")

    parsed: dict[str, ElevatorOutageObservation] = {}
    if outage_list is not None and source_updated_at is not None:
        rows = outage_list.select(":scope > li") if modern else outage_list.select("li")
        for row in rows:
            station_link = row.select_one(
                ".station-name a" if modern else 'a[href^="/station/"]:not(.lift-link)'
            )
            if station_link is None:
                warnings.append("outage row without station link")
                continue

            station_name = station_link.get_text(" ", strip=True)
            if not station_name:
                warnings.append("outage row without station name")
                continue
            station_match = STATION_PATH.fullmatch(station_link.get("href", ""))
            if station_match is None:
                warnings.append("outage row with invalid station path")
                continue
            info = row.select_one(
                ".station-elevator-message" if modern else '[data-role="info"]'
            )
            status_text = info.get_text(" ", strip=True) if info else ""

            for asset_link in row.select(
                "a.elevator-link.elevator-broken" if modern else "a.lift-link.alert"
            ):
                match = ASSET_PATH.match(asset_link.get("href", ""))
                if match is None:
                    warnings.append("outage link with invalid asset path")
                    continue

                station_id = match.group("station_id")
                if station_id != station_match.group("station_id"):
                    warnings.append("asset station differs from its station row")
                    continue
                asset_id = match.group("asset_id")
                if asset_id in parsed:
                    warnings.append(f"duplicate asset_id {asset_id}")
                    continue

                parsed[asset_id] = ElevatorOutageObservation(
                    asset_id=asset_id,
                    station_id=station_id,
                    station_name=station_name,
                    status_text=status_text,
                    source_url=urljoin(source_url, asset_link["href"]),
                    source_updated_at=source_updated_at,
                    observed_at=observed_at,
                )

    if expected_count is not None and expected_count != len(parsed):
        warnings.append(
            f"advertised {expected_count} outages but parsed {len(parsed)} unique assets"
        )

    complete = (
        source_updated_at is not None
        and expected_count is not None
        and outage_list is not None
        and expected_count == len(parsed)
        and not warnings
    )

    return OutageSnapshot(
        advertised_count=expected_count,
        source_url=source_url,
        observed_at=observed_at,
        source_updated_at=source_updated_at,
        outages=tuple(sorted(parsed.values(), key=lambda outage: outage.asset_id)),
        complete=complete,
        warnings=tuple(warnings),
    )
