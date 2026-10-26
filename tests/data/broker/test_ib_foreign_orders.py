"""Foreign/TWS orders cannot become QAT protection or permit another buy."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from ib_async import OrderStatus, Stock, StopOrder, Trade

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter
from qat.data.broker.ib_translate import from_ib_open_order
from qat.domain.bus import EventBus


def _adapter(tmp_path) -> IBAdapter:
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        ibkr_account_id="DU_TEST",
        ibkr_client_id=1,
        data_dir=str(tmp_path),
        operator_name="Alice",
    )
    return IBAdapter(object(), EventBus(), settings=settings)


def _stop(
    *, order_id: int = 88, client_id: int = 1, order_ref: str = "", auto_cancel_date: str = ""
) -> Trade:
    contract = Stock("BHP", "SMART", "AUD")
    contract.conId = 123
    order = StopOrder("SELL", 10, 58.0, tif="GTC")
    order.orderId = order_id
    order.permId = 999
    order.clientId = client_id
    order.account = "DU_TEST"
    order.orderRef = order_ref
    order.autoCancelDate = auto_cancel_date
    return Trade(contract, order, OrderStatus(status="Submitted", remaining=10))


def test_watchdog_requires_permid_and_orderref_to_match_durable_leg(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    ref = "245cd4e6-6339-483a-a686-e6115476bcb1"
    assert adapter._pending_legs is not None
    adapter._pending_legs.begin("entry-1", "BHP.AX", "stop", "DU_TEST", 123, ref, 1)
    adapter._pending_legs.observe(ref, broker_order_id=88, perm_id=999)
    order = from_ib_open_order(_stop(order_ref=ref))
    assert adapter.owns_resting_order(order)
    assert not adapter.owns_resting_order(replace(order, perm_id=0))
    assert not adapter.owns_resting_order(replace(order, order_ref=""))
    assert not adapter.owns_resting_order(replace(order, broker_order_id=0))


def test_qat_stop_handoff_records_placement_time_without_broker_expiry(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    ref = "395cd4e6-6339-483a-a686-e6115476bcb1"
    assert adapter._pending_legs is not None
    adapter._pending_legs.begin("entry-2", "BHP.AX", "stop", "DU_TEST", 123, ref, 1)
    trade = _stop(order_ref=ref)
    adapter._observe_leg(ref, trade.order, trade)
    saved = json.loads((tmp_path / "gtc_expiry.json").read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Australia/Sydney")).date().isoformat()
    assert saved["placements"][ref].startswith(today)


@pytest.mark.asyncio
@pytest.mark.parametrize("order_id,client_id", [(0, 1), (88, 0), (88, 7)])
async def test_unowned_order_blocks_buys_and_is_not_counted_as_qat_stop(
    tmp_path, order_id: int, client_id: int
) -> None:
    adapter = _adapter(tmp_path)
    adapter._all_open_orders = AsyncMock(
        return_value=[_stop(order_id=order_id, client_id=client_id)]
    )

    assert "unowned" in (await adapter.foreign_order_reason("BHP.AX") or "")
    assert await adapter.resting_stop_orders() == {}


@pytest.mark.asyncio
async def test_durably_proven_qat_stop_remains_visible_as_protection(tmp_path, caplog) -> None:
    adapter = _adapter(tmp_path)
    ref = "245cd4e6-6339-483a-a686-e6115476bcb1"
    assert adapter._pending_legs is not None
    adapter._pending_legs.begin("app-1", "BHP.AX", "stop", "DU_TEST", 123, ref, 1)
    adapter._pending_legs.observe(ref, broker_order_id=88, perm_id=999)
    expiry = (datetime.now(ZoneInfo("Australia/Sydney")) + timedelta(days=15)).date()
    adapter._all_open_orders = AsyncMock(
        return_value=[_stop(order_ref=ref, auto_cancel_date=expiry.strftime("%Y%m%d"))]
    )

    assert await adapter.foreign_order_reason("BHP.AX") is None
    with caplog.at_level(logging.CRITICAL):
        assert (await adapter.resting_stop_orders())["BHP.AX"].order_id == "999"
    saved = json.loads((tmp_path / "gtc_expiry.json").read_text(encoding="utf-8"))
    assert saved["stops"]["999"]["auto_cancel_date"] is None
    assert "OPERATOR ACTION REQUIRED" in caplog.text


@pytest.mark.asyncio
async def test_unreadable_open_order_source_blocks_exposure(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter._all_open_orders = AsyncMock(return_value=None)

    with pytest.raises(RuntimeError, match="open-order"):
        await adapter.foreign_order_reason("BHP.AX")
    with pytest.raises(RuntimeError, match="protective"):
        await adapter.resting_stop_orders()


@pytest.mark.asyncio
async def test_foreign_quarantine_survives_restart_until_ds_clearance(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter._all_open_orders = AsyncMock(return_value=[_stop(client_id=7)])
    assert "unowned" in (await adapter.foreign_order_reason("BHP.AX") or "")

    restarted = _adapter(tmp_path)
    restarted._all_open_orders = AsyncMock(return_value=[])
    assert "clearance" in (await restarted.foreign_order_reason("BHP.AX") or "")
    assert await restarted.clear_foreign_order_quarantine(
        "BHP.AX", operator="Alice", ds_approval_ref="DS approval TEST-1"
    )
    assert await restarted.foreign_order_reason("BHP.AX") is None
    saved = json.loads((tmp_path / "foreign_order_quarantine.json").read_text(encoding="utf-8"))
    assert saved["active"] == {}
    assert saved["clearances"][0]["operator"] == "Alice"
    assert saved["clearances"][0]["ds_approval_ref"] == "DS approval TEST-1"


@pytest.mark.asyncio
async def test_foreign_quarantine_cannot_be_cleared_while_order_works(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter._all_open_orders = AsyncMock(return_value=[_stop(client_id=7)])
    await adapter.foreign_order_reason("BHP.AX")
    with pytest.raises(ValueError, match="still working"):
        await adapter.clear_foreign_order_quarantine(
            "BHP.AX", operator="Alice", ds_approval_ref="DS approval TEST-2"
        )
    with pytest.raises(ValueError, match="configured operator"):
        await adapter.clear_foreign_order_quarantine(
            "BHP.AX", operator="generic", ds_approval_ref="DS approval TEST-2"
        )


@pytest.mark.asyncio
async def test_foreign_stop_scan_persists_quarantine_even_without_a_buy(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    adapter._all_open_orders = AsyncMock(return_value=[_stop(client_id=7)])
    assert await adapter.resting_stop_orders() == {}

    restarted = _adapter(tmp_path)
    restarted._all_open_orders = AsyncMock(return_value=[])
    assert "clearance" in (await restarted.foreign_order_reason("BHP.AX") or "")
