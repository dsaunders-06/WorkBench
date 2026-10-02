"""Ordered authoritative multi-symbol swing replay tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from qat.domain.backtester.swing_fills import AmbiguityPolicy
from qat.domain.backtester.swing_replay import (
    AuthoritativeSwingReplay,
    ReplayCalendarRow,
    SessionKind,
    classify_post_fill_resistance,
)
from qat.domain.backtester.swing_results import (
    PostFillResistanceDiagnostic,
    RunStatus,
    SwingReplayResult,
)
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
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
)


def D(value: str | int) -> Decimal:
    return Decimal(value)


COSTS = ExactCostProfile("fixture-v1", "fixture", D("0"), D("0"), "AUD", False, D("0"))
LIQUIDITY = LiquidityProfile("fixture-v1", D("1"), D("0"), D("0"))


def _bar(
    symbol: str,
    session: date,
    *,
    open_: str = "10",
    high: str = "10.5",
    low: str = "9.5",
    close: str = "10",
    volume: int = 100_000,
) -> FinalBar:
    prices = Ohlcv(D(open_), D(high), D(low), D(close), volume)
    return FinalBar(
        symbol,
        session,
        prices,
        prices,
        "fixture",
        DataQuality.VERIFIED,
        AdjustmentStatus.SPLIT_NORMALIZED,
        SplitFactor(1, 1),
        True,
        f"{symbol}-{session.isoformat()}-{open_}-{high}-{low}-{close}",
    )


def _calendar(first: date, last: date) -> tuple[ReplayCalendarRow, ...]:
    rows: list[ReplayCalendarRow] = []
    current = first
    while current <= last:
        kind = SessionKind.WEEKEND if current.weekday() >= 5 else SessionKind.FULL
        rows.append(
            ReplayCalendarRow(
                current,
                kind,
                source="fixture-calendar",
                reason="weekend" if kind is SessionKind.WEEKEND else "normal session",
                source_hash=f"calendar-{current.isoformat()}",
                finalized=True,
            )
        )
        current += timedelta(days=1)
    return tuple(rows)


def _business_days(first: date, count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    current = first
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def _decision(
    symbol: str,
    session: date,
    *,
    status: DecisionStatus = DecisionStatus.QUALIFIED,
    pattern: Pattern = Pattern.EMA_PULLBACK,
    pattern_id: str | None = None,
    breakout_id: str | None = None,
    limit: str = "10",
    stop: str = "9",
    quantity: int = 5,
) -> SetupDecision:
    candidate = PatternCandidate(
        pattern,
        pattern_id or f"pattern-{symbol}-{session.isoformat()}",
        breakout_id,
        session,
        D(limit),
        D(stop),
        D("0.5"),
    )
    pattern_decision = PatternDecision(pattern, status, (), candidate)
    return SetupDecision(
        "phase2-swing-v1",
        "swing-evidence-v1",
        f"decision-{symbol}-{session.isoformat()}-{pattern.value}-{breakout_id or 'none'}",
        symbol,
        session,
        status,
        (pattern,),
        (pattern_decision,),
        D(limit) if status is DecisionStatus.QUALIFIED else None,
        D(stop) if status is DecisionStatus.QUALIFIED else None,
        quantity if status is DecisionStatus.QUALIFIED else 0,
        quantity if status is DecisionStatus.QUALIFIED else 0,
        quantity if status is DecisionStatus.QUALIFIED else 0,
        (f"bar-{symbol}-{session.isoformat()}",),
    )


class _FixtureEngine:
    def __init__(self, decisions: Mapping[tuple[str, date], SetupDecision]) -> None:
        self._decisions = decisions

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
        assert evaluation_session is not None
        found = self._decisions.get((history.symbol, evaluation_session))
        if found is not None:
            return found
        return SetupDecision(
            "phase2-swing-v1",
            "swing-evidence-v1",
            f"abstain-{history.symbol}-{evaluation_session.isoformat()}",
            history.symbol,
            evaluation_session,
            DecisionStatus.ABSTAIN,
            (),
            (),
            None,
            None,
            0,
            0,
            0,
            tuple(bar.digest for bar in history.daily),
            setup_rules=(
                RuleEvidence("fixture_no_signal", RuleOutcome.ABSTAIN, reason="no signal"),
            ),
        )


def _run(
    *,
    bars: Mapping[str, Sequence[FinalBar]],
    decisions: Mapping[tuple[str, date], SetupDecision],
    first: date,
    last: date,
    starting_equity: str = "10000",
    calendar: Sequence[ReplayCalendarRow] | None = None,
    membership: Mapping[date, frozenset[str]] | None = None,
    benchmark: Sequence[FinalBar] | None = None,
) -> SwingReplayResult:
    calendar_rows = tuple(calendar) if calendar is not None else _calendar(first, last)
    official = tuple(row.calendar_date for row in calendar_rows if row.is_tradable)
    replay_membership = (
        dict(membership)
        if membership is not None
        else {session: frozenset(bars) for session in official}
    )
    replay_benchmark = (
        tuple(benchmark)
        if benchmark is not None
        else tuple(
            _bar("BENCH.AX", session, open_="100", high="101", low="99", close="100")
            for session in official
        )
    )
    replay = AuthoritativeSwingReplay(
        calendar_rows=calendar_rows,
        bars=bars,
        membership=replay_membership,
        corporate_actions=(),
        benchmark=replay_benchmark,
        engine=_FixtureEngine(decisions),
        starting_equity=D(starting_equity),
        costs=COSTS,
        liquidity=LIQUIDITY,
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE,
    )
    return replay.run()


def test_qualify_at_close_fills_next_open_and_stops_later() -> None:
    signal = date(2026, 1, 5)
    entry = date(2026, 1, 6)
    stopped = date(2026, 1, 7)
    bars = {
        "AAA.AX": (
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry, open_="9.8", high="10.2", low="9.4", close="10"),
            _bar("AAA.AX", stopped, open_="9.5", high="9.7", low="8.8", close="9"),
        )
    }

    result = _run(
        bars=bars,
        decisions={("AAA.AX", signal): _decision("AAA.AX", signal)},
        first=signal,
        last=stopped,
    )

    assert result.status is RunStatus.VALID
    assert [(fill.side, fill.reason, fill.session) for fill in result.fills] == [
        ("buy", "entry", entry),
        ("sell", "protective_stop", stopped),
    ]
    assert len(result.trades) == 1
    assert result.trades[0].entry_price == D("9.8")
    assert result.trades[0].exit_reason == "protective_stop"


def test_daily_invalidation_keeps_stop_until_replacement_open() -> None:
    signal = date(2026, 1, 5)
    entry = date(2026, 1, 6)
    stopped = date(2026, 1, 7)
    first = date(2025, 12, 8)
    warm_sessions = tuple(
        first + timedelta(days=offset)
        for offset in range((signal - first).days + 1)
        if (first + timedelta(days=offset)).weekday() < 5
    )
    history = tuple(_bar("AAA.AX", session) for session in warm_sessions)
    bars = {
        "AAA.AX": history
        + (
            _bar("AAA.AX", entry, open_="9.8", high="10", low="8.5", close="9"),
            _bar("AAA.AX", stopped, open_="7.8", high="8", low="7.5", close="7.9"),
        )
    }

    result = _run(
        bars=bars,
        decisions={
            ("AAA.AX", signal): _decision("AAA.AX", signal, stop="8"),
        },
        first=first,
        last=stopped,
    )

    assert result.trades[0].exit_reason == "protective_stop"
    assert "daily_invalidation" in result.trades[0].observed_triggers
    assert result.position_events.count_reason("sell_fill") == 1


def test_signal_arm_suppresses_same_pattern_overlap_until_lifecycle_closes() -> None:
    first_signal = date(2026, 1, 5)
    entry_and_overlap = date(2026, 1, 6)
    stopped = date(2026, 1, 7)
    bars = {
        "AAA.AX": (
            _bar("AAA.AX", first_signal),
            _bar(
                "AAA.AX",
                entry_and_overlap,
                open_="9.8",
                high="10.2",
                low="9.4",
                close="10",
            ),
            _bar("AAA.AX", stopped, open_="9.5", high="9.7", low="8.8", close="9"),
        )
    }
    decisions = {
        ("AAA.AX", first_signal): _decision(
            "AAA.AX", first_signal, pattern_id="pattern-first"
        ),
        ("AAA.AX", entry_and_overlap): _decision(
            "AAA.AX", entry_and_overlap, pattern_id="pattern-overlap"
        ),
    }

    result = _run(
        bars=bars,
        decisions=decisions,
        first=first_signal,
        last=stopped,
    )

    assert len(result.signal_trades) == 1
    assert result.signal_trades[0].edge_sample_eligible is True
    assert any(rule.code == "OVERLAPPING_EVENT" for rule in result.abstentions)


def test_gap_above_limit_cancels_entry_without_intraday_chase() -> None:
    signal = date(2026, 1, 5)
    gap = date(2026, 1, 6)
    bars = {
        "AAA.AX": (
            _bar("AAA.AX", signal),
            _bar("AAA.AX", gap, open_="10.5", high="11", low="9.5", close="10"),
        )
    }

    result = _run(
        bars=bars,
        decisions={("AAA.AX", signal): _decision("AAA.AX", signal)},
        first=signal,
        last=gap,
    )

    assert not any(fill.side == "buy" for fill in result.fills)
    assert result.position_events.count_reason("entry_cancelled") == 1


def test_simultaneous_signals_scale_without_symbol_order_bias() -> None:
    signal = date(2026, 1, 5)
    entry = date(2026, 1, 6)
    bars = {
        symbol: (
            _bar(symbol, signal, open_="100", high="101", low="99", close="100"),
            _bar(symbol, entry, open_="100", high="101", low="99", close="100"),
        )
        for symbol in ("AAA.AX", "BBB.AX")
    }
    decisions = {
        (symbol, signal): _decision(
            symbol, signal, limit="100", stop="95", quantity=20
        )
        for symbol in bars
    }

    result = _run(
        bars=bars,
        decisions=decisions,
        first=signal,
        last=entry,
        starting_equity="3000",
    )

    assert [(fill.symbol, fill.quantity) for fill in result.fills if fill.side == "buy"] == [
        ("AAA.AX", 15),
        ("BBB.AX", 15),
    ]


def test_better_fill_preserves_quantity_and_records_both_r_denominators() -> None:
    signal = date(2026, 1, 5)
    entry = date(2026, 1, 6)
    stopped = date(2026, 1, 7)
    bars = {
        "AAA.AX": (
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry, open_="9.4", high="9.7", low="9.2", close="9.5"),
            _bar("AAA.AX", stopped, open_="9.2", high="9.3", low="8.8", close="9"),
        )
    }

    result = _run(
        bars=bars,
        decisions={("AAA.AX", signal): _decision("AAA.AX", signal)},
        first=signal,
        last=stopped,
    )

    trade = result.trades[0]
    assert trade.quantity == 5
    assert trade.order_initial_risk_dollars == D("5")
    assert trade.fill_initial_risk_dollars == D("2")
    assert trade.order_r_multiple == D("-0.4")
    assert trade.fill_r_multiple == D("-1")


def test_actual_fill_resistance_classifies_inside_and_path_blocked() -> None:
    assert classify_post_fill_resistance(
        D("9.90"), D("9.00"), ((D("9.80"), D("9.95")),)
    ) is PostFillResistanceDiagnostic.INSIDE_ZONE
    assert classify_post_fill_resistance(
        D("9.40"), D("9.00"), ((D("9.50"), D("9.60")),)
    ) is PostFillResistanceDiagnostic.PATH_BLOCKED


def test_duplicate_or_missing_calendar_row_invalidates_before_state_changes() -> None:
    first = date(2026, 1, 5)
    second = date(2026, 1, 6)
    duplicate = _calendar(first, second) + (_calendar(first, second)[-1],)
    missing = (_calendar(first, first)[0], ReplayCalendarRow(
        date(2026, 1, 7),
        SessionKind.FULL,
        "fixture-calendar",
        "normal session",
        "calendar-2026-01-07",
        True,
    ))

    duplicate_result = _run(
        bars={}, decisions={}, first=first, last=second, calendar=duplicate
    )
    missing_result = _run(
        bars={}, decisions={}, first=first, last=date(2026, 1, 7), calendar=missing
    )

    for result in (duplicate_result, missing_result):
        assert result.status is RunStatus.INVALID
        assert result.decisions == ()
        assert result.fills == ()
        assert result.equity == ()


def test_closed_row_with_traded_bar_invalidates_dataset() -> None:
    session = date(2026, 1, 5)
    closed = (
        ReplayCalendarRow(
            session,
            SessionKind.AD_HOC_CLOSED,
            "fixture-calendar",
            "documented closure",
            "calendar-closed",
            True,
        ),
    )

    result = _run(
        bars={"AAA.AX": (_bar("AAA.AX", session),)},
        decisions={},
        first=session,
        last=session,
        calendar=closed,
        membership={},
    )

    assert result.status is RunStatus.INVALID
    assert "closed calendar row" in result.invalid_reasons[0]


def test_missing_member_bar_abstains_without_carry_forward() -> None:
    first = date(2026, 1, 5)
    second = date(2026, 1, 6)
    membership = {
        first: frozenset({"AAA.AX"}),
        second: frozenset({"AAA.AX"}),
    }

    result = _run(
        bars={"AAA.AX": (_bar("AAA.AX", first),)},
        decisions={},
        first=first,
        last=second,
        membership=membership,
    )

    assert result.status is RunStatus.VALID
    assert any(
        rule.code == "symbol_bar_missing" and rule.measured == "AAA.AX"
        for rule in result.abstentions
    )
    assert tuple(point.session for point in result.equity) == (first, second)


def test_documented_closure_does_not_advance_tenth_session_exit() -> None:
    sessions = _business_days(date(2025, 12, 1), 33)
    signal = sessions[19]
    closure = sessions[20]
    entry = sessions[21]
    tenth_completed = sessions[30]
    exit_session = sessions[31]
    calendar = tuple(
        replace(
            row,
            session_kind=SessionKind.AD_HOC_CLOSED,
            reason="documented exchange closure",
        )
        if row.calendar_date == closure
        else row
        for row in _calendar(sessions[0], exit_session)
    )
    bars = {
        "AAA.AX": tuple(
            _bar("AAA.AX", session)
            for session in sessions[:32]
            if session != closure
        )
    }

    result = _run(
        bars=bars,
        decisions={
            ("AAA.AX", signal): _decision("AAA.AX", signal, stop="8"),
        },
        first=sessions[0],
        last=exit_session,
        calendar=calendar,
    )

    assert result.status is RunStatus.VALID
    assert result.trades[0].entry_session == entry
    assert result.trades[0].exit_session == exit_session
    assert "time_stop" in result.trades[0].observed_triggers
    assert closure not in {point.session for point in result.equity}
    assert tenth_completed in {point.session for point in result.equity}


def test_target_banks_half_then_later_close_trails_runner_before_stop() -> None:
    sessions = _business_days(date(2025, 12, 1), 25)
    signal, entry, target, trail, stopped = sessions[19:24]
    warm = tuple(_bar("AAA.AX", session) for session in sessions[:20])
    bars = {
        "AAA.AX": warm
        + (
            _bar("AAA.AX", entry, open_="10", high="10.5", low="9.5", close="10"),
            _bar("AAA.AX", target, open_="10.5", high="11.2", low="10.2", close="11"),
            _bar("AAA.AX", trail, open_="11.5", high="13", low="11.1", close="12"),
            _bar("AAA.AX", stopped, open_="10.5", high="10.7", low="10", close="10.4"),
        )
    }

    result = _run(
        bars=bars,
        decisions={("AAA.AX", signal): _decision("AAA.AX", signal)},
        first=sessions[0],
        last=stopped,
    )

    assert [(fill.reason, fill.quantity) for fill in result.fills if fill.side == "sell"] == [
        ("banked_target", 3),
        ("protective_stop", 2),
    ]
    assert result.trades[0].exit_session == stopped


def test_double_bottom_cancel_recross_and_filled_pair_consumption() -> None:
    first_signal, cancelled, recross, entry, stopped = _business_days(
        date(2026, 1, 5), 5
    )
    bars = {
        "AAA.AX": (
            _bar("AAA.AX", first_signal),
            _bar("AAA.AX", cancelled, open_="10.5", high="11", low="9.5", close="10"),
            _bar("AAA.AX", recross),
            _bar("AAA.AX", entry, open_="9.8", high="10.2", low="9.4", close="10"),
            _bar("AAA.AX", stopped, open_="9.5", high="9.7", low="8.8", close="9"),
        )
    }
    decisions = {
        ("AAA.AX", first_signal): _decision(
            "AAA.AX",
            first_signal,
            pattern=Pattern.DOUBLE_BOTTOM,
            pattern_id="pair-1",
            breakout_id="breakout-1",
        ),
        ("AAA.AX", recross): _decision(
            "AAA.AX",
            recross,
            pattern=Pattern.DOUBLE_BOTTOM,
            pattern_id="pair-1",
            breakout_id="breakout-2",
        ),
        ("AAA.AX", stopped): _decision(
            "AAA.AX",
            stopped,
            pattern=Pattern.DOUBLE_BOTTOM,
            pattern_id="pair-1",
            breakout_id="breakout-3",
        ),
    }

    result = _run(
        bars=bars,
        decisions=decisions,
        first=first_signal,
        last=stopped,
    )

    assert result.position_events.count_reason("entry_cancelled") == 1
    assert [(fill.session, fill.side) for fill in result.fills] == [
        (entry, "buy"),
        (stopped, "sell"),
    ]
    assert len(result.signal_trades) == 1
    assert any(rule.code == "signal_identity_consumed" for rule in result.abstentions)


def test_post_fill_zone_diagnostic_is_retained_on_baseline_trade() -> None:
    prior_sessions = _business_days(date(2025, 10, 1), 42)
    signal, entry, stopped = _business_days(prior_sessions[-1] + timedelta(days=1), 3)
    prior: list[FinalBar] = []
    for index, session in enumerate(prior_sessions):
        high = "9.5" if index == 5 else "9.55" if index == 30 else "9.4"
        prior.append(
            _bar("AAA.AX", session, open_="9", high=high, low="8.5", close="9")
        )
    bars = {
        "AAA.AX": tuple(prior)
        + (
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry, open_="9.4", high="9.45", low="9.2", close="9.4"),
            _bar("AAA.AX", stopped, open_="9.2", high="9.3", low="8.8", close="9"),
        )
    }

    result = _run(
        bars=bars,
        decisions={("AAA.AX", signal): _decision("AAA.AX", signal)},
        first=prior_sessions[0],
        last=stopped,
    )

    assert result.status is RunStatus.VALID
    assert (
        result.trades[0].post_fill_resistance
        is PostFillResistanceDiagnostic.PATH_BLOCKED
    )


def test_replay_is_deterministic_for_identical_inputs() -> None:
    signal, entry, stopped = _business_days(date(2026, 1, 5), 3)
    bars = {
        "AAA.AX": (
            _bar("AAA.AX", signal),
            _bar("AAA.AX", entry, open_="9.8", high="10.2", low="9.4", close="10"),
            _bar("AAA.AX", stopped, open_="9.5", high="9.7", low="8.8", close="9"),
        )
    }
    arguments = {
        "bars": bars,
        "decisions": {("AAA.AX", signal): _decision("AAA.AX", signal)},
        "first": signal,
        "last": stopped,
    }

    assert _run(**arguments) == _run(**arguments)


def test_missing_next_session_bar_cancels_on_that_session_and_abstains() -> None:
    signal, missing = _business_days(date(2026, 1, 5), 2)
    result = _run(
        bars={"AAA.AX": (_bar("AAA.AX", signal),)},
        decisions={("AAA.AX", signal): _decision("AAA.AX", signal)},
        first=signal,
        last=missing,
        membership={
            signal: frozenset({"AAA.AX"}),
            missing: frozenset({"AAA.AX"}),
        },
    )

    cancellation = next(
        event for event in result.position_events if event.reason == "entry_cancelled"
    )
    assert cancellation.session == missing
    assert any(rule.code == "symbol_bar_missing" for rule in result.abstentions)


def test_benchmark_gap_invalidates_before_replay() -> None:
    first, second = _business_days(date(2026, 1, 5), 2)
    result = _run(
        bars={},
        decisions={},
        first=first,
        last=second,
        benchmark=(
            _bar("BENCH.AX", first, open_="100", high="101", low="99", close="100"),
        ),
    )

    assert result.status is RunStatus.INVALID
    assert result.equity == ()
    assert any("benchmark" in reason for reason in result.invalid_reasons)
