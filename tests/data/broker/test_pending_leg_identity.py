"""Durable per-leg identity before a Gateway hand-off."""

from __future__ import annotations

from uuid import UUID

from qat.data.broker.pending_legs import PendingLegStore, leg_order_ref


def test_each_leg_has_a_stable_distinct_uuid_reference() -> None:
    app_id = "e17bb4c8-b3d8-4d4a-a5bb-5bd2fb0d80ce"
    refs = {role: leg_order_ref(app_id, role) for role in ("primary", "stop", "target", "exit")}
    assert len(set(refs.values())) == 4
    assert refs["primary"] == app_id
    assert all(str(UUID(ref)) == ref for ref in refs.values())
    assert refs == {role: leg_order_ref(app_id, role) for role in refs}


def test_primary_preserves_the_oms_hex_uuid_and_store_accepts_it(tmp_path) -> None:
    app_id = "e17bb4c8b3d84d4aa5bb5bd2fb0d80ce"
    assert leg_order_ref(app_id, "primary") == app_id
    store = PendingLegStore(tmp_path / "pending_legs.json")
    store.begin(app_id, "BHP.AX", "primary", "DU123", 4036812, app_id, 7)
    assert PendingLegStore(store.path).unresolved("BHP.AX") == (app_id,)


def test_pending_leg_survives_restart_and_cannot_be_resubmitted(tmp_path) -> None:
    path = tmp_path / "pending_legs.json"
    store = PendingLegStore(path)
    ref = leg_order_ref("card-id", "entry")
    store.begin(
        app_order_id="card-id",
        symbol="BHP.AX",
        role="entry",
        account="DU123",
        con_id=4036812,
        order_ref=ref,
        client_id=7,
    )
    recovered = PendingLegStore(path)
    assert recovered.unresolved("BHP.AX") == (ref,)
    try:
        recovered.begin(
            app_order_id="card-id",
            symbol="BHP.AX",
            role="entry",
            account="DU123",
            con_id=4036812,
            order_ref=ref,
            client_id=7,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate transmission intent was allowed")

    recovered.observe(ref, broker_order_id=81, perm_id=0)
    assert PendingLegStore(path).unresolved("BHP.AX") == (ref,)
    recovered.observe(ref, broker_order_id=81, perm_id=991)
    assert PendingLegStore(path).unresolved("BHP.AX") == ()
    assert recovered.application_id_for(ref) == "card-id"


def test_missing_reference_cannot_resolve_an_unrelated_pending_leg(tmp_path) -> None:
    store = PendingLegStore(tmp_path / "pending_legs.json")
    ref = leg_order_ref("stop-id", "stop")
    store.begin("stop-id", "BHP.AX", "stop", "DU123", 4036812, ref, 7)
    assert not store.resolve_match("", "DU123", 4036812, 7, perm_id=991)
    assert not store.resolve_match(ref, "DU123", 55555, 7, perm_id=991)
    assert store.unresolved("BHP.AX") == (ref,)
    assert store.resolve_match(ref, "DU123", 4036812, 7, perm_id=991)
    assert store.unresolved("BHP.AX") == ()
