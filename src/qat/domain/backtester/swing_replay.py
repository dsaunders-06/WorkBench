"""Ordered, deterministic replay for the authoritative swing lifecycle."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Protocol

from qat.domain.backtester.swing_events import (
    CashDividendEvent,
    DelistingEvent,
    DividendReceivable,
    SplitEvent,
    SuspensionEvent,
    SwingMarketEvent,
    SymbolChangeEvent,
    apply_split_to_pending,
    apply_split_to_position,
    apply_symbol_change_to_pending,
    apply_symbol_change_to_position,
)
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
    apply_dividend_cash,
    apply_fills,
    mark_to_market,
)
from qat.domain.backtester.swing_results import (
    CorporateActionEvidence,
    FillAmbiguity,
    LifecycleActionSeries,
    PostFillResistanceDiagnostic,
    ReplayArm,
    RunStatus,
    SimulatedFill,
    SwingReplayResult,
    SwingTrade,
)
from qat.domain.strategies.authoritative_swing.engine import (
    raw_order_terms,
    raw_resistance_rule,
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
    schedule_exit,
)
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    FinalBar,
    RuleEvidence,
    RuleOutcome,
    SetupDecision,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor, to_raw_price
from qat.domain.strategies.authoritative_swing.resistance import (
    find_resistance_zones,
    resistance_history,
    three_year_cutoff,
)
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
    size_for_risk,
    size_instruction,
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
    eligible_dividends: Decimal = Decimal(0)
    quantity_ratio: Fraction = Fraction(1, 1)


def _entry_basis_price(price: Decimal, state: _TradeState) -> Decimal:
    ratio = state.quantity_ratio
    return to_raw_price(price, SplitFactor(ratio.denominator, ratio.numerator))


def _event_order(event: SwingMarketEvent) -> tuple[int, str, str]:
    precedence = {
        CashDividendEvent: 0,
        SplitEvent: 1,
        SymbolChangeEvent: 2,
        SuspensionEvent: 3,
        DelistingEvent: 4,
    }
    return precedence[type(event)], event.symbol, event.event_id


def _confirmed(fill: SimulatedFill) -> ConfirmedFill:
    return ConfirmedFill(
        fill.event_id,
        fill.session,
        fill.side,
        fill.quantity,
        fill.price,
        fill.reason,
    )


def _terminal_fill(
    position: SwingPosition,
    session: date,
    price: Decimal,
    reason: str,
    source_event_id: str | None = None,
) -> SimulatedFill:
    return SimulatedFill(
        stable_decision_id(
            {
                "kind": reason,
                "position_id": position.position_id,
                "session": session,
                "price": price,
                "source_event_id": source_event_id,
            }
        ),
        position.symbol,
        session,
        "sell",
        position.open_quantity,
        price,
        Decimal(0),
        reason,
        source_event_id=source_event_id,
    )


def _corporate_action_evidence(
    event: SplitEvent | SymbolChangeEvent,
    before: PendingEntry | SwingPosition,
    after: PendingEntry | SwingPosition,
) -> CorporateActionEvidence:
    if isinstance(before, PendingEntry) and isinstance(after, PendingEntry):
        position_id = before.instruction_id
        quantity_before, quantity_after = before.quantity, after.quantity
        entry_before, entry_after = before.submitted_limit, after.submitted_limit
        stop_before, stop_after = before.initial_stop, after.initial_stop
        target_before = target_after = None
    elif isinstance(before, SwingPosition) and isinstance(after, SwingPosition):
        position_id = before.position_id
        quantity_before, quantity_after = before.open_quantity, after.open_quantity
        entry_before, entry_after = before.entry_fill, after.entry_fill
        stop_before, stop_after = before.current_stop, after.current_stop
        target_before, target_after = before.target_price, after.target_price
    else:
        raise TypeError("corporate-action evidence requires matching lifecycle types")
    return CorporateActionEvidence(
        event.event_id,
        "split" if isinstance(event, SplitEvent) else "symbol_change",
        position_id,
        event.effective_session,
        before.symbol,
        after.symbol,
        quantity_before,
        quantity_after,
        entry_before,
        entry_after,
        stop_before,
        stop_after,
        target_before,
        target_after,
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
        final_entry_session: date | None = None,
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
        self._final_entry_session = final_entry_session

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
            dates[0] + timedelta(days=offset) for offset in range((dates[-1] - dates[0]).days + 1)
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
        event_ids = tuple(event.event_id for event in self._corporate_actions)
        if len(event_ids) != len(set(event_ids)):
            reasons.append("corporate-action identities are duplicated")
        for event in self._corporate_actions:
            row = by_date.get(event.effective_session)
            if row is None or not row.is_tradable:
                reasons.append(f"corporate action {event.event_id} lacks a tradable session")
            if event.symbol not in self._bars:
                reasons.append(f"corporate action {event.event_id} lacks symbol history")
            if isinstance(event, SymbolChangeEvent) and event.new_symbol not in self._bars:
                reasons.append(f"symbol change {event.event_id} lacks new-symbol history")
            if isinstance(event, SuspensionEvent) and any(
                bar.session >= event.effective_session
                and (event.resume_session is None or bar.session < event.resume_session)
                for bar in self._bars.get(event.symbol, ())
            ):
                reasons.append(f"suspension {event.event_id} has contradictory traded bars")
            if isinstance(event, DelistingEvent) and any(
                bar.session >= event.effective_session for bar in self._bars.get(event.symbol, ())
            ):
                reasons.append(f"delisting {event.event_id} has contradictory traded bars")
        if not self._starting_equity.is_finite() or self._starting_equity <= 0:
            reasons.append("starting equity must be finite and positive")
        tradable = tuple(row.calendar_date for row in self._calendar_rows if row.is_tradable)
        if self._final_entry_session is not None:
            if self._final_entry_session not in tradable:
                reasons.append("final entry session is absent from the official calendar")
            elif len(tradable) - tradable.index(self._final_entry_session) - 1 < 63:
                reasons.append("the authorized 63-session outcome tail is incomplete")
            elif dates[-1] > tradable[tradable.index(self._final_entry_session) + 63]:
                reasons.append("calendar includes rows beyond authorized T64")
        elif any(
            isinstance(event, DelistingEvent)
            and event.realizable_price is None
            or isinstance(event, SuspensionEvent)
            and event.resume_session is None
            for event in self._corporate_actions
        ):
            reasons.append("unresolved market event requires an authorized 63-session tail")
        return tuple(dict.fromkeys(reasons))

    def run(self) -> SwingReplayResult:
        invalid_reasons = self._validate_inputs()
        if invalid_reasons:
            return _empty_result(status=RunStatus.INVALID, invalid_reasons=invalid_reasons)

        bars_by_session = {
            symbol: {bar.session: bar for bar in items} for symbol, items in self._bars.items()
        }
        portfolio = PortfolioState(self._starting_equity, self._starting_equity)
        pending: dict[str, PendingEntry] = {}
        decisions: list[SetupDecision] = []
        signal_decisions: list[SetupDecision] = []
        position_events: list[LifecycleAction] = []
        fills: list[SimulatedFill] = []
        trades: list[SwingTrade] = []
        corporate_action_evidence: list[CorporateActionEvidence] = []
        dividend_entitlements: list[DividendReceivable] = []
        equity = []
        abstentions: list[RuleEvidence] = []
        ambiguities: list[FillAmbiguity] = []
        trade_states: dict[str, _TradeState] = {}
        decision_by_id: dict[str, SetupDecision] = {}
        used_breakouts: set[str] = set()
        consumed_patterns: set[str] = set()
        tradable_sessions = tuple(
            row.calendar_date for row in self._calendar_rows if row.is_tradable
        )
        official_ordinal = {day: index for index, day in enumerate(tradable_sessions)}
        terminal_session = (
            tradable_sessions[tradable_sessions.index(self._final_entry_session) + 63]
            if self._final_entry_session is not None
            else None
        )
        events_by_session: dict[date, list[SwingMarketEvent]] = defaultdict(list)
        for event in self._corporate_actions:
            events_by_session[event.effective_session].append(event)
        receivables: dict[str, DividendReceivable] = {}
        active_suspensions: dict[str, date | None] = {}
        suspension_event_ids: dict[str, str] = {}
        unresolved_delistings: dict[str, str] = {}
        last_traded_close: dict[str, Decimal] = {}

        for row in self._calendar_rows:
            if not row.is_tradable:
                for receivable in tuple(receivables.values()):
                    if receivable.payment_date == row.calendar_date:
                        portfolio = apply_dividend_cash(
                            portfolio, receivable.event_id, receivable.face_value
                        )
                        receivables.pop(receivable.event_id)
                continue
            session = row.calendar_date
            session_bars = {
                symbol: indexed[session]
                for symbol, indexed in bars_by_session.items()
                if session in indexed
            }

            for event in sorted(events_by_session[session], key=_event_order):
                if isinstance(event, SplitEvent):
                    if event.symbol in last_traded_close:
                        last_traded_close[event.symbol] = to_raw_price(
                            last_traded_close[event.symbol],
                            SplitFactor(event.numerator, event.denominator),
                        )
                    affected_quantities = (
                        () if event.symbol not in pending else (pending[event.symbol].quantity,)
                    ) + tuple(
                        quantity
                        for position in portfolio.positions
                        if position.symbol == event.symbol
                        for quantity in (
                            position.total_quantity,
                            position.banked_quantity,
                            position.runner_quantity,
                        )
                    )
                    if any(
                        quantity * event.numerator % event.denominator
                        for quantity in affected_quantities
                    ):
                        return _empty_result(
                            status=RunStatus.INVALID,
                            invalid_reasons=(
                                f"split {event.event_id} requires a fractional-share outcome",
                            ),
                        )
                    if event.symbol in pending:
                        before = pending[event.symbol]
                        pending[event.symbol] = apply_split_to_pending(before, event)
                        corporate_action_evidence.append(
                            _corporate_action_evidence(event, before, pending[event.symbol])
                        )
                    transformed: list[SwingPosition] = []
                    for position in portfolio.positions:
                        updated = apply_split_to_position(position, event)
                        if updated is not position:
                            corporate_action_evidence.append(
                                _corporate_action_evidence(event, position, updated)
                            )
                            state = trade_states[position.position_id]
                            state.quantity_ratio *= Fraction(event.numerator, event.denominator)
                        transformed.append(updated)
                    portfolio = replace(portfolio, positions=tuple(transformed))
                elif isinstance(event, SymbolChangeEvent):
                    if event.symbol in last_traded_close:
                        last_traded_close[event.new_symbol] = last_traded_close.pop(event.symbol)
                    if event.symbol in active_suspensions:
                        active_suspensions[event.new_symbol] = active_suspensions.pop(event.symbol)
                        suspension_event_ids[event.new_symbol] = suspension_event_ids.pop(
                            event.symbol
                        )
                    if event.symbol in unresolved_delistings:
                        unresolved_delistings[event.new_symbol] = unresolved_delistings.pop(
                            event.symbol
                        )
                    if event.symbol in pending:
                        before = pending.pop(event.symbol)
                        pending[event.new_symbol] = apply_symbol_change_to_pending(before, event)
                        corporate_action_evidence.append(
                            _corporate_action_evidence(event, before, pending[event.new_symbol])
                        )
                    transformed = []
                    for position in portfolio.positions:
                        updated = apply_symbol_change_to_position(position, event)
                        if updated is not position:
                            corporate_action_evidence.append(
                                _corporate_action_evidence(event, position, updated)
                            )
                            trade_states[position.position_id].position = updated
                        transformed.append(updated)
                    portfolio = replace(
                        portfolio,
                        positions=tuple(transformed),
                        pending_allocations=tuple(
                            (
                                replace(allocation, symbol=event.new_symbol)
                                if allocation.symbol == event.symbol
                                else allocation
                            )
                            for allocation in portfolio.pending_allocations
                        ),
                    )
                elif isinstance(event, SuspensionEvent):
                    active_suspensions[event.symbol] = event.resume_session
                    suspension_event_ids[event.symbol] = event.event_id
                elif isinstance(event, DelistingEvent):
                    if event.realizable_price is None:
                        unresolved_delistings[event.symbol] = event.event_id
                    else:
                        for position in tuple(portfolio.positions):
                            if position.symbol == event.symbol:
                                portfolio = self._apply_terminal_exit(
                                    portfolio,
                                    position,
                                    session,
                                    event.realizable_price,
                                    "delisting_outcome",
                                    position_events,
                                    fills,
                                    trade_states,
                                    trades,
                                    source_event_id=event.event_id,
                                )
                elif isinstance(event, CashDividendEvent):
                    for position in portfolio.positions:
                        if position.symbol != event.symbol:
                            continue
                        face = Decimal(position.open_quantity) * event.amount_per_share
                        receivable = DividendReceivable(
                            event.event_id,
                            position.position_id,
                            event.symbol,
                            event.declaration_date,
                            event.ex_session,
                            event.record_date,
                            event.payment_date,
                            position.open_quantity,
                            event.amount_per_share,
                            face,
                        )
                        receivables[event.event_id] = receivable
                        dividend_entitlements.append(receivable)
                        trade_states[position.position_id].eligible_dividends += face
                        portfolio = replace(
                            portfolio,
                            dividend_receivables=portfolio.dividend_receivables + face,
                        )
            for symbol, resume in tuple(active_suspensions.items()):
                if resume is not None and session >= resume:
                    active_suspensions.pop(symbol)
                    suspension_event_ids.pop(symbol)
            last_traded_close.update(
                (symbol, bar.raw.close) for symbol, bar in session_bars.items()
            )

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
            if session == terminal_session:
                for position in tuple(portfolio.positions):
                    if (
                        position.symbol in unresolved_delistings
                        or position.symbol in active_suspensions
                    ):
                        portfolio = self._apply_terminal_exit(
                            portfolio,
                            position,
                            session,
                            Decimal(0),
                            "terminal_zero",
                            position_events,
                            fills,
                            trade_states,
                            trades,
                            source_event_id=(
                                unresolved_delistings.get(position.symbol)
                                or suspension_event_ids.get(position.symbol)
                            ),
                        )
            for receivable in tuple(receivables.values()):
                if receivable.payment_date == session:
                    portfolio = apply_dividend_cash(
                        portfolio, receivable.event_id, receivable.face_value
                    )
                    receivables.pop(receivable.event_id)

            open_symbols = {position.symbol for position in portfolio.positions}
            stale_symbols = open_symbols & active_suspensions.keys()
            missing_stale = tuple(sorted(stale_symbols - last_traded_close.keys()))
            if missing_stale:
                return _empty_result(
                    status=RunStatus.INVALID,
                    invalid_reasons=tuple(
                        f"missing last traded close for halted position {symbol} on {session}"
                        for symbol in missing_stale
                    ),
                )
            zero_marked = unresolved_delistings.keys()
            missing_open = tuple(
                sorted(open_symbols - session_bars.keys() - stale_symbols - zero_marked)
            )
            if missing_open:
                return _empty_result(
                    status=RunStatus.INVALID,
                    invalid_reasons=tuple(
                        f"missing mark for open position {symbol} on {session}"
                        for symbol in missing_open
                    ),
                )
            closing_prices = {symbol: bar.raw.close for symbol, bar in session_bars.items()}
            stale_marks = tuple(
                (symbol, last_traded_close[symbol]) for symbol in sorted(stale_symbols)
            )
            closing_prices.update(stale_marks)
            closing_prices.update((symbol, Decimal(0)) for symbol in zero_marked)
            point = mark_to_market(
                portfolio,
                session,
                closing_prices,
                stale_marks,
            )
            abstentions.extend(
                RuleEvidence(
                    "stale_halt_mark",
                    RuleOutcome.ABSTAIN,
                    measured=f"{symbol}:{price}",
                    reason="last traded close carried while trading is suspended",
                )
                for symbol, price in stale_marks
            )
            portfolio = self._evaluate_closes(
                portfolio,
                session_bars,
                trade_states,
                abstentions,
            )
            advanced = tuple(
                _advance_official_holding_session(position, session, official_ordinal)
                for position in portfolio.positions
            )
            for position in advanced:
                trade_states[position.position_id].position = position
            portfolio = replace(portfolio, positions=advanced)

            qualified: list[SetupDecision] = []
            blocked_symbols = {position.symbol for position in portfolio.positions} | set(pending)
            if self._final_entry_session is not None and session >= self._final_entry_session:
                equity.append(point)
                continue
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
                    current_equity=point.equity,
                )
                if qualified and portfolio.available_cash > 0
                else ()
            )
            allocated_ids = {allocation.decision.decision_id for allocation in allocations}
            abstentions.extend(
                RuleEvidence(
                    "portfolio_allocation",
                    RuleOutcome.ABSTAIN,
                    measured=decision.symbol,
                    reason="available cash cannot fund the minimum two-share allocation",
                )
                for decision in qualified
                if decision.decision_id not in allocated_ids
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

        try:
            (
                signal_trades,
                signal_abstentions,
                signal_action_evidence,
                signal_dividend_entitlements,
            ) = replay_signal_candidates(
                calendar_rows=self._calendar_rows,
                bars=self._bars,
                decisions=signal_decisions,
                reference_equity=self._starting_equity,
                costs=self._costs,
                liquidity=self._liquidity,
                ambiguity_policy=self._ambiguity_policy,
                corporate_actions=self._corporate_actions,
                terminal_session=terminal_session,
            )
        except ValueError as error:
            return _empty_result(
                status=RunStatus.INVALID,
                invalid_reasons=(f"signal lifecycle event is incomplete: {error}",),
            )
        abstentions.extend(signal_abstentions)
        abstentions.extend(
            RuleEvidence(
                "post_fill_resistance",
                RuleOutcome.ABSTAIN,
                measured=trade.trade_id,
                reason="three-year resistance history or zone construction is invalid",
            )
            for trade in trades
            if trade.post_fill_resistance is PostFillResistanceDiagnostic.ABSTAIN
        )
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
            corporate_action_evidence=tuple(corporate_action_evidence),
            dividend_entitlements=tuple(dividend_entitlements),
            signal_corporate_action_evidence=signal_action_evidence,
            signal_dividend_entitlements=signal_dividend_entitlements,
        )

    def _apply_terminal_exit(
        self,
        portfolio: PortfolioState,
        position: SwingPosition,
        session: date,
        price: Decimal,
        reason: str,
        actions: list[LifecycleAction],
        all_fills: list[SimulatedFill],
        trade_states: dict[str, _TradeState],
        trades: list[SwingTrade],
        *,
        source_event_id: str | None,
    ) -> PortfolioState:
        fill = _terminal_fill(position, session, price, reason, source_event_id)
        updated = apply_exit_fill(position, _confirmed(fill))
        portfolio = apply_fills(portfolio, (fill,))
        actions.append(_action(position.state, updated, fill, "sell_fill"))
        all_fills.append(fill)
        state = trade_states.pop(position.position_id)
        state.exits.append(fill)
        state.observed_triggers.extend(position.scheduled_exit_triggers)
        trades.append(_trade(state, updated, reason))
        return replace(
            portfolio,
            positions=tuple(
                item for item in portfolio.positions if item.position_id != position.position_id
            ),
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
            evidence = ambiguity_for_session(position, traded, self._costs, self._liquidity)
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
            state.highest_high = max(state.highest_high, _entry_basis_price(source.raw.high, state))
            state.lowest_low = min(state.lowest_low, _entry_basis_price(source.raw.low, state))
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
            source = session_bars.get(position.symbol)
            if source is None:
                positions.append(position)
                continue
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
        return _diagnostic_for_decision(decision, fill, self._bars)


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


def _advance_official_holding_session(
    position: SwingPosition,
    session: date,
    ordinal: Mapping[date, int],
) -> SwingPosition:
    """Count exchange sessions even when a halt supplies no symbol bar."""

    held = ordinal[session] - ordinal[position.entry_session] + 1
    updated = replace(position, completed_sessions=max(position.completed_sessions, held))
    if held >= 10:
        updated = schedule_exit(updated, ("time_stop",))
    return updated


def replay_signal_candidates(
    *,
    calendar_rows: Sequence[ReplayCalendarRow],
    bars: Mapping[str, Sequence[FinalBar]],
    decisions: Sequence[SetupDecision],
    reference_equity: Decimal,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    ambiguity_policy: AmbiguityPolicy = AmbiguityPolicy.CONSERVATIVE,
    corporate_actions: Sequence[SwingMarketEvent] = (),
    terminal_session: date | None = None,
) -> tuple[
    tuple[SwingTrade, ...],
    tuple[RuleEvidence, ...],
    tuple[CorporateActionEvidence, ...],
    tuple[DividendReceivable, ...],
]:
    """Replay per-pattern candidates at one fixed risk-equity reference."""

    indexed = {symbol: {bar.session: bar for bar in history} for symbol, history in bars.items()}
    by_session: dict[date, list[SetupDecision]] = defaultdict(list)
    for decision in decisions:
        if (
            decision.status is DecisionStatus.QUALIFIED
            and decision.structural_invalidation_raw is None
        ):
            raise ValueError("qualified pattern requires structural invalidation")
        if any(
            item.status is DecisionStatus.QUALIFIED and item.candidate is not None
            for item in decision.pattern_decisions
        ):
            by_session[decision.session].append(decision)

    pending: dict[tuple[str, object], PendingEntry] = {}
    pending_decisions: dict[tuple[str, object], SetupDecision] = {}
    positions: dict[tuple[str, object], SwingPosition] = {}
    trade_states: dict[tuple[str, object], _TradeState] = {}
    used_breakouts: dict[tuple[str, object], set[str]] = defaultdict(set)
    consumed_patterns: dict[tuple[str, object], set[str]] = defaultdict(set)
    trades: list[SwingTrade] = []
    abstentions: list[RuleEvidence] = []
    corporate_action_evidence: list[CorporateActionEvidence] = []
    dividend_entitlements: list[DividendReceivable] = []
    events_by_session: dict[date, list[SwingMarketEvent]] = defaultdict(list)
    for event in corporate_actions:
        events_by_session[event.effective_session].append(event)
    active_suspensions: dict[str, date | None] = {}
    suspension_event_ids: dict[str, str] = {}
    unresolved_delistings: dict[str, str] = {}
    last_traded_close: dict[str, Decimal] = {}
    official_ordinal = {
        row.calendar_date: index
        for index, row in enumerate(item for item in calendar_rows if item.is_tradable)
    }

    for row in calendar_rows:
        if not row.is_tradable:
            continue
        session = row.calendar_date
        session_bars = {
            symbol: symbol_bars[session]
            for symbol, symbol_bars in indexed.items()
            if session in symbol_bars
        }
        for event in sorted(events_by_session[session], key=_event_order):
            if isinstance(event, SplitEvent):
                if event.symbol in last_traded_close:
                    last_traded_close[event.symbol] = to_raw_price(
                        last_traded_close[event.symbol],
                        SplitFactor(event.numerator, event.denominator),
                    )
                for key, instruction in tuple(pending.items()):
                    transformed_pending = apply_split_to_pending(instruction, event)
                    if transformed_pending is not instruction:
                        corporate_action_evidence.append(
                            _corporate_action_evidence(event, instruction, transformed_pending)
                        )
                    pending[key] = transformed_pending
                for key, position in tuple(positions.items()):
                    transformed_position = apply_split_to_position(position, event)
                    if transformed_position is not position:
                        corporate_action_evidence.append(
                            _corporate_action_evidence(event, position, transformed_position)
                        )
                        trade_states[key].quantity_ratio *= Fraction(
                            event.numerator, event.denominator
                        )
                    positions[key] = transformed_position
            elif isinstance(event, SymbolChangeEvent):
                if event.symbol in last_traded_close:
                    last_traded_close[event.new_symbol] = last_traded_close.pop(event.symbol)
                if event.symbol in active_suspensions:
                    active_suspensions[event.new_symbol] = active_suspensions.pop(event.symbol)
                    suspension_event_ids[event.new_symbol] = suspension_event_ids.pop(event.symbol)
                if event.symbol in unresolved_delistings:
                    unresolved_delistings[event.new_symbol] = unresolved_delistings.pop(
                        event.symbol
                    )
                for identities in (used_breakouts, consumed_patterns):
                    for old_key in tuple(identities):
                        if old_key[0] == event.symbol:
                            new_key = (event.new_symbol, old_key[1])
                            identities[new_key].update(identities.pop(old_key))
                for key, instruction in tuple(pending.items()):
                    if instruction.symbol != event.symbol:
                        continue
                    new_key = (event.new_symbol, key[1])
                    transformed_pending = apply_symbol_change_to_pending(instruction, event)
                    corporate_action_evidence.append(
                        _corporate_action_evidence(event, instruction, transformed_pending)
                    )
                    pending[new_key] = transformed_pending
                    pending.pop(key)
                    pending_decisions[new_key] = pending_decisions.pop(key)
                for key, position in tuple(positions.items()):
                    if position.symbol != event.symbol:
                        continue
                    new_key = (event.new_symbol, key[1])
                    transformed_position = apply_symbol_change_to_position(position, event)
                    corporate_action_evidence.append(
                        _corporate_action_evidence(event, position, transformed_position)
                    )
                    positions[new_key] = transformed_position
                    positions.pop(key)
                    state = trade_states.pop(key)
                    state.position = transformed_position
                    trade_states[new_key] = state
            elif isinstance(event, SuspensionEvent):
                active_suspensions[event.symbol] = event.resume_session
                suspension_event_ids[event.symbol] = event.event_id
            elif isinstance(event, DelistingEvent):
                if event.realizable_price is None:
                    unresolved_delistings[event.symbol] = event.event_id
                else:
                    for key, position in tuple(positions.items()):
                        if position.symbol != event.symbol:
                            continue
                        fill = _terminal_fill(
                            position,
                            session,
                            event.realizable_price,
                            "delisting_outcome",
                            event.event_id,
                        )
                        updated = apply_exit_fill(position, _confirmed(fill))
                        state = trade_states.pop(key)
                        state.exits.append(fill)
                        trades.append(_trade(state, updated, fill.reason))
                        positions.pop(key)
            elif isinstance(event, CashDividendEvent):
                for key, position in positions.items():
                    if position.symbol == event.symbol:
                        face = Decimal(position.open_quantity) * event.amount_per_share
                        dividend_entitlements.append(
                            DividendReceivable(
                                event.event_id,
                                position.position_id,
                                event.symbol,
                                event.declaration_date,
                                event.ex_session,
                                event.record_date,
                                event.payment_date,
                                position.open_quantity,
                                event.amount_per_share,
                                face,
                            )
                        )
                        trade_states[key].eligible_dividends += face
        for symbol, resume in tuple(active_suspensions.items()):
            if resume is not None and session >= resume:
                active_suspensions.pop(symbol)
                suspension_event_ids.pop(symbol)
        last_traded_close.update((symbol, bar.raw.close) for symbol, bar in session_bars.items())

        for position in positions.values():
            if (
                position.symbol not in session_bars
                and position.symbol not in active_suspensions
                and position.symbol not in unresolved_delistings
            ):
                raise ValueError(f"missing signal position mark for {position.symbol} on {session}")
            if position.symbol in active_suspensions:
                price = last_traded_close.get(position.symbol)
                if price is None:
                    raise ValueError(
                        f"missing last traded close for halted signal position {position.symbol}"
                    )
                abstentions.append(
                    RuleEvidence(
                        "stale_halt_mark",
                        RuleOutcome.ABSTAIN,
                        measured=f"{position.symbol}:{price}",
                        reason="last traded close carried while trading is suspended",
                    )
                )

        if session == terminal_session:
            for key, position in tuple(positions.items()):
                if (
                    position.symbol not in unresolved_delistings
                    and position.symbol not in active_suspensions
                ):
                    continue
                fill = _terminal_fill(
                    position,
                    session,
                    Decimal(0),
                    "terminal_zero",
                    unresolved_delistings.get(position.symbol)
                    or suspension_event_ids.get(position.symbol),
                )
                updated = apply_exit_fill(position, _confirmed(fill))
                state = trade_states.pop(key)
                state.exits.append(fill)
                trades.append(_trade(state, updated, fill.reason))
                positions.pop(key)

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
                decision = pending_decisions.pop(key)
                diagnostic = _diagnostic_for_decision(decision, fill.price, bars)
                if diagnostic is PostFillResistanceDiagnostic.ABSTAIN:
                    abstentions.append(
                        RuleEvidence(
                            "post_fill_resistance",
                            RuleOutcome.ABSTAIN,
                            measured=decision.decision_id,
                            reason="three-year resistance history or zone construction is invalid",
                        )
                    )
                trade_states[key] = _TradeState(
                    decision,
                    fill,
                    position,
                    [],
                    fill.price,
                    fill.price,
                    [],
                    diagnostic,
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
            pending_decisions.pop(key, None)

        for key, position in tuple(sorted(positions.items(), key=lambda item: str(item[0]))):
            source = session_bars.get(position.symbol)
            if source is None:
                continue
            state = trade_states[key]
            state.highest_high = max(state.highest_high, _entry_basis_price(source.raw.high, state))
            state.lowest_low = min(state.lowest_low, _entry_basis_price(source.raw.low, state))
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

        for key, position in tuple(positions.items()):
            advanced = _advance_official_holding_session(position, session, official_ordinal)
            positions[key] = advanced
            trade_states[key].position = advanced

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
                if candidate is None:
                    raise ValueError("qualified pattern requires a candidate")
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
                if candidate.pattern_instance_id in consumed_patterns[key] or (
                    candidate.breakout_event_id is not None
                    and candidate.breakout_event_id in used_breakouts[key]
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
                analytical_limit = next(
                    (
                        rule.threshold
                        for rule in matching[0].rules
                        if rule.code == "analytical_resistance"
                        and rule.outcome is RuleOutcome.PASS
                        and isinstance(rule.threshold, Decimal)
                    ),
                    None,
                )
                if analytical_limit is not None:
                    signal_bar = indexed[decision.symbol][decision.session]
                    try:
                        limit, stop, raw_invalidation = raw_order_terms(
                            analytical_limit,
                            candidate.analytical_invalidation,
                            signal_bar.raw_to_adjusted_price_factor,
                        )
                    except ValueError as error:
                        abstentions.append(
                            RuleEvidence(
                                "isolated_raw_terms",
                                RuleOutcome.ABSTAIN,
                                measured=f"{decision.symbol}:{pattern.value}",
                                reason=str(error),
                            )
                        )
                        continue
                    resistance_bars = tuple(
                        bar
                        for bar in bars[decision.symbol]
                        if three_year_cutoff(decision.session) <= bar.session < decision.session
                    )
                    try:
                        zones = find_resistance_zones(resistance_bars)
                    except ValueError as error:
                        abstentions.append(
                            RuleEvidence(
                                "isolated_raw_resistance",
                                RuleOutcome.ABSTAIN,
                                measured=f"{decision.symbol}:{pattern.value}",
                                reason=str(error),
                            )
                        )
                        continue
                    raw_resistance = raw_resistance_rule(
                        limit, stop, zones, signal_bar.raw_to_adjusted_price_factor
                    )
                    if raw_resistance.outcome is not RuleOutcome.PASS:
                        abstentions.append(raw_resistance)
                        continue
                elif len(decision.patterns) == 1 and decision.status is DecisionStatus.QUALIFIED:
                    if decision.entry_limit_raw is None:
                        raise ValueError("qualified pattern requires an entry limit")
                    if decision.initial_stop_raw is None:
                        raise ValueError("qualified pattern requires an initial stop")
                    limit = decision.entry_limit_raw
                    stop = decision.initial_stop_raw
                    single_invalidation = decision.structural_invalidation_raw
                    if single_invalidation is None:
                        raise ValueError("qualified pattern requires structural invalidation")
                    raw_invalidation = single_invalidation
                else:
                    abstentions.append(
                        RuleEvidence(
                            "isolated_raw_terms",
                            RuleOutcome.ABSTAIN,
                            measured=f"{decision.symbol}:{pattern.value}",
                            reason="qualified pattern lacks independent analytical limit",
                        )
                    )
                    continue
                if analytical_limit is not None:
                    sizing = size_instruction(
                        equity=reference_equity,
                        available_cash=reference_equity,
                        limit=limit,
                        stop=stop,
                        bars=tuple(
                            bar for bar in bars[decision.symbol] if bar.session <= decision.session
                        ),
                        signal_session=decision.session,
                        cost_profile=costs,
                        liquidity_profile=liquidity,
                    )
                    if sizing.status is DecisionStatus.ABSTAIN:
                        abstentions.extend(
                            rule for rule in sizing.evidence if rule.outcome is RuleOutcome.ABSTAIN
                        )
                        continue
                    risk_quantity = sizing.risk_quantity
                    capacity = sizing.capacity_quantity
                    quantity = sizing.quantity
                else:
                    risk_quantity = size_for_risk(
                        reference_equity, limit, stop, costs, liquidity
                    ).quantity
                    capacity = decision.capacity_quantity or risk_quantity
                    quantity = min(risk_quantity, capacity)
                if quantity < 2:
                    abstentions.append(
                        RuleEvidence(
                            "isolated_minimum_quantity",
                            RuleOutcome.ABSTAIN,
                            measured=quantity,
                            threshold=2,
                            reason=f"{decision.symbol}:{pattern.value} cannot fund two shares",
                        )
                    )
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
                    status=DecisionStatus.QUALIFIED,
                    entry_limit_raw=limit,
                    initial_stop_raw=stop,
                    structural_invalidation_raw=raw_invalidation,
                    risk_quantity=risk_quantity,
                    capacity_quantity=capacity,
                    quantity=quantity,
                )
                instruction = pending_entry_from_setup(isolated)
                pending[key] = instruction
                pending_decisions[key] = isolated
                used_breakouts[key].update(instruction.breakout_event_ids)

    return (
        tuple(trades),
        tuple(abstentions),
        tuple(corporate_action_evidence),
        tuple(dividend_entitlements),
    )


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
        return PostFillResistanceDiagnostic.ABSTAIN
    symbol_bars = tuple(bars[decision.symbol])
    try:
        prior = resistance_history(decision.session, symbol_bars)
        analytical_zones = find_resistance_zones(prior)
    except ValueError:
        return PostFillResistanceDiagnostic.ABSTAIN
    eligible = tuple(bar for bar in symbol_bars if bar.session == decision.session)
    if len(eligible) != 1:
        return PostFillResistanceDiagnostic.ABSTAIN
    factor = eligible[0].raw_to_adjusted_price_factor
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
    exit_notional = sum((Decimal(fill.quantity) * fill.price for fill in state.exits), Decimal(0))
    exit_price = exit_notional / Decimal(quantity)
    gross = exit_notional - Decimal(quantity) * state.entry.price
    costs = state.entry.cost + sum((fill.cost for fill in state.exits), Decimal(0))
    net = gross + state.eligible_dividends - costs
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
        state.eligible_dividends,
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
