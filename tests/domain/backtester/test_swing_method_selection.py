"""Candidate selection uses paired synthetic evidence and frozen size gates."""

from __future__ import annotations

from decimal import Decimal

import pytest

from qat.domain.backtester import swing_method_audit as audit
from qat.domain.backtester.swing_statistics import (
    ENTRY_MONTH_WCR_S,
    QUARTER_WCR_S,
)


def _protocol() -> audit.MethodAuditProtocol:
    return audit.MethodAuditProtocol(
        mandatory_scenarios=("complete:confidence", "complete:family"),
        mandatory_power_scenarios=("power",),
        candidate_methods=(ENTRY_MONTH_WCR_S, QUARTER_WCR_S),
        projection_sample_size=100,
        declaration_sha256="a" * 64,
        scenario_matrix_sha256="b" * 64,
        pilot_sha256="c" * 64,
    )


def _evidence(
    candidate: object,
    *,
    confidence_false: int = 100,
    family_false: int = 100,
    projected_rejections: int = 700,
    required_n: int = 120,
    clusters: int = 12,
    input_hash: str = "e" * 64,
    patterns: tuple[str, ...] = ("ema_pullback", "bull_flag", "double_bottom"),
) -> audit.CandidateAuditEvidence:
    return audit.CandidateAuditEvidence(
        candidate=candidate,
        size_audits=(
            audit.ScenarioSizeAudit(
                "complete:confidence", "confidence", 20_000, confidence_false, "d" * 64
            ),
            audit.ScenarioSizeAudit("complete:family", "family", 20_000, family_false, "d" * 64),
        ),
        power_trials=tuple(
            trial
            for pattern in patterns
            for trial in (
                audit.PowerScenario(
                    "power", pattern, 100, clusters, Decimal("0.2"), 1000, projected_rejections
                ),
                audit.PowerScenario(
                    "power", pattern, required_n, clusters, Decimal("0.2"), 1000, 850
                ),
            )
        ),
        cluster_count=clusters,
        shared_inputs_sha256=input_hash,
    )


def test_only_candidates_passing_every_size_cell_can_be_selected() -> None:
    result = audit.select_method(
        _protocol(),
        (
            _evidence(ENTRY_MONTH_WCR_S, projected_rejections=700, clusters=36),
            _evidence(QUARTER_WCR_S, confidence_false=1000, projected_rejections=900),
        ),
        delta_mme=Decimal("0.2"),
    )

    assert result.status is audit.MethodStatus.METHOD_ADEQUATE
    assert result.selected_candidate == ENTRY_MONTH_WCR_S
    assert result.requirements["ema_pullback"].n_required == 120
    assert result.requirements["ema_pullback"].g_required == 36


def test_highest_projected_power_wins_then_larger_cluster_count_breaks_tie() -> None:
    high_power = audit.select_method(
        _protocol(),
        (
            _evidence(ENTRY_MONTH_WCR_S, projected_rejections=700, clusters=36),
            _evidence(QUARTER_WCR_S, projected_rejections=750, clusters=12),
        ),
        delta_mme=Decimal("0.2"),
    )
    tied = audit.select_method(
        _protocol(),
        (
            _evidence(ENTRY_MONTH_WCR_S, projected_rejections=750, clusters=36),
            _evidence(QUARTER_WCR_S, projected_rejections=750, clusters=12),
        ),
        delta_mme=Decimal("0.2"),
    )

    assert high_power.selected_candidate == QUARTER_WCR_S
    assert high_power.projected_power == Decimal("0.75")
    assert tied.selected_candidate == ENTRY_MONTH_WCR_S


def test_no_size_qualified_candidate_is_method_inadequate() -> None:
    result = audit.select_method(
        _protocol(),
        (
            _evidence(ENTRY_MONTH_WCR_S, confidence_false=1000, clusters=36),
            _evidence(QUARTER_WCR_S, family_false=2000, clusters=12),
        ),
        delta_mme=Decimal("0.2"),
    )

    assert result.status is audit.MethodStatus.METHOD_INADEQUATE
    assert result.selected_candidate is None
    assert not result.requirements


def test_selection_refuses_unpaired_inputs_and_missing_candidates() -> None:
    with pytest.raises(ValueError, match="identical"):
        audit.select_method(
            _protocol(),
            (
                _evidence(ENTRY_MONTH_WCR_S, clusters=36),
                _evidence(QUARTER_WCR_S, input_hash="f" * 64),
            ),
            delta_mme=Decimal("0.2"),
        )
    with pytest.raises(ValueError, match="candidate"):
        audit.select_method(
            _protocol(), (_evidence(ENTRY_MONTH_WCR_S, clusters=36),), delta_mme=Decimal("0.2")
        )


