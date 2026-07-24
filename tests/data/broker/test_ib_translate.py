"""Translation correctness using real ib_async data classes (no network) -
they're plain constructible objects, so this tests against the actual
library's shapes rather than a guess at them."""

from __future__ import annotations

from ib_async import AccountValue, Stock
from ib_async import Position as IBPosition
from ib_async.order import MarketOrder, OrderStatus, Trade

from qat.data.broker.adapter import Order
from qat.data.broker.ib_translate import (
    from_ib_account_values,
    from_ib_position,
    from_ib_trade,
    to_ib_contract,
    to_ib_order,
)


def test_to_ib_contract_builds_a_stock_contract():
    contract = to_ib_contract("AAPL")
    assert contract.symbol == "AAPL"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"


def test_to_ib_order_market_buy():
    order = Order(symbol="AAPL", side="buy", quantity=10, order_id="x")
    ib_order = to_ib_order(order)
    assert ib_order.action == "BUY"
    assert ib_order.totalQuantity == 10
    assert ib_order.orderType == "MKT"


def test_to_ib_order_limit_sell():
    order = Order(symbol="AAPL", side="sell", quantity=5, order_id="x", limit_price=123.45)
    ib_order = to_ib_order(order)
    assert ib_order.action == "SELL"
    assert ib_order.orderType == "LMT"
    assert ib_order.lmtPrice == 123.45


def test_from_ib_trade_updates_status_and_fill_price():
    our_order = Order(symbol="AAPL", side="buy", quantity=10, order_id="x")
    contract = Stock("AAPL", "SMART", "USD")
    ib_order = MarketOrder("BUY", 10)
    order_status = OrderStatus(status="Filled", avgFillPrice=150.25, filled=10, remaining=0)
    trade = Trade(contract=contract, order=ib_order, orderStatus=order_status)

    updated = from_ib_trade(trade, our_order)

    assert updated.status == "filled"
    assert updated.filled_price == 150.25


def test_from_ib_trade_leaves_unmapped_intermediate_status_alone():
    our_order = Order(symbol="AAPL", side="buy", quantity=10, order_id="x", status="transmitted")
    contract = Stock("AAPL", "SMART", "USD")
    ib_order = MarketOrder("BUY", 10)
    order_status = OrderStatus(status="Submitted", avgFillPrice=0.0, filled=0, remaining=10)
    trade = Trade(contract=contract, order=ib_order, orderStatus=order_status)

    updated = from_ib_trade(trade, our_order)

    assert updated.status == "transmitted"


def test_from_ib_position_translates_symbol_quantity_and_avg_cost():
    contract = Stock("AAPL", "SMART", "USD")
    ib_position = IBPosition(account="DU12345", contract=contract, position=25.0, avgCost=142.5)

    position = from_ib_position(ib_position)

    assert position.symbol == "AAPL"
    assert position.quantity == 25.0
    assert position.avg_price == 142.5


def test_from_ib_account_values_extracts_known_tags():
    values = [
        AccountValue(
            account="DU1", tag="NetLiquidation", value="100000.5", currency="USD", modelCode=""
        ),
        AccountValue(
            account="DU1", tag="TotalCashValue", value="50000.0", currency="USD", modelCode=""
        ),
        AccountValue(
            account="DU1", tag="BuyingPower", value="200000.0", currency="USD", modelCode=""
        ),
        AccountValue(account="DU1", tag="SomeOtherTag", value="999", currency="USD", modelCode=""),
    ]

    summary = from_ib_account_values(values)

    assert summary.net_liquidation == 100000.5
    assert summary.cash == 50000.0
    assert summary.buying_power == 200000.0


def test_from_ib_account_values_defaults_to_zero_when_tags_missing():
    summary = from_ib_account_values([])
    assert summary.net_liquidation == 0.0
    assert summary.cash == 0.0
    assert summary.buying_power == 0.0


def test_from_ib_account_values_skips_unparseable_values():
    values = [
        AccountValue(
            account="DU1", tag="NetLiquidation", value="not-a-number", currency="USD", modelCode=""
        )
    ]
    summary = from_ib_account_values(values)
    assert summary.net_liquidation == 0.0
