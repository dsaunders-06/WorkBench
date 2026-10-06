"""The generic pilot runs the complete agreed dependence matrix."""

from __future__ import annotations

from scripts.research import run_phase2c_generic_method_pilot as pilot


def test_generic_pilot_covers_every_phase_persistence_and_partial_null() -> None:
    cells = pilot.build_cells()

    assert len(cells) == 56
    assert {(cell.block_months, cell.null_configuration, cell.shock_phase) for cell in cells} == {
        (months, null, phase)
        for months in (1, 2, 3, 4)
        for null in ("000", "d00", "0d0", "00d", "dd0", "d0d", "0dd")
        for phase in ("aligned", "random")
    }
    assert len({cell.scenario_id for cell in cells}) == 56
    assert tuple((candidate.method, candidate.block_months) for candidate in pilot.CANDIDATES) == (
        ("entry_month", 1),
        ("quarter", 3),
        ("aligned_block", 4),
    )


def test_generic_pilot_seeds_are_stable_and_cell_specific() -> None:
    first, second = pilot.build_cells()[:2]

    assert pilot.seed_for(first) == pilot.seed_for(first)
    assert pilot.seed_for(first) != pilot.seed_for(second)


def test_amended_matrix_separates_calibrated_dependence_from_constant_shock_sensitivity() -> None:
    mandatory, sensitivity = pilot.build_amended_cells()

    assert len(mandatory) == 21
    assert {
        (cell.family, cell.mean_autocorrelation, cell.volatility_autocorrelation)
        for cell in mandatory
    } == {
        ("volatility_regime", 0.0, 0.4524),
        ("ar1_mean", -0.0874, 0.0),
        ("ar1_mean", 0.25, 0.0),
    }
    assert {cell.dependence_stress for cell in mandatory if cell.family == "ar1_mean"} == {
        False,
        True,
    }
    assert {cell.null_configuration for cell in mandatory} == set(pilot.NULLS)
    assert len(sensitivity) == 56
    assert {cell.block_months for cell in sensitivity} == {1, 2, 3, 4}
    assert {cell.shock_phase for cell in sensitivity} == {"aligned", "random"}
    assert all(cell.family == "gaussian" for cell in sensitivity)
    assert len({cell.scenario_id for cell in (*mandatory, *sensitivity)}) == 77


def test_amended_pilot_keeps_approved_seed_domains_distinct() -> None:
    first = pilot.build_amended_cells()[0][0]

    assert pilot.BASE_SEED == 20261005
    assert pilot.OUTER_NULL_SEED == 845317
    assert pilot.INNER_SIGNS_SEED == 845318
    assert pilot.POWER_SEED == 845319
    assert pilot.seed_for(first) != pilot.power_seed_for(first)
