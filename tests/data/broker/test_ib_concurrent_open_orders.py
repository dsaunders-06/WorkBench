"""Two callers may not collide on `reqAllOpenOrders` (item 34, ROOT CAUSE).

The 25 August wedge was blamed on `reqExecutionsAsync` losing an
`execDetailsEnd`. That was a guess from reading a call site, and it was wrong:
`reqExecutionsAsync` keys its future on `client.getReqId()`, which is unique per
request, so two of them cannot interfere.

`reqAllOpenOrdersAsync` does not. Measured against the installed ib_async 2.1.0::

    def reqAllOpenOrdersAsync(self):
        future = self.wrapper.startReq("openOrders")   # a LITERAL key
        self.client.reqAllOpenOrders()
        return future

    def startReq(self, key, ...):
        future = asyncio.Future()
        self._futures[key] = future                    # OVERWRITES, silently

`openOrderEnd` resolves whichever future is in the dict at the time. A second
call while the first is in flight replaces the first future without resolving or
cancelling it, so the first caller's await never returns.

This application has two independent asyncio tasks that both reach it, and
`reconciliation_poll_seconds` and `protection_sweep_seconds` are BOTH 300.0 -
the engines start in the same second, so the two timers are phase-locked and
collide on every tick for the life of the process, not occasionally:

  * `ReconciliationMonitor.poll` -> `check_resting_orders` -> `open_orders()`
  * `CorporateActionMonitor.refresh` -> `resting_stop_orders()`

That is why the startup scan ALWAYS succeeds - the orchestrator awaits each
engine's `start()` in turn, so nothing overlaps - and why every poll after it
failed. Before the deadline landed, the orphaned await hung for the life of the
process: 6h50m and ~20 missed polls on 25 August, in silence.

⚠️ The fakes in `test_ib_call_timeouts.py` are `async def`, which CANNOT
reproduce this: calling a coroutine function runs none of its body, so no
`startReq` happens until the await. The real method is a plain `def` that
registers its future the moment it is CALLED - which is at the call site, before
`_call` is ever entered. A lock inside `_call` would therefore be too late.
"""

from __future__ import annotations

import asyncio

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter


class _SharedKeyClient:
    """ib_async's real semantics: one literal key, and the last writer wins.

    Deliberately a faithful copy of `Wrapper.startReq`/`_endReq` rather than a
    convenient stand-in. The bug lives in the overwrite, so a fake that hands
    every caller its own future would test nothing.
    """

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future] = {}
        self.requests_received = 0

    def reqAllOpenOrdersAsync(self) -> asyncio.Future:  # noqa: N802 - library spelling
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._futures["openOrders"] = future
        self.requests_received += 1
        return future

    def open_order_end(self) -> None:
        """What the Gateway sends back: resolves the ONE registered future."""
        future = self._futures.pop("openOrders", None)
        if future is not None and not future.done():
            future.set_result([])


def _adapter(client: _SharedKeyClient) -> IBAdapter:
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.settings = Settings(  # type: ignore[arg-type]
        _env_file=None, market="ASX", ibkr_call_timeout_seconds=0.3
    )
    adapter.ib_client = client  # type: ignore[assignment]
    return adapter


async def _answer_every_request(client: _SharedKeyClient) -> None:
    """A healthy Gateway: answers each request it receives, promptly."""
    answered = 0
    for _ in range(200):
        await asyncio.sleep(0.005)
        while answered < client.requests_received:
            client.open_order_end()
            answered += 1


@pytest.mark.asyncio
async def test_two_concurrent_open_order_reads_both_complete():
    """The reconciliation poll and the corporate-action sweep, on the same tick.

    Both callers must get an answer from a Gateway that answered both requests.
    Unguarded, the first caller's future is orphaned by the second's `startReq`
    and only the deadline ends it - which is the reconciliation rail going dark.
    """
    client = _SharedKeyClient()
    adapter = _adapter(client)
    gateway = asyncio.create_task(_answer_every_request(client))

    results = await asyncio.gather(
        adapter.open_orders(),
        adapter.resting_stop_orders(),
        return_exceptions=True,
    )
    gateway.cancel()

    timed_out = [r for r in results if isinstance(r, BaseException)]
    assert not timed_out, (
        "a caller was orphaned on the shared 'openOrders' future while the "
        f"Gateway answered every request: {timed_out}"
    )


@pytest.mark.asyncio
async def test_a_stalled_read_does_not_strand_the_next_caller():
    """One dead call must cost one poll, not every poll after it.

    The first caller gets no answer and must hit its own deadline; the second
    must then be able to ask and be answered normally. If serialisation let the
    failure hold the lock, this is where it would show.
    """
    client = _SharedKeyClient()
    adapter = _adapter(client)

    async def _answer_only_the_second() -> None:
        while client.requests_received < 2:
            await asyncio.sleep(0.005)
        client.open_order_end()

    gateway = asyncio.create_task(_answer_only_the_second())
    first = asyncio.create_task(adapter.open_orders())
    await asyncio.sleep(0.05)
    second = asyncio.create_task(adapter.resting_stop_orders())

    with pytest.raises(TimeoutError):
        await first
    assert await second == {}
    gateway.cancel()


def test_every_open_order_read_goes_through_the_serialising_helper():
    """A structural sweep, so a FOURTH call site cannot reintroduce the race.

    The rail was invisible for the same reason item 44's was: every layer
    looked correctly written. Three call sites each did their own
    `getattr(...,"reqAllOpenOrdersAsync")` and each was individually fine.
    """
    import pathlib
    import re

    source = pathlib.Path("src/qat/data/broker/ib_adapter.py").read_text(encoding="utf-8")
    body = source.split("async def _all_open_orders", 1)
    assert len(body) == 2, "the serialising helper is gone"

    outside = body[0] + body[1].split("\n    async def ", 1)[1]
    stray = [
        line.strip()
        for line in outside.splitlines()
        # The CALL, not the many docstrings that name it.
        if re.search(
            r"""(getattr\(\s*self\.ib_client\s*,\s*["']reqAllOpenOrdersAsync"""
            r"""|self\.ib_client\.reqAllOpenOrdersAsync)""",
            line,
        )
    ]
    assert not stray, (
        "these reach reqAllOpenOrders without the lock, so they can orphan "
        f"another caller's future on the shared 'openOrders' key: {stray}"
    )


def test_the_two_colliding_timers_still_share_an_interval():
    """Not a rail - a tripwire on the REASON this collided every tick.

    `reconciliation_poll_seconds` and `protection_sweep_seconds` are both
    300.0, and the engines start in the same second, so the two readers wake
    together for the life of the process. The lock is what makes that safe; if
    either default ever moves, the collision becomes intermittent instead of
    constant, and this test's failure is the note explaining why the logs
    changed shape.
    """
    settings = Settings(_env_file=None, market="ASX")  # type: ignore[arg-type]
    assert settings.reconciliation_poll_seconds == settings.protection_sweep_seconds == 300.0
