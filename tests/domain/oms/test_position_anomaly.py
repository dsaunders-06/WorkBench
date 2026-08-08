"""The concept M39 and M43 share: a held position in a state the ordinary path
must not treat as ordinary.

The test that matters most here is the immunity one. An explanation that is not
bound to the quantity it was declared against grants a symbol permanent
immunity, and the next genuine divergence passes in silence - which is exactly
the failure `adopt_broker_positions` already warns about, where an operator is
trained to ignore the one signal meaning "my view of the account cannot be
trusted".
"""

from __future__ import annotations

from qat.domain.oms.anomaly import PositionAnomalyStore


def test_nothing_is_quarantined_by_default() -> None:
    store = PositionAnomalyStore()

    assert store.active() == []
    assert store.is_quarantined("CRWD") is False
    assert store.get("CRWD") is None


def test_a_declared_anomaly_quarantines_its_symbol() -> None:
    store = PositionAnomalyStore()

    anomaly = store.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert anomaly.symbol == "CRWD"
    assert anomaly.declared_at.tzinfo is not None
    assert store.is_quarantined("CRWD") is True
    assert store.is_quarantined("AMD") is False
    assert [a.symbol for a in store.active()] == ["CRWD"]


def test_it_explains_the_quantity_it_was_declared_against() -> None:
    store = PositionAnomalyStore()
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert store.explains("CRWD", 64.0) is True


def test_it_does_not_explain_a_later_different_quantity() -> None:
    """The immunity test, and the reason `explains` takes a quantity at all.

    Declaring 16-to-64 explained must not also explain a later 64-to-128. If it
    did, one declaration would silence that symbol forever and the second event
    - which nobody has looked at - would pass as accounted for.
    """
    store = PositionAnomalyStore()
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert store.explains("CRWD", 128.0) is False
    # Still quarantined, though - the position is no less suspect for having
    # moved again. Quarantine and explanation are separate questions.
    assert store.is_quarantined("CRWD") is True


def test_it_explains_nothing_for_an_undeclared_symbol() -> None:
    store = PositionAnomalyStore()

    assert store.explains("AMD", 14.0) is False


def test_clearing_releases_the_symbol() -> None:
    store = PositionAnomalyStore()
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert store.clear("CRWD", operator="operator") is True
    assert store.is_quarantined("CRWD") is False
    assert store.explains("CRWD", 64.0) is False
    assert store.clear("CRWD", operator="operator") is False


def test_it_survives_a_restart(tmp_path) -> None:
    """The whole point. An in-memory-only anomaly is erased by the restart that
    follows every overnight session, and the position goes back to looking
    ordinary while its records are still wrong."""
    store = PositionAnomalyStore(tmp_path)
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    reloaded = PositionAnomalyStore(tmp_path)

    assert reloaded.is_quarantined("CRWD") is True
    assert reloaded.explains("CRWD", 64.0) is True
    restored = reloaded.get("CRWD")
    assert restored is not None
    assert restored.reason == "4-for-1 split, ex 2 July"
    assert restored.declared_by == "operator"
    assert restored.tracked_quantity == 16.0


def test_clearing_survives_a_restart_too(tmp_path) -> None:
    """A cleared anomaly that comes back on the next launch would re-quarantine
    a position the operator has already dealt with."""
    store = PositionAnomalyStore(tmp_path)
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )
    store.clear("CRWD", operator="operator")

    assert PositionAnomalyStore(tmp_path).is_quarantined("CRWD") is False


def test_an_unreadable_file_does_not_stop_startup(tmp_path) -> None:
    """Degrading to "nothing is quarantined" is the wrong direction on its own,
    so it is loud. It is still better than refusing to launch: an app that will
    not start protects nothing at all."""
    (tmp_path / "position_anomalies.json").write_text("{not json", encoding="utf-8")

    store = PositionAnomalyStore(tmp_path)

    assert store.active() == []
