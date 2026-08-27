"""A degraded advisory answer must announce itself (item 61, follow-up).

On 28 August the Workbench's AI note still made no reference to a 3,192-share
SUN.AX holding after item 61 shipped — and it was **impossible to tell whether
the fix had failed or the model had simply not mentioned the data**, because
`gather()` swallowed any failure into an empty `AccountFacts` and logged it at
DEBUG, which is below the root level and has never emitted a line in this
application.

⚠️ **That is the exact failure mode item 61 existed to fix, reproduced inside
its own fix.** The broad `except` is right — an advisory screen must never raise
— but a fallback whose failure is silent is indistinguishable from a fallback
that never fired.

There is also no logging anywhere else in `domain/ai_advisory/`, so an advisory
answer reaches the operator and then cannot be reconstructed. One INFO line
naming what the context actually carried is what makes a read-back answerable
instead of a guess.
"""

from __future__ import annotations

import logging

import pytest

from qat.presentation import advisory_account


class _Boom:
    """A runtime whose account read fails, which is the case that was silent."""

    @property
    def account_poller(self):
        raise RuntimeError("gateway went away mid-question")


@pytest.mark.asyncio
async def test_a_failed_gather_is_reported_at_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        facts = await advisory_account.gather(_Boom(), "SUN.AX")

    assert facts.positions == {}, "the answer must still be given"
    assert "SUN.AX" in caplog.text
    assert "account" in caplog.text.lower()
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "a degraded advisory context was reported below WARNING, so it cannot be "
        "distinguished from one that worked (item 61 follow-up)"
    )


@pytest.mark.asyncio
async def test_a_successful_gather_records_what_the_context_carried(caplog) -> None:
    """⚠️ The line that makes a read-back ANSWERABLE. Without it, 'the note did
    not mention the holding' cannot be told apart from 'the holding never
    reached the model'."""

    class _Position:
        def __init__(self, symbol, quantity):
            self.symbol, self.quantity = symbol, quantity

    class _Snapshot:
        positions = (_Position("SUN.AX", 3192.0), _Position("A2M.AX", 9636.0))

    class _Poller:
        async def snapshot(self):
            return _Snapshot()

    class _Runtime:
        """⚠️ Deliberately missing `risk_engine` and `settings`. The first
        version of `gather` wrapped everything in ONE try, so this stub - a
        working account read beside a failing optional one - produced an EMPTY
        context and the positions were thrown away. That is the live symptom."""

        account_poller = _Poller()

    with caplog.at_level(logging.INFO):
        facts = await advisory_account.gather(_Runtime(), "SUN.AX")

    assert facts.positions == {"SUN.AX": 3192.0, "A2M.AX": 9636.0}
    assert "2 position(s)" in caplog.text
    assert "SUN.AX" in caplog.text
    assert "held" in caplog.text.lower(), "the line must say whether THIS symbol is held"
