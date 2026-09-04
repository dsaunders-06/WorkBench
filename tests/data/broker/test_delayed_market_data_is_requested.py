"""IBKR answers nothing unless the delayed tier is asked for, and we never asked.

`reqMarketDataType` defaults to 1 (real-time) on every new API connection. This
account has no real-time ASX subscription, so at that tier every quote field
comes back `nan` — and IBKR's blind-trading precaution then refuses the order:

    Error 354: You are trying to submit an order without having market data for
    this instrument.

On 4 September that refused an A2M.AX exit four times in four minutes while the
position sat 0.61R down past its minimum hold, and the app re-issued the same
order every sixty seconds because nothing told it the previous four had failed.

⚠️ THIS WENT UNCAUGHT FOR THREE WEEKS BECAUSE ITS SYMPTOM IS AN ABSENCE.
`IBAdapter.get_market_data`'s docstring records that no `has drifted` line exists
in any log back to 12 August. It diagnosed that as a `reqMktData`/`sleep(0)` bug
and fixed it with `reqTickersAsync`. The fix could not work while the tier was
wrong — and a check that never runs is indistinguishable from a check that runs
and passes, because both leave the log silent. Two weeks later the same symptom
was attributed to a yfinance outage that was real but was not the cause.

So this test asserts the REQUEST, not the quote. A quote can be absent for a
dozen honest reasons; the request either happened or it did not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter


class _RecordingClient:
    """Records the market-data tier it was asked for, if it was asked at all."""

    def __init__(self) -> None:
        self.market_data_types: list[int] = []
        self.connected = False

    def isConnected(self) -> bool:
        return self.connected

    async def connectAsync(self, *args: Any, **kwargs: Any) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    async def reqCurrentTimeAsync(self) -> datetime:
        return datetime.now()

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_types.append(market_data_type)


class _ClientWithoutTierSupport(_RecordingClient):
    """A client that cannot set the tier — the `getattr` fallback path."""

    reqMarketDataType = None  # type: ignore[assignment]


def _adapter(client: Any) -> IBAdapter:
    return IBAdapter(client, _Bus(), settings=Settings(_env_file=None, market="ASX"))


class _Bus:
    async def publish(self, event: object) -> None:
        return None


@pytest.mark.asyncio
async def test_connect_requests_the_delayed_tier() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. Without this call every quote is nan."""
    client = _RecordingClient()
    adapter = _adapter(client)

    await adapter.connect()

    assert client.market_data_types == [3], (
        "IBKR must be asked for the delayed tier (3) on connect. At the default "
        "real-time tier this account has no ASX subscription, so every quote "
        "field returns nan and IBKR refuses orders with error 354."
    )


@pytest.mark.asyncio
async def test_a_client_that_cannot_set_the_tier_says_so_loudly(caplog) -> None:
    """A silent fallback here would recreate the defect: no quotes, no reason."""
    import logging

    adapter = _adapter(_ClientWithoutTierSupport())

    with caplog.at_level(logging.WARNING):
        await adapter.connect()

    assert "market-data type" in caplog.text
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
