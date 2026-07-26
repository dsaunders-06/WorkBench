"""De-levering sweep (spec M15).

Blocking new risk only unwinds a breach passively, as stops hit. The reference
implementation measured that at roughly 6 points a week against readings of
36.8% and 30.4% versus a 5% cap. This is the active half - and it is off by
default, because it SELLS.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.delever import DeleverSweep
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.governor import PortfolioGovernor
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, positions: dict[str, float], equity: float = 100_000.0) -> None:
        self._positions = dict(positions)
        self.equity = equity
        self.placed: list[Order] = []

    async def positions(self) -> list[Position]:
        return [Position(symbol=s, quantity=q, avg_price=100.0) for s, q in self._positions.items()]

    async def account(self) -> AccountSummary:
        return AccountSummary(
            net_liquidation=self.equity, cash=self.equity, buying_power=self.equity
        )

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order)
        order.status = "filled"
        return order

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        raise NotImplementedError

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError


def _build(positions: dict[str, float], stops: dict[str, float] | None = None, **overrides):
    settings = Settings(_env_file=None, max_aggregate_risk_at_stop_pct=0.05, **overrides)
    switch = KillSwitch()
    broker = _Broker(positions)
    engine = RiskEngine(EventBus(), switch, settings=settings)
    oms = OMS(broker, engine, switch, max_order_notional=10_000_000.0)
    if stops:
        oms._position_stops.update(stops)
    sweep = DeleverSweep(oms, PortfolioGovernor(settings), settings=settings, poll_seconds=3600.0)
    return broker, oms, sweep


@pytest.mark.asyncio
async def test_no_trim_when_within_cap():
    _, oms, sweep = _build({"A": 100.0}, {"A": 99.0}, delever_sweep_enabled=True)
    assert await sweep.poll() == []
    assert oms.orders() == []


@pytest.mark.asyncio
async def test_an_empty_account_is_a_no_op():
    _, _, sweep = _build({}, delever_sweep_enabled=True)
    assert await sweep.poll() == []


@pytest.mark.asyncio
async def test_the_sweep_is_off_by_default():
    """It sells. A rail that sells uninvited is a bigger delegation than one
    that declines to buy, so enabling it is a deliberate act."""
    assert Settings(_env_file=None).delever_sweep_enabled is False

    _, oms, sweep = _build({"A": 2000.0}, {"A": 95.0})
    trimmed = await sweep.poll()

    assert trimmed == []
    assert oms.orders() == [], "disabled means no orders, not quiet orders"
    assert sweep.last_fraction > 0, "the breach is still measured"


@pytest.mark.asyncio
async def test_a_breach_is_reported_even_when_the_sweep_is_disabled(caplog):
    """'We are over cap and doing nothing about it' must be a visible state."""
    _, _, sweep = _build({"A": 2000.0}, {"A": 95.0})

    with caplog.at_level("WARNING"):
        await sweep.poll()

    assert "over the" in caplog.text
    assert "sweep is disabled" in caplog.text


@pytest.mark.asyncio
async def test_an_enabled_sweep_trims_every_position_proportionally():
    _, oms, sweep = _build(
        {"A": 1000.0, "B": 1500.0},
        {"A": 95.0, "B": 90.0},
        delever_sweep_enabled=True,
    )

    trimmed = await sweep.poll()

    assert sorted(trimmed) == ["A", "B"]
    orders = {o.symbol: o for o in oms.orders()}
    assert set(orders) == {"A", "B"}
    assert all(o.side == "sell" for o in orders.values())
    # Same proportion of each holding, which is what makes one fraction hit the
    # aggregate target exactly.
    ratio_a = orders["A"].quantity / 1000.0
    ratio_b = orders["B"].quantity / 1500.0
    assert ratio_a == pytest.approx(ratio_b, rel=0.01)


@pytest.mark.asyncio
async def test_trims_go_through_the_sign_off_gate_like_any_other_order():
    """The sweep decides what to trim, never whether it transmits."""
    broker, oms, sweep = _build({"A": 2000.0}, {"A": 95.0}, delever_sweep_enabled=True)

    await sweep.poll()

    assert broker.placed == [], "nothing may reach the broker without sign-off"
    assert all(o.status == "pending_signoff" for o in oms.orders())


@pytest.mark.asyncio
async def test_the_trim_quantity_is_floored_not_rounded():
    """Trimming slightly less than target is a smaller error than selling more
    of a position than intended."""
    _, oms, sweep = _build({"A": 1001.0}, {"A": 95.0}, delever_sweep_enabled=True)

    await sweep.poll()

    quantity = oms.orders()[0].quantity
    assert quantity == float(int(quantity))


@pytest.mark.asyncio
async def test_a_position_too_small_to_trim_is_skipped_not_zero_ordered():
    _, oms, sweep = _build(
        {"BIG": 2000.0, "TINY": 1.0},
        {"BIG": 95.0, "TINY": 99.99},
        delever_sweep_enabled=True,
    )

    await sweep.poll()

    assert all(o.quantity > 0 for o in oms.orders())
