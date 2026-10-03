"""Frozen statistical boundary checks using synthetic decimal outcomes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_results import (
    PostFillResistanceDiagnostic,
    ReplayEquityPoint,
    SwingTrade,
)
from qat.domain.backtester.swing_statistics import (
    romano_wolf_stepdown,
    summarize_swing_statistics,
    wcr_s_mean_test,
    wcr_s_pvalue,
)
from qat.domain.strategies.authoritative_swing.model import Pattern


def _reference_t(values: tuple[Decimal, ...]) -> float:
    """Independent equal-cluster CRV3 intercept reference for a small fixture."""
    observations = [float(value) for value in values]
    mean = sum(observations) / len(observations)
    leverage = 1 / len(observations)
    transformed = [(value - mean) / (1 - leverage) for value in observations]
    variance = len(observations) / (len(observations) - 1)
    variance *= sum(score * score for score in transformed) / len(observations) ** 2
    return mean / variance**0.5


def test_wcr_s_intercept_reference_and_common_weights() -> None:
    values = (Decimal("1"), Decimal("2"), Decimal("-1"), Decimal("3"), Decimal("0"))
    months = tuple((value,) for value in values)
    weights = (
        (1, 1, 1, 1, 1),
        (-1, 1, -1, 1, -1),
        (1, -1, -1, 1, 1),
        (-1, -1, 1, -1, 1),
        (1, 1, -1, -1, -1),
    )

    result = wcr_s_mean_test(months, weights=weights)

    assert result.observed_t == pytest.approx(_reference_t(values), rel=1e-12)
    assert result.bootstrap_count == len(weights)
    assert result.nonempty_clusters == 5
    assert Decimal(0) <= result.p_value <= Decimal(1)
    assert result.lower_bound < Decimal("1")


def test_zero_months_remain_in_common_romano_wolf_frame() -> None:
    samples = {
        "ema_pullback": ((Decimal("2"),), (), (Decimal("1"),), (Decimal("3"),)),
        "bull_flag": ((), (Decimal("1"),), (Decimal("1"),), (Decimal("2"),)),
        "double_bottom": ((Decimal("1"),), (Decimal("-1"),), (), (Decimal("2"),)),
    }
    weights = tuple(
        tuple(-1 if (draw >> month) & 1 else 1 for month in range(4)) for draw in range(16)
    )

    result = romano_wolf_stepdown(samples, weights=weights)

    assert set(result.adjusted_p_values) == set(samples)
    assert all(Decimal(0) <= value <= Decimal(1) for value in result.adjusted_p_values.values())
    ordered = result.order
    assert tuple(result.adjusted_p_values[name] for name in ordered) == tuple(
        sorted(result.adjusted_p_values.values())
    )


def test_wcr_s_refuses_zero_trades_and_collapsed_variance() -> None:
    with pytest.raises(ValueError, match="trade"):
        wcr_s_mean_test(((), (), ()))
    with pytest.raises(ValueError, match="variance"):
        wcr_s_mean_test(((Decimal("1"),),) * 4)


def test_pilot_pvalue_uses_same_restricted_test_without_bound_inversion() -> None:
    months = tuple((Decimal(value),) for value in (1, 2, -1, 3, 0))
    weights = tuple(
        tuple(-1 if (draw >> month) & 1 else 1 for month in range(5)) for draw in range(32)
    )
    assert wcr_s_pvalue(months, weights=weights) == wcr_s_mean_test(months, weights=weights).p_value


def test_signal_metrics_use_order_r_and_cash_equity_uses_compounding() -> None:
    first = SwingTrade(
        trade_id="a",
        symbol="AAA.AX",
        patterns=(Pattern.EMA_PULLBACK,),
        entry_session=date(2020, 1, 2),
        exit_session=date(2020, 1, 10),
        quantity=10,
        submitted_limit=Decimal("10"),
        entry_price=Decimal("9.9"),
        exit_price=Decimal("11"),
        initial_stop=Decimal("9"),
        gross_pnl=Decimal("110"),
        eligible_dividends=Decimal(0),
        costs=Decimal("10"),
        net_pnl=Decimal("100"),
        order_initial_risk_dollars=Decimal("100"),
        fill_initial_risk_dollars=Decimal("90"),
        order_r_multiple=Decimal("1"),
        fill_r_multiple=Decimal("1.111111111111"),
        mfe_order_r=Decimal("1.2"),
        mae_order_r=Decimal("-0.2"),
        mfe_fill_r=Decimal("1.3"),
        mae_fill_r=Decimal("-0.2"),
        exit_reason="target",
        observed_triggers=("target",),
        post_fill_resistance=PostFillResistanceDiagnostic.CLEAR,
        analysis_regime="bull",
        edge_sample_eligible=True,
        edge_exclusion_reason=None,
    )
    second = replace(
        first,
        trade_id="b",
        symbol="BBB.AX",
        entry_session=date(2020, 2, 3),
        exit_session=date(2020, 2, 12),
        net_pnl=Decimal("-50"),
        costs=Decimal("15"),
        order_r_multiple=Decimal("-0.5"),
        fill_r_multiple=Decimal("-0.55"),
        analysis_regime="bear",
    )
    suppressed = replace(first, trade_id="c", edge_sample_eligible=False)
    equity = (
        ReplayEquityPoint(
            date(2020, 1, 2), Decimal("10000"), Decimal("9000"), Decimal("1000"), Decimal(0)
        ),
        ReplayEquityPoint(
            date(2020, 1, 10), Decimal("10100"), Decimal("10100"), Decimal(0), Decimal(0)
        ),
        ReplayEquityPoint(
            date(2020, 2, 3), Decimal("10050"), Decimal("9050"), Decimal("1000"), Decimal(0)
        ),
    )

    result = summarize_swing_statistics(
        signal_trades=(first, second, suppressed),
        equity=equity,
        signal_reference_equity=Decimal("10000"),
    )

    assert result.eligible_trades == 2
    assert result.overlap_suppressed_trades == 1
    assert result.mean_r_order == Decimal("0.25")
    assert result.mean_r_fill == Decimal("0.2805555555555")
    assert result.profit_factor == Decimal("2")
    assert result.total_costs == Decimal("25")
    assert result.maximum_drawdown == Decimal("50") / Decimal("10100")
    assert result.symbol_groups["AAA.AX"] == Decimal("1")
    assert result.regime_groups["bear"] == Decimal("-0.5")
