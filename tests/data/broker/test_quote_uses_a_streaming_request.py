"""A snapshot has no delayed tier, so the quote must stream.

This line has been wrong twice. It first called `reqMktData` and yielded ONCE
before reading a `Ticker` whose fields default to `nan`. That was diagnosed as
"not waiting long enough" and replaced with `reqTickersAsync`, which genuinely
waits. It still returned `nan`, and the price-drift check stayed dead.

⚠️ AND THE THIRD DIAGNOSIS WAS WRONG TOO, RETRACTED THE SAME EVENING. This file
said `reqTickersAsync` issues `reqMktData(..., snapshot=True)` and that IBKR
serves no delayed quote to a snapshot. A direct comparison against Gateway
returned IDENTICAL prices from the snapshot and the streaming request - BHP
62.2500 from both - so the snapshot was never the problem either.

⚠️ THE ACTUAL CAUSE: `to_ib_contract` builds a Stock with `conId=0`, and
`reqMktData` RAISES `ValueError` on a conId-less contract. Measured: the
unqualified call raised for BHP.AX and ANZ.AX while the qualified one returned
62.25 and 37.95 in the same run. `_current_price` catches Exception and falls
back, so the failure looked like "the broker has no quote" for weeks.
`probe_halts.py` had carried the warning the whole time - "reqTickers hashes the
contract and a conId-less one raises. The app's own adapter does this" - and the
adapter did not.

Streaming is kept because it is measured to work, not because the snapshot was
proved broken. The 0.11s-0.77s first-tick measurement stands.
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
        self.qualified: list[Any] = []

    async def qualifyContractsAsync(self, contract: Any) -> list[Any]:  # noqa: N802
        self.qualified.append(contract)
        contract.conId = 4391
        return [contract]

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


@pytest.mark.asyncio
async def test_the_contract_is_qualified_before_any_quote_is_asked_for() -> None:
    """⚠️ THE DEFECT THIS FILE WAS WRONG ABOUT FOR A DAY. `to_ib_contract`
    builds a Stock with `conId=0`, and `reqMktData` RAISES on one. Measured
    against Gateway: unqualified raised for BHP.AX and ANZ.AX; qualified
    returned 62.25 and 37.95 in the same run."""
    client = _StreamingClient(_Ticker(last=62.07))
    await _adapter(client).get_market_data("BHP.AX")

    assert len(client.qualified) == 1, "the contract reached reqMktData unqualified"
    assert client.stream_calls[0][0].conId == 4391, "the QUALIFIED contract must be the one used"


@pytest.mark.asyncio
async def test_a_symbol_ibkr_cannot_qualify_yields_no_quote() -> None:
    """No contract, no request - and no exception out of a method whose caller
    treats any failure as 'the broker has no quote'."""

    class _Unqualifiable(_StreamingClient):
        async def qualifyContractsAsync(self, contract: Any) -> list[Any]:  # noqa: N802
            return []

    client = _Unqualifiable(_Ticker(last=62.07))
    assert await _adapter(client).get_market_data("NOPE.AX") == {}
    assert client.stream_calls == []


@pytest.mark.asyncio
async def test_the_conid_is_looked_up_once_per_symbol() -> None:
    """Qualification is a network round trip and a conId does not change
    within a session."""
    client = _StreamingClient(_Ticker(last=62.07))
    adapter = _adapter(client)
    await adapter.get_market_data("BHP.AX")
    await adapter.get_market_data("BHP.AX")

    assert len(client.qualified) == 1
