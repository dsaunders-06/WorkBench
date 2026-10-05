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
