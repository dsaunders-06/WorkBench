"""Frozen statistical boundary checks using synthetic decimal outcomes."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from qat.domain.backtester import swing_method_audit as audit
from qat.domain.backtester import swing_statistics as stats
from qat.domain.backtester.swing_results import (
    PostFillResistanceDiagnostic,
    ReplayEquityPoint,
    SwingTrade,
)
from qat.domain.backtester.swing_statistics import (
    ENTRY_MONTH_WCR_S,
    QUARTER_WCR_S,
    InferenceCandidate,
    candidate_cluster_count,
    candidate_eligible,
    romano_wolf_stepdown,
    summarize_swing_statistics,
    wcr_s_mean_test,
    wcr_s_pvalue,
)
from qat.domain.strategies.authoritative_swing.model import Pattern


def _reference_t(months: tuple[tuple[Decimal, ...], ...]) -> float:
    """Independent intercept-only CV1 reference with unequal month sizes."""
    sums = [sum(float(value) for value in month) for month in months]
    counts = [len(month) for month in months]
    total = sum(counts)
    mean = sum(sums) / total
    cluster_scores = [score - count * mean for score, count in zip(sums, counts, strict=True)]
    nonempty = sum(count > 0 for count in counts)
    variance = nonempty / (nonempty - 1)
    variance *= sum(score * score for score in cluster_scores) / total**2
    return mean / variance**0.5


def _reference_pvalue(
    months: tuple[tuple[Decimal, ...], ...], weights: tuple[tuple[int, ...], ...]
) -> Decimal:
    sums = [sum(float(value) for value in month) for month in months]
    counts = [len(month) for month in months]
    total = sum(counts)
    nonempty = sum(count > 0 for count in counts)
    observed = _reference_t(months)
    exceed = 0
    for draw in weights:
        weighted = [weight * score for weight, score in zip(draw, sums, strict=True)]
        total_score = sum(weighted)
        centered = [
            score - count * total_score / total
            for score, count in zip(weighted, counts, strict=True)
        ]
        denominator = (nonempty / (nonempty - 1) * sum(score**2 for score in centered)) ** 0.5
        statistic = total_score / denominator
        exceed += statistic > observed or math.isclose(statistic, observed, rel_tol=1e-12)
    return Decimal(exceed) / Decimal(len(weights))


def test_wcr_s_intercept_reference_and_common_weights() -> None:
    months = (
        (Decimal("1"), Decimal("2")),
        (Decimal("-1"),),
        (Decimal("3"), Decimal("2"), Decimal("1")),
        (Decimal("0"),),
        (Decimal("4"), Decimal("3")),
        (Decimal("-2"),),
        (Decimal("2"), Decimal("1")),
    )
    weights = tuple(
        tuple(-1 if (draw >> month) & 1 else 1 for month in range(len(months)))
        for draw in range(1 << len(months))
    )

    result = wcr_s_mean_test(months, weights=weights)

    assert result.observed_t == pytest.approx(_reference_t(months), rel=1e-12)
    assert result.p_value == _reference_pvalue(months, weights)
    assert result.bootstrap_count == len(weights)
    assert result.nonempty_clusters == 7
    assert Decimal(0) <= result.p_value <= Decimal(1)
    assert result.lower_bound < Decimal("2")


def test_wcr_s_bound_refuses_weight_grid_too_small_for_2_5_percent_inversion() -> None:
    months = tuple((Decimal(value),) for value in (1, 2, -1, 3, 0))
    weights = ((1, 1, 1, 1, 1), (-1, 1, -1, 1, -1))
    with pytest.raises(ValueError, match="2.5%"):
        wcr_s_mean_test(months, weights=weights)


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
    months = tuple((Decimal(value),) for value in (1, 2, -1, 3, 0, 4, -2))
    weights = tuple(
        tuple(-1 if (draw >> month) & 1 else 1 for month in range(7)) for draw in range(128)
    )
    assert wcr_s_pvalue(months, weights=weights) == wcr_s_mean_test(months, weights=weights).p_value


def test_all_positive_bootstrap_draw_counts_as_exact_tie() -> None:
    months = tuple((Decimal(value),) for value in ("0.1", "0.1", "0.4"))
    assert wcr_s_pvalue(months, weights=((1, 1, 1),), draws=1) == Decimal(1)


def test_three_cluster_exact_grid_has_one_eighth_pvalue_floor() -> None:
    months = tuple((Decimal(value),) for value in ("0.1", "0.2", "0.4"))
    result = wcr_s_pvalue(months, draws=8, seed=7)
    assert result == Decimal(1) / Decimal(8)


def test_candidate_eligibility_uses_nonempty_aligned_clusters() -> None:
    months = tuple((Decimal(str(index + 1)),) if index % 3 == 0 else () for index in range(18))
    assert candidate_cluster_count(months, ENTRY_MONTH_WCR_S) == 6
    assert candidate_cluster_count(months, QUARTER_WCR_S) == 6
    assert candidate_cluster_count(months, InferenceCandidate("aligned_block", 6)) == 3
    assert candidate_eligible(months, ENTRY_MONTH_WCR_S)
    assert candidate_eligible(months, QUARTER_WCR_S)
    assert not candidate_eligible(months, InferenceCandidate("aligned_block", 6))
    assert not candidate_eligible(months[:-3], QUARTER_WCR_S)


def test_quarter_candidate_matches_direct_three_month_aggregation() -> None:
    months = tuple((Decimal(str(index % 7 - 2)),) for index in range(18))
    quarters = tuple(
        tuple(value for month in months[start : start + 3] for value in month)
        for start in range(0, len(months), 3)
    )
    assert wcr_s_pvalue(months, candidate=QUARTER_WCR_S, draws=64) == wcr_s_pvalue(
        quarters, draws=64
    )


def test_quarter_candidate_projects_common_month_weights() -> None:
    months = tuple((Decimal(str(index % 7 - 2)),) for index in range(21))
    quarters = tuple(
        tuple(value for month in months[start : start + 3] for value in month)
        for start in range(0, len(months), 3)
    )
    weights = (
        tuple(1 if index % 4 else -1 for index in range(21)),
        tuple(-1 if index % 5 else 1 for index in range(21)),
    )
    quarter_weights = tuple(tuple(row[index] for index in range(0, 21, 3)) for row in weights)
    assert wcr_s_pvalue(months, candidate=QUARTER_WCR_S, weights=weights, draws=2) == (
        wcr_s_pvalue(quarters, weights=quarter_weights, draws=2)
    )


def test_aligned_block_candidate_shares_romano_wolf_path() -> None:
    candidate = InferenceCandidate("aligned_block", 6)
    samples = {
        "first": tuple((Decimal(str(index % 9 - 2)),) for index in range(36)),
        "second": tuple((Decimal(str(index % 7 - 3)),) for index in range(36)),
    }
    blocks = {
        name: tuple(
            tuple(value for month in months[start : start + 6] for value in month)
            for start in range(0, 36, 6)
        )
        for name, months in samples.items()
    }
    candidate_result = romano_wolf_stepdown(samples, candidate=candidate, draws=64)
    direct_result = romano_wolf_stepdown(blocks, draws=64)
    assert candidate_result.adjusted_p_values == direct_result.adjusted_p_values
    assert candidate_result.order == direct_result.order


def test_romano_wolf_all_positive_draw_counts_as_exact_tie() -> None:
    months = tuple((Decimal(value),) for value in ("0.1", "0.1", "0.4"))
    result = romano_wolf_stepdown({"one": months}, weights=((1, 1, 1),), draws=1)
    assert result.adjusted_p_values["one"] == Decimal(1)


def test_six_cluster_exact_floor_reaches_confidence_and_family_gates() -> None:
    months = tuple((Decimal(value),) for value in ("0.1", "0.2", "0.4", "0.5", "0.7", "1.1"))
    assert candidate_eligible(months, ENTRY_MONTH_WCR_S)
    assert wcr_s_pvalue(months, draws=64) == Decimal(1) / Decimal(64)
    family = romano_wolf_stepdown({"one": months}, draws=64)
    assert family.adjusted_p_values["one"] == Decimal(1) / Decimal(64)


def test_holm_stepdown_orders_pvalues_and_matches_hand_calculation() -> None:
    result = stats.holm_stepdown(
        {"third": Decimal("0.20"), "first": Decimal("0.01"), "second": Decimal("0.04")}
    )

    assert result.order == ("first", "second", "third")
    assert result.adjusted_p_values == {
        "first": Decimal("0.03"),
        "second": Decimal("0.08"),
        "third": Decimal("0.20"),
    }


def test_holm_stepdown_ties_are_stable_and_adjustment_is_monotone() -> None:
    result = stats.holm_stepdown({"z": Decimal(1), "b": Decimal("0.02"), "a": Decimal("0.02")})

    assert result.order == ("a", "b", "z")
    assert result.adjusted_p_values == {
        "a": Decimal("0.06"),
        "b": Decimal("0.06"),
        "z": Decimal(1),
    }


def test_holm_candidate_uses_unchanged_exact_wcr_pvalues() -> None:
    candidate = InferenceCandidate("aligned_block", 4, "holm")
    samples = {
        "ema_pullback": tuple((Decimal(str(index % 9 - 2)),) for index in range(36)),
        "bull_flag": tuple((Decimal(str(index % 7 - 3)),) for index in range(36)),
        "double_bottom": tuple((Decimal(str(index % 5 - 2)),) for index in range(36)),
    }

    result = stats.holm_wcr_stepdown(samples, candidate=candidate, draws=9_999)

    assert result.bootstrap_counts == {name: 512 for name in samples}
    assert result.raw_p_values == {
        name: wcr_s_pvalue(months, candidate=candidate, draws=9_999)
        for name, months in samples.items()
    }
    assert all(
        value >= result.raw_p_values[name] for name, value in result.adjusted_p_values.items()
    )


def test_family_dispatch_uses_holm_only_for_declared_candidate() -> None:
    scenario = audit.SyntheticScenario("holm-dispatch", "gaussian", 36, 8, 1, "000", Decimal("0.2"))
    rng = np.random.Generator(np.random.PCG64(91))
    samples = audit._synthetic_months(scenario, rng)
    weights = np.where(rng.integers(0, 2, size=(31, 36)) == 0, -1, 1).tolist()

    holm = stats.family_adjusted_pvalues(
        samples, weights=weights, draws=31, candidate=InferenceCandidate("aligned_block", 4, "holm")
    )
    romano = stats.family_adjusted_pvalues(
        samples, weights=weights, draws=31, candidate=InferenceCandidate("aligned_block", 4)
    )

    assert set(holm.values()) == {Decimal("0.09375")}
    assert set(romano.values()) == {Decimal("0.03125")}


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
