"""A snapshot has no delayed tier, so the quote must stream.

This line has been wrong twice. It first called `reqMktData` and yielded ONCE
before reading a `Ticker` whose fields default to `nan`. That was diagnosed as
"not waiting long enough" and replaced with `reqTickersAsync`, which genuinely
waits. It still returned `nan`, and the price-drift check stayed dead.

⚠️ The reason, read out of ib_async on 4 September, is that `reqTickersAsync`
issues `reqMktData(..., snapshot=True)` — and IBKR does not serve a delayed
quote to a snapshot request. The wait was never the problem, which is why
lengthening it would have produced another confident fix and another silent log.

Measured on Gateway the same afternoon, a streaming request returned the first
delayed price for five ASX symbols in 0.11s to 0.77s.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter


class _Bus:
    async def publish(self, event: object) -> None:
        return None


class _Ticker:
    def __init__(self, **fields: float) -> None:
        for name in ("bid", "ask", "last"):
            setattr(self, name, fields.get(name, float("nan")))


class _StreamingClient:
    """Records how the quote was asked for, and whether it was let go."""

    def __init__(self, ticker: _Ticker) -> None:
        self._ticker = ticker
        self.stream_calls: list[tuple[Any, ...]] = []
        self.cancelled: list[Any] = []

    def isConnected(self) -> bool:
        return True

    async def reqCurrentTimeAsync(self) -> datetime:
        return datetime.now()

    def reqMktData(self, contract: Any, *args: Any) -> _Ticker:
        self.stream_calls.append((contract,) + args)
        return self._ticker

    def cancelMktData(self, contract: Any) -> None:
        self.cancelled.append(contract)


def _adapter(client: Any) -> IBAdapter:
    return IBAdapter(client, _Bus(), settings=Settings(_env_file=None, market="ASX"))


@pytest.mark.asyncio
async def test_the_quote_is_not_a_snapshot() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. `snapshot=True` returns nan on a
    delayed entitlement no matter how long the caller waits."""
    client = _StreamingClient(_Ticker(bid=62.06, ask=62.08, last=62.07))
    quote = await _adapter(client).get_market_data("BHP.AX")

    assert quote == {"bid": 62.06, "ask": 62.08, "last": 62.07}
    assert len(client.stream_calls) == 1
    snapshot_flag = client.stream_calls[0][2]
    assert snapshot_flag is False, "a snapshot request cannot receive delayed data"


@pytest.mark.asyncio
async def test_the_subscription_is_released_even_when_no_price_arrives() -> None:
    """⚠️ IBKR caps concurrent market data lines. Leaking one per sign-off
    would take the feed down by the same slow path this guard protects."""
    client = _StreamingClient(_Ticker())
    quote = await _adapter(client).get_market_data("BHP.AX")

    assert quote == {}
    assert len(client.cancelled) == 1, "the line must be given back on the empty path too"


@pytest.mark.asyncio
async def test_a_nan_field_is_absent_rather_than_present_and_meaningless() -> None:
    """`{"last": nan}` reads as a quote to every `if quote:` downstream, and
    that is the shape of the original defect - a check that looked answered."""
    client = _StreamingClient(_Ticker(last=float("nan"), bid=62.06))
    quote = await _adapter(client).get_market_data("BHP.AX")

    assert quote == {"bid": 62.06}
    assert "last" not in quote


@pytest.mark.asyncio
async def test_a_zero_price_is_not_a_price() -> None:
    """Zero passes `isfinite` and would size an order against nothing."""
    client = _StreamingClient(_Ticker(last=0.0))
    assert await _adapter(client).get_market_data("BHP.AX") == {}


@pytest.mark.asyncio
async def test_a_client_that_cannot_stream_returns_no_quote() -> None:
    """The fake brokers in the test suite implement `get_market_data` directly
    and have no `reqMktData`; this path must not raise on them."""

    class _NoStreaming(_StreamingClient):
        reqMktData = None  # type: ignore[assignment]

    assert await _adapter(_NoStreaming(_Ticker())).get_market_data("BHP.AX") == {}
