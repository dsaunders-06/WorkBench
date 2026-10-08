"""Pure orchestration for authoritative Phase 2 swing setup evidence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import fields, replace
from datetime import date
from decimal import Decimal

from qat.data.broker.ticks import previous_raw_order_tick, tick_size
from qat.domain.strategies.authoritative_swing.bull_flag import evaluate_bull_flag
from qat.domain.strategies.authoritative_swing.double_bottom import evaluate_double_bottom
from qat.domain.strategies.authoritative_swing.ema_pullback import evaluate_ema_pullback
from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    Pattern,
    PatternCandidate,
    PatternDecision,
    RuleEvidence,
    RuleOutcome,
    SetupDecision,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor, to_raw_price
from qat.domain.strategies.authoritative_swing.resistance import (
    ResistanceDecision,
    ResistanceZone,
    analytical_entry_ceiling_for,
)
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
    size_instruction,
)

STRATEGY_VERSION = "phase2-swing-v1"
SCHEMA_VERSION = "swing-evidence-v1"

PatternEvaluator = Callable[[SwingHistory, Sequence[date]], PatternDecision]


def _floor_raw_order_price(price: Decimal) -> Decimal:
    if price <= 0 or not price.is_finite():
        raise ValueError("raw order price must be finite and positive")
    tick = tick_size(price, "ASX")
    if price % tick == 0:
        return price
    return previous_raw_order_tick(price, "ASX")


def raw_order_terms(
    analytical_limit: Decimal,
    analytical_invalidation: Decimal,
    factor: SplitFactor,
) -> tuple[Decimal, Decimal, Decimal]:
    """Derive one pattern's exact raw limit, protective stop, and invalidation."""

    raw_limit = _floor_raw_order_price(to_raw_price(analytical_limit, factor))
    raw_invalidation = to_raw_price(analytical_invalidation, factor)
    raw_stop = previous_raw_order_tick(raw_invalidation, "ASX")
    return raw_limit, raw_stop, raw_invalidation


def _resistance_rule(result: ResistanceDecision) -> RuleEvidence:
    outcome = {
        DecisionStatus.QUALIFIED: RuleOutcome.PASS,
        DecisionStatus.REJECTED: RuleOutcome.FAIL,
        DecisionStatus.ABSTAIN: RuleOutcome.ABSTAIN,
    }[result.status]
    measured: Decimal | str | None
    if result.relevant_zone is None:
        measured = "no_relevant_zone"
    else:
        measured = f"{result.relevant_zone.lower}..{result.relevant_zone.upper}"
    return RuleEvidence(
        "analytical_resistance",
        outcome,
        measured=measured,
        threshold=result.limit_price,
        reason=result.reason,
    )


def raw_resistance_rule(
    entry: Decimal,
    stop: Decimal,
    zones: Sequence[ResistanceZone],
    factor: SplitFactor,
) -> RuleEvidence:
    raw_zones = tuple(
        sorted(
            (
                (to_raw_price(zone.lower, factor), to_raw_price(zone.upper, factor))
                for zone in zones
            ),
            key=lambda edges: edges,
        )
    )
    relevant = tuple(edges for edges in raw_zones if edges[1] >= entry)
    if not relevant:
        return RuleEvidence(
            "raw_resistance",
            RuleOutcome.PASS,
            measured="no_relevant_zone",
        )
    lower, upper = min(relevant, key=lambda edges: (max(entry, edges[0]), edges))
    if lower <= entry <= upper:
        return RuleEvidence(
            "raw_resistance",
            RuleOutcome.FAIL,
            measured=f"inside:{lower}..{upper}",
            threshold=lower,
            reason="raw limit lies inside resistance zone",
        )
    two_r = entry + Decimal(2) * (entry - stop)
    clear = two_r < lower
    return RuleEvidence(
        "raw_resistance",
        RuleOutcome.PASS if clear else RuleOutcome.FAIL,
        measured=two_r,
        threshold=lower,
        reason=None if clear else "raw 2R path reaches resistance",
    )


def _with_decision_id(decision: SetupDecision) -> SetupDecision:
    semantic = {
        field.name: getattr(decision, field.name)
        for field in fields(decision)
        if field.name != "decision_id"
    }
    return replace(decision, decision_id=stable_decision_id(semantic))


