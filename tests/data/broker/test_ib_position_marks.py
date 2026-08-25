"""IBKR positions must carry the broker's mark (item 45).

On 25 August every row of the Positions panel showed `Last ($) —`, `P&L —`,
`To stop —` and `(escape unknown)`, for all ten holdings. `(escape unknown)` was
the honesty marker working: `escape_evaluated` is false only when a stop exists
but no price was supplied to measure the loss against, so the panel said "we
could not check" rather than asserting the minimum hold was on.

It appeared on every row because `Position.current_price` was never populated.
The field is M66's and its comment discusses ALPACA's consolidated tape - built
before the IBKR move and never carried across. Measured against ib_async 2.1.0:

    ib.positions()  -> Position(account, contract, position, avgCost)
    ib.portfolio()  -> PortfolioItem(contract, position, marketPrice, ...)

`ib_adapter.positions()` used the first, which has no price.

The mark is NOT cosmetic: without it the minimum-hold loss escape cannot be
evaluated, so every position is conservatively held and one falling hard enough
to escape its hold cannot be detected. That is a rail, not a display.

`positions()` stays the source of truth for QUANTITY - `check_reconciliation`
builds its kill-switch input from that set - and the mark is enriched onto it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qat.data.broker.ib_adapter import IBAdapter


def _adapter(positions, portfolio):
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = SimpleNamespace(
        positions=lambda: positions,
        portfolio=lambda: portfolio,
    )
    adapter.settings = SimpleNamespace(market="ASX")
    return adapter


def _pos(symbol: str, qty: float, avg: float):
    return SimpleNamespace(contract=SimpleNamespace(symbol=symbol), position=qty, avgCost=avg)


def _item(symbol: str, qty: float, mark: float):
    return SimpleNamespace(contract=SimpleNamespace(symbol=symbol), position=qty, marketPrice=mark)


@pytest.mark.asyncio
async def test_the_broker_mark_reaches_the_position():
    """THE regression for item 45."""
    got = await _adapter([_pos("ANZ", 640, 37.24)], [_item("ANZ", 640, 38.10)]).positions()
    assert len(got) == 1
    assert got[0].symbol == "ANZ.AX"
    assert got[0].current_price == 38.10, "the mark from portfolio() must reach current_price"
    assert got[0].avg_price == 37.24, "avg_price is the cost basis and must not be overwritten"


@pytest.mark.asyncio
async def test_quantity_still_comes_from_positions_not_portfolio():
    """`check_reconciliation` builds its kill-switch input from this set, so
    the QUANTITY must keep coming from `positions()`. A portfolio item that
    disagrees must not silently redefine the book."""
    got = await _adapter([_pos("ANZ", 640, 37.24)], [_item("ANZ", 999, 38.10)]).positions()
    assert got[0].quantity == 640, "quantity must come from positions(), not portfolio()"


@pytest.mark.asyncio
async def test_a_position_absent_from_the_portfolio_keeps_no_mark():
    """`None` means "this adapter does not report a mark", which is a DIFFERENT
    claim from "the mark is zero" - read as zero, every position would measure
    as risk-free. So an unmatched position must stay None, not become 0.0."""
    got = await _adapter([_pos("ANZ", 640, 37.24)], []).positions()
    assert got[0].current_price is None


@pytest.mark.asyncio
async def test_a_client_without_portfolio_still_returns_positions():
    """An adapter or fake that predates this must keep working, with no mark
    rather than an exception."""
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = SimpleNamespace(positions=lambda: [_pos("ANZ", 640, 37.24)])
    adapter.settings = SimpleNamespace(market="ASX")
    got = await adapter.positions()
    assert len(got) == 1
    assert got[0].current_price is None


@pytest.mark.asyncio
async def test_a_zero_or_negative_mark_is_not_recorded():
    """IBKR reports 0.0 for an instrument it has no data on. Zero is not a
    price, and a position marked at zero measures as a total loss."""
    got = await _adapter([_pos("ANZ", 640, 37.24)], [_item("ANZ", 640, 0.0)]).positions()
    assert got[0].current_price is None


@pytest.mark.asyncio
async def test_a_nan_mark_is_not_recorded():
    """The item 37 trap, pinned here because it fails OPEN one line away.

    `nan` is TRUTHY in Python, so `float(getattr(item, "marketPrice", 0.0) or
    0.0)` returns `nan` rather than falling through to the default - exactly
    how the drift guard's `quote.get("last") or quote.get("ask")` chain was
    defeated. It is caught here only because the guard tests `price > 0`, and
    `nan > 0` is False. Written down so a future refactor to `if price:` or
    `if price is not None:` fails this test instead of silently marking a
    position at nan.
    """
    got = await _adapter([_pos("ANZ", 640, 37.24)], [_item("ANZ", 640, float("nan"))]).positions()
    assert got[0].current_price is None
