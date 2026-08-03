"""Portfolio-level risk checks (spec §H, paper §6/§18.1): historical VaR
(95/99%) and Expected Shortfall (97.5%) computed on the combined portfolio
return series - including the candidate - plus single-name and sector
concentration caps.

Correlation is captured by the combined-series math itself rather than a
separate "correlation haircut": summing each position's return series
weighted by its dollar exposure naturally reinforces correlated moves and
partially cancels uncorrelated ones, which is exactly what "size correlated
positions jointly" (spec §H) requires. Factor concentration is out of scope
- no factor-exposure model exists yet, a documented boundary consistent with
prior milestones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from qat.config import Settings

_VAR_CONFIDENCE_95 = 0.95
_VAR_CONFIDENCE_99 = 0.99
_ES_CONFIDENCE = 0.975


def compute_historical_var(returns: pd.Series, confidence: float = _VAR_CONFIDENCE_95) -> float:
    """Empirical VaR as a positive fraction of equity: -1 * the (1-confidence)
    percentile of the return distribution."""
    if len(returns) < 2:
        return 0.0
    percentile = (1.0 - confidence) * 100.0
    return max(0.0, -float(np.percentile(returns, percentile)))


def compute_expected_shortfall(returns: pd.Series, confidence: float = _ES_CONFIDENCE) -> float:
    """Average loss in the tail beyond the VaR threshold (positive fraction)."""
    if len(returns) < 2:
        return 0.0
    var = compute_historical_var(returns, confidence)
    tail = returns[returns <= -var]
    if len(tail) == 0:
        return var
    return max(0.0, -float(tail.mean()))


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PortfolioCheckResult:
    approved: bool
    reason: str
    historical_var_95: float
    historical_var_99: float
    expected_shortfall_975: float
    single_name_pct: float
    sector_pct: float | None


class PortfolioRiskChecker:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or Settings()
        self.es_limit = settings.portfolio_es_limit_pct
        self.max_single_name_pct = settings.max_single_name_concentration_pct
        self.max_sector_pct = settings.max_sector_concentration_pct

    def check(
        self,
        existing_weights: dict[str, float],
        existing_returns: dict[str, pd.Series],
        candidate_symbol: str,
        candidate_dollar_exposure: float,
        candidate_returns: pd.Series,
        total_equity: float,
        candidate_sector: str | None = None,
        sector_by_symbol: dict[str, str] | None = None,
    ) -> PortfolioCheckResult:
        combined_weights = dict(existing_weights)
        combined_weights[candidate_symbol] = (
            combined_weights.get(candidate_symbol, 0.0) + candidate_dollar_exposure
        )
        combined_returns = dict(existing_returns)
        combined_returns[candidate_symbol] = candidate_returns

        portfolio_returns = self._combined_portfolio_returns(
            combined_weights, combined_returns, total_equity
        )
        var_95 = compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_95)
        var_99 = compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_99)
        es_975 = compute_expected_shortfall(portfolio_returns, _ES_CONFIDENCE)

        # Concentration is relative to total equity (NAV), not currently-deployed
        # capital - otherwise a portfolio's very first position is trivially
        # "100% concentrated" simply because nothing else is deployed yet.
        single_name_pct = (
            abs(combined_weights[candidate_symbol]) / total_equity if total_equity > 0 else 0.0
        )

        sector_pct = None
        if candidate_sector and sector_by_symbol:
            sector_gross = sum(
                abs(v)
                for sym, v in combined_weights.items()
                if sector_by_symbol.get(sym) == candidate_sector
            )
            sector_pct = sector_gross / total_equity if total_equity > 0 else 0.0

        def _result(approved: bool, reason: str) -> PortfolioCheckResult:
            return PortfolioCheckResult(
                approved, reason, var_95, var_99, es_975, single_name_pct, sector_pct
            )

        if es_975 > self.es_limit:
            return _result(False, f"Portfolio ES {es_975:.2%} exceeds limit {self.es_limit:.2%}")
        if single_name_pct > self.max_single_name_pct:
            return _result(
                False,
                f"Single-name concentration {single_name_pct:.2%} exceeds "
                f"limit {self.max_single_name_pct:.2%}",
            )
        if sector_pct is not None and sector_pct > self.max_sector_pct:
            return _result(
                False,
                f"Sector concentration {sector_pct:.2%} exceeds limit {self.max_sector_pct:.2%}",
            )

        return _result(True, "within limits")

    @staticmethod
    def _combined_portfolio_returns(
        weights: dict[str, float], returns: dict[str, pd.Series], total_equity: float
    ) -> pd.Series:
        if total_equity <= 0:
            return pd.Series(dtype=float)
        # Duplicate timestamps are dropped, and named when they appear (M38).
        #
        # pandas builds this frame by reindexing every series onto the union of
        # their indexes, and reindexing FROM an index with duplicate labels is
        # an error rather than a warning. Before M33 this function only ever
        # received one series - existing_returns was an empty dict - so the
        # condition could not arise. Feeding it real per-symbol history made it
        # reachable, and on 3 August it raised on every signal for a whole
        # session.
        #
        # Keeping the last observation per timestamp is the right collapse: a
        # repeated timestamp means the same bar was recorded twice, and the
        # later copy is the more complete one.
        usable: dict[str, pd.Series] = {}
        for symbol, raw in returns.items():
            if symbol not in weights or raw is None:
                continue
            # Callers legitimately pass a plain sequence - pandas accepted one
            # here before M38 and several tests rely on it.
            series = raw if isinstance(raw, pd.Series) else pd.Series(raw)
            if series.empty:
                continue
            if series.index.has_duplicates:
                duplicated = int(series.index.duplicated().sum())
                logger.warning(
                    "%s return series has %d duplicate timestamp(s) - keeping the last "
                    "observation of each. A duplicated index here would otherwise fail "
                    "the whole portfolio check and refuse the order.",
                    symbol,
                    duplicated,
                )
                series = series[~series.index.duplicated(keep="last")]
            usable[symbol] = series

        aligned = pd.DataFrame(usable).dropna()
        if aligned.empty:
            return pd.Series(dtype=float)
        weight_fractions = pd.Series(
            {symbol: weights[symbol] / total_equity for symbol in aligned.columns}
        )
        result: pd.Series = aligned.mul(weight_fractions, axis=1).sum(axis=1)
        return result
