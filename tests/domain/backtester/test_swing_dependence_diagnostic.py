"""Checks for the diagnostic-only comparison harness."""

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/research/diagnose_swing_dependence.py"


def test_matching_cluster_definitions_retain_identical_attempts():
    run_cell = runpy.run_path(str(SCRIPT))["run_cell"]
    for persistence, first, second in (
        (1, "month_wcr_s", "block_wild"),
        (3, "quarter_wcr_s", "block_wild"),
    ):
        left = run_cell((persistence, "d00", first, 4, 99, 104))
        right = run_cell((persistence, "d00", second, 4, 99, 104))
        assert left["attempts"] == right["attempts"]
        assert left["pilot_attempts_sha256"] == right["pilot_attempts_sha256"]
        assert left["retained_pvalues_sha256"] == right["retained_pvalues_sha256"]
        assert left["patterns"]["ema_pullback"]["role"] == "power"
        assert left["patterns"]["bull_flag"]["role"] == "size"
        assert len(left["attempts"]) == 4


def test_three_block_conservative_ties_preserve_discrete_sign_floor():
    run_cell = runpy.run_path(str(SCRIPT))["run_cell"]
    result = run_cell((12, "d00", "block_wild", 20, 999, 104))
    assert result["clusters"] == 3
    assert len(result["attempts"]) == 20
    # Every all-positive sign draw is retained as a tie, so p-values cannot
    # cross the 2.5% or 5% gates in this deterministic diagnostic fixture.
    assert all(float(value) >= 0.05 for row in result["attempts"] for value in row["confidence_p"])
    assert result["patterns"]["ema_pullback"]["confidence_0_025"]["rejections"] == 0
    assert result["family_false_positive"]["rejections"] == 0
