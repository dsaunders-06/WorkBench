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

import pytest

import qat.presentation as presentation_package

_HEX = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")
# The holes M75's guard left, found while doing §4.4 (M78). Hex was never the
# only way to write a colour by hand:
#
# * `color: gray` in 20 places, where MUTED exists and its docstring calls it
#   load-bearing - "an unavailable number rendered at full weight reads as data".
# * `#444` in 4 places, three digits, which a six-digit pattern cannot see.
# * `pen="y"` in 6 places, which is not a wrong colour so much as no colour at
#   all - a single-letter code the plotting library resolves for you.
#
# A guard that catches one spelling and misses three teaches the wrong lesson:
# that the rule is about hex rather than about where colour decisions live.
_NAMED = re.compile(
    r"(?:color|background|background-color|border-color)\s*:\s*"
    r"(gray|grey|white|black|red|green|blue|orange|yellow|silver|maroon|navy)\b",
    re.IGNORECASE,
)
_PEN_CODE = re.compile(r"\bpen\s*=\s*['\"]([bgrcmykw])['\"]")
_PRESENTATION = Path(presentation_package.__file__).parent
# The one module allowed to know what a colour actually is. That is the whole
# point of it: "Primitives are raw values named by what they ARE. Nothing
# outside this module should use them."
_ALLOWED = {"theme.py"}


def _hand_written_colours(path: Path) -> list[tuple[int, str]]:
    """Every colour decided in this file rather than asked of `theme`."""
    found: list[tuple[int, str]] = []
    source = path.read_text(encoding="utf-8")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.STRING:
            continue
        for pattern in (_HEX, _NAMED, _PEN_CODE):
            for match in pattern.findall(token.string):
                found.append((token.start[0], match))
    # A pen code is an argument, not a string's contents, so it is matched
    # against the source line rather than against a literal.
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for match in _PEN_CODE.findall(line):
            found.append((number, f'pen="{match}"'))
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
        for line, literal in _hand_written_colours(path)
    }

    assert offenders == {}, (
        "These decide a colour instead of asking theme for it. Every value "
        "below already has a semantic name - see ROADMAP M75 and M78."
    )


def _scan(source: str) -> list[str]:
    """The guard, run over a string, so its own behaviour can be asserted."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(source)
        path = Path(handle.name)
    try:
        return [literal for _line, literal in _hand_written_colours(path)]
    finally:
        path.unlink()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('x = "color: #b71c1c;"\n', ["#b71c1c"]),
        ('x = "border: 1px solid #444;"\n', ["#444"]),
        ('x = "color: gray;"\n', ["gray"]),
        ('x = "background-color: white;"\n', ["white"]),
        ('plot(pen="y")\n', ['pen="y"']),
    ],
)
def test_the_scan_would_actually_catch_one(source, expected):
    """The guard's own guard. M75's version caught six-digit hex and nothing
    else, and declared the layer clean while 32 hand-written colours remained -
    so a guard is only worth what its own tests prove it sees."""
    assert _scan(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "# theme.DANGER, not #d9534f, because the migration missed it\n",
        "# the cone used pen='y' before it had a name\n",
        '"""A docstring may say gray without meaning it."""\n',
    ],
)
def test_prose_about_a_colour_is_not_an_offence(source):
    """`workbench.py` explains why it no longer uses a hand-written red.
    Discussing a colour is not using one, and a guard that cannot tell the
    difference gets disabled rather than obeyed."""
    assert _scan(source) == []
