"""The added seven-cell stress cannot run before the current pilot completes."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_combined_runner_imports_its_own_checkout_before_environment_qat(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    foreign = tmp_path / "foreign"
    package = foreign / "qat" / "domain" / "backtester"
    package.mkdir(parents=True)
    for parent in (foreign / "qat", foreign / "qat" / "domain", package):
        (parent / "__init__.py").write_text("", encoding="ascii")
    (package / "swing_method_audit.py").write_text(
        'raise RuntimeError("foreign QAT module loaded")\n', encoding="ascii"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/research/run_phase2d_combined_stress_pilot.py"),
            "--help",
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(foreign)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_combined_stress_waits_for_complete_existing_pilot(tmp_path: Path) -> None:
    combined = importlib.import_module("scripts.research.run_phase2d_combined_stress_pilot")
    report = tmp_path / "report.json"
    with pytest.raises(ValueError, match="complete prior pilot"):
        combined.require_prior_pilot_complete(report)
    report.write_text(
        json.dumps(
            {"phase": "pre-declaration generic pilot", "matrix_cells": 77, "completed_cells": 76}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="complete prior pilot"):
        combined.require_prior_pilot_complete(report)
    report.write_text(
        json.dumps(
            {
                "phase": "pre-declaration generic pilot",
                "matrix_cells": 77,
                "completed_cells": 77,
                "cells": [{} for _ in range(77)],
            }
        ),
        encoding="utf-8",
    )
    combined.require_prior_pilot_complete(report)
