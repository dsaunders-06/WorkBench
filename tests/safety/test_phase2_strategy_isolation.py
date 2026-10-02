"""The Phase 2 research engine cannot transitively reach execution interfaces."""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from support.source_corpus import source_files

from qat.domain.backtester.swing_fills import AmbiguityPolicy
from qat.domain.backtester.swing_replay import (
    AuthoritativeSwingReplay,
    ReplayCalendarRow,
    SessionKind,
)
from qat.domain.backtester.swing_results import RunStatus
from qat.domain.oms.oms import OMS
from qat.domain.strategies.authoritative_swing.sizing import (
    ExactCostProfile,
    LiquidityProfile,
)

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src"
PACKAGE = SOURCE / "qat" / "domain" / "strategies" / "authoritative_swing"


class _RuntimeImports(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.names.add(node.module)


def _module_path(name: str) -> Path | None:
    path = SOURCE.joinpath(*name.split("."))
    module = path.with_suffix(".py")
    if module.exists():
        return module
    package = path / "__init__.py"
    return package if package.exists() else None


def _imports(path: Path) -> set[str]:
    visitor = _RuntimeImports()
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return visitor.names


def _transitive_imports() -> set[str]:
    pending = [
        f"qat.domain.strategies.authoritative_swing.{path.stem}"
        for path in source_files(PACKAGE, minimum=10)
        if path.stem != "__init__"
    ]
    pending.append("qat.domain.backtester.swing_replay")
    seen: set[str] = set()
    all_imports: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        path = _module_path(name)
        if path is None:
            continue
        imports = _imports(path)
        all_imports.update(imports)
        pending.extend(item for item in imports if item.startswith("qat."))
    return all_imports


def test_phase2_transitive_import_graph_has_no_execution_dependencies() -> None:
    forbidden = (
        "qat.domain.oms",
        "qat.data.broker.adapter",
        "qat.domain.autonomy",
        "qat.presentation",
    )
    imported = _transitive_imports()

    assert not any(
        name == root or name.startswith(root + ".")
        for name in imported
        for root in forbidden
    )


def test_phase2_transitive_import_graph_has_no_network_or_process_interfaces() -> None:
    forbidden = ("requests", "httpx", "urllib", "socket", "subprocess", "ib_async", "alpaca")
    imported = _transitive_imports()

    assert not any(
        name == root or name.startswith(root + ".")
        for name in imported
        for root in forbidden
    )


def test_complete_phase2_replay_never_invokes_oms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("Phase 2 replay reached the production OMS")

    for method in ("submit_order", "submit_exit_order", "sign_off"):
        monkeypatch.setattr(OMS, method, forbidden)

    session = date(2026, 1, 5)
    replay = AuthoritativeSwingReplay(
        calendar_rows=(
            ReplayCalendarRow(
                session,
                SessionKind.FULL,
                "fixture-calendar",
                "normal session",
                "calendar-2026-01-05",
                True,
            ),
        ),
        bars={},
        membership={session: frozenset()},
        corporate_actions=(),
        benchmark=(),
        engine=object(),  # type: ignore[arg-type]
        starting_equity=Decimal("10000"),
        costs=ExactCostProfile(
            "fixture-v1", "fixture", Decimal(0), Decimal(0), "AUD", False, Decimal(0)
        ),
        liquidity=LiquidityProfile("fixture-v1", Decimal(1), Decimal(0), Decimal(0)),
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE,
    )

    assert replay.run().status is RunStatus.VALID
