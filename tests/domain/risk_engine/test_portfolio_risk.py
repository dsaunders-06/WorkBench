from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.risk_engine.portfolio_risk import (
    PortfolioRiskChecker,
    compute_expected_shortfall,
    compute_historical_var,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_historical_var_matches_percentile():
    returns = pd.Series([0.01, -0.02, 0.03, -0.05, 0.02, -0.01, 0.04, -0.03, 0.01, -0.04])
    var_95 = compute_historical_var(returns, 0.95)
    assert var_95 == pytest.approx(max(0.0, -returns.quantile(0.05)))


def test_var_increases_at_higher_confidence():
    returns = pd.Series([0.01, -0.02, 0.03, -0.05, 0.02, -0.01, 0.04, -0.03, 0.01, -0.10])
    assert compute_historical_var(returns, 0.99) >= compute_historical_var(returns, 0.95)


def test_expected_shortfall_is_at_least_the_var():
    returns = pd.Series([0.01, -0.02, 0.03, -0.05, 0.02, -0.01, 0.04, -0.03, 0.01, -0.10])
    assert compute_expected_shortfall(returns, 0.975) >= compute_historical_var(returns, 0.975)


def test_var_and_es_zero_for_insufficient_data():
    assert compute_historical_var(pd.Series([0.01])) == 0.0
    assert compute_expected_shortfall(pd.Series([0.01])) == 0.0


def test_check_rejects_when_es_exceeds_limit():
    checker = PortfolioRiskChecker(settings=_settings(portfolio_es_limit_pct=0.01))
    dates = pd.date_range("2024-01-01", periods=30)
    volatile_returns = pd.Series([0.05, -0.06] * 15, index=dates)

    result = checker.check(
        existing_weights={},
        existing_returns={},
        candidate_symbol="AAA",
        candidate_dollar_exposure=50_000.0,
        candidate_returns=volatile_returns,
        total_equity=100_000.0,
    )

    assert result.approved is False
    assert "ES" in result.reason


def test_check_approves_within_limits():
    checker = PortfolioRiskChecker(settings=_settings(portfolio_es_limit_pct=0.50))
    dates = pd.date_range("2024-01-01", periods=30)
    calm_returns = pd.Series([0.001, -0.001] * 15, index=dates)

    result = checker.check(
        existing_weights={},
        existing_returns={},
        candidate_symbol="AAA",
        candidate_dollar_exposure=1_000.0,
        candidate_returns=calm_returns,
        total_equity=100_000.0,
    )

    assert result.approved is True


def test_check_rejects_on_single_name_concentration():
    checker = PortfolioRiskChecker(
        settings=_settings(portfolio_es_limit_pct=0.50, max_single_name_concentration_pct=0.10)
    )
    dates = pd.date_range("2024-01-01", periods=30)
    calm_returns = pd.Series([0.001, -0.001] * 15, index=dates)

    result = checker.check(
        existing_weights={"BBB": 10_000.0},
        existing_returns={"BBB": calm_returns},
        candidate_symbol="AAA",
        candidate_dollar_exposure=50_000.0,
        candidate_returns=calm_returns,
        total_equity=100_000.0,
    )

    assert result.approved is False
    assert "concentration" in result.reason.lower()


def test_check_rejects_on_sector_concentration():
    checker = PortfolioRiskChecker(
        settings=_settings(
            portfolio_es_limit_pct=0.50,
            max_single_name_concentration_pct=0.9,
            max_sector_concentration_pct=0.20,
        )
    )
    dates = pd.date_range("2024-01-01", periods=30)
    calm_returns = pd.Series([0.001, -0.001] * 15, index=dates)

    result = checker.check(
        existing_weights={"BBB": 10_000.0},
        existing_returns={"BBB": calm_returns},
        candidate_symbol="AAA",
        candidate_dollar_exposure=15_000.0,
        candidate_returns=calm_returns,
        total_equity=100_000.0,
        candidate_sector="Technology",
        sector_by_symbol={"BBB": "Technology", "AAA": "Technology"},
    )

    assert result.approved is False
    assert "sector" in result.reason.lower()


def test_correlated_positions_increase_combined_var_vs_uncorrelated():
    checker = PortfolioRiskChecker(settings=_settings(portfolio_es_limit_pct=1.0))
    dates = pd.date_range("2024-01-01", periods=40)
    shared_shock = pd.Series([0.03 if i % 5 == 0 else 0.0 for i in range(40)], index=dates)
    correlated = shared_shock + 0.001
    uncorrelated = pd.Series([0.03 if i % 5 == 2 else 0.0 for i in range(40)], index=dates) + 0.001

    result_correlated = checker.check(
        existing_weights={"BBB": 50_000.0},
        existing_returns={"BBB": correlated},
        candidate_symbol="AAA",
        candidate_dollar_exposure=50_000.0,
        candidate_returns=correlated,
        total_equity=100_000.0,
    )
    result_uncorrelated = checker.check(
        existing_weights={"BBB": 50_000.0},
        existing_returns={"BBB": correlated},
        candidate_symbol="AAA",
        candidate_dollar_exposure=50_000.0,
        candidate_returns=uncorrelated,
        total_equity=100_000.0,
    )

    assert result_correlated.historical_var_95 >= result_uncorrelated.historical_var_95
