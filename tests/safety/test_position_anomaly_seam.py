"""Reconciliation being able to be told a difference is explained.

Today `check_reconciliation` compares and trips, with no way to be told "this
one is accounted for" - so an ordinary corporate action halts a session, which
is in the freeze's fix-immediately list as "the kill-switch tripping on
something that is not a real discrepancy".
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, positions: dict[str, float]) -> None:
        self._positions = dict(positions)

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since):
        return []


def _build(tmp_path, positions: dict[str, float]):
    """`data_dir` is per-test and never omitted.

    conftest sets QAT_DATA_DIR session-wide, so a bare Settings would give
    every test the SAME directory - and this store persists there, so one
    declared anomaly would quarantine that symbol for the rest of the suite.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return broker, oms, switch


@pytest.mark.asyncio
async def test_an_undeclared_divergence_still_trips_the_kill_switch(tmp_path):
    """Unchanged behaviour, and the more important half. An unexplained
    difference means this app's view of the account cannot be trusted, and that
    is account-wide by nature."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()

    broker._positions["CRWD"] = 64.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_declared_divergence_does_not_trip(tmp_path):
    """The seam. The session continues, and the symbol is quarantined."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0

    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert await oms.check_reconciliation() is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_a_declaration_does_not_excuse_a_later_movement(tmp_path):
    """The immunity test, at the seam rather than in the store. A symbol that
    moves again has not been looked at, and must halt."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )
    assert await oms.check_reconciliation() is False

    broker._positions["CRWD"] = 128.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_one_declared_symbol_does_not_excuse_another(tmp_path):
    """Quarantine is per symbol. A declaration on CRWD says nothing about AMD."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0, "AMD": 7.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    broker._positions["AMD"] = 14.0
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_an_explained_divergence_is_logged_once_not_every_poll(tmp_path, caplog):
    """Reconciliation polls on an interval. A line per poll floods the log and
    trains the operator to scroll past it - the same reason KillSwitch.trip
    ignores a repeat trip."""
    broker, oms, _ = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    with caplog.at_level("WARNING"):
        await oms.check_reconciliation()
        await oms.check_reconciliation()
        await oms.check_reconciliation()

    assert caplog.text.count("explained by a declared position anomaly") == 1
