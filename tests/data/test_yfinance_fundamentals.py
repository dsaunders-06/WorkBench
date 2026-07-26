"""Real fundamentals translation (spec M18), driven by a fake ticker.

The unit conversions are the reason this file exists. A unit error at this
seam produces no exception and no wrong type - every figure stays numeric and
every comparison still evaluates - so it can only be caught by asserting the
converted value against a known input.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.data.yfinance_fundamentals import YFinanceFundamentalsSource

# Measured from the live API, not invented: MSFT's actual shape at the time
# this module was written.
_MSFT_INFO = {
    "earningsGrowth": 0.234,
    "trailingPegRatio": 1.1806,
    "returnOnEquity": 0.34013999,
    "debtToEquity": 30.271,  # percent-scaled at source
    "priceToBook": 6.8433228,
    "trailingPE": 22.73377,
    "freeCashflow": 37_011_251_200,
    "marketCap": 2_835_433_652_224,
    "dividendYield": 0.95,  # percent-scaled at source: 0.95%
    "payoutRatio": 0.20729999,
    "heldPercentInstitutions": 0.76447,
    "enterpriseValue": 2_882_637_398_016,
}

# SPY's actual shape: an index ETF has no earnings, no equity and no owners to
# report, and the vendor correctly returns nothing for them.
_ETF_INFO = {"priceToBook": 1.7215647, "trailingPE": 26.579433, "dividendYield": 1.01}


class FakeTicker:
    def __init__(self, info=None, financials=None, balance_sheet=None, dividends=None) -> None:
        self._info = info if info is not None else {}
        self._financials = financials if financials is not None else pd.DataFrame()
        self._balance_sheet = balance_sheet if balance_sheet is not None else pd.DataFrame()
        self._dividends = dividends if dividends is not None else pd.Series(dtype=float)

    @property
    def info(self):
        return self._info

    @property
    def financials(self):
        return self._financials

    @property
    def balance_sheet(self):
        return self._balance_sheet

    @property
    def dividends(self):
        return self._dividends


def _statements(eps=(6.0, 5.0, 4.0), ebit=100.0, tax=0.21, debt=200.0, equity=800.0, cash=100.0):
    columns = pd.to_datetime(["2025-09-30", "2024-09-30", "2023-09-30"])
    financials = pd.DataFrame(
        {
            columns[0]: [ebit, tax, eps[0]],
            columns[1]: [ebit, tax, eps[1]],
            columns[2]: [ebit, tax, eps[2]],
        },
        index=["EBIT", "Tax Rate For Calcs", "Diluted EPS"],
    )
    balance_sheet = pd.DataFrame(
        {columns[0]: [debt, equity, cash]},
        index=["Total Debt", "Stockholders Equity", "Cash And Cash Equivalents"],
    )
    return financials, balance_sheet


def _source(ticker: FakeTicker) -> YFinanceFundamentalsSource:
    return YFinanceFundamentalsSource(ticker_factory=lambda symbol: ticker)


# --- the two unit traps ------------------------------------------------------


async def test_dividend_yield_is_converted_from_percent_to_a_fraction():
    """0.95 from the vendor means 0.95%, not 95%.

    Passed through unconverted, the Screener would render MSFT's dividend as
    "95.00%" and any yield threshold would be off by a factor of a hundred.
    """
    snapshot = await _source(FakeTicker(info=_MSFT_INFO)).get_fundamentals("MSFT")

    assert snapshot.dividend_yield == pytest.approx(0.0095)


async def test_debt_to_equity_is_converted_from_percent_to_a_ratio():
    """30.271 from the vendor means 0.30, not 30x.

    GARP caps leverage at 1.5. Unconverted, every real company would look
    twenty times over the cap and the strategy would silently never fire.
    """
    snapshot = await _source(FakeTicker(info=_MSFT_INFO)).get_fundamentals("MSFT")

    assert snapshot.debt_to_equity == pytest.approx(0.30271)
    assert snapshot.debt_to_equity < 1.5  # the value GARP actually compares


# --- translation -------------------------------------------------------------


async def test_direct_fields_are_carried_across():
    snapshot = await _source(FakeTicker(info=_MSFT_INFO)).get_fundamentals("MSFT")

    assert snapshot.eps_growth_yoy == pytest.approx(0.234)
    assert snapshot.peg_ratio == pytest.approx(1.1806)
    assert snapshot.roe == pytest.approx(0.34013999)
    assert snapshot.payout_ratio == pytest.approx(0.20729999)
    assert snapshot.institutional_ownership_pct == pytest.approx(0.76447)
    assert snapshot.is_synthetic is False


async def test_derived_ratios_are_computed_from_the_reported_figures():
    snapshot = await _source(FakeTicker(info=_MSFT_INFO)).get_fundamentals("MSFT")

    assert snapshot.book_to_market == pytest.approx(1 / 6.8433228)
    assert snapshot.earnings_yield == pytest.approx(1 / 22.73377)
    assert snapshot.fcf_yield == pytest.approx(37_011_251_200 / 2_835_433_652_224)


async def test_roic_uses_nopat_over_invested_capital_net_of_cash():
    financials, balance_sheet = _statements(
        ebit=100.0, tax=0.25, debt=200.0, equity=800.0, cash=100.0
    )
    ticker = FakeTicker(info=_MSFT_INFO, financials=financials, balance_sheet=balance_sheet)

    snapshot = await _source(ticker).get_fundamentals("MSFT")

    # NOPAT 100 * 0.75 = 75; invested capital 200 + 800 - 100 = 900.
    assert snapshot.roic == pytest.approx(75.0 / 900.0)


async def test_ev_to_ebit_pairs_the_info_field_with_the_statement_row():
    financials, balance_sheet = _statements(ebit=1_000_000.0)
    ticker = FakeTicker(info=_MSFT_INFO, financials=financials, balance_sheet=balance_sheet)

    snapshot = await _source(ticker).get_fundamentals("MSFT")

    assert snapshot.ev_to_ebit == pytest.approx(2_882_637_398_016 / 1_000_000.0)


async def test_eps_acceleration_compares_the_two_most_recent_growth_rates():
    # 4 -> 5 is +25%, 5 -> 8 is +60%: accelerating.
    financials, balance_sheet = _statements(eps=(8.0, 5.0, 4.0))
    accelerating = await _source(
        FakeTicker(info=_MSFT_INFO, financials=financials, balance_sheet=balance_sheet)
    ).get_fundamentals("MSFT")
    assert accelerating.eps_growth_accelerating is True

    # 4 -> 5 is +25%, 5 -> 5.5 is +10%: decelerating.
    financials, balance_sheet = _statements(eps=(5.5, 5.0, 4.0))
    slowing = await _source(
        FakeTicker(info=_MSFT_INFO, financials=financials, balance_sheet=balance_sheet)
    ).get_fundamentals("MSFT")
    assert slowing.eps_growth_accelerating is False


async def test_eps_acceleration_is_unknown_rather_than_false_without_enough_history():
    """False would read as "checked, and it is not accelerating", which fails
    CAN SLIM's gate for a company that might well qualify."""
    columns = pd.to_datetime(["2025-09-30", "2024-09-30"])
    financials = pd.DataFrame({columns[0]: [5.0], columns[1]: [4.0]}, index=["Diluted EPS"])

    snapshot = await _source(FakeTicker(info=_MSFT_INFO, financials=financials)).get_fundamentals(
        "MSFT"
    )

    assert snapshot.eps_growth_accelerating is None


