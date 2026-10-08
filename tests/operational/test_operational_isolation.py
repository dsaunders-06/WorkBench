"""AST transitive isolation, exact tick exception, and runtime execution traps."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path

from support.source_corpus import source_files

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src"
BROKER_ALLOWLIST = frozenset({"qat.data.broker.ticks"})
FORBIDDEN = (
    "qat.ui",
    "qat.presentation",
    "PySide6",
    "qasync",
    "qat.domain.oms",
    "qat.application",
    "qat.app",
    "qat.runtime",
    "qat.scheduler",
    "socket",
    "_socket",
    "ssl",
    "_ssl",
    "websockets",
    "httpcore",
    "ftplib",
    "smtplib",
    "asyncio",
    "urllib",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "ib_async",
    "alpaca",
    "yfinance",
    "anthropic",
    "subprocess",
)


def module_path(name):
    p = SOURCE.joinpath(*name.split("."))
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    if (p / "__init__.py").is_file():
        return p / "__init__.py"
    return None


def imported_modules(tree, module):
    found = set()

    # Include every static import, even typing-only and conditional imports.
    # The exact broker exception cannot be widened by placing an import in a guard.
    class Visitor(ast.NodeVisitor):
        def visit_Import(self, node):
            found.update(a.name for a in node.names)

        def visit_ImportFrom(self, node):
            if node.level:
                package = (
                    module
                    if module_path(module).name == "__init__.py"
                    else module.rpartition(".")[0]
                )
                name = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            else:
                name = node.module or ""
            if name:
                found.add(name)
            for a in node.names:
                candidate = name + "." + a.name
                if module_path(candidate):
                    found.add(candidate)

    Visitor().visit(tree)
    return found


def violations(entry, overrides=None):
    overrides = overrides or {}
    pending = [entry]
    seen = set()
    bad = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        path = module_path(name)
        if path is None:
            continue
        tree = ast.parse(overrides.get(name, path.read_text(encoding="utf-8")))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id in ("__import__", "eval", "exec"))
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            ):
                bad.add(name + ":dynamic_import")
        for imported in imported_modules(tree, name):
            if imported.startswith("qat.data.broker") and imported not in BROKER_ALLOWLIST:
                bad.add(imported)
            if imported == "qat.operational" or imported.startswith("qat.operational."):
                if entry.startswith("qat.domain."):
                    bad.add(imported)
            if any(imported == p or imported.startswith(p + ".") for p in FORBIDDEN):
                bad.add(imported)
            if imported.startswith("qat."):
                pending.append(imported)
            # Package initializers are executed even for a leaf import.
            parts = imported.split(".")
            for i in range(1, len(parts)):
                parent = ".".join(parts[:i])
                p = module_path(parent)
                if p and p.name == "__init__.py":
                    pending.append(parent)
    return bad


def test_engine_transitive_isolation():
    assert violations("qat.domain.strategies.authoritative_swing.engine") == set()


def test_adapter_transitive_isolation():
    assert violations("qat.operational.adapter") == set()


def test_tick_exception_is_exact_and_rejects_new_broker_dependency():
    assert BROKER_ALLOWLIST == frozenset({"qat.data.broker.ticks"})
    engine = "qat.domain.strategies.authoritative_swing.engine"
    source = (
        module_path(engine).read_text() + "\nfrom qat.data.broker.ib_adapter import IBAdapter\n"
    )
    assert "qat.data.broker.ib_adapter" in violations(engine, {engine: source})
    ticks = "qat.data.broker.ticks"
    source = module_path(ticks).read_text() + "\nfrom qat.data.broker.adapter import Order\n"
    assert "qat.data.broker.adapter" in violations(engine, {ticks: source})


def test_ticks_has_only_stdlib_and_calendar_imports():
    imports = imported_modules(
        ast.parse(module_path("qat.data.broker.ticks").read_text()), "qat.data.broker.ticks"
    )
    assert all(
        name == "qat.domain.market_calendar" or name.split(".")[0] in sys.stdlib_module_names
        for name in imports
    )


def test_broker_package_initializer_has_no_imports():
    tree = ast.parse(module_path("qat.data.broker").read_text())
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom, ast.Call)) for n in ast.walk(tree))


def test_static_guard_catches_network_and_dynamic_imports():
    engine = "qat.domain.strategies.authoritative_swing.engine"
    source = module_path(engine).read_text()
    assert "socket" in violations(engine, {engine: source + "\nimport socket\n"})
    assert engine + ":dynamic_import" in violations(
        engine, {engine: source + "\n__import__('requests')\n"}
    )


def test_runtime_adapter_never_calls_any_oms_broker_or_network_entry(tmp_path, monkeypatch):
    from test_operational_adapter import NOW, prepared

    a, snapshot, *_ = prepared(tmp_path, qualified=True)

    def denied(*args, **kwargs):
        raise AssertionError("forbidden execution or network entry")

    # Every function/method defined in the repository's OMS and broker modules
    # is trapped. Tick arithmetic is the sole exact exception.
    trapped = []
    for directory in ("qat/domain/oms", "qat/data/broker"):
        for path in source_files(SOURCE / directory, minimum=5):
            if path.name in ("__init__.py", "ticks.py"):
                continue
            name = ".".join(path.relative_to(SOURCE).with_suffix("").parts)
            module = importlib.import_module(name)
            for key, value in tuple(vars(module).items()):
                if getattr(value, "__module__", None) != name:
                    continue
                if isinstance(value, type):
                    for method, member in tuple(vars(value).items()):
                        if callable(member) or isinstance(member, (staticmethod, classmethod)):
                            monkeypatch.setattr(value, method, denied)
                            trapped.append(name + "." + key + "." + method)
                elif callable(value):
                    monkeypatch.setattr(module, key, denied)
                    trapped.append(name + "." + key)
    import http.client
    import socket
    import urllib.request

    import ib_async
    import requests

    for obj, names in (
        (socket.socket, ("connect", "connect_ex", "sendto")),
        (socket, ("create_connection", "getaddrinfo")),
        (urllib.request, ("urlopen",)),
        (http.client.HTTPConnection, ("connect", "request")),
        (requests.Session, ("request", "send")),
    ):
        for name in names:
            monkeypatch.setattr(obj, name, denied)
    for cls in (ib_async.IB, ib_async.Client):
        for name, value in tuple(vars(cls).items()):
            if callable(value):
                monkeypatch.setattr(cls, name, denied)
    result = a.run(snapshot, now=NOW)
    assert len(result.candidates) == 1
    assert trapped


def test_static_guard_rejects_presentation_and_adapter_back_import():
    engine = "qat.domain.strategies.authoritative_swing.engine"
    original = module_path(engine).read_text()
    assert "qat.presentation.theme" in violations(
        engine, {engine: original + "\nfrom qat.presentation.theme import apply_theme\n"}
    )
    assert "qat.operational.adapter" in violations(
        engine, {engine: original + "\nfrom qat.operational.adapter import OperationalAdapter\n"}
    )
    adapter = "qat.operational.adapter"
    original = module_path(adapter).read_text()
    assert "qat.presentation.theme" in violations(
        adapter, {adapter: original + "\nfrom qat.presentation.theme import apply_theme\n"}
    )


def test_typing_only_broker_import_cannot_expand_the_allowlist():
    engine = "qat.domain.strategies.authoritative_swing.engine"
    source = module_path(engine).read_text() + """\nfrom typing import TYPE_CHECKING
if TYPE_CHECKING:
    from qat.data.broker.ib_adapter import IBAdapter
"""
    assert "qat.data.broker.ib_adapter" in violations(engine, {engine: source})
