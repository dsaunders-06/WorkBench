"""Double-bottom detector tests for confirmed pivots and first-close crossing."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.double_bottom import evaluate_double_bottom
from qat.domain.strategies.authoritative_swing.indicators import ema
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


def _sessions() -> tuple[date, ...]:
    first = date(2025, 1, 6)
    return tuple(
        first + timedelta(days=week * 7 + weekday) for week in range(51) for weekday in range(5)
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


def _history(
    *,
    first_bottom: int = 230,
    second_bottom: int = 240,
    reversal_trend: bool = False,
) -> tuple[SwingHistory, tuple[date, ...]]:
    sessions = _sessions()
    bars: list[FinalBar] = []
    for index, session in enumerate(sessions[:251]):
        if reversal_trend and index < 220:
            close = D("12") - D(index) * D("0.008")
        elif reversal_trend:
            close = D("10.00") + D(index - 220) * D("0.008")
        else:
            close = D("10") + D(index) / D("1000")
        values = Ohlcv(close - D("0.01"), close + D("0.03"), close - D("0.02"), close, 1000)
        bars.append(_bar(session, index, values))

    for index, low in ((first_bottom, D("9.80")), (second_bottom, D("9.82"))):
        values = Ohlcv(D("10.05"), D("10.10"), low, D("10.02"), 1000)
        bars[index] = _bar(bars[index].session, index, values)

    neckline_indexes = (
        (first_bottom + 4, first_bottom + 5)
        if second_bottom - first_bottom > 5
        else (first_bottom + 1, first_bottom + 2)
    )
    for index in neckline_indexes:
        values = replace(bars[index].adjusted, high=D("10.50"), close=D("10.20"))
        bars[index] = replace(bars[index], raw=values, adjusted=values)

    bars[-2] = replace(
        bars[-2],
        raw=replace(bars[-2].raw, close=D("10.50")),
        adjusted=replace(bars[-2].adjusted, close=D("10.50")),
    )
    preceding_mean = sum(bar.raw.volume for bar in bars[-21:-1]) // 20
    breakout = Ohlcv(D("10.51"), D("10.65"), D("10.48"), D("10.60"), preceding_mean * 3 // 2)
    bars[-1] = _bar(bars[-1].session, 250, breakout)
    return SwingHistory("BHP.AX", tuple(bars)), sessions


def _rule(rules: tuple[RuleEvidence, ...], code: str) -> RuleEvidence:
    return next(rule for rule in rules if rule.code == code)


def _replace_prices(history: SwingHistory, index: int, prices: Ohlcv) -> SwingHistory:
    bars = list(history.daily)
    bars[index] = replace(bars[index], raw=prices, adjusted=prices)
    return SwingHistory(history.symbol, tuple(bars))


def test_confirmed_double_bottom_qualifies_with_tied_neckline_members() -> None:
    history, sessions = _history()

    decision = evaluate_double_bottom(history, sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert decision.candidate is not None
    metadata = dict(decision.candidate.metadata)
    assert metadata["first_bottom"] == history.daily[230].session.isoformat()
    assert metadata["second_bottom"] == history.daily[240].session.isoformat()
    assert metadata["neckline_members"] == (
        f"{history.daily[234].session.isoformat()}:digest-234,"
        f"{history.daily[235].session.isoformat()}:digest-235"
    )
    assert decision.candidate.analytical_invalidation == D("9.82")
    assert decision.candidate.breakout_event_id is not None


def test_three_bars_on_each_side_are_required_for_a_confirmed_low() -> None:
    history, sessions = _history()
    neighbor = history.daily[228]
    prices = replace(neighbor.adjusted, low=D("9.80"))

    decision = evaluate_double_bottom(_replace_prices(history, 228, prices), sessions)

    assert decision.status is DecisionStatus.REJECTED


def test_bottom_spacing_below_five_sessions_is_rejected() -> None:
    history, sessions = _history(first_bottom=236, second_bottom=240)

    decision = evaluate_double_bottom(history, sessions)

    assert decision.status is DecisionStatus.REJECTED


@pytest.mark.parametrize(("first", "second"), [(235, 240), (210, 240)])
def test_five_and_thirty_session_spacing_boundaries_pass(first: int, second: int) -> None:
    history, sessions = _history(first_bottom=first, second_bottom=second)

    decision = evaluate_double_bottom(history, sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert _rule(decision.rules, "bottom_spacing").measured == second - first


def test_bottom_price_distance_over_two_percent_is_rejected() -> None:
    history, sessions = _history()
    second = history.daily[240]
    prices = replace(second.adjusted, low=D("10.10"))

    decision = evaluate_double_bottom(_replace_prices(history, 240, prices), sessions)

    assert decision.status is DecisionStatus.REJECTED


def test_bottom_price_distance_exactly_two_percent_passes() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    for index, low in ((230, D("9.90")), (240, D("10.10"))):
        prices = replace(bars[index].adjusted, low=low)
        bars[index] = replace(bars[index], raw=prices, adjusted=prices)

    decision = evaluate_double_bottom(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert _rule(decision.rules, "bottom_similarity").measured == D("0.02")


def test_breakout_must_be_the_first_completed_close_above_neckline() -> None:
    history, sessions = _history()
    previous = history.daily[-2]
    prices = replace(previous.adjusted, close=D("10.51"), high=D("10.55"))

    decision = evaluate_double_bottom(_replace_prices(history, -2, prices), sessions)

    assert _rule(decision.rules, "first_close_crossing").outcome is RuleOutcome.FAIL


def test_breakout_close_must_be_strictly_above_neckline() -> None:
    history, sessions = _history()
    signal = history.daily[-1]
    prices = replace(signal.adjusted, close=D("10.50"))

    decision = evaluate_double_bottom(_replace_prices(history, -1, prices), sessions)

    assert _rule(decision.rules, "first_close_crossing").outcome is RuleOutcome.FAIL


def test_breakout_after_twenty_sessions_is_expired() -> None:
    history, sessions = _history(first_bottom=219, second_bottom=229)

    decision = evaluate_double_bottom(history, sessions)

    assert _rule(decision.rules, "breakout_expiry").outcome is RuleOutcome.FAIL


def test_breakout_on_twentieth_session_passes_expiry() -> None:
    history, sessions = _history(first_bottom=220, second_bottom=230)

    decision = evaluate_double_bottom(history, sessions)

    assert _rule(decision.rules, "breakout_expiry").outcome is RuleOutcome.PASS
    assert _rule(decision.rules, "breakout_expiry").measured == 20


def test_volume_rule_excludes_breakout_and_zero_volume_abstains() -> None:
    history, sessions = _history()
    decision = evaluate_double_bottom(history, sessions)
    assert _rule(decision.rules, "breakout_volume").measured == D("1.5")

    prior = history.daily[-2]
    zero = replace(prior.adjusted, volume=0)
    abstained = evaluate_double_bottom(_replace_prices(history, -2, zero), sessions)
    assert _rule(abstained.rules, "breakout_volume").outcome is RuleOutcome.ABSTAIN


def test_reversal_does_not_require_ema20_above_ema50() -> None:
    history, sessions = _history(reversal_trend=True)
    closes = tuple(bar.adjusted.close for bar in history.daily)
    assert ema(closes, 20)[-1] is not None
    assert ema(closes, 50)[-1] is not None
    assert ema(closes, 20)[-1] < ema(closes, 50)[-1]  # type: ignore[operator]

    decision = evaluate_double_bottom(history, sessions)

    assert decision.status is DecisionStatus.QUALIFIED
    assert all(rule.code != "daily_ema_trend" for rule in decision.rules)


def test_neckline_depth_must_strictly_exceed_maximum_threshold() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    for index in (234, 235):
        prices = replace(bars[index].adjusted, high=D("9.90"))
        bars[index] = replace(bars[index], raw=prices, adjusted=prices)

    decision = evaluate_double_bottom(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert decision.status is DecisionStatus.REJECTED


def test_most_recent_second_bottom_pair_wins() -> None:
    history, sessions = _history()
    bars = list(history.daily)
    third = bars[244]
    prices = replace(third.adjusted, low=D("9.81"), close=D("10.02"))
    bars[244] = replace(third, raw=prices, adjusted=prices)

    decision = evaluate_double_bottom(SwingHistory("BHP.AX", tuple(bars)), sessions)

    assert decision.candidate is not None
    assert dict(decision.candidate.metadata)["second_bottom"] == bars[244].session.isoformat()


def test_pattern_and_breakout_identities_are_stable() -> None:
    history, sessions = _history()

    left = evaluate_double_bottom(history, sessions)
    right = evaluate_double_bottom(history, sessions)

    assert left.candidate is not None and right.candidate is not None
    assert left.candidate.pattern_instance_id == right.candidate.pattern_instance_id
    assert left.candidate.breakout_event_id == right.candidate.breakout_event_id
