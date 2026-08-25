"""The reconciliation poll must not be able to wedge silently (item 34).

On 25 August `ReconciliationMonitor` started at 09:09:52, ran once, and then
completed NONE of the ~20 polls due in the following 6h50m, while the app
placed nine bracketed entries and was otherwise healthy. Nothing said so: no
exception was raised, so `_run`'s handler never fired and no line was written.

The signature is a hung `await` inside `poll()`. The IBKR adapter has no
timeout on ANY of its eight awaits on the client - `reqExecutionsAsync`,
reached first through `absorb_broker_fills`, resolves only when IBKR sends
`execDetailsEnd`, and if that message is lost the future never completes.

While wedged, nothing compares book to broker, nothing verifies a stop, the
orphan scan does not run, and `absorb_broker_fills` does not run - so a stop
firing is never recorded and the app keeps believing it holds a position it
has already exited.

A loop whose only failure mode is silence cannot be monitored by reading its
log. It needs a DEADLINE.
"""

from __future__ import annotations

import asyncio

import pytest

from qat.config import Settings
from qat.domain.oms.reconciliation import ReconciliationMonitor


class _StuckOMS:
    """An OMS whose reconciliation never returns, like 25 August's."""

    def __init__(self) -> None:
        self.kill_switch = type("_KS", (), {"tripped": False, "reason": None})()
        self.scans = 0

    async def adopt_broker_positions(self) -> dict[str, float]:
        return {}

    async def check_reconciliation(self) -> bool:
        await asyncio.Event().wait()  # never returns, exactly like the field case
        raise AssertionError("unreachable")

    async def check_resting_orders(self) -> list[object]:
        self.scans += 1
        return []


@pytest.mark.asyncio
async def test_a_hung_poll_raises_and_is_logged_rather_than_hanging_forever(caplog):
    oms = _StuckOMS()
    monitor = ReconciliationMonitor(
        oms,  # type: ignore[arg-type]
        settings=Settings(  # type: ignore[arg-type]
            _env_file=None,
            reconciliation_poll_seconds=0.05,
            reconciliation_poll_timeout_seconds=0.2,
        ),
    )

    with caplog.at_level("ERROR"):
        # Must COMPLETE. Before the deadline this awaited forever.
        await asyncio.wait_for(monitor.poll(), timeout=10)

    assert "poll" in caplog.text.lower()
    assert "did not complete" in caplog.text.lower() or "timed out" in caplog.text.lower()


@pytest.mark.asyncio
async def test_the_loop_survives_a_hung_poll_and_keeps_trying(caplog):
    """A deadline that ended the rail would be worse than the wedge: at least
    the wedge left the app trading. The loop must log and come round again."""
    oms = _StuckOMS()
    monitor = ReconciliationMonitor(
        oms,  # type: ignore[arg-type]
        settings=Settings(  # type: ignore[arg-type]
            _env_file=None,
            reconciliation_poll_seconds=0.05,
            reconciliation_poll_timeout_seconds=0.2,
        ),
    )
    monitor._task = asyncio.create_task(monitor._run())
    await asyncio.sleep(1.0)
    still_running = not monitor._task.done()
    await monitor.stop()

    assert still_running, "the poll loop died on a hung poll instead of continuing"
    assert caplog.text.count("poll") >= 1
