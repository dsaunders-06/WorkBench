"""Pure structural portfolio preflight and Phase 2 non-promotional verdicts."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from statistics import NormalDist
from types import MappingProxyType

import numpy as np

from qat.domain.backtester.swing_method_audit import (
    FeasibilityStatus,
    FrequencyPlan,
    MethodStatus,
)
from qat.domain.backtester.swing_reference import IncidenceCalibration, PromotionStatus
from qat.domain.backtester.swing_results import (
    ReplayEquityPoint,
    RunStatus,
    SwingReplayResult,
    SwingTrade,
)
from qat.domain.backtester.swing_statistics import (
    ENTRY_MONTH_WCR_S,
    InferenceCandidate,
    candidate_cluster_count,
    candidate_eligible,
    romano_wolf_stepdown,
    wcr_s_mean_test,
)


class StructuralStatus(StrEnum):
    PASS = "PASS"  # nosec B105 # Enum outcome label, not a credential.
    PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE = "PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE"


@dataclass(frozen=True, slots=True)
class Phase4RiskPolicy:
    ordinary_drawdown_budget: Decimal
    maximum_drawdown: Decimal
    maximum_single_notional: Decimal
    maximum_aggregate_notional: Decimal
    maximum_sector_notional: Decimal
    minimum_stop_distance: Decimal
    maximum_cost_to_risk: Decimal

    def __post_init__(self) -> None:
        rates = (
            self.ordinary_drawdown_budget,
            self.maximum_drawdown,
            self.maximum_single_notional,
            self.maximum_aggregate_notional,
            self.maximum_sector_notional,
            self.minimum_stop_distance,
            self.maximum_cost_to_risk,
        )
        if any(not rate.is_finite() or not Decimal(0) <= rate <= Decimal(1) for rate in rates):
            raise ValueError("Phase 4 risk-policy fractions must be finite and within [0,1]")
        if self.maximum_drawdown <= 0 or self.minimum_stop_distance <= 0:
            raise ValueError("Phase 4 drawdown and stop limits must be positive")
        if self.maximum_drawdown > Decimal("0.20"):
            raise ValueError("Phase 4 cannot relax the 20% maximum drawdown gate")


@dataclass(frozen=True, slots=True)
class PositionImpact:
    trade_id: str
    issuer_id: str
    entry_session: date
    exit_session: date
    marks: Mapping[date, Decimal]
    exit_proceeds: Decimal
    dividends: Mapping[date, Decimal]
    sector: str
    initial_notional: Decimal
    stop_distance: Decimal
    cost_to_risk: Decimal

    def __post_init__(self) -> None:
        if not self.trade_id or not self.issuer_id or not self.sector:
            raise ValueError("funded position impact needs trade, issuer, and sector identities")
        if self.entry_session >= self.exit_session:
            raise ValueError("funded position must exit after entry")
        for value in (
            self.exit_proceeds,
            self.initial_notional,
            self.stop_distance,
            self.cost_to_risk,
            *self.marks.values(),
            *self.dividends.values(),
        ):
            if not value.is_finite() or value < 0:
                raise ValueError(
                    "position marks, proceeds, and policy measurements must be nonnegative"
                )
        object.__setattr__(self, "marks", MappingProxyType(dict(self.marks)))
        object.__setattr__(self, "dividends", MappingProxyType(dict(self.dividends)))


@dataclass(frozen=True, slots=True)
class StructuralPlacement:
    trade_id: str
    onset: date
    max_drawdown: Decimal
    affected_points: int


@dataclass(frozen=True, slots=True)
class StructuralRiskResult:
    status: StructuralStatus
    placements_tested: int
    placements: tuple[StructuralPlacement, ...]
    max_drawdown: Decimal
    realized_baseline_drawdown: Decimal
    design_envelope: Decimal
    policy_violations: tuple[str, ...]
    affected_points_processed: int
    parity_digest: str
    recommended_holdout_months: int | None = None


@dataclass(frozen=True, slots=True)
class TerminalScenarioTrade:
    position: PositionImpact
    ordinary_r_order: Decimal
    zero_r_order: Decimal
    bucket_probability: Decimal

    def __post_init__(self) -> None:
        if any(
            not value.is_finite()
            for value in (self.ordinary_r_order, self.zero_r_order, self.bucket_probability)
        ) or not Decimal(0) <= self.bucket_probability <= Decimal(1):
            raise ValueError("terminal scenario needs finite R outcomes and a probability")


@dataclass(frozen=True, slots=True)
class TerminalTailResult:
    fifth_percentile_mean_r: Decimal
    analytical_expected_mean_r: Decimal
    simulated_expected_mean_r: Decimal
    analytical_parity_gap: Decimal
    analytical_tolerance: Decimal
    analytical_parity_pass: bool
    drawdown_95: Decimal
    signal_es1: Decimal
    signal_es5: Decimal
    cash_es1: Decimal
    cash_es5: Decimal
    simulations: int
    seed: int


@dataclass(frozen=True, slots=True)
class TwoIssuerZeroSensitivity:
    worst_drawdown: Decimal
    placements_tested: int
    worst_pair: tuple[str, str, date] | None


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool | None
    evidence: str


@dataclass(frozen=True, slots=True)
class SignalEdgeTrade:
    trade_id: str
    symbol: str
    entry_session: date
    order_r_multiple: Decimal
    net_pnl: Decimal
    edge_sample_eligible: bool


@dataclass(frozen=True, slots=True)
class PatternEdgeInputs:
    pattern: str
    trades: tuple[SignalEdgeTrade, ...]
    n_required: int
    g_required: int
    wcr_lower_bound: Decimal | None
    romano_wolf_adjusted_p: Decimal | None
    doubled_cost_expectancy: Decimal | None
    method_status: MethodStatus | None
    feasibility_status: FeasibilityStatus | None
    eligible_holdout_months: int
    phase4_policy_frozen: bool
    protocol_frozen: bool
    permit_satisfied: bool
    inference_clusters: int | None = None


@dataclass(frozen=True, slots=True)
class PatternEdgeResult:
    pattern: str
    gates: tuple[GateResult, ...]
    passed: bool


def _leave_out_mean(trades: Sequence[SignalEdgeTrade]) -> Decimal | None:
    return (
        sum((trade.order_r_multiple for trade in trades), Decimal(0)) / Decimal(len(trades))
        if trades
        else None
    )


def evaluate_pattern_edge_gates(inputs: PatternEdgeInputs) -> PatternEdgeResult:
    """Assess all seven conjunctive signal-level gates for one pattern."""
    if not inputs.pattern or inputs.n_required < 100 or inputs.g_required <= 0:
        raise ValueError("pattern edge needs a named frozen N>=100 and positive G requirement")
    eligible = tuple(trade for trade in inputs.trades if trade.edge_sample_eligible)
    if len({trade.trade_id for trade in eligible}) != len(eligible):
        raise ValueError("eligible signal trades must have unique identities")
    months = {trade.entry_session.strftime("%Y-%m") for trade in eligible}
    expectation = _leave_out_mean(eligible)
    gains = sum((trade.net_pnl for trade in eligible if trade.net_pnl > 0), Decimal(0))
    losses = -sum((trade.net_pnl for trade in eligible if trade.net_pnl < 0), Decimal(0))
    profit_factor_pass = bool(
        eligible and gains > 0 and (losses == 0 or gains / losses >= Decimal("1.2"))
    )
    concentration_pass = False
    if eligible:
        symbol_totals: dict[str, Decimal] = defaultdict(Decimal)
        year_totals: dict[int, Decimal] = defaultdict(Decimal)
        for trade in eligible:
            symbol_totals[trade.symbol] += trade.order_r_multiple
            year_totals[trade.entry_session.year] += trade.order_r_multiple
        best_symbol = max(symbol_totals, key=lambda symbol: (symbol_totals[symbol], symbol))
        best_year = max(year_totals, key=lambda year: (year_totals[year], year))
        top_count = math.ceil(len(eligible) * 0.05)
        top_ids = {
            trade.trade_id
            for trade in sorted(
                eligible, key=lambda trade: (-trade.order_r_multiple, trade.trade_id)
            )[:top_count]
        }
        leave_symbol = _leave_out_mean(
            tuple(trade for trade in eligible if trade.symbol != best_symbol)
        )
        leave_year = _leave_out_mean(
            tuple(trade for trade in eligible if trade.entry_session.year != best_year)
        )
        leave_top = _leave_out_mean(
            tuple(trade for trade in eligible if trade.trade_id not in top_ids)
        )
        concentration_pass = all(
            value is not None and value > 0 for value in (leave_symbol, leave_year, leave_top)
        )
    observed_clusters = (
        inputs.inference_clusters if inputs.inference_clusters is not None else len(months)
    )
    gates = (
        GateResult(
            "sample_size",
            len(eligible) >= inputs.n_required and observed_clusters >= inputs.g_required,
            f"eligible N={len(eligible)}, nonempty G={observed_clusters}",
        ),
        GateResult(
            "expectancy", expectation is not None and expectation > 0, f"mean R_order={expectation}"
        ),
        GateResult(
            "cluster_inference",
            inputs.wcr_lower_bound is not None
            and inputs.wcr_lower_bound > 0
            and inputs.romano_wolf_adjusted_p is not None
            and inputs.romano_wolf_adjusted_p < Decimal("0.05"),
            "97.5% WCR-S lower bound and 5% Romano-Wolf stepdown",
        ),
        GateResult("profit_factor", profit_factor_pass, "net P&L profit factor >= 1.20"),
        GateResult(
            "doubled_costs",
            inputs.doubled_cost_expectancy is not None and inputs.doubled_cost_expectancy > 0,
            f"doubled-cost mean R_order={inputs.doubled_cost_expectancy}",
        ),
        GateResult(
            "concentration",
            concentration_pass,
            "leave best symbol, best entry year, and top 5% of R_order trades out",
        ),
        GateResult(
            "protocol_and_feasibility",
            inputs.method_status is MethodStatus.METHOD_ADEQUATE
            and inputs.feasibility_status is FeasibilityStatus.FEASIBLE
            and inputs.eligible_holdout_months >= 36
            and inputs.phase4_policy_frozen
            and inputs.protocol_frozen
            and inputs.permit_satisfied,
            "declared method, power, duration, Phase 4 policy, and Phase 2D permit",
        ),
    )
    return PatternEdgeResult(inputs.pattern, gates, all(gate.passed is True for gate in gates))


@dataclass(frozen=True, slots=True)
class PromotionCase:
    evidence_tier: str
    data_valid: bool = True
    incidence: IncidenceCalibration | None = None
    structural: StructuralRiskResult | None = None
    method_status: MethodStatus | None = None
    feasibility: FrequencyPlan | None = None
    terminal_tail: TerminalTailResult | None = None
    all_edge_gates_pass: bool | None = None
    pattern_edges: tuple[PatternEdgeResult, ...] = ()
    portfolio_safety_pass: bool | None = None
    conservative_terminal_gate_pass: bool | None = None
    recovery_sensitivity_pass: bool = False
    phase4_policy_frozen: bool = False
    permit_satisfied: bool = False


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    status: PromotionStatus
    gates: tuple[GateResult, ...]
    feasibility_reason: FeasibilityStatus | None
    required_months: int | None
    available_months: int | None
    binding_pattern: str | None
    binding_rate_source: str | None
    recommended_holdout_months: int | None
    recommended_operator_action: str
    forward_acquisition_could_help: bool


def all_exposed_trade_session_pairs(
    official_sessions: Sequence[date], positions: Sequence[PositionImpact]
) -> tuple[tuple[str, date], ...]:
    """A documented halt leaves the funded position exposed until its exit."""
    sessions = tuple(official_sessions)
    if tuple(sorted(set(sessions))) != sessions:
        raise ValueError("structural preflight needs ordered unique official sessions")
    return tuple(
        (position.trade_id, session)
        for position in positions
        for session in sessions
        if position.entry_session < session <= position.exit_session
    )


def _maximum_drawdown(values: Sequence[Decimal]) -> Decimal:
    peak: Decimal | None = None
    maximum = Decimal(0)
    for value in values:
        if not value.is_finite() or value <= 0:
            return Decimal(1)
        peak = value if peak is None else max(peak, value)
        maximum = max(maximum, (peak - value) / peak)
    return maximum


def _policy_violations(
    sessions: tuple[date, ...],
    baseline_equity: Mapping[date, Decimal],
    positions: Sequence[PositionImpact],
    policy: Phase4RiskPolicy,
) -> tuple[tuple[str, ...], Decimal]:
    violations: list[str] = []
    maximum_envelope = Decimal(0)
    for position in positions:
        entry_equity = baseline_equity[position.entry_session]
        zero_price_loss = position.initial_notional / entry_equity
        envelope = Decimal(1) - (Decimal(1) - policy.ordinary_drawdown_budget) * (
            Decimal(1) - zero_price_loss
        )
        maximum_envelope = max(maximum_envelope, envelope)
        if envelope > policy.maximum_drawdown:
            violations.append(f"{position.trade_id}:design_envelope")
        if zero_price_loss > policy.maximum_single_notional:
            violations.append(f"{position.trade_id}:single_notional")
        if position.stop_distance < policy.minimum_stop_distance:
            violations.append(f"{position.trade_id}:stop_distance")
        if position.cost_to_risk > policy.maximum_cost_to_risk:
            violations.append(f"{position.trade_id}:cost_to_risk")
    for session in sessions:
        active = [
            position
            for position in positions
            if position.entry_session <= session < position.exit_session
        ]
        if not active:
            continue
        equity = baseline_equity[session]
        # The open fill funds the position on its entry session. Its initial
        # notional is the available entry-day measure; later sessions use marks.
        notional = {
            position.trade_id: (
                position.initial_notional
                if session == position.entry_session
                else position.marks[session]
            )
            for position in active
        }
        aggregate = sum(notional.values(), Decimal(0)) / equity
        if aggregate > policy.maximum_aggregate_notional:
            violations.append(f"{session.isoformat()}:aggregate_notional")
        by_sector: dict[str, Decimal] = defaultdict(Decimal)
        for position in active:
            by_sector[position.sector] += notional[position.trade_id]
        if any(value / equity > policy.maximum_sector_notional for value in by_sector.values()):
            violations.append(f"{session.isoformat()}:sector_notional")
    return tuple(sorted(set(violations))), maximum_envelope


def _baseline_prefix(
    baseline: tuple[Decimal, ...],
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
    peaks: list[Decimal] = []
    drawdowns: list[Decimal] = []
    peak = Decimal(0)
    maximum = Decimal(0)
    for value in baseline:
        peak = max(peak, value)
        maximum = max(maximum, (peak - value) / peak)
        peaks.append(peak)
        drawdowns.append(maximum)
    return tuple(peaks), tuple(drawdowns)


def _placement_drawdown(
    sessions: tuple[date, ...],
    baseline: tuple[Decimal, ...],
    position: PositionImpact,
    onset: date,
    prefix_peaks: tuple[Decimal, ...],
    prefix_drawdowns: tuple[Decimal, ...],
    session_index: Mapping[date, int],
) -> Decimal:
    """Apply an exact sparse delta only to the affected cached equity suffix."""
    first_affected = session_index[onset]
    peak = prefix_peaks[first_affected - 1]
    maximum = prefix_drawdowns[first_affected - 1]
    cumulative_dividends = Decimal(0)
    for index in range(first_affected, len(sessions)):
        session = sessions[index]
        cumulative_dividends += position.dividends.get(session, Decimal(0))
        contribution = (
            position.marks[session] if session < position.exit_session else position.exit_proceeds
        )
        value = baseline[index] - contribution - cumulative_dividends
        if value <= 0:
            return Decimal(1)
        peak = max(peak, value)
        maximum = max(maximum, (peak - value) / peak)
    return maximum


def _lower_tail_mean(values: Sequence[Decimal], fraction: Decimal) -> Decimal:
    count = max(1, math.ceil(Decimal(len(values)) * fraction))
    return sum(sorted(values)[:count], Decimal(0)) / Decimal(count)


def simulate_terminal_tail(
    official_sessions: Sequence[date],
    equity: Sequence[ReplayEquityPoint],
    trades: Sequence[TerminalScenarioTrade],
    *,
    simulations: int = 9_999,
    seed: int = 0,
) -> TerminalTailResult:
    """Apply correlated terminal onsets to frozen funded cash and R outcomes."""
    sessions = tuple(official_sessions)
    if simulations <= 0 or not trades or tuple(point.session for point in equity) != sessions:
        raise ValueError("terminal simulation needs funded trades and a complete equity ledger")
    if len({trade.position.trade_id for trade in trades}) != len(trades):
        raise ValueError("terminal trade identities must be unique")
    baseline = tuple(point.equity for point in equity)
    if not baseline or baseline[0] <= 0:
        raise ValueError("terminal simulation needs positive starting equity")
    exposure_sessions = {
        trade.position.trade_id: tuple(
            session
            for session in sessions
            if trade.position.entry_session < session <= trade.position.exit_session
        )
        for trade in trades
    }
    if any(not values for values in exposure_sessions.values()):
        raise ValueError("terminal simulation needs at least one exposed session per trade")
    for trade in trades:
        mark_sessions = set(exposure_sessions[trade.position.trade_id]) - {
            trade.position.exit_session
        }
        if set(trade.position.marks) != mark_sessions:
            raise ValueError("terminal position marks must cover every exposed session")
    analytical = sum(
        (
            (Decimal(1) - trade.bucket_probability) * trade.ordinary_r_order
            + trade.bucket_probability * trade.zero_r_order
            for trade in trades
        ),
        Decimal(0),
    ) / Decimal(len(trades))
    rng = np.random.Generator(np.random.PCG64(seed))
    normal = NormalDist()
    means: list[Decimal] = []
    drawdowns: list[Decimal] = []
    cash_returns: list[Decimal] = []
    for _ in range(simulations):
        market = float(rng.normal())
        sectors: dict[str, float] = {}
        path = list(baseline)
        outcomes: list[Decimal] = []
        for trade in trades:
            sector = trade.position.sector
            if sector not in sectors:
                sectors[sector] = float(rng.normal())
            latent = 0.5 * market + 0.5 * sectors[sector] + math.sqrt(0.5) * float(rng.normal())
            selected = normal.cdf(latent) < float(trade.bucket_probability)
            if not selected:
                outcomes.append(trade.ordinary_r_order)
                continue
            outcomes.append(trade.zero_r_order)
            available = exposure_sessions[trade.position.trade_id]
            onset = available[int(rng.integers(0, len(available)))]
            cumulative_dividends = Decimal(0)
            for index, session in enumerate(sessions):
                if session < onset:
                    continue
                cumulative_dividends += trade.position.dividends.get(session, Decimal(0))
                contribution = (
                    trade.position.marks[session]
                    if session < trade.position.exit_session
                    else trade.position.exit_proceeds
                )
                path[index] -= contribution + cumulative_dividends
        means.append(sum(outcomes, Decimal(0)) / Decimal(len(trades)))
        drawdowns.append(_maximum_drawdown(path))
        cash_returns.append((path[-1] - baseline[0]) / baseline[0])
    simulated_expectation = sum(means, Decimal(0)) / Decimal(simulations)
    parity_gap = abs(simulated_expectation - analytical)
    sampling_error = (
        float(np.std([float(value) for value in means], ddof=1)) / math.sqrt(simulations)
        if simulations > 1
        else 0.0
    )
    tolerance = max(Decimal("0.01"), Decimal(str(3 * sampling_error)))
    return TerminalTailResult(
        Decimal(str(float(np.percentile([float(value) for value in means], 5, method="lower")))),
        analytical,
        simulated_expectation,
        parity_gap,
        tolerance,
        parity_gap <= tolerance,
        Decimal(
            str(float(np.percentile([float(value) for value in drawdowns], 95, method="higher")))
        ),
        _lower_tail_mean(means, Decimal("0.01")),
        _lower_tail_mean(means, Decimal("0.05")),
        _lower_tail_mean(cash_returns, Decimal("0.01")),
        _lower_tail_mean(cash_returns, Decimal("0.05")),
        simulations,
        seed,
    )


def simultaneous_two_issuer_zero(
    official_sessions: Sequence[date],
    equity: Sequence[ReplayEquityPoint],
    positions: Sequence[PositionImpact],
) -> TwoIssuerZeroSensitivity:
    """Report the worst same-session two-issuer zero as a sensitivity only."""
    sessions = tuple(official_sessions)
    if tuple(point.session for point in equity) != sessions:
        raise ValueError("two-issuer sensitivity needs the complete official equity ledger")
    baseline = tuple(point.equity for point in equity)
    worst = _maximum_drawdown(baseline)
    worst_pair: tuple[str, str, date] | None = None
    placements = 0
    for first_index, first in enumerate(positions):
        for second in positions[first_index + 1 :]:
            if first.issuer_id == second.issuer_id:
                continue
            shared = tuple(
                session
                for session in sessions
                if first.entry_session < session <= first.exit_session
                and second.entry_session < session <= second.exit_session
            )
            for onset in shared:
                placements += 1
                path = list(baseline)
                for position in (first, second):
                    cumulative_dividends = Decimal(0)
                    for index, session in enumerate(sessions):
                        if session < onset:
                            continue
                        cumulative_dividends += position.dividends.get(session, Decimal(0))
                        contribution = (
                            position.marks[session]
                            if session < position.exit_session
                            else position.exit_proceeds
                        )
                        path[index] -= contribution + cumulative_dividends
                drawdown = _maximum_drawdown(path)
                if drawdown > worst:
                    worst = drawdown
                    worst_pair = (first.trade_id, second.trade_id, onset)
    return TwoIssuerZeroSensitivity(worst, placements, worst_pair)


def evaluate_structural_risk(
    official_sessions: Sequence[date],
    equity: Sequence[ReplayEquityPoint],
    positions: Sequence[PositionImpact],
    policy: Phase4RiskPolicy,
) -> StructuralRiskResult:
    """Inject zero on every funded exposure session without replaying strategy."""
    sessions = tuple(official_sessions)
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("structural sessions must be ordered and unique")
    if tuple(point.session for point in equity) != sessions:
        raise ValueError("cash-funded equity must cover every official session")
    baseline = tuple(point.equity for point in equity)
    baseline_by_session = dict(zip(sessions, baseline, strict=True))
    session_index = {session: index for index, session in enumerate(sessions)}
    for position in positions:
        if (
            position.entry_session not in baseline_by_session
            or position.exit_session not in baseline_by_session
        ):
            raise ValueError("funded position boundary is absent from official sessions")
        expected_marks = {
            session
            for session in sessions
            if position.entry_session < session < position.exit_session
        }
        if set(position.marks) != expected_marks:
            raise ValueError("funded position needs an exact mark on every exposed session")
        if any(session not in baseline_by_session for session in position.dividends):
            raise ValueError("dividend evidence lies outside the official ledger")
    pairs = all_exposed_trade_session_pairs(sessions, positions)
    by_trade = {position.trade_id: position for position in positions}
    if len(by_trade) != len(positions):
        raise ValueError("funded trade identities must be unique")
    prefix_peaks, prefix_drawdowns = _baseline_prefix(baseline)
    placements = []
    for trade_id, onset in pairs:
        placements.append(
            StructuralPlacement(
                trade_id,
                onset,
                _placement_drawdown(
                    sessions,
                    baseline,
                    by_trade[trade_id],
                    onset,
                    prefix_peaks,
                    prefix_drawdowns,
                    session_index,
                ),
                len(sessions) - session_index[onset],
            )
        )
    realized = _maximum_drawdown(baseline)
    worst = max((placement.max_drawdown for placement in placements), default=realized)
    violations, envelope = _policy_violations(sessions, baseline_by_session, positions, policy)
    if realized > policy.maximum_drawdown:
        violations += ("realized_drawdown",)
    status = (
        StructuralStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
        if violations or worst > policy.maximum_drawdown
        else StructuralStatus.PASS
    )
    encoded = json.dumps(
        [
            (placement.trade_id, placement.onset.isoformat(), str(placement.max_drawdown))
            for placement in placements
        ],
        separators=(",", ":"),
    ).encode("ascii")
    return StructuralRiskResult(
        status,
        len(placements),
        tuple(placements),
        worst,
        realized,
        envelope,
        violations,
        sum(placement.affected_points for placement in placements),
        hashlib.sha256(encoded).hexdigest(),
    )


def promotion_case_from_replays(
    case: PromotionCase,
    replays: Mapping[str, SwingReplayResult],
    *,
    doubled_cost_replays: Mapping[str, SwingReplayResult] | None = None,
    recovery_replays: Mapping[str, SwingReplayResult] | None = None,
    recovery_doubled_cost_replays: Mapping[str, SwingReplayResult] | None = None,
    recovery_terminal_tail: TerminalTailResult | None = None,
    contexts: Mapping[str, PatternEdgeInputs] | None = None,
    entry_months: Sequence[str] = (),
    draws: int = 9999,
    seed: int = 0,
    candidate: InferenceCandidate = ENTRY_MONTH_WCR_S,
) -> PromotionCase:
    """Derive edge and terminal provenance from conservative/recovery replay evidence.

    Recovery is supplied explicitly; no payout is inferred from a stale mark.
    Frozen protocol inputs remain separate from recomputed economic evidence.
    """
    if not replays or (contexts is not None and set(contexts) != set(replays)):
        raise ValueError("replay patterns require matching frozen contexts")
    if tuple(sorted(set(entry_months))) != tuple(entry_months):
        raise ValueError("entry months require a complete ordered common frame")

    def validate_pair(
        baselines: Mapping[str, SwingReplayResult],
        variants: Mapping[str, SwingReplayResult],
        *,
        terminal_only: bool,
    ) -> None:
        if set(baselines) != set(variants):
            raise ValueError("replay pattern identities differ")

        def signal_identity(trade: SwingTrade) -> tuple[object, ...]:
            if terminal_only:
                return (trade.trade_id,)
            # Cost-driven sizing changes the instruction/trade ID; the signal
            # and price terms must still identify the same eligible cohort.
            return (
                trade.symbol,
                trade.patterns,
                trade.entry_session,
                trade.submitted_limit,
                trade.initial_stop,
            )

        for name, replay in baselines.items():
            baseline = {signal_identity(trade): trade for trade in replay.signal_trades}
            variant = {signal_identity(trade): trade for trade in variants[name].signal_trades}
            if (
                len(baseline) != len(replay.signal_trades)
                or len(variant) != len(variants[name].signal_trades)
                or set(baseline) != set(variant)
            ):
                raise ValueError("replay trade identities differ or are duplicated")
            for identity, trade in baseline.items():
                other = variant[identity]
                fixed: tuple[str, ...] = (
                    "symbol",
                    "patterns",
                    "entry_session",
                    "edge_sample_eligible",
                    "edge_exclusion_reason",
                )
                if terminal_only:
                    fixed += (
                        "exit_session",
                        "quantity",
                        "submitted_limit",
                        "entry_price",
                        "initial_stop",
                        "order_initial_risk_dollars",
                        "fill_initial_risk_dollars",
                        "costs",
                        "eligible_dividends",
                    )
                if any(getattr(trade, field) != getattr(other, field) for field in fixed):
                    raise ValueError("replay changed frozen economic terms or eligibility")
                if terminal_only and trade.exit_reason != "terminal_zero" and trade != other:
                    raise ValueError("recovery replay changed a nonterminal outcome")

    if doubled_cost_replays is not None:
        validate_pair(replays, doubled_cost_replays, terminal_only=False)
    if recovery_replays is not None:
        validate_pair(replays, recovery_replays, terminal_only=True)
    if recovery_doubled_cost_replays is not None:
        if doubled_cost_replays is None or recovery_replays is None:
            raise ValueError(
                "recovery doubled-cost evidence requires both conservative and recovery pairs"
            )
        validate_pair(recovery_replays, recovery_doubled_cost_replays, terminal_only=False)
        validate_pair(doubled_cost_replays, recovery_doubled_cost_replays, terminal_only=True)

    def results_for(
        rows: Mapping[str, SwingReplayResult], doubled: Mapping[str, SwingReplayResult] | None
    ) -> tuple[PatternEdgeResult, ...]:
        samples: dict[str, tuple[tuple[Decimal, ...], ...]] = {}
        for name, replay in rows.items():
            groups: dict[str, list[Decimal]] = defaultdict(list)
            for trade in replay.signal_trades:
                if trade.edge_sample_eligible:
                    groups[trade.entry_session.strftime("%Y-%m")].append(trade.order_r_multiple)
            if any(month not in entry_months for month in groups):
                raise ValueError("eligible replay entry lies outside the frozen month frame")
            samples[name] = tuple(tuple(groups[month]) for month in entry_months)
        adjusted: Mapping[str, Decimal] = {}
        lowers: dict[str, Decimal] = {}
        try:
            if all(candidate_eligible(sample, candidate) for sample in samples.values()):
                adjusted = romano_wolf_stepdown(
                    samples, draws=draws, seed=seed, candidate=candidate
                ).adjusted_p_values
                lowers = {
                    name: wcr_s_mean_test(
                        sample, draws=draws, seed=seed, candidate=candidate
                    ).lower_bound
                    for name, sample in samples.items()
                }
        except ValueError:
            # Insufficient clusters/variance cannot become passing inference.
            pass
        results = []
        for name, replay in rows.items():
            context = (
                contexts[name]
                if contexts is not None
                else PatternEdgeInputs(
                    name,
                    (),
                    100,
                    36,
                    None,
                    None,
                    None,
                    None,
                    None,
                    len(entry_months),
                    False,
                    False,
                    False,
                )
            )
            trades = tuple(
                SignalEdgeTrade(
                    trade.trade_id,
                    trade.symbol,
                    trade.entry_session,
                    trade.order_r_multiple,
                    trade.net_pnl,
                    trade.edge_sample_eligible,
                )
                for trade in replay.signal_trades
            )
            doubled_trades = (
                tuple(trade for trade in doubled[name].signal_trades if trade.edge_sample_eligible)
                if doubled is not None
                and name in doubled
                and doubled[name].status is RunStatus.VALID
                else ()
            )
            double_mean = (
                sum((trade.order_r_multiple for trade in doubled_trades), Decimal(0))
                / Decimal(len(doubled_trades))
                if doubled_trades
                else None
            )
            result = evaluate_pattern_edge_gates(
                replace(
                    context,
                    trades=trades,
                    wcr_lower_bound=lowers.get(name),
                    romano_wolf_adjusted_p=adjusted.get(name),
                    doubled_cost_expectancy=double_mean,
                    inference_clusters=candidate_cluster_count(samples[name], candidate),
                )
            )
            results.append(
                result if replay.status is RunStatus.VALID else replace(result, passed=False)
            )
        return tuple(results)

    conservative = results_for(replays, doubled_cost_replays)
    edge_pass = all(result.passed for result in conservative)
    has_terminal = any(
        trade.exit_reason == "terminal_zero" and trade.edge_sample_eligible
        for replay in replays.values()
        for trade in replay.signal_trades
    )
    recovery_tail_pass = case.terminal_tail is None or (
        recovery_terminal_tail is not None
        and recovery_terminal_tail.analytical_parity_pass
        and recovery_terminal_tail.fifth_percentile_mean_r > 0
        and recovery_terminal_tail.drawdown_95 <= Decimal("0.2")
    )
    recovery_pass = bool(
        has_terminal
        and recovery_replays is not None
        and case.portfolio_safety_pass is not False
        and recovery_tail_pass
        and all(
            result.passed for result in results_for(recovery_replays, recovery_doubled_cost_replays)
        )
    )
    return replace(
        case,
        data_valid=case.data_valid
        and all(replay.status is RunStatus.VALID for replay in replays.values()),
        pattern_edges=conservative,
        all_edge_gates_pass=edge_pass,
        conservative_terminal_gate_pass=edge_pass if has_terminal else None,
        recovery_sensitivity_pass=recovery_pass,
    )


def evaluate_promotion(case: PromotionCase) -> PromotionVerdict:
    """Keep Phase 2 evidence non-promotional while retaining gate provenance."""
    feasibility = case.feasibility
    reason = feasibility.status if feasibility is not None else None
    required = feasibility.required_months if feasibility is not None else None
    available = feasibility.available_months if feasibility is not None else None
    binding = feasibility.binding_pattern if feasibility is not None else None
    rate_source = feasibility.binding_rate_source if feasibility is not None else None
    forward = bool(feasibility and feasibility.forward_acquisition_could_help)
    edge_pass = case.all_edge_gates_pass
    if case.pattern_edges:
        constituent_pass = all(result.passed for result in case.pattern_edges)
        edge_pass = constituent_pass if edge_pass is None else edge_pass and constituent_pass
    recommended = required if reason is FeasibilityStatus.DATASET_INSUFFICIENT and forward else None
    gates = (
        GateResult("dataset_valid", case.data_valid, "dataset-wide integrity"),
        GateResult(
            "incidence",
            case.incidence.status is PromotionStatus.PASS if case.incidence else None,
            "support-matched reference",
        ),
        GateResult(
            "structural",
            case.structural.status is StructuralStatus.PASS if case.structural else None,
            "every funded exposure placement",
        ),
        GateResult(
            "method",
            case.method_status is MethodStatus.METHOD_ADEQUATE if case.method_status else None,
            "declared method size",
        ),
        GateResult("edge", edge_pass, "seven frozen gates for every constituent pattern"),
        GateResult("portfolio", case.portfolio_safety_pass, "cash-funded safety"),
        GateResult(
            "conservative_terminal",
            case.conservative_terminal_gate_pass,
            "all conservative replay edge gates with unresolved terminal zero",
        ),
        GateResult(
            "recovery_sensitivity",
            case.recovery_sensitivity_pass,
            "all gates on explicit matching recovery replays; absent evidence cannot pass",
        ),
        GateResult(
            "terminal_mean_r",
            case.terminal_tail.fifth_percentile_mean_r > 0 if case.terminal_tail else None,
            "calibrated fifth percentile of mean net R_order",
        ),
        GateResult(
            "terminal_drawdown",
            case.terminal_tail.drawdown_95 <= Decimal("0.2") if case.terminal_tail else None,
            "calibrated 95th-percentile cash drawdown",
        ),
    )
    if not case.data_valid or (
        case.terminal_tail and not case.terminal_tail.analytical_parity_pass
    ):
        status = PromotionStatus.INVALID
        action = "repair dataset or terminal expected-value parity before scoring"
    elif case.incidence and case.incidence.status is PromotionStatus.INCIDENCE_DATA_INSUFFICIENT:
        status = PromotionStatus.INCIDENCE_DATA_INSUFFICIENT
        action = "acquire support-matched reference exposure"
        recommended = None
        forward = False
    elif (
        case.structural
        and case.structural.status is StructuralStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
    ):
        status = PromotionStatus.PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE
        action = "revise Phase 4 policy in a new signed lineage"
        recommended = None
        forward = False
    elif case.method_status is MethodStatus.METHOD_INADEQUATE:
        status = PromotionStatus.METHOD_INADEQUATE
        action = "redesign and redeclare the inferential method"
        recommended = None
        forward = False
    elif case.evidence_tier != "promotion_point_in_time":
        status = PromotionStatus.PORTFOLIO_RISK_DESIGN_PENDING
        action = "freeze Phase 4 risk policy and complete Phase 2D controls"
    elif reason in {
        FeasibilityStatus.DATASET_INSUFFICIENT,
        FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON,
    }:
        status = PromotionStatus.INSUFFICIENT_EVIDENCE
        action = (
            "acquire untouched forward holdout months"
            if reason is FeasibilityStatus.DATASET_INSUFFICIENT
            else "do not extend within the declared 120-month horizon"
        )
    elif (
        case.conservative_terminal_gate_pass is False
        and case.recovery_sensitivity_pass
        and case.portfolio_safety_pass is not False
    ):
        status = PromotionStatus.TERMINAL_OUTCOME_SENSITIVE
        action = "retain the conservative non-promotional terminal result"
    elif edge_pass is False or (
        case.terminal_tail and case.terminal_tail.fifth_percentile_mean_r <= 0
    ):
        status = PromotionStatus.FAIL
        action = "retain failed pattern or terminal edge evidence"
    elif edge_pass and (
        case.portfolio_safety_pass is False
        or (case.terminal_tail and case.terminal_tail.drawdown_95 > Decimal("0.2"))
    ):
        status = PromotionStatus.EDGE_PASS_PORTFOLIO_RISK_BLOCKED
        action = "retain edge evidence without shadow authorization"
    elif case.conservative_terminal_gate_pass is False:
        status = PromotionStatus.FAIL
        action = "retain the conservative terminal failure"
    else:
        status = PromotionStatus.INSUFFICIENT_EVIDENCE
        action = "complete Phase 2D declarations, permit, and exposure checks"
    return PromotionVerdict(
        status,
        gates,
        reason,
        required,
        available,
        binding,
        rate_source,
        recommended,
        action,
        forward,
    )
