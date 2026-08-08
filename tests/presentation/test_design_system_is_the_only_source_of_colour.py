"""No screen spells a colour out by hand (M75).

§5 step 1 - *"67 inline stylesheets become one central sheet"* - was recorded as
done and was half-done. 22 raw-hex sites survived across six of the eight
presentation modules, every one of them a `theme.py` primitive written longhand:
`#b71c1c` is `DANGER`, `#1b5e20` is `SUCCESS`, `#b45309` is `WARNING`,
`#1e3a5f` is `ACCENT`. `settings.py` hand-wrote the exact string
`theme.callout("warning")` returns, twice.

**That is why `theme.callout` had zero consumers until M72** - not because
nothing needed it, but because the call sites that needed it still contained the
literal it was extracted from. A restyle would have changed some screens and not
others, which is worse than never having extracted it at all.

This test is the part that makes it stay fixed. The migration itself is a
one-off; without a guard the next hand-written `#b71c1c` arrives with the next
screen and nobody notices until the restyle that was supposed to be one edit.

**String literals only, via `tokenize`.** A naive text scan would flag the M74
comment in `workbench.py` that quotes `#d9534f` while explaining why it was
removed - and prose about a colour is not a use of one. Only what could actually
reach a stylesheet is checked.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import qat.presentation as presentation_package

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_PRESENTATION = Path(presentation_package.__file__).parent
# The one module allowed to know what a colour actually is. That is the whole
# point of it: "Primitives are raw values named by what they ARE. Nothing
# outside this module should use them."
_ALLOWED = {"theme.py"}


def _hex_literals(path: Path) -> list[tuple[int, str]]:
    """Every six-digit hex colour inside a STRING token in this file."""
    found: list[tuple[int, str]] = []
    source = path.read_text(encoding="utf-8")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING:
            for match in _HEX.findall(token.string):
                found.append((token.start[0], match))
    return found


def _modules() -> list[Path]:
    return sorted(p for p in _PRESENTATION.glob("*.py") if p.name not in _ALLOWED)


def test_there_are_modules_to_check():
    """A guard that silently checks nothing is worse than no guard."""
    assert len(_modules()) >= 8


def test_no_screen_writes_a_colour_by_hand():
    offenders = {
        f"{path.name}:{line}": literal
        for path in _modules()
        for line, literal in _hex_literals(path)
    }

    assert offenders == {}, (
        "These spell a colour out instead of asking theme for it. Every value "
        "below already has a semantic name - see ROADMAP M75."
    )


def test_the_scan_would_actually_catch_one():
    """The guard's own guard. A tokenizer change or a bad regex would turn this
    whole file into a test that passes by looking at nothing."""
    planted = 'x = "color: #b71c1c;"  # noqa\n'
    found = [
        match
        for token in tokenize.generate_tokens(io.StringIO(planted).readline)
        if token.type == tokenize.STRING
        for match in _HEX.findall(token.string)
    ]

    assert found == ["#b71c1c"]


def test_a_colour_named_in_a_comment_is_not_an_offence():
    """`workbench.py` explains in prose why it no longer uses `#d9534f`.
    Discussing a colour is not using one, and a guard that cannot tell the
    difference gets disabled rather than obeyed."""
    commented = "# theme.DANGER, not #d9534f, because the migration missed it\n"
    found = [
        match
        for token in tokenize.generate_tokens(io.StringIO(commented).readline)
        if token.type == tokenize.STRING
        for match in _HEX.findall(token.string)
    ]

    assert found == []
