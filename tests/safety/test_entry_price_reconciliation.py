"""The entry record must hold what we PAID, not what we asked for (M65).

`OMS._announce_fill` publishes when an order reaches "filled" OR "transmitted",
taking `order.filled_price or order.reference_price`. At transmit there is no
fill price, so it publishes the REFERENCE - and `_on_fill` stores that with
`setdefault`, so the genuine fill can never replace it. Nothing corrected it
afterwards: an entry this app transmitted sits in `_broker_order_ids`, so
`absorb_broker_fills` skips it by design.

Measured on the live book: 8 of 10 positions recorded a price that differs from
what the broker charged, AMD by 141 bps. `restore_open_lots` passes
`entry.price` as the lot's cost basis, so realised P&L and the R-multiple
DENOMINATOR - R is (exit - entry) / (entry - stop) - are both wrong by that
drift, and both feed the promotion gate.

The fix asks the broker, which is the authority on what was paid, exactly as it
is the authority on what is held. That also heals the records already written.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge, _Entry
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, positions: dict[str, tuple[float, float]]) -> None:
        # symbol -> (quantity, avg_entry_price)
        self._positions = dict(positions)
        self.fail = False

    async def positions(self) -> list[Position]:
        if self.fail:
            raise ConnectionError("broker unreachable")
        return [
            Position(symbol=symbol, quantity=qty, avg_price=price)
            for symbol, (qty, price) in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since):
        return []


def _bridge(tmp_path, positions: dict[str, tuple[float, float]]):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings)
    return broker, oms, bridge


def _entry(price: float, stop: float = 405.55) -> _Entry:
    return _Entry(
        opened_at=datetime(2026, 8, 4, tzinfo=UTC),
        price=price,
        stop_price=stop,
        target_price=None,
        strategy="swing",
    )


@pytest.mark.asyncio
async def test_a_recorded_price_is_corrected_to_what_the_broker_charged(tmp_path):
    """The live case: AMD sized against 503.16 and filled at 510.27."""
    _, _, bridge = _bridge(tmp_path, {"AMD": (7.0, 510.267)})
    bridge._entries["AMD"] = _entry(503.16)

    corrected = await bridge.reconcile_entry_prices()

    assert corrected == ["AMD"]
    assert bridge._entries["AMD"].price == pytest.approx(510.267)


@pytest.mark.asyncio
async def test_the_stop_and_the_open_date_are_left_alone(tmp_path):
    """Only the price was wrong. The stop is the level the risk budget was
    spent on and re-arming reads it; the open date drives the churn rails."""
    _, _, bridge = _bridge(tmp_path, {"AMD": (7.0, 510.267)})
    bridge._entries["AMD"] = _entry(503.16, stop=405.55)

    await bridge.reconcile_entry_prices()

    assert bridge._entries["AMD"].stop_price == 405.55
    assert bridge._entries["AMD"].opened_at == datetime(2026, 8, 4, tzinfo=UTC)
    assert bridge._entries["AMD"].strategy == "swing"


@pytest.mark.asyncio
async def test_a_matching_price_is_left_alone_and_not_reported(tmp_path):
    """The quiet path stays quiet - CSCO drifted 0.9 bps and needs no
    correction. A log line per position per startup would be noise."""
    _, _, bridge = _bridge(tmp_path, {"CSCO": (44.0, 114.39)})
    bridge._entries["CSCO"] = _entry(114.39, stop=105.56)

    assert await bridge.reconcile_entry_prices() == []


@pytest.mark.asyncio
async def test_a_quarantined_position_is_never_corrected(tmp_path):
    """A corporate action changes avg_entry_price legitimately - a 2-for-1
    split halves it - so 'correcting' the record to the post-split figure would
    silently rewrite the basis of a position M60 exists to stop anything
    touching."""
    _, oms, bridge = _bridge(tmp_path, {"AMD": (14.0, 255.13)})
    bridge._entries["AMD"] = _entry(503.16)
    oms.anomalies.declare(
        symbol="AMD",
        reason="2-for-1 split",
        declared_by="operator",
        tracked_quantity=7.0,
        broker_quantity=14.0,
    )

    assert await bridge.reconcile_entry_prices() == []
    assert bridge._entries["AMD"].price == pytest.approx(503.16)


@pytest.mark.asyncio
async def test_a_position_with_no_entry_record_is_skipped(tmp_path):
    """An adopted position has no record to correct, and inventing one would
    put a fabricated open date into the evidence - the rule restore_open_lots
    already follows."""
    _, _, bridge = _bridge(tmp_path, {"MNST": (8.0, 90.85)})

    assert await bridge.reconcile_entry_prices() == []
    assert "MNST" not in bridge._entries


@pytest.mark.asyncio
async def test_a_broker_that_cannot_be_read_changes_nothing(tmp_path):
    """Degrading to 'leave the record alone' is right: a wrong price is bad,
    and a price overwritten from a failed read would be worse."""
    broker, _, bridge = _bridge(tmp_path, {"AMD": (7.0, 510.267)})
    bridge._entries["AMD"] = _entry(503.16)
    broker.fail = True

    assert await bridge.reconcile_entry_prices() == []
    assert bridge._entries["AMD"].price == pytest.approx(503.16)


@pytest.mark.asyncio
async def test_the_correction_survives_a_restart(tmp_path):
    """`_entries` is persisted, so a correction that is not saved would be
    redone every launch and the ledger would keep being rebuilt from the wrong
    basis in between."""
    _, _, bridge = _bridge(tmp_path, {"AMD": (7.0, 510.267)})
    bridge._entries["AMD"] = _entry(503.16)

    await bridge.reconcile_entry_prices()

    _, _, reloaded = _bridge(tmp_path, {"AMD": (7.0, 510.267)})
    assert reloaded._entries["AMD"].price == pytest.approx(510.267)


@pytest.mark.asyncio
async def test_it_runs_before_the_ledger_is_rebuilt(tmp_path):
    """Ordering is the whole point. `restore_open_lots` passes `entry.price` as
    the lot's cost basis, so a correction applied afterwards would leave the
    ledger holding the number this exists to remove.
    """
    from qat.domain.performance.trades import TradeLedger

    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker({"AMD": (7.0, 510.267)})
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    bridge = SignalToOrderBridge(
        bus=bus,
        oms=oms,
        settings=settings,
        trade_ledger=TradeLedger(EventBus(), tmp_path, settings=settings),
    )
    bridge._entries["AMD"] = _entry(503.16)

    await bridge.reconcile_entry_prices()
    await bridge.restore_open_lots()

    lot = bridge.oms  # placeholder to keep the import used
    assert lot is not None
    lots = bridge._lot_store().open_lots("AMD")  # type: ignore[union-attr]
    assert lots[0].price == pytest.approx(510.267)


# --- M175: IBKR's average cost is commission-INCLUSIVE --------------------------
#
# Every restart rewrote every position to avgCost, because the 1 bp tolerance is
# tighter than the 8.8 bp commission - and it undid M70's correct price:
#   31 Aug 10:35  ENTRY PRICE CORRECTED: JHX.AX filled at 41.9185
#   31 Aug 13:38  Corrected the recorded entry price for JHX.AX -> 41.9554


class _IBLikeBroker(_Broker):
    avg_price_includes_commission = True


def _ib_bridge(tmp_path, positions: dict[str, tuple[float, float]]):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")
    bus = EventBus()
    switch = KillSwitch()
    broker = _IBLikeBroker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return SignalToOrderBridge(bus=bus, oms=oms, settings=settings)


@pytest.mark.asyncio
async def test_an_observed_fill_is_never_overwritten(tmp_path):
    bridge = _ib_bridge(tmp_path, {"JHX.AX": (1097.0, 41.95541155)})
    bridge._entries["JHX.AX"] = replace(_entry(41.9185, stop=39.39), price_source="fill")

    assert await bridge.reconcile_entry_prices() == []
    assert bridge._entries["JHX.AX"].price == pytest.approx(41.9185)


@pytest.mark.asyncio
async def test_ibkr_average_cost_is_converted_back_to_the_fill(tmp_path):
    """BHP.AX: a record still at the 64.08 reference, avgCost 64.1263816."""
    bridge = _ib_bridge(tmp_path, {"BHP.AX": (793.0, 64.1263816)})
    bridge._entries["BHP.AX"] = replace(_entry(64.08, stop=60.45), price_source="reference")

    assert await bridge.reconcile_entry_prices() == ["BHP.AX"]
    assert bridge._entries["BHP.AX"].price == pytest.approx(64.07, abs=1e-6)


@pytest.mark.asyncio
async def test_a_record_already_at_the_fill_is_left_alone(tmp_path):
    """The regression itself: an unstamped record holding the true fill must
    NOT be 'corrected' up to avgCost."""
    bridge = _ib_bridge(tmp_path, {"COH.AX": (363.0, 135.85548075)})
    bridge._entries["COH.AX"] = _entry(135.73603304, stop=126.09)

    assert await bridge.reconcile_entry_prices() == []


@pytest.mark.asyncio
async def test_below_the_floor_the_conversion_takes_the_floor_off(tmp_path):
    bridge = _ib_bridge(tmp_path, {"XYZ.AX": (10.0, 50.66)})
    bridge._entries["XYZ.AX"] = _entry(51.00, stop=45.0)

    assert await bridge.reconcile_entry_prices() == ["XYZ.AX"]
    assert bridge._entries["XYZ.AX"].price == pytest.approx(50.0)


def test_the_ibkr_adapter_declares_its_average_cost_commission_inclusive():
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.mock_broker import MockBroker

    assert IBAdapter.avg_price_includes_commission is True
    assert getattr(MockBroker(seed=1), "avg_price_includes_commission", False) is False
