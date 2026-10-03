"""Frozen synthetic method audit, power requirements, and holdout feasibility."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import NormalDist
from types import MappingProxyType

import numpy as np

from qat.domain.backtester.swing_results import SwingTrade
from qat.domain.backtester.swing_statistics import romano_wolf_stepdown, wcr_s_pvalue
from qat.domain.backtester.swing_validation import PartitionWindow
from qat.domain.strategies.authoritative_swing.model import Pattern


class MethodStatus(StrEnum):
    METHOD_ADEQUATE = "METHOD_ADEQUATE"
    METHOD_AUDIT_PENDING = "METHOD_AUDIT_PENDING"
    METHOD_INADEQUATE = "METHOD_INADEQUATE"


class FeasibilityStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    DATASET_INSUFFICIENT = "DATASET_INSUFFICIENT"
    FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON = "FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON"


@dataclass(frozen=True, slots=True)
class MethodAuditProtocol:
    mandatory_scenarios: tuple[str, ...]
    declaration_sha256: str | None = None
    scenario_matrix_sha256: str | None = None
    pilot_sha256: str | None = None
    inner_draws: int = 9_999
    initial_outer_runs: int = 20_000
    maximum_outer_runs: int = 100_000
    seed: int = 0
    null_configurations: tuple[str, ...] = (
        "000",
        "d00",
        "0d0",
        "00d",
        "dd0",
        "d0d",
        "0dd",
    )

    def __post_init__(self) -> None:
        if not self.mandatory_scenarios or len(set(self.mandatory_scenarios)) != len(
            self.mandatory_scenarios
        ):
            raise ValueError("mandatory scenarios must be unique and nonempty")
        if (self.inner_draws, self.initial_outer_runs, self.maximum_outer_runs) != (
            9_999,
            20_000,
            100_000,
        ):
            raise ValueError("promotion method-audit simulation counts are frozen")


@dataclass(frozen=True, slots=True)
class ScenarioSizeAudit:
    scenario_id: str
    gate: str
    outer_runs: int
    false_rejections: int
    attempts_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.gate not in {"confidence", "family"}:
            raise ValueError("size gate must be confidence or family")
        if (
            self.outer_runs not in {20_000, 100_000}
            or not 0 <= self.false_rejections <= self.outer_runs
        ):
            raise ValueError("invalid method-size simulation count")


@dataclass(frozen=True, slots=True)
class SyntheticScenario:
    scenario_id: str
    family: str
    months: int
    observations_per_month: int
    block_months: int
    null_configuration: str
    delta_mme: Decimal
    imbalance: str = "observed"
    terminal_probability: Decimal = Decimal(0)
    terminal_severity: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.family not in {"gaussian", "empirical_skew", "terminal_mixture"}:
            raise ValueError("pilot accepts only declared synthetic families")
        if self.block_months not in {3, 6, 12} or self.months < 12:
            raise ValueError("pilot requires a declared 3/6/12-month block design")
        if self.observations_per_month <= 0 or self.imbalance not in {"observed", "stressed"}:
            raise ValueError("pilot month-size design is invalid")
        if self.null_configuration not in {"000", "d00", "0d0", "00d", "dd0", "d0d", "0dd"}:
            raise ValueError("pilot requires a complete or partial null")
        if not self.delta_mme.is_finite() or self.delta_mme <= 0:
            raise ValueError("pilot delta_MME must be positive")
        if not Decimal(0) <= self.terminal_probability <= Decimal(1) or self.terminal_severity > 0:
            raise ValueError("terminal contamination needs probability and nonpositive severity")


@dataclass(frozen=True, slots=True)
class SyntheticPilotAttempt:
    attempt: int
    confidence_rejections: tuple[bool, bool, bool]
    family_false_positive: bool


@dataclass(frozen=True, slots=True)
class SyntheticPilotResult:
    scenario_id: str
    null_configuration: str
    attempts: tuple[SyntheticPilotAttempt, ...]
    attempts_sha256: str
    promotion_eligible: bool

    def size_audits(self) -> tuple[ScenarioSizeAudit, ScenarioSizeAudit]:
        if not self.promotion_eligible:
            raise ValueError("diagnostic pilot cannot supply a promotion method audit")
        null_indices = tuple(
            index for index, flag in enumerate(self.null_configuration) if flag == "0"
        )
        worst_pattern_count = max(
            sum(attempt.confidence_rejections[index] for attempt in self.attempts)
            for index in null_indices
        )
        return (
            ScenarioSizeAudit(
                f"{self.scenario_id}:confidence",
                "confidence",
                len(self.attempts),
                worst_pattern_count,
                self.attempts_sha256,
            ),
            ScenarioSizeAudit(
                f"{self.scenario_id}:family",
                "family",
                len(self.attempts),
                sum(attempt.family_false_positive for attempt in self.attempts),
                self.attempts_sha256,
            ),
        )


def _synthetic_months(
    scenario: SyntheticScenario, rng: np.random.Generator
) -> Mapping[str, tuple[tuple[Decimal, ...], ...]]:
    names = ("ema_pullback", "bull_flag", "double_bottom")
    block_count = math.ceil(scenario.months / scenario.block_months)
    common = np.repeat(rng.normal(size=block_count), scenario.block_months)[: scenario.months]
    results: dict[str, tuple[tuple[Decimal, ...], ...]] = {}
    for pattern_index, name in enumerate(names):
        months: list[tuple[Decimal, ...]] = []
        for month_index in range(scenario.months):
            count = scenario.observations_per_month
            if scenario.imbalance == "stressed":
                count = max(1, count // 2) if month_index % 3 else count * 3
            values: list[Decimal] = []
            for _ in range(count):
                value = 0.35 * common[month_index] + rng.normal()
                if scenario.family == "empirical_skew":
                    value += rng.exponential() - 1.0
                if scenario.family == "terminal_mixture":
                    probability = float(scenario.terminal_probability)
                    severity = float(scenario.terminal_severity)
                    value += (
                        severity if rng.random() < probability else 0.0
                    ) - probability * severity
                if scenario.null_configuration[pattern_index] == "d":
                    value += float(scenario.delta_mme)
                values.append(Decimal(str(float(value))))
            months.append(tuple(values))
        results[name] = tuple(months)
    return MappingProxyType(results)


def run_synthetic_pilot(
    scenario: SyntheticScenario,
    *,
    outer_runs: int = 20_000,
    inner_draws: int = 9_999,
    seed: int,
    diagnostic: bool = False,
) -> SyntheticPilotResult:
    """Retain every generic synthetic attempt; short diagnostics cannot promote."""
    if outer_runs <= 0 or inner_draws <= 0:
        raise ValueError("pilot simulation counts must be positive")
    if not diagnostic and (outer_runs not in {20_000, 100_000} or inner_draws != 9_999):
        raise ValueError("promotion pilot counts are frozen at 20k/100k outer and 9999 inner")
    rng = np.random.Generator(np.random.PCG64(seed))
    names = ("ema_pullback", "bull_flag", "double_bottom")
    null_names = tuple(
        name for index, name in enumerate(names) if scenario.null_configuration[index] == "0"
    )
    attempts: list[SyntheticPilotAttempt] = []
    for index in range(outer_runs):
        months = _synthetic_months(scenario, rng)
        weights = np.where(
            rng.integers(0, 2, size=(inner_draws, scenario.months)) == 0, -1, 1
        ).tolist()
        confidence_rejections = tuple(
            scenario.null_configuration[pattern_index] == "0"
            and wcr_s_pvalue(months[name], weights=weights) < Decimal("0.025")
            for pattern_index, name in enumerate(names)
        )
        family = romano_wolf_stepdown(months, weights=weights)
        family_false = any(family.adjusted_p_values[name] < Decimal("0.05") for name in null_names)
        attempts.append(
            SyntheticPilotAttempt(
                index,
                (confidence_rejections[0], confidence_rejections[1], confidence_rejections[2]),
                family_false,
            )
        )
    encoded = json.dumps(
        [
            (attempt.attempt, attempt.confidence_rejections, attempt.family_false_positive)
            for attempt in attempts
        ],
        separators=(",", ":"),
    ).encode("ascii")
    return SyntheticPilotResult(
        scenario.scenario_id,
        scenario.null_configuration,
        tuple(attempts),
        hashlib.sha256(encoded).hexdigest(),
        not diagnostic,
    )


@dataclass(frozen=True, slots=True)
class ScenarioSizeDecision:
    scenario_id: str
    gate: str
    outer_runs: int
    point_rate: Decimal
    lower_95: Decimal
    upper_95: Decimal
    cap: Decimal
    status: MethodStatus


@dataclass(frozen=True, slots=True)
class MethodAuditResult:
    status: MethodStatus
    worst_scenario: str | None
    requested_outer_runs: int
    scenarios: tuple[ScenarioSizeDecision, ...]
    evidence_complete: bool = False


@dataclass(frozen=True, slots=True)
class PowerScenario:
    scenario_id: str
    pattern: str
    sample_size: int
    nonempty_clusters: int
    effect: Decimal
    trials: int
    rejections: int


@dataclass(frozen=True, slots=True)
class PowerRequirement:
    pattern: str
    n_required: int
    g_required: int
    minimum_detectable_effect: Decimal
    prospective_power: Decimal

    def __post_init__(self) -> None:
        if self.n_required < 100 or self.g_required <= 0:
            raise ValueError("power requirement needs at least 100 trades and positive clusters")
        if self.minimum_detectable_effect <= 0 or self.prospective_power < Decimal("0.8"):
            raise ValueError("power requirement needs a positive effect and at least 80% power")


@dataclass(frozen=True, slots=True)
class FrequencyPlan:
    status: FeasibilityStatus
    required_months: int | None
    available_months: int
    shortfall_months: int | None
    binding_pattern: str | None
    binding_rate_source: str | None
    predictive_probabilities: Mapping[str, Decimal]
    expected_counts: Mapping[str, Decimal]
    percentile_counts: Mapping[str, tuple[int, int, int]]
    stress_rates: Mapping[str, Decimal]
    rolling_window_count: int
    rolling_window_overlap: int
    forward_acquisition_could_help: bool
    edge_precondition_satisfied: bool

    def __post_init__(self) -> None:
        for name in (
            "predictive_probabilities",
            "expected_counts",
            "percentile_counts",
            "stress_rates",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def _wilson_one_sided(rejections: int, trials: int) -> tuple[Decimal, Decimal]:
    z = NormalDist().inv_cdf(0.95)
    proportion = rejections / trials
    correction = z * z / trials
    center = (proportion + correction / 2) / (1 + correction)
    half = z * math.sqrt(proportion * (1 - proportion) / trials + correction / (4 * trials))
    half /= 1 + correction
    return Decimal(str(max(0.0, center - half))), Decimal(str(min(1.0, center + half)))


def audit_method_size(
    protocol: MethodAuditProtocol, audits: Sequence[ScenarioSizeAudit]
) -> MethodAuditResult:
    """Adjudicate every declared synthetic cell using upper Monte Carlo limits."""
    expected = set(protocol.mandatory_scenarios)
    if {audit.scenario_id for audit in audits} != expected or len(audits) != len(expected):
        raise ValueError("every mandatory method-audit scenario needs one result")
    decisions: list[ScenarioSizeDecision] = []
    for audit in audits:
        cap = Decimal("0.0325") if audit.gate == "confidence" else Decimal("0.06")
        lower, upper = _wilson_one_sided(audit.false_rejections, audit.outer_runs)
        if audit.outer_runs == protocol.initial_outer_runs:
            if upper <= cap - Decimal("0.0025"):
                status = MethodStatus.METHOD_ADEQUATE
            elif lower >= cap + Decimal("0.0025"):
                status = MethodStatus.METHOD_INADEQUATE
            else:
                status = MethodStatus.METHOD_AUDIT_PENDING
        else:
            status = (
                MethodStatus.METHOD_ADEQUATE if upper <= cap else MethodStatus.METHOD_INADEQUATE
            )
        decisions.append(
            ScenarioSizeDecision(
                audit.scenario_id,
                audit.gate,
                audit.outer_runs,
                Decimal(audit.false_rejections) / Decimal(audit.outer_runs),
                lower,
                upper,
                cap,
                status,
            )
        )
    failures = [
        decision for decision in decisions if decision.status is MethodStatus.METHOD_INADEQUATE
    ]
    pending = [
        decision for decision in decisions if decision.status is MethodStatus.METHOD_AUDIT_PENDING
    ]
    evidence_complete = all(
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        for digest in (
            protocol.declaration_sha256,
            protocol.scenario_matrix_sha256,
            protocol.pilot_sha256,
            *(audit.attempts_sha256 for audit in audits),
        )
    )
    if failures:
        worst = max(failures, key=lambda decision: decision.upper_95 - decision.cap)
        return MethodAuditResult(
            MethodStatus.METHOD_INADEQUATE,
            worst.scenario_id,
            0,
            tuple(decisions),
            evidence_complete,
        )
    if pending:
        return MethodAuditResult(
            MethodStatus.METHOD_AUDIT_PENDING,
            max(pending, key=lambda decision: decision.upper_95 - decision.cap).scenario_id,
            protocol.maximum_outer_runs,
            tuple(decisions),
            evidence_complete,
        )
    if not evidence_complete:
        return MethodAuditResult(MethodStatus.METHOD_AUDIT_PENDING, None, 0, tuple(decisions))
    return MethodAuditResult(MethodStatus.METHOD_ADEQUATE, None, 0, tuple(decisions), True)


def audit_power(
    scenarios: Sequence[PowerScenario],
    *,
    mandatory_scenarios: Sequence[str],
    delta_mme: Decimal,
) -> Mapping[str, PowerRequirement]:
    """Take the maximum 80%-power requirement over all declared scenarios."""
    if not delta_mme.is_finite() or delta_mme <= 0:
        raise ValueError("externally declared delta_MME must be positive")
    if not scenarios or not mandatory_scenarios:
        raise ValueError("power audit needs mandatory synthetic scenarios")
    grouped: dict[str, dict[str, list[PowerScenario]]] = defaultdict(lambda: defaultdict(list))
    for scenario in scenarios:
        if (
            scenario.effect != delta_mme
            or scenario.sample_size < 100
            or scenario.nonempty_clusters <= 0
            or scenario.trials <= 0
            or not 0 <= scenario.rejections <= scenario.trials
        ):
            raise ValueError("power trial conflicts with the declared effect or sample contract")
        grouped[scenario.pattern][scenario.scenario_id].append(scenario)
    requirements: dict[str, PowerRequirement] = {}
    for pattern, by_scenario in grouped.items():
        if set(by_scenario) != set(mandatory_scenarios):
            raise ValueError("each pattern needs every mandatory power scenario")
        selected: list[PowerScenario] = []
        for scenario_id in mandatory_scenarios:
            candidates = sorted(by_scenario[scenario_id], key=lambda item: item.sample_size)
            adequate = [
                trial
                for trial in candidates
                if Decimal(trial.rejections) / Decimal(trial.trials) >= Decimal("0.8")
            ]
            if not adequate:
                raise ValueError(f"80% power was not demonstrated for {pattern}/{scenario_id}")
            selected.append(adequate[0])
        requirements[pattern] = PowerRequirement(
            pattern,
            max(trial.sample_size for trial in selected),
            max(trial.nonempty_clusters for trial in selected),
            delta_mme,
            min(Decimal(trial.rejections) / Decimal(trial.trials) for trial in selected),
        )
    return MappingProxyType(requirements)


def eligible_month_count_vector(
    window: PartitionWindow, trades: Sequence[SwingTrade], pattern: Pattern
) -> tuple[int, ...]:
    """Include genuine zero months while excluding tail and overlap entries."""
    counts = {month: 0 for month in window.signal_months}
    eligible_sessions = set(window.signal_sessions)
    for trade in trades:
        if (
            trade.edge_sample_eligible
            and pattern in trade.patterns
            and trade.entry_session in eligible_sessions
        ):
            counts[trade.entry_session.strftime("%Y-%m")] += 1
    return tuple(counts[month] for month in window.signal_months)


def _count_frame(
    development: Mapping[str, Sequence[int]], validation: Mapping[str, Sequence[int]]
) -> tuple[tuple[str, ...], tuple[tuple[int, ...], ...], tuple[tuple[int, ...], ...]]:
    patterns = tuple(sorted(development))
    if not patterns or set(patterns) != set(validation):
        raise ValueError("development and validation need the same pattern count vectors")
    development_lengths = {len(development[name]) for name in patterns}
    validation_lengths = {len(validation[name]) for name in patterns}
    if len(development_lengths) != 1 or len(validation_lengths) != 1:
        raise ValueError("pattern count vectors must share each partition's month frame")
    if next(iter(development_lengths)) < 36 or next(iter(validation_lengths)) == 0:
        raise ValueError("frequency needs 36 development months and validation history")
    for values in (*development.values(), *validation.values()):
        if any(not isinstance(value, int) or value < 0 for value in values):
            raise ValueError("monthly entry counts must be nonnegative integers")
    development_frame = tuple(
        tuple(development[name][i] for name in patterns)
        for i in range(next(iter(development_lengths)))
    )
    validation_frame = tuple(
        tuple(validation[name][i] for name in patterns)
        for i in range(next(iter(validation_lengths)))
    )
    return patterns, development_frame, validation_frame


def _predictive_lower(counts: Sequence[int]) -> Decimal:
    mean = sum(counts) / len(counts)
    if len(counts) == 1:
        return Decimal(str(mean))
    variance = sum((value - mean) ** 2 for value in counts) / (len(counts) - 1)
    # Predict one future monthly count, including its observation variance;
    # variance / n alone would bound the historical mean instead.
    lower = max(
        0.0,
        mean - NormalDist().inv_cdf(0.9) * math.sqrt(variance * (1 + 1 / len(counts))),
    )
    return Decimal(str(lower))


def _sample_path(
    development: tuple[tuple[int, ...], ...],
    validation: tuple[tuple[int, ...], ...],
    block_size: int,
    rng: random.Random,
) -> tuple[tuple[int, ...], ...]:
    path: list[tuple[int, ...]] = []
    while len(path) < 120:
        source = (
            development
            if rng.randrange(len(development) + len(validation)) < len(development)
            else validation
        )
        start = rng.randrange(len(source))
        path.extend(source[(start + offset) % len(source)] for offset in range(block_size))
    return tuple(path[:120])


def plan_holdout_duration(
    *,
    development: Mapping[str, Sequence[int]],
    validation: Mapping[str, Sequence[int]],
    requirements: Mapping[str, PowerRequirement],
    available_months: int,
    development_validation_expectancy: Mapping[str, Decimal] | None = None,
    simulations: int = 9_999,
    seed: int = 0,
) -> FrequencyPlan:
    """Find the first holdout duration meeting joint baseline and stress power."""
    patterns, development_frame, validation_frame = _count_frame(development, validation)
    if set(patterns) != set(requirements) or any(
        requirement.pattern != name for name, requirement in requirements.items()
    ):
        raise ValueError("every pattern needs a matching frozen power requirement")
    if development_validation_expectancy is not None:
        if set(development_validation_expectancy) != set(patterns) or any(
            not value.is_finite() or value <= 0
            for value in development_validation_expectancy.values()
        ):
            raise ValueError("nonpositive development/validation expectancy refuses holdout")
    if simulations <= 0 or available_months < 0:
        raise ValueError("simulations must be positive and available months nonnegative")
    rolling_count = len(development_frame) - 35
    stress_rates: dict[str, Decimal] = {}
    rate_sources: dict[str, str] = {}
    baseline_rates: dict[str, Decimal] = {}
    for index, name in enumerate(patterns):
        development_counts = [row[index] for row in development_frame]
        validation_counts = [row[index] for row in validation_frame]
        rolling = min(
            Decimal(sum(development_counts[start : start + 36])) / Decimal(36)
            for start in range(rolling_count)
        )
        validation_rate = Decimal(sum(validation_counts)) / Decimal(len(validation_counts))
        predictive = _predictive_lower((*development_counts, *validation_counts))
        options = {
            "rolling_36_development": rolling,
            "full_validation": validation_rate,
            "predictive_90_lower": predictive,
        }
        rate_sources[name], stress_rates[name] = min(
            options.items(), key=lambda item: (item[1], item[0])
        )
        baseline_rates[name] = Decimal(sum(development_counts) + sum(validation_counts)) / Decimal(
            len(development_counts) + len(validation_counts)
        )

    baseline_paths: dict[int, list[np.ndarray]] = {3: [], 6: [], 12: []}
    baseline_clusters: dict[int, list[np.ndarray]] = {3: [], 6: [], 12: []}
    stress_paths: dict[int, list[np.ndarray]] = {3: [], 6: [], 12: []}
    stress_clusters: dict[int, list[np.ndarray]] = {3: [], 6: [], 12: []}
    rng = random.Random(seed)
    thinning_rng = np.random.Generator(np.random.PCG64(seed))
    ratios = np.asarray(
        [
            (
                min(1.0, float(stress_rates[name] / baseline_rates[name]))
                if baseline_rates[name] > 0
                else 0.0
            )
            for name in patterns
        ]
    )
    for block_size in (3, 6, 12):
        for _ in range(simulations):
            sampled = np.asarray(
                _sample_path(development_frame, validation_frame, block_size, rng), dtype=np.int64
            )
            stressed = thinning_rng.binomial(sampled, ratios)
            baseline_paths[block_size].append(np.cumsum(sampled, axis=0))
            baseline_clusters[block_size].append(np.cumsum(sampled > 0, axis=0))
            stress_paths[block_size].append(np.cumsum(stressed, axis=0))
            stress_clusters[block_size].append(np.cumsum(stressed > 0, axis=0))

    required: int | None = None
    chosen_probabilities: dict[str, Decimal] = {}
    required_n = np.asarray([requirements[name].n_required for name in patterns])
    required_g = np.asarray([requirements[name].g_required for name in patterns])
    for duration in range(36, 121):
        probabilities: dict[str, Decimal] = {}
        for label, paths, clusters in (
            ("baseline", baseline_paths, baseline_clusters),
            ("stressed", stress_paths, stress_clusters),
        ):
            block_probabilities = []
            for block_size in (3, 6, 12):
                successes = sum(
                    bool(
                        np.all(path[duration - 1] >= required_n)
                        and np.all(group[duration - 1] >= required_g)
                    )
                    for path, group in zip(paths[block_size], clusters[block_size], strict=True)
                )
                block_probabilities.append(Decimal(successes) / Decimal(simulations))
            probabilities[label] = min(block_probabilities)
        chosen_probabilities = probabilities
        if probabilities["baseline"] >= Decimal("0.9") and probabilities["stressed"] >= Decimal(
            "0.8"
        ):
            required = duration
            break

    horizon = required or 120
    counts = np.asarray(
        [path[horizon - 1] for paths in baseline_paths.values() for path in paths], dtype=np.int64
    )
    expected = {name: Decimal(str(float(np.mean(counts[:, i])))) for i, name in enumerate(patterns)}
    percentiles: dict[str, tuple[int, int, int]] = {
        name: (
            int(np.percentile(counts[:, i], 10, method="lower")),
            int(np.percentile(counts[:, i], 5, method="lower")),
            int(np.percentile(counts[:, i], 1, method="lower")),
        )
        for i, name in enumerate(patterns)
    }
    binding_pattern = max(
        patterns,
        key=lambda name: (
            Decimal(requirements[name].n_required) / stress_rates[name]
            if stress_rates[name] > 0
            else Decimal("Infinity")
        ),
    )
    status = (
        FeasibilityStatus.FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON
        if required is None
        else (
            FeasibilityStatus.DATASET_INSUFFICIENT
            if required > available_months
            else FeasibilityStatus.FEASIBLE
        )
    )
    return FrequencyPlan(
        status,
        required,
        available_months,
        max(0, required - available_months) if required is not None else None,
        binding_pattern,
        rate_sources[binding_pattern],
        chosen_probabilities,
        expected,
        percentiles,
        stress_rates,
        rolling_count,
        35,
        status is FeasibilityStatus.DATASET_INSUFFICIENT,
        development_validation_expectancy is not None,
    )
