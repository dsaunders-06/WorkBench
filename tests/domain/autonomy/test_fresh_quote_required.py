"""Autonomous exposure addition cannot skip drift when the quote is unusable."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order
from qat.domain.autonomy.executor import AutonomousExecutor


class NoQuoteBroker:
    async def account(self) -> AccountSummary:
        return AccountSummary(100_000, 100_000, 100_000)

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        return {}


@pytest.mark.asyncio
async def test_missing_source_quote_blocks_buy_even_when_bar_fallback_exists() -> None:
    order = Order("BHP.AX", "buy", 9, "approved-id", reference_price=61.86)
    signed: list[str] = []
    journalled: list[tuple[object, ...]] = []

    async def sign_off(order_id: str, operator: str) -> Order:
        signed.append(order_id)
        return order

    def evaluate(*args: object, **kwargs: object) -> object:
        raise AssertionError("drift gate must not run without a current observation")

    executor = AutonomousExecutor.__new__(AutonomousExecutor)
    executor.oms = SimpleNamespace(
        broker=NoQuoteBroker(), get_order=lambda _: order, sign_off=sign_off
    )
    executor.gate = SimpleNamespace(evaluate=evaluate)
    executor.equity_monitor = None
    executor.settings = Settings(_env_file=None)
    executor._fallback_price = lambda symbol: 61.86
    executor._journal = lambda *args: journalled.append(args)  # type: ignore[method-assign]

    await executor._consider(order.order_id)

    assert not signed
    assert journalled
    assert journalled[0][1] == "blocked"
    assert "quote" in str(journalled[0][2]).lower()
