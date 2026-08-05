from __future__ import annotations

import pytest

from qat.data.fundamentals import FundamentalSnapshot, MockFundamentalsSource


def _snapshot(**overrides: object) -> FundamentalSnapshot:
    base: dict[str, object] = {
        "symbol": "AAPL",
        "sector": "Technology",
        "eps_growth_yoy": None,
        "eps_growth_accelerating": None,
        "peg_ratio": None,
        "roe": None,
        "roic": None,
        "debt_to_equity": None,
        "book_to_market": None,
        "earnings_yield": None,
        "ev_to_ebit": None,
        "fcf_yield": None,
        "dividend_yield": None,
        "dividend_growth_streak_years": None,
        "payout_ratio": None,
        "institutional_ownership_pct": None,
        "relative_strength_rank": None,
    }
    base.update(overrides)
    return FundamentalSnapshot(**base)  # type: ignore[arg-type]


def test_available_figures_omits_what_the_vendor_cannot_answer():
    """A reader given `"roe": null` has to know that means "not published" and
    not "zero". A reader given nothing at all cannot make that mistake."""
    figures = _snapshot(roe=0.31).available_figures()

    assert figures["roe"] == 0.31
    assert "peg_ratio" not in figures
    assert figures["sector"] == "Technology"


def test_available_figures_carries_provenance():
    """A figure's provenance matters at least as much as its value to anything
    reasoning about it."""
    assert _snapshot(roe=0.31, is_synthetic=True).available_figures()["is_synthetic"] is True
    assert _snapshot(roe=0.31).available_figures()["is_synthetic"] is False


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