async def test_dividend_streak_counts_consecutive_annual_increases():
    # The final (in-progress) year is excluded, so 2021-2024 is a 3-year streak.
    dividends = pd.Series(
        [1.0, 1.1, 1.2, 1.3, 0.4],
        index=pd.to_datetime(
            ["2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01", "2025-06-01"]
        ),
    )

    snapshot = await _source(FakeTicker(info=_MSFT_INFO, dividends=dividends)).get_fundamentals("T")

    assert snapshot.dividend_growth_streak_years == 3


async def test_a_dividend_cut_ends_the_streak():
    dividends = pd.Series(
        [1.0, 1.5, 0.9, 1.0, 0.4],
        index=pd.to_datetime(
            ["2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01", "2025-06-01"]
        ),
    )

    snapshot = await _source(FakeTicker(info=_MSFT_INFO, dividends=dividends)).get_fundamentals("T")

    assert snapshot.dividend_growth_streak_years == 1  # 2023 -> 2024 only


# --- missing data ------------------------------------------------------------


async def test_an_etf_reports_missing_rather_than_zero():
    """The whole point of M18. An ETF has no ROE - that is a fact about the
    instrument, not a data failure, and it must not read as a ROE of zero."""
    snapshot = await _source(FakeTicker(info=_ETF_INFO)).get_fundamentals("SPY")

    assert snapshot.roe is None
    assert snapshot.roic is None
    assert snapshot.eps_growth_yoy is None
    assert snapshot.peg_ratio is None
    assert snapshot.institutional_ownership_pct is None
    # What an ETF genuinely does have still comes through.
    assert snapshot.book_to_market == pytest.approx(1 / 1.7215647)
    assert snapshot.dividend_yield == pytest.approx(0.0101)


