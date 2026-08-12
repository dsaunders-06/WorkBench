"""Tests IBAdapter's own logic (connection lifecycle, backoff reconnect,
heartbeat, safety gates) against a FakeIBClient - no real socket or IB
Gateway/TWS process involved. Translation correctness is covered
separately in test_ib_translate.py using real ib_async data classes."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import (
    _LIVE_PORTS,
    IBAdapter,
    LivePortInPaperModeError,
    LiveTradingNotConfirmedError,
    ReadOnlyModeError,
)
from qat.domain.bus import EventBus
from qat.domain.events import KillSwitchEvent


class _FakeTicker:
    bid = 99.0
    ask = 101.0
    last = 100.0


class FakeIBClient:
    def __init__(self, connect_should_fail: bool = False) -> None:
        self.connected = False
        self.connect_calls = 0
        self.connect_should_fail = connect_should_fail
        self.placed_orders: list[tuple[Any, Any]] = []
        self.cancelled_orders: list[Any] = []

    def isConnected(self) -> bool:
        return self.connected

    async def connectAsync(
        self, host: str, port: int, clientId: int, timeout: float = 4.0, readonly: bool = False
    ) -> None:
        self.connect_calls += 1
        if self.connect_should_fail:
            raise ConnectionError("simulated connect failure")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    async def reqCurrentTimeAsync(self) -> datetime:
        if not self.connected:
            raise ConnectionError("not connected")
        return datetime.now()

    def placeOrder(self, contract: Any, order: Any) -> Trade:
        self.placed_orders.append((contract, order))
        order_status = OrderStatus(
            status="Filled", avgFillPrice=100.0, filled=order.totalQuantity, remaining=0
        )
        return Trade(contract=contract, order=order, orderStatus=order_status)

    def cancelOrder(self, order: Any, manualCancelOrderTime: str = "") -> Trade | None:
        self.cancelled_orders.append(order)
        return None

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []

    async def reqHistoricalDataAsync(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def reqMktData(
        self,
        contract: Any,
        genericTickList: str = "",
        snapshot: bool = False,
        regulatorySnapshot: bool = False,
    ) -> _FakeTicker:
        return _FakeTicker()


def _candidate_order(symbol: str = "AAPL") -> Order:
    return Order(symbol=symbol, side="buy", quantity=10, order_id="order-1")


@pytest.mark.asyncio
async def test_connect_calls_client_connect_and_starts_heartbeat():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(
        client, bus, settings=Settings(_env_file=None), heartbeat_interval_seconds=1000
    )

    await adapter.connect()

    assert client.connect_calls == 1
    assert client.connected is True
    await adapter.disconnect()


def test_live_trading_without_confirmation_raises():
    client = FakeIBClient()
    bus = EventBus()
    settings = Settings(_env_file=None, trading_mode="live")

    with pytest.raises(LiveTradingNotConfirmedError):
        IBAdapter(client, bus, settings=settings, live_trading_confirmed=False)


def test_live_trading_with_explicit_confirmation_constructs():
    client = FakeIBClient()
    bus = EventBus()
    settings = Settings(_env_file=None, trading_mode="live")

    adapter = IBAdapter(client, bus, settings=settings, live_trading_confirmed=True)
    assert adapter is not None


@pytest.mark.asyncio
async def test_read_only_blocks_place_order():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(client, bus, settings=Settings(_env_file=None), read_only=True)

    with pytest.raises(ReadOnlyModeError):
        await adapter.place_order(_candidate_order())

    assert client.placed_orders == []


@pytest.mark.asyncio
async def test_read_only_blocks_cancel_order():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(client, bus, settings=Settings(_env_file=None), read_only=True)

    with pytest.raises(ReadOnlyModeError):
        await adapter.cancel_order("does-not-matter")


@pytest.mark.asyncio
async def test_place_order_fills_and_tracks_ib_order():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(client, bus, settings=Settings(_env_file=None))

    filled = await adapter.place_order(_candidate_order())

    assert filled.status == "filled"
    assert filled.filled_price == 100.0
    assert len(client.placed_orders) == 1


@pytest.mark.asyncio
async def test_cancel_order_calls_broker_cancel():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(client, bus, settings=Settings(_env_file=None))
    order = await adapter.place_order(_candidate_order())

    cancelled = await adapter.cancel_order(order.order_id)

    assert cancelled.status == "cancelled"
    assert len(client.cancelled_orders) == 1


@pytest.mark.asyncio
async def test_get_market_data_returns_bid_ask_last():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(client, bus, settings=Settings(_env_file=None))

    quote = await adapter.get_market_data("AAPL")

    assert quote == {"bid": 99.0, "ask": 101.0, "last": 100.0}


@pytest.mark.asyncio
async def test_reconnect_succeeds_within_backoff_budget():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(
        client,
        bus,
        settings=Settings(_env_file=None),
        initial_backoff_seconds=0.001,
        max_backoff_seconds=0.01,
        max_reconnect_attempts=3,
    )
    await adapter.connect()
    client.connected = False

    await adapter._reconnect_with_backoff()

    assert client.connected is True
    assert client.connect_calls >= 2
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_reconnect_exhausted_publishes_kill_switch_event():
    client = FakeIBClient(connect_should_fail=True)
    bus = EventBus()
    received: list[KillSwitchEvent] = []

    async def handler(event: KillSwitchEvent) -> None:
        received.append(event)

    bus.subscribe(KillSwitchEvent, handler)
    adapter = IBAdapter(
        client,
        bus,
        settings=Settings(_env_file=None),
        initial_backoff_seconds=0.001,
        max_backoff_seconds=0.01,
        max_reconnect_attempts=2,
    )

    await adapter._reconnect_with_backoff()

    assert len(received) == 1
    assert received[0].triggered_by == "ib-adapter"


@pytest.mark.asyncio
async def test_heartbeat_loop_triggers_reconnect_when_unhealthy():
    client = FakeIBClient()
    bus = EventBus()
    adapter = IBAdapter(
        client,
        bus,
        settings=Settings(_env_file=None),
        heartbeat_interval_seconds=0.01,
        initial_backoff_seconds=0.001,
        max_backoff_seconds=0.01,
        max_reconnect_attempts=2,
    )
    await adapter.connect()
    client.connected = False

    await asyncio.sleep(0.1)

    assert client.connected is True
    await adapter.disconnect()


@pytest.mark.parametrize("live_port", sorted(_LIVE_PORTS))
def test_paper_mode_with_a_live_port_refuses_to_construct(live_port: int):
    """W1.4. This used to warn and then connect, which is the one direction
    that cannot be allowed to be a log line: `is_live` is `trading_mode ==
    "live"` and nothing else, so a paper claim against a live Gateway leaves
    the autonomy gate, promotion-evidence enforcement, the cost model and the
    mode banner all reading 'paper' while real orders are reachable."""
    client = FakeIBClient()
    bus = EventBus()
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=live_port)

    with pytest.raises(LivePortInPaperModeError):
        IBAdapter(client, bus, settings=settings)


def test_the_port_refusal_says_which_ports_are_the_paper_ones():
    """An operator who has just been refused needs the fix in the message, not
    a trip to the source - the same argument M39's wording tests make."""
    client = FakeIBClient()
    bus = EventBus()
    settings = Settings(_env_file=None, trading_mode="paper", ibkr_port=4001)

    with pytest.raises(LivePortInPaperModeError) as raised:
        IBAdapter(client, bus, settings=settings)
    message = str(raised.value)
    assert "4002" in message
    assert "7497" in message


def test_live_mode_against_a_paper_port_still_constructs():
    """The asymmetry is deliberate. Claiming live while reaching a paper
    Gateway is the SAFE direction - costs are applied, autonomy is gated and
    the banner says DANGER - so it is not refused."""
    client = FakeIBClient()
    bus = EventBus()
    settings = Settings(_env_file=None, trading_mode="live", ibkr_port=4002)

    adapter = IBAdapter(client, bus, settings=settings, live_trading_confirmed=True)
    assert adapter is not None
