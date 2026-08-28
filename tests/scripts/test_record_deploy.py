"""The deploy record is rewritten by the deploy, not by a human (item 29).

`handoff_state.DEPLOYED` is hand-maintained, and its own comment says it "must
change in the same minute as the copy". It has been wrong for a day after M104,
across the whole M130 deploy, for two hours after M139 - and, found while fixing
this, **through every deploy of 28 August**: it still read `0b1ecd6` (M148) with
M155 installed.

⚠️ That is the point. Exhortation has now failed not three times but ten, and
the last seven were failures of the person who wrote the exhortation down. A
step a human must remember is a step that gets missed in the rush before a
close, which is exactly when a wrong deploy record is most expensive.

Only the REWRITE is here. The install itself - rename, copy, verify - stays in
the deploy script, because it needs the operator's own permissions and cannot be
exercised by a test. What can be tested is the one operation that has actually
gone wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from record_deploy import rewrite_deployed  # noqa: E402


def _source(commit: str) -> str:
    return (
        "# Updated in the same minute as the copy, which is the whole of item 29.\n"
        f'DEPLOYED = "{commit}"\n'
        "\n"
        "def something_else() -> None:\n"
        '    return "0b1ecd6"\n'
    )


def test_it_rewrites_the_constant(tmp_path) -> None:
    path = tmp_path / "handoff_state.py"
    path.write_text(_source("0b1ecd6"), encoding="utf-8")

    assert rewrite_deployed(path, "9bd111a") is True
    assert 'DEPLOYED = "9bd111a"' in path.read_text(encoding="utf-8")


def test_it_touches_only_the_constant(tmp_path) -> None:
    """⚠️ The old commit appears elsewhere in the file - in prose, in history
    notes, sometimes as a string in another function. A blind replace of the
    commit text would rewrite the record of PREVIOUS deploys, which is the one
    thing this file exists to preserve."""
    path = tmp_path / "handoff_state.py"
    path.write_text(_source("0b1ecd6"), encoding="utf-8")

    rewrite_deployed(path, "9bd111a")
    after = path.read_text(encoding="utf-8")

    assert 'return "0b1ecd6"' in after, "an unrelated occurrence was rewritten"
    assert after.count("9bd111a") == 1


def test_an_unchanged_commit_is_a_no_op(tmp_path) -> None:
    """Returns False so the caller can say "already current" rather than
    claiming to have done something."""
    path = tmp_path / "handoff_state.py"
    path.write_text(_source("9bd111a"), encoding="utf-8")
    before = path.read_bytes()

    assert rewrite_deployed(path, "9bd111a") is False
    assert path.read_bytes() == before


def test_a_missing_constant_RAISES(tmp_path) -> None:
    """⚠️ Never a silent no-op. If the line has been renamed or removed, the
    deploy must fail loudly rather than complete while leaving the record
    stale - a deploy that half-succeeds is how this became wrong in the first
    place."""
    path = tmp_path / "handoff_state.py"
    path.write_text("# no constant here\n", encoding="utf-8")

    with pytest.raises(ValueError, match="DEPLOYED"):
        rewrite_deployed(path, "9bd111a")


def test_a_bad_commit_is_refused(tmp_path) -> None:
    """A short git sha is 7-40 hex characters. Writing anything else would put
    a value in the record that `deployed_milestone()` cannot resolve."""
    path = tmp_path / "handoff_state.py"
    path.write_text(_source("0b1ecd6"), encoding="utf-8")

    for bad in ("", "zzz", "not-a-sha", "0b1ec"):
        with pytest.raises(ValueError, match="commit"):
            rewrite_deployed(path, bad)


def test_the_live_file_still_carries_the_constant() -> None:
    """⚠️ The allowlist problem: this helper is worthless if the real file stops
    matching what it edits, and it would fail only at the next deploy."""
    source = (Path(__file__).resolve().parents[2] / "scripts" / "handoff_state.py").read_text(
        encoding="utf-8"
    )

    assert "\nDEPLOYED = " in source, "handoff_state.py no longer has the constant to rewrite"
