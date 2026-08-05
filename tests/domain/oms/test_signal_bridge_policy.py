"""Signal -> order policy (spec M11).

Regressions for the field failure where deploying a strategy produced ~75,000
blotter rows: strategies re-emit a signal on every tick while their condition
holds, and the bridge treated each emission as a fresh instruction. It also
never consulted positions, so "sell" fired for symbols with no holding.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.events import MarketDataEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_SYMBOL = "AAA"


def _build(
    journal: DecisionJournal | None = None, **settings_kwargs: object
) -> tuple[SignalToOrderBridge, OMS, MockBroker]:
    # Unit-scale fixtures: a hundred shares of a $100 stock puts tens of
    # dollars at risk, so the M27 cost rail correctly refuses them as too
    # small to carry a $6-a-side commission. These tests are about sizing,
    # brackets and bridge policy, so they opt out of the rail rather than
    # inflate every number to an economically realistic one.
    settings_kwargs.setdefault("apply_costs_in_paper", False)
    settings = Settings(_env_file=None, data_dir=tempfile.mkdtemp(), **settings_kwargs)  # type: ignore[arg-type]
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch, settings=settings)
    broker = MockBroker(seed=1)
    oms = OMS(broker, risk_engine, switch, max_order_notional=1_000_000.0, journal=journal)
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    return bridge, oms, broker


async def _feed_bars(bridge: SignalToOrderBridge, symbol: str = _SYMBOL, n: int = 30) -> None:
    """Feeds n *bars*, not n ticks.

    Ticks are aggregated into fixed-interval OHLC bars (M14), so timestamps
    have to advance past a bar boundary for each one to become its own bar -
    otherwise thirty ticks in the same minute are a single bar and the bridge
    correctly declines to size a stop from it.
    """
    start = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
    for step in range(n):
        await bridge._on_market_data(
            MarketDataEvent(
                symbol=symbol,
                price=100.0 + step * 0.5,
                volume=1000,
                ts=start + timedelta(seconds=step * 60),
            )
        )


def _signal(side: str, symbol: str = _SYMBOL) -> SignalEvent:
    return SignalEvent(symbol=symbol, side=side, conviction=1.0, strategy="test")  # type: ignore[arg-type]


async def test_a_broker_failure_while_sizing_refuses_the_signal_rather_than_throwing():
    """M54, and it happened live on 6 August.

    Alpaca returned HTTP 500 for ninety seconds. The account fetch in the sizing
    path sat outside every guard, so the exception escaped through the event bus
    and the signal vanished - no order, no refusal, no journal entry, nothing on
    any screen but a stack trace.

    M38 made this exact argument about the risk evaluation and wrapped it. This
    call is upstream of that guard and was missed. A rail that refuses is
    visible and auditable; a rail that throws is neither."""
    journal = DecisionJournal(tempfile.mkdtemp())
    bridge, oms, broker = _build(journal=journal)
    await _feed_bars(bridge)

    async def _boom():
        raise RuntimeError("500 Internal Server Error")

    broker.account = _boom  # type: ignore[assignment]

    # Must not raise: the bus would log "EventBus handler failed" and move on.
    await bridge._on_signal(_signal("buy"))

    orders = oms.orders()
    assert len(orders) == 1, "the signal must leave a record, not a gap"
    assert orders[0].status == "rejected"
    assert orders[0].symbol == _SYMBOL
    # And the reason reaches the audit trail, which is the whole point: "why
    # did nothing happen" must be answerable from the record.
    reasons = [row["reason"] for row in journal.entries()]
    assert any("account unavailable" in r for r in reasons), reasons


async def test_the_signal_is_reconsidered_once_the_broker_recovers():
    """A refusal, not a retry loop - the next tick re-emits the signal if the
    condition still holds, and inventing a retry here would hide an outage
    rather than record it."""
    bridge, oms, broker = _build()
    await _feed_bars(bridge)
    original = broker.account

    async def _boom():
        raise RuntimeError("500 Internal Server Error")

    broker.account = _boom  # type: ignore[assignment]
    await bridge._on_signal(_signal("buy"))
    assert oms.orders()[0].status == "rejected"

    broker.account = original  # type: ignore[assignment]
    await bridge._on_signal(_signal("buy"))

    assert any(o.status == "pending_signoff" for o in oms.orders())


async def test_repeated_identical_buy_signal_creates_only_one_order():
    bridge, oms, _broker = _build()
    await _feed_bars(bridge)

    for _ in range(50):
        await bridge._on_signal(_signal("buy"))

    assert len(oms.orders()) == 1
    assert oms.orders()[0].status == "pending_signoff"


async def test_no_further_orders_once_the_position_is_held():
    bridge, oms, _broker = _build()
    await _feed_bars(bridge)
    await bridge._on_signal(_signal("buy"))
    await oms.sign_off(oms.orders()[0].order_id, operator="alice")

    for _ in range(20):
        await bridge._on_signal(_signal("buy"))

    # Only the original (now filled) order - re-signalling must not pyramid.
    assert len(oms.orders()) == 1


async def test_sell_signal_with_no_holding_is_dropped_when_long_only():
    bridge, oms, _broker = _build()
    await _feed_bars(bridge)

    for _ in range(20):
        await bridge._on_signal(_signal("sell"))

    assert oms.orders() == []


async def test_sell_signal_closes_exactly_the_held_quantity():
    bridge, oms, broker = _build()
    await _feed_bars(bridge)
    await bridge._on_signal(_signal("buy"))
    await oms.sign_off(oms.orders()[0].order_id, operator="alice")
    held = next(p.quantity for p in await broker.positions() if p.symbol == _SYMBOL)

    await bridge._on_signal(_signal("sell"))

    exits = [o for o in oms.orders() if o.side == "sell"]
    assert len(exits) == 1
    assert exits[0].quantity == held
    assert exits[0].status == "pending_signoff"  # still needs human sign-off


async def test_exit_order_is_not_resized_by_the_entry_sizer():
    """The entry sizer would produce an arbitrary quantity unrelated to the
    holding; an exit must close what is actually held."""
    bridge, oms, broker = _build()
    await _feed_bars(bridge)
    await bridge._on_signal(_signal("buy"))
    entry = oms.orders()[0]
    await oms.sign_off(entry.order_id, operator="alice")
    held = next(p.quantity for p in await broker.positions() if p.symbol == _SYMBOL)

    await bridge._on_signal(_signal("sell"))

    exit_order = next(o for o in oms.orders() if o.side == "sell")
    assert exit_order.quantity == held == entry.quantity


async def test_short_selling_can_be_explicitly_enabled():
    bridge, oms, _broker = _build(allow_short_selling=True)
    await _feed_bars(bridge)

    await bridge._on_signal(_signal("sell"))

    shorts = [o for o in oms.orders() if o.side == "sell"]
    assert len(shorts) == 1


async def test_a_pending_order_suppresses_further_signals_for_that_symbol():
    bridge, oms, _broker = _build()
    await _feed_bars(bridge)
    await _feed_bars(bridge, symbol="BBB")

    await bridge._on_signal(_signal("buy"))
    await bridge._on_signal(_signal("buy"))
    await bridge._on_signal(_signal("buy", symbol="BBB"))

    # One per symbol - a pending order blocks duplicates for its own symbol
    # without blocking other symbols.
    assert {o.symbol for o in oms.orders()} == {"AAA", "BBB"}
    assert len(oms.orders()) == 2


@pytest.mark.parametrize("side", ["buy", "sell"])
async def test_exit_and_entry_both_still_require_sign_off(side):
    """The M11 policy changes must not weaken the core invariant."""
    bridge, oms, broker = _build()
    await _feed_bars(bridge)
    if side == "sell":
        await bridge._on_signal(_signal("buy"))
        await oms.sign_off(oms.orders()[0].order_id, operator="alice")

    calls = 0
    original = broker.place_order

    async def counting(order):
        nonlocal calls
        calls += 1
        return await original(order)

    broker.place_order = counting  # type: ignore[method-assign]
    await bridge._on_signal(_signal(side))

    assert calls == 0
    assert any(o.status == "pending_signoff" for o in oms.orders())
