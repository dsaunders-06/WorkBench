"""Quarantine that cannot lie about positions (M141, item 23).

`PositionAnomalyStore.declare` binds an anomaly to `broker_quantity`, and
`explains()` then returns True for any position divergence at that quantity -
which `check_reconciliation` uses to SUPPRESS the kill-switch trip.

Quarantining a flat symbol through it would therefore grant that symbol immunity
from the position-reconciliation halt at broker=0: the exact rail that caught the
real mismatch on 24 August. Item 23's fix would have partly disabled item 27's.

So this store has no `explains` at all, and the test below is what keeps it that
way.
"""

from __future__ import annotations

from pathlib import Path

from qat.domain.oms.resting_order_anomaly import RestingOrderAnomalyStore


def test_it_cannot_explain_a_position_divergence() -> None:
    """THE test. Structural, not behavioural - there is no method to call."""
    assert not hasattr(RestingOrderAnomalyStore, "explains")


def test_declare_then_quarantined(tmp_path: Path) -> None:
    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(
        symbol="TNE.AX",
        reason="8 legs resting on a flat book",
        declared_by="order-reconciler",
        excess=12304.0,
    )
    assert store.is_quarantined("TNE.AX")
    anomaly = store.get("TNE.AX")
    assert anomaly is not None
    assert anomaly.excess == 12304.0


def test_it_survives_a_restart(tmp_path: Path) -> None:
    RestingOrderAnomalyStore(tmp_path).declare(
        symbol="TNE.AX", reason="orphaned legs", declared_by="order-reconciler", excess=1.0
    )
    assert RestingOrderAnomalyStore(tmp_path).is_quarantined("TNE.AX")


def test_clear_releases_and_reports_whether_it_did(tmp_path: Path) -> None:
    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(symbol="TNE.AX", reason="r", declared_by="d", excess=1.0)
    assert store.clear("TNE.AX", "operator") is True
    assert store.clear("TNE.AX", "operator") is False
    assert not store.is_quarantined("TNE.AX")


def test_redeclaring_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(symbol="TNE.AX", reason="a", declared_by="d", excess=1.0)
    store.declare(symbol="TNE.AX", reason="b", declared_by="d", excess=2.0)
    assert len(store.active()) == 1
    anomaly = store.get("TNE.AX")
    assert anomaly is not None
    assert anomaly.excess == 2.0


def test_an_unreadable_file_quarantines_nothing_and_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "resting_order_anomalies.json").write_text("{not json", encoding="utf-8")
    assert RestingOrderAnomalyStore(tmp_path).active() == []


def test_no_data_dir_is_tolerated(tmp_path: Path) -> None:
    store = RestingOrderAnomalyStore(None)
    store.declare(symbol="TNE.AX", reason="r", declared_by="d", excess=1.0)
    assert store.is_quarantined("TNE.AX")
