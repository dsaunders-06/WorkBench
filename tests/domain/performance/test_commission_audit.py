"""IBKR's own commission against the model the ledger records (M175)."""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerCommission
from qat.data.broker.mock_broker import MockBroker
from qat.domain.performance.commission_audit import (
    COMMISSION_CHECKS_FILENAME,
    CommissionAuditor,
)

_WHEN = datetime(2026, 9, 11, 0, 3, 22, tzinfo=UTC)


def _report(**overrides) -> BrokerCommission:
    fields = {
        "order_id": "750830217",
        "symbol": "BHP.AX",
        "side": "sell",
        "quantity": 793.0,
        "notional": 793 * 60.40,
        "commission": 42.149536,
        "currency": "AUD",
    }
    fields.update(overrides)
    return BrokerCommission(**fields)  # type: ignore[arg-type]


def _auditor(tmp_path) -> CommissionAuditor:
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")
    return CommissionAuditor(tmp_path, settings=settings, clock=lambda: _WHEN)


def _rows(tmp_path) -> list[dict[str, str]]:
    with (tmp_path / COMMISSION_CHECKS_FILENAME).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_a_matching_commission_is_verified_and_recorded(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    check = _auditor(tmp_path).check(_report())

    assert check.agrees
    assert check.modelled == pytest.approx(42.15, abs=0.01)
    [row] = _rows(tmp_path)
    assert row["order_id"] == "750830217"
    assert row["agrees"] == "True"
    assert "COMMISSION VERIFIED" in caplog.text


def test_a_different_commission_is_a_warning(tmp_path, caplog):
    check = _auditor(tmp_path).check(_report(commission=50.00))

    assert not check.agrees
    assert any(
        r.levelno == logging.WARNING and "COMMISSION DISAGREES" in r.getMessage()
        for r in caplog.records
    )


def test_a_currency_other_than_the_markets_disagrees(tmp_path):
    assert not _auditor(tmp_path).check(_report(currency="USD")).agrees


def test_checks_append_under_one_header(tmp_path):
    auditor = _auditor(tmp_path)
    auditor.check(_report())
    auditor.check(_report(order_id="750830242", symbol="SEK.AX"))

    assert [r["symbol"] for r in _rows(tmp_path)] == ["BHP.AX", "SEK.AX"]


def test_an_unwritable_file_is_logged_never_raised(tmp_path, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")

    check = CommissionAuditor(blocker, settings=settings, clock=lambda: _WHEN).check(_report())

    assert check.agrees
    assert "Could not record" in caplog.text


def test_the_runtime_hands_the_auditor_to_a_broker_that_reports_commissions(tmp_path):
    """Wiring, not mechanism - this project's recurring failure is machinery
    built and never reached."""
    from qat.presentation.runtime import Runtime

    class _ListeningBroker(MockBroker):
        def __init__(self) -> None:
            super().__init__(seed=1)
            self.listener = None

        def set_commission_listener(self, listener) -> None:
            self.listener = listener

    broker = _ListeningBroker()
    Runtime.build_demo(
        settings=Settings(_env_file=None, data_dir=str(tmp_path), market="ASX"),
        broker=broker,  # type: ignore[arg-type]
    )

    assert broker.listener is not None
    assert type(broker.listener.__self__).__name__ == "CommissionAuditor"  # type: ignore[attr-defined]