def test_duration_planner_counts_clusters_under_the_selected_method() -> None:
    names = ("ema", "flag", "bottom")
    result = audit.plan_holdout_duration(
        development={name: (4,) * 60 for name in names},
        validation={name: (4,) * 24 for name in names},
        requirements={
            name: audit.PowerRequirement(name, 100, 36, Decimal("0.2"), Decimal("0.8"))
            for name in names
        },
        selected_candidate=QUARTER_WCR_S,
        available_months=120,
        simulations=10,
        seed=17,
    )

    assert result.required_months == 106


def test_power_requirement_cannot_claim_an_ineligible_five_cluster_design() -> None:
    with pytest.raises(ValueError, match="six"):
        audit.PowerRequirement("ema", 100, 5, Decimal("0.2"), Decimal("0.8"))


def test_selection_requires_every_strategy_pattern_and_a_supported_cluster_count() -> None:
    with pytest.raises(ValueError, match="three strategy patterns"):
        audit.select_method(
            _protocol(),
            (
                _evidence(ENTRY_MONTH_WCR_S, clusters=36, patterns=("ema_pullback",)),
                _evidence(QUARTER_WCR_S, clusters=12, patterns=("ema_pullback",)),
            ),
            delta_mme=Decimal("0.2"),
        )

    unsupported = _evidence(ENTRY_MONTH_WCR_S, clusters=36)
    with pytest.raises(ValueError, match="cluster count"):
        audit.select_method(
            _protocol(),
            (
                audit.CandidateAuditEvidence(
                    unsupported.candidate,
                    unsupported.size_audits,
                    unsupported.power_trials,
                    37,
                    unsupported.shared_inputs_sha256,
                ),
                _evidence(QUARTER_WCR_S, clusters=12),
            ),
            delta_mme=Decimal("0.2"),
        )


def test_ineligible_candidate_does_not_delay_an_eligible_candidate() -> None:
    result = audit.select_method(
        _protocol(),
        (
            _evidence(ENTRY_MONTH_WCR_S, clusters=36),
            _evidence(QUARTER_WCR_S, clusters=5, confidence_false=650),
        ),
        delta_mme=Decimal("0.2"),
    )

    assert result.status is audit.MethodStatus.METHOD_ADEQUATE
    assert result.selected_candidate == ENTRY_MONTH_WCR_S


def test_430_projection_freeze_requires_identical_complete_rankings_at_every_effect_and_size() -> (
    None
):
    effects = (Decimal("0.10"), Decimal("0.15"), Decimal("0.20"), Decimal("0.30"))
    points = {(n, effect) for n in (200, 430) for effect in effects}
    evidence = {
        point: {
            ENTRY_MONTH_WCR_S: {
                ("regime", name): Decimal("0.6")
                for name in ("ema_pullback", "bull_flag", "double_bottom")
            },
            QUARTER_WCR_S: {
                ("regime", name): Decimal("0.7")
                for name in ("ema_pullback", "bull_flag", "double_bottom")
            },
        }
        for point in points
    }

    stable = audit.rank_projection_sensitivity(
        evidence, clusters={ENTRY_MONTH_WCR_S: 36, QUARTER_WCR_S: 12}
    )
    assert stable.freeze_430
    assert all(
        ranking == (QUARTER_WCR_S, ENTRY_MONTH_WCR_S) for ranking in stable.rankings.values()
    )

    for key in evidence[(430, Decimal("0.30"))][ENTRY_MONTH_WCR_S]:
        evidence[(430, Decimal("0.30"))][ENTRY_MONTH_WCR_S][key] = Decimal("0.8")
    unstable = audit.rank_projection_sensitivity(
        evidence, clusters={ENTRY_MONTH_WCR_S: 36, QUARTER_WCR_S: 12}
    )
    assert not unstable.freeze_430
    assert unstable.rankings[(430, Decimal("0.30"))] == (ENTRY_MONTH_WCR_S, QUARTER_WCR_S)


def test_projection_ranking_refuses_missing_bull_flag_cell() -> None:
    evidence = {
        (n, effect): {ENTRY_MONTH_WCR_S: {("regime", "ema_pullback"): Decimal("0.6")}}
        for n in (200, 430)
        for effect in (Decimal("0.10"), Decimal("0.15"), Decimal("0.20"), Decimal("0.30"))
    }
    with pytest.raises(ValueError, match="all three strategy patterns"):
        audit.rank_projection_sensitivity(evidence, clusters={ENTRY_MONTH_WCR_S: 36})
