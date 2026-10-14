"""Foreign holdings must stop new exposure without delaying exits."""

from __future__ import annotations

from dataclasses import replace

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.position_closer import PositionCloser
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class IdentityBroker(MockBroker):
    def __init__(self, holdings: list[Position]) -> None:
        super().__init__()
        self.holdings = holdings
        self.placed: list[Order] = []

    async def positions(self) -> list[Position]:
        return self.holdings

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order)
        return replace(order, status="transmitted", filled_quantity=0.0)


class PendingBroker(IdentityBroker):
    async def pending_identity_reason(self, symbol: str) -> str:
        return f"pending broker identity for {symbol}: unresolved stop leg"


def _oms(tmp_path, broker: IdentityBroker) -> OMS:
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")
    bus = EventBus()
    switch = KillSwitch(data_dir=tmp_path)
    engine = RiskEngine(bus, switch, settings=settings)
    return OMS(broker, engine, switch, max_order_pct_of_cash=1.0, bus=bus, settings=settings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "foreign",
    [
        Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False),
        Position("BHP.AX", 18, 60, account="DU2", con_id=1001, qat_holding=False),
        Position("BHP.AX", 18, 60, account="DU1", con_id=1001, sec_type="OPT", qat_holding=False),
        Position("BHP.AX", 18, 60, account="DU1", con_id=1001, currency="USD", qat_holding=False),
    ],
)
async def test_foreign_holding_blocks_buy_without_changing_quantity_or_placing(
    tmp_path, foreign: Position
) -> None:
    managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001, qat_holding=True)
    broker = IdentityBroker([managed, foreign])
    oms = _oms(tmp_path, broker)
    order = oms._new_pending_order("BHP.AX", "buy", 9, 60.0)

    result = await oms.sign_off(order.order_id, operator="DS")

    assert result.status == "rejected"
    assert order.quantity == 9
    assert broker.placed == []
    assert await oms._broker_quantity("BHP.AX") == 9


@pytest.mark.asyncio
async def test_foreign_holding_does_not_block_reducing_sell(tmp_path) -> None:
    managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001, qat_holding=True)
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)
    broker = IdentityBroker([managed, foreign])
    oms = _oms(tmp_path, broker)
    order = oms._new_pending_order("BHP.AX", "sell", 9, 60.0)

    result = await oms.sign_off(order.order_id, operator="DS")

    assert result.status == "transmitted"
    assert len(broker.placed) == 1


@pytest.mark.asyncio
async def test_unresolved_leg_blocks_buy_but_not_exit(tmp_path) -> None:
    broker = PendingBroker([Position("BHP.AX", 9, 60)])
    oms = _oms(tmp_path, broker)
    buy = oms._new_pending_order("BHP.AX", "buy", 9, 60.0)
    refused = await oms.sign_off(buy.order_id, "DS")
    assert refused.status == "rejected"
    assert broker.placed == []

    sell = oms._new_pending_order("BHP.AX", "sell", 9, 60.0)
    sent = await oms.sign_off(sell.order_id, "DS")
    assert sent.status == "transmitted"
    assert len(broker.placed) == 1


@pytest.mark.asyncio
async def test_reconciliation_counts_only_the_qualified_holding(tmp_path) -> None:
    managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001, qat_holding=True)
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)
    oms = _oms(tmp_path, IdentityBroker([managed, foreign]))
    oms._filled_quantities["BHP.AX"] = 9

    assert await oms.check_reconciliation() is False
    assert not oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_manual_close_sizes_only_the_qualified_holding(tmp_path) -> None:
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)
    managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001, qat_holding=True)
    broker = IdentityBroker([foreign, managed])
    oms = _oms(tmp_path, broker)
    closer = PositionCloser(oms, broker, oms.kill_switch, {})

    assert await closer._held_quantity("BHP.AX") == 9


@pytest.mark.asyncio
async def test_startup_adopts_only_the_qualified_holding(tmp_path) -> None:
    managed = Position("BHP.AX", 9, 60, account="DU1", con_id=1001, qat_holding=True)
    foreign = Position("BHP.AX", 18, 60, account="DU1", con_id=2002, qat_holding=False)
    oms = _oms(tmp_path, IdentityBroker([managed, foreign]))

    adopted = await oms.adopt_broker_positions()

    assert adopted == {"BHP.AX": 9}
