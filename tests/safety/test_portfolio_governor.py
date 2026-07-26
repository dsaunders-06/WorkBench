"""Portfolio-level exposure caps (spec M15).

Per-trade risk limits bound one trade and say nothing about ten trades each
individually within budget. These cover the three things that closes: an
aggregate risk-at-stop cap, a concurrent-position count, and - the one that
actually bit in the reference implementation - counting pending orders as
committed exposure.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order, Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.governor import PortfolioGovernor
from qat.domain.risk_engine.kill_switch import KillSwitch

EQUITY = 100_000.0


def _settings(**overrides) -> Settings:
    base = {"_env_file": None, "max_aggregate_risk_at_stop_pct": 0.05}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _position(symbol: str, quantity: float = 100.0, price: float = 100.0) -> Position:
    return Position(symbol=symbol, quantity=quantity, avg_price=price)


def _pending(
    symbol: str, quantity: float = 100.0, price: float = 100.0, stop: float | None = 95.0
) -> Order:
    return Order(
        symbol=symbol,
        side="buy",
        quantity=quantity,
        order_id=f"pending-{symbol}",
        status="pending_signoff",
        reference_price=price,
        stop_price=stop,
    )


# --- Measurement --------------------------------------------------------------


def test_risk_at_stop_is_the_sum_of_each_positions_risk():
    governor = PortfolioGovernor(_settings())
    positions = [_position("A"), _position("B")]
    stops = {"A": 95.0, "B": 90.0}

    snap = governor.snapshot(positions, stops, EQUITY)

    # A: 100 x (100-95) = 500; B: 100 x (100-90) = 1000
    assert snap.risk_at_stop_dollars == pytest.approx(1500.0)
    assert snap.risk_at_stop_pct == pytest.approx(0.015)
    assert snap.position_count == 2


def test_a_position_with_no_known_stop_risks_its_whole_value():
    """Unknown protection is treated as no protection. Assuming a stop exists
    would understate risk by exactly the amount that is unknown - which is the
    situation for every position adopted from a previous session."""
    governor = PortfolioGovernor(_settings())
    snap = governor.snapshot([_position("A")], stops={}, equity=EQUITY)
    assert snap.risk_at_stop_dollars == pytest.approx(10_000.0)


def test_a_stop_above_the_price_is_not_treated_as_protection():
    governor = PortfolioGovernor(_settings())
    snap = governor.snapshot([_position("A")], stops={"A": 150.0}, equity=EQUITY)
    assert snap.risk_at_stop_dollars == pytest.approx(10_000.0)


def test_pending_buys_count_as_committed_exposure():
    """The bug this exists to prevent: a governor that only sees filled
    positions approves a tenth candidate while nine sit in the blotter."""
    governor = PortfolioGovernor(_settings())
    with_pending = governor.snapshot([], {}, EQUITY, pending_orders=[_pending("A")])
    assert with_pending.position_count == 1
    assert with_pending.risk_at_stop_dollars == pytest.approx(500.0)


def test_pending_sells_do_not_create_headroom_before_they_fill():
    """Counting a reduction that has not happened would let new risk in against
    headroom that does not exist yet."""
    governor = PortfolioGovernor(_settings())
    sell = Order(
        symbol="A",
        side="sell",
        quantity=100.0,
        order_id="x",
        status="pending_signoff",
        reference_price=100.0,
    )
    snap = governor.snapshot([_position("A")], {"A": 95.0}, EQUITY, pending_orders=[sell])
    assert snap.risk_at_stop_dollars == pytest.approx(500.0)


def test_a_symbol_held_and_pending_counts_as_one_position():
    governor = PortfolioGovernor(_settings())
    snap = governor.snapshot([_position("A")], {"A": 95.0}, EQUITY, pending_orders=[_pending("A")])
    assert snap.position_count == 1


# --- Gating -------------------------------------------------------------------


def test_a_candidate_within_every_cap_is_allowed():
    governor = PortfolioGovernor(_settings())
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=[],
        stops={},
        equity=EQUITY,
    )
    assert decision.allowed is True
    assert decision.max_shares == 10.0


def test_the_position_count_cap_blocks_a_new_name():
    governor = PortfolioGovernor(_settings(max_concurrent_positions=2))
    positions = [_position("A"), _position("B")]
    decision = governor.evaluate(
        "C",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 99.0, "B": 99.0},
        equity=EQUITY,
    )
    assert decision.allowed is False
    assert "position limit" in decision.reason


def test_the_position_count_cap_does_not_block_adding_to_a_held_name():
    """The cap bounds how thinly the portfolio is spread, not position size -
    that is the single-name concentration check's job."""
    governor = PortfolioGovernor(_settings(max_concurrent_positions=2))
    positions = [_position("A"), _position("B")]
    decision = governor.evaluate(
        "A",
        price=100.0,
        proposed_shares=10.0,
        stop_price=99.0,
        positions=positions,
        stops={"A": 99.0, "B": 99.0},
        equity=EQUITY,
    )
    assert decision.allowed is True


