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
from qat.domain.backtester.swing_statistics import (
    ENTRY_MONTH_WCR_S,
    InferenceCandidate,
    romano_wolf_stepdown,
    wcr_s_pvalue,
)
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
    mandatory_power_scenarios: tuple[str, ...] = ()
    candidate_methods: tuple[InferenceCandidate, ...] = (ENTRY_MONTH_WCR_S,)
    projection_sample_size: int = 100
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
        if not self.candidate_methods or len(set(self.candidate_methods)) != len(
            self.candidate_methods
        ):
            raise ValueError("candidate methods must be unique and nonempty")
        if self.projection_sample_size < 100:
            raise ValueError("power projection needs at least 100 trades")


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
        if self.family not in {
            "gaussian",
            "empirical_skew",
            "terminal_mixture",
            "calibrated_block",
        }:
            raise ValueError("pilot accepts only declared synthetic families")
        if not 1 <= self.block_months <= 12 or self.months < 12:
            raise ValueError("pilot requires a declared 1–12-month block design")
        if self.observations_per_month <= 0 or self.imbalance not in {"observed", "stressed"}:
            raise ValueError("pilot month-size design is invalid")
        if self.null_configuration not in {"000", "d00", "0d0", "00d", "dd0", "d0d", "0dd"}:
            raise ValueError("pilot requires a complete or partial null")
        if not self.delta_mme.is_finite() or self.delta_mme <= 0:
            raise ValueError("pilot delta_MME must be positive")
        if not Decimal(0) <= self.terminal_probability <= Decimal(1) or self.terminal_severity > 0:
            raise ValueError("terminal contamination needs probability and nonpositive severity")