async def test_missing_fields_are_named_by_missing():
    snapshot = await _source(FakeTicker(info=_ETF_INFO)).get_fundamentals("SPY")

    assert set(snapshot.missing("roe", "roic", "book_to_market")) == {"roe", "roic"}


async def test_nan_is_treated_as_missing_not_as_a_number():
    """NaN makes every comparison False, so a gate would silently reject
    instead of abstaining - indistinguishable from a real failure."""
    snapshot = await _source(FakeTicker(info={"returnOnEquity": float("nan")})).get_fundamentals(
        "X"
    )

    assert snapshot.roe is None


async def test_a_zero_price_to_book_does_not_divide_by_zero():
    snapshot = await _source(FakeTicker(info={"priceToBook": 0.0})).get_fundamentals("X")

    assert snapshot.book_to_market is None


async def test_a_dead_vendor_yields_an_all_missing_snapshot_rather_than_raising():
    def explode(symbol: str):
        raise RuntimeError("rate limited")

    source = YFinanceFundamentalsSource(ticker_factory=explode)

    snapshot = await source.get_fundamentals("AAPL")

    assert snapshot.available_fields() == ()
    assert snapshot.is_synthetic is False  # absent, not invented


async def test_sector_comes_from_the_curated_map_not_the_vendor():
    """yfinance says "Technology"; the Screener's filter is built from the
    curated GICS-style names, and a mismatch would silently filter to nothing."""
    ticker = FakeTicker(info={**_MSFT_INFO, "sector": "Technology"})

    snapshot = await _source(ticker).get_fundamentals("MSFT")

    assert snapshot.sector == "Information Technology"


async def test_the_relative_strength_ranker_supplies_the_rank():
    class FakeRanker:
        async def rank_for(self, symbol: str) -> float | None:
            return 87.5

    source = YFinanceFundamentalsSource(
        ticker_factory=lambda symbol: FakeTicker(info=_MSFT_INFO),
        relative_strength=FakeRanker(),
    )

    snapshot = await source.get_fundamentals("MSFT")

    assert snapshot.relative_strength_rank == 87.5


async def test_without_a_ranker_the_rank_is_missing_rather_than_invented():
    snapshot = await _source(FakeTicker(info=_MSFT_INFO)).get_fundamentals("MSFT")

    assert snapshot.relative_strength_rank is None
