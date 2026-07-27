"""Trade-shape, exposure and the assembled summary (spec M23).

Two properties run through all of it. Every metric returns None below the
minimum sample rather than a number, because a figure from three trades is
noise with a decimal point. And a dash is never a zero: "not enough trades to
say" and "measured, and it is zero" are different claims.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.domain.performance.metrics import (
    MIN_TRADES_FOR_STATS,
    average_exposure,
    average_holding_period,
    peak_exposure,
    recovery_factor,
    trades_per_week,
)
from qat.domain.performance.summary import build_summary, format_duration
from qat.domain.performance.trades import ClosedTrade, EquityPoint

BASE = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)


def _trade(
    index: int = 0,
    pnl: float = 100.0,
    held: timedelta = timedelta(hours=6),
    opened: datetime | None = None,
    stop: float | None = 95.0,
) -> ClosedTrade:
    opened_at = opened if opened is not None else BASE + timedelta(days=index)
    entry = 100.0
    return ClosedTrade(
        symbol="AAPL",
        strategy="swing",
        quantity=10.0,
        entry_price=entry,
        exit_price=entry + pnl / 10.0,
        stop_price=stop,
        opened_at=opened_at,
        closed_at=opened_at + held,
    )


def _trades(count: int = 10, **kwargs) -> list[ClosedTrade]:
    return [_trade(index=i, **kwargs) for i in range(count)]


def _points(equities: list[float], cash: list[float] | None = None) -> list[EquityPoint]:
    cash = cash if cash is not None else [e * 0.5 for e in equities]
    return [
        EquityPoint(ts=BASE + timedelta(days=i), equity=e, cash=c)
        for i, (e, c) in enumerate(zip(equities, cash, strict=True))
    ]


# --- holding period ----------------------------------------------------------


def test_the_holding_period_is_the_mean_time_in_a_position():
    trades = _trades(10, held=timedelta(hours=6))

    assert average_holding_period(trades) == timedelta(hours=6)


def test_the_holding_period_averages_across_different_spans():
    trades = [_trade(0, held=timedelta(hours=2)), _trade(1, held=timedelta(hours=10))]
    trades += [_trade(i, held=timedelta(hours=6)) for i in range(2, 6)]

    assert average_holding_period(trades) == timedelta(hours=6)


def test_the_holding_period_is_unavailable_below_the_minimum_sample():
    assert average_holding_period(_trades(MIN_TRADES_FOR_STATS - 1)) is None


def test_durations_render_in_units_a_person_reads():
    """ "0.04 days" tells nobody anything."""
    assert format_duration(timedelta(seconds=45)) == "45s"
    assert format_duration(timedelta(minutes=20)) == "20m"
    assert format_duration(timedelta(hours=6)) == "6.0h"
    assert format_duration(timedelta(days=9)) == "9.0d"
    assert format_duration(None) == "-"


# --- trade frequency ---------------------------------------------------------


def test_trade_frequency_is_measured_against_elapsed_time():
    """A burst in one afternoon must not read like steady daily turnover."""
    trades = [_trade(index=i) for i in range(15)]  # one per day over 14 days

    rate = trades_per_week(trades)

    assert rate == pytest.approx(15 / 2.0, rel=0.01)


def test_trades_closed_in_a_single_instant_have_no_measurable_rate():
    trades = [_trade(0, opened=BASE) for _ in range(10)]

    assert trades_per_week(trades) is None


def test_trade_frequency_is_unavailable_below_the_minimum_sample():
    assert trades_per_week(_trades(MIN_TRADES_FOR_STATS - 1)) is None


# --- recovery factor ---------------------------------------------------------


def test_recovery_factor_is_profit_against_the_drawdown_that_produced_it():
    trades = _trades(10, pnl=100.0)  # +1000 net
    # Peak 100_000, trough 90_000 -> 10% drawdown -> 10_000 of equity.
    points = _points([100_000.0, 90_000.0, 95_000.0])

    assert recovery_factor(trades, points) == pytest.approx(1000.0 / 10_000.0)


def test_recovery_factor_is_unavailable_without_a_drawdown():
    """Dividing by a drawdown of zero would report infinite recovery from a
    curve that has never fallen."""
    trades = _trades(10)
    points = _points([100_000.0, 101_000.0, 102_000.0])

    assert recovery_factor(trades, points) is None


def test_recovery_factor_is_unavailable_below_the_minimum_sample():
    points = _points([100_000.0, 90_000.0])

    assert recovery_factor(_trades(MIN_TRADES_FOR_STATS - 1), points) is None


# --- exposure ----------------------------------------------------------------


def test_exposure_is_the_share_of_equity_not_in_cash():
    points = _points([100.0, 100.0], cash=[20.0, 40.0])

    assert average_exposure(points) == pytest.approx(0.7)
    assert peak_exposure(points) == pytest.approx(0.8)


def test_a_fully_cash_account_has_zero_exposure_not_none():
    """Measured and zero, which is a different claim from unmeasurable."""
    points = _points([100.0, 100.0], cash=[100.0, 100.0])

    assert average_exposure(points) == 0.0


def test_cash_above_equity_reads_as_nothing_invested_not_negative():
    """Arithmetically possible mid-settlement; negative exposure is not a
    thing this application can have, being long-only and unleveraged."""
    points = _points([100.0], cash=[120.0])

    assert average_exposure(points) == 0.0


def test_exposure_is_unavailable_with_no_equity_samples():
    assert average_exposure([]) is None
    assert peak_exposure([]) is None


# --- the assembled summary ---------------------------------------------------


def test_the_summary_surfaces_expectancy_which_was_previously_discarded():
    """It was computed on every refresh and dropped by summary_line()."""
    summary = build_summary(_trades(10, pnl=100.0), _points([100_000.0, 101_000.0]))

    labels = {label: value for label, value, _why in summary.rows()}
    assert labels["Expectancy"] == "$100.00"


def test_the_summary_reports_the_win_to_loss_ratio():
    trades = [_trade(i, pnl=200.0) for i in range(6)] + [
        _trade(i, pnl=-100.0) for i in range(6, 10)
    ]

    summary = build_summary(trades, _points([100_000.0, 101_000.0]))

    assert summary.win_loss_ratio == pytest.approx(2.0)


def test_the_win_loss_ratio_is_unavailable_without_a_loss():
    """A strategy with no losses yet has not proved a ratio, it has just not
    lost yet."""
    summary = build_summary(_trades(10, pnl=100.0), _points([100_000.0]))

    assert summary.win_loss_ratio is None


def test_an_empty_ledger_renders_dashes_rather_than_zeros():
    summary = build_summary([], [])

    values = {label: value for label, value, _why in summary.rows()}
    assert values["Expectancy"] == "-"
    assert values["Holding period"] == "-"
    assert values["Avg exposure"] == "-"
    assert values["Trades"] == "0"  # a count genuinely is zero


def test_every_row_explains_what_it_tells_you():
    """The panel is for judging a strategy, not admiring numbers."""
    summary = build_summary(_trades(10), _points([100_000.0, 99_000.0]))

    for label, _value, why in summary.rows():
        assert why.strip(), f"{label} has no explanation"


def test_the_summary_covers_every_metric_the_screen_promises():
    summary = build_summary(_trades(10), _points([100_000.0, 99_000.0]))

    labels = {label for label, _value, _why in summary.rows()}
    assert {
        "Expectancy",
        "Avg win / avg loss",
        "Average win",
        "Average loss",
        "Holding period",
        "Trades / week",
        "Avg exposure",
        "Peak exposure",
        "Recovery factor",
        "Max drawdown",
        "Sharpe",
    } <= labels


def test_a_rate_is_not_extrapolated_from_minutes():
    """Eight trades closed seconds apart divided out to hundreds of millions
    per week. Guarding only against a zero span let that through."""
    trades = [_trade(0, opened=BASE + timedelta(seconds=i)) for i in range(10)]

    assert trades_per_week(trades) is None


def test_a_rate_is_reported_once_there_is_a_day_of_history():
    trades = [_trade(0, opened=BASE + timedelta(days=i)) for i in range(8)]

    rate = trades_per_week(trades)

    assert rate is not None
    assert rate == pytest.approx(8 / (7 / 7.0), rel=0.01)
