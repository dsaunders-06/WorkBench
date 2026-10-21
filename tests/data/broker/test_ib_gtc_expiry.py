"""A protective GTC stop carries IBKR's actual auto-cancel date."""

from __future__ import annotations

import json
from datetime import date

import pytest
from ib_async import OrderStatus, Stock, StopOrder, Trade

from qat.data.broker.adapter import RestingStopOrder
from qat.data.broker.gtc_expiry import GtcExpiryStore
from qat.data.broker.ib_translate import from_ib_resting_stop


def _trade(auto_cancel_date: str) -> Trade:
    contract = Stock("BHP", "SMART", "AUD")
    order = StopOrder("SELL", 10, 58.0, tif="GTC")
    order.permId = 999
    order.autoCancelDate = auto_cancel_date
    return Trade(contract, order, OrderStatus(status="Submitted", remaining=10))


@pytest.mark.parametrize("raw", ["20261231", "2026-12-31", "20261231 23:59:59"])
def test_gtc_auto_cancel_date_is_preserved(raw: str) -> None:
    stop = from_ib_resting_stop(_trade(raw))
    assert stop is not None
    assert stop.auto_cancel_date == date(2026, 12, 31)


def test_missing_auto_cancel_date_is_explicitly_unknown() -> None:
    stop = from_ib_resting_stop(_trade(""))
    assert stop is not None
    assert stop.auto_cancel_date is None


def test_invalid_auto_cancel_date_refuses_to_guess() -> None:
    with pytest.raises(ValueError, match="auto-cancel"):
        from_ib_resting_stop(_trade("not a date"))


def test_every_duplicate_protective_stop_keeps_its_own_expiry(tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    store.record(
        [
            RestingStopOrder("BHP.AX", "999", 58.0, 10, auto_cancel_date=date(2026, 12, 31)),
            RestingStopOrder("BHP.AX", "1000", 58.0, 10, auto_cancel_date=date(2027, 3, 31)),
        ]
    )
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(saved["stops"]) == {"999", "1000"}
