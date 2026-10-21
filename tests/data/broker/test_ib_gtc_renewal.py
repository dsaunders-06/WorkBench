"""Approved renewal amends one owned stop in place and confirms a later date."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from ib_async import OrderStatus, Stock, StopOrder, Trade

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus

REF = "245cd4e6-6339-483a-a686-e6115476bcb1"


def _trade(
    expiry: str, *, order_id: int = 88, stop_price: float = 58.0, oca_group: str = ""
) -> Trade:
    contract = Stock("BHP", "SMART", "AUD")
    contract.conId = 123
    order = StopOrder("SELL", 10, stop_price, tif="GTC")
    order.orderId = order_id
    order.permId = 999
    order.clientId = 1
    order.account = "DU_TEST"
    order.orderRef = REF
    order.ocaGroup = oca_group
    order.autoCancelDate = expiry
    return Trade(contract, order, OrderStatus(status="Submitted", remaining=10))


def _adapter(tmp_path, answers: list[list[Trade]]) -> IBAdapter:
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        ibkr_account_id="DU_TEST",
        ibkr_client_id=1,
        data_dir=str(tmp_path),
        operator_name="Alice Example",
    )
    adapter = IBAdapter(object(), EventBus(), settings=settings)
    assert adapter._pending_legs is not None
    adapter._pending_legs.begin("app-1", "BHP.AX", "stop", "DU_TEST", 123, REF, 1)
    adapter._pending_legs.observe(REF, broker_order_id=88, perm_id=999)
    adapter._all_open_orders = AsyncMock(side_effect=answers)
    adapter.positions = AsyncMock(
        return_value=[Position("BHP.AX", 10, 60, account="DU_TEST", con_id=123, qat_holding=True)]
    )
    adapter.modify_order = AsyncMock(return_value=None)
    adapter.cancel_order = AsyncMock(return_value=None)
    return adapter


@pytest.mark.asyncio
async def test_approved_gtc_renewal_amends_in_place_without_cancel(tmp_path) -> None:
    adapter = _adapter(
        tmp_path,
        [[_trade("20261231")], [_trade("20261231")], [_trade("20270331")]],
    )
    plan = await adapter.plan_gtc_renewal("BHP.AX")
    after = await adapter.apply_approved_gtc_renewal(
        plan, approved_plan_sha256=plan.digest, operator="Alice Example"
    )

    adapter.modify_order.assert_awaited_once_with("999", stop_price=58.0)
    adapter.cancel_order.assert_not_awaited()
    assert after.auto_cancel_date.isoformat() == "2027-03-31"
    journal = json.loads((tmp_path / "gtc_renewal_history.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in journal] == ["approved_intent", "confirmed"]
    assert all(row["operator"] == "Alice Example" for row in journal)


@pytest.mark.asyncio
async def test_wrong_plan_hash_refuses_before_broker_amendment(tmp_path) -> None:
    adapter = _adapter(tmp_path, [[_trade("20261231")]])
    plan = await adapter.plan_gtc_renewal("BHP.AX")
    with pytest.raises(ValueError, match="approved"):
        await adapter.apply_approved_gtc_renewal(
            plan, approved_plan_sha256="wrong", operator="Alice Example"
        )
    adapter.modify_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_unextended_auto_cancel_date_is_not_called_renewed(tmp_path) -> None:
    adapter = _adapter(
        tmp_path,
        [[_trade("20261231")], [_trade("20261231")], [_trade("20261231")]],
    )
    plan = await adapter.plan_gtc_renewal("BHP.AX")
    with pytest.raises(RuntimeError, match="did not extend"):
        await adapter.apply_approved_gtc_renewal(
            plan, approved_plan_sha256=plan.digest, operator="Alice Example"
        )
    journal = json.loads((tmp_path / "gtc_renewal_history.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in journal] == ["approved_intent"]


@pytest.mark.asyncio
async def test_legacy_order_id_zero_cannot_be_renewed_as_ours(tmp_path) -> None:
    adapter = _adapter(tmp_path, [[_trade("20261231", order_id=0)]])
    with pytest.raises(ValueError, match="unowned"):
        await adapter.plan_gtc_renewal("BHP.AX")


@pytest.mark.asyncio
async def test_changed_stop_price_refuses_before_amendment(tmp_path) -> None:
    adapter = _adapter(tmp_path, [[_trade("20261231")], [_trade("20261231", stop_price=57)]])
    plan = await adapter.plan_gtc_renewal("BHP.AX")
    with pytest.raises(ValueError, match="changed"):
        await adapter.apply_approved_gtc_renewal(
            plan, approved_plan_sha256=plan.digest, operator="Alice Example"
        )
    adapter.modify_order.assert_not_awaited()
    adapter.cancel_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_oca_group_refuses_before_amendment(tmp_path) -> None:
    adapter = _adapter(
        tmp_path,
        [[_trade("20261231", oca_group="pair-a")], [_trade("20261231", oca_group="pair-b")]],
    )
    plan = await adapter.plan_gtc_renewal("BHP.AX")
    with pytest.raises(ValueError, match="changed"):
        await adapter.apply_approved_gtc_renewal(
            plan, approved_plan_sha256=plan.digest, operator="Alice Example"
        )
    adapter.modify_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_intent_save_refuses_before_amendment(tmp_path, monkeypatch) -> None:
    adapter = _adapter(tmp_path, [[_trade("20261231")], [_trade("20261231")]])
    plan = await adapter.plan_gtc_renewal("BHP.AX")
    assert adapter._gtc_renewal_journal is not None

    def fail_save(record):
        raise OSError("disk refused")

    monkeypatch.setattr(adapter._gtc_renewal_journal, "append", fail_save)
    with pytest.raises(OSError, match="disk refused"):
        await adapter.apply_approved_gtc_renewal(
            plan, approved_plan_sha256=plan.digest, operator="Alice Example"
        )
    adapter.modify_order.assert_not_awaited()
    adapter.cancel_order.assert_not_awaited()
