from __future__ import annotations

import pytest

from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker, new_order_id


@pytest.mark.asyncio
async def test_same_seed_produces_same_fill_price():
    broker_a = MockBroker(seed=42)
    broker_b = MockBroker(seed=42)

    price_a = await broker_a.get_market_data("AAPL")
    price_b = await broker_b.get_market_data("AAPL")

    assert price_a == price_b


@pytest.mark.asyncio
async def test_place_order_fills_immediately_and_updates_position():
    broker = MockBroker(seed=1)
    order = Order(symbol="AAPL", side="buy", quantity=10, order_id=new_order_id())

    filled = await broker.place_order(order)

    assert filled.status == "filled"
    assert filled.filled_price is not None

    positions = await broker.positions()
    assert len(positions) == 1
    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity == 10


@pytest.mark.asyncio
async def test_sell_order_reduces_cash_less_than_buy():
    broker = MockBroker(seed=1)
    buy_order = Order(symbol="AAPL", side="buy", quantity=10, order_id=new_order_id())
    await broker.place_order(buy_order)
    account_after_buy = await broker.account()

    sell_order = Order(symbol="AAPL", side="sell", quantity=5, order_id=new_order_id())
    await broker.place_order(sell_order)
    account_after_sell = await broker.account()

    assert account_after_sell.cash > account_after_buy.cash


@pytest.mark.asyncio
async def test_cancel_order_sets_status_cancelled():
    broker = MockBroker(seed=1)
    order = Order(symbol="AAPL", side="buy", quantity=10, order_id=new_order_id())
    await broker.place_order(order)

    cancelled = await broker.cancel_order(order.order_id)

    assert cancelled.status == "cancelled"
