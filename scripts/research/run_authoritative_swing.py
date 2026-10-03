"""Offline-only Phase 2C engineering evidence runner."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path

import numpy as np

from qat.domain.backtester.swing_artifacts import SwingArtifactRun, write_swing_artifacts
from qat.domain.backtester.swing_dataset import (
    DatasetIntegrityError,
    DatasetTier,
    PartitionAccess,
    SwingDataset,
    load_static_asx_engineering_dataset,
    load_swing_dataset,
    validate_catalog,
)
from qat.domain.backtester.swing_events import (
    CashDividendEvent,
    SplitEvent,
    SuspensionEvent,
    SwingMarketEvent,
)
from qat.domain.backtester.swing_fills import AmbiguityPolicy
from qat.domain.backtester.swing_promotion import PromotionCase, evaluate_promotion
from qat.domain.backtester.swing_replay import (
    AuthoritativeSwingReplay,
    ReplayCalendarRow,
    SessionKind,
)
from qat.domain.backtester.swing_results import (
    LifecycleActionSeries,
    ReplayArm,
    ReplayEquityPoint,
    RunStatus,
    SwingReplayResult,
)
from qat.domain.backtester.swing_statistics import summarize_swing_statistics
from qat.domain.strategies.authoritative_swing.bull_flag import evaluate_bull_flag
from qat.domain.strategies.authoritative_swing.double_bottom import evaluate_double_bottom
from qat.domain.strategies.authoritative_swing.ema_pullback import evaluate_ema_pullback
from qat.domain.strategies.authoritative_swing.engine import (
    AuthoritativeSwingEngine,
    PatternEvaluator,
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
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor, canonical_decimal
from qat.domain.strategies.authoritative_swing.sizing import ExactCostProfile, LiquidityProfile

_STARTING_EQUITY = Decimal("10000")
_COSTS = ExactCostProfile(
    "phase2-engineering-v1",
    "ASX engineering",
    Decimal("5"),
    Decimal("6"),
    "AUD",
    False,
    Decimal("0"),
)
_LIQUIDITY = LiquidityProfile(
    "phase2-engineering-v1", Decimal("0.05"), Decimal("5"), Decimal("10"), provisional=True
)
_PATTERN_ARM = {
    ReplayArm.EMA_PULLBACK: Pattern.EMA_PULLBACK,
    ReplayArm.BULL_FLAG: Pattern.BULL_FLAG,
    ReplayArm.DOUBLE_BOTTOM: Pattern.DOUBLE_BOTTOM,
}


@dataclass(frozen=True, slots=True)
class _GoldenFixture:
    calendar: tuple[ReplayCalendarRow, ...]
    sessions: tuple[date, ...]
    bars: Mapping[str, tuple[FinalBar, ...]]
    membership: Mapping[date, frozenset[str]]
    benchmark: tuple[FinalBar, ...]
    decisions: Mapping[tuple[str, date], SetupDecision]
    corporate_actions: tuple[SwingMarketEvent, ...]
    final_entry_session: date


class _GoldenEngine:
    def __init__(
        self,
        decisions: Mapping[tuple[str, date], SetupDecision],
        arm: ReplayArm,
        risk_multiplier: int = 1,
    ) -> None:
        self._decisions = decisions
        self._arm = arm
        self._risk_multiplier = risk_multiplier

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
        del equity, costs, liquidity, available_cash
        session = evaluation_session or history.daily[-1].session
        decision = self._decisions.get((history.symbol, session))
        if decision is not None and (
            self._arm is ReplayArm.COMBINED or _PATTERN_ARM[self._arm] in decision.patterns
        ):
            if self._arm is ReplayArm.COMBINED:
                return replace(
                    decision,
                    analysis_regime=analysis_regime or "synthetic-bull",
                    risk_quantity=decision.risk_quantity * self._risk_multiplier,
                    capacity_quantity=decision.capacity_quantity * self._risk_multiplier,
                    quantity=decision.quantity * self._risk_multiplier,
                )
            pattern = _PATTERN_ARM[self._arm]
            return replace(
                decision,
                patterns=(pattern,),
                pattern_decisions=tuple(
                    item for item in decision.pattern_decisions if item.pattern is pattern
                ),
                analysis_regime=analysis_regime or "synthetic-bull",
                risk_quantity=decision.risk_quantity * self._risk_multiplier,
                capacity_quantity=decision.capacity_quantity * self._risk_multiplier,
                quantity=decision.quantity * self._risk_multiplier,
            )
        return SetupDecision(
            "phase2-swing-v1",
            "swing-evidence-v1",
            f"golden-abstain-{history.symbol}-{session.isoformat()}-{self._arm.value}",
            history.symbol,
            session,
            DecisionStatus.ABSTAIN,
            (),
            (),
            None,
            None,
            0,
            0,
            0,
            tuple(bar.digest for bar in history.daily),
            analysis_regime=analysis_regime or "synthetic-bull",
            setup_rules=(
                RuleEvidence("golden_no_signal", RuleOutcome.ABSTAIN, reason="fixture no signal"),
            ),
        )


class _RiskScaledEngine(AuthoritativeSwingEngine):
    """Diagnostic 2% budget while preserving the funded cash constraint."""

    def __init__(
        self,
        official_sessions: Sequence[date],
        evaluators: Sequence[PatternEvaluator],
        multiplier: int,
    ) -> None:
        super().__init__(official_sessions, evaluators)
        self._multiplier = multiplier

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
        return super().evaluate(
            history,
            equity * self._multiplier,
            costs,
            liquidity,
            available_cash=available_cash,
            analysis_regime=analysis_regime,
            evaluation_session=evaluation_session,
        )


def _sessions(first: date, count: int) -> tuple[date, ...]:
    output: list[date] = []
    current = first
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return tuple(output)


def _golden_bar(
    symbol: str,
    session: date,
    *,
    open_price: Decimal = Decimal("10"),
    high: Decimal = Decimal("10.5"),
    low: Decimal = Decimal("9.5"),
    close: Decimal = Decimal("10"),
    volume: int = 100_000,
) -> FinalBar:
    prices = Ohlcv(open_price, high, low, close, volume)
    return FinalBar(
        symbol,
        session,
        prices,
        prices,
        "frozen-synthetic-golden",
        DataQuality.VERIFIED,
        AdjustmentStatus.SPLIT_NORMALIZED,
        SplitFactor(1, 1),
        True,
        f"golden-{symbol}-{session.isoformat()}-{canonical_decimal(open_price)}-{canonical_decimal(low)}",
    )


def _golden_decision(symbol: str, session: date, patterns: tuple[Pattern, ...]) -> SetupDecision:
    candidates = tuple(
        PatternDecision(
            pattern,
            DecisionStatus.QUALIFIED,
            (),
            PatternCandidate(
                pattern,
                f"golden-{pattern.value}-{symbol}-{session.isoformat()}",
                None,
                session,
                Decimal("10"),
                Decimal("9.01"),
                Decimal("0.5"),
            ),
        )
        for pattern in patterns
    )
    return SetupDecision(
        "phase2-swing-v1",
        "swing-evidence-v1",
        f"golden-{symbol}-{session.isoformat()}-{'-'.join(patterns)}",
        symbol,
        session,
        DecisionStatus.QUALIFIED,
        patterns,
        candidates,
        Decimal("10"),
        Decimal("9"),
        10 if len(patterns) > 1 else 5,
        5,
        5,
        (f"golden-bar-{symbol}-{session.isoformat()}",),
        structural_invalidation_raw=Decimal("9.01"),
    )


def _synthetic_golden(volume_multiplier: Decimal) -> _GoldenFixture:
    sessions = _sessions(date(2022, 1, 3), 134)
    first, last = sessions[0], sessions[-1]
    calendar: list[ReplayCalendarRow] = []
    current = first
    while current <= last:
        kind = SessionKind.WEEKEND if current.weekday() >= 5 else SessionKind.FULL
        calendar.append(
            ReplayCalendarRow(
                current,
                kind,
                "frozen-synthetic-calendar",
                "weekend" if kind is SessionKind.WEEKEND else "trading session",
                f"golden-calendar-{current.isoformat()}",
                True,
            )
        )
        current += timedelta(days=1)
    setup_days = {
        "EMA.AX": (50, (Pattern.EMA_PULLBACK,)),
        "FLAG.AX": (54, (Pattern.BULL_FLAG,)),
        "DBL.AX": (58, (Pattern.DOUBLE_BOTTOM,)),
        "CONFL.AX": (62, (Pattern.EMA_PULLBACK, Pattern.BULL_FLAG)),
        "HALT.AX": (68, (Pattern.BULL_FLAG,)),
        "UNRES.AX": (69, (Pattern.DOUBLE_BOTTOM,)),
    }
    bars: dict[str, tuple[FinalBar, ...]] = {}
    decisions: dict[tuple[str, date], SetupDecision] = {}
    for symbol, (index, patterns) in setup_days.items():
        decisions[(symbol, sessions[index])] = _golden_decision(symbol, sessions[index], patterns)
        if symbol == "EMA.AX":
            decisions[(symbol, sessions[index + 1])] = _golden_decision(
                symbol, sessions[index + 1], patterns
            )
        history: list[FinalBar] = []
        for ordinal, session in enumerate(sessions):
            if symbol == "HALT.AX" and 70 <= ordinal < 86:
                continue
            if symbol == "UNRES.AX" and ordinal >= 72:
                continue
            if ordinal == index + 1:
                entry_open = (
                    Decimal("9.4")
                    if symbol == "EMA.AX"
                    else Decimal("9.5") if symbol == "FLAG.AX" else Decimal("9.8")
                )
                history.append(
                    _golden_bar(
                        symbol,
                        session,
                        open_price=entry_open,
                        high=Decimal("9.8") if symbol in {"EMA.AX", "FLAG.AX"} else Decimal("10.3"),
                        low=Decimal("9.2") if symbol in {"EMA.AX", "FLAG.AX"} else Decimal("9.4"),
                        close=Decimal("9.6") if symbol in {"EMA.AX", "FLAG.AX"} else Decimal("10"),
                        volume=int(100_000 * volume_multiplier),
                    )
                )
            elif ordinal == index + 2:
                if symbol == "UNRES.AX":
                    history.append(
                        _golden_bar(
                            symbol,
                            session,
                            open_price=Decimal("10.3"),
                            high=Decimal("10.5"),
                            low=Decimal("10.2"),
                            close=Decimal("10.3"),
                        )
                    )
                    continue
                history.append(
                    _golden_bar(
                        symbol,
                        session,
                        open_price=(
                            Decimal("9.2") if symbol in {"EMA.AX", "FLAG.AX"} else Decimal("9.5")
                        ),
                        high=Decimal("11.2") if symbol == "EMA.AX" else Decimal("9.7"),
                        low=Decimal("8.8"),
                        close=Decimal("9"),
                    )
                )
            elif symbol in {"EMA.AX", "FLAG.AX"} and ordinal < index:
                high = (
                    Decimal("9.5")
                    if ordinal == index - 37
                    else Decimal("9.55") if ordinal == index - 12 else Decimal("9.4")
                )
                history.append(
                    _golden_bar(
                        symbol,
                        session,
                        open_price=Decimal("9"),
                        high=high,
                        low=Decimal("8.5"),
                        close=Decimal("9"),
                    )
                )
            else:
                history.append(_golden_bar(symbol, session))
        bars[symbol] = tuple(history)
    bars["REJ.AX"] = tuple(_golden_bar("REJ.AX", session) for session in sessions)
    bars["TAIL.AX"] = tuple(_golden_bar("TAIL.AX", session) for session in sessions)
    decisions[("TAIL.AX", sessions[71])] = _golden_decision(
        "TAIL.AX", sessions[71], (Pattern.DOUBLE_BOTTOM,)
    )
    rejected = _golden_decision("REJ.AX", sessions[66], (Pattern.EMA_PULLBACK,))
    decisions[("REJ.AX", sessions[66])] = replace(
        rejected,
        status=DecisionStatus.REJECTED,
        entry_limit_raw=None,
        initial_stop_raw=None,
        risk_quantity=0,
        capacity_quantity=0,
        quantity=0,
    )
    split_bars = []
    for session in sessions:
        bar = _golden_bar("SPLIT.AX", session, volume=3000)
        adjusted = Ohlcv(Decimal("3"), Decimal("3.15"), Decimal("2.85"), Decimal("3"), 10_000)
        split_bars.append(
            replace(
                bar,
                adjusted=adjusted,
                raw_to_adjusted_price_factor=SplitFactor(3, 10),
            )
        )
    bars["SPLIT.AX"] = tuple(split_bars)
    events: tuple[SwingMarketEvent, ...] = (
        CashDividendEvent(
            "golden-dividend-ema",
            "EMA.AX",
            sessions[52],
            sessions[49],
            sessions[52],
            sessions[53],
            sessions[55],
            Decimal("0.10"),
        ),
        SplitEvent("golden-split-3-10", "SPLIT.AX", sessions[60], 3, 10),
        SuspensionEvent("golden-halt", "HALT.AX", sessions[70], sessions[86]),
        SuspensionEvent("golden-unresolved", "UNRES.AX", sessions[72], None),
    )
    benchmark = tuple(
        _golden_bar(
            "BENCH.AX",
            session,
            open_price=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
        )
        for session in sessions
    )
    membership = {session: frozenset(bars) for session in sessions}
    return _GoldenFixture(
        tuple(calendar),
        sessions,
        bars,
        membership,
        benchmark,
        decisions,
        events,
        sessions[70],
    )


def _calendar_rows(dataset: SwingDataset) -> tuple[ReplayCalendarRow, ...]:
    return tuple(
        ReplayCalendarRow(
            row.calendar_date,
            SessionKind(row.session_kind.value),
            row.source,
            row.reason,
            row.source_hash,
            row.finalized,
        )
        for row in dataset.official_calendar.rows
    )


def _static_abstention_replays(dataset: SwingDataset) -> dict[ReplayArm, SwingReplayResult]:
    reasons = (
        RuleEvidence(
            "STATIC_PROVENANCE_UNVERIFIED",
            RuleOutcome.ABSTAIN,
            reason="vendor-adjusted static bars lack split-only raw fill provenance",
        ),
        RuleEvidence(
            "INSUFFICIENT_RESISTANCE_HISTORY",
            RuleOutcome.ABSTAIN,
            reason="static cache has less than the required multi-year resistance history",
        ),
    )
    equity = tuple(
        ReplayEquityPoint(day, _STARTING_EQUITY, _STARTING_EQUITY, Decimal(0), Decimal(0))
        for day in dataset.official_sessions
    )
    return {
        arm: SwingReplayResult(
            RunStatus.VALID,
            arm,
            (),
            LifecycleActionSeries(),
            (),
            (),
            (),
            equity,
            reasons,
            (),
        )
        for arm in ReplayArm
    }


def _static_mechanical_diagnostic(
    dataset: SwingDataset, volume_multiplier: Decimal
) -> dict[str, object]:
    """Count pre-resistance pattern geometry on vendor bars; never emit orders."""
    counts: dict[tuple[str, str, Pattern], int] = {}
    eligible_pairs: set[tuple[str, str]] = set()
    official = dataset.official_sessions
    for symbol, original in sorted(dataset.bars.items()):
        # Verification is bypassed only for diagnostic geometry. The original
        # vendor-adjusted values never enter fills, equity, or promotion gates.
        history = tuple(replace(bar, quality=DataQuality.VERIFIED) for bar in original)
        for index in range(250, len(history)):
            prefix = SwingHistory(symbol, history[: index + 1])
            day = history[index].session
            month = day.strftime("%Y-%m")
            eligible_pairs.add((symbol, month))
            sessions = tuple(session for session in official if session <= day)
            for pattern in Pattern:
                if pattern is Pattern.BULL_FLAG:
                    result = evaluate_bull_flag(prefix, sessions, volume_multiplier)
                elif pattern is Pattern.EMA_PULLBACK:
                    result = evaluate_ema_pullback(prefix, sessions)
                else:
                    result = evaluate_double_bottom(prefix, sessions)
                if result.status is DecisionStatus.QUALIFIED:
                    key = (symbol, month, pattern)
                    counts[key] = counts.get(key, 0) + 1
    if not eligible_pairs:
        return {"status": "INSUFFICIENT_HISTORY", "eligible_symbol_months": 0}
    symbols = tuple(sorted({symbol for symbol, _ in eligible_pairs}))
    months = tuple(sorted({month for _, month in eligible_pairs}))
    rng = np.random.Generator(np.random.PCG64(0))
    patterns: dict[str, object] = {}
    for pattern in Pattern:
        matrix = np.asarray(
            [[counts.get((symbol, month, pattern), 0) for month in months] for symbol in symbols],
            dtype=np.float64,
        )
        available = np.asarray(
            [[(symbol, month) in eligible_pairs for month in months] for symbol in symbols],
            dtype=np.float64,
        )
        total = int(matrix.sum())
        rate = Decimal(total * 1000) / Decimal(len(eligible_pairs))
        proxy = Decimal(total * 200) / Decimal(len(eligible_pairs))
        bootstraps = []
        for _ in range(999):
            symbol_indices = rng.integers(0, len(symbols), len(symbols))
            month_indices = rng.integers(0, len(months), len(months))
            sampled_counts = matrix[np.ix_(symbol_indices, month_indices)]
            sampled_available = available[np.ix_(symbol_indices, month_indices)]
            denominator = sampled_available.sum()
            if denominator:
                bootstraps.append(float(sampled_counts.sum() * 200 / denominator))
        bounds = np.quantile(bootstraps, [0.05, 0.95]) if bootstraps else (0.0, 0.0)
        patterns[pattern.value] = {
            "pre_resistance_candidates": total,
            "per_1000_eligible_symbol_months": rate,
            "asx200_price_proxy_per_month": proxy,
            "symbol_month_clustered_90pct_range": tuple(Decimal(str(value)) for value in bounds),
        }
    return {
        "status": "NON_PROMOTIONAL_MECHANICAL_DIAGNOSTIC",
        "eligible_symbol_months": len(eligible_pairs),
        "symbols": len(symbols),
        "months": months,
        "numeric_policy": "numpy-binary64-pcg64-diagnostic-only",
        "patterns": patterns,
        "limitations": (
            "vendor-adjusted geometry only; raw fills, resistance, "
            "and eligibility are not assessed",
            "ASX200 proxy is a symbol/month exposure scaling estimate, not a trade forecast",
        ),
    }


def _run_golden(
    fixture: _GoldenFixture,
    ambiguity: AmbiguityPolicy,
    *,
    costs: ExactCostProfile = _COSTS,
    liquidity: LiquidityProfile = _LIQUIDITY,
    risk_multiplier: int = 1,
) -> dict[ReplayArm, SwingReplayResult]:
    replays = {}
    for arm in ReplayArm:
        replay = AuthoritativeSwingReplay(
            calendar_rows=fixture.calendar,
            bars=fixture.bars,
            membership=fixture.membership,
            corporate_actions=fixture.corporate_actions,
            benchmark=fixture.benchmark,
            engine=_GoldenEngine(fixture.decisions, arm, risk_multiplier),
            starting_equity=_STARTING_EQUITY,
            costs=costs,
            liquidity=liquidity,
            ambiguity_policy=ambiguity,
            final_entry_session=fixture.final_entry_session,
        ).run()
        replays[arm] = replace(replay, arm=arm)
    return replays


def _run_signed_dataset(
    dataset: SwingDataset,
    ambiguity: AmbiguityPolicy,
    volume_multiplier: Decimal,
    *,
    costs: ExactCostProfile = _COSTS,
    liquidity: LiquidityProfile = _LIQUIDITY,
    risk_multiplier: int = 1,
) -> dict[ReplayArm, SwingReplayResult]:
    bull_flag = partial(evaluate_bull_flag, volume_multiplier=volume_multiplier)
    evaluators: dict[ReplayArm, tuple[PatternEvaluator, ...]] = {
        ReplayArm.EMA_PULLBACK: (evaluate_ema_pullback,),
        ReplayArm.BULL_FLAG: (bull_flag,),
        ReplayArm.DOUBLE_BOTTOM: (evaluate_double_bottom,),
        ReplayArm.COMBINED: (
            evaluate_ema_pullback,
            bull_flag,
            evaluate_double_bottom,
        ),
    }
    final_entry = dataset.manifest.boundary_ids.get("T1")
    rows = _calendar_rows(dataset)
    replays = {}
    for arm in ReplayArm:
        replay = AuthoritativeSwingReplay(
            calendar_rows=rows,
            bars=dataset.bars,
            membership=dataset.membership,
            corporate_actions=dataset.corporate_actions,
            benchmark=dataset.benchmark,
            engine=_RiskScaledEngine(dataset.official_sessions, evaluators[arm], risk_multiplier),
            starting_equity=_STARTING_EQUITY,
            costs=costs,
            liquidity=liquidity,
            ambiguity_policy=ambiguity,
            final_entry_session=final_entry,
        ).run()
        replays[arm] = replace(replay, arm=arm)
    return replays


def _replay_summary(replay: SwingReplayResult) -> dict[str, object]:
    eligible = tuple(trade for trade in replay.signal_trades if trade.edge_sample_eligible)
    entry_equity = {point.session: point.equity for point in replay.equity}
    single_entry_exposures = tuple(
        trade.entry_price * Decimal(trade.quantity) / entry_equity[trade.entry_session]
        for trade in replay.trades
        if trade.entry_session in entry_equity and entry_equity[trade.entry_session] > 0
    )
    statistics = summarize_swing_statistics(
        signal_trades=replay.signal_trades,
        equity=replay.equity,
        signal_reference_equity=_STARTING_EQUITY,
    )
    return {
        "status": replay.status.value,
        "trades": len(replay.trades),
        "eligible_signal_trades": len(eligible),
        "terminal_valued_trades": sum(
            trade.exit_reason == "terminal_zero" for trade in replay.trades
        ),
        "final_equity": replay.equity[-1].equity if replay.equity else None,
        "mean_r_order": statistics.mean_r_order,
        "mean_r_fill": statistics.mean_r_fill,
        "minimum_r_order": min((trade.order_r_multiple for trade in eligible), default=None),
        "maximum_drawdown": statistics.maximum_drawdown,
        "maximum_exposure": statistics.maximum_exposure,
        "average_exposure": statistics.average_exposure,
        "maximum_single_position_entry_notional_exposure": max(
            single_entry_exposures, default=Decimal(0)
        ),
        "average_single_position_entry_notional_exposure": (
            sum(single_entry_exposures, Decimal(0)) / Decimal(len(single_entry_exposures))
            if single_entry_exposures
            else Decimal(0)
        ),
        "cost_to_risk": statistics.cost_to_risk,
        "costs": statistics.total_costs,
        "capacity_bound_decisions": sum(
            decision.status is DecisionStatus.QUALIFIED
            and decision.capacity_quantity < decision.risk_quantity
            for decision in replay.decisions
        ),
        "post_fill_resistance": {
            diagnostic.value: sum(
                trade.post_fill_resistance is diagnostic for trade in replay.trades
            )
            for diagnostic in set(trade.post_fill_resistance for trade in replay.trades)
        },
        "days_above_concentration": {
            str(level): sum(point.position_value / point.equity > level for point in replay.equity)
            for level in (Decimal("0.1"), Decimal("0.2"), Decimal("0.3"))
        },
        "gap_losses_beyond_planned_1pct": sum(
            trade.net_pnl < -trade.order_initial_risk_dollars for trade in replay.trades
        ),
    }


def _golden_case(
    volume: Decimal,
    ambiguity: AmbiguityPolicy,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    risk_multiplier: int,
) -> SwingReplayResult:
    return _run_golden(
        _synthetic_golden(volume),
        ambiguity,
        costs=costs,
        liquidity=liquidity,
        risk_multiplier=risk_multiplier,
    )[ReplayArm.COMBINED]


def _signed_case(
    dataset: SwingDataset,
    volume: Decimal,
    ambiguity: AmbiguityPolicy,
    costs: ExactCostProfile,
    liquidity: LiquidityProfile,
    risk_multiplier: int,
) -> SwingReplayResult:
    return _run_signed_dataset(
        dataset,
        ambiguity,
        volume,
        costs=costs,
        liquidity=liquidity,
        risk_multiplier=risk_multiplier,
    )[ReplayArm.COMBINED]


def _scenario_sensitivities(
    run_case: Callable[
        [Decimal, AmbiguityPolicy, ExactCostProfile, LiquidityProfile, int], SwingReplayResult
    ],
    baseline: SwingReplayResult,
    baseline_volume: Decimal,
) -> dict[str, object]:
    sensitivity: dict[str, object] = {}
    for multiplier in (Decimal("1.25"), Decimal("1.5"), Decimal("2.0")):
        volume_replay = run_case(multiplier, AmbiguityPolicy.CONSERVATIVE, _COSTS, _LIQUIDITY, 1)
        sensitivity[f"volume_{multiplier}"] = _replay_summary(volume_replay)
    sensitivity["optimistic_ambiguity"] = _replay_summary(
        run_case(baseline_volume, AmbiguityPolicy.OPTIMISTIC, _COSTS, _LIQUIDITY, 1)
    )
    doubled_costs = replace(
        _COSTS,
        version="phase2-engineering-double-cost-v1",
        commission_bps=_COSTS.commission_bps * 2,
        min_commission=_COSTS.min_commission * 2,
        third_party_bps=_COSTS.third_party_bps * 2,
    )
    sensitivity["doubled_costs"] = _replay_summary(
        run_case(baseline_volume, AmbiguityPolicy.CONSERVATIVE, doubled_costs, _LIQUIDITY, 1)
    )
    impact_profile = replace(
        _LIQUIDITY,
        version="phase2-engineering-double-impact-v1",
        entry_impact_bps=_LIQUIDITY.entry_impact_bps * 2,
        stop_exit_impact_bps=_LIQUIDITY.stop_exit_impact_bps * 2,
    )
    sensitivity["doubled_liquidity_impact"] = _replay_summary(
        run_case(baseline_volume, AmbiguityPolicy.CONSERVATIVE, _COSTS, impact_profile, 1)
    )
    sensitivity["two_percent_sizing"] = _replay_summary(
        run_case(baseline_volume, AmbiguityPolicy.CONSERVATIVE, _COSTS, _LIQUIDITY, 2)
    )
    clear = tuple(
        trade
        for trade in baseline.signal_trades
        if trade.post_fill_resistance.value == "post_fill_resistance_clear"
    )
    sensitivity["post_fill_resistance_exclusion"] = {
        "eligible_signal_trades": len(clear),
        "excluded_signal_trades": len(baseline.signal_trades) - len(clear),
        "mean_r_order": (
            sum((trade.order_r_multiple for trade in clear), Decimal(0)) / Decimal(len(clear))
            if clear
            else None
        ),
    }
    sensitivity["minimum_r_stress"] = {
        "minimum_r_order": min(
            (trade.order_r_multiple for trade in baseline.signal_trades), default=None
        ),
        "minimum_r_fill": min(
            (trade.fill_r_multiple for trade in baseline.signal_trades), default=None
        ),
    }
    sensitivity["diagnostic_only"] = True
    return sensitivity


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--shard-root")
    parser.add_argument("--shard-id")
    parser.add_argument("--verification-key-file")
    parser.add_argument(
        "--engineering-mode",
        choices=("strict_authoritative", "mechanical_diagnostic"),
        default="strict_authoritative",
    )
    parser.add_argument("--partition", choices=("development", "validation"), default="development")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--ambiguity-policy",
        choices=tuple(item.value for item in AmbiguityPolicy),
        default=AmbiguityPolicy.CONSERVATIVE.value,
    )
    parser.add_argument("--volume-multiplier", default="1.5")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 for valid offline engineering evidence, 2 for invalid inputs."""
    parser = _argument_parser()
    try:
        args = parser.parse_args(argv)
        multiplier = Decimal(args.volume_multiplier)
        if not multiplier.is_finite() or multiplier <= 0:
            raise ValueError("volume multiplier must be finite and positive")
        if args.engineering_mode == "mechanical_diagnostic" and args.catalog != "static-asx":
            raise ValueError("mechanical diagnostic mode is limited to static ASX cache")
        ambiguity = AmbiguityPolicy(args.ambiguity_policy)
        mechanical: dict[str, object] | None = None
        limitations: tuple[str, ...]
        if args.catalog == "synthetic-golden":
            if any((args.shard_root, args.shard_id, args.verification_key_file)):
                raise ValueError("synthetic fixture does not accept shard capabilities")
            fixture = _synthetic_golden(multiplier)
            replays = _run_golden(fixture, ambiguity)
            dataset_manifest: dict[str, object] = {
                "catalog_id": "synthetic-golden",
                "shard_ids": ("synthetic-development",),
                "T0": fixture.sessions[0],
                "T1": fixture.sessions[70],
                "T10": fixture.sessions[79],
                "T11": fixture.sessions[80],
                "T64": fixture.sessions[-1],
                "T65": _sessions(fixture.sessions[-1] + timedelta(days=1), 1)[0],
                "official_session_count": len(fixture.sessions),
                "symbol_count": len(fixture.bars),
                "regime_provenance": {
                    "label": "synthetic-bull",
                    "input_cutoff": fixture.sessions[49],
                    "max_input_session": fixture.sessions[49],
                    "source": "frozen-synthetic-fixture",
                },
                "signal_reference_equity": _STARTING_EQUITY,
                "cost_profile": _COSTS,
                "liquidity_profile": _LIQUIDITY,
                "partition": args.partition,
                "engineering_mode": args.engineering_mode,
            }
            limitations = ("synthetic fixture has no empirical edge interpretation",)
        elif args.catalog == "static-asx":
            if any((args.shard_root, args.shard_id, args.verification_key_file)):
                raise ValueError("static fixture does not accept shard capabilities")
            dataset = load_static_asx_engineering_dataset()
            replays = _static_abstention_replays(dataset)
            if args.engineering_mode == "mechanical_diagnostic":
                mechanical = _static_mechanical_diagnostic(dataset, multiplier)
            dataset_manifest = {
                "catalog_id": dataset.catalog.dataset_id,
                "shard_ids": (dataset.manifest.shard_id,),
                "T0": dataset.official_sessions[0],
                "T64": dataset.official_sessions[-1],
                "official_session_count": len(dataset.official_sessions),
                "symbol_count": len(dataset.bars),
                "per_symbol_session_counts": {
                    symbol: len(history) for symbol, history in dataset.bars.items()
                },
                "signal_reference_equity": _STARTING_EQUITY,
                "cost_profile": _COSTS,
                "liquidity_profile": _LIQUIDITY,
                "partition": args.partition,
                "engineering_mode": args.engineering_mode,
                "limitations": dataset.catalog.limitations,
            }
            limitations = dataset.catalog.limitations
        else:
            if not all((args.shard_root, args.shard_id, args.verification_key_file)):
                raise ValueError(
                    "authorized engineering shard needs root, ID, and verification key"
                )
            verification_key = Path(args.verification_key_file).read_bytes()
            catalog = validate_catalog(Path(args.catalog), verification_key)
            if catalog.tier is not DatasetTier.ENGINEERING_SYNTHETIC:
                raise ValueError("Phase 2C runner rejects promotion-tier capability")
            dataset = load_swing_dataset(
                PartitionAccess(
                    Path(args.catalog),
                    args.shard_id,
                    Path(args.shard_root),
                    verification_key,
                    required_tier=DatasetTier.ENGINEERING_SYNTHETIC,
                )
            )
            if dataset.catalog.tier is not DatasetTier.ENGINEERING_SYNTHETIC:
                raise ValueError("Phase 2C runner rejects promotion-tier capability")
            if dataset.manifest.partition != args.partition:
                raise ValueError("authorized shard belongs to a different partition")
            replays = _run_signed_dataset(dataset, ambiguity, multiplier)
            dataset_manifest = {
                "catalog_id": dataset.catalog.dataset_id,
                "shard_ids": (dataset.manifest.shard_id,),
                "T0": dataset.official_sessions[0],
                "T64": dataset.official_sessions[-1],
                "boundaries": dataset.manifest.boundary_ids,
                "official_session_count": len(dataset.official_sessions),
                "symbol_count": len(dataset.bars),
                "signal_reference_equity": _STARTING_EQUITY,
                "cost_profile": _COSTS,
                "liquidity_profile": _LIQUIDITY,
                "partition": args.partition,
                "engineering_mode": args.engineering_mode,
                "limitations": dataset.catalog.limitations,
            }
            limitations = dataset.catalog.limitations
        if any(replay.status is RunStatus.INVALID for replay in replays.values()):
            raise ValueError("one or more replay arms are INVALID")
        combined = replays[ReplayArm.COMBINED]
        sensitivity: dict[str, object] = {
            "ambiguity_policy": ambiguity.value,
            "volume_multiplier": multiplier,
            "diagnostic_only": True,
        }
        if args.catalog == "synthetic-golden":
            sensitivity.update(_scenario_sensitivities(_golden_case, combined, multiplier))
        elif args.catalog != "static-asx":
            sensitivity.update(
                _scenario_sensitivities(partial(_signed_case, dataset), combined, multiplier)
            )
        metrics: dict[str, object] = {
            "arms": {
                arm.value: {
                    "decisions": len(replay.decisions),
                    "fills": len(replay.fills),
                    "trades": len(replay.trades),
                    "eligible_signal_trades": sum(
                        t.edge_sample_eligible for t in replay.signal_trades
                    ),
                    "abstentions": len(replay.abstentions),
                    "ambiguities": len(replay.ambiguities),
                    "summary": _replay_summary(replay),
                }
                for arm, replay in replays.items()
            },
            "combined_equity_final": combined.equity[-1].equity if combined.equity else None,
            "strict_provenance_abstention": args.catalog == "static-asx"
            and args.engineering_mode == "strict_authoritative",
            "limitations": limitations,
        }
        if mechanical is not None:
            metrics["mechanical_diagnostic"] = mechanical
        run = SwingArtifactRun(
            (
                "synthetic"
                if args.catalog == "synthetic-golden"
                else (
                    "engineering_static"
                    if args.catalog == "static-asx"
                    else "engineering_synthetic"
                )
            ),
            dataset_manifest,
            replays,
            metrics,
            evaluate_promotion(PromotionCase(evidence_tier="engineering")),
            {"status": "METHOD_AUDIT_PENDING", "numeric_policy": "wcr-s-cv1-v2"},
            {
                "status": "DATASET_INSUFFICIENT",
                "reason": "engineering evidence cannot plan promotion",
            },
            {"status": "INCIDENCE_DATA_INSUFFICIENT"},
            sensitivity,
            datetime.now(UTC),
        )
        path = write_swing_artifacts(run, Path(args.out))
        print(path.resolve())
        return 0
    except (DatasetIntegrityError, FileExistsError, OSError, ValueError) as error:
        print(f"invalid engineering run: {error}", file=sys.stderr)
        return 2
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2


if __name__ == "__main__":
    raise SystemExit(main())
