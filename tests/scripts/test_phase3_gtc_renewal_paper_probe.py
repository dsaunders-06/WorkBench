"""Offline safety checks for the date-gated GTC paper probe."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from ib_async import Stock
from ib_async.order import OrderStatus, Trade

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import phase3_gtc_renewal_paper_probe as probe  # noqa: E402

from qat.config import Settings  # noqa: E402
from qat.data.broker.adapter import Order  # noqa: E402
from qat.data.broker.gtc_expiry import GtcRenewalPlan  # noqa: E402
from qat.data.broker.ib_adapter import IBAdapter  # noqa: E402
from qat.data.broker.pending_legs import leg_order_ref  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
FAKE_ACCOUNT = "DUTEST"


class FakeReferenceIB:
    """Return real adapter-generated broker refs, never application IDs."""

    def __init__(self) -> None:
        self.expected_account = FAKE_ACCOUNT
        self.contract = Stock("BHP", "ASX", "AUD", conId=4036812)
        self._trades: list[Trade] = []
        self.held = 0

    def managedAccounts(self) -> list[str]:
        return [FAKE_ACCOUNT]

    def trades(self) -> list[Trade]:
        return self._trades

    def positions(self) -> list[SimpleNamespace]:
        return (
            [SimpleNamespace(account=FAKE_ACCOUNT, contract=self.contract, position=self.held)]
            if self.held
            else []
        )

    async def qualifyContractsAsync(self, *contracts):
        return [self.contract]

    async def reqAllOpenOrdersAsync(self) -> list[Trade]:
        return [trade for trade in self._trades if trade.orderStatus.status == "Submitted"]

    def placeOrder(self, contract, order) -> Trade:
        if not order.orderId:
            order.orderId = 100 + len(self._trades)
        if not order.permId:
            order.permId = 500 + len(self._trades)
        order.clientId = 101
        if order.orderType == "STP":
            order.autoCancelDate = "20270122"
        filled = order.orderType == "MKT"
        if filled:
            self.held += int(order.totalQuantity) * (1 if order.action == "BUY" else -1)
        trade = Trade(
            contract=self.contract,
            order=order,
            orderStatus=OrderStatus(
                status="Filled" if filled else "Submitted",
                filled=order.totalQuantity if filled else 0,
                remaining=0 if filled else order.totalQuantity,
                avgFillPrice=65 if filled else 0,
                permId=order.permId,
            ),
        )
        if filled:
            trade.fills.append(
                SimpleNamespace(
                    time=datetime.now(UTC),
                    execution=SimpleNamespace(
                        execId=f"fake-{order.orderId}",
                        shares=order.totalQuantity,
                        price=65,
                        time=datetime.now(UTC),
                    ),
                    commissionReport=SimpleNamespace(commission=1, currency="AUD"),
                )
            )
        self._trades.append(trade)
        return trade

    def cancelOrder(self, order, manualCancelOrderTime="") -> None:
        matches = [trade for trade in self._trades if trade.order is order]
        assert len(matches) == 1
        matches[0].orderStatus.status = "Cancelled"


def _real_reference_adapter(tmp_path, client: FakeReferenceIB) -> IBAdapter:
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        ibkr_account_id=FAKE_ACCOUNT,
        ibkr_client_id=101,
        ibkr_permid_wait_seconds=0,
        operator_name="DS",
        data_dir=str(tmp_path),
    )
    return IBAdapter(client, EventBus(), settings=settings)


def _stub_nonidentity_inputs(monkeypatch, client: FakeReferenceIB) -> None:
    monkeypatch.setattr(probe, "_session_window", lambda session: None)
    monkeypatch.setattr(probe, "_qualified_bhp_contract", AsyncMock(return_value=client.contract))
    monkeypatch.setattr(probe, "_require_flat_book", AsyncMock())
    monkeypatch.setattr(probe, "_reference_quote", AsyncMock(return_value={"price": Decimal("65")}))

    async def held(*args, **kwargs):
        return float(client.held)

    monkeypatch.setattr(probe, "_positions", held)
    monkeypatch.setattr(probe, "_wait_for_position", held)


@pytest.mark.asyncio
async def test_real_adapter_refs_drive_buy_stop_renewal_and_exit(tmp_path, monkeypatch) -> None:
    client = FakeReferenceIB()
    adapter = _real_reference_adapter(tmp_path, client)
    _stub_nonidentity_inputs(monkeypatch, client)
    execution_recheck = AsyncMock()
    monkeypatch.setattr(probe, "_record_execution_recheck", execution_recheck)

    async def approved_renewal(plan, *, approved_plan_sha256, operator):
        assert operator == "DS" and approved_plan_sha256 == plan.digest
        stop = next(t for t in client.trades() if t.order.orderType == "STP")
        assert stop.order.orderRef == leg_order_ref(stop_app_id, "primary")
        assert plan.order_id == str(stop.order.permId)
        return replace(plan, auto_cancel_date=plan.auto_cancel_date + timedelta(days=90))

    original_place = adapter.place_order
    stop_app_id = ""

    async def capture_stop_id(order: Order):
        nonlocal stop_app_id
        if order.order_type == "stop":
            stop_app_id = order.order_id
        return await original_place(order)

    monkeypatch.setattr(adapter, "place_order", capture_stop_id)
    monkeypatch.setattr(adapter, "apply_approved_gtc_renewal", approved_renewal)
    events: list[dict] = []
    await probe._perform(client, adapter, "DS", events)

    assert client.held == 0
    assert [t.order.orderType for t in client.trades()] == ["MKT", "STP", "MKT"]
    buy, stop, sell = client.trades()
    for trade in (buy, stop, sell):
        leg = next(
            leg
            for leg in adapter._pending_legs.legs.values()
            if leg.broker_order_id == trade.order.orderId
        )
        assert trade.order.orderRef == leg_order_ref(leg.app_order_id, "primary")
        assert trade.order.orderRef != leg.app_order_id
    assert stop.orderStatus.status == "Cancelled"
    assert any(event["event"] == "GTC renewal result" for event in events)
    snapshots = [event for event in events if event["event"] == "initial stop auto-cancel date"]
    assert snapshots[0]["working_stops"][0]["order_ref"] == stop.order.orderRef
    assert execution_recheck.await_args.args[2] == (
        buy.order.orderRef,
        sell.order.orderRef,
    )


@pytest.mark.asyncio
async def test_real_adapter_refs_allow_bounded_emergency_sale(tmp_path, monkeypatch) -> None:
    client = FakeReferenceIB()
    adapter = _real_reference_adapter(tmp_path, client)
    _stub_nonidentity_inputs(monkeypatch, client)

    def halt_after_buy(*args):
        raise RuntimeError("forced post-buy halt")

    monkeypatch.setattr(probe, "_record_buy_fill", halt_after_buy)
    with pytest.raises(RuntimeError, match="forced post-buy halt"):
        await probe._perform(client, adapter, "DS", [])
    assert client.held == 0
    assert len(client.trades()) == 2
    buy, rescue = client.trades()
    assert buy.order.action == "BUY" and rescue.order.action == "SELL"
    rescue_leg = next(
        leg
        for leg in adapter._pending_legs.legs.values()
        if leg.broker_order_id == rescue.order.orderId
    )
    assert rescue.order.orderRef == leg_order_ref(rescue_leg.app_order_id, "primary")
    assert rescue.order.orderRef != rescue_leg.app_order_id


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
        pending_identity_reason=AsyncMock(return_value=None),
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
    adapter.pending_identity_reason.assert_awaited_once_with("BHP.AX")
    execution_recheck.assert_awaited_once()


@pytest.mark.asyncio
async def test_unresolved_stop_identity_refuses_renewal(monkeypatch) -> None:
    monkeypatch.setattr(
        probe, "_qualified_bhp_contract", AsyncMock(return_value=SimpleNamespace(conId=123))
    )
    monkeypatch.setattr(probe, "_session_window", lambda session: None)
    monkeypatch.setattr(probe, "_require_flat_book", AsyncMock())
    monkeypatch.setattr(probe, "_reference_quote", AsyncMock(return_value={"price": Decimal("65")}))
    monkeypatch.setattr(probe, "_wait_for_position", AsyncMock(return_value=8))
    monkeypatch.setattr(probe, "_open_bhp_orders", AsyncMock(return_value=[]))
    monkeypatch.setattr(probe, "_wait_for_stop", AsyncMock())
    monkeypatch.setattr(probe, "_record_trade", lambda *args: None)
    monkeypatch.setattr(probe, "_record_buy_fill", lambda *args: None)
    monkeypatch.setattr(probe, "_record_stop_book", AsyncMock())
    monkeypatch.setattr(probe, "_trade_filled", lambda *args: 8)
    monkeypatch.setattr(probe, "_exact_account", lambda *args: None)
    emergency = AsyncMock()
    monkeypatch.setattr(probe, "_emergency_exit", emergency)
    renewal = AsyncMock()
    adapter = SimpleNamespace(
        place_order=AsyncMock(),
        pending_identity_reason=AsyncMock(return_value="pending broker identity for BHP.AX"),
        plan_gtc_renewal=renewal,
    )
    with pytest.raises(RuntimeError, match="pending broker identity"):
        await probe._perform(SimpleNamespace(expected_account=FAKE_ACCOUNT), adapter, "DS", [])
    assert adapter.place_order.await_count == 2
    renewal.assert_not_awaited()
    emergency.assert_awaited_once()


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
        order=SimpleNamespace(orderRef=leg_order_ref("probe-stop", "primary")),
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
    sale = SimpleNamespace(order=SimpleNamespace(orderRef=leg_order_ref("probe-sell", "primary")))
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
        order=SimpleNamespace(orderRef=leg_order_ref("probe-buy", "primary")),
        orderStatus=SimpleNamespace(filled=8),
    )
    stopped = SimpleNamespace(
        order=SimpleNamespace(orderRef=leg_order_ref("probe-stop", "primary")),
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
