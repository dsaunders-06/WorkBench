"""Production invariants must survive optimized Python compilation."""

import ast
from pathlib import Path


def test_phase2_production_invariants_are_explicit_exceptions() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "qat" / "domain"
    targets = (
        root / "backtester" / "swing_portfolio.py",
        root / "backtester" / "swing_replay.py",
        *(
            root / "strategies" / "authoritative_swing" / name
            for name in ("bull_flag.py", "double_bottom.py", "ema_pullback.py")
        ),
    )
    failures = [
        (str(path), node.lineno)
        for path in targets
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assert)
    ]
    assert failures == [], failures


def test_allocation_invariant_survives_optimized_python() -> None:
    import subprocess
    import sys

    code = (
        "from decimal import Decimal\n"
        "from types import SimpleNamespace\n"
        "from qat.domain.backtester.swing_portfolio import _allocation, PortfolioInvariantError\n"
        "decision=SimpleNamespace(entry_limit_raw=None, initial_stop_raw=Decimal(9))\n"
        "try:\n"
        " _allocation(decision, 2, Decimal(1), Decimal(100), None, None)\n"
        "except PortfolioInvariantError:\n"
        " pass\n"
        "else:\n"
        " raise RuntimeError('missing explicit allocation invariant')\n"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
