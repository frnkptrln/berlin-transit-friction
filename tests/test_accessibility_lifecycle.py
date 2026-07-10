from datetime import datetime, timedelta, timezone

from transit_friction.accessibility.lifecycle import load_state, reconcile, save_state
from transit_friction.accessibility.models import (
    ElevatorOutageObservation,
    OutageSnapshot,
)


T0 = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)


def observation(asset_id: str, observed_at: datetime, source_updated_at=None):
    return ElevatorOutageObservation(
        asset_id=asset_id,
        station_id=f"station-{asset_id}",
        station_name=f"Station {asset_id}",
        status_text="Außer Betrieb",
        source_url=f"https://www.brokenlifts.org/station/x/{asset_id}",
        source_updated_at=source_updated_at or observed_at,
        observed_at=observed_at,
    )


def snapshot(*assets: str, at: datetime, complete: bool = True, source_at=None):
    source_at = source_at or at
    return OutageSnapshot(
        source_url="https://www.brokenlifts.org/",
        observed_at=at,
        source_updated_at=source_at,
        outages=tuple(observation(asset, at, source_at) for asset in assets),
        complete=complete,
    )


def test_repeated_observation_keeps_identity_and_first_seen():
    first = reconcile({}, snapshot("1", at=T0))
    second = reconcile(first.active, snapshot("1", at=T0 + timedelta(minutes=15)))

    assert len(first.new) == 1
    assert len(second.ongoing) == 1
    assert second.ongoing[0].outage_id == first.new[0].outage_id
    assert second.ongoing[0].first_seen_at == T0
    assert second.ongoing[0].last_seen_at == T0 + timedelta(minutes=15)


def test_complete_newer_snapshot_resolves_missing_asset():
    first = reconcile({}, snapshot("1", "2", at=T0))
    result = reconcile(first.active, snapshot("1", at=T0 + timedelta(minutes=15)))

    assert result.resolution_allowed is True
    assert set(result.active) == {"1"}
    assert [outage.asset_id for outage in result.resolved] == ["2"]
    assert result.resolved[0].resolved_at == T0 + timedelta(minutes=15)


def test_incomplete_snapshot_never_resolves_missing_asset():
    first = reconcile({}, snapshot("1", "2", at=T0))
    incomplete = snapshot(
        "1",
        at=T0 + timedelta(minutes=15),
        complete=False,
    )
    result = reconcile(first.active, incomplete)

    assert result.resolution_allowed is False
    assert set(result.active) == {"1", "2"}
    assert result.resolved == ()


def test_stale_complete_snapshot_never_resolves_newer_state():
    first = reconcile({}, snapshot("1", at=T0))
    stale = snapshot(
        at=T0 + timedelta(minutes=15),
        source_at=T0 - timedelta(minutes=15),
    )
    result = reconcile(first.active, stale)

    assert result.resolution_allowed is False
    assert set(result.active) == {"1"}


def test_state_round_trip_survives_new_process(tmp_path):
    first = reconcile({}, snapshot("1", at=T0))
    state_path = tmp_path / "accessibility-state.json"

    save_state(state_path, first.active)
    restored = load_state(state_path)

    assert restored == first.active
