"""Every position must have a way out (spec M14).

Before M14 SwingStrategy emitted buy-only and no protective stop was ever
placed at the broker, so a position entered by it had no exit path at all
short of a human noticing. Two independent mechanisms now cover it, and both
are tested here because either one alone leaves a real hole:

* A bracket resting AT THE BROKER, which survives this process dying.
* A trend-broken exit signal from the strategy, which needs the app alive.

The bracket is the one that matters for unattended trading. The exit signal is
what closes a position the thesis has stopped supporting, which a stop cannot
know about.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_BASE = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
_SYMBOL = "AAA"


# --- The broker-side bracket --------------------------------------------------


def _build() -> tuple[SignalToOrderBridge, OMS, MockBroker]:
    # Unit-scale fixtures: a hundred shares of a $100 stock puts tens of
    # dollars at risk, so the M27 cost rail correctly refuses them as too
    # small to carry a $6-a-side commission. These tests are about sizing,
    # brackets and bridge policy, so they opt out of the rail rather than
    # inflate every number to an economically realistic one.
    settings = Settings(_env_file=None, apply_costs_in_paper=False)
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch, settings=settings)
    broker = MockBroker(seed=1)
    oms = OMS(broker, risk_engine, switch, max_order_notional=1_000_000.0)
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    return bridge, oms, broker


async def _feed(bridge: SignalToOrderBridge, n: int = 30) -> None:
    for step in range(n):
        await bridge._on_market_data(
            MarketDataEvent(
                symbol=_SYMBOL,
                price=100.0 + step * 0.5,
                volume=1000,
                ts=_BASE + timedelta(seconds=step * 60),
            )
        )


@pytest.mark.asyncio
async def test_a_strategy_stop_becomes_a_bracket_on_the_order():
    bridge, oms, _ = _build()
    await _feed(bridge)

    await bridge._on_signal(
        SignalEvent(
            symbol=_SYMBOL,
            side="buy",
            conviction=1.0,
            strategy="swing",
            meta={"stop_price": 95.0, "target_price": 125.0},
        )
    )

    order = oms.orders()[0]
    assert order.stop_price == 95.0
    assert order.take_profit_price == 125.0
    assert order.is_bracket is True


@pytest.mark.asyncio
async def test_the_protective_stop_rests_at_the_broker_after_sign_off():
    """The property that matters for unattended trading: the stop outlives
    this process because the broker is holding it, not the app."""
    bridge, oms, broker = _build()
    await _feed(bridge)
    await bridge._on_signal(
        SignalEvent(
            symbol=_SYMBOL,
            side="buy",
            conviction=1.0,
            strategy="swing",
            meta={"stop_price": 95.0, "target_price": 125.0},
        )
    )

    await oms.sign_off(oms.orders()[0].order_id, operator="tester")

    assert broker.resting_stop(_SYMBOL) == 95.0
    assert broker.resting_target(_SYMBOL) == 125.0


@pytest.mark.asyncio
async def test_closing_the_position_clears_its_resting_legs():
    """A stale stop against a position that no longer exists would be a live
    order nobody intended."""
    bridge, oms, broker = _build()
    await _feed(bridge)
    await bridge._on_signal(
        SignalEvent(
            symbol=_SYMBOL,
            side="buy",
            conviction=1.0,
            strategy="swing",
            meta={"stop_price": 95.0, "target_price": 125.0},
        )
    )
    await oms.sign_off(oms.orders()[0].order_id, operator="tester")
    assert broker.resting_stop(_SYMBOL) == 95.0

    exit_order = await oms.submit_exit_order(_SYMBOL, quantity=1.0, price=100.0)
    await oms.sign_off(exit_order.order_id, operator="tester")

    assert broker.resting_stop(_SYMBOL) is None


@pytest.mark.asyncio
async def test_a_signal_without_a_stop_still_gets_a_protective_bracket():
    """Not every strategy proposes protective levels - but every position still
    reaches the broker protected, using the ATR stop the sizer already
    computed. A stop that exists only as a sizing assumption protects nothing,
    and an unbracketed position is exactly the hole M14 set out to close."""
    bridge, oms, _ = _build()
    await _feed(bridge)

    await bridge._on_signal(
        SignalEvent(symbol=_SYMBOL, side="buy", conviction=1.0, strategy="momentum", meta={})
    )

    order = oms.orders()[0]
    assert order.status == "pending_signoff"
    assert order.is_bracket is True
    assert order.stop_price is not None
    assert order.stop_price < (order.reference_price or 0.0)


@pytest.mark.asyncio
async def test_a_strategy_stop_takes_precedence_over_the_atr_fallback():
    bridge, oms, _ = _build()
    await _feed(bridge)

    await bridge._on_signal(
        SignalEvent(
            symbol=_SYMBOL,
            side="buy",
            conviction=1.0,
            strategy="swing",
            meta={"stop_price": 42.0, "target_price": 200.0},
        )
    )

    assert oms.orders()[0].stop_price == 42.0


@pytest.mark.asyncio
async def test_junk_in_signal_meta_is_ignored_rather_than_raising():
    """meta is an untyped dict any strategy can put anything in, and it sits on
    the order path."""
    bridge, oms, _ = _build()
    await _feed(bridge)

    await bridge._on_signal(
        SignalEvent(
            symbol=_SYMBOL,
            side="buy",
            conviction=1.0,
            strategy="swing",
            meta={"stop_price": "not a number", "target_price": None},
        )
    )

    order = oms.orders()[0]
    assert order.status == "pending_signoff"
    # The junk values are ignored, so the ATR fallback supplies the stop rather
    # than the order going out unprotected.
    assert order.stop_price is not None
    assert order.stop_price != "not a number"


# --- Sizing and the bracket must agree ----------------------------------------


def _candidate(stop_price: float | None) -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol=_SYMBOL,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
        stop_price=stop_price,
    )


def test_sizing_uses_the_strategy_stop_when_one_is_supplied():
    """Sizing against one stop while resting a different one at the broker
    would make the per-trade risk limit describe a trade nobody placed."""
    settings = Settings(_env_file=None, apply_costs_in_paper=False)
    engine = RiskEngine(EventBus(), KillSwitch(), settings=settings)

    wide = engine.evaluate_order(
        _candidate(stop_price=80.0), 100_000.0, {}, {}, available_cash=1_000_000.0
    )
    tight = engine.evaluate_order(
        _candidate(stop_price=99.0), 100_000.0, {}, {}, available_cash=1_000_000.0
    )

    assert wide.inputs["stop_source"] == "strategy"
    assert wide.inputs["stop_distance"] == pytest.approx(20.0)
    assert tight.inputs["stop_distance"] == pytest.approx(1.0)
    # A wider stop means more risk per share, so fewer shares for the same
    # dollar budget.
    assert wide.final_shares < tight.final_shares


def test_sizing_falls_back_to_the_atr_stop_without_one():
    settings = Settings(_env_file=None, apply_costs_in_paper=False)
    engine = RiskEngine(EventBus(), KillSwitch(), settings=settings)

    decision = engine.evaluate_order(
        _candidate(stop_price=None), 100_000.0, {}, {}, available_cash=1_000_000.0
    )

    assert decision.inputs["stop_source"] == "atr_multiple"
    assert decision.inputs["stop_distance"] == pytest.approx(settings.atr_stop_multiple * 2.0)


def test_a_stop_above_the_entry_is_rejected_as_a_stop_source():
    """A 'stop' that is not below the entry is not a stop; falling back is
    safer than sizing off a negative risk-per-share."""
    settings = Settings(_env_file=None, apply_costs_in_paper=False)
    engine = RiskEngine(EventBus(), KillSwitch(), settings=settings)

    decision = engine.evaluate_order(
        _candidate(stop_price=150.0), 100_000.0, {}, {}, available_cash=1_000_000.0
    )

    assert decision.inputs["stop_source"] == "atr_multiple"
