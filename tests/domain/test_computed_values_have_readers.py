"""A computed value with no reader is waste that looks like work (M80).

Six times this project has built a producer and left the consumer for later, or
for never:

| Computed | Read from |
|---|---|
| `shows_advanced()` | M45 → M63 |
| `theme.callout` | M45 → M72 |
| `is_synthetic` | M18 → M72 (the LLM had it from M40; the operator did not) |
| `refusals.rail_of` | M51 → M77 |
| the journal `reason` | always → M77 |
| the M37 diagnostics | M37 → M79 |

Every one was found by a human noticing. That is not a method, and "ask what
reads it" written in a handoff is a habit rather than a check - it works exactly
as long as somebody remembers to apply it.

**A `@property` is the sharpest case to test.** A stored field with no reader
may still be carrying data forward for something to pick up later; a computed
one is arithmetic performed for nobody. It also has a stable name to search for,
which a dict key or a CSV column does not.

So: every property on the record types below is read somewhere in `src/`, or is
listed in `_NO_READER_YET` with a reason. The allowlist is the point of the
test, not a hole in it - it converts "nobody noticed" into "somebody decided",
and the reason is what a later reader argues with.

**It finds one thing today, and that is the honest answer.** Three separate
hand-counts during this session put the number at three, then five - both
produced by grepping a few paths and trusting the result. The rule below is
narrower than either guess and is checked rather than remembered, which is the
whole difference between a habit and a guard.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from support.source_corpus import source_files

import qat

_SRC = Path(qat.__file__).parent

# The record types where this pattern has actually bitten. Deliberately not
# every module in the tree: a guard that flags two hundred things is a guard
# that gets an ever-growing allowlist and stops being read.
_WATCHED = (
    "domain/performance/trades.py",
    "data/fundamentals.py",
    "domain/evaluation/refusals.py",
    # M39: PendingAction computes symbol, ratio and ex_date.
    "domain/corporate_actions/detector.py",
)

# Computed, and read by nothing. Each needs a reason, and each is a standing
# invitation to either wire it up or delete it.
_NO_READER_YET = {
    "is_win": (
        "A per-trade boolean with no reader anywhere in src/. "
        "`PerformanceStats.win_rate` asks the same question of a whole set, "
        "which is the form every caller actually wants, and the CSV row does "
        "not carry it. Candidate for deletion at the September review - left "
        "in place for now because deleting a public property mid-trial is a "
        "change to the record's shape for no gain."
    ),
}


def _properties(path: Path) -> list[str]:
    """Every `@property` name defined in this module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "property":
                names.append(node.name)
    return names


def _is_read(name: str) -> bool:
    """Whether anything in `src/` reads this property.

    **Anywhere, including the module that defines it.** The first version of
    this rule demanded a reader OUTSIDE the defining module, and immediately
    flagged four values that are not waste at all: `gross_r_multiple` and
    `pnl_pct` are written into the `closed_trades.csv` row, and `refused` and
    `approval_rate` feed `RefusalSummary.headline()`, which every caller reads.
    A property consumed by its own module's public surface is being used.

    Too strict is the failure mode that matters here. A guard that flags things
    which are fine earns an allowlist of things which are fine, and an
    allowlist of things which are fine is not read - which is how M75's colour
    guard came to assert something untrue.

    Matched on `.name`, so the `def name(self)` that declares it cannot satisfy
    its own test.
    """
    pattern = re.compile(rf"\.{re.escape(name)}\b")
    # Item 20. `any()` over an empty corpus is False, so a scan root that had
    # moved would report EVERY watched property as unread - loudly, which is
    # the safe direction, but it would be read as a hundred real defects
    # rather than as one wrong path. `source_files` names the actual cause.
    return any(
        pattern.search(path.read_text(encoding="utf-8"))
        for path in source_files(_SRC, recurse=True, minimum=100)
    )


def _watched_properties() -> list[tuple[Path, str]]:
    return [(_SRC / module, name) for module in _WATCHED for name in _properties(_SRC / module)]


def test_there_are_properties_to_check():
    """A guard that silently checks nothing is worse than no guard - the lesson
    M78 had to learn about M75's version."""
    assert len(_watched_properties()) >= 12


@pytest.mark.parametrize(
    ("module", "name"),
    [(path.name, name) for path, name in _watched_properties()],
)
def test_every_computed_value_is_read_by_something(module, name):
    if name in _NO_READER_YET:
        pytest.skip(f"declared unread: {_NO_READER_YET[name]}")

    assert _is_read(name), (
        f"{module}.{name} is computed and nothing in src/ reads it. Wire it up, "
        f"delete it, or add it to _NO_READER_YET with a reason."
    )


def test_the_allowlist_does_not_outlive_its_entries():
    """An allowlist naming something that no longer exists is how a guard
    quietly stops covering what it claims to."""
    defined = {name for _path, name in _watched_properties()}

    assert set(_NO_READER_YET) <= defined


def test_every_declared_exception_gives_a_reason():
    """ "Not displayed" is not a reason. The reason is what a later reader
    argues with, and it is the only thing separating this allowlist from a
    rubber stamp."""
    for name, reason in _NO_READER_YET.items():
        assert len(reason) > 60, f"{name} needs a real reason, not a label"


def test_the_scan_would_catch_a_planted_orphan(tmp_path):
    """The guard's own guard."""
    orphan = tmp_path / "orphan.py"
    orphan.write_text(
        "class X:\n    @property\n    def nobody_reads_this(self):\n        return 1\n",
        encoding="utf-8",
    )

    assert _properties(orphan) == ["nobody_reads_this"]
    assert _is_read("nobody_reads_this") is False
