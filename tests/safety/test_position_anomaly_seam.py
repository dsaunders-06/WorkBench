"""Reconciliation being able to be told a difference is explained.

Today `check_reconciliation` compares and trips, with no way to be told "this
one is accounted for" - so an ordinary corporate action halts a session, which
is in the freeze's fix-immediately list as "the kill-switch tripping on
something that is not a real discrepancy".
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
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


# --- Block writes, allow exits ------------------------------------------------
#
# The rule chosen deliberately. Refusing entries, trims and re-arming stops the
# thing that destroys a position; refusing EXITS would be the shape M56c was a
# defect for, where a gate quietly suppressed the only route to selling.


class _ExitBroker(_Broker):
    """A broker whose position read can be made to fail."""

    def __init__(self, positions: dict[str, float]) -> None:
        super().__init__(positions)
        self.fail_positions = False

    async def positions(self) -> list[Position]:
        if self.fail_positions:
            raise ConnectionError("broker unreachable")
        return await super().positions()


def _build_exit(tmp_path, positions: dict[str, float]):
    """Per-test `data_dir`, for the reason given on `_build` above.

    A real DecisionJournal, because a refusal's REASON does not live on the
    Order - it goes to the journal, and M54 exists precisely so the audit trail
    answers "why did nothing happen" with a reason rather than a gap. Asserting
    on the file is the only way to know that actually happened.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _ExitBroker(positions)
    oms = OMS(
        broker,
        RiskEngine(bus, switch, settings=settings),
        switch,
        settings=settings,
        journal=DecisionJournal(tmp_path),
    )
    return broker, oms


def _journalled_reasons(tmp_path, symbol: str) -> str:
    """Every reason recorded for `symbol`, lowercased and joined."""
    path = Path(tmp_path) / "decision_journal.csv"
    if not path.exists():
        return ""
    with path.open(newline="", encoding="utf-8") as handle:
        return " | ".join(
            row["reason"].lower() for row in csv.DictReader(handle) if row["symbol"] == symbol
        )


def _quarantine(oms: OMS, symbol: str, tracked: float, broker_qty: float) -> None:
    oms.anomalies.declare(
        symbol=symbol,
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=tracked,
        broker_quantity=broker_qty,
    )


def _candidate(symbol: str, price: float) -> OrderCandidate:
    """A candidate valid enough to construct. It never reaches sizing - the
    quarantine check sits ahead of the whole risk pipeline."""
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=price,
        atr=5.0,
        win_rate=0.55,
        win_loss_ratio=1.8,
        candidate_returns=pd.Series([0.01, -0.005, 0.02]),
        stop_price=price * 0.9,
    )


@pytest.mark.asyncio
async def test_a_quarantined_symbol_refuses_new_entries(tmp_path):
    """Sized against a quantity known to be wrong, an entry is wrong."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_order(
        _candidate("CRWD", 214.42),
        equity=100_000.0,
        existing_weights={},
        existing_returns={},
    )

    assert order.status == "rejected"
    assert "position anomaly" in _journalled_reasons(tmp_path, "CRWD")


@pytest.mark.asyncio
async def test_a_quarantined_symbol_refuses_a_delever_trim(tmp_path):
    """A trim sized against a known-wrong quantity is the trim doing damage."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_exit_order("CRWD", quantity=8.0, price=214.42, reason="delever")

    assert order.status == "rejected"
    assert "de-lever trim refused" in _journalled_reasons(tmp_path, "CRWD")


@pytest.mark.asyncio
async def test_a_quarantined_symbol_still_allows_an_exit(tmp_path):
    """M56c's lesson. No gate silently suppresses the only route to selling."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_exit_order("CRWD", quantity=16.0, price=214.42, reason="signal")

    assert order.status == "pending_signoff"


@pytest.mark.asyncio
async def test_an_exit_on_a_quarantined_symbol_is_sized_from_the_broker(tmp_path):
    """The caller passes the TRACKED quantity, which is the wrong one - that is
    what being quarantined means. Selling 16 of 64 leaves three quarters of a
    position behind that nobody intended to keep."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_exit_order("CRWD", quantity=16.0, price=214.42, reason="signal")

    assert order.quantity == 64.0


@pytest.mark.asyncio
async def test_an_exit_is_refused_when_the_broker_cannot_be_read(tmp_path):
    """Exiting a known-wrong quantity on a symbol already flagged as
    untrustworthy is worse than not exiting. Recorded as a rejection with a
    reason, per M54, rather than vanishing."""
    broker, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)
    broker.fail_positions = True

    order = await oms.submit_exit_order("CRWD", quantity=16.0, price=214.42, reason="signal")

    assert order.status == "rejected"
    assert "could not read the broker" in _journalled_reasons(tmp_path, "CRWD")


@pytest.mark.asyncio
async def test_an_unquarantined_symbol_is_untouched(tmp_path):
    """The ordinary path must not pay for this."""
    _, oms = _build_exit(tmp_path, {"AMD": 7.0})

    order = await oms.submit_exit_order("AMD", quantity=7.0, price=483.36, reason="signal")

    assert order.status == "pending_signoff"
    assert order.quantity == 7.0
