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

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

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


def test_redeclaring_preserves_the_original_declared_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I5, final review. With cancelling off (the default) the scan re-declares
    an unresolved symbol on every poll - dozens of times across a trading day.
    `declared_at` must survive that, so the file can still say when the
    orphans were FIRST seen rather than when they were last re-detected.
    `excess` and `reason` are NOT preserved - those genuinely change."""
    import qat.domain.oms.resting_order_anomaly as mod

    first_seen = datetime(2026, 8, 24, 10, 0, 0, tzinfo=UTC)
    later = datetime(2026, 8, 24, 15, 30, 0, tzinfo=UTC)
    stamps = iter([first_seen, later])

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001 - mirrors datetime.now's signature
            return next(stamps)

    monkeypatch.setattr(mod, "datetime", _FixedDateTime)

    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(symbol="TNE.AX", reason="a", declared_by="d", excess=1.0)
    store.declare(symbol="TNE.AX", reason="b", declared_by="d", excess=2.0)

    anomaly = store.get("TNE.AX")
    assert anomaly is not None
    assert anomaly.declared_at == first_seen
    assert anomaly.excess == 2.0
    assert anomaly.reason == "b"


def test_an_unreadable_file_quarantines_nothing_and_does_not_raise(tmp_path: Path) -> None:
    (tmp_path / "resting_order_anomalies.json").write_text("{not json", encoding="utf-8")
    assert RestingOrderAnomalyStore(tmp_path).active() == []


def test_no_data_dir_is_tolerated(tmp_path: Path) -> None:
    store = RestingOrderAnomalyStore(None)
    store.declare(symbol="TNE.AX", reason="r", declared_by="d", excess=1.0)
    assert store.is_quarantined("TNE.AX")


def test_a_write_failure_does_not_abort_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`declare` is called in a loop over every divergent symbol. An OSError
    escaping the first one would abandon the rest of the scan, so a failed
    write degrades to an in-memory quarantine and a logged error."""
    store = RestingOrderAnomalyStore(tmp_path)

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _boom)
    with caplog.at_level(logging.ERROR):
        store.declare(symbol="TNE.AX", reason="r", declared_by="d", excess=1.0)
    assert store.is_quarantined("TNE.AX")
    assert "Could not write" in caplog.text
