"""No IBKR call may await forever (item 34, root cause).

The reconciliation poll wedged on 25 August and completed none of the ~20 polls
due in 6h50m, silently, because a hung `await` raises nothing. The deadline
added to `poll()` catches that in ONE loop. This closes the hole itself.

Measured before the fix: `ib_adapter.py` contained **eight** awaits on the IB
client and **zero** timeouts. The first one `check_reconciliation` reaches is
`recent_fills`':

    executions = await request(ExecutionFilter())

`reqExecutionsAsync` resolves only when IBKR sends `execDetailsEnd`. If that
message is lost - a known failure after a reconnect, and the 25 August session
made six failed connection attempts before it connected - the future never
completes and whatever loop made the call is gone for the life of the process.

A timeout turns "this rail is silently dead forever" into "this call failed,
loudly, and the loop comes round again". Losing one poll is recoverable;
losing every future poll is what actually happened.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter


def _hanging_adapter(**client_methods):
    """An adapter whose client accepts a call and never answers."""
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.settings = Settings(  # type: ignore[arg-type]
        _env_file=None, market="ASX", ibkr_call_timeout_seconds=0.15
    )
    adapter.ib_client = SimpleNamespace(**client_methods)
    return adapter


async def _never_answers(*_args, **_kwargs):
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


async def _assert_gives_up_quickly(coro, caplog) -> None:
    """The ADAPTER must be what times out, not this test.

    An outer `asyncio.wait_for` would raise `TimeoutError` whether or not the
    adapter has a guard, so asserting on the exception alone is vacuous - the
    first draft of these tests passed against the unfixed adapter for exactly
    that reason. The adapter's own timeout log distinguishes its deadline from
    the outer test guard without a flaky one-second wall-clock assertion.
    """
    with caplog.at_level(logging.ERROR), pytest.raises(TimeoutError):
        await asyncio.wait_for(coro, timeout=10)
    assert "IBKR did not answer" in caplog.text


@pytest.mark.asyncio
async def test_recent_fills_does_not_hang_forever(caplog):
    """The call that wedged the poll on 25 August."""
    adapter = _hanging_adapter(reqExecutionsAsync=_never_answers)
    await _assert_gives_up_quickly(adapter.recent_fills(None, None), caplog)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_open_orders_does_not_hang_forever(caplog):
    """The orphan scan's own call. If this hangs, M141's rail is dead too."""
    adapter = _hanging_adapter(reqAllOpenOrdersAsync=_never_answers)
    await _assert_gives_up_quickly(adapter.open_orders(), caplog)


@pytest.mark.asyncio
async def test_resting_stop_orders_does_not_hang_forever(caplog):
    """The protection check. A hang here means `verify_position_stops` never
    runs and nothing notices a stop has gone."""
    adapter = _hanging_adapter(reqAllOpenOrdersAsync=_never_answers)
    await _assert_gives_up_quickly(adapter.resting_stop_orders(), caplog)


@pytest.mark.asyncio
async def test_a_timely_call_is_unaffected():
    """The guard must not change the happy path."""

    async def _answers(*_args, **_kwargs):
        return []

    adapter = _hanging_adapter(reqAllOpenOrdersAsync=_answers)
    assert await adapter.open_orders() == []


def test_the_adapter_has_no_unguarded_awaits_left():
    """A structural sweep, so a NEW unguarded await fails this test rather than
    waiting to wedge a session.

    `connectAsync` is excluded: it takes its own `timeout=` argument and is
    already bounded.
    """
    import pathlib
    import re

    source = pathlib.Path("src/qat/data/broker/ib_adapter.py").read_text(encoding="utf-8")
    unguarded = [
        line.strip()
        for line in source.splitlines()
        if re.search(r"await\s+(request|self\.ib_client)\b", line)
        and "connectAsync" not in line
        and "_call(" not in line
    ]
    assert not unguarded, (
        "these awaits on the IB client are not routed through the timeout "
        f"helper and can hang a loop forever: {unguarded}"
    )
