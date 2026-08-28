"""A source corpus that refuses to be empty (item 20).

M135's colour guard scanned every screen for a hand-written colour and
reported none. It was right about what it saw and wrong about the codebase:
PEP 701 had moved f-string text to a token type it did not look at, so from
one interpreter upgrade onward it read every f-string as empty - while
`dashboard.py` carried a live `color: white` inside one.

**A narrowed guard is worse than no guard, because its green is read as
evidence.** The narrowing that is easiest to miss is not a subtle regex: it is
a corpus that quietly became empty. `Path.rglob` on a directory that does not
exist returns nothing and raises nothing, so a moved package, a renamed folder
or one wrong `parents[1]` turns "no offenders" into "nothing was looked at" -
and the two are indistinguishable at the assertion.

Two guards had already learned this the hard way and grown a
`test_there_are_..._to_check` of their own. Two others had not. Rather than
add a third and fourth copy of that test, the check moves to where the corpus
is BUILT, so a guard written next month inherits it without knowing the story.

⚠️ This proves only that files were READ. It cannot prove the detector run
over them still detects anything - that needs a planted violation, which is
what each guard's own positive-control test is for. Both halves are required:
this one answers "did we look", the other answers "can we see".
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

__all__ = ["source_files"]


def source_files(
    root: Path,
    pattern: str = "*.py",
    *,
    minimum: int,
    exclude: Iterable[str] = (),
    recurse: bool = False,
) -> list[Path]:
    """The files a guard will scan, or an assertion failure naming why not.

    `minimum` is deliberately required rather than defaulted to 1. One file is
    a corpus that has ALREADY collapsed in most of these cases, and a caller
    forced to write the number has to look at what it is actually scanning.
    Set it well below today's count - it exists to catch a corpus falling off
    a cliff, not to be re-tuned whenever a module is added or removed.
    """
    assert root.is_dir(), (
        f"the scan root {root} is not a directory, so this guard would have "
        f"scanned nothing and passed. A moved package or a wrong `parents[N]` "
        f"looks exactly like a clean codebase from inside the assertion."
    )

    skip = set(exclude)
    found = sorted(
        path
        for path in (root.rglob(pattern) if recurse else root.glob(pattern))
        if path.name not in skip and "__pycache__" not in path.parts
    )

    assert len(found) >= minimum, (
        f"expected at least {minimum} files matching {pattern!r} under {root}, "
        f"found {len(found)}: {[p.name for p in found]}. A guard that silently "
        f"checks nothing is worse than no guard - see M135."
    )
    return found
