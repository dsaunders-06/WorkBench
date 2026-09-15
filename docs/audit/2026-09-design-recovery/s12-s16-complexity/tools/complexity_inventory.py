"""Audit, brief §12 and §16: what in src/qat the running app never reaches.

Read-only. Parses src/qat with ast; writes nothing; needs no data folder.

    python complexity_inventory.py <repo_root>

Sections:
  1. size: modules and lines, by package;
  2. modules the app cannot import: the import graph from qat.app, the only
     entry point of the packaged build (QuantAdvisoryTerminal.spec:16).
     src/qat has no dynamic imports (no importlib, no __import__), so a module
     outside this graph cannot run inside the app. It may still be used by
     scripts or tests, which are listed;
  3. Settings fields no code outside config.py reads by attribute name, with
     their indirect readers (a quoted name for getattr; a config.py property).
     A list to check, not a verdict;
  4. (printed before 3) how much of each module is prose: '#' comments and
     docstrings.

A module inside the graph can still be dead in part: this measures imports,
not calls.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path


def module_name(src: Path, path: Path) -> str:
    parts = list(path.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imports_of(tree: ast.AST, name: str, is_package: bool) -> set[str]:
    found: set[str] = set()
    package = name if is_package else name.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                stem = ".".join(base + ([node.module] if node.module else []))
            else:
                stem = node.module or ""
            found.add(stem)
            # "from qat.x import y" may name a submodule y.
            found.update(f"{stem}.{alias.name}" for alias in node.names)
    return found


def main(root: Path) -> None:
    src = root / "src"
    files = sorted((src / "qat").rglob("*.py"))
    modules: dict[str, Path] = {module_name(src, p): p for p in files}
    lines = {m: len(p.read_text(encoding="utf-8").splitlines()) for m, p in modules.items()}
    graph: dict[str, set[str]] = {}
    for m, p in modules.items():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        graph[m] = {i for i in imports_of(tree, m, p.name == "__init__.py") if i in modules}

    print("=== 1. SIZE ===")
    by_pkg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for m, n in lines.items():
        pkg = ".".join(m.split(".")[:3])
        by_pkg[pkg][0] += 1
        by_pkg[pkg][1] += n
    print(
        f"src/qat: {len(modules)} modules, {sum(lines.values()):,} physical lines "
        "(comments and blank lines included)"
    )
    for pkg, (count, n) in sorted(by_pkg.items(), key=lambda kv: -kv[1][1])[:25]:
        print(f"  {pkg:40s} {count:3d} modules {n:7,d} lines")
    print()

    # Importing a.b.c runs a/__init__ and a/b/__init__ too.
    reached: set[str] = set()
    todo = ["qat.app"]
    while todo:
        m = todo.pop()
        if m in reached:
            continue
        reached.add(m)
        parts = m.split(".")
        parents = [".".join(parts[:k]) for k in range(1, len(parts))]
        todo.extend(x for x in [*graph.get(m, ()), *parents] if x in modules)

    unreached = sorted(set(modules) - reached)
    print("=== 2. MODULES THE APP CANNOT IMPORT (graph from qat.app) ===")
    print(
        f"reached {len(reached)} of {len(modules)} modules; "
        f"unreached {len(unreached)}, {sum(lines[m] for m in unreached):,} lines"
    )
    users = _outside_users(root, unreached)
    for m in unreached:
        who = users.get(m, {})
        tag = (
            ", ".join(f"{k} {v}" for k, v in sorted(who.items())) or "no script or test imports it"
        )
        print(f"  {m:55s} {lines[m]:5d} lines  [{tag}]")
    print()

    section_prose(modules)

    print("=== 3. SETTINGS FIELDS WITH NO ATTRIBUTE READ OUTSIDE config.py ===")
    config = modules["qat.config"]
    fields = _settings_fields(config)
    corpus = "\n".join(
        p.read_text(encoding="utf-8") for m, p in modules.items() if m != "qat.config"
    )
    config_text = config.read_text(encoding="utf-8")
    unread = [f for f in fields if not re.search(rf"\.{re.escape(f)}\b", corpus)]
    print(f"Settings fields: {len(fields)}; with no '.field' read outside config.py: {len(unread)}")
    for f in unread:
        # The indirect readers: a quoted name (getattr) outside config.py, or a
        # config.py property that reads self.field.
        quoted = len(re.findall(rf"[\"']{re.escape(f)}[\"']", corpus))
        via_self = len(re.findall(rf"self\.{re.escape(f)}\b", config_text))
        print(f"  {f:35s} quoted outside config.py: {quoted}; self.{f} in config.py: {via_self}")


def section_prose(modules: dict[str, Path]) -> None:
    """How much of each module is prose: '#' comment lines plus docstring lines.

    The audit treats comments as claims (CE-018), so the amount of prose in the
    code is the amount of unverified narrative a reader meets beside it.
    """
    print("=== 4. PROSE IN THE CODE: '#' comment lines + docstring lines ===")
    rows = []
    for m, p in modules.items():
        text = p.read_text(encoding="utf-8")
        all_lines = text.splitlines()
        comment = {i for i, line in enumerate(all_lines, 1) if line.strip().startswith("#")}
        doc: set[int] = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    doc.update(range(body[0].lineno, (body[0].end_lineno or 0) + 1))
        code = sum(
            1
            for i, line in enumerate(all_lines, 1)
            if line.strip() and i not in comment and i not in doc
        )
        rows.append((m, len(all_lines), len(comment | doc), code))
    total, prose, code = (sum(r[k] for r in rows) for k in (1, 2, 3))
    print(f"all modules: {total:,} lines = prose {prose:,} ({prose / total:.0%}) + code {code:,}")
    print("the 12 modules with the most prose:")
    for m, n, pr, c in sorted(rows, key=lambda r: -r[2])[:12]:
        print(f"  {m:45s} {n:5d} lines, prose {pr:5d} ({pr / n:.0%}), code {c:5d}")
    print()


def _settings_fields(config: Path) -> list[str]:
    tree = ast.parse(config.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return [
                s.target.id
                for s in node.body
                if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
            ]
    return []


def _outside_users(root: Path, targets: list[str]) -> dict[str, dict[str, int]]:
    """How many scripts and test files import each unreached module."""
    found: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for kind, folder in (("scripts", root / "scripts"), ("tests", root / "tests")):
        for path in folder.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in targets:
                if re.search(rf"\b{re.escape(m)}\b", text):
                    found[m][kind] += 1
    return found


if __name__ == "__main__":
    main(Path(sys.argv[1]))
