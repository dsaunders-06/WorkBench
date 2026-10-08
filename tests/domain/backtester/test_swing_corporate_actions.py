"""Golden corporate-action outcomes for the isolated authoritative replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from qat.domain.backtester.swing_events import (
    CashDividendEvent,
    DelistingEvent,
    SplitEvent,
    SuspensionEvent,
    SwingMarketEvent,
    SymbolChangeEvent,
)
from qat.domain.backtester.swing_fills import AmbiguityPolicy
from qat.domain.backtester.swing_replay import (
    AuthoritativeSwingReplay,
    ReplayCalendarRow,
    SessionKind,
)
from qat.domain.backtester.swing_results import RunStatus, SimulatedFill, SwingReplayResult
from qat.domain.strategies.authoritative_swing.lifecycle import ConfirmedFill
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
    SetupDecision,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor
from qat.domain.strategies.authoritative_swing.resistance import ResistanceZone
from qat.domain.strategies.authoritative_swing.sizing import ExactCostProfile, LiquidityProfile


def D(value: str | int) -> Decimal:
    return Decimal(value)


COSTS = ExactCostProfile("fixture-v1", "fixture", D("0"), D("0"), "AUD", False, D("0"))
LIQUIDITY = LiquidityProfile("fixture-v1", D("1"), D("0"), D("0"))
IDENTITY_FACTOR = SplitFactor(1, 1)


def _bar(
    symbol: str,
    session: date,
    *,
    open_: str = "10",
    high: str = "10.2",
    low: str = "9.5",
    close: str = "10",
    factor: SplitFactor = IDENTITY_FACTOR,
) -> FinalBar:
    raw = Ohlcv(D(open_), D(high), D(low), D(close), 100_000)
    adjusted = Ohlcv(
        raw.open * D(factor.numerator) / D(factor.denominator),
        raw.high * D(factor.numerator) / D(factor.denominator),
        raw.low * D(factor.numerator) / D(factor.denominator),
        raw.close * D(factor.numerator) / D(factor.denominator),
        raw.volume,
    )
    return FinalBar(
        symbol,
        session,
        raw,
        adjusted,
        "fixture",
        DataQuality.VERIFIED,
        AdjustmentStatus.SPLIT_NORMALIZED,
        factor,
        True,
        f"{symbol}-{session.isoformat()}",
    )


def _decision(
    symbol: str,
    session: date,
    *,
    quantity: int = 5,
    stop: str = "9",
    pattern_id: str | None = None,
) -> SetupDecision:
    pattern = Pattern.EMA_PULLBACK
    candidate = PatternCandidate(
        pattern,
        pattern_id or f"pattern-{symbol}-{session}",
        None,
        session,
        D("10"),
        D(stop),
        D("0.5"),
    )
    return SetupDecision(
        "phase2-swing-v1",
        "swing-evidence-v1",
        f"decision-{symbol}-{session}",
        symbol,
        session,
        DecisionStatus.QUALIFIED,
        (pattern,),
        (PatternDecision(pattern, DecisionStatus.QUALIFIED, (), candidate),),
        D("10"),
        D(stop),
        quantity,
        quantity,
        quantity,
        (f"bar-{symbol}-{session}",),
        structural_invalidation_raw=D(stop),
    )


class _FixtureEngine:
    def __init__(
        self,
        decision: SetupDecision,
        later_decisions: Mapping[tuple[str, date], SetupDecision] | None = None,
    ) -> None:
        self.decision = decision
        self.later_decisions = later_decisions or {}

    def evaluate(
        self,
        history: SwingHistory,
        equity: Decimal,
        costs: ExactCostProfile,
        liquidity: LiquidityProfile | None,
        *,
        available_cash: Decimal | None = None,
        analysis_regime: str | None = None,
        evaluation_session: date | None = None,
    ) -> SetupDecision:
        del equity, costs, liquidity, available_cash, analysis_regime
        if history.symbol == self.decision.symbol and evaluation_session == self.decision.session:
            return self.decision
        if evaluation_session is not None:
            later = self.later_decisions.get((history.symbol, evaluation_session))
            if later is not None:
                return later
        return SetupDecision(
            "phase2-swing-v1",
            "swing-evidence-v1",
            f"abstain-{history.symbol}-{evaluation_session}",
            history.symbol,
            evaluation_session or date.min,
            DecisionStatus.ABSTAIN,
            (),
            (),
            None,
            None,
            0,
            0,
            0,
            (),
        )


def _run(
    *,
    bars: tuple[FinalBar, ...] | Mapping[str, tuple[FinalBar, ...]],
    decision: SetupDecision,
    events: tuple[SwingMarketEvent, ...],
    last_session: date | None = None,
    final_entry_session: date | None = None,
    later_decisions: Mapping[tuple[str, date], SetupDecision] | None = None,
) -> SwingReplayResult:
    histories = {decision.symbol: bars} if isinstance(bars, tuple) else dict(bars)
    all_bars = tuple(item for history in histories.values() for item in history)
    first = min(item.session for item in all_bars)
    last = last_session or max(item.session for item in all_bars)
    dates = tuple(first + timedelta(days=offset) for offset in range((last - first).days + 1))
    calendar = tuple(
        ReplayCalendarRow(
            day,
            SessionKind.WEEKEND if day.weekday() >= 5 else SessionKind.FULL,
            "fixture-calendar",
            "weekend" if day.weekday() >= 5 else "normal session",
            f"calendar-{day}",
            True,
        )
        for day in dates
    )
    sessions = tuple(row.calendar_date for row in calendar if row.is_tradable)
    benchmark = tuple(_bar("BENCH.AX", session) for session in sessions)
    return AuthoritativeSwingReplay(
        calendar_rows=calendar,
        bars=histories,
        membership={
            session: frozenset(
                symbol
                for symbol, history in histories.items()
                if any(item.session == session for item in history)
            )
            for session in sessions
        },
        corporate_actions=events,
        benchmark=benchmark,
        engine=_FixtureEngine(decision, later_decisions),
        starting_equity=D("10000"),
        costs=COSTS,
        liquidity=LIQUIDITY,
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE,
        final_entry_session=final_entry_session,
    ).run()


def test_two_for_one_split_preserves_value_and_initial_risk() -> None:
    signal, entry, split, stopped = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars=(
            _bar("AAA.AX", signal, factor=SplitFactor(1, 2)),
            _bar("AAA.AX", entry, factor=SplitFactor(1, 2)),
            _bar("AAA.AX", split, open_="5", high="5.2", low="4.8", close="5"),
            _bar("AAA.AX", stopped, open_="4.4", high="4.6", low="4.2", close="4.4"),
        ),
        decision=_decision("AAA.AX", signal),
        events=(SplitEvent("split-aaa", "AAA.AX", split, 2, 1),),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.side, fill.quantity) for fill in result.fills] == [("buy", 5), ("sell", 10)]
    assert result.equity[1].equity == result.equity[2].equity == D("10000")
    assert result.trades[0].order_initial_risk_dollars == D("5")
    assert result.trades[0].fill_initial_risk_dollars == D("5")
    assert result.trades[0].gross_pnl == D("-6")
    assert result.signal_trades[0].exit_session == stopped
    assert result.signal_trades[0].gross_pnl == D("-6")
    transformation = result.corporate_action_evidence[0]
    assert transformation.event_id == "split-aaa"
    assert (transformation.quantity_before, transformation.quantity_after) == (5, 10)
    assert (transformation.entry_price_before, transformation.entry_price_after) == (
        D("10"),
        D("5"),
    )
    assert (transformation.stop_before, transformation.stop_after) == (D("9"), D("4.5"))
    assert (transformation.target_before, transformation.target_after) == (D("11"), D("5.5"))
    assert result.signal_corporate_action_evidence[0].quantity_after == 10


def test_dividend_accrues_once_then_settles_without_second_pnl() -> None:
    signal, entry, ex_date, stopped, payment = (date(2026, 1, day) for day in (5, 6, 7, 8, 9))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", ex_date),
            _bar("AAA.AX", stopped, open_="9.5", high="9.7", low="8.5", close="9"),
            _bar("AAA.AX", payment),
        ),
        decision=_decision("AAA.AX", signal),
        events=(
            CashDividendEvent(
                "div-aaa", "AAA.AX", ex_date, signal, ex_date, stopped, payment, D("0.20")
            ),
        ),
    )

    assert result.status is RunStatus.VALID
    assert result.equity[2].dividend_receivables == D("1")
    assert result.trades[0].eligible_dividends == D("1")
    assert result.trades[0].net_pnl == D("-4")
    assert result.signal_trades[0].eligible_dividends == D("1")
    assert result.equity[3].equity == result.equity[4].equity
    assert result.equity[4].dividend_receivables == D("0")
    assert result.equity[4].cash == D("9996")
    entitlement = result.dividend_entitlements[0]
    assert entitlement.event_id == "div-aaa"
    assert entitlement.quantity == 5
    assert entitlement.face_value == D("1")
    assert entitlement.position_id == result.position_events[0].position_id
    assert result.signal_dividend_entitlements[0].face_value == D("1")


def test_one_for_two_consolidation_preserves_value_and_risk_dollars() -> None:
    signal, entry, consolidation, stopped = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars=(
            _bar("AAA.AX", signal, factor=SplitFactor(2, 1)),
            _bar("AAA.AX", entry, factor=SplitFactor(2, 1)),
            _bar("AAA.AX", consolidation, open_="20", high="20.4", low="19.2", close="20"),
            _bar("AAA.AX", stopped, open_="17.6", high="18", low="17.4", close="17.6"),
        ),
        decision=_decision("AAA.AX", signal, quantity=8),
        events=(SplitEvent("consolidation-aaa", "AAA.AX", consolidation, 1, 2),),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.side, fill.quantity) for fill in result.fills] == [("buy", 8), ("sell", 4)]
    assert result.equity[1].equity == result.equity[2].equity == D("10000")
    assert result.trades[0].order_initial_risk_dollars == D("8")
    assert result.trades[0].fill_initial_risk_dollars == D("8")


def test_purchase_on_ex_date_has_no_dividend_entitlement() -> None:
    signal, ex_date, stopped, payment = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", ex_date),
            _bar("AAA.AX", stopped, open_="9.5", high="9.7", low="8.5", close="9"),
            _bar("AAA.AX", payment),
        ),
        decision=_decision("AAA.AX", signal),
        events=(
            CashDividendEvent(
                "div-aaa", "AAA.AX", ex_date, signal, ex_date, stopped, payment, D("0.20")
            ),
        ),
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].eligible_dividends == D("0")
    assert result.signal_trades[0].eligible_dividends == D("0")
    assert all(point.dividend_receivables == 0 for point in result.equity)


def test_symbol_change_keeps_the_position_identity_through_exit() -> None:
    signal, entry, renamed, stopped = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars={
            "OLD.AX": (_bar("OLD.AX", signal), _bar("OLD.AX", entry)),
            "NEW.AX": (
                _bar("NEW.AX", renamed),
                _bar("NEW.AX", stopped, open_="8.8", high="9", low="8.5", close="8.8"),
            ),
        },
        decision=_decision("OLD.AX", signal),
        events=(SymbolChangeEvent("rename-old", "OLD.AX", renamed, "NEW.AX"),),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.symbol, fill.side) for fill in result.fills] == [
        ("OLD.AX", "buy"),
        ("NEW.AX", "sell"),
    ]
    assert result.position_events[0].position_id == result.position_events[-1].position_id
    assert result.signal_trades[0].exit_session == stopped
    transformation = result.corporate_action_evidence[0]
    assert (transformation.symbol_before, transformation.symbol_after) == ("OLD.AX", "NEW.AX")
    assert transformation.position_id == result.position_events[0].position_id


def test_suspension_defers_due_invalidation_exit_until_first_resumed_open() -> None:
    sessions: list[date] = []
    cursor = date(2025, 12, 1)
    while len(sessions) < 23:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, suspended, resumed = sessions[19:23]
    result = _run(
        bars=tuple(_bar("AAA.AX", day) for day in sessions[:20])
        + (
            _bar("AAA.AX", entry, open_="10", high="10.2", low="8.5", close="8.8"),
            _bar("AAA.AX", resumed, open_="9.5", high="9.8", low="9.2", close="9.5"),
        ),
        decision=_decision("AAA.AX", signal, stop="8"),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", suspended, resumed),),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.reason, fill.session) for fill in result.fills if fill.side == "sell"] == [
        ("scheduled_open_exit", resumed)
    ]
    assert result.equity[-2].position_value == D("44")
    assert result.equity[-2].stale_marks == (("AAA.AX", D("8.8")),)
    assert result.signal_trades[0].exit_session == resumed


def test_one_day_halt_keeps_last_close_and_does_not_force_exit() -> None:
    signal, entry, halted, resumed = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", resumed),
        ),
        decision=_decision("AAA.AX", signal),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", halted, resumed),),
    )

    assert result.status is RunStatus.VALID
    assert result.equity[2].position_value == D("50")
    assert result.equity[2].stale_marks == (("AAA.AX", D("10")),)
    assert result.equity[3].stale_marks == ()
    assert result.trades == result.signal_trades == ()
    assert sum(item.code == "stale_halt_mark" for item in result.abstentions) == 2


@pytest.mark.parametrize("combined_status", (DecisionStatus.QUALIFIED, DecisionStatus.REJECTED))
def test_isolated_patterns_keep_own_limit_and_stop(
    combined_status: DecisionStatus,
) -> None:
    sessions: list[date] = []
    cursor = date(2025, 12, 1)
    while len(sessions) < 24:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, ema_exit, flag_exit = sessions[20:24]
    first = PatternCandidate(
        Pattern.EMA_PULLBACK,
        "ema-pattern",
        None,
        signal,
        D("10"),
        D("9"),
        D("0.5"),
    )
    second = PatternCandidate(
        Pattern.BULL_FLAG,
        "flag-pattern",
        None,
        signal,
        D("10"),
        D("8.5"),
        D("0.5"),
    )
    base = _decision("AAA.AX", signal)
    combined_decision = replace(
        base,
        status=combined_status,
        patterns=(Pattern.EMA_PULLBACK, Pattern.BULL_FLAG),
        pattern_decisions=(
            PatternDecision(
                Pattern.EMA_PULLBACK,
                DecisionStatus.QUALIFIED,
                (RuleEvidence("analytical_resistance", RuleOutcome.PASS, threshold=D("10")),),
                first,
            ),
            PatternDecision(
                Pattern.BULL_FLAG,
                DecisionStatus.QUALIFIED,
                (RuleEvidence("analytical_resistance", RuleOutcome.PASS, threshold=D("9.5")),),
                second,
            ),
        ),
        entry_limit_raw=D("9.5"),
        initial_stop_raw=D("8.49"),
        structural_invalidation_raw=D("8.5"),
    )
    result = _run(
        bars=tuple(
            _bar("AAA.AX", day, open_="9.4", high="9.6", low="9.2", close="9.4")
            for day in sessions[:20]
        )
        + (
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry, open_="9.4", high="9.5", low="9.1", close="9.4"),
            _bar("AAA.AX", ema_exit, open_="8.8", high="9", low="8.6", close="8.8"),
            _bar("AAA.AX", flag_exit, open_="8.4", high="8.6", low="8.2", close="8.4"),
        ),
        decision=combined_decision,
        events=(),
    )

    assert result.status is RunStatus.VALID
    if combined_status is DecisionStatus.REJECTED:
        assert result.trades == ()
    assert {
        trade.patterns[0]: (trade.submitted_limit, trade.initial_stop, trade.exit_session)
        for trade in result.signal_trades
    } == {
        Pattern.EMA_PULLBACK: (D("10"), D("8.99"), ema_exit),
        Pattern.BULL_FLAG: (D("9.5"), D("8.49"), flag_exit),
    }


def test_isolated_pattern_rechecks_raw_resistance_after_tick_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qat.domain.backtester.swing_replay as replay_module

    sessions: list[date] = []
    cursor = date(2025, 12, 1)
    while len(sessions) < 23:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, stopped = sessions[20:23]
    candidate = PatternCandidate(
        Pattern.EMA_PULLBACK, "ema-raw-gate", None, signal, D("10"), D("9.5"), D("0.5")
    )
    decision = replace(
        _decision("AAA.AX", signal),
        status=DecisionStatus.REJECTED,
        pattern_decisions=(
            PatternDecision(
                Pattern.EMA_PULLBACK,
                DecisionStatus.QUALIFIED,
                (RuleEvidence("analytical_resistance", RuleOutcome.PASS, threshold=D("10")),),
                candidate,
            ),
        ),
    )
    monkeypatch.setattr(
        replay_module,
        "find_resistance_zones",
        lambda _bars: (ResistanceZone(D("11.001"), D("11.1"), ()),),
    )
    result = _run(
        bars=tuple(_bar("AAA.AX", day) for day in sessions[:21])
        + (
            _bar("AAA.AX", entry, open_="9.6", high="9.9", low="9.6", close="9.8"),
            _bar("AAA.AX", stopped, open_="9.3", high="9.5", low="9.1", close="9.3"),
        ),
        decision=decision,
        events=(),
    )

    assert result.status is RunStatus.VALID
    assert result.signal_trades == ()
    assert any(item.code == "raw_resistance" for item in result.abstentions)


def test_isolated_candidate_below_two_shares_has_abstention_evidence() -> None:
    signal, entry = date(2026, 1, 5), date(2026, 1, 6)
    decision = replace(_decision("AAA.AX", signal), capacity_quantity=1)
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=decision,
        events=(),
    )

    assert result.status is RunStatus.VALID
    assert result.signal_trades == ()
    assert any(
        item.code == "isolated_minimum_quantity" and item.measured == 1
        for item in result.abstentions
    )


def test_isolated_pattern_sizes_against_own_terms_and_history() -> None:
    sessions: list[date] = []
    cursor = date(2025, 12, 1)
    while len(sessions) < 23:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, stopped = sessions[20:23]
    candidate = PatternCandidate(
        Pattern.EMA_PULLBACK,
        "ema-pattern",
        None,
        signal,
        D("10"),
        D("9"),
        D("0.5"),
    )
    decision = replace(
        _decision("AAA.AX", signal),
        status=DecisionStatus.REJECTED,
        capacity_quantity=2,
        pattern_decisions=(
            PatternDecision(
                Pattern.EMA_PULLBACK,
                DecisionStatus.QUALIFIED,
                (RuleEvidence("analytical_resistance", RuleOutcome.PASS, threshold=D("10")),),
                candidate,
            ),
        ),
    )
    result = _run(
        bars=tuple(_bar("AAA.AX", day) for day in sessions[:21])
        + (
            _bar("AAA.AX", entry, open_="9.4", high="9.5", low="9.1", close="9.4"),
            _bar("AAA.AX", stopped, open_="8.8", high="9", low="8.6", close="8.8"),
        ),
        decision=decision,
        events=(),
    )

    assert result.status is RunStatus.VALID
    assert len(result.signal_trades) == 1
    assert result.signal_trades[0].quantity > 2
    assert result.signal_trades[0].submitted_limit == D("10")


def test_first_post_halt_close_resumes_invalidation_evaluation() -> None:
    sessions: list[date] = []
    cursor = date(2025, 12, 1)
    while len(sessions) < 24:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, halted, resumed, exit_day = sessions[19:24]
    result = _run(
        bars=tuple(_bar("AAA.AX", day) for day in sessions[:20])
        + (
            _bar("AAA.AX", entry),
            _bar("AAA.AX", resumed, open_="10", high="10.2", low="8.5", close="8.8"),
            _bar("AAA.AX", exit_day, open_="9.5", high="9.8", low="9.2", close="9.5"),
        ),
        decision=_decision("AAA.AX", signal, stop="8"),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", halted, resumed),),
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_session == exit_day
    assert "daily_invalidation" in result.trades[0].observed_triggers
    assert result.signal_trades[0].exit_session == exit_day


def test_delisting_uses_explicit_realizable_proceeds() -> None:
    signal, entry, delisted = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(DelistingEvent("delist-aaa", "AAA.AX", delisted, D("7")),),
        last_session=delisted,
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_reason == "delisting_outcome"
    assert result.trades[0].exit_price == D("7")
    assert result.trades[0].gross_pnl == D("-15")
    assert result.equity[-1].cash == D("9985")
    assert result.signal_trades[0].exit_reason == "delisting_outcome"
    assert result.fills[-1].source_event_id == "delist-aaa"


def test_unresolved_delisting_marks_zero_at_onset_and_closes_once_at_t64() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 65:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, onset = sessions[:3]
    t64 = sessions[64]
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(DelistingEvent("delist-aaa", "AAA.AX", onset, None),),
        last_session=t64,
        final_entry_session=entry,
    )

    assert result.status is RunStatus.VALID
    assert result.equity[1].equity == D("10000")
    assert result.equity[2].equity == D("9950")
    assert result.equity[-1].equity == D("9950")
    assert result.equity[-1].cash == D("9950")
    assert result.trades[0].exit_session == t64
    assert result.trades[0].exit_reason == "terminal_zero"
    assert result.trades[0].gross_pnl == D("-50")
    assert result.signal_trades[0].exit_session == t64
    assert result.fills[-1].source_event_id == "delist-aaa"


def test_unresolved_delisting_without_complete_tail_invalidates_run() -> None:
    signal, entry, onset = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(DelistingEvent("delist-aaa", "AAA.AX", onset, None),),
        last_session=onset,
        final_entry_session=entry,
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("63" in reason for reason in result.invalid_reasons)


def test_halt_spanning_tenth_session_exits_at_first_resumed_open() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 65:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, onset = sessions[:3]
    resumed = sessions[50]
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", resumed, open_="9.5", high="9.8", low="9.2", close="9.5"),
        ),
        decision=_decision("AAA.AX", signal),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", onset, resumed),),
        last_session=sessions[64],
        final_entry_session=entry,
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_session == resumed
    assert result.trades[0].exit_reason == "scheduled_open_exit"
    assert "time_stop" in result.trades[0].observed_triggers
    assert "suspension_exit" not in result.trades[0].observed_triggers
    assert result.equity[2].position_value == D("50")
    assert result.equity[2].stale_marks == (("AAA.AX", D("10")),)
    assert result.signal_trades[0].exit_session == resumed
    assert "time_stop" in result.signal_trades[0].observed_triggers


def test_official_tenth_session_exits_without_available_ema_or_atr() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 12:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    result = _run(
        bars=tuple(_bar("AAA.AX", session) for session in sessions),
        decision=_decision("AAA.AX", sessions[0]),
        events=(),
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_session == sessions[11]
    assert "time_stop" in result.trades[0].observed_triggers
    assert result.signal_trades[0].exit_session == sessions[11]


def test_halt_unresolved_at_t64_keeps_stale_marks_then_exits_at_zero() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 65:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, halted = sessions[:3]
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", halted, None),),
        last_session=sessions[64],
        final_entry_session=entry,
    )

    assert result.status is RunStatus.VALID
    assert result.equity[2].position_value == D("50")
    assert result.equity[2].stale_marks == (("AAA.AX", D("10")),)
    assert result.equity[-2].position_value == D("50")
    assert result.equity[-1].position_value == D("0")
    assert result.trades[0].exit_reason == "terminal_zero"
    assert result.trades[0].exit_session == sessions[64]
    assert result.signal_trades[0].exit_reason == "terminal_zero"


def test_documented_consideration_at_t64_beats_halt_zero_value() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 65:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, halted = sessions[:3]
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(
            SuspensionEvent("halt-aaa", "AAA.AX", halted, None),
            DelistingEvent("consideration-aaa", "AAA.AX", sessions[64], D("7")),
        ),
        last_session=sessions[64],
        final_entry_session=entry,
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_reason == "delisting_outcome"
    assert result.trades[0].exit_price == D("7")
    assert result.signal_trades[0].exit_reason == "delisting_outcome"


def test_gap_through_stop_on_resumption_uses_open_without_forced_halt_exit() -> None:
    signal, entry, halted, resumed = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", resumed, open_="8.5", high="8.8", low="8", close="8.5"),
        ),
        decision=_decision("AAA.AX", signal),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", halted, resumed),),
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_reason == "protective_stop"
    assert result.trades[0].exit_price == D("8.5")
    assert "suspension_exit" not in result.trades[0].observed_triggers
    assert result.signal_trades[0].exit_reason == "protective_stop"


def test_dividend_payment_after_t64_remains_a_receivable_at_face_value() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 66:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, ex_date = sessions[:3]
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", ex_date, open_="8.8", high="9", low="8.5", close="8.8"),
        ),
        decision=_decision("AAA.AX", signal),
        events=(
            CashDividendEvent(
                "div-aaa", "AAA.AX", ex_date, signal, ex_date, ex_date, sessions[65], D("0.20")
            ),
        ),
        last_session=sessions[64],
        final_entry_session=entry,
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].eligible_dividends == D("1")
    assert result.equity[-1].dividend_receivables == D("1")
    assert result.equity[-1].cash == D("9994")
    assert result.equity[-1].equity == D("9995")


def test_multileg_exit_uses_total_net_for_order_r_and_fill_r() -> None:
    sessions: list[date] = []
    cursor = date(2025, 12, 1)
    while len(sessions) < 31:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry, target = sessions[19:22]
    exit_session = sessions[30]
    bars = (
        tuple(_bar("AAA.AX", day) for day in sessions[:20])
        + (
            _bar("AAA.AX", entry, open_="9.8", high="10.2", low="9.6", close="10"),
            _bar("AAA.AX", target, open_="10", high="10.7", low="10", close="10.4"),
        )
        + tuple(
            _bar("AAA.AX", day, open_="10.1", high="10.4", low="9.9", close="10.1")
            for day in sessions[22:30]
        )
        + (_bar("AAA.AX", exit_session, open_="11.4", high="11.5", low="11.2", close="11.4"),)
    )
    result = _run(bars=bars, decision=_decision("AAA.AX", signal, quantity=4), events=())

    assert result.status is RunStatus.VALID
    assert [(fill.reason, fill.quantity) for fill in result.fills if fill.side == "sell"] == [
        ("banked_target", 2),
        ("scheduled_open_exit", 2),
    ]
    assert result.trades[0].gross_pnl == D("4.8")
    assert result.trades[0].fill_r_multiple == D("1.5")
    assert result.trades[0].order_r_multiple == D("1.2")


def test_exit_price_uses_original_share_basis_across_a_split() -> None:
    signal, entry, target, split, delisted = (date(2026, 1, day) for day in (5, 6, 7, 8, 9))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry, open_="10", high="10.5", low="9.5"),
            _bar("AAA.AX", target, open_="10.5", high="11.2", low="10.2", close="10.7"),
            _bar("AAA.AX", split, open_="5.35", high="5.5", low="5.2", close="5.35"),
        ),
        decision=_decision("AAA.AX", signal, quantity=4),
        events=(
            SplitEvent("two-for-one", "AAA.AX", split, 2, 1),
            DelistingEvent("delisted", "AAA.AX", delisted, D("5.5")),
        ),
        last_session=delisted,
    )

    assert result.status is RunStatus.VALID
    assert [(fill.quantity, fill.price) for fill in result.fills if fill.side == "sell"] == [
        (2, D("11")),
        (4, D("5.5")),
    ]
    assert result.trades[0].gross_pnl == D("4")
    assert result.trades[0].entry_price == D("10")
    assert result.trades[0].exit_price == D("11")


def test_signal_only_open_position_missing_bar_invalidates_the_run() -> None:
    first_signal, first_entry, second_signal, second_entry, missing = (
        date(2026, 1, day) for day in (5, 6, 7, 8, 9)
    )
    histories = {
        "AAA.AX": tuple(
            _bar("AAA.AX", session)
            for session in (first_signal, first_entry, second_signal, second_entry, missing)
        ),
        "BBB.AX": (
            _bar("BBB.AX", second_signal),
            _bar("BBB.AX", second_entry),
        ),
    }
    result = _run(
        bars=histories,
        decision=_decision("AAA.AX", first_signal, quantity=999),
        later_decisions={("BBB.AX", second_signal): _decision("BBB.AX", second_signal, quantity=5)},
        events=(),
        last_session=missing,
    )

    assert result.status is RunStatus.INVALID
    assert result.trades == ()
    assert any("missing signal position mark" in reason for reason in result.invalid_reasons)


def test_fully_spent_portfolio_still_records_later_isolated_signal() -> None:
    first_signal, first_entry, second_signal, second_entry = (
        date(2026, 1, day) for day in (5, 6, 7, 8)
    )
    result = _run(
        bars={
            "AAA.AX": tuple(
                _bar("AAA.AX", session)
                for session in (first_signal, first_entry, second_signal, second_entry)
            ),
            "BBB.AX": (
                _bar("BBB.AX", second_signal),
                _bar("BBB.AX", second_entry),
            ),
        },
        decision=_decision("AAA.AX", first_signal, quantity=1000),
        later_decisions={("BBB.AX", second_signal): _decision("BBB.AX", second_signal, quantity=5)},
        events=(),
    )

    assert result.status is RunStatus.VALID
    assert any(
        decision.symbol == "BBB.AX" and decision.status is DecisionStatus.QUALIFIED
        for decision in result.signal_decisions
    )


def test_fractional_consolidation_without_cash_in_lieu_invalidates_run() -> None:
    signal, entry, consolidation = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", consolidation, open_="20", high="20.4", low="19", close="20"),
        ),
        decision=_decision("AAA.AX", signal, quantity=5),
        events=(SplitEvent("reverse-aaa", "AAA.AX", consolidation, 1, 2),),
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("fractional" in reason for reason in result.invalid_reasons)


def test_traded_bar_during_signed_suspension_invalidates_before_replay() -> None:
    signal, entry, suspended, resumed = (date(2026, 1, day) for day in (5, 6, 7, 8))
    result = _run(
        bars=tuple(_bar("AAA.AX", day) for day in (signal, entry, suspended, resumed)),
        decision=_decision("AAA.AX", signal),
        events=(SuspensionEvent("halt-aaa", "AAA.AX", suspended, resumed),),
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("suspension" in reason for reason in result.invalid_reasons)


def test_partition_rejects_calendar_rows_beyond_authorized_t64() -> None:
    sessions: list[date] = []
    cursor = date(2026, 1, 5)
    while len(sessions) < 66:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    signal, entry = sessions[:2]
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(),
        last_session=sessions[65],
        final_entry_session=entry,
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("T64" in reason for reason in result.invalid_reasons)


def test_split_before_next_open_transforms_pending_quantity_limit_and_stop() -> None:
    signal, split_entry, stopped = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(
            _bar("AAA.AX", signal, factor=SplitFactor(1, 2)),
            _bar("AAA.AX", split_entry, open_="5", high="5.2", low="4.8", close="5"),
            _bar("AAA.AX", stopped, open_="4.4", high="4.6", low="4.2", close="4.4"),
        ),
        decision=_decision("AAA.AX", signal),
        events=(SplitEvent("split-aaa", "AAA.AX", split_entry, 2, 1),),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.side, fill.quantity) for fill in result.fills] == [("buy", 10), ("sell", 10)]
    assert result.trades[0].submitted_limit == D("5")
    assert result.trades[0].initial_stop == D("4.5")
    assert result.trades[0].order_initial_risk_dollars == D("5")
    assert result.signal_trades[0].entry_session == split_entry
    assert result.corporate_action_evidence[0].quantity_after == 10


def test_symbol_change_before_next_open_preserves_pending_signal_identity() -> None:
    signal, renamed_entry, stopped = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars={
            "OLD.AX": (_bar("OLD.AX", signal),),
            "NEW.AX": (
                _bar("NEW.AX", renamed_entry),
                _bar("NEW.AX", stopped, open_="8.8", high="9", low="8.5", close="8.8"),
            ),
        },
        decision=_decision("OLD.AX", signal),
        events=(SymbolChangeEvent("rename-old", "OLD.AX", renamed_entry, "NEW.AX"),),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.symbol, fill.side) for fill in result.fills] == [
        ("NEW.AX", "buy"),
        ("NEW.AX", "sell"),
    ]
    assert result.position_events[0].position_id == result.position_events[-1].position_id
    assert result.signal_trades[0].entry_session == renamed_entry


def test_zero_realizable_delisting_proceeds_are_an_explicit_terminal_exit() -> None:
    signal, entry, delisted = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(DelistingEvent("delist-zero", "AAA.AX", delisted, D("0")),),
        last_session=delisted,
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].exit_session == delisted
    assert result.trades[0].exit_reason == "delisting_outcome"
    assert result.trades[0].gross_pnl == D("-50")
    assert result.equity[-1].equity == D("9950")


def test_symbol_change_without_new_symbol_history_invalidates_before_replay() -> None:
    signal, entry, renamed = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(_bar("AAA.AX", signal), _bar("AAA.AX", entry)),
        decision=_decision("AAA.AX", signal),
        events=(SymbolChangeEvent("rename-aaa", "AAA.AX", renamed, "MISSING.AX"),),
        last_session=renamed,
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("new-symbol history" in reason for reason in result.invalid_reasons)


def test_duplicate_corporate_action_identity_invalidates_before_replay() -> None:
    signal, entry, split = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", split, open_="5", high="5.2", low="4.8", close="5"),
        ),
        decision=_decision("AAA.AX", signal),
        events=(
            SplitEvent("duplicate", "AAA.AX", split, 2, 1),
            SplitEvent("duplicate", "AAA.AX", split, 2, 1),
        ),
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("duplicated" in reason for reason in result.invalid_reasons)


def test_same_day_split_precedes_symbol_change_independent_of_input_order() -> None:
    signal, transformed_entry, stopped = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars={
            "OLD.AX": (_bar("OLD.AX", signal, factor=SplitFactor(1, 2)),),
            "NEW.AX": (
                _bar("NEW.AX", transformed_entry, open_="5", high="5.2", low="4.8", close="5"),
                _bar("NEW.AX", stopped, open_="4.4", high="4.6", low="4.2", close="4.4"),
            ),
        },
        decision=_decision("OLD.AX", signal),
        events=(
            SymbolChangeEvent("rename-old", "OLD.AX", transformed_entry, "NEW.AX"),
            SplitEvent("split-old", "OLD.AX", transformed_entry, 2, 1),
        ),
    )

    assert result.status is RunStatus.VALID
    assert [(fill.symbol, fill.quantity) for fill in result.fills] == [
        ("NEW.AX", 10),
        ("NEW.AX", 10),
    ]
    assert [item.event_id for item in result.corporate_action_evidence] == [
        "split-old",
        "rename-old",
    ]
    assert result.signal_trades[0].entry_session == transformed_entry


def test_symbol_change_during_suspension_carries_stale_mark_without_forced_exit() -> None:
    signal, entry, suspended, renamed, resumed = (date(2026, 1, day) for day in (5, 6, 7, 8, 12))
    result = _run(
        bars={
            "OLD.AX": (_bar("OLD.AX", signal), _bar("OLD.AX", entry)),
            "NEW.AX": (_bar("NEW.AX", resumed, open_="9.5", high="9.8", low="9.2", close="9.5"),),
        },
        decision=_decision("OLD.AX", signal),
        events=(
            SuspensionEvent("halt-old", "OLD.AX", suspended, resumed),
            SymbolChangeEvent("rename-old", "OLD.AX", renamed, "NEW.AX"),
        ),
    )

    assert result.status is RunStatus.VALID
    assert result.equity[2].position_value == result.equity[3].position_value == D("50")
    assert result.equity[2].stale_marks == (("OLD.AX", D("10")),)
    assert result.equity[3].stale_marks == (("NEW.AX", D("10")),)
    assert result.trades == result.signal_trades == ()


def test_zero_price_is_reserved_for_terminal_sell_fills() -> None:
    session = date(2026, 1, 7)
    with pytest.raises(ValueError):
        SimulatedFill("bad-buy", "AAA.AX", session, "buy", 5, D("0"), D("0"), "terminal_zero")
    with pytest.raises(ValueError):
        ConfirmedFill("bad-buy", session, "buy", 5, D("0"), "terminal_zero")
    with pytest.raises(ValueError):
        SimulatedFill("unlinked", "AAA.AX", session, "sell", 5, D("0"), D("0"), "terminal_zero")


def test_traded_bar_after_preopen_delisting_invalidates_before_any_fill() -> None:
    signal, entry, delisted = (date(2026, 1, day) for day in (5, 6, 7))
    result = _run(
        bars=tuple(_bar("AAA.AX", day) for day in (signal, entry, delisted)),
        decision=_decision("AAA.AX", signal),
        events=(DelistingEvent("delist-aaa", "AAA.AX", delisted, D("7")),),
    )

    assert result.status is RunStatus.INVALID
    assert result.decisions == result.trades == result.signal_trades == ()
    assert any("delisting" in reason for reason in result.invalid_reasons)


def test_dividend_payment_on_closed_calendar_date_settles_before_next_session() -> None:
    signal = date(2026, 1, 7)
    entry = date(2026, 1, 8)
    ex_date = date(2026, 1, 9)
    payment = date(2026, 1, 10)
    next_session = date(2026, 1, 12)
    result = _run(
        bars=(
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry),
            _bar("AAA.AX", ex_date, open_="9.5", high="9.7", low="8.5", close="9"),
            _bar("AAA.AX", next_session),
        ),
        decision=_decision("AAA.AX", signal),
        events=(
            CashDividendEvent(
                "div-aaa", "AAA.AX", ex_date, signal, ex_date, ex_date, payment, D("0.20")
            ),
        ),
    )

    assert result.status is RunStatus.VALID
    assert result.equity[-1].session == next_session
    assert result.equity[-1].cash == D("9996")
    assert result.equity[-1].dividend_receivables == D("0")
    assert result.equity[-1].equity == result.equity[-2].equity


def test_filled_pattern_identity_stays_consumed_after_later_ticker_change() -> None:
    first_signal = date(2026, 1, 5)
    first_entry = date(2026, 1, 6)
    first_stop = date(2026, 1, 7)
    renamed = date(2026, 1, 8)
    repeat_signal = date(2026, 1, 9)
    second_entry = date(2026, 1, 12)
    second_stop = date(2026, 1, 13)
    repeated = _decision("NEW.AX", repeat_signal, pattern_id="same-pattern-instance")
    result = _run(
        bars={
            "OLD.AX": (
                _bar("OLD.AX", first_signal),
                _bar("OLD.AX", first_entry),
                _bar("OLD.AX", first_stop, open_="8.8", high="9", low="8.5", close="8.8"),
            ),
            "NEW.AX": (
                _bar("NEW.AX", renamed),
                _bar("NEW.AX", repeat_signal),
                _bar("NEW.AX", second_entry),
                _bar("NEW.AX", second_stop, open_="8.8", high="9", low="8.5", close="8.8"),
            ),
        },
        decision=_decision("OLD.AX", first_signal, pattern_id="same-pattern-instance"),
        later_decisions={("NEW.AX", repeat_signal): repeated},
        events=(SymbolChangeEvent("rename-old", "OLD.AX", renamed, "NEW.AX"),),
    )

    assert result.status is RunStatus.VALID
    assert len(result.trades) == 1
    assert len(result.signal_trades) == 1
    assert any(rule.code == "signal_identity_consumed" for rule in result.abstentions)
