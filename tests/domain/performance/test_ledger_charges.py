"""A realised cost is what the broker billed, once per order (M175).

Three defects, measured on the live ledger 11 September: modelled slippage was
charged on fills that already contained it; the $6.60 floor was charged once
per ABSORBED PIECE of one order (LOV.AX's single exit paid four floors); and a
replay double-counted too, because SimulatedBroker already slips its prices.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.simulated_broker import SimulatedBroker
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.events import EntryPriceCorrectedEvent, ExitPriceCorrectedEvent, OrderFilledEvent
from qat.domain.performance.trades import TradeLedger

_BASE = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


async def _ledger(tmp_path, **overrides) -> TradeLedger:
    base = {
        "_env_file": None,
        "data_dir": str(tmp_path),
        "commission_bps": 8.8,
        "slippage_bps": 5.0,
        "broker_min_commission": 6.60,
    }
    base.update(overrides)
    ledger = TradeLedger(EventBus(), tmp_path, settings=Settings(**base))  # type: ignore[arg-type]
    await ledger.start()
    return ledger


def _event(order_id: str, side: str, quantity: float, price: float, day: int = 0):
    return OrderFilledEvent(
        order_id=order_id,
        symbol="SEK.AX",
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        price=price,
        strategy="swing",
        stop_price=price * 0.9 if side == "buy" else None,
        ts=_BASE + timedelta(days=day),
    )


@pytest.mark.asyncio
async def test_a_live_cost_is_the_commission_not_the_commission_plus_slippage(tmp_path):
    """The audit's own numbers: 38,500 of notional is 33.88 of commission,
    and 53.13 only if 5 bp of slippage is added on top."""
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(_event("in", "buy", 1000, 38.50))
    await ledger._on_fill(_event("out", "sell", 1000, 38.50, day=5))

    trade = ledger.closed_trades()[0]

    assert trade.entry_cost == pytest.approx(33.88)
    assert trade.exit_cost == pytest.approx(33.88)


@pytest.mark.asyncio
async def test_one_order_absorbed_in_pieces_pays_one_floor(tmp_path):
    """LOV.AX, 26 August: one exit order absorbed as several OrderFilledEvents
    under the SAME order id. The floor belongs to the order, not the piece."""
    ledger = await _ledger(tmp_path, commission_bps=5.0)
    await ledger._on_fill(_event("in", "buy", 300, 100.0))
    for _ in range(3):
        await ledger._on_fill(_event("out-1", "sell", 100, 110.0, day=1))

    # `closed_trades()` collapses same order_id/symbol/opened_at rows into one
    # POSITION (pre-existing `collapse_to_positions`, M71) - exactly what this
    # test's own order fragmentation triggers - so the merged total is where
    # the sum is visible.
    exits = [t.exit_cost for t in ledger.closed_trades()]
    # 5 bp of 33,000 is 16.50 for the whole order - not three $6.60 floors.
    assert sum(exits) == pytest.approx(16.50)

    # The PER-PIECE cost, before that merge, is what proves the floor was
    # charged once across the order rather than once per absorbed fragment.
    pieces = [t.exit_cost for t in ledger._closed]
    assert pieces == pytest.approx([6.60, 4.40, 5.50])
    assert pieces[0] == pytest.approx(6.60)  # the first piece alone is under the floor


@pytest.mark.asyncio
async def test_an_entry_price_correction_recosts_with_the_charge(tmp_path):
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(_event("in", "buy", 793, 64.08))

    await ledger._on_entry_price_corrected(
        EntryPriceCorrectedEvent(order_id="in", symbol="SEK.AX", price=64.07, announced_price=64.08)
    )

    lot = ledger.open_lots("SEK.AX")[0]
    assert lot.entry_cost == pytest.approx(CostModel(8.8, 5.0, 6.60).charge(793 * 64.07))


@pytest.mark.asyncio
async def test_an_exit_price_correction_recosts_with_the_charge(tmp_path):
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(_event("in", "buy", 793, 64.07))
    await ledger._on_fill(_event("out", "sell", 793, 60.45, day=2))

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id="out", symbol="SEK.AX", price=60.40, announced_price=60.45, quantity=793.0
        )
    )

    trade = ledger.closed_trades()[0]
    assert trade.exit_cost == pytest.approx(CostModel(8.8, 5.0, 6.60).charge(793 * 60.40))


@pytest.mark.asyncio
async def test_a_replay_round_trip_pays_slippage_once_in_the_prices(tmp_path):
    """WHERE ELSE: SimulatedBroker already moves every fill against the
    order, so the ledger must not charge slippage again on top."""
    index = pd.DatetimeIndex(
        [pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02"), pd.Timestamp("2026-09-03")]
    )
    prices = [100.0, 100.0, 110.0]
    bars = {
        "SEK.AX": pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices}, index=index
        )
    }
    model = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=0.0)
    broker = SimulatedBroker(bars=bars, cost_model=model)
    await broker.place_order(Order(symbol="SEK.AX", side="buy", quantity=100.0, order_id="in"))
    broker.advance()
    bought = broker._orders["in"].filled_price
    await broker.place_order(Order(symbol="SEK.AX", side="sell", quantity=100.0, order_id="out"))
    broker.advance()
    sold = broker._orders["out"].filled_price
    assert bought == pytest.approx(100.0 * 1.0005)  # slippage IS in the price
    assert sold == pytest.approx(110.0 * 0.9995)

    ledger = await _ledger(tmp_path, broker_min_commission=0.0)
    await ledger._on_fill(_event("in", "buy", 100, bought))
    await ledger._on_fill(_event("out", "sell", 100, sold, day=2))
    trade = ledger.closed_trades()[0]

    assert trade.costs == pytest.approx(model.charge(100 * bought) + model.charge(100 * sold))
