"""The drift guard on parked orders must not fail open in silence (item 37).

An order the autonomy gate blocks on session phase is not rejected - it parks
in `pending_signoff` and is retried every 60s. On 25 August four orders parked
across the Midday Lull and all four released together at 14:04:53, having been
sized 80+ minutes earlier.

`AutonomousExecutor._retry_loop`'s docstring says parking is safe because "the
gate re-reads the current price and refuses anything that has drifted past
`autonomous_price_drift_limit_pct`... An order that sat too long fails on drift
rather than being signed at a price nobody chose."

Two things defeat that:

1. `gate.py` reads `if current_price is not None and ...` - a None price skips
   the check with no block AND NO LOG, so an operator cannot tell a drift check
   that passed from one that never ran.
2. `_current_price` builds the price as
   `float(quote.get("last") or quote.get("ask") or 0.0)`. **`nan` is truthy**,
   so a `nan` last returns `nan` instead of falling through to `ask` - the
   fallback is unreachable - and `nan > 0` is False, so the whole thing returns
   None. `IBAdapter.get_market_data` issues `reqMktData` and yields ONCE before
   reading a ticker whose fields default to `nan`.

No `has drifted` line exists in any log back to 12 August.
"""

from __future__ import annotations

import logging
import math

import pytest

from qat.domain.autonomy.executor import AutonomousExecutor


class _Broker:
    def __init__(self, quote):
        self._quote = quote

    async def get_market_data(self, symbol: str):
        return self._quote


def _executor(quote) -> AutonomousExecutor:
    ex = AutonomousExecutor.__new__(AutonomousExecutor)
    ex.oms = type("_O", (), {"broker": _Broker(quote)})()
    # No fallback: this file pins what happens when NOTHING can price the
    # symbol. The fallback added on 4 September is a second source, not a
    # replacement for these rails - with one wired, a broker that cannot quote
    # is no longer the end of the story, and none of the assertions below would
    # be testing the case they are named for.
    ex._fallback_price = None
    return ex


@pytest.mark.asyncio
async def test_a_nan_last_falls_through_to_the_ask():
    """The unreachable fallback. `nan or x` returns nan because nan is truthy,
    so before this fix a nan `last` never reached `ask`."""
    price = await _executor({"last": float("nan"), "ask": 44.60, "bid": 44.50})._current_price(
        "RHC.AX"
    )
    assert price == 44.60, "a nan last must fall through to the ask, not swallow it"


@pytest.mark.asyncio
async def test_all_nan_yields_no_price_rather_than_nan():
    price = await _executor(
        {"last": float("nan"), "ask": float("nan"), "bid": float("nan")}
    )._current_price("RHC.AX")
    assert price is None
    assert not (price is not None and math.isnan(price))


@pytest.mark.asyncio
async def test_a_real_last_is_used_unchanged():
    price = await _executor({"last": 44.60, "ask": 44.70, "bid": 44.50})._current_price("RHC.AX")
    assert price == 44.60


@pytest.mark.asyncio
async def test_a_zero_price_is_not_a_price():
    price = await _executor({"last": 0.0, "ask": 0.0, "bid": 0.0})._current_price("RHC.AX")
    assert price is None


@pytest.mark.asyncio
async def test_being_unable_to_price_is_LOGGED_not_silent(caplog):
    """The half that matters most. A skipped drift check and a passed one were
    indistinguishable, on every screen and in every log."""
    with caplog.at_level(logging.WARNING):
        price = await _executor({"last": float("nan"), "ask": float("nan")})._current_price(
            "RHC.AX"
        )
    assert price is None
    assert "RHC.AX" in caplog.text
    assert "drift" in caplog.text.lower()
