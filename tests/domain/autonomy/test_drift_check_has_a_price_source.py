"""DS's 15 October ruling: a bar/feed close is not a current drift quote.

The old fallback let an absent broker quote appear to pass a drift check. A
source-dated broker observation is now required for exposure-adding orders.
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
async def test_the_app_s_own_bar_price_is_not_a_current_quote() -> None:
    ex = _with(lambda symbol: 6.52)

    price = await ex._current_price("A2M.AX")

    assert price is None


@pytest.mark.asyncio
async def test_no_fallback_still_refuses_to_guess() -> None:
    """Absent is absent; _consider refuses an exposure-adding order."""
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
