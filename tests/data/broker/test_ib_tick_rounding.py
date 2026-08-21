"""M123: the first ASX order this app sends must be a price the ASX accepts.

Nothing computed ticks until now, and on the US side nothing had to: the tick
is a cent at every price a megacap trades at, so AlpacaAdapter's `round(x, 2)`
and "on a valid increment" were the same thing. The ASX step between $0.10 and
$2.00 is half a cent, the swing strategy derives its stop from ATR, and on
21 August the app went live on 94 ASX names with autonomous execution - two of
the armed candidates trading inside that band.

An off-tick price is not a worse price. IBKR rejects it (error 110) and the
order never reaches the market, so the entry does not happen or - worse - the
protective leg of a bracket does not.

Imported by BARE NAME because CI runs bare pytest.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_ib_brackets import RecordingIB

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.data.broker.ticks import is_on_tick
from qat.domain.bus import EventBus


def _adapter(market: str = "ASX") -> tuple[IBAdapter, RecordingIB]:
    client = RecordingIB()
    settings = Settings(_env_file=None, trading_mode="paper", market=market)
    return IBAdapter(client, EventBus(), settings=settings), client


def _entry(**overrides: Any) -> Order:
    fields: dict[str, Any] = {
        "symbol": "MGR.AX",
        "side": "buy",
        "quantity": 100,
        "order_id": "app-entry",
        "limit_price": 1.9137,
        "stop_price": 1.8734,
        "take_profit_price": 2.0341,
    }
    fields.update(overrides)
    return Order(**fields)


@pytest.mark.asyncio
async def test_a_bracketed_asx_entry_is_priced_on_ticks(monkeypatch) -> None:
    """The case that prompted this. MGR.AX at $1.91 is in the half-cent band
    and every one of these three prices is off it."""
    adapter, _client = _adapter()
    monkeypatch.setattr(adapter, "_check_not_read_only", lambda: None)

    placed = await adapter.place_order(_entry())

    for field in ("limit_price", "stop_price", "take_profit_price"):
        price = getattr(placed, field)
        assert is_on_tick(price, "ASX"), f"{field}={price} is not an ASX price"


@pytest.mark.asyncio
async def test_the_protective_stop_is_never_loosened_by_rounding(monkeypatch) -> None:
    """The leg REVERSES the entry's side, so a long's stop is a SELL and rounds
    UP - toward the market, triggering sooner. Rounding may tighten protection
    by up to a tick; it must never widen it."""
    adapter, _client = _adapter()
    monkeypatch.setattr(adapter, "_check_not_read_only", lambda: None)

    placed = await adapter.place_order(_entry(stop_price=1.8734))

    assert placed.stop_price == 1.875
    assert placed.stop_price > 1.8734


@pytest.mark.asyncio
async def test_the_entry_never_bids_more_than_it_was_asked_to(monkeypatch) -> None:
    adapter, _client = _adapter()
    monkeypatch.setattr(adapter, "_check_not_read_only", lambda: None)

    placed = await adapter.place_order(_entry(limit_price=1.9137))

    assert placed.limit_price == 1.910
    assert placed.limit_price < 1.9137


@pytest.mark.asyncio
async def test_a_standalone_resting_stop_rounds_on_its_own_side(monkeypatch) -> None:
    """`order_type="stop"` means the order IS the protection, so its own side
    is already the closing side and must not be reversed a second time."""
    adapter, _client = _adapter()
    monkeypatch.setattr(adapter, "_check_not_read_only", lambda: None)

    placed = await adapter.place_order(
        Order(
            symbol="MGR.AX",
            side="sell",
            quantity=100,
            order_id="app-stop",
            order_type="stop",
            stop_price=1.8734,
        )
    )

    assert placed.stop_price == 1.875  # up: tighter, not looser


@pytest.mark.asyncio
async def test_a_split_adjusted_stop_is_re_ticked_on_modify(monkeypatch) -> None:
    """M39's corporate-action path divides the old stop by the split ratio,
    which lands off the grid far more often than on it. A rejected adjustment
    leaves the OLD stop at the broker while the app records the new one - the
    MNST shape."""
    adapter, _client = _adapter()
    monkeypatch.setattr(adapter, "_check_not_read_only", lambda: None)
    await adapter.place_order(_entry())

    modified = await adapter.modify_order("app-entry", stop_price=1.8734 / 2)

    assert is_on_tick(modified.stop_price, "ASX")
    assert modified.stop_price == 0.94  # 0.9367 -> up to the half-cent grid


@pytest.mark.asyncio
async def test_a_us_order_is_unchanged_at_a_cent(monkeypatch) -> None:
    """The US path had no defect and must not acquire one."""
    adapter, _client = _adapter(market="US")
    monkeypatch.setattr(adapter, "_check_not_read_only", lambda: None)

    placed = await adapter.place_order(
        _entry(symbol="AAPL", limit_price=105.47, stop_price=99.36, take_profit_price=115.02)
    )

    assert placed.limit_price == 105.47
    assert placed.stop_price == 99.36
    assert placed.take_profit_price == 115.02
