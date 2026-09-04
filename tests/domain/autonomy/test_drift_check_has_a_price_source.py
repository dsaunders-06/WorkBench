"""The price-drift check has never run, because it only ever asked the broker.

`AutonomousExecutor._current_price` asked `broker.get_market_data` and gave up
when it returned nothing. This account has no ASX market-data entitlement, so it
always returns nothing — measured 4 September against live TWS:

    marketDataType = 3          (the delayed tier IS accepted)
    snapshotPermissions = 0
    err 10167: Requested market data is not subscribed.
    ...and not one price field populated, for A2M, BHP or CBA, on either SMART
    or ASX routing, over a streaming subscription held fifteen seconds.

So the check was skipped on every order since 12 August. `_current_price`'s own
docstring records the absence — "No `has drifted` line exists in any log back to
12 August" — diagnoses it as a `reqMktData`/`sleep(0)` bug and fixes it with
`reqTickersAsync`. That fix could not work, and nobody re-checked, because a
check that never runs and one that runs and passes leave identical logs.

⚠️ THE APPLICATION ALREADY HAD A PRICE ALL ALONG. The yfinance feed the sizer
itself used. Falling back to it needs no broker entitlement — and it compares
like with like, because the order was SIZED against that same feed. A quote from
a second vendor would measure the gap between two sources as well as the drift.
"""

from __future__ import annotations

import pytest

from qat.domain.autonomy.executor import AutonomousExecutor


class _NoQuoteBroker:
    """An adapter with no market-data entitlement — this account, exactly."""

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {}


class _OMS:
    def __init__(self) -> None:
        self.broker = _NoQuoteBroker()


def _executor(fallback) -> AutonomousExecutor:  # noqa: ANN001
    return AutonomousExecutor.__new__(AutonomousExecutor)  # type: ignore[return-value]


def _with(fallback) -> AutonomousExecutor:  # noqa: ANN001
    """Build only what `_current_price` touches, so the test pins that method
    rather than the whole construction path."""
    ex = AutonomousExecutor.__new__(AutonomousExecutor)
    ex.oms = _OMS()  # type: ignore[assignment]
    ex._fallback_price = fallback
    return ex


@pytest.mark.asyncio
async def test_the_app_s_own_price_is_used_when_the_broker_has_none() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR."""
    ex = _with(lambda symbol: 6.52)

    price = await ex._current_price("A2M.AX")

    assert price == 6.52, (
        "with no broker entitlement the drift check must fall back to the feed "
        "the order was sized against, not skip itself"
    )


@pytest.mark.asyncio
async def test_no_fallback_still_skips_rather_than_guessing() -> None:
    """Absent is absent. A skipped check is honest; an invented price is not."""
    ex = _with(None)

    assert await ex._current_price("A2M.AX") is None


@pytest.mark.asyncio
async def test_a_nonsense_fallback_is_refused() -> None:
    """Zero, negative and nan are not prices."""
    for bad in (0.0, -1.0, float("nan")):
        assert await _with(lambda symbol, v=bad: v)._current_price("A2M.AX") is None


@pytest.mark.asyncio
async def test_a_raising_fallback_never_stops_the_order() -> None:
    """A price lookup is not permitted to break the order path."""

    def _boom(symbol: str) -> float | None:
        raise RuntimeError("aggregator not ready")

    assert await _with(_boom)._current_price("A2M.AX") is None
