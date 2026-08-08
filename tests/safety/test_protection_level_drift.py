"""A protective stop whose LEVEL moves at the broker is as serious as one that
disappears, and until now only disappearance was watched.

`verify_position_stops` compared presence - `symbol not in resting` - so a stop
still resting at a different price passed the check. `_position_stops` is what
PortfolioGovernor measures risk-at-stop against, and the book sits at 5.02%
against a 5.00% cap, so a belief wrong by a factor mis-states the aggregate
that gates entries in every OTHER symbol. A wrong denominator does not stay in
one symbol.
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
    """A broker that holds positions and can say what is actually resting."""

    def __init__(self, positions: dict[str, float], resting: dict[str, float]) -> None:
        self._positions = dict(positions)
        self._resting = dict(resting)
        self.fail_resting = False

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        if self.fail_resting:
            raise ConnectionError("broker unreachable")
        return dict(self._resting)


def _build(tmp_path, positions: dict[str, float], resting: dict[str, float]):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _StopBroker(positions, resting)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch)
    return broker, oms


@pytest.mark.asyncio
async def test_a_stop_whose_level_moved_is_reported_and_corrected(tmp_path):
    """The defect. The symbol is still present in `resting`, so the old
    presence test passed and the app kept believing 95.00."""
    broker, oms = _build(tmp_path, {"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()
    assert oms.position_stops() == {"AAPL": 95.0}

    broker._resting["AAPL"] = 87.5

    drifted = await oms.verify_position_stops()

    assert drifted == ["AAPL"]
    # The broker is the authority on what is resting, so the belief is
    # replaced rather than dropped - the position IS protected, just not
    # where this app thought.
    assert oms.position_stops() == {"AAPL": 87.5}


@pytest.mark.asyncio
async def test_a_stop_still_at_its_recorded_level_is_left_alone(tmp_path):
    """The quiet path has to stay quiet, or the log fills with non-events and
    the operator stops reading it."""
    _, oms = _build(tmp_path, {"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()

    assert await oms.verify_position_stops() == []
    assert oms.position_stops() == {"AAPL": 95.0}


@pytest.mark.asyncio
async def test_cent_level_rounding_is_not_drift(tmp_path):
    """The comparison is relative, not absolute. A book holding WFC at 87 and
    GS at 1,040 cannot share an absolute epsilon: one loose enough for GS is
    blind to a real move on WFC."""
    broker, oms = _build(tmp_path, {"GS": 7.0}, {"GS": 1040.00})
    await oms.adopt_broker_positions()

    broker._resting["GS"] = 1040.01

    assert await oms.verify_position_stops() == []


@pytest.mark.asyncio
async def test_a_vanished_stop_is_still_reported(tmp_path):
    """The behaviour that already existed must survive the change."""
    broker, oms = _build(tmp_path, {"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()

    broker._resting.pop("AAPL")

    assert await oms.verify_position_stops() == ["AAPL"]
    assert oms.position_stops() == {}


@pytest.mark.asyncio
async def test_a_broker_that_cannot_answer_changes_nothing(tmp_path):
    """An adapter that cannot answer must not read as "no stops rest anywhere",
    which is indistinguishable from a genuinely naked book and would be acted
    on as if it were one."""
    broker, oms = _build(tmp_path, {"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()
    broker.fail_resting = True

    with pytest.raises(ConnectionError):
        await oms.verify_position_stops()

    assert oms.position_stops() == {"AAPL": 95.0}
