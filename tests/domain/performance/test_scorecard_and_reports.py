"""Metrics, the promotion gate, and reports (spec M16).

The promotion gate is what makes "fine tuned" falsifiable. These tests pin the
two properties that matter most: it refuses to conclude anything from a thin
sample, and it advises rather than acts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.domain.performance.metrics import (
    MIN_TRADES_FOR_STATS,
    compute_stats,
    max_drawdown,
    sharpe_ratio,
)
from qat.domain.performance.reports import (
    build_report,
    summarise_blocked_reasons,
)
from qat.domain.performance.scorecard import build_all_scorecards, build_scorecard
from qat.domain.performance.trades import ClosedTrade, EquityPoint

_BASE = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)


def _trade(
    pnl_per_share: float,
    *,
    strategy: str = "swing",
    stop_distance: float = 5.0,
    quantity: float = 10.0,
    day: int = 0,
) -> ClosedTrade:
    entry = 100.0
    return ClosedTrade(
        symbol="AAA",
        strategy=strategy,
        quantity=quantity,
        entry_price=entry,
        exit_price=entry + pnl_per_share,
        stop_price=entry - stop_distance if stop_distance else None,
        opened_at=_BASE + timedelta(days=day),
        closed_at=_BASE + timedelta(days=day, hours=6),
    )


def _settings(**overrides) -> Settings:
    base = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- Metrics ------------------------------------------------------------------


def test_no_trades_yields_an_empty_but_valid_stats_object():
    stats = compute_stats([])
    assert stats.trade_count == 0
    assert stats.win_rate is None
    assert "No closed trades" in stats.summary_line()


def test_a_thin_sample_reports_counts_but_not_statistics():
    """A win rate from two trades is noise wearing a number's clothes, and a
    gate that accepts it will promote noise."""
    stats = compute_stats([_trade(10.0), _trade(-5.0)])
    assert stats.trade_count == 2
    assert stats.win_rate is None
    assert stats.expectancy is None
    assert stats.profit_factor is None
    assert stats.total_pnl == pytest.approx(50.0)  # counts are still exact


def test_statistics_appear_once_the_sample_is_large_enough():
    trades = [_trade(10.0) for _ in range(4)] + [_trade(-5.0)]
    stats = compute_stats(trades)
    assert stats.trade_count == MIN_TRADES_FOR_STATS
    assert stats.win_rate == pytest.approx(0.8)
    assert stats.average_r == pytest.approx((2.0 * 4 + -1.0) / 5)
    assert stats.profit_factor == pytest.approx(400.0 / 50.0)


def test_trades_without_a_stop_are_excluded_from_average_r_not_counted_as_zero():
    with_r = [_trade(10.0) for _ in range(5)]
    without_r = [_trade(10.0, stop_distance=0.0) for _ in range(5)]

    stats = compute_stats(with_r + without_r)

    assert stats.trade_count == 10
    assert stats.r_trade_count == 5
    assert stats.average_r == pytest.approx(2.0), "the unstopped trades must not dilute it"


def test_profit_factor_is_none_rather_than_infinite_without_a_loss():
    stats = compute_stats([_trade(10.0) for _ in range(6)])
    assert stats.profit_factor is None


def test_max_drawdown_measures_peak_to_trough():
    points = [
        EquityPoint(_BASE, 100_000.0, 0.0),
        EquityPoint(_BASE, 120_000.0, 0.0),
        EquityPoint(_BASE, 90_000.0, 0.0),
        EquityPoint(_BASE, 110_000.0, 0.0),
    ]
    assert max_drawdown(points) == pytest.approx(0.25)


def test_max_drawdown_is_zero_for_a_rising_curve():
    points = [EquityPoint(_BASE, v, 0.0) for v in (100.0, 110.0, 120.0)]
    assert max_drawdown(points) == 0.0


def test_sharpe_is_none_on_a_flat_curve_rather_than_infinite():
    """No variance yet is an absence of evidence, not a perfect result."""
    points = [EquityPoint(_BASE, 100.0, 0.0) for _ in range(20)]
    assert sharpe_ratio(points) is None


def test_sharpe_is_none_without_enough_samples():
    points = [EquityPoint(_BASE, 100.0 + i, 0.0) for i in range(3)]
    assert sharpe_ratio(points) is None


# --- Promotion gate -----------------------------------------------------------


def test_a_strategy_with_no_history_is_not_eligible():
    card = build_scorecard("swing", [], _settings())
    assert card.eligible is False
    assert card.status == "not-eligible"
    assert any("closed trades" in c.detail for c in card.failing)


def test_a_thin_but_profitable_record_is_still_not_eligible():
    """Profitability over five trades is not evidence."""
    card = build_scorecard("swing", [_trade(20.0) for _ in range(5)], _settings())
    assert card.eligible is False


def test_a_strong_record_is_eligible():
    trades = [_trade(10.0) for _ in range(24)] + [_trade(-5.0) for _ in range(8)]
    card = build_scorecard("swing", trades, _settings())
    assert card.eligible is True, card.failing
    assert card.status == "eligible"


def test_a_losing_strategy_is_not_eligible():
    trades = [_trade(-5.0) for _ in range(30)] + [_trade(2.0) for _ in range(5)]
    card = build_scorecard("swing", trades, _settings())
    assert card.eligible is False
    assert any("positive" in c.detail for c in card.failing)


def test_one_catastrophic_loss_blocks_promotion_despite_a_good_average():
    """A good average hides a single trade that could reverse it."""
    trades = [_trade(10.0) for _ in range(34)] + [_trade(-300.0)]
    card = build_scorecard("swing", trades, _settings())
    assert card.eligible is False
    assert any("worst loss" in c.detail for c in card.failing)


def test_a_strategy_with_no_measurable_r_cannot_be_promoted():
    trades = [_trade(10.0, stop_distance=0.0) for _ in range(40)]
    card = build_scorecard("swing", trades, _settings())
    assert card.eligible is False
    assert any("measurable stop" in c.detail for c in card.failing)


def test_a_missing_average_r_says_which_of_the_three_reasons_applies():
    """Telling an operator 'no measurable stop' when every trade has one, and
    the real problem is a four-trade sample, sends them hunting a bug that is
    not there."""
    none_yet = build_scorecard("swing", [], _settings())
    assert any("no closed trades yet" in c.detail for c in none_yet.criteria)

    no_stops = build_scorecard(
        "swing", [_trade(10.0, stop_distance=0.0) for _ in range(10)], _settings()
    )
    assert any(
        "none of the 10 closed trades had a measurable stop" in c.detail for c in no_stops.criteria
    )

    too_few = build_scorecard("swing", [_trade(10.0) for _ in range(3)], _settings())
    detail = next(c.detail for c in too_few.criteria if c.name == "average R")
    assert "too few to average R" in detail
    assert "measurable stop" not in detail


def test_promoted_but_failing_is_its_own_visible_state():
    """The most important row on the screen: trading unattended on a record
    that no longer supports it."""
    card = build_scorecard(
        "swing", [_trade(-5.0) for _ in range(40)], _settings(autonomous_strategies="swing")
    )
    assert card.status == "promoted-below-bar"
    assert "no longer meets the bar" in card.summary_line()


def test_a_promoted_strategy_with_no_trades_still_gets_a_scorecard():
    """It would otherwise be invisible precisely because it has no data."""
    cards = build_all_scorecards({}, _settings(autonomous_strategies="swing"))
    assert [c.strategy for c in cards] == ["swing"]
    assert cards[0].status == "promoted-below-bar"


def test_the_thresholds_are_configurable_and_load_bearing():
    trades = [_trade(10.0) for _ in range(24)] + [_trade(-5.0) for _ in range(8)]
    assert build_scorecard("swing", trades, _settings()).eligible is True
    strict = build_scorecard("swing", trades, _settings(promotion_min_trades=500))
    assert strict.eligible is False


# --- Reports ------------------------------------------------------------------


def test_a_report_renders_without_any_data():
    report = build_report("daily", "Test day", [], [], _BASE.date(), _BASE.date())
    markdown = report.to_markdown()
    assert "No closed trades yet." in markdown
    assert "not sampled this period" in markdown


def test_a_report_covers_only_its_own_period():
    inside = _trade(10.0, day=0)
    outside = _trade(999.0, day=30)
    report = build_report("daily", "Test day", [inside, outside], [], _BASE.date(), _BASE.date())
    assert report.stats.trade_count == 1
    assert report.stats.total_pnl == pytest.approx(100.0)


def test_a_report_breaks_results_down_by_strategy():
    trades = [_trade(10.0, strategy="swing"), _trade(-5.0, strategy="momentum")]
    report = build_report("daily", "Test day", trades, [], _BASE.date(), _BASE.date())
    assert set(report.by_strategy) == {"swing", "momentum"}
    assert "**swing**" in report.to_markdown()


def test_a_report_shows_the_equity_move():
    points = [
        EquityPoint(_BASE, 100_000.0, 0.0),
        EquityPoint(_BASE, 102_000.0, 0.0),
    ]
    report = build_report("daily", "Test day", [], points, _BASE.date(), _BASE.date())
    assert report.equity_change == pytest.approx(2000.0)
    assert report.equity_change_pct == pytest.approx(0.02)
    assert "+2,000.00" in report.to_markdown()


def test_blocked_autonomy_reasons_are_counted_and_grouped():
    """A day with no trades because nothing qualified and a day with no trades
    because a rail stopped eleven candidates are different states."""
    rows = [
        {"outcome": "blocked", "reason": "US market is closed (weekend)"},
        {"outcome": "blocked", "reason": "US market is closed (after close)"},
        {"outcome": "blocked", "reason": "kill-switch active - daily loss"},
        {"outcome": "auto_signed", "reason": "all autonomy preconditions met"},
    ]
    counts = summarise_blocked_reasons(rows)
    assert counts["US market is closed"] == 2
    assert counts["kill-switch active"] == 1
    assert "all autonomy preconditions met" not in counts


def test_a_narrative_is_optional_and_its_absence_is_not_an_error():
    report = build_report("daily", "Test day", [_trade(10.0)], [], _BASE.date(), _BASE.date())
    assert report.narrative is None
    assert "Analyst notes" not in report.to_markdown()
