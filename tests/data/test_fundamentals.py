from __future__ import annotations

import pytest

from qat.data.fundamentals import MockFundamentalsSource


@pytest.mark.asyncio
async def test_same_seed_and_symbol_is_deterministic():
    source_a = MockFundamentalsSource(seed=7)
    source_b = MockFundamentalsSource(seed=7)

    snap_a = await source_a.get_fundamentals("AAPL")
    snap_b = await source_b.get_fundamentals("AAPL")

    assert snap_a == snap_b


@pytest.mark.asyncio
async def test_different_symbols_get_different_values():
    source = MockFundamentalsSource(seed=1)

    snap_a = await source.get_fundamentals("AAA")
    snap_b = await source.get_fundamentals("BBB")

    assert snap_a.eps_growth_yoy != snap_b.eps_growth_yoy


@pytest.mark.asyncio
async def test_repeated_calls_for_same_symbol_are_cached_and_stable():
    source = MockFundamentalsSource(seed=1)

    first = await source.get_fundamentals("AAA")
    second = await source.get_fundamentals("AAA")

    assert first == second
