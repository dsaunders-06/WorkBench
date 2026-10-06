"""The added seven-cell stress cannot run before the current pilot completes."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


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
