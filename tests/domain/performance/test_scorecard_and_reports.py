"""Metrics, the promotion gate, and reports (spec M16).

The promotion gate is what makes "fine tuned" falsifiable. These tests pin the
two properties that matter most: it refuses to conclude anything from a thin
sample, and it advises rather than acts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.domain.evaluation.approvals import summarise_approvals
from qat.domain.evaluation.refusals import summarise_refusals
from qat.domain.performance.metrics import (
    MIN_TRADES_FOR_STATS,
    compute_stats,
    max_drawdown,
    sharpe_ratio,
)
from qat.domain.performance.reports import (
    PerformanceReport,
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


def test_blocked_reasons_are_bounded_to_the_reported_period():
    """M56b. Every other section of a report covers the period in its heading;
    this one covered all of history, so a clean day inherited every kill-switch
    and unprotected position the journal had ever recorded."""
    rows = [
        {
            "timestamp": "2026-08-04T14:00:00+00:00",
            "outcome": "blocked",
            "reason": "kill-switch active",
        },
        {
            "timestamp": "2026-08-04T14:01:00+00:00",
            "outcome": "blocked",
            "reason": "protective stop for an unprotected position",
        },
        {
            "timestamp": "2026-08-06T14:00:00+00:00",
            "outcome": "blocked",
            "reason": "already at the 10-position limit",
        },
    ]
    counts = summarise_blocked_reasons(rows, since="2026-08-06", until="2026-08-06")

    assert counts == {"already at the 10-position limit": 1}
    # The specific misreading this exists to stop: a quiet day reporting a
    # kill-switch that fired two days earlier.
    assert "kill-switch active" not in counts


def test_blocked_reasons_without_bounds_still_count_everything():
    """The bounds are opt-in - a caller that does not ask for a period gets the
    whole journal, which is what the weekly and any ad-hoc caller rely on."""
    rows = [
        {
            "timestamp": "2026-08-04T14:00:00+00:00",
            "outcome": "blocked",
            "reason": "kill-switch active",
        },
        {
            "timestamp": "2026-08-06T14:00:00+00:00",
            "outcome": "blocked",
            "reason": "already at the 10-position limit",
        },
    ]
    assert sum(summarise_blocked_reasons(rows).values()) == 2


def test_blocked_reasons_collapse_causes_that_differ_only_in_their_amounts():
    """One cause, not ninety rows. The cost rail quotes the exact dollars at
    risk, so 90 candidates produced 90 distinct keys and 8,907 characters of
    report - which is what pushed the narrative past its context cap."""
    rows = [
        {
            "outcome": "blocked",
            "reason": f"Round-trip cost $18.24 is 13.2% of the ${amount} at risk, "
            "above the 10.0% limit",
        }
        for amount in ("138.38", "138.37", "138.42", "138.30")
    ]
    counts = summarise_blocked_reasons(rows)

    assert len(counts) == 1
    assert next(iter(counts.values())) == 4
    # The position limit keeps its number, because "10-position limit" names the
    # rail rather than quoting a measurement.
    assert summarise_blocked_reasons(
        [{"outcome": "blocked", "reason": "already at the 10-position limit"}]
    ) == {"already at the 10-position limit": 1}


def test_attaching_a_narrative_keeps_every_other_field(qtbot=None):
    """M57b. `_with_narrative` rebuilt the report by listing its fields, and
    the list stopped at `blocked_counts` - so refusals, approvals, opened and
    held silently reverted to their defaults the moment a narrative succeeded.

    It went unnoticed because the narrator had been failing since 4 August on a
    context-size cap, so this path had not run in six reports. M56b shrank the
    report, the narrator came back, and the 7 August daily lost both M51
    sections and its held positions.

    Written over `dataclasses.fields` rather than by naming them, because
    naming them by hand is the defect.
    """
    from dataclasses import fields

    from qat.domain.performance.reporter import _with_narrative

    trade = _trade(10.0)
    report = build_report(
        "daily",
        "Test day",
        [trade],
        [],
        _BASE.date(),
        _BASE.date(),
        blocked_counts={"a reason": 1},
        refusals=summarise_refusals([]),
        approvals=summarise_approvals([], Settings(_env_file=None)),
        open_lots=[],
    )

    carried = _with_narrative(report, "some narrative")

    assert carried.narrative == "some narrative"
    for field in fields(PerformanceReport):
        if field.name == "narrative":
            continue
        assert getattr(carried, field.name) == getattr(
            report, field.name
        ), f"{field.name} was dropped when the narrative was attached"


def test_a_report_with_a_narrative_still_renders_the_evaluation_sections():
    """The symptom as an operator meets it: the sections vanish from the
    written markdown, not merely from an object."""
    from qat.domain.performance.reporter import _with_narrative

    report = build_report(
        "daily",
        "Test day",
        [],
        [],
        _BASE.date(),
        _BASE.date(),
        refusals=summarise_refusals([]),
        approvals=summarise_approvals([], Settings(_env_file=None)),
    )

    markdown = _with_narrative(report, "notes").to_markdown()

    assert "### Why orders did not happen" in markdown
    assert "### What the approvals nearly were" in markdown
    assert "### Analyst notes" in markdown


def test_a_narrative_is_optional_and_its_absence_is_not_an_error():
    report = build_report("daily", "Test day", [_trade(10.0)], [], _BASE.date(), _BASE.date())
    assert report.narrative is None
    assert "Analyst notes" not in report.to_markdown()
