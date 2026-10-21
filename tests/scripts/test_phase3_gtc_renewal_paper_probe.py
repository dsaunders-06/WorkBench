"""Offline safety checks for the date-gated GTC paper probe."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import phase3_gtc_renewal_paper_probe as probe  # noqa: E402

from qat.data.broker.gtc_expiry import GtcRenewalPlan  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
FAKE_ACCOUNT = "DUTEST"


def test_session_gate_allows_only_thursday_after_1030_aedt() -> None:
    probe._session_window(date(2026, 10, 22), now=datetime(2026, 10, 22, 10, 30, tzinfo=SYDNEY))
    for session, clock in (
        (date(2026, 10, 21), datetime(2026, 10, 22, 10, 30, tzinfo=SYDNEY)),
        (date(2026, 10, 22), datetime(2026, 10, 21, 10, 30, tzinfo=SYDNEY)),
        (date(2026, 10, 22), datetime(2026, 10, 22, 10, 29, tzinfo=SYDNEY)),
        (date(2026, 10, 22), datetime(2026, 10, 22, 15, 1, tzinfo=SYDNEY)),
    ):
        with pytest.raises(ValueError, match="pinned"):
            probe._session_window(session, now=clock)


@pytest.mark.asyncio
async def test_no_execute_refuses_before_constructing_a_gateway(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(probe, "IB", lambda: pytest.fail("Gateway was constructed"))
    with pytest.raises(ValueError, match="--execute"):
        await probe._run(date(2026, 10, 22), tmp_path, "DS", tmp_path / "absent", "x", False)


def test_private_approval_requires_exact_hash_and_probe_terms(tmp_path) -> None:
    path = tmp_path / "approval.json"
    terms = {
        "account": FAKE_ACCOUNT,
        "approved_by": "DS",
        "approval_date": "2026-10-21",
        "session": "2026-10-22",
        "symbol": "BHP.AX",
        "operator": "DS",
        "quote_notional_cap_aud": "800",
    }
    path.write_text(json.dumps(terms), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert probe._load_approval(path, digest, "DS") == FAKE_ACCOUNT
    with pytest.raises(ValueError, match="SHA-256"):
        probe._load_approval(path, "wrong", "DS")
    with pytest.raises(ValueError, match="terms differ"):
        probe._load_approval(path, digest, "other operator")


def test_gateway_guard_checks_exact_account_before_every_request() -> None:
    raw = SimpleNamespace(
        managedAccounts=lambda: [FAKE_ACCOUNT],
        reqAllOpenOrdersAsync=lambda: "requested",
        placeOrder=lambda *args: "placed",
        cancelOrder=lambda *args: "cancelled",
    )
    guarded = probe._ExactAccountGateway(raw, FAKE_ACCOUNT)
    assert guarded.reqAllOpenOrdersAsync() == "requested"
    assert guarded.placeOrder(None, None) == "placed"
    raw.managedAccounts = lambda: [FAKE_ACCOUNT, "DU_OTHER"]
    with pytest.raises(ValueError, match="exactly"):
        guarded.reqAllOpenOrdersAsync()
    with pytest.raises(ValueError, match="exactly"):
        guarded.placeOrder(None, None)
    with pytest.raises(ValueError, match="exactly"):
        guarded.cancelOrder(None)


@pytest.mark.asyncio
async def test_initial_book_refuses_position_or_working_order(monkeypatch) -> None:
    monkeypatch.setattr(probe, "_order_view", lambda row: {})
    client = SimpleNamespace(
        expected_account=FAKE_ACCOUNT,
        managedAccounts=lambda: [FAKE_ACCOUNT],
        reqPositionsAsync=AsyncMock(return_value=[]),
        reqAllOpenOrdersAsync=AsyncMock(return_value=[]),
    )
    await probe._require_flat_book(client, [])
    client.reqPositionsAsync.return_value = [SimpleNamespace(account=FAKE_ACCOUNT, position=1)]
    with pytest.raises(RuntimeError, match="flat"):
        await probe._require_flat_book(client, [])
    client.reqPositionsAsync.return_value = []
    client.reqAllOpenOrdersAsync.return_value = [SimpleNamespace()]
    with pytest.raises(RuntimeError, match="flat"):
        await probe._require_flat_book(client, [])


@pytest.mark.asyncio
async def test_quote_delay_cannot_start_buy_after_entry_window(monkeypatch) -> None:
    monkeypatch.setattr(
        probe, "_qualified_bhp_contract", AsyncMock(return_value=SimpleNamespace(conId=123))
    )
    monkeypatch.setattr(probe, "_require_flat_book", AsyncMock())
    monkeypatch.setattr(probe, "_reference_quote", AsyncMock(return_value={"price": Decimal("65")}))

    def too_late(session):
        raise ValueError("entry window closed")

    monkeypatch.setattr(probe, "_session_window", too_late)
    adapter = SimpleNamespace(place_order=AsyncMock())
    with pytest.raises(ValueError, match="entry window"):
        await probe._perform(SimpleNamespace(), adapter, "DS", [])
    adapter.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_calls_approved_renewal_before_cancel_and_exit(monkeypatch) -> None:
    calls: list[str] = []
    contract = SimpleNamespace(conId=123)
    plan = GtcRenewalPlan(
        symbol="BHP.AX",
        order_id="stop",
        broker_order_id=17,
        quantity=8,
        stop_price=float(probe._stop_prices(Decimal("65"))[0]),
        auto_cancel_date=date(2026, 12, 31),
        account=FAKE_ACCOUNT,
        con_id=123,
        oca_group="",
        oca_type=0,
    )
    later = replace(plan, auto_cancel_date=date(2027, 3, 31))

    async def place(order):
        calls.append(f"place:{order.side}:{order.order_type}")

    async def renew(received, *, approved_plan_sha256, operator):
        assert received == plan
        assert approved_plan_sha256 == plan.digest
        assert operator == "DS"
        calls.append("renew")
        return later

    async def positions(*args):
        return 8.0

    async def flat(*args):
        calls.append("flat")

    async def quote(*args):
        return {"price": Decimal("65"), "market_data_type": 3}

    async def contract_fn(*args):
        return contract

    async def no_orders(*args):
        return []

    async def waiting(*args, **kwargs):
        return 8.0 if kwargs.get("positive") else 0.0

    async def cancel(*args):
        calls.append("cancel")

    monkeypatch.setattr(probe, "_qualified_bhp_contract", contract_fn)
    monkeypatch.setattr(probe, "_session_window", lambda session: None)
    monkeypatch.setattr(probe, "_require_flat_book", flat)
    monkeypatch.setattr(probe, "_reference_quote", quote)
    monkeypatch.setattr(probe, "_positions", positions)
    monkeypatch.setattr(probe, "_open_bhp_orders", no_orders)
    monkeypatch.setattr(probe, "_wait_for_position", waiting)
    monkeypatch.setattr(probe, "_wait_for_stop", AsyncMock())
    monkeypatch.setattr(probe, "_trade_filled", lambda *args: 8.0)
    monkeypatch.setattr(probe, "_record_buy_fill", lambda *args: None)
    monkeypatch.setattr(probe, "_record_trade", lambda *args: None)
    stop_snapshots = AsyncMock()
    execution_recheck = AsyncMock()
    monkeypatch.setattr(probe, "_record_stop_book", stop_snapshots)
    monkeypatch.setattr(probe, "_record_execution_recheck", execution_recheck)
    monkeypatch.setattr(probe, "_cancel_confirmed", cancel)
    monkeypatch.setattr(probe, "_exact_account", lambda *args: None)
    adapter = SimpleNamespace(
        place_order=place,
        plan_gtc_renewal=AsyncMock(return_value=plan),
        apply_approved_gtc_renewal=renew,
    )
    await probe._perform(SimpleNamespace(expected_account=FAKE_ACCOUNT), adapter, "DS", [])
    assert calls == [
        "flat",
        "place:buy:market",
        "place:sell:stop",
        "renew",
        "cancel",
        "place:sell:market",
        "flat",
    ]
    assert stop_snapshots.await_count == 2
    execution_recheck.assert_awaited_once()


@pytest.mark.asyncio
async def test_broker_snapshot_keeps_raw_auto_cancel_date(monkeypatch) -> None:
    order = SimpleNamespace(
        orderId=17,
        permId=19,
        orderRef="probe-stop",
        orderType="STP",
        tif="GTC",
        action="SELL",
        totalQuantity=8,
        auxPrice=58.5,
        autoCancelDate="20270331",
    )
    status = SimpleNamespace(status="Submitted", filled=0, avgFillPrice=0)
    trade = SimpleNamespace(order=order, orderStatus=status)
    monkeypatch.setattr(probe, "_open_bhp_orders", AsyncMock(return_value=[trade]))
    events = []
    await probe._record_stop_book(SimpleNamespace(), "probe-stop", "after amend", events)
    assert events[0]["working_stops"][0]["auto_cancel_date_raw"] == "20270331"
    assert events[0]["working_stops"][0]["status"] == "Submitted"


@pytest.mark.asyncio
async def test_emergency_sale_refuses_uncertain_stop(monkeypatch) -> None:
    trade = SimpleNamespace(
        order=SimpleNamespace(orderRef="probe-stop"),
        orderStatus=SimpleNamespace(status="PendingCancel"),
    )
    client = SimpleNamespace(trades=lambda: [trade])
    monkeypatch.setattr(probe, "_open_bhp_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(probe, "_positions", AsyncMock(return_value=8))
    adapter = SimpleNamespace(place_order=AsyncMock(), cancel_order=AsyncMock())
    with pytest.raises(RuntimeError, match="uncertain"):
        await probe._emergency_exit(
            client, adapter, 123, "probe-buy", "probe-stop", "probe-sell", 8, True, []
        )
    adapter.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_emergency_sale_refuses_after_normal_sell_submitted() -> None:
    sale = SimpleNamespace(order=SimpleNamespace(orderRef="probe-sell"))
    client = SimpleNamespace(trades=lambda: [sale])
    adapter = SimpleNamespace(place_order=AsyncMock(), cancel_order=AsyncMock())
    with pytest.raises(RuntimeError, match="second sale"):
        await probe._emergency_exit(
            client, adapter, 123, "probe-buy", "probe-stop", "probe-sell", 8, True, []
        )
    adapter.place_order.assert_not_awaited()
    adapter.cancel_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_emergency_sale_refuses_unidentified_submitted_stop(monkeypatch) -> None:
    client = SimpleNamespace(trades=lambda: [])
    monkeypatch.setattr(probe, "_open_bhp_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(probe, "_positions", AsyncMock(return_value=8))
    adapter = SimpleNamespace(place_order=AsyncMock(), cancel_order=AsyncMock())
    with pytest.raises(RuntimeError, match="no confirmed broker identity"):
        await probe._emergency_exit(
            client, adapter, 123, "probe-buy", "probe-stop", "probe-sell", 8, True, []
        )
    adapter.place_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_emergency_sale_is_limited_to_confirmed_probe_shares(monkeypatch) -> None:
    buy = SimpleNamespace(
        order=SimpleNamespace(orderRef="probe-buy"),
        orderStatus=SimpleNamespace(filled=8),
    )
    stopped = SimpleNamespace(
        order=SimpleNamespace(orderRef="probe-stop"),
        orderStatus=SimpleNamespace(status="Cancelled"),
    )
    client = SimpleNamespace(trades=lambda: [buy, stopped])
    monkeypatch.setattr(probe, "_open_bhp_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(probe, "_positions", AsyncMock(return_value=8))
    monkeypatch.setattr(probe, "_wait_for_position", AsyncMock(return_value=0))
    monkeypatch.setattr(probe, "_record_trade", lambda *args: None)
    monkeypatch.setattr(probe, "_exact_account", lambda *args: None)
    adapter = SimpleNamespace(place_order=AsyncMock(), cancel_order=AsyncMock())
    await probe._emergency_exit(
        client, adapter, 123, "probe-buy", "probe-stop", "probe-sell", 8, True, []
    )
    adapter.cancel_order.assert_not_awaited()
    submitted = adapter.place_order.await_args.args[0]
    assert submitted.side == "sell" and submitted.quantity == 8
    assert submitted.order_id == "probe-sell-rescue"
