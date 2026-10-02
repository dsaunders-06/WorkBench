"""Bull-flag detector tests for the frozen Phase 2 geometry."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from qat.domain.strategies.authoritative_swing.bull_flag import evaluate_bull_flag
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


def _sessions(weeks: int = 51) -> tuple[date, ...]:
    first = date(2025, 1, 6)
    return tuple(
        first + timedelta(days=week * 7 + weekday)
        for week in range(weeks)
        for weekday in range(5)
    )


def _bar(session: date, index: int, prices: Ohlcv) -> FinalBar:
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


def _history(flag_sessions: int = 8) -> tuple[SwingHistory, tuple[date, ...]]:
    sessions = _sessions()
    observed = sessions[:251]
    bars: list[FinalBar] = []
    for index, session in enumerate(observed):
        close = D("10") + D(index) / D("1000")
        bars.append(
            _bar(
                session,
                index,
                Ohlcv(close - D("0.01"), close + D("0.02"), close - D("0.02"), close, 1000),
            )
        )

    breakout_index = len(bars) - 1
    flag_start = breakout_index - flag_sessions
    pole_start = flag_start - 5
    pole_closes = ("10.20", "10.40", "10.60", "10.80", "11.00")
    for offset, close_text in enumerate(pole_closes):
        index = pole_start + offset
        close = D(close_text)
        open_ = D("10.00") if offset == 0 else close - D("0.10")
        high = D("11.10") if flag_sessions == 3 and offset == 4 else close + D("0.02")
        bars[index] = _bar(
            bars[index].session,
            index,
            Ohlcv(open_, high, open_ - D("0.02"), close, 1200),
        )

    for offset in range(flag_sessions):
        index = flag_start + offset
        close = D("10.98") - D(offset) / D("100")
        bars[index] = _bar(
            bars[index].session,
            index,
            Ohlcv(close + D("0.005"), D("11.02"), close - D("0.05"), close, 800),
        )

    preceding_volume = sum(bar.raw.volume for bar in bars[-21:-1])
    breakout_volume = preceding_volume * 3 // 40
    assert breakout_volume * 20 == preceding_volume * 3 // 2
    bars[-1] = _bar(
        bars[-1].session,
        breakout_index,
        Ohlcv(D("11.00"), D("11.05"), D("10.98"), D("11.03"), breakout_volume),
    )
    return SwingHistory("BHP.AX", tuple(bars)), sessions


def _rule(rules: tuple[RuleEvidence, ...], code: str) -> RuleEvidence:
    return next(rule for rule in rules if rule.code == code)


def _replace_prices(history: SwingHistory, index: int, prices: Ohlcv) -> SwingHistory:
    bars = list(history.daily)
    bars[index] = replace(bars[index], raw=prices, adjusted=prices)
    return SwingHistory(history.symbol, tuple(bars))


def test_eight_session_flag_qualifies_and_longest_window_wins() -> None:
    history, sessions = _history(8)

    decision = evaluate_bull_flag(history, sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert decision.candidate is not None
    assert dict(decision.candidate.metadata)["flag_sessions"] == 8


def test_three_session_flag_boundary_qualifies() -> None:
    history, sessions = _history(3)

    decision = evaluate_bull_flag(history, sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert decision.candidate is not None
    assert dict(decision.candidate.metadata)["flag_sessions"] == 3


def test_breakout_volume_excludes_the_breakout_session() -> None:
    history, sessions = _history()

    decision = evaluate_bull_flag(history, sessions)

    assert _rule(decision.rules, "breakout_volume").measured == D("1.5")


def test_zero_preceding_volume_abstains() -> None:
    history, sessions = _history()
    bar = history.daily[-2]
    prices = replace(bar.adjusted, volume=0)

    decision = evaluate_bull_flag(_replace_prices(history, -2, prices), sessions)

    assert decision.status is DecisionStatus.ABSTAIN
    assert _rule(decision.rules, "breakout_volume").outcome is RuleOutcome.ABSTAIN


def test_flat_flag_slope_passes() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    for index in range(len(bars) - 9, len(bars) - 1):
        prices = bars[index].adjusted
        close = D("10.90")
        values = Ohlcv(close, prices.high, prices.low, close, prices.volume)
        bars[index] = replace(bars[index], raw=values, adjusted=values)

    decision = evaluate_bull_flag(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert _rule(decision.rules, "flag_slope").outcome is RuleOutcome.PASS


def test_positive_flag_slope_fails() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    for offset, index in enumerate(range(len(bars) - 9, len(bars) - 1)):
        close = D("10.80") + D(offset) / D("100")
        values = Ohlcv(close, D("11.02"), close - D("0.05"), close, 800)
        bars[index] = replace(bars[index], raw=values, adjusted=values)

    decision = evaluate_bull_flag(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert _rule(decision.rules, "flag_slope").outcome is RuleOutcome.FAIL


def test_fifty_percent_retracement_boundary_passes() -> None:
    history, sessions = _history()
    flag_bar = history.daily[-2]
    prices = replace(flag_bar.adjusted, low=D("10.50"))

    decision = evaluate_bull_flag(_replace_prices(history, -2, prices), sessions)

    assert _rule(decision.rules, "flag_retracement").outcome is RuleOutcome.PASS


def test_retracement_beyond_fifty_percent_fails() -> None:
    history, sessions = _history()
    flag_bar = history.daily[-2]
    prices = replace(flag_bar.adjusted, low=D("10.499"))

    decision = evaluate_bull_flag(_replace_prices(history, -2, prices), sessions)

    assert _rule(decision.rules, "flag_retracement").outcome is RuleOutcome.FAIL


def test_flag_mean_volume_must_be_strictly_below_pole_mean() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    for index in range(len(bars) - 9, len(bars) - 1):
        prices = replace(bars[index].adjusted, volume=1200)
        bars[index] = replace(bars[index], raw=prices, adjusted=prices)

    decision = evaluate_bull_flag(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert _rule(decision.rules, "flag_volume").outcome is RuleOutcome.FAIL


def test_breakout_must_be_strictly_above_flag_high() -> None:
    history, sessions = _history()
    breakout = history.daily[-1]
    prices = replace(breakout.adjusted, close=D("11.02"))

    decision = evaluate_bull_flag(_replace_prices(history, -1, prices), sessions)

    assert _rule(decision.rules, "breakout_price").outcome is RuleOutcome.FAIL


def test_structural_invalidation_is_the_flag_low() -> None:
    history, sessions = _history()

    decision = evaluate_bull_flag(history, sessions)

    assert decision.candidate is not None
    assert decision.candidate.analytical_invalidation == min(
        bar.adjusted.low for bar in history.daily[-9:-1]
    )