def test_an_over_cap_portfolio_blocks_new_risk_entirely():
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=200.0)]  # no stop -> 20,000 at risk
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={},
        equity=EQUITY,
    )
    assert decision.allowed is False
    assert "aggregate risk-at-stop" in decision.reason


def test_a_candidate_is_trimmed_to_the_remaining_headroom():
    """Graceful degradation: trim to what fits rather than rejecting outright."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=800.0)]  # 800 x 5 = 4,000 of the 5,000 cap
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=1000.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 95.0},
        equity=EQUITY,
    )
    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(200.0)  # 1,000 headroom / 5 per share
    assert "trimmed" in decision.reason


def test_headroom_too_small_for_one_share_is_rejected():
    """999.5 x 5 = 4,997.50 of the 5,000 cap, leaving $2.50 - half a share's
    worth of risk. A fractional share of headroom is not a trade."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=999.5)]
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 95.0},
        equity=EQUITY,
    )
    assert decision.allowed is False
    assert "headroom" in decision.reason


def test_exactly_one_share_of_headroom_is_allowed_and_trimmed_to_it():
    """The boundary the previous test sits just past."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=999.0)]
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=positions,
        stops={"A": 95.0},
        equity=EQUITY,
    )
    assert decision.allowed is True
    assert decision.max_shares == pytest.approx(1.0)


@pytest.mark.parametrize("equity", [0.0, -5.0])
def test_non_positive_equity_is_rejected(equity):
    governor = PortfolioGovernor(_settings())
    decision = governor.evaluate(
        "NEW",
        price=100.0,
        proposed_shares=10.0,
        stop_price=95.0,
        positions=[],
        stops={},
        equity=equity,
    )
    assert decision.allowed is False


# --- De-levering --------------------------------------------------------------


def test_no_delever_when_within_cap():
    governor = PortfolioGovernor(_settings())
    assert governor.delever_fraction([_position("A")], {"A": 99.0}, EQUITY) == 0.0


def test_the_delever_fraction_lands_under_the_cap_not_on_it():
    """Landing exactly on the boundary would re-trigger the sweep from ordinary
    price movement alone on the next check."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=2000.0)]  # 2000 x 5 = 10,000 vs a 5,000 cap
    stops = {"A": 95.0}

    fraction = governor.delever_fraction(positions, stops, EQUITY)

    assert 0.0 < fraction < 1.0
    remaining = [_position("A", quantity=2000.0 * (1 - fraction))]
    after = governor.snapshot(remaining, stops, EQUITY)
    assert after.risk_at_stop_pct < 0.05
    assert after.risk_at_stop_pct == pytest.approx(0.05 * 0.9, rel=1e-6)


def test_proportional_trimming_scales_the_whole_sum_by_the_same_fraction():
    """The reason a proportional trim needs no ranking: aggregate risk is a
    linear sum, so one fraction hits the target exactly."""
    governor = PortfolioGovernor(_settings())
    positions = [_position("A", quantity=1000.0), _position("B", quantity=1500.0)]
    stops = {"A": 95.0, "B": 90.0}

    fraction = governor.delever_fraction(positions, stops, EQUITY)
    trimmed = [
        _position("A", quantity=1000.0 * (1 - fraction)),
        _position("B", quantity=1500.0 * (1 - fraction)),
    ]

    after = governor.snapshot(trimmed, stops, EQUITY)
    assert after.risk_at_stop_pct == pytest.approx(0.05 * 0.9, rel=1e-6)


# --- Integration through the risk engine --------------------------------------


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
    )


@pytest.mark.asyncio
async def test_the_governor_gates_orders_through_the_oms_path():
    """OMS supplies the portfolio state itself, so no caller can bypass the cap
    by omitting an argument - the same reasoning as the cash check."""
    settings = _settings(max_concurrent_positions=3)
    engine = RiskEngine(EventBus(), KillSwitch(), settings=settings)
    oms = OMS(MockBroker(seed=1), engine, engine.kill_switch, max_order_notional=1_000_000.0)

    accepted = []
    for i in range(12):
        order = await oms.submit_order(_candidate(f"S{i}"), EQUITY, {}, {})
        if order.status == "pending_signoff":
            accepted.append(order)

    assert len(accepted) <= 3, "the position cap must bound pending orders too"


@pytest.mark.asyncio
async def test_every_approved_buy_carries_a_protective_stop():
    """A stop that exists only as a sizing assumption protects nothing - so the
    sizing stop is attached as a real bracket when the strategy proposes none."""
    engine = RiskEngine(EventBus(), KillSwitch(), settings=_settings())
    oms = OMS(MockBroker(seed=1), engine, engine.kill_switch, max_order_notional=1_000_000.0)

    order = await oms.submit_order(_candidate(), EQUITY, {}, {})

    assert order.status == "pending_signoff"
    assert order.stop_price is not None
    assert order.stop_price < 100.0
    assert order.is_bracket is True
