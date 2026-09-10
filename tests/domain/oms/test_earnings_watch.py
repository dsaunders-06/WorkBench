"""M41's hold-through half, as detection (10 September 2026).

The entry half shipped as M57 - `_earnings_scalar` halves size into a scheduled
print. Nothing looked again afterwards: a position whose print arrives three
weeks into a hold passed unremarked, against a 6% gap budget measured on
ORDINARY nights while earnings gaps run 15-20%.
"""

from __future__ import annotations

import logging

from qat.domain.oms.earnings_watch import (
    positions_facing_earnings,
    report,
    unreadable_symbols,
)

_HELD = {"BHP.AX": 793.0, "TAH.AX": 64229.0, "WOW.AX": 1098.0}


def _calendar(**days: int | None):
    def lookup(symbol: str) -> int | None:
        return days.get(symbol.replace(".AX", ""))

    return lookup


def test_only_positions_inside_the_window_are_reported() -> None:
    found = positions_facing_earnings(_HELD, _calendar(BHP=2, TAH=40, WOW=None), within=5)

    assert [e.symbol for e in found] == ["BHP.AX"]


def test_soonest_first() -> None:
    """The one reporting tomorrow matters more than the one reporting Friday."""
    found = positions_facing_earnings(_HELD, _calendar(BHP=4, TAH=1, WOW=3), within=5)

    assert [e.symbol for e in found] == ["TAH.AX", "WOW.AX", "BHP.AX"]


def test_a_flat_symbol_is_not_a_held_position() -> None:
    found = positions_facing_earnings({"BHP.AX": 0.0}, _calendar(BHP=1), within=5)

    assert found == []


def test_an_unreadable_calendar_is_not_reported_as_safe() -> None:
    """⚠️ M39's lesson, unchanged: "nothing pending" and "I could not find out"
    are different facts, and a screen reporting the first when the second is
    true asserts something false."""
    unreadable = unreadable_symbols(_HELD, _calendar(BHP=2))

    assert unreadable == ["TAH.AX", "WOW.AX"]


def test_a_raising_calendar_never_breaks_the_sweep() -> None:
    """This runs inside the protection sweep. A diagnostic that can throw would
    stop stops being re-armed, which is the 9 September deadlock's shape."""

    def explode(symbol: str) -> int | None:
        raise RuntimeError("vendor down")

    assert positions_facing_earnings(_HELD, explode, within=5) == []
    assert unreadable_symbols(_HELD, explode) == ["BHP.AX", "TAH.AX", "WOW.AX"]


def test_it_says_out_loud_that_it_is_not_a_rail(caplog) -> None:
    """⚠️ The wording is the point. A line that merely names the exposure reads
    as though something handled it."""
    with caplog.at_level(logging.WARNING):
        report(_HELD, _calendar(BHP=1, TAH=99, WOW=99), within=5)

    assert "EARNINGS WITHIN" in caplog.text
    assert "not a rail" in caplog.text
    assert "BHP.AX" in caplog.text


def test_nothing_is_logged_when_nothing_is_due(caplog) -> None:
    """A warning printed every sweep stops being read."""
    with caplog.at_level(logging.WARNING):
        report(_HELD, _calendar(BHP=99, TAH=99, WOW=99), within=5)

    assert "EARNINGS WITHIN" not in caplog.text