class AuthoritativeSwingEngine:
    """Evaluate all approved patterns and produce one immutable setup envelope."""

    def __init__(
        self,
        official_sessions: Sequence[date],
        evaluators: Sequence[PatternEvaluator] | None = None,
    ) -> None:
        self._official_sessions = tuple(official_sessions)
        self._evaluators = (
            tuple(evaluators)
            if evaluators is not None
            else (
                evaluate_ema_pullback,
                evaluate_bull_flag,
                evaluate_double_bottom,
            )
        )

    def evaluate_patterns(
        self, history: SwingHistory, evaluation_session: date | None = None
    ) -> tuple[PatternDecision, ...]:
        if not history.daily:
            return tuple(evaluator(history, ()) for evaluator in self._evaluators)
        session = evaluation_session or history.daily[-1].session
        prefix = SwingHistory(
            history.symbol,
            tuple(bar for bar in history.daily if bar.session <= session),
        )
        sessions = tuple(item for item in self._official_sessions if item <= session)
        return tuple(evaluator(prefix, sessions) for evaluator in self._evaluators)

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
        if not history.daily:
            session = evaluation_session or date.min
            pattern_decisions = self.evaluate_patterns(history, session)
            return self._empty_decision(
                history.symbol,
                session,
                pattern_decisions,
                DecisionStatus.ABSTAIN,
                (),
                analysis_regime,
                (RuleEvidence("daily_history", RuleOutcome.ABSTAIN, reason="no bars"),),
            )

        session = evaluation_session or history.daily[-1].session
        prefix = SwingHistory(
            history.symbol,
            tuple(bar for bar in history.daily if bar.session <= session),
        )
        if not prefix.daily or prefix.daily[-1].session != session:
            return self._empty_decision(
                history.symbol,
                session,
                (),
                DecisionStatus.ABSTAIN,
                tuple(bar.digest for bar in prefix.daily),
                analysis_regime,
                (
                    RuleEvidence(
                        "evaluation_session",
                        RuleOutcome.ABSTAIN,
                        reason="evaluation session has no finalized input bar",
                    ),
                ),
            )
        sessions = tuple(item for item in self._official_sessions if item <= session)
        original = tuple(evaluator(prefix, sessions) for evaluator in self._evaluators)
        processed: list[PatternDecision] = []
        eligible: list[tuple[PatternDecision, PatternCandidate, ResistanceDecision]] = []

        for decision in original:
            if decision.status is not DecisionStatus.QUALIFIED or decision.candidate is None:
                processed.append(decision)
                continue
            if decision.candidate.signal_session != session:
                processed.append(
                    replace(
                        decision,
                        status=DecisionStatus.ABSTAIN,
                        rules=decision.rules
                        + (
                            RuleEvidence(
                                "signal_session",
                                RuleOutcome.ABSTAIN,
                                reason="candidate session differs from evaluation session",
                            ),
                        ),
                    )
                )
                continue
            resistance = analytical_entry_ceiling_for(decision.candidate, prefix.daily)
            updated = replace(
                decision,
                status=resistance.status,
                rules=decision.rules + (_resistance_rule(resistance),),
            )
            processed.append(updated)
            if resistance.status is DecisionStatus.QUALIFIED and resistance.limit_price is not None:
                eligible.append((updated, decision.candidate, resistance))

        input_digests = tuple(bar.digest for bar in prefix.daily)
        if not eligible:
            status = (
                DecisionStatus.ABSTAIN
                if any(item.status is DecisionStatus.ABSTAIN for item in processed)
                else DecisionStatus.REJECTED
            )
            return self._empty_decision(
                history.symbol,
                session,
                tuple(processed),
                status,
                input_digests,
                analysis_regime,
                (
                    RuleEvidence(
                        "qualified_patterns",
                        (
                            RuleOutcome.ABSTAIN
                            if status is DecisionStatus.ABSTAIN
                            else RuleOutcome.FAIL
                        ),
                        measured=0,
                    ),
                ),
            )

        constituents = tuple(item[0].pattern for item in eligible)
        analytical_limit = min(item[2].limit_price for item in eligible if item[2].limit_price)
        analytical_stop = min(item[1].analytical_invalidation for item in eligible)
        resistance = eligible[0][2]
        setup_rules: list[RuleEvidence] = []

        if len(eligible) > 1:
            first_candidate = eligible[0][1]
            combined = replace(
                first_candidate,
                pattern_instance_id=stable_decision_id(
                    {
                        "kind": "confluence",
                        "members": tuple(item[1].pattern_instance_id for item in eligible),
                    }
                ),
                breakout_event_id=None,
                analytical_signal_close=analytical_limit,
                analytical_invalidation=analytical_stop,
            )
            resistance = analytical_entry_ceiling_for(combined, prefix.daily)
            setup_rules.append(_resistance_rule(resistance))
            if resistance.status is not DecisionStatus.QUALIFIED or resistance.limit_price is None:
                return self._empty_decision(
                    history.symbol,
                    session,
                    tuple(processed),
                    resistance.status,
                    input_digests,
                    analysis_regime,
                    tuple(setup_rules),
                    constituents,
                )
            analytical_limit = resistance.limit_price

        factor = prefix.daily[-1].raw_to_adjusted_price_factor
        try:
            raw_limit, raw_stop, raw_invalidation = raw_order_terms(
                analytical_limit, analytical_stop, factor
            )
        except ValueError as error:
            setup_rules.append(RuleEvidence("raw_conversion", RuleOutcome.FAIL, reason=str(error)))
            return self._empty_decision(
                history.symbol,
                session,
                tuple(processed),
                DecisionStatus.REJECTED,
                input_digests,
                analysis_regime,
                tuple(setup_rules),
                constituents,
            )

        raw_resistance = raw_resistance_rule(raw_limit, raw_stop, resistance.zones, factor)
        setup_rules.append(raw_resistance)
        if raw_resistance.outcome is not RuleOutcome.PASS:
            return self._empty_decision(
                history.symbol,
                session,
                tuple(processed),
                DecisionStatus.REJECTED,
                input_digests,
                analysis_regime,
                tuple(setup_rules),
                constituents,
                raw_limit,
                raw_stop,
            )

        sizing = size_instruction(
            equity=equity,
            available_cash=equity if available_cash is None else available_cash,
            limit=raw_limit,
            stop=raw_stop,
            bars=prefix.daily,
            signal_session=session,
            cost_profile=costs,
            liquidity_profile=liquidity,
        )
        setup_rules.extend(sizing.evidence)
        setup_decision = SetupDecision(
            strategy_version=STRATEGY_VERSION,
            schema_version=SCHEMA_VERSION,
            decision_id="",
            symbol=history.symbol,
            session=session,
            status=sizing.status,
            patterns=constituents,
            pattern_decisions=tuple(processed),
            entry_limit_raw=raw_limit,
            initial_stop_raw=raw_stop,
            risk_quantity=sizing.risk_quantity,
            capacity_quantity=sizing.capacity_quantity,
            quantity=sizing.quantity,
            input_digests=input_digests,
            analysis_regime=analysis_regime,
            setup_rules=tuple(setup_rules),
            structural_invalidation_raw=raw_invalidation,
        )
        return _with_decision_id(setup_decision)

    @staticmethod
    def _empty_decision(
        symbol: str,
        session: date,
        pattern_decisions: tuple[PatternDecision, ...],
        status: DecisionStatus,
        input_digests: tuple[str, ...],
        analysis_regime: str | None,
        setup_rules: tuple[RuleEvidence, ...],
        patterns: tuple[Pattern, ...] = (),
        entry_limit_raw: Decimal | None = None,
        initial_stop_raw: Decimal | None = None,
    ) -> SetupDecision:
        return _with_decision_id(
            SetupDecision(
                strategy_version=STRATEGY_VERSION,
                schema_version=SCHEMA_VERSION,
                decision_id="",
                symbol=symbol,
                session=session,
                status=status,
                patterns=patterns,
                pattern_decisions=pattern_decisions,
                entry_limit_raw=entry_limit_raw,
                initial_stop_raw=initial_stop_raw,
                risk_quantity=0,
                capacity_quantity=0,
                quantity=0,
                input_digests=input_digests,
                analysis_regime=analysis_regime,
                setup_rules=setup_rules,
            )
        )
