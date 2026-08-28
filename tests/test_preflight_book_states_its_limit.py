"""The book check says what it does NOT cover (item 25).

`preflight`'s book check walks HELD positions and asks which lack a stop. It
answers *"is every position protected"* and it cannot answer *"what is resting
that the book does not explain"* — a stop resting on a symbol the book does not
hold, which is exactly M141's orphan shape, is invisible to it.

⚠️ **The fix is not to widen it.** That second question belongs to
`check_resting_orders`, which owns the reconciler and can cancel; duplicating it
here would be a second derivation of one question, the shape this project has
been bitten by repeatedly. What preflight must stop doing is implying coverage
it does not have — a clean `book` line reading "all carrying a resting stop"
invites an operator to conclude nothing unexpected is resting, which it never
checked.
"""

from __future__ import annotations

import pytest

from qat.preflight import Status, book_checks


class _Position:
    def __init__(self, symbol: str, quantity: float) -> None:
        self.symbol, self.quantity = symbol, quantity


class _Broker:
    def __init__(self, positions, stops) -> None:
        self._positions, self._stops = positions, stops

    async def positions(self):
        return self._positions

    async def resting_stops(self):
        return self._stops


def _book(checks):
    return next(c for c in checks if c.name == "book")


@pytest.mark.asyncio
async def test_a_clean_book_states_what_it_did_not_check() -> None:
    """⚠️ The whole item. "All carrying a resting stop" is true and reads as
    "nothing unexpected is resting", which was never asked."""
    broker = _Broker([_Position("BHP.AX", 100.0)], {"BHP.AX": 30.0})

    check = _book(await book_checks(broker))

    assert check.status is Status.OK
    assert "orphan" in check.detail.lower() or "does not hold" in check.detail.lower(), (
        "a clean book line must say it did not look for stops resting on symbols the "
        "book does not hold - otherwise it implies coverage it has not got (item 25)"
    )


@pytest.mark.asyncio
async def test_it_names_the_check_that_does_answer_it() -> None:
    """A limit stated without naming its owner sends the reader looking."""
    broker = _Broker([_Position("BHP.AX", 100.0)], {"BHP.AX": 30.0})

    assert "check_resting_orders" in _book(await book_checks(broker)).detail


@pytest.mark.asyncio
async def test_an_unprotected_position_still_FAILS_and_still_names_it() -> None:
    """The limit must not soften the finding this check DOES make."""
    broker = _Broker([_Position("BHP.AX", 100.0), _Position("CBA.AX", 50.0)], {"BHP.AX": 30.0})

    check = _book(await book_checks(broker))

    assert check.status is Status.FAIL
    assert "CBA.AX" in check.detail


@pytest.mark.asyncio
async def test_an_empty_book_says_it_checked_nothing_rather_than_nothing_is_wrong() -> None:
    """⚠️ "no positions, no resting stops" asserts the SECOND half, which this
    check cannot see. With no positions held, the loop runs zero times - a stop
    resting on any symbol at all would go unreported."""
    check = _book(await book_checks(_Broker([], {})))

    assert check.status is Status.OK
    assert "no positions" in check.detail
    assert "resting" in check.detail.lower()
    assert (
        "no resting stops" not in check.detail
    ), "an empty book cannot assert that nothing is resting - it never looked"
