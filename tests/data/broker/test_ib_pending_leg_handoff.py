"""A late permId is a durable pending identity, never permission to resend."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from ib_async import CommissionReport, Execution, Fill, Stock
from ib_async import Position as IBPosition
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus


class Gateway:
    def __init__(self) -> None:
        self.placed: list[Trade] = []
        self.open: list[Trade] = []
        self.position_contract = Stock("BHP", "ASX", "AUD", primaryExchange="ASX")
        self.position_contract.conId = 4036812

    async def qualifyContractsAsync(self, contract):
        contract.conId = 4036812
        return [contract]

    def positions(self, account=""):
        return [IBPosition("DU123", self.position_contract, 9, 60)]

    def placeOrder(self, contract, order):
        order.orderId = len(self.placed) + 100
        order.clientId = 7
        order.permId = 0
        trade = Trade(contract, order, OrderStatus(status="PreSubmitted", permId=0))
        self.placed.append(trade)
        self.open.append(trade)
        return trade

    async def reqAllOpenOrdersAsync(self):
        return self.open

    async def reqExecutionsAsync(self, _filter):
        return []


def adapter(gateway: Gateway, tmp_path) -> IBAdapter:
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        market="ASX",
        ibkr_account_id="DU123",
        ibkr_client_id=7,
        ibkr_permid_wait_seconds=0,
    )
    return IBAdapter(gateway, EventBus(), settings=settings)


@pytest.mark.asyncio
async def test_late_entry_id_survives_restart_and_blocks_second_buy(tmp_path) -> None:
    gateway = Gateway()
    first = adapter(gateway, tmp_path)
    app_id = str(uuid4())
    await first.place_order(Order("BHP.AX", "buy", 9, order_id=app_id))
    assert len(gateway.placed) == 1
    assert gateway.placed[0].order.orderRef == app_id
    assert first._pending_legs is not None
    assert first._pending_legs.unresolved("BHP.AX") == (app_id,)

    restarted = adapter(gateway, tmp_path)
    assert await restarted.pending_identity_reason("BHP.AX")
    with pytest.raises(ValueError, match="pending broker identity"):
        await restarted.place_order(Order("BHP.AX", "buy", 9, order_id=app_id))
    assert len(gateway.placed) == 1

    gateway.open[0].order.permId = 991
    assert await restarted.pending_identity_reason("BHP.AX") is None
    assert restarted._pending_legs is not None
    assert restarted._pending_legs.legs[app_id].perm_id == 991


@pytest.mark.asyncio
async def test_stop_and_market_exit_do_not_wait_for_broker_identity(tmp_path) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    broker.settings.ibkr_permid_wait_seconds = 5
    loop = asyncio.get_running_loop()
    started = loop.time()
    stop = Order("BHP.AX", "sell", 9, order_id=str(uuid4()), order_type="stop", stop_price=55)
    await broker.place_order(stop)
    market_exit = Order("BHP.AX", "sell", 9, order_id=str(uuid4()))
    await broker.place_order(market_exit)
    assert loop.time() - started < 1
    assert len(gateway.placed) == 2
    assert all(str(UUID(trade.order.orderRef)) == trade.order.orderRef for trade in gateway.placed)
    assert broker._pending_legs is not None
    assert len(broker._pending_legs.unresolved("BHP.AX")) == 2


@pytest.mark.asyncio
async def test_working_stop_resolves_by_open_order_without_a_fill(tmp_path) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    app_id = str(uuid4())
    await broker.place_order(
        Order("BHP.AX", "sell", 9, order_id=app_id, order_type="stop", stop_price=55)
    )
    assert broker._pending_legs is not None
    assert broker._pending_legs.unresolved("BHP.AX") == (app_id,)
    gateway.open[0].order.permId = 992
    assert await broker.pending_identity_reason("BHP.AX") is None
    assert gateway.open, "the stop remains working after identity resolution"


@pytest.mark.asyncio
async def test_bracket_records_distinct_uuid_for_each_leg(tmp_path) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    await broker.place_order(
        Order("BHP.AX", "buy", 9, order_id=str(uuid4()), stop_price=55, take_profit_price=70)
    )
    refs = [trade.order.orderRef for trade in gateway.placed]
    assert len(refs) == 3
    assert len(set(refs)) == 3
    assert all(str(UUID(ref)) == ref for ref in refs)
    assert broker._pending_legs is not None
    assert set(broker._pending_legs.unresolved("BHP.AX")) == set(refs)


@pytest.mark.asyncio
async def test_immediate_fill_without_open_order_resolves_by_execution_reference(tmp_path) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    app_id = str(uuid4())
    await broker.place_order(Order("BHP.AX", "buy", 9, order_id=app_id))
    gateway.open.clear()

    async def requested(_filter):
        execution = SimpleNamespace(
            orderRef=app_id,
            acctNumber="DU123",
            clientId=7,
            permId=991,
            orderId=100,
        )
        return [SimpleNamespace(contract=gateway.position_contract, execution=execution)]

    gateway.reqExecutionsAsync = requested  # type: ignore[method-assign]
    assert await broker.pending_identity_reason("BHP.AX") is None
    assert broker._pending_legs is not None
    assert broker._pending_legs.legs[app_id].perm_id == 991


@pytest.mark.asyncio
async def test_identity_store_failure_does_not_block_an_exposure_reducing_exit(
    tmp_path, monkeypatch
) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    assert broker._pending_legs is not None

    def unavailable(*_args, **_kwargs):
        assert gateway.placed, "the exit must be handed to IBKR before identity persistence"
        raise OSError("disk unavailable")

    monkeypatch.setattr(broker._pending_legs, "begin", unavailable)
    await broker.place_order(Order("BHP.AX", "sell", 9, order_id=str(uuid4())))
    assert len(gateway.placed) == 1

    def unavailable_buy(*_args, **_kwargs):
        assert len(gateway.placed) == 1, "the buy must be persisted before hand-off"
        raise OSError("disk unavailable")

    monkeypatch.setattr(broker._pending_legs, "begin", unavailable_buy)
    with pytest.raises(OSError, match="disk unavailable"):
        await broker.place_order(Order("BHP.AX", "buy", 9, order_id=str(uuid4())))
    assert len(gateway.placed) == 1


@pytest.mark.asyncio
async def test_target_execution_maps_its_distinct_uuid_back_to_the_app_order(tmp_path) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    app_id = str(uuid4())
    await broker.place_order(
        Order("BHP.AX", "buy", 9, order_id=app_id, stop_price=55, take_profit_price=70)
    )
    target = next(trade.order for trade in gateway.placed if trade.order.orderType == "LMT")
    instant = datetime(2026, 10, 14, 0, 30, tzinfo=UTC)
    execution = Execution(
        execId="target.1",
        time=instant,
        side="SLD",
        shares=9,
        price=70,
        cumQty=9,
        avgPrice=70,
        permId=991,
        orderId=target.orderId,
        clientId=7,
        acctNumber="DU123",
        orderRef=target.orderRef,
    )
    gateway.open.clear()

    async def requested(_filter):
        return [Fill(gateway.position_contract, execution, CommissionReport(), instant)]

    gateway.reqExecutionsAsync = requested  # type: ignore[method-assign]
    fills = await broker.recent_fills(datetime(2026, 10, 13, tzinfo=UTC))
    assert len(fills) == 1
    assert fills[0].app_order_id == app_id
    assert fills[0].filled_at == instant
    assert broker._pending_legs is not None
    assert target.orderRef not in broker._pending_legs.unresolved("BHP.AX")


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_identity", ["account", "con_id", "client_id"])
async def test_matching_reference_cannot_alias_a_fill_with_wrong_broker_identity(
    tmp_path, wrong_identity: str
) -> None:
    gateway = Gateway()
    broker = adapter(gateway, tmp_path)
    app_id = str(uuid4())
    await broker.place_order(Order("BHP.AX", "buy", 9, order_id=app_id))
    instant = datetime(2026, 10, 14, 0, 30, tzinfo=UTC)
    contract = gateway.position_contract
    if wrong_identity == "con_id":
        contract = Stock("BHP", "ASX", "AUD", primaryExchange="ASX")
        contract.conId = 999999
    execution = Execution(
        execId="wrong.1",
        time=instant,
        side="BOT",
        shares=9,
        price=60,
        cumQty=9,
        avgPrice=60,
        permId=991,
        orderId=100,
        clientId=8 if wrong_identity == "client_id" else 7,
        acctNumber="DU999" if wrong_identity == "account" else "DU123",
        orderRef=app_id,
    )

    async def requested(_filter):
        return [Fill(contract, execution, CommissionReport(), instant)]

    gateway.reqExecutionsAsync = requested  # type: ignore[method-assign]
    assert await broker.recent_fills(datetime(2026, 10, 13, tzinfo=UTC)) == []
    assert broker._pending_legs is not None
    assert broker._pending_legs.unresolved("BHP.AX") == (app_id,)
