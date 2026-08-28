"""The guards that read this repository's own source must not go blind (item 20).

M135 found the colour guard reading every f-string as empty since the 3.12
upgrade: it reported no offenders while `dashboard.py` carried a live
`color: white`. Item 20 asked whether any sibling had narrowed the same way.

**Swept 28 August. Four guards scan a globbed corpus of `*.py`:**

| Guard | Corpus check | Positive control |
|---|---|---|
| `test_design_system_is_the_only_source_of_colour` | had one | had one (the f-string case) |
| `test_computed_values_have_readers` | had one | n/a - asserts a PRESENCE |
| `test_theme` | **none** | **none** |
| `test_m111_trading_day` | **none** | **none** |

⚠️ **No hidden live violation was found** - which is the honest result, and
unlike M135, which was hiding one. What two of the four could not do was tell
you their green meant anything. Three narrownesses were closed anyway:

* `test_theme`'s font-size scan required exactly one space after the colon, so
  `font-size:14px` was invisible.
* `test_theme`'s hex scan required the colour to be the WHOLE literal, so
  `"color: #b71c1c;"` - the only way a screen actually writes one - was
  invisible. **The positive control found this on its first run**, which is the
  argument for positive controls in one line.
* Both were latent because the tokenising colour guard covers the same ground.
  A guard that is only correct because another one overlaps it is not a guard.

Two halves are needed and neither substitutes for the other. `source_files`
answers *did we look at anything*; a planted violation answers *can we still
see*. This file pins the first and forbids the shape that skips it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from support.source_corpus import source_files

_TESTS = Path(__file__).resolve().parent
_SUPPORT = _TESTS / "support" / "source_corpus.py"


def test_a_missing_scan_root_is_refused_rather_than_scanned_as_empty() -> None:
    """⚠️ The failure this exists for. `rglob` on a directory that is not there
    yields nothing and raises nothing, so a wrong `parents[N]` reads exactly
    like a clean codebase."""
    with pytest.raises(AssertionError, match="not a directory"):
        source_files(_TESTS / "no-such-package", minimum=1)


def test_a_corpus_that_collapsed_is_refused(tmp_path: Path) -> None:
    (tmp_path / "only_one.py").write_text("x = 1", encoding="utf-8")

    with pytest.raises(AssertionError, match="at least 5"):
        source_files(tmp_path, minimum=5)


def test_the_minimum_is_met_by_real_files_not_by_caches(tmp_path: Path) -> None:
    """`__pycache__` holds a `.py`-named file in no build I have seen, but the
    exclusion is what every hand-rolled version of this did, and dropping it
    silently would let a stale cache satisfy the count."""
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "c.py").write_text("", encoding="utf-8")

    assert [p.name for p in source_files(tmp_path, recurse=True, minimum=2)] == ["a.py", "b.py"]


def test_an_excluded_name_does_not_count_toward_the_minimum(tmp_path: Path) -> None:
    (tmp_path / "theme.py").write_text("", encoding="utf-8")
    (tmp_path / "screen.py").write_text("", encoding="utf-8")

    with pytest.raises(AssertionError, match="at least 2"):
        source_files(tmp_path, exclude={"theme.py"}, minimum=2)


# `.py` specifically. A test globbing `*.csv.bak-*` in its own `tmp_path` is
# asserting about behaviour it just produced, not scanning the codebase, and
# has no corpus to lose.
_BARE_PY_GLOB = re.compile(r"\.r?glob\(\s*[\"']\*\*?/?\*?\.py[\"']")


def test_no_guard_globs_the_source_tree_without_the_corpus_check() -> None:
    """⚠️ The one that stops this coming back. A helper nobody is required to
    use is a convention, and a convention is what M135 had.

    Two files are exempt. `source_corpus.py` is the thing doing the globbing.
    This file holds the PLANTED globs that prove the pattern below still
    matches - and it flagged all three of them on its first run, which is the
    evidence that the exemption is a real one rather than a convenience.
    """
    exempt = {_SUPPORT, Path(__file__).resolve()}
    offenders = [
        f"{path.relative_to(_TESTS)}:{number}"
        for path in source_files(_TESTS, recurse=True, minimum=100)
        if path not in exempt
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _BARE_PY_GLOB.search(line.split("#", 1)[0])
    ]

    assert not offenders, (
        "these scan the source tree directly, so an empty corpus would read as "
        f"a clean codebase - build the file list with `source_files`: {offenders}"
    )


@pytest.mark.parametrize(
    "planted",
    [
        'files = src.rglob("*.py")',
        "files = src.glob('*.py')",
        'files = sorted(root.rglob("**/*.py"))',
    ],
)
def test_the_meta_guard_sees_a_bare_glob(planted: str) -> None:
    """⚠️ THE POSITIVE CONTROL for the assertion above - which, being an
    absence over a scan, is the exact shape this whole file is about."""
    assert _BARE_PY_GLOB.search(planted) is not None


def test_the_meta_guard_does_not_flag_a_fixture_glob() -> None:
    """A test looking for the backup it just wrote is not scanning source."""
    assert (
        _BARE_PY_GLOB.search('assert list(tmp_path.glob("closed_trades.csv.bak-*")) == []') is None
    )
