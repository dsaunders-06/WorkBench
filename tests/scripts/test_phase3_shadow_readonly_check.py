"""The no-authority shadow check cannot start outside its approved window."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_shadow_readonly_check.py"
spec = importlib.util.spec_from_file_location("phase3_shadow_readonly_check", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_readonly_check_requires_window_and_missing_authorities(tmp_path):
    session = date(2026, 10, 22)
    authorities = tmp_path / "missing-authorities"
    module.validate_window(
        session, datetime.fromisoformat("2026-10-22T17:30:00+11:00"), authorities
    )
    with pytest.raises(ValueError, match="17:30"):
        module.validate_window(
            session, datetime.fromisoformat("2026-10-22T17:29:59+11:00"), authorities
        )
    with pytest.raises(ValueError, match="17:30"):
        module.validate_window(
            session, datetime.fromisoformat("2026-10-22T20:00:00+11:00"), authorities
        )
    authorities.mkdir()
    (authorities / "actions.json").write_text("{}")
    with pytest.raises(ValueError, match="authorities appeared"):
        module.validate_window(
            session, datetime.fromisoformat("2026-10-22T17:30:00+11:00"), authorities
        )


def test_readonly_surface_refuses_every_broker_access():
    with pytest.raises(RuntimeError, match="cannot access place_order"):
        _ = module._NoTradingSurface().place_order