@dataclass(frozen=True, slots=True)
class CalibratedResidualFrame:
    development: Mapping[str, tuple[tuple[Decimal, ...], ...]]
    validation: Mapping[str, tuple[tuple[Decimal, ...], ...]]

    def __post_init__(self) -> None:
        names = {"ema_pullback", "bull_flag", "double_bottom"}
        if set(self.development) != names or set(self.validation) != names:
            raise ValueError("calibration needs all three joint pattern frames")
        for part in (self.development, self.validation):
            lengths = {len(months) for months in part.values()}
            if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
                raise ValueError("calibration needs complete aligned months")
            if any(
                not value.is_finite()
                for months in part.values()
                for month in months
                for value in month
            ):
                raise ValueError("calibration residuals must be finite")
        object.__setattr__(
            self,
            "development",
            MappingProxyType(
                {
                    name: tuple(tuple(month) for month in months)
                    for name, months in self.development.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "validation",
            MappingProxyType(
                {
                    name: tuple(tuple(month) for month in months)
                    for name, months in self.validation.items()
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class AuditScenarioMatrix:
    mandatory: tuple[SyntheticScenario, ...]
    sensitivity: tuple[SyntheticScenario, ...]
    sha256: str


def build_audit_scenario_matrix(
    *,
    months: int,
    observations_per_month: int,
    delta_mme: Decimal,
    calibrated_block_months: Sequence[int],
    generic_persistence_months: Sequence[int],
    mandatory_generic_max_months: int,
    null_configurations: Sequence[str],
    generic_families: Sequence[str],
    imbalance_modes: Sequence[str],
    terminal_probability: Decimal = Decimal(0),
    terminal_severity: Decimal = Decimal(0),
) -> AuditScenarioMatrix:
    """Build the frozen matrix; longer generic persistence remains sensitivity."""
    if (
        not calibrated_block_months
        or not generic_persistence_months
        or not null_configurations
        or not generic_families
        or not imbalance_modes
    ):
        raise ValueError("scenario matrix axes must be nonempty")
    if any(
        len(set(axis)) != len(axis)
        for axis in (
            calibrated_block_months,
            generic_persistence_months,
            null_configurations,
            generic_families,
            imbalance_modes,
        )
    ):
        raise ValueError("scenario matrix axes must not contain duplicates")
    if mandatory_generic_max_months < 1 or any(
        not 1 <= length <= 12 for length in (*calibrated_block_months, *generic_persistence_months)
    ):
        raise ValueError("scenario matrix requires declared 1–12-month lengths")
    if "terminal_mixture" in generic_families and (
        terminal_probability <= 0 or terminal_severity >= 0
    ):
        raise ValueError("terminal mixture needs a calibrated nonzero envelope")
    mandatory: list[SyntheticScenario] = []
    sensitivity: list[SyntheticScenario] = []
    for family, lengths in (
        ("calibrated_block", calibrated_block_months),
        *((name, generic_persistence_months) for name in generic_families),
    ):
        for length in lengths:
            for imbalance in imbalance_modes:
                for null in null_configurations:
                    label = "calibrated" if family == "calibrated_block" else family
                    suffix = "" if imbalance == "observed" else f"-{imbalance}"
                    scenario = SyntheticScenario(
                        scenario_id=f"{label}-L{length}-{null}{suffix}",
                        family=family,
                        months=months,
                        observations_per_month=observations_per_month,
                        block_months=length,
                        null_configuration=null,
                        delta_mme=delta_mme,
                        imbalance=imbalance,
                        terminal_probability=(
                            terminal_probability if family == "terminal_mixture" else Decimal(0)
                        ),
                        terminal_severity=(
                            terminal_severity if family == "terminal_mixture" else Decimal(0)
                        ),
                    )
                    if family == "calibrated_block" or length <= mandatory_generic_max_months:
                        mandatory.append(scenario)
                    else:
                        sensitivity.append(scenario)
    encoded = json.dumps(
        [
            (
                scenario.scenario_id,
                scenario.family,
                scenario.months,
                scenario.observations_per_month,
                scenario.block_months,
                scenario.null_configuration,
                str(scenario.delta_mme),
                scenario.imbalance,
                str(scenario.terminal_probability),
                str(scenario.terminal_severity),
                role,
            )
            for role, scenarios in (("mandatory", mandatory), ("sensitivity", sensitivity))
            for scenario in scenarios
        ],
        separators=(",", ":"),
    ).encode("ascii")
    return AuditScenarioMatrix(
        tuple(mandatory), tuple(sensitivity), hashlib.sha256(encoded).hexdigest()
    )


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
    candidate: InferenceCandidate = ENTRY_MONTH_WCR_S
    shared_inputs_sha256: str = ""

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
    scenario: SyntheticScenario,
    rng: np.random.Generator,
    *,
    calibration: CalibratedResidualFrame | None = None,
) -> Mapping[str, tuple[tuple[Decimal, ...], ...]]:
    names = ("ema_pullback", "bull_flag", "double_bottom")
    if scenario.family == "calibrated_block":
        if calibration is None:
            raise ValueError("calibrated scenario needs a development/validation calibration frame")
        sources = (calibration.development, calibration.validation)
        eligible_starts = tuple(
            (source_index, start)
            for source_index, source in enumerate(sources)
            for start in range(len(source[names[0]]) - scenario.block_months + 1)
        )
        if not eligible_starts:
            raise ValueError("calibration partitions are shorter than the declared block")
        centers: dict[str, Decimal] = {}
        for name in names:
            values = tuple(value for source in sources for month in source[name] for value in month)
            if not values:
                raise ValueError("calibration needs eligible residual observations")
            centers[name] = sum(values, Decimal(0)) / Decimal(len(values))
        sampled: dict[str, list[tuple[Decimal, ...]]] = {name: [] for name in names}
        while len(sampled[names[0]]) < scenario.months:
            source_index, start = eligible_starts[int(rng.integers(len(eligible_starts)))]
            source = sources[source_index]
            for month_index in range(start, start + scenario.block_months):
                if len(sampled[names[0]]) >= scenario.months:
                    break
                for pattern_index, name in enumerate(names):
                    values = source[name][month_index]
                    if scenario.imbalance == "stressed" and values:
                        target = (
                            len(values) * 3
                            if len(sampled[name]) % 3 == 0
                            else max(1, len(values) // 2)
                        )
                        values = tuple(values[index % len(values)] for index in range(target))
                    shift = (
                        scenario.delta_mme
                        if scenario.null_configuration[pattern_index] == "d"
                        else Decimal(0)
                    )
                    sampled[name].append(tuple(value - centers[name] + shift for value in values))
        return MappingProxyType({name: tuple(months) for name, months in sampled.items()})
    if calibration is not None:
        raise ValueError("generic synthetic scenario cannot consume calibration observations")
    block_count = math.ceil(scenario.months / scenario.block_months)
    common = np.repeat(rng.normal(size=block_count), scenario.block_months)[: scenario.months]
    results: dict[str, tuple[tuple[Decimal, ...], ...]] = {}
    for pattern_index, name in enumerate(names):
        months: list[tuple[Decimal, ...]] = []
        for month_index in range(scenario.months):
            count = scenario.observations_per_month
            if scenario.imbalance == "stressed":
                count = max(1, count // 2) if month_index % 3 else count * 3
            drawn_values: list[Decimal] = []
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
                drawn_values.append(Decimal(str(float(value))))
            months.append(tuple(drawn_values))
        results[name] = tuple(months)
    return MappingProxyType(results)


def run_synthetic_pilot(
    scenario: SyntheticScenario,
    *,
    outer_runs: int = 20_000,
    inner_draws: int = 9_999,
    seed: int,
    diagnostic: bool = False,
    calibration: CalibratedResidualFrame | None = None,
    candidate: InferenceCandidate = ENTRY_MONTH_WCR_S,
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
    input_digest = hashlib.sha256()
    for index in range(outer_runs):
        months = _synthetic_months(scenario, rng, calibration=calibration)
        input_digest.update(
            json.dumps(
                [[[str(value) for value in month] for month in months[name]] for name in names],
                separators=(",", ":"),
            ).encode("ascii")
        )
        weight_array = np.where(
            rng.integers(0, 2, size=(inner_draws, scenario.months)) == 0, -1, 1
        ).astype(np.int8)
        input_digest.update(weight_array.tobytes())
        weights = weight_array.tolist()
        confidence_rejections = tuple(
            scenario.null_configuration[pattern_index] == "0"
            and wcr_s_pvalue(months[name], weights=weights, draws=inner_draws, candidate=candidate)
            < Decimal("0.025")
            for pattern_index, name in enumerate(names)
        )
        family = romano_wolf_stepdown(
            months, weights=weights, draws=inner_draws, candidate=candidate
        )
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
        candidate,
        input_digest.hexdigest(),
    )


def run_candidate_pilots(
    scenario: SyntheticScenario,
    *,
    candidates: Sequence[InferenceCandidate],
    outer_runs: int = 20_000,
    inner_draws: int = 9_999,
    seed: int,
    diagnostic: bool = False,
    calibration: CalibratedResidualFrame | None = None,
) -> Mapping[InferenceCandidate, SyntheticPilotResult]:
    """Evaluate every frozen candidate on identical generated outer inputs."""
    if not candidates or len(set(candidates)) != len(candidates):
        raise ValueError("pilot candidates must be unique and nonempty")
    pilots = {
        candidate: run_synthetic_pilot(
            scenario,
            outer_runs=outer_runs,
            inner_draws=inner_draws,
            seed=seed,
            diagnostic=diagnostic,
            calibration=calibration,
            candidate=candidate,
        )
        for candidate in candidates
    }
    if len({pilot.shared_inputs_sha256 for pilot in pilots.values()}) != 1:
        raise ValueError("candidate pilot inputs must be byte-identical")
    return MappingProxyType(pilots)


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
        if self.n_required < 100 or self.g_required < 6:
            raise ValueError("power requirement needs at least 100 trades and six clusters")
        if self.minimum_detectable_effect <= 0 or self.prospective_power < Decimal("0.8"):
            raise ValueError("power requirement needs a positive effect and at least 80% power")


@dataclass(frozen=True, slots=True)
class CandidateAuditEvidence:
    candidate: InferenceCandidate
    size_audits: tuple[ScenarioSizeAudit, ...]
    power_trials: tuple[PowerScenario, ...]
    cluster_count: int
    shared_inputs_sha256: str


@dataclass(frozen=True, slots=True)
class MethodSelectionResult:
    status: MethodStatus
    selected_candidate: InferenceCandidate | None
    projected_power: Decimal | None
    requirements: Mapping[str, PowerRequirement]
    candidate_audits: Mapping[InferenceCandidate, MethodAuditResult]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirements", MappingProxyType(dict(self.requirements)))
        object.__setattr__(self, "candidate_audits", MappingProxyType(dict(self.candidate_audits)))


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


def select_method(
    protocol: MethodAuditProtocol,
    evidence: Sequence[CandidateAuditEvidence],
    *,
    delta_mme: Decimal,
) -> MethodSelectionResult:
    """Select only after every frozen candidate has paired, complete audit evidence."""
    if not delta_mme.is_finite() or delta_mme <= 0:
        raise ValueError("externally declared delta_MME must be positive")
    if not protocol.mandatory_power_scenarios or len(
        set(protocol.mandatory_power_scenarios)
    ) != len(protocol.mandatory_power_scenarios):
        raise ValueError("mandatory power scenarios must be unique and nonempty")
    if len(evidence) != len(protocol.candidate_methods) or {
        item.candidate for item in evidence
    } != set(protocol.candidate_methods):
        raise ValueError("every frozen candidate needs one audit")
    fingerprints = {item.shared_inputs_sha256 for item in evidence}
    if len(fingerprints) != 1 or any(
        len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
        for digest in fingerprints
    ):
        raise ValueError("candidates need identical hashed outer draws and weight matrices")

    decisions: dict[InferenceCandidate, MethodAuditResult] = {}
    projected: dict[InferenceCandidate, Decimal] = {}
    projection_keys: set[tuple[str, str]] | None = None
    by_candidate = {item.candidate: item for item in evidence}
    for candidate in protocol.candidate_methods:
        item = by_candidate[candidate]
        decisions[candidate] = audit_method_size(protocol, item.size_audits)
        if item.cluster_count < 1:
            raise ValueError("candidate cluster count must be positive")
        trials = [
            trial
            for trial in item.power_trials
            if trial.sample_size == protocol.projection_sample_size
        ]
        keys = {(trial.scenario_id, trial.pattern) for trial in trials}
        if len(keys) != len(trials) or not keys:
            raise ValueError("power projection needs one trial per scenario and pattern")
        patterns = {pattern for _, pattern in keys}
        if patterns != {"ema_pullback", "bull_flag", "double_bottom"}:
            raise ValueError("power projection needs all three strategy patterns")
        if item.cluster_count != min(trial.nonempty_clusters for trial in trials):
            raise ValueError("candidate cluster count must match projected power evidence")
        if any(
            {scenario for scenario, trial_pattern in keys if trial_pattern == pattern}
            != set(protocol.mandatory_power_scenarios)
            for pattern in patterns
        ):
            raise ValueError("power projection needs every mandatory scenario")
        if projection_keys is None:
            projection_keys = keys
        elif keys != projection_keys:
            raise ValueError("candidates need identical projected power cells")
        if any(
            trial.effect != delta_mme
            or trial.trials <= 0
            or not 0 <= trial.rejections <= trial.trials
            for trial in trials
        ):
            raise ValueError("power projection conflicts with the declared effect or trial count")
        projected[candidate] = min(
            Decimal(trial.rejections) / Decimal(trial.trials) for trial in trials
        )

    eligible_candidates = tuple(
        candidate
        for candidate in protocol.candidate_methods
        if Decimal(1) / (Decimal(2) ** by_candidate[candidate].cluster_count) <= Decimal("0.025")
    )
    if any(
        decisions[candidate].status is MethodStatus.METHOD_AUDIT_PENDING
        for candidate in eligible_candidates
    ):
        return MethodSelectionResult(MethodStatus.METHOD_AUDIT_PENDING, None, None, {}, decisions)
    qualified = [
        candidate
        for candidate in eligible_candidates
        if decisions[candidate].status is MethodStatus.METHOD_ADEQUATE
    ]
    if not qualified:
        return MethodSelectionResult(MethodStatus.METHOD_INADEQUATE, None, None, {}, decisions)
    chosen = max(
        qualified,
        key=lambda candidate: (
            projected[candidate],
            by_candidate[candidate].cluster_count,
            -protocol.candidate_methods.index(candidate),
        ),
    )
    try:
        requirements = audit_power(
            by_candidate[chosen].power_trials,
            mandatory_scenarios=protocol.mandatory_power_scenarios,
            delta_mme=delta_mme,
        )
    except ValueError as exc:
        if "80% power was not demonstrated" not in str(exc):
            raise
        return MethodSelectionResult(MethodStatus.METHOD_INADEQUATE, None, None, {}, decisions)
    return MethodSelectionResult(
        MethodStatus.METHOD_ADEQUATE,
        chosen,
        projected[chosen],
        requirements,
        decisions,
    )


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


def _predictive_lower(
    counts: Sequence[int], *, duration: int = 36, simulations: int = 9999, seed: int = 0
) -> Decimal:
    """One-sided 90% lower predictive holdout rate under moving-block counts.

    This predicts a holdout-average rate, never a single future observation.
    The planner uses its joint partition-preserving paths for each horizon.
    """
    if not counts or duration <= 0 or simulations <= 0 or any(value < 0 for value in counts):
        raise ValueError("predictive rate requires nonnegative counts and positive horizon/draws")
    frame = tuple((value,) for value in counts)
    rng = random.Random(seed)  # nosec B311 # Reproducible count simulation, not security.
    lowers = []
    for block in (3, 6, 12):
        totals = sorted(
            sum(row[0] for row in _sample_path(frame, frame, block, rng)[:duration])
            for _ in range(simulations)
        )
        lowers.append(Decimal(totals[math.floor((simulations - 1) * 0.1)]) / Decimal(duration))
    return min(lowers)


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


def _grouped_cluster_prefix(monthly: np.ndarray, block_months: int) -> np.ndarray:
    """Count nonempty aligned inference clusters at each eligible month horizon."""
    out = np.zeros_like(monthly)
    completed = np.zeros((monthly.shape[0], monthly.shape[2]), dtype=np.int64)
    current = np.zeros_like(completed)
    for month in range(monthly.shape[1]):
        if month % block_months == 0:
            current = np.zeros_like(completed)
        current += monthly[:, month, :]
        out[:, month, :] = completed + (current > 0)
        if (month + 1) % block_months == 0:
            completed += current > 0
    return out


def _grouped_cluster_count(monthly: np.ndarray, block_months: int) -> np.ndarray:
    grouped = np.add.reduceat(monthly, np.arange(0, monthly.shape[1], block_months), axis=1)
    return np.asarray(np.count_nonzero(grouped, axis=1), dtype=np.int64)


def plan_holdout_duration(
    *,
    development: Mapping[str, Sequence[int]],
    validation: Mapping[str, Sequence[int]],
    requirements: Mapping[str, PowerRequirement],
    available_months: int,
    development_validation_expectancy: Mapping[str, Decimal] | None = None,
    selected_candidate: InferenceCandidate = ENTRY_MONTH_WCR_S,
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
    historical_rates: dict[str, dict[str, Decimal]] = {}
    for index, name in enumerate(patterns):
        development_counts = [row[index] for row in development_frame]
        validation_counts = [row[index] for row in validation_frame]
        rolling = min(
            Decimal(sum(development_counts[start : start + 36])) / Decimal(36)
            for start in range(rolling_count)
        )
        validation_rate = Decimal(sum(validation_counts)) / Decimal(len(validation_counts))
        historical_rates[name] = {
            "rolling_36_development": rolling,
            "full_validation": validation_rate,
        }
        baseline_rates[name] = Decimal(sum(development_counts) + sum(validation_counts)) / Decimal(
            len(development_counts) + len(validation_counts)
        )

    baseline_paths: dict[int, list[np.ndarray]] = {3: [], 6: [], 12: []}
    rng = random.Random(seed)  # nosec B311 # Reproducible count simulation, not security.
    thinning_rng = np.random.Generator(np.random.PCG64(seed))
    for block_size in (3, 6, 12):
        for _ in range(simulations):
            sampled = np.asarray(
                _sample_path(development_frame, validation_frame, block_size, rng), dtype=np.int64
            )
            baseline_paths[block_size].append(np.cumsum(sampled, axis=0))

    baseline_arrays = {block: np.asarray(paths) for block, paths in baseline_paths.items()}
    monthly_paths = {
        block: np.diff(
            paths, axis=1, prepend=np.zeros((simulations, 1, len(patterns)), dtype=np.int64)
        )
        for block, paths in baseline_arrays.items()
    }
    cluster_arrays = {
        block: _grouped_cluster_prefix(paths, selected_candidate.block_months)
        for block, paths in monthly_paths.items()
    }
    required: int | None = None
    chosen_probabilities: dict[str, Decimal] = {}
    required_n = np.asarray([requirements[name].n_required for name in patterns])
    required_g = np.asarray([requirements[name].g_required for name in patterns])
    for duration in range(36, 121):
        for index, name in enumerate(patterns):
            predictive = min(
                Decimal(int(np.quantile(paths[:, duration - 1, index], 0.1, method="lower")))
                / Decimal(duration)
                for paths in baseline_arrays.values()
            )
            options = {**historical_rates[name], "predictive_90_lower": predictive}
            rate_sources[name], stress_rates[name] = min(
                options.items(), key=lambda item: (item[1], item[0])
            )
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
        baseline_probabilities = []
        stressed_probabilities = []
        for block_size in (3, 6, 12):
            totals = baseline_arrays[block_size][:, duration - 1, :]
            clusters = cluster_arrays[block_size][:, duration - 1, :]
            baseline_probabilities.append(
                Decimal(
                    int(
                        np.count_nonzero(
                            np.all(totals >= required_n, axis=1)
                            & np.all(clusters >= required_g, axis=1)
                        )
                    )
                )
                / Decimal(simulations)
            )
            stressed = thinning_rng.binomial(monthly_paths[block_size][:, :duration, :], ratios)
            successes = np.all(np.sum(stressed, axis=1) >= required_n, axis=1) & np.all(
                _grouped_cluster_count(stressed, selected_candidate.block_months) >= required_g,
                axis=1,
            )
            stressed_probabilities.append(
                Decimal(int(np.count_nonzero(successes))) / Decimal(simulations)
            )
        chosen_probabilities = {
            "baseline": min(baseline_probabilities),
            "stressed": min(stressed_probabilities),
        }
        if chosen_probabilities["baseline"] >= Decimal("0.9") and chosen_probabilities[
            "stressed"
        ] >= Decimal("0.8"):
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
