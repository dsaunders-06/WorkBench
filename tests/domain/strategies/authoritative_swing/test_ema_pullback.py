"""EMA20 pullback pattern tests against the frozen Phase 2 rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from qat.domain.strategies.authoritative_swing.ema_pullback import evaluate_ema_pullback
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    Ohlcv,
    RuleEvidence,
    RuleOutcome,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor


def D(value: str | int) -> Decimal:
    return Decimal(value)


def _sessions(weeks: int) -> tuple[date, ...]:
    first = date(2025, 1, 6)
    return tuple(
        first + timedelta(days=week * 7 + weekday)
        for week in range(weeks)
        for weekday in range(5)
    )


def _bar(session: date, close: Decimal, index: int) -> FinalBar:
    open_ = close - D("0.004")
    low = open_ - D("0.008")
    high = close + D("0.002")
    prices = Ohlcv(open_, high, low, close, 10_000 + index)
    return FinalBar(
        symbol="BHP.AX",
        session=session,
        raw=prices,
        adjusted=prices,
        source="fixture",
        quality=DataQuality.VERIFIED,
        adjustment=AdjustmentStatus.SPLIT_NORMALIZED,
        raw_to_adjusted_price_factor=SplitFactor(1, 1),
        finalized=True,
        digest=f"digest-{index}",
    )


def _history(
    *,
    completed_weeks: int = 50,
    weekly_case: str = "bullish",
) -> tuple[SwingHistory, tuple[date, ...]]:
    official = _sessions(completed_weeks + 1)
    observed_count = completed_weeks * 5 + 1
    bars: list[FinalBar] = []
    for index, session in enumerate(official[:observed_count]):
        close = D("10") + D(index) / D("1000")
        if weekly_case == "bearish":
            close = D("12") - D(index) / D("1000")
        elif weekly_case == "dip" and completed_weeks * 5 - 5 <= index < completed_weeks * 5:
            close = D("10.100") + D(index % 5) / D("10000")
        bars.append(_bar(session, close, index))
    return SwingHistory("BHP.AX", tuple(bars)), official


def _replace_signal(
    history: SwingHistory, prices: Ohlcv, *, finalized: bool = True
) -> SwingHistory:
    signal = history.daily[-1]
    replacement = replace(signal, raw=prices, adjusted=prices, finalized=finalized)
    return SwingHistory(history.symbol, (*history.daily[:-1], replacement))


def _rule(decision_rules: tuple[RuleEvidence, ...], code: str) -> RuleEvidence:
    return next(item for item in decision_rules if item.code == code)


def test_exactly_fifty_completed_weeks_can_qualify() -> None:
    history, sessions = _history(completed_weeks=50)

    decision = evaluate_ema_pullback(history, sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert decision.candidate is not None
    assert len(decision.rules) == 9


def test_forty_nine_completed_weeks_abstains() -> None:
    history, sessions = _history(completed_weeks=49)

    decision = evaluate_ema_pullback(history, sessions)

    assert decision.status is DecisionStatus.ABSTAIN
    assert _rule(decision.rules, "weekly_filter").outcome is RuleOutcome.ABSTAIN


def test_wick_exactly_twice_the_body_passes() -> None:
    history, sessions = _history()

    decision = evaluate_ema_pullback(history, sessions)

    assert _rule(decision.rules, "lower_wick").outcome is RuleOutcome.PASS
    assert _rule(decision.rules, "lower_wick").measured == D("2")


def test_close_exactly_at_upper_third_boundary_passes() -> None:
    history, sessions = _history()
    close = history.daily[-1].adjusted.close
    low = close - D("0.012")
    prices = Ohlcv(close - D("0.004"), close + D("0.006"), low, close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert _rule(decision.rules, "upper_third_close").outcome is RuleOutcome.PASS


def test_close_below_upper_third_is_rejected() -> None:
    history, sessions = _history()
    close = history.daily[-1].adjusted.close
    prices = Ohlcv(close - D("0.004"), close + D("0.007"), close - D("0.012"), close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert _rule(decision.rules, "upper_third_close").outcome is RuleOutcome.FAIL


def test_doji_is_rejected_as_flat_geometry() -> None:
    history, sessions = _history()
    close = history.daily[-1].adjusted.close
    prices = Ohlcv(close, close + D("0.01"), close - D("0.01"), close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert decision.status is DecisionStatus.REJECTED
    assert _rule(decision.rules, "positive_geometry").outcome is RuleOutcome.FAIL


def test_ema_touch_is_required() -> None:
    history, sessions = _history()
    close = history.daily[-1].adjusted.close
    prices = Ohlcv(close - D("0.0001"), close + D("0.001"), close - D("0.001"), close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert _rule(decision.rules, "ema_touch").outcome is RuleOutcome.FAIL


def test_touched_ema_that_closes_below_it_is_rejected() -> None:
    history, sessions = _history()
    prior_close = history.daily[-2].adjusted.close
    close = prior_close - D("0.020")
    prices = Ohlcv(close - D("0.001"), close + D("0.002"), close - D("0.006"), close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert _rule(decision.rules, "close_above_ema").outcome is RuleOutcome.FAIL


def test_bullish_close_is_required() -> None:
    history, sessions = _history()
    close = history.daily[-1].adjusted.close
    prices = Ohlcv(close + D("0.001"), close + D("0.003"), close - D("0.012"), close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert _rule(decision.rules, "bullish_close").outcome is RuleOutcome.FAIL


def test_daily_ema20_must_be_above_ema50() -> None:
    history, sessions = _history(weekly_case="bearish")

    decision = evaluate_ema_pullback(history, sessions)

    assert _rule(decision.rules, "daily_ema_trend").outcome is RuleOutcome.FAIL


def test_current_ema20_must_be_above_five_sessions_earlier() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    for offset in range(6):
        index = len(bars) - 1 - offset
        close = D("10.050") - D(offset) / D("1000")
        bars[index] = _bar(bars[index].session, close, index)

    decision = evaluate_ema_pullback(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert _rule(decision.rules, "daily_ema_rising").outcome is RuleOutcome.FAIL


def test_weekly_filter_rejects_only_when_both_clauses_are_bearish() -> None:
    history, sessions = _history(weekly_case="dip")

    decision = evaluate_ema_pullback(history, sessions)

    weekly = _rule(decision.rules, "weekly_filter")
    assert weekly.outcome is RuleOutcome.PASS
    assert weekly.measured == "close_below=True;ema20_below_ema50=False"


def test_weekly_filter_rejects_when_both_clauses_are_bearish() -> None:
    history, sessions = _history(weekly_case="bearish")

    decision = evaluate_ema_pullback(history, sessions)

    assert _rule(decision.rules, "weekly_filter").outcome is RuleOutcome.FAIL


def test_unfinalized_signal_abstains() -> None:
    history, sessions = _history()
    signal = history.daily[-1]

    decision = evaluate_ema_pullback(
        SwingHistory("BHP.AX", (*history.daily[:-1], replace(signal, finalized=False))),
        sessions,
    )

    assert decision.status is DecisionStatus.ABSTAIN


def test_detector_preserves_analytical_invalidation_before_raw_conversion() -> None:
    history, sessions = _history()
    signal = history.daily[-1]
    close = signal.adjusted.close
    prices = Ohlcv(close - D("0.004"), close + D("0.002"), D("1.995"), close, 10_000)

    decision = evaluate_ema_pullback(_replace_signal(history, prices), sessions)

    assert decision.candidate is not None
    assert decision.candidate.analytical_invalidation == D("1.995")
    assert ("signal_digest", signal.digest) in decision.candidate.metadata
    assert ("raw_to_adjusted_price_factor", "1/1") in decision.candidate.metadata
