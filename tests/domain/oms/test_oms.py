from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


def _oms(
    max_order_notional: float = 1_000_000.0, **settings_overrides: object
) -> tuple[OMS, KillSwitch]:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None, **settings_overrides)  # type: ignore[arg-type]
    engine = RiskEngine(bus, switch, settings=settings)
    broker = MockBroker(seed=1)
    oms = OMS(broker, engine, switch, max_order_notional=max_order_notional)
    return oms, switch


@pytest.mark.asyncio
async def test_submit_order_creates_pending_signoff_not_transmitted():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "pending_signoff"
    assert order.filled_price is None


@pytest.mark.asyncio
async def test_sign_off_transmits_and_fills():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    filled = await oms.sign_off(order.order_id, operator="alice")

    assert filled.status == "filled"
    assert filled.filled_price is not None


@pytest.mark.asyncio
async def test_sign_off_on_non_pending_order_raises():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")

    with pytest.raises(ValueError):
        await oms.sign_off(order.order_id, operator="alice")


@pytest.mark.asyncio
async def test_kill_switch_blocks_submission():
    oms, switch = _oms()
    switch.trigger_manual("test")

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_kill_switch_tripped_after_submit_blocks_signoff():
    oms, switch = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    switch.trigger_manual("test")

    result = await oms.sign_off(order.order_id, operator="alice")

    assert result.status == "rejected"


@pytest.mark.asyncio
async def test_symbol_not_in_allow_list_is_rejected():
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch)
    broker = MockBroker(seed=1)
    oms = OMS(broker, engine, switch, symbol_allow_list={"BBB"})

    order = await oms.submit_order(_candidate("AAA"), 100_000.0, {}, {})

    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_a_cap_too_small_for_one_share_still_rejects():
    """The one refusal a trim cannot rescue.

    This test used to be called "exceeding max notional is rejected", and it
    kept passing after the rail began TRIMMING on 24 August 2026 - but only
    because a $1 cap cannot cover a single share at any price, so it took the
    residual refusal path rather than the one its name described. Renamed to
    what it actually proves.
    """
    oms, _ = _oms(max_order_notional=1.0, per_trade_risk_pct=0.02)

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_an_order_over_the_cap_is_trimmed_to_it_not_rejected():
    """The behaviour change itself, and the reason for it.

    A limit that refuses makes the trade disappear; a limit that trims makes it
    the size the limit believes in. The single-name cap has trimmed since M31c
    for exactly this reason, and on 24 August this rail refused the first real
    ASX entry signal this system ever produced, 48 times in a row, rather than
    placing a smaller one.
    """
    cap = 5_000.0
    oms, _ = _oms(max_order_notional=cap, per_trade_risk_pct=0.02)

    order = await oms.submit_order(_candidate(), 1_000_000.0, {}, {})

    assert order.status != "rejected", "the cap refused instead of trimming"
    assert order.quantity >= 1
    assert order.quantity * _candidate().price <= cap, "the trim did not respect the cap"


@pytest.mark.asyncio
async def test_trimming_only_ever_reduces_the_order():
    """A trim must not be able to size UP. The stop is per-share and unchanged,
    so fewer shares is strictly less at stake than the sizer approved - that is
    what makes trimming safe to do silently to a risk figure."""
    generous, _ = _oms(max_order_notional=10_000_000.0, per_trade_risk_pct=0.02)
    tight, _ = _oms(max_order_notional=5_000.0, per_trade_risk_pct=0.02)

    untrimmed = await generous.submit_order(_candidate(), 1_000_000.0, {}, {})
    trimmed = await tight.submit_order(_candidate(), 1_000_000.0, {}, {})

    assert trimmed.quantity < untrimmed.quantity


@pytest.mark.asyncio
async def test_reject_order_from_pending_signoff():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    rejected = await oms.reject_order(order.order_id, operator="alice", reason="changed my mind")

    assert rejected.status == "rejected"


@pytest.mark.asyncio
async def test_cancel_filled_order_is_a_noop():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    filled = await oms.sign_off(order.order_id, operator="alice")
    assert filled.status == "filled"

    result = await oms.cancel_order(order.order_id)

    assert result.status == "filled"


@pytest.mark.asyncio
async def test_cancel_pending_order_marks_cancelled_without_broker_call():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    cancelled = await oms.cancel_order(order.order_id)

    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_reconciliation_matches_after_normal_fill():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")

    assert await oms.check_reconciliation() is False


@pytest.mark.asyncio
async def test_reconciliation_mismatch_trips_kill_switch():
    oms, switch = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")

    oms._filled_quantities["AAA"] = 999.0  # simulate app-state/broker drift

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_submit_order_rejected_by_risk_engine_no_edge():
    oms, _ = _oms()
    no_edge_candidate = OrderCandidate(
        symbol="AAA",
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.2,
        win_loss_ratio=1.0,
        candidate_returns=_flat_returns(),
    )

    order = await oms.submit_order(no_edge_candidate, 100_000.0, {}, {})

    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_reject_order_from_terminal_status_raises():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")  # now "filled" - terminal

    with pytest.raises(ValueError):
        await oms.reject_order(order.order_id, operator="alice", reason="too late")


@pytest.mark.asyncio
async def test_cancel_transmitted_order_calls_broker_cancel():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, operator="alice")  # registers the order with the broker
    # simulate the in-flight window a real broker has between "transmitted"
    # and a fill confirmation arriving (MockBroker fills synchronously, so
    # this state is otherwise instantaneous and unreachable from the outside)
    oms._orders[order.order_id].status = "transmitted"

    cancelled = await oms.cancel_order(order.order_id)

    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_get_order_returns_tracked_order():
    oms, _ = _oms()
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert oms.get_order(order.order_id).order_id == order.order_id
