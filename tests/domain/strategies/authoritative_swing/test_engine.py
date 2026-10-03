"""Authoritative orchestration, confluence, raw-repeat, and determinism tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from qat.domain.strategies.authoritative_swing.engine import AuthoritativeSwingEngine
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    Ohlcv,
    Pattern,
    PatternCandidate,
    PatternDecision,
    RuleEvidence,
    RuleOutcome,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor
from qat.domain.strategies.authoritative_swing.sizing import (
    LiquidityProfile,
    exact_cost_profile,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


LIQUIDITY = LiquidityProfile("fixture-v1", D("0.10"), D("5"), D("7"))
COSTS = exact_cost_profile("ASX", "fixed")
IDENTITY_FACTOR = SplitFactor(1, 1)


def _history(
    *,
    factor: SplitFactor = IDENTITY_FACTOR,
    peaks: dict[int, str] | None = None,
    future: int = 0,
) -> tuple[SwingHistory, tuple[date, ...], date]:
    peaks = peaks or {}
    first = date(2023, 1, 1)
    bars: list[FinalBar] = []
    for index in range(1101 + future):
        session = first + timedelta(days=index)
        high = D(peaks.get(index, "5"))
        prices = Ohlcv(D("4.5"), high, D("4"), D("4.75"), 100_000)
        bars.append(
            FinalBar(
                symbol="BHP.AX",
                session=session,
                raw=prices,
                adjusted=prices,
                source="fixture",
                quality=DataQuality.VERIFIED,
                adjustment=AdjustmentStatus.SPLIT_NORMALIZED,
                raw_to_adjusted_price_factor=factor,
                finalized=True,
                digest=f"digest-{index}",
            )
        )
    evaluation_session = first + timedelta(days=1100)
    sessions = tuple(first + timedelta(days=index) for index in range(1101 + future))
    return SwingHistory("BHP.AX", tuple(bars)), sessions, evaluation_session


def _decision(
    pattern: Pattern,
    *,
    close: str = "10",
    invalidation: str = "9",
    pattern_id: str | None = None,
    breakout_id: str | None = None,
) -> PatternDecision:
    candidate = PatternCandidate(
        pattern=pattern,
        pattern_instance_id=pattern_id or f"{pattern.value}-instance",
        breakout_event_id=breakout_id,
        signal_session=date(2026, 1, 5),
        analytical_signal_close=D(close),
        analytical_invalidation=D(invalidation),
        analytical_atr14=D("0.5"),
    )
    return PatternDecision(
        pattern,
        DecisionStatus.QUALIFIED,
        (RuleEvidence("fixture", RuleOutcome.PASS),),
        candidate,
    )


def _evaluator(decision: PatternDecision):
    def evaluate(history: SwingHistory, sessions: tuple[date, ...]) -> PatternDecision:
        del history, sessions
        return decision

    return evaluate


def _engine(sessions: tuple[date, ...], *decisions: PatternDecision) -> AuthoritativeSwingEngine:
    return AuthoritativeSwingEngine(sessions, tuple(_evaluator(item) for item in decisions))


def test_confluence_recomputes_with_lowest_limit_and_stop() -> None:
    history, sessions, evaluation_session = _history()
    engine = _engine(
        sessions,
        _decision(Pattern.EMA_PULLBACK, close="10", invalidation="9"),
        _decision(Pattern.BULL_FLAG, close="9.8", invalidation="8.5", breakout_id="flag-cross"),
    )

    decision = engine.evaluate(
        history,
        D("100000"),
        COSTS,
        LIQUIDITY,
        evaluation_session=evaluation_session,
    )

    assert decision.status is DecisionStatus.QUALIFIED
    assert decision.entry_limit_raw == D("9.80")
    assert decision.initial_stop_raw == D("8.49")
    assert decision.patterns == (Pattern.EMA_PULLBACK, Pattern.BULL_FLAG)


def test_repeated_evaluation_is_identical() -> None:
    history, sessions, evaluation_session = _history()
    engine = _engine(sessions, _decision(Pattern.EMA_PULLBACK))

    first = engine.evaluate(
        history, D("100000"), COSTS, LIQUIDITY, evaluation_session=evaluation_session
    )
    second = engine.evaluate(
        history, D("100000"), COSTS, LIQUIDITY, evaluation_session=evaluation_session
    )

    assert first == second


def test_required_data_defect_abstains_but_measured_failures_reject() -> None:
    history, sessions, evaluation_session = _history()
    abstain = PatternDecision(
        Pattern.EMA_PULLBACK,
        DecisionStatus.ABSTAIN,
        (RuleEvidence("data", RuleOutcome.ABSTAIN),),
    )
    rejected = PatternDecision(
        Pattern.BULL_FLAG,
        DecisionStatus.REJECTED,
        (RuleEvidence("geometry", RuleOutcome.FAIL),),
    )

    abstained = _engine(sessions, abstain, rejected).evaluate(
        history, D("100000"), COSTS, LIQUIDITY, evaluation_session=evaluation_session
    )
    failed = _engine(sessions, rejected).evaluate(
        history, D("100000"), COSTS, LIQUIDITY, evaluation_session=evaluation_session
    )

    assert abstained.status is DecisionStatus.ABSTAIN
    assert failed.status is DecisionStatus.REJECTED


def test_analysis_regime_cannot_change_eligibility_or_sizing() -> None:
    history, sessions, evaluation_session = _history()
    engine = _engine(sessions, _decision(Pattern.EMA_PULLBACK))

    bull = engine.evaluate(
        history,
        D("100000"),
        COSTS,
        LIQUIDITY,
        evaluation_session=evaluation_session,
        analysis_regime="bull",
    )
    bear = engine.evaluate(
        history,
        D("100000"),
        COSTS,
        LIQUIDITY,
        evaluation_session=evaluation_session,
        analysis_regime="bear",
    )

    assert (bull.status, bull.entry_limit_raw, bull.initial_stop_raw, bull.quantity) == (
        bear.status,
        bear.entry_limit_raw,
        bear.initial_stop_raw,
        bear.quantity,
    )


def test_raw_tick_repeat_can_reject_an_analytically_clear_path() -> None:
    history, sessions, evaluation_session = _history(peaks={400: "12.001", 800: "12.001"})
    engine = _engine(sessions, _decision(Pattern.EMA_PULLBACK, close="10", invalidation="9"))

    decision = engine.evaluate(
        history,
        D("100000"),
        COSTS,
        LIQUIDITY,
        evaluation_session=evaluation_session,
    )

    assert decision.status is DecisionStatus.REJECTED
    raw_rule = next(rule for rule in decision.setup_rules if rule.code == "raw_resistance")
    assert raw_rule.outcome is RuleOutcome.FAIL


def test_raw_conversion_and_tick_rounding_govern_emitted_prices() -> None:
    history, sessions, evaluation_session = _history(factor=SplitFactor(3, 10))
    engine = _engine(
        sessions,
        _decision(Pattern.EMA_PULLBACK, close="3.0", invalidation="2.7"),
    )

    decision = engine.evaluate(
        history,
        D("100000"),
        COSTS,
        LIQUIDITY,
        evaluation_session=evaluation_session,
    )

    assert decision.entry_limit_raw == D("10")
    assert decision.initial_stop_raw == D("8.99")
    assert decision.structural_invalidation_raw == D("9")


def test_future_bar_mutation_leaves_as_of_decision_identical() -> None:
    history, sessions, evaluation_session = _history(future=10)

    def dynamic(history: SwingHistory, sessions: tuple[date, ...]) -> PatternDecision:
        del sessions
        signal = history.daily[-1]
        return replace(
            _decision(Pattern.EMA_PULLBACK),
            candidate=replace(
                _decision(Pattern.EMA_PULLBACK).candidate,  # type: ignore[arg-type]
                signal_session=signal.session,
            ),
        )

    engine = AuthoritativeSwingEngine(sessions, (dynamic,))
    bars = list(history.daily)
    future = bars[-1]
    changed = replace(future.adjusted, close=D("999"), high=D("1000"))
    bars[-1] = replace(future, raw=changed, adjusted=changed, digest="changed-future")

    left = engine.evaluate(
        history, D("100000"), COSTS, LIQUIDITY, evaluation_session=evaluation_session
    )
    right = engine.evaluate(
        SwingHistory("BHP.AX", tuple(bars)),
        D("100000"),
        COSTS,
        LIQUIDITY,
        evaluation_session=evaluation_session,
    )

    assert left == right


def test_double_bottom_identity_is_retained_in_final_evidence() -> None:
    history, sessions, evaluation_session = _history()
    double = _decision(
        Pattern.DOUBLE_BOTTOM,
        pattern_id="bottom-pair-id",
        breakout_id="crossing-id",
    )

    decision = _engine(sessions, double).evaluate(
        history, D("100000"), COSTS, LIQUIDITY, evaluation_session=evaluation_session
    )

    candidate = decision.pattern_decisions[0].candidate
    assert candidate is not None
    assert candidate.pattern_instance_id == "bottom-pair-id"
    assert candidate.breakout_event_id == "crossing-id"
