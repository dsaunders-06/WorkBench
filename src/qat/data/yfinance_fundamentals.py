"""Real company fundamentals via yfinance (spec M18).

Chosen because it is already a dependency serving prices, needs no API key,
and covers ASX as well as US listings. It carries the same caveats as the
price feed - unofficial, rate-limited, and free to change shape without
notice - handled the same way: nothing is assumed, and anything that cannot be
read becomes None rather than a plausible-looking default.

Two traps this module exists to get right, both measured against the live API
rather than inferred from documentation:

  * `dividendYield` is a PERCENT, not a fraction. MSFT comes back as 0.95
    meaning 0.95%. The rest of this codebase uses fractions, so a passthrough
    would render a 0.95% yield as "95.00%" in the Screener and hand strategies
    a figure a hundred times too large.
  * `debtToEquity` is likewise percent-scaled: 30.271 means 0.30. GARP's
    max_debt_to_equity default is 1.5, so an unconverted value would reject
    every real company while appearing to work.

Both are converted here, at the boundary, and both have named regression
tests. A unit error at this seam is invisible downstream: every number stays
numeric and every comparison still runs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from qat.data import sectors
from qat.data.fundamentals import FundamentalSnapshot
from qat.data.relative_strength import RelativeStrengthSource
from qat.data.symbols import to_yfinance

logger = logging.getLogger(__name__)

# Rows on the income statement / balance sheet, named as yfinance labels them.
_EBIT_ROW = "EBIT"
_TAX_RATE_ROW = "Tax Rate For Calcs"
_EPS_ROWS = ("Diluted EPS", "Basic EPS")
_TOTAL_DEBT_ROW = "Total Debt"
_EQUITY_ROW = "Stockholders Equity"
_CASH_ROW = "Cash And Cash Equivalents"

# Below this many annual EPS figures, "accelerating" is not answerable: it
# needs two consecutive growth rates, so three periods.
_MIN_EPS_PERIODS = 3


class TickerLike(Protocol):
    """The slice of yfinance.Ticker this module uses.

    Narrow on purpose so tests drive a fake and never touch the network.
    """

    @property
    def info(self) -> dict[str, Any]: ...
    @property
    def financials(self) -> Any: ...
    @property
    def balance_sheet(self) -> Any: ...
    @property
    def dividends(self) -> Any: ...


class TickerFactory(Protocol):
    def __call__(self, symbol: str) -> TickerLike: ...


def _default_ticker_factory(symbol: str) -> TickerLike:
    import yfinance as yf  # type: ignore[import-untyped]

    # Yahoo writes class shares with a hyphen; the rest of the app uses the
    # broker's dot form. Translating here rather than storing two spellings.
    ticker: TickerLike = yf.Ticker(to_yfinance(symbol))
    return ticker


class YFinanceFundamentalsSource:
    def __init__(
        self,
        ticker_factory: TickerFactory | None = None,
        relative_strength: RelativeStrengthSource | None = None,
    ) -> None:
        self.ticker_factory = ticker_factory or _default_ticker_factory
        self.relative_strength = relative_strength

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        try:
            # yfinance is blocking and does real network I/O; on the Qt thread
            # that would freeze the UI for the length of the call.
            snapshot = await asyncio.to_thread(self._fetch, symbol)
        except Exception:  # noqa: BLE001 - a dead vendor must not stop the app
            logger.warning(
                "Could not fetch fundamentals for %s - every field is unavailable and the "
                "fundamentals strategies will abstain on it",
                symbol,
                exc_info=True,
            )
            return _empty_snapshot(symbol)

        if self.relative_strength is not None:
            rank = await self.relative_strength.rank_for(symbol)
            snapshot = _with_rank(snapshot, rank)
        return snapshot

    def _fetch(self, symbol: str) -> FundamentalSnapshot:
        ticker = self.ticker_factory(symbol)
        info = _safe_info(ticker)
        financials = _safe_frame(ticker, "financials")
        balance_sheet = _safe_frame(ticker, "balance_sheet")
        dividends = _safe_series(ticker, "dividends")

        ebit = _latest_row_value(financials, _EBIT_ROW)

        return FundamentalSnapshot(
            symbol=symbol,
            # Deliberately the curated map, not info["sector"]: yfinance says
            # "Technology" where this codebase says "Information Technology",
            # and the Screener's sector filter is built from the latter.
            sector=sectors.sector_for(symbol),
            eps_growth_yoy=_as_float(info.get("earningsGrowth")),
            eps_growth_accelerating=_eps_accelerating(financials),
            # Item 48. The frame was already here and discarded - only EBIT
            # and the tax rate were taken from it.
            **_reported_kwargs(financials),
            peg_ratio=_positive(_as_float(info.get("trailingPegRatio"))),
            roe=_as_float(info.get("returnOnEquity")),
            roic=_roic(
                ebit, _as_float(_latest_row_value(financials, _TAX_RATE_ROW)), balance_sheet
            ),
            # Percent at source - see the module docstring.
            debt_to_equity=_scale(_as_float(info.get("debtToEquity")), 0.01),
            book_to_market=_reciprocal(_as_float(info.get("priceToBook"))),
            earnings_yield=_reciprocal(_as_float(info.get("trailingPE"))),
            ev_to_ebit=_ratio(_as_float(info.get("enterpriseValue")), _as_float(ebit)),
            fcf_yield=_ratio(_as_float(info.get("freeCashflow")), _as_float(info.get("marketCap"))),
            # Percent at source - see the module docstring.
            dividend_yield=_scale(_as_float(info.get("dividendYield")), 0.01),
            dividend_growth_streak_years=_dividend_streak(dividends),
            payout_ratio=_as_float(info.get("payoutRatio")),
            institutional_ownership_pct=_as_float(info.get("heldPercentInstitutions")),
            # Supplied by the caller-injected ranker, not by the vendor.
            relative_strength_rank=None,
            is_synthetic=False,
        )


# --- vendor access -----------------------------------------------------------


def _safe_info(ticker: TickerLike) -> dict[str, Any]:
    try:
        info = ticker.info
    except Exception:  # noqa: BLE001 - treated as "nothing available"
        return {}
    return info if isinstance(info, dict) else {}


def _safe_frame(ticker: TickerLike, attribute: str) -> Any:
    try:
        return getattr(ticker, attribute)
    except Exception:  # noqa: BLE001
        return None


def _safe_series(ticker: TickerLike, attribute: str) -> Any:
    return _safe_frame(ticker, attribute)


def _latest_row_value(frame: Any, row: str) -> Any:
    """The most recent annual figure for a named statement row.

    yfinance returns statements with periods as columns, newest first.
    """
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        if row not in frame.index:
            return None
        return frame.loc[row].iloc[0]
    except Exception:  # noqa: BLE001 - shape is not guaranteed
        return None


def _eps_row(frame: Any) -> Any:
    """Diluted EPS if reported, else basic - some filings carry only one."""
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        index = frame.index
    except Exception:  # noqa: BLE001 - shape is not guaranteed
        return None
    for row in _EPS_ROWS:
        if row in index:
            return frame.loc[row]
    return None


# --- derivations -------------------------------------------------------------


def _eps_accelerating(financials: Any) -> bool | None:
    """Is the latest EPS growth rate faster than the one before it?

    Needs three annual EPS figures to produce two growth rates. Fewer, and the
    honest answer is "unknown" rather than False - False reads as "checked, and
    it is not accelerating", which would silently fail CAN SLIM's gate for a
    company that might well qualify.
    """
    series = _eps_row(financials)
    if series is None:
        return None
    try:
        values = [float(value) for value in series.tolist()]
    except (TypeError, ValueError):
        return None

    values = [value for value in values if value == value]  # drop NaN
    if len(values) < _MIN_EPS_PERIODS:
        return None

    # Newest first from yfinance; compare the two most recent growth rates.
    latest, previous, earlier = values[0], values[1], values[2]
    if previous <= 0 or earlier <= 0:
        return None
    return (latest - previous) / previous > (previous - earlier) / earlier


def _roic(ebit: Any, tax_rate: float | None, balance_sheet: Any) -> float | None:
    """NOPAT over invested capital.

    yfinance has no ROIC field, but every input is on the statements. Invested
    capital is debt plus equity less cash - cash is not capital the business
    has put to work, and leaving it in flatters a cash-rich company.
    """
    ebit_value = _as_float(ebit)
    if ebit_value is None:
        return None

    debt = _as_float(_latest_row_value(balance_sheet, _TOTAL_DEBT_ROW)) or 0.0
    equity = _as_float(_latest_row_value(balance_sheet, _EQUITY_ROW))
    cash = _as_float(_latest_row_value(balance_sheet, _CASH_ROW)) or 0.0
    if equity is None:
        return None

    invested = debt + equity - cash
    if invested <= 0:
        return None

    effective_tax = tax_rate if tax_rate is not None and 0.0 <= tax_rate < 1.0 else 0.0
    return (ebit_value * (1.0 - effective_tax)) / invested


def _dividend_streak(dividends: Any) -> int | None:
    """Consecutive years of increasing total dividends, most recent backwards.

    The current (incomplete) year is excluded: a part-year total is almost
    always lower than the full year before it, which would read as a broken
    streak every January.
    """
    if dividends is None or len(dividends) == 0:
        return None

    try:
        by_year: dict[int, float] = {}
        for timestamp, amount in dividends.items():
            by_year[timestamp.year] = by_year.get(timestamp.year, 0.0) + float(amount)
    except Exception:  # noqa: BLE001 - shape is not guaranteed
        return None

    if not by_year:
        return None

    years = sorted(by_year)[:-1]  # drop the in-progress year
    if len(years) < 2:
        return None

    streak = 0
    for newer, older in zip(reversed(years), reversed(years[:-1]), strict=False):
        if by_year[newer] > by_year[older]:
            streak += 1
        else:
            break
    return streak


# --- conversions -------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # NaN is yfinance's usual "no data", and it must not propagate: it makes
    # every comparison False, so a gate would silently reject rather than
    # abstain.
    return result if result == result else None


def _positive(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


def _scale(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _reciprocal(value: float | None) -> float | None:
    return None if value is None or value == 0 else 1.0 / value


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _empty_snapshot(symbol: str) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        sector=sectors.sector_for(symbol),
        eps_growth_yoy=None,
        eps_growth_accelerating=None,
        peg_ratio=None,
        roe=None,
        roic=None,
        debt_to_equity=None,
        book_to_market=None,
        earnings_yield=None,
        ev_to_ebit=None,
        fcf_yield=None,
        dividend_yield=None,
        dividend_growth_streak_years=None,
        payout_ratio=None,
        institutional_ownership_pct=None,
        relative_strength_rank=None,
        is_synthetic=False,
    )


def _with_rank(snapshot: FundamentalSnapshot, rank: float | None) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=snapshot.symbol,
        sector=snapshot.sector,
        eps_growth_yoy=snapshot.eps_growth_yoy,
        eps_growth_accelerating=snapshot.eps_growth_accelerating,
        peg_ratio=snapshot.peg_ratio,
        roe=snapshot.roe,
        roic=snapshot.roic,
        debt_to_equity=snapshot.debt_to_equity,
        book_to_market=snapshot.book_to_market,
        earnings_yield=snapshot.earnings_yield,
        ev_to_ebit=snapshot.ev_to_ebit,
        fcf_yield=snapshot.fcf_yield,
        dividend_yield=snapshot.dividend_yield,
        dividend_growth_streak_years=snapshot.dividend_growth_streak_years,
        payout_ratio=snapshot.payout_ratio,
        institutional_ownership_pct=snapshot.institutional_ownership_pct,
        relative_strength_rank=rank,
        is_synthetic=snapshot.is_synthetic,
    )


# Reported results rows, in the order yfinance names them (item 48).
#
# Carried RAW alongside the ratios, because a ratio answers "is this cheap"
# and a result answers "what did the business actually do". The advisory
# context could reason about a P/E and never about "revenue up 8%, profit
# down 3%".
#
# The frame was already being fetched and discarded: `get_fundamentals` pulls
# the whole income statement and takes only EBIT and the tax rate.
_REVENUE_ROWS = ("Total Revenue", "Operating Revenue")
_NET_INCOME_ROWS = ("Net Income", "Net Income Common Stockholders")
_EBITDA_ROWS = ("EBITDA", "Normalized EBITDA")
_EPS_ROWS = ("Diluted EPS", "Basic EPS")


@dataclass(frozen=True, slots=True)
class ReportedResults:
    """What a company actually reported, with the period it covers.

    The period end is not decoration. A growth figure whose period is unknown
    cannot be checked against anything, and this application has been bitten
    repeatedly by numbers that could not be traced to what produced them.
    """

    period_end: date | None = None
    revenue: float | None = None
    net_income: float | None = None
    ebitda: float | None = None
    diluted_eps: float | None = None
    revenue_growth: float | None = None
    net_income_growth: float | None = None


def _first_row(frame: Any, rows: tuple[str, ...], column: int) -> float | None:
    """The first of `rows` the vendor actually answered, in that column.

    yfinance names the same line differently between filers - "Total Revenue"
    and "Operating Revenue" are both revenue - so the alternatives are tried in
    order rather than one being assumed.
    """
    for name in rows:
        try:
            value = frame.loc[name].iloc[column]
        except (KeyError, IndexError):
            continue
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _growth(latest: float | None, prior: float | None) -> float | None:
    """Period-on-period change, or None when it cannot be measured.

    A zero or absent prior yields None rather than a division or a fabricated
    0.0 - the same rule the rest of this module follows, and the reason a
    single-period frame reports figures with no growth rather than inventing
    one.
    """
    if latest is None or not prior:
        return None
    return (latest - prior) / abs(prior)


def reported_results(frame: Any) -> ReportedResults:
    """The latest reported figures and their period, from an income statement.

    Answers `None` per field rather than zero. A row the vendor did not supply
    must not read as a company that earned nothing.
    """
    if frame is None or getattr(frame, "empty", True):
        return ReportedResults()

    columns = list(frame.columns)
    period = columns[0] if columns else None
    period_end: date | None = None
    if period is not None and hasattr(period, "date"):
        period_end = period.date()

    latest_revenue = _first_row(frame, _REVENUE_ROWS, 0)
    latest_income = _first_row(frame, _NET_INCOME_ROWS, 0)
    has_prior = len(columns) > 1
    prior_revenue = _first_row(frame, _REVENUE_ROWS, 1) if has_prior else None
    prior_income = _first_row(frame, _NET_INCOME_ROWS, 1) if has_prior else None

    return ReportedResults(
        period_end=period_end,
        revenue=latest_revenue,
        net_income=latest_income,
        ebitda=_first_row(frame, _EBITDA_ROWS, 0),
        diluted_eps=_first_row(frame, _EPS_ROWS, 0),
        revenue_growth=_growth(latest_revenue, prior_revenue),
        net_income_growth=_growth(latest_income, prior_income),
    )


def _reported_kwargs(frame: Any) -> dict[str, Any]:
    """The reported figures as snapshot kwargs (item 48)."""
    r = reported_results(frame)
    return {
        "results_period_end": r.period_end,
        "revenue": r.revenue,
        "net_income": r.net_income,
        "ebitda": r.ebitda,
        "diluted_eps": r.diluted_eps,
        "revenue_growth": r.revenue_growth,
        "net_income_growth": r.net_income_growth,
    }
