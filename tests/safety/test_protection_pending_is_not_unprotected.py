"""A stop being REPLACED is not a stop that vanished, and the rails could not
tell the difference.

⚠️ FOUND 9 September 2026, designing the partial-exit leg release. Three
independent 300-second timers touch one piece of state:

  * `DeleverSweep._run` trims EVERY position when risk is over cap;
  * `check_reconciliation` runs `verify_position_stops`, which POPS the stop
    belief for any held symbol with nothing resting;
  * `_sweep_protection` runs `rearm_protective_stops`, which puts it back.

And `PortfolioGovernor._per_share_risk` returns THE WHOLE PRICE when no stop is
known - "Unknown protection is treated as no protection." So if reconciliation
wins the race against re-arming, every trimmed position is repriced from
(price - stop) to full value, the aggregate risk-at-stop jumps by about an order
of magnitude, `delever_fraction` grows, and the next sweep trims harder. A
de-lever sweep runs during a breach by definition, so that is exactly when it
would happen.

⚠️ THE GAP IS NOT IN THE LEG CODE. It is that "unprotected" and "re-protection
in flight" were the same state. `submit_protective_stop` only ever proposes -
"nothing reaches the broker without sign-off" - so there is ALWAYS a window
where the old leg is cancelled, the replacement is pending, and nothing rests.
Shortening that window does not close it; naming the state does.

⚠️ AND THE GRACE MUST BE BOUNDED. `verify_position_stops` exists because a stop
that quietly stopped existing makes the whole book look safer than it is - six
positions at once on 31 July. A belief held open indefinitely because something
is "pending" would recreate that defect with an excuse attached, so the grace
lasts ONE check and then the belief is dropped anyway.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _StopBroker:
    """Holds positions and reports what is actually resting."""

    def __init__(self, positions: dict[str, float], resting: dict[str, float]) -> None:
        self._positions = dict(positions)
        self.resting = dict(resting)

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return dict(self.resting)


def _build(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _StopBroker({"AAPL": 50.0}, {"AAPL": 95.0})
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return broker, oms


@pytest.mark.asyncio
async def test_a_lost_stop_with_NO_replacement_pending_is_still_dropped(tmp_path):
    """⚠️ THE PRESENCE GUARD, and it goes first deliberately.

    The two tests below assert that a belief SURVIVES. If this fixture could not
    produce a DROP in the first place they would pass against any code at all -
    the vacuous shape this project keeps rediscovering. This proves the drop is
    real before anything asserts its absence.
    """
    broker, oms = _build(tmp_path)
    await oms.adopt_broker_positions()
    assert oms.position_stops() == {"AAPL": 95.0}

    broker.resting = {}
    await oms.verify_position_stops()

    assert oms.position_stops() == {}, "a stop with no replacement pending must be dropped"


@pytest.mark.asyncio
async def test_a_lost_stop_SURVIVES_while_its_replacement_awaits_signoff(tmp_path):
    """The fix. The position is being re-protected, not left bare, and the
    governor must keep pricing it at the stop rather than at full value."""
    broker, oms = _build(tmp_path)
    await oms.adopt_broker_positions()

    broker.resting = {}
    await oms.submit_protective_stop("AAPL", 30.0, 95.0)
    await oms.verify_position_stops()

    assert oms.position_stops() == {"AAPL": 95.0}, (
        "re-protection in flight must not be read as unprotected - that is what "
        "reprices the book at full value and drives the sweep to trim again"
    )


@pytest.mark.asyncio
async def test_the_grace_lasts_ONE_check_so_a_stuck_signoff_cannot_blind_the_rail(tmp_path):
    """⚠️ Bounded, or this is the 31 July defect with a justification attached.

    A sign-off that never happens must not hold the belief open forever, so the
    second consecutive check drops it however pending the replacement looks.
    """
    broker, oms = _build(tmp_path)
    await oms.adopt_broker_positions()

    broker.resting = {}
    await oms.submit_protective_stop("AAPL", 30.0, 95.0)

    await oms.verify_position_stops()
    assert oms.position_stops() == {"AAPL": 95.0}, "the first check grants the grace"

    await oms.verify_position_stops()
    assert oms.position_stops() == {}, "the second check must drop it anyway"


@pytest.mark.asyncio
async def test_the_grace_is_RENEWED_once_protection_rests_again(tmp_path):
    """⚠️ FOUND BY SABOTAGE, and it escaped the first three tests.

    Deleting the `discard` that releases the grace when a stop is seen resting
    again left every test green. It is not cosmetic: the reprieve is spent
    per-symbol and never returned, so the SECOND re-protection in a symbol's
    life would drop its belief on the very first check - reinstating the
    full-value-at-risk repricing, and the de-lever feedback loop with it, for
    exactly the positions that have been re-protected before.

    A position is re-protected on every stop-out and every trim, so "twice in
    one symbol" is ordinary, not an edge case.
    """
    broker, oms = _build(tmp_path)
    await oms.adopt_broker_positions()

    # First re-protection: the grace is granted and spent.
    broker.resting = {}
    await oms.submit_protective_stop("AAPL", 30.0, 95.0)
    await oms.verify_position_stops()
    assert oms.position_stops() == {"AAPL": 95.0}

    # Protection rests again, which must RETURN the grace.
    broker.resting = {"AAPL": 95.0}
    await oms.verify_position_stops()

    # Second re-protection: must be reprieved exactly as the first was.
    broker.resting = {}
    await oms.verify_position_stops()

    assert oms.position_stops() == {"AAPL": 95.0}, (
        "the grace must be renewed once a stop rests again, or a symbol is "
        "protected on its first re-arm and exposed on every one after it"
    )
