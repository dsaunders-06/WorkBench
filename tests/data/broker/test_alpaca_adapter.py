"""AlpacaAdapter (spec M12), driven by a fake client.

Same approach as test_ib_adapter.py: the adapter's own logic (field
translation, status mapping, the live-trading gate) is what is worth testing,
and it is tested without API keys or network access. Nothing here proves a
real Alpaca round-trip works - see the README for how to check that yourself.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.alpaca_adapter import (
    AlpacaAdapter,
    AlpacaLiveTradingNotConfirmedError,
    _map_status,
)


class FakeAccount:
    equity = "50000.25"
    cash = "12345.67"
    buying_power = "24691.34"


class FakePosition:
    symbol = "AAPL"
    qty = "10"
    avg_entry_price = "190.50"


class FakeAlpacaOrder:
    id = "alpaca-order-1"
    symbol = "AAPL"
    qty = "5"
    side = "OrderSide.BUY"
    status = "accepted"
    filled_avg_price = None


class FakeClient:
    def __init__(self) -> None:
        self.submitted: list[object] = []
        self.cancelled: list[str] = []

    def get_account(self) -> FakeAccount:
        return FakeAccount()

    def get_all_positions(self) -> list[FakePosition]:
        return [FakePosition()]

    def submit_order(self, order_data: object) -> FakeAlpacaOrder:
        self.submitted.append(order_data)
        return FakeAlpacaOrder()

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def get_order_by_id(self, order_id: str) -> FakeAlpacaOrder:
        return FakeAlpacaOrder()


def _adapter(**settings_kwargs: object) -> tuple[AlpacaAdapter, FakeClient]:
    client = FakeClient()
    settings = Settings(_env_file=None, **settings_kwargs)  # type: ignore[arg-type]
    return AlpacaAdapter(client=client, settings=settings), client


async def test_account_translates_alpacas_string_fields():
    adapter, _client = _adapter()

    account = await adapter.account()

    assert account.net_liquidation == 50000.25
    assert account.cash == 12345.67
    assert account.buying_power == 24691.34


async def test_positions_are_translated():
    adapter, _client = _adapter()

    positions = await adapter.positions()

    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity == 10.0
    assert positions[0].avg_price == 190.50


async def test_place_order_submits_and_adopts_the_broker_order_id():
    adapter, client = _adapter()
    order = Order(symbol="AAPL", side="buy", quantity=5, order_id="local-id")

    result = await adapter.place_order(order)

    assert len(client.submitted) == 1
    assert result.order_id == "alpaca-order-1"
    # An accepted-but-unfilled order must not be reported as filled.
    assert result.status == "transmitted"


async def test_cancel_order_calls_through_and_returns_the_order():
    adapter, client = _adapter()

    result = await adapter.cancel_order("alpaca-order-1")

    assert client.cancelled == ["alpaca-order-1"]
    assert result.symbol == "AAPL"


def test_defaults_to_the_paper_endpoint():
    adapter, _client = _adapter()
    assert adapter.paper is True


def test_live_mode_requires_explicit_confirmation():
    with pytest.raises(AlpacaLiveTradingNotConfirmedError):
        AlpacaAdapter(client=FakeClient(), settings=Settings(_env_file=None, trading_mode="live"))


def test_live_mode_with_confirmation_targets_the_live_endpoint():
    adapter = AlpacaAdapter(
        client=FakeClient(),
        settings=Settings(_env_file=None, trading_mode="live"),
        live_trading_confirmed=True,
    )
    assert adapter.paper is False


@pytest.mark.parametrize(
    ("alpaca_status", "expected"),
    [
        ("filled", "filled"),
        ("accepted", "transmitted"),
        ("partially_filled", "transmitted"),
        ("canceled", "cancelled"),
        ("rejected", "rejected"),
        ("something_new_alpaca_added", "transmitted"),
    ],
)
def test_status_mapping(alpaca_status, expected):
    assert _map_status(alpaca_status) == expected


async def test_market_data_is_explicitly_unsupported():
    """This adapter is execution + account state only; pretending otherwise
    would silently produce a broken price feed."""
    adapter, _client = _adapter()

    with pytest.raises(NotImplementedError):
        await adapter.get_market_data("AAPL")
