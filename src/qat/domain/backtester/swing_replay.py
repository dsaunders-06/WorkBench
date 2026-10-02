"""Ordered, deterministic replay for the authoritative swing lifecycle."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from qat.domain.backtester.swing_events import SwingMarketEvent
from qat.domain.backtester.swing_fills import (
    AmbiguityPolicy,
    TradedDailyBar,
    ambiguity_for_session,
    resolve_entry_open,
    resolve_open_exit,
    resolve_protective_session,
)
from qat.domain.backtester.swing_portfolio import (
    PortfolioState,
    allocate_entry_batch,
    apply_fills,
    mark_to_market,
)
from qat.domain.backtester.swing_results import (
    FillAmbiguity,
    LifecycleActionSeries,
    PostFillResistanceDiagnostic,
    ReplayArm,
    RunStatus,
    SimulatedFill,
    SwingReplayResult,
    SwingTrade,
)
from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.indicators import ema, wilder_atr
from qat.domain.strategies.authoritative_swing.lifecycle import (
    CompletedSession,
    ConfirmedFill,
    LifecycleAction,
    PendingEntry,
    PositionState,
    SwingPosition,
    apply_entry_fill,
    apply_exit_fill,
    apply_target_fill,
    cancel_pending_entry,
    evaluate_completed_close,
    pending_entry_from_setup,
)
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    FinalBar,
    RuleEvidence,
    RuleOutcome,
    SetupDecision,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import to_raw_price
from qat.domain.strategies.authoritative_swing.resistance import find_resistance_zones
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
    size_for_risk,
)


class SessionKind(StrEnum):
    FULL = "FULL"
    SHORTENED = "SHORTENED"
    AD_HOC_CLOSED = "AD_HOC_CLOSED"
    SCHEDULED_CLOSED = "SCHEDULED_CLOSED"
    WEEKEND = "WEEKEND"


@dataclass(frozen=True, slots=True)
class ReplayCalendarRow:
    calendar_date: date
    session_kind: SessionKind
    source: str
    reason: str
    source_hash: str
    finalized: bool

    @property
    def is_tradable(self) -> bool:
        return self.session_kind in {SessionKind.FULL, SessionKind.SHORTENED}


class SwingEngine(Protocol):
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
    ) -> SetupDecision: ...


@dataclass(slots=True)
class _TradeState:
    decision: SetupDecision
    entry: SimulatedFill
    position: SwingPosition
    exits: list[SimulatedFill]
    highest_high: Decimal
    lowest_low: Decimal
    observed_triggers: list[str]
    post_fill_resistance: PostFillResistanceDiagnostic


def _confirmed(fill: SimulatedFill) -> ConfirmedFill:
    return ConfirmedFill(
        fill.event_id,
        fill.session,
        fill.side,
        fill.quantity,
        fill.price,
        fill.reason,
    )


def classify_post_fill_resistance(
    actual_fill: Decimal,
    structural_stop: Decimal,
    zones: Sequence[tuple[Decimal, Decimal]],
) -> PostFillResistanceDiagnostic:
    """Classify the actual-fill path through the unchanged structural zones."""

    relevant = tuple(
        sorted(
            ((lower, upper) for lower, upper in zones if upper >= actual_fill),
            key=lambda item: (max(actual_fill, item[0]), item[0], item[1]),
        )
    )
    if not relevant:
        return PostFillResistanceDiagnostic.CLEAR
    lower, upper = relevant[0]
    if lower <= actual_fill <= upper:
        return PostFillResistanceDiagnostic.INSIDE_ZONE
    two_r = actual_fill + Decimal(2) * (actual_fill - structural_stop)
    if two_r >= lower:
        return PostFillResistanceDiagnostic.PATH_BLOCKED
    return PostFillResistanceDiagnostic.CLEAR


def _empty_result(
    *,
    status: RunStatus = RunStatus.VALID,
    invalid_reasons: tuple[str, ...] = (),
) -> SwingReplayResult:
    return SwingReplayResult(
        status=status,
        arm=ReplayArm.COMBINED,
        decisions=(),
        position_events=LifecycleActionSeries(),
        fills=(),
        trades=(),
        signal_trades=(),
        equity=(),
        abstentions=(),
        ambiguities=(),
        invalid_reasons=invalid_reasons,
    )


class AuthoritativeSwingReplay:
    """Replay the shared engine through one explicit official-calendar ledger."""

    def __init__(
        self,
        *,
        calendar_rows: Sequence[ReplayCalendarRow],
        bars: Mapping[str, Sequence[FinalBar]],
        membership: Mapping[date, frozenset[str]],
        corporate_actions: Sequence[SwingMarketEvent],
        benchmark: Sequence[FinalBar],
        engine: SwingEngine,
        starting_equity: Decimal,
        costs: ExactCostProfile,
        liquidity: LiquidityProfile,
        ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.CONSERVATIVE,
    ) -> None:
        self._calendar_rows = tuple(calendar_rows)
        self._bars = {symbol: tuple(items) for symbol, items in bars.items()}
        self._membership = dict(membership)
        self._corporate_actions = tuple(corporate_actions)
        self._benchmark = tuple(benchmark)
        self._engine = engine
        self._starting_equity = starting_equity
        self._costs = costs
        self._liquidity = liquidity
        self._ambiguity_policy = ambiguity_policy

    def _validate_inputs(self) -> tuple[str, ...]:
        reasons: list[str] = []
        dates = tuple(row.calendar_date for row in self._calendar_rows)
        if not dates:
            reasons.append("official calendar is empty")
            return tuple(reasons)
        if len(dates) != len(set(dates)):
            reasons.append("official calendar contains a duplicate civil date")
        if dates != tuple(sorted(dates)):
            reasons.append("official calendar rows are not ordered")
        expected = tuple(
            dates[0] + timedelta(days=offset)
            for offset in range((dates[-1] - dates[0]).days + 1)
        )
        if dates != expected:
            reasons.append("official calendar is missing a civil date")
        if any(
            not row.finalized or not row.source or not row.source_hash or not row.reason
            for row in self._calendar_rows
        ):
            reasons.append("official calendar contains unverifiable rows")

        by_date = {row.calendar_date: row for row in self._calendar_rows}
        for symbol, items in self._bars.items():
            sessions = tuple(bar.session for bar in items)
            if len(sessions) != len(set(sessions)) or sessions != tuple(sorted(sessions)):
                reasons.append(f"{symbol} bars contain duplicate or unordered sessions")
            for bar in items:
                row = by_date.get(bar.session)
                if row is None:
                    reasons.append(f"{symbol} has a bar outside the calendar")
                elif not row.is_tradable:
                    reasons.append(f"{symbol} has a traded bar on a closed calendar row")
                elif not bar.finalized:
                    reasons.append(f"{symbol} has a non-finalized replay bar")
        for bar in self._benchmark:
            row = by_date.get(bar.session)
            if row is None or not row.is_tradable:
                reasons.append("benchmark has a bar outside the tradable calendar")
        if self._benchmark:
            benchmark_sessions = tuple(bar.session for bar in self._benchmark)
            tradable_sessions = tuple(
                row.calendar_date for row in self._calendar_rows if row.is_tradable
            )
            if (
                benchmark_sessions != tradable_sessions
                or len({bar.symbol for bar in self._benchmark}) != 1
                or any(not bar.finalized for bar in self._benchmark)
            ):
                reasons.append(
                    "benchmark must contain one finalized row for every tradable session"
                )
        if self._corporate_actions:
            reasons.append("corporate-action transformation belongs to Phase 2B Task 6")
        if not self._starting_equity.is_finite() or self._starting_equity <= 0:
            reasons.append("starting equity must be finite and positive")
        return tuple(dict.fromkeys(reasons))

    def run(self) -> SwingReplayResult:
        invalid_reasons = self._validate_inputs()
        if invalid_reasons:
            return _empty_result(status=RunStatus.INVALID, invalid_reasons=invalid_reasons)

        bars_by_session = {
            symbol: {bar.session: bar for bar in items}
            for symbol, items in self._bars.items()
        }
        portfolio = PortfolioState(self._starting_equity, self._starting_equity)
        pending: dict[str, PendingEntry] = {}
        decisions: list[SetupDecision] = []
        signal_decisions: list[SetupDecision] = []
        position_events: list[LifecycleAction] = []
        fills: list[SimulatedFill] = []
        trades: list[SwingTrade] = []
        equity = []
        abstentions: list[RuleEvidence] = []
        ambiguities: list[FillAmbiguity] = []
        trade_states: dict[str, _TradeState] = {}
        decision_by_id: dict[str, SetupDecision] = {}
        used_breakouts: set[str] = set()
        consumed_patterns: set[str] = set()

        for row in self._calendar_rows:
            if not row.is_tradable:
                continue
            session = row.calendar_date
            session_bars = {
                symbol: indexed[session]
                for symbol, indexed in bars_by_session.items()
                if session in indexed
            }

            portfolio, closed = self._resolve_opening_positions(
                portfolio,
                session_bars,
                position_events,
                fills,
                trade_states,
                trades,
            )
            del closed
            portfolio = self._resolve_pending_entries(
                portfolio,
                pending,
                session,
                session_bars,
                position_events,
                fills,
                trade_states,
                decision_by_id,
                consumed_patterns,
            )
            portfolio = self._resolve_intraday(
                portfolio,
                session_bars,
                position_events,
                fills,
                trade_states,
                trades,
                ambiguities,
            )

            open_symbols = {position.symbol for position in portfolio.positions}
            missing_open = tuple(sorted(open_symbols - session_bars.keys()))
            if missing_open:
                return _empty_result(
                    status=RunStatus.INVALID,
                    invalid_reasons=tuple(
                        f"missing mark for open position {symbol} on {session}"
                        for symbol in missing_open
                    ),
                )
            point = mark_to_market(
                portfolio,
                session,
                {symbol: bar.raw.close for symbol, bar in session_bars.items()},
            )
            portfolio = self._evaluate_closes(
                portfolio,
                session_bars,
                trade_states,
                abstentions,
            )

            qualified: list[SetupDecision] = []
            blocked_symbols = {
                position.symbol for position in portfolio.positions
            } | set(pending)
            for symbol in sorted(self._membership.get(session, frozenset())):
                bar = session_bars.get(symbol)
                if bar is None:
                    abstentions.append(
                        RuleEvidence(
                            "symbol_bar_missing",
                            RuleOutcome.ABSTAIN,
                            measured=symbol,
                            reason=f"no finalized bar on official session {session}",
                        )
                    )
                    continue
                history = SwingHistory(
                    symbol,
                    tuple(item for item in self._bars[symbol] if item.session <= session),
                )
                decision = self._engine.evaluate(
                    history,
                    point.equity,
                    self._costs,
                    self._liquidity,
                    available_cash=portfolio.available_cash,
                    evaluation_session=session,
                )
                decisions.append(decision)
                signal_decision = (
                    decision
                    if point.equity == self._starting_equity
                    and portfolio.available_cash == self._starting_equity
                    else self._engine.evaluate(
                        history,
                        self._starting_equity,
                        self._costs,
                        self._liquidity,
                        available_cash=self._starting_equity,
                        evaluation_session=session,
                    )
                )
                signal_decisions.append(signal_decision)
                decision_by_id[decision.decision_id] = decision
                if decision.status is not DecisionStatus.QUALIFIED:
                    abstentions.extend(
                        rule for rule in decision.setup_rules if rule.outcome is RuleOutcome.ABSTAIN
                    )
                    continue
                identities = tuple(
                    item.candidate
                    for item in decision.pattern_decisions
                    if item.candidate is not None
                )
                breakout_ids = {
                    item.breakout_event_id
                    for item in identities
                    if item.breakout_event_id is not None
                }
                pattern_ids = {item.pattern_instance_id for item in identities}
                if (
                    symbol in blocked_symbols
                    or breakout_ids & used_breakouts
                    or pattern_ids & consumed_patterns
                ):
                    abstentions.append(
                        RuleEvidence(
                            "candidate_blocked",
                            RuleOutcome.ABSTAIN,
                            measured=symbol,
                            reason="open/pending symbol or consumed setup identity",
                        )
                    )
                    continue
                qualified.append(decision)

            allocations = (
                allocate_entry_batch(
                    portfolio.available_cash,
                    qualified,
                    self._costs,
                    self._liquidity,
                )
                if qualified
                else ()
            )
            for allocation in allocations:
                instruction_id = stable_decision_id(
                    {
                        "decision_id": allocation.decision.decision_id,
                        "allocated_quantity": allocation.quantity,
                    }
                )
                instruction_decision = replace(
                    allocation.decision,
                    decision_id=instruction_id,
                    quantity=allocation.quantity,
                )
                entry = pending_entry_from_setup(instruction_decision)
                pending[entry.symbol] = entry
                decision_by_id[instruction_id] = allocation.decision
                used_breakouts.update(entry.breakout_event_ids)
            portfolio = replace(
                portfolio,
                pending_allocations=portfolio.pending_allocations + allocations,
            )
            equity.append(point)

        signal_trades, signal_abstentions = replay_signal_candidates(
            calendar_rows=self._calendar_rows,
            bars=self._bars,
            decisions=signal_decisions,
            reference_equity=self._starting_equity,
            costs=self._costs,
            liquidity=self._liquidity,
            ambiguity_policy=self._ambiguity_policy,
        )
        abstentions.extend(signal_abstentions)
        return SwingReplayResult(
            RunStatus.VALID,
            ReplayArm.COMBINED,
            tuple(decisions),
            LifecycleActionSeries(position_events),
            tuple(fills),
            tuple(trades),
            signal_trades,
            tuple(equity),
            tuple(abstentions),
            tuple(ambiguities),
            signal_decisions=tuple(signal_decisions),
        )

    def _resolve_pending_entries(
        self,
        portfolio: PortfolioState,
        pending: dict[str, PendingEntry],
        session: date,
        session_bars: Mapping[str, FinalBar],
        actions: list[LifecycleAction],
        all_fills: list[SimulatedFill],
        trade_states: dict[str, _TradeState],
        decisions: Mapping[str, SetupDecision],
        consumed_patterns: set[str],
    ) -> PortfolioState:
        positions = list(portfolio.positions)
        for symbol, instruction in tuple(sorted(pending.items())):
            source = session_bars.get(symbol)
            simulated = (
                ()
                if source is None
                else resolve_entry_open(
                    instruction,
                    _traded(source),
                    self._costs,
                    self._liquidity,
                )
            )
            if simulated:
                fill = simulated[0]
                portfolio = apply_fills(portfolio, simulated)
                position = apply_entry_fill(instruction, _confirmed(fill))
                positions.append(position)
                all_fills.append(fill)
                actions.append(_action(instruction.state, position, fill, "buy_fill"))
                decision = decisions[instruction.instruction_id]
                diagnostic = self._post_fill_diagnostic(decision, fill.price)
                trade_states[position.position_id] = _TradeState(
                    decision,
                    fill,
                    position,
                    [],
                    fill.price,
                    fill.price,
                    [],
                    diagnostic,
                )
                consumed_patterns.update(instruction.pattern_instance_ids)
            else:
                cancellation_id = stable_decision_id(
                    {
                        "instruction_id": instruction.instruction_id,
                        "session": session,
                        "kind": "entry_cancelled",
                    }
                )
                cancelled = cancel_pending_entry(
                    instruction,
                    cancellation_id,
                    "next_session_entry_not_filled",
                )
                actions.append(
                    LifecycleAction(
                        cancellation_id,
                        instruction.instruction_id,
                        symbol,
                        session,
                        instruction.state,
                        cancelled.state,
                        "entry_cancelled",
                    )
                )
                portfolio = replace(
                    portfolio,
                    pending_allocations=tuple(
                        item for item in portfolio.pending_allocations if item.symbol != symbol
                    ),
                )
            pending.pop(symbol)
        return replace(portfolio, positions=tuple(positions))

    def _resolve_opening_positions(
        self,
        portfolio: PortfolioState,
        session_bars: Mapping[str, FinalBar],
        actions: list[LifecycleAction],
        all_fills: list[SimulatedFill],
        trade_states: dict[str, _TradeState],
        trades: list[SwingTrade],
    ) -> tuple[PortfolioState, int]:
        positions: list[SwingPosition] = []
        closed = 0
        for position in portfolio.positions:
            source = session_bars.get(position.symbol)
            simulated = (
                ()
                if source is None
                else resolve_open_exit(position, _traded(source), self._costs, self._liquidity)
            )
            if not simulated:
                positions.append(position)
                continue
            portfolio = apply_fills(portfolio, simulated)
            fill = simulated[0]
            updated = apply_exit_fill(position, _confirmed(fill))
            all_fills.append(fill)
            actions.append(_action(position.state, updated, fill, "sell_fill"))
            state = trade_states[position.position_id]
            state.exits.append(fill)
            state.observed_triggers.extend(position.scheduled_exit_triggers)
            trades.append(_trade(state, updated, fill.reason))
            trade_states.pop(position.position_id)
            closed += 1
        return replace(portfolio, positions=tuple(positions)), closed

    def _resolve_intraday(
        self,
        portfolio: PortfolioState,
        session_bars: Mapping[str, FinalBar],
        actions: list[LifecycleAction],
        all_fills: list[SimulatedFill],
        trade_states: dict[str, _TradeState],
        trades: list[SwingTrade],
        ambiguities: list[FillAmbiguity],
    ) -> PortfolioState:
        positions: list[SwingPosition] = []
        for position in portfolio.positions:
            source = session_bars.get(position.symbol)
            if source is None:
                positions.append(position)
                continue
            traded = _traded(source)
            evidence = ambiguity_for_session(
                position, traded, self._costs, self._liquidity
            )
            if evidence is not None:
                ambiguities.append(evidence)
            simulated = resolve_protective_session(
                position,
                traded,
                self._costs,
                self._liquidity,
                policy=self._ambiguity_policy,
            )
            state = trade_states[position.position_id]
            state.highest_high = max(state.highest_high, source.raw.high)
            state.lowest_low = min(state.lowest_low, source.raw.low)
            updated = position
            for fill in simulated:
                before = updated.state
                if fill.reason == "banked_target":
                    updated = apply_target_fill(updated, _confirmed(fill))
                    reason = "target_fill"
                else:
                    updated = apply_exit_fill(updated, _confirmed(fill))
                    reason = "sell_fill"
                actions.append(_action(before, updated, fill, reason))
                state.exits.append(fill)
                all_fills.append(fill)
            if simulated:
                portfolio = apply_fills(portfolio, simulated)
            if updated.state is PositionState.CLOSED:
                trades.append(_trade(state, updated, simulated[-1].reason))
                trade_states.pop(position.position_id)
            else:
                state.position = updated
                positions.append(updated)
        return replace(portfolio, positions=tuple(positions))

    def _evaluate_closes(
        self,
        portfolio: PortfolioState,
        session_bars: Mapping[str, FinalBar],
        trade_states: dict[str, _TradeState],
        abstentions: list[RuleEvidence],
    ) -> PortfolioState:
        positions: list[SwingPosition] = []
        for position in portfolio.positions:
            source = session_bars[position.symbol]
            history = tuple(
                item for item in self._bars[position.symbol] if item.session <= source.session
            )
            ema20 = ema(tuple(item.adjusted.close for item in history), 20)[-1]
            atr14 = wilder_atr(history)[-1]
            if ema20 is None or atr14 is None:
                abstentions.append(
                    RuleEvidence(
                        "lifecycle_indicators",
                        RuleOutcome.ABSTAIN,
                        measured=position.symbol,
                        reason="insufficient finalized history for EMA20/ATR14",
                    )
                )
                positions.append(position)
                continue
            factor = source.raw_to_adjusted_price_factor
            evaluated = evaluate_completed_close(
                position,
                CompletedSession(source.session, source.raw.high, source.raw.close),
                ema20=to_raw_price(ema20, factor),
                atr14=to_raw_price(atr14, factor),
            )
            state = trade_states[position.position_id]
            state.position = evaluated.position
            state.observed_triggers.extend(evaluated.triggers)
            positions.append(evaluated.position)
        return replace(portfolio, positions=tuple(positions))

    def _post_fill_diagnostic(
        self, decision: SetupDecision, fill: Decimal
    ) -> PostFillResistanceDiagnostic:
        stop = decision.initial_stop_raw
        if stop is None:
            return PostFillResistanceDiagnostic.CLEAR
        prior = tuple(
            bar
            for bar in self._bars[decision.symbol]
            if bar.session < decision.session
        )
        try:
            analytical_zones = find_resistance_zones(prior)
        except ValueError:
            analytical_zones = ()
        factor = (
            next(
                bar.raw_to_adjusted_price_factor
                for bar in reversed(self._bars[decision.symbol])
                if bar.session <= decision.session
            )
            if prior or self._bars[decision.symbol]
            else None
        )
        if factor is None:
            return PostFillResistanceDiagnostic.CLEAR
        raw_zones = tuple(
            (to_raw_price(zone.lower, factor), to_raw_price(zone.upper, factor))
            for zone in analytical_zones
        )
        return classify_post_fill_resistance(fill, stop, raw_zones)


def _traded(bar: FinalBar) -> TradedDailyBar:
    return TradedDailyBar(
        bar.symbol,
        bar.session,
        bar.raw.open,
        bar.raw.high,
        bar.raw.low,
        bar.raw.close,
        bar.raw.volume,
    )


def replay_signal_candidates(
    *,
    calendar_rows: Sequence[ReplayCalendarRow],
    bars: Mapping[str, Sequence[FinalBar]],
    decisions: Sequence[SetupDecision],
    reference_equity: Decimal,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.CONSERVATIVE,
) -> tuple[tuple[SwingTrade, ...], tuple[RuleEvidence, ...]]:
    """Replay per-pattern candidates at one fixed risk-equity reference."""

    indexed = {
        symbol: {bar.session: bar for bar in history}
        for symbol, history in bars.items()
    }
    by_session: dict[date, list[SetupDecision]] = defaultdict(list)
    for decision in decisions:
        if decision.status is DecisionStatus.QUALIFIED:
            by_session[decision.session].append(decision)

    pending: dict[tuple[str, object], PendingEntry] = {}
    positions: dict[tuple[str, object], SwingPosition] = {}
    trade_states: dict[tuple[str, object], _TradeState] = {}
    used_breakouts: dict[tuple[str, object], set[str]] = defaultdict(set)
    consumed_patterns: dict[tuple[str, object], set[str]] = defaultdict(set)
    trades: list[SwingTrade] = []
    abstentions: list[RuleEvidence] = []

    for row in calendar_rows:
        if not row.is_tradable:
            continue
        session = row.calendar_date
        session_bars = {
            symbol: symbol_bars[session]
            for symbol, symbol_bars in indexed.items()
            if session in symbol_bars
        }

        for key, position in tuple(sorted(positions.items(), key=lambda item: str(item[0]))):
            source = session_bars.get(position.symbol)
            if source is None:
                continue
            opening = resolve_open_exit(position, _traded(source), costs, liquidity)
            if opening:
                fill = opening[0]
                updated = apply_exit_fill(position, _confirmed(fill))
                state = trade_states.pop(key)
                state.exits.append(fill)
                state.observed_triggers.extend(position.scheduled_exit_triggers)
                trades.append(_trade(state, updated, fill.reason))
                positions.pop(key)

        for key, instruction in tuple(sorted(pending.items(), key=lambda item: str(item[0]))):
            source = session_bars.get(instruction.symbol)
            entry_fills = (
                ()
                if source is None
                else resolve_entry_open(instruction, _traded(source), costs, liquidity)
            )
            if entry_fills:
                fill = entry_fills[0]
                position = apply_entry_fill(instruction, _confirmed(fill))
                positions[key] = position
                decision = next(
                    item
                    for item in by_session[instruction.signal_session]
                    if item.symbol == instruction.symbol and key[1] in item.patterns
                )
                trade_states[key] = _TradeState(
                    decision,
                    fill,
                    position,
                    [],
                    fill.price,
                    fill.price,
                    [],
                    _diagnostic_for_decision(decision, fill.price, bars),
                )
                consumed_patterns[key].update(instruction.pattern_instance_ids)
            else:
                cancel_pending_entry(
                    instruction,
                    stable_decision_id(
                        {
                            "signal_instruction": instruction.instruction_id,
                            "session": session,
                            "kind": "entry_cancelled",
                        }
                    ),
                    "next_session_entry_not_filled",
                )
            pending.pop(key)

        for key, position in tuple(sorted(positions.items(), key=lambda item: str(item[0]))):
            source = session_bars.get(position.symbol)
            if source is None:
                continue
            state = trade_states[key]
            state.highest_high = max(state.highest_high, source.raw.high)
            state.lowest_low = min(state.lowest_low, source.raw.low)
            intraday = resolve_protective_session(
                position,
                _traded(source),
                costs,
                liquidity,
                policy=ambiguity_policy,
            )
            updated = position
            for fill in intraday:
                if fill.reason == "banked_target":
                    updated = apply_target_fill(updated, _confirmed(fill))
                else:
                    updated = apply_exit_fill(updated, _confirmed(fill))
                state.exits.append(fill)
            if updated.state is PositionState.CLOSED:
                trades.append(_trade(state, updated, intraday[-1].reason))
                trade_states.pop(key)
                positions.pop(key)
                continue
            evaluated = _evaluate_position_close(updated, source, bars[position.symbol])
            if evaluated is not None:
                updated, triggers = evaluated
                state.observed_triggers.extend(triggers)
            state.position = updated
            positions[key] = updated

        for decision in sorted(
            by_session.get(session, ()), key=lambda item: (item.symbol, item.decision_id)
        ):
            for pattern in decision.patterns:
                key = (decision.symbol, pattern)
                matching = tuple(
                    item
                    for item in decision.pattern_decisions
                    if item.pattern is pattern
                    and item.status is DecisionStatus.QUALIFIED
                    and item.candidate is not None
                )
                if not matching:
                    continue
                candidate = matching[0].candidate
                assert candidate is not None
                if key in pending or key in positions:
                    abstentions.append(
                        RuleEvidence(
                            "OVERLAPPING_EVENT",
                            RuleOutcome.ABSTAIN,
                            measured=f"{decision.symbol}:{pattern.value}",
                            reason="isolated signal lifecycle remains open",
                        )
                    )
                    continue
                if (
                    candidate.pattern_instance_id in consumed_patterns[key]
                    or (
                        candidate.breakout_event_id is not None
                        and candidate.breakout_event_id in used_breakouts[key]
                    )
                ):
                    abstentions.append(
                        RuleEvidence(
                            "signal_identity_consumed",
                            RuleOutcome.ABSTAIN,
                            measured=f"{decision.symbol}:{pattern.value}",
                            reason="breakout event or filled pattern was already consumed",
                        )
                    )
                    continue
                limit = decision.entry_limit_raw
                stop = decision.initial_stop_raw
                assert limit is not None and stop is not None
                risk_quantity = size_for_risk(
                    reference_equity, limit, stop, costs, liquidity
                ).quantity
                capacity = decision.capacity_quantity or risk_quantity
                quantity = min(risk_quantity, capacity)
                if quantity < 2:
                    continue
                isolated = replace(
                    decision,
                    decision_id=stable_decision_id(
                        {
                            "kind": "signal_arm_instruction",
                            "decision_id": decision.decision_id,
                            "pattern": pattern,
                            "quantity": quantity,
                        }
                    ),
                    patterns=(pattern,),
                    pattern_decisions=matching,
                    risk_quantity=risk_quantity,
                    quantity=quantity,
                )
                instruction = pending_entry_from_setup(isolated)
                pending[key] = instruction
                used_breakouts[key].update(instruction.breakout_event_ids)

    return tuple(trades), tuple(abstentions)


def _evaluate_position_close(
    position: SwingPosition,
    source: FinalBar,
    history: Sequence[FinalBar],
) -> tuple[SwingPosition, tuple[str, ...]] | None:
    prefix = tuple(item for item in history if item.session <= source.session)
    ema20 = ema(tuple(item.adjusted.close for item in prefix), 20)[-1]
    atr14 = wilder_atr(prefix)[-1]
    if ema20 is None or atr14 is None:
        return None
    factor = source.raw_to_adjusted_price_factor
    evaluated = evaluate_completed_close(
        position,
        CompletedSession(source.session, source.raw.high, source.raw.close),
        ema20=to_raw_price(ema20, factor),
        atr14=to_raw_price(atr14, factor),
    )
    return evaluated.position, evaluated.triggers


def _diagnostic_for_decision(
    decision: SetupDecision,
    fill: Decimal,
    bars: Mapping[str, Sequence[FinalBar]],
) -> PostFillResistanceDiagnostic:
    stop = decision.initial_stop_raw
    if stop is None:
        return PostFillResistanceDiagnostic.CLEAR
    symbol_bars = tuple(bars[decision.symbol])
    prior = tuple(bar for bar in symbol_bars if bar.session < decision.session)
    try:
        analytical_zones = find_resistance_zones(prior)
    except ValueError:
        analytical_zones = ()
    eligible = tuple(bar for bar in symbol_bars if bar.session <= decision.session)
    if not eligible:
        return PostFillResistanceDiagnostic.CLEAR
    factor = eligible[-1].raw_to_adjusted_price_factor
    raw_zones = tuple(
        (to_raw_price(zone.lower, factor), to_raw_price(zone.upper, factor))
        for zone in analytical_zones
    )
    return classify_post_fill_resistance(fill, stop, raw_zones)


def _action(
    previous: PositionState,
    updated: SwingPosition,
    fill: SimulatedFill,
    reason: str,
) -> LifecycleAction:
    return LifecycleAction(
        stable_decision_id(
            {
                "fill_id": fill.event_id,
                "kind": reason,
                "previous": previous,
                "next": updated.state,
            }
        ),
        updated.position_id,
        updated.symbol,
        fill.session,
        previous,
        updated.state,
        reason,
        fill.quantity,
        fill.price,
    )


def _trade(
    state: _TradeState,
    position: SwingPosition,
    exit_reason: str,
) -> SwingTrade:
    del position
    quantity = state.entry.quantity
    exit_notional = sum(
        (Decimal(fill.quantity) * fill.price for fill in state.exits), Decimal(0)
    )
    exit_quantity = sum(fill.quantity for fill in state.exits)
    exit_price = exit_notional / Decimal(exit_quantity)
    gross = exit_notional - Decimal(quantity) * state.entry.price
    costs = state.entry.cost + sum((fill.cost for fill in state.exits), Decimal(0))
    net = gross - costs
    order_risk = state.position.order_initial_risk_dollars
    fill_risk = state.position.fill_initial_risk_dollars
    favorable = Decimal(quantity) * (state.highest_high - state.entry.price)
    adverse = Decimal(quantity) * (state.lowest_low - state.entry.price)
    return SwingTrade(
        stable_decision_id(
            {
                "position_id": state.position.position_id,
                "exit_ids": tuple(fill.event_id for fill in state.exits),
            }
        ),
        state.position.symbol,
        state.position.patterns,
        state.entry.session,
        state.exits[-1].session,
        quantity,
        state.position.submitted_limit,
        state.entry.price,
        exit_price,
        state.position.initial_stop,
        gross,
        Decimal(0),
        costs,
        net,
        order_risk,
        fill_risk,
        net / order_risk,
        net / fill_risk,
        favorable / order_risk,
        adverse / order_risk,
        favorable / fill_risk,
        adverse / fill_risk,
        exit_reason,
        tuple(dict.fromkeys(state.observed_triggers)),
        state.post_fill_resistance,
        state.decision.analysis_regime,
        True,
        None,
    )
