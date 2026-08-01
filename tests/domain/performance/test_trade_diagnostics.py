"""Per-trade diagnostics captured as they happen (M37).

Two independent reviews of the product description asked for the same thing:
that every closed trade record which regime it was opened in, how it was
sized, how it ended, and how far it travelled both ways before it resolved.

None of it decides anything. The point is that a three-month trial should be
able to answer WHY a result happened rather than only what it was - and none
of it can be reconstructed afterwards, because the price path is gone by the
time the trade closes. If the trial starts without this, the trades are
permanently thin.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, OrderFilledEvent, RegimeEvent
from qat.domain.performance.trades import TradeLedger


async def _ledger() -> TradeLedger:
    ledger = TradeLedger(EventBus(), tempfile.mkdtemp())
    await ledger.start()
    return ledger


def _buy(
    symbol: str = "AAA",
    price: float = 100.0,
    stop: float | None = 95.0,
    ref: float | None = 100.0,
):
    return OrderFilledEvent(
        order_id="buy-1",
        symbol=symbol,
        side="buy",
        quantity=10.0,
        price=price,
        strategy="swing",
        stop_price=stop,
        reference_price=ref,
    )


def _sell(symbol: str = "AAA", price: float = 110.0, reason: str | None = "target"):
    return OrderFilledEvent(
        order_id="sell-1",
        symbol=symbol,
        side="sell",
        quantity=10.0,
        price=price,
        exit_reason=reason,
    )


@pytest.mark.asyncio
async def test_the_regime_at_entry_is_recorded():
    """Which market state a trade was taken in is the first thing an analysis
    of the trial will want to split on."""
    ledger = await _ledger()
    await ledger.bus.publish(
        RegimeEvent(
            label="high_vol",
            probs={"high_vol": 0.42, "bull": 0.31},
            exposure_scalar=0.40,
            ts=datetime.now(UTC),
        )
    )
    await ledger.bus.publish(_buy())
    await ledger.bus.publish(_sell())

    trade = ledger.closed_trades()[0]
    assert trade.regime_at_entry == "high_vol"
    assert trade.regime_probability == pytest.approx(0.42)
    assert trade.exposure_scalar == pytest.approx(0.40)


@pytest.mark.asyncio
async def test_the_regime_recorded_is_the_one_at_entry_not_at_exit():
    """A position held for weeks will close in a different regime from the one
    it opened in. Attributing the result to the exit's regime would answer the
    wrong question entirely."""
    ledger = await _ledger()
    await ledger.bus.publish(
        RegimeEvent(label="bull", probs={"bull": 0.6}, exposure_scalar=1.0, ts=datetime.now(UTC))
    )
    await ledger.bus.publish(_buy())
    await ledger.bus.publish(
        RegimeEvent(label="bear", probs={"bear": 0.8}, exposure_scalar=0.25, ts=datetime.now(UTC))
    )
    await ledger.bus.publish(_sell())

    assert ledger.closed_trades()[0].regime_at_entry == "bull"


@pytest.mark.asyncio
async def test_how_the_position_ended_is_recorded():
    ledger = await _ledger()
    await ledger.bus.publish(_buy())
    await ledger.bus.publish(_sell(reason="time_stop"))

    assert ledger.closed_trades()[0].exit_reason == "time_stop"


@pytest.mark.asyncio
async def test_the_excursion_both_ways_is_tracked_while_the_position_is_held():
    """A winner that spent its life at -0.9R was nearly a loser, and the
    average result hides that completely. The path is gone by the time the
    trade closes, so it has to be recorded as it happens."""
    ledger = await _ledger()
    await ledger.bus.publish(_buy(price=100.0, stop=95.0))

    for price in (99.0, 96.0, 104.0, 101.0):
        await ledger.bus.publish(
            MarketDataEvent(symbol="AAA", price=price, volume=1.0, ts=datetime.now(UTC))
        )
    await ledger.bus.publish(_sell(price=102.0))

    trade = ledger.closed_trades()[0]
    assert trade.worst_price == pytest.approx(96.0)
    assert trade.best_price == pytest.approx(104.0)
    # Risk was 5.00 a share, so -4.00 against is -0.8R and +4.00 for is +0.8R.
    assert trade.mae_r == pytest.approx(-0.8)
    assert trade.mfe_r == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_entry_slippage_is_measured_against_the_price_it_was_sized_on():
    """The cost model ASSUMES a slippage figure. This is what it actually
    cost, and the difference is the only way to find out if the assumption
    holds."""
    ledger = await _ledger()
    await ledger.bus.publish(_buy(price=100.12, ref=100.00))
    await ledger.bus.publish(_sell())

    assert ledger.closed_trades()[0].entry_slippage == pytest.approx(0.12)


@pytest.mark.asyncio
async def test_a_trade_with_no_stop_reports_no_excursion_in_r():
    """R is meaningless without a risk per share, and inventing one would put
    a fabricated number in the column an analysis leans on hardest."""
    ledger = await _ledger()
    await ledger.bus.publish(_buy(stop=None))
    await ledger.bus.publish(
        MarketDataEvent(symbol="AAA", price=90.0, volume=1.0, ts=datetime.now(UTC))
    )
    await ledger.bus.publish(_sell())

    trade = ledger.closed_trades()[0]
    assert trade.worst_price == pytest.approx(90.0)
    assert trade.mae_r is None


@pytest.mark.asyncio
async def test_prices_for_symbols_not_held_are_ignored():
    ledger = await _ledger()
    await ledger.bus.publish(_buy())
    await ledger.bus.publish(
        MarketDataEvent(symbol="ZZZ", price=1.0, volume=1.0, ts=datetime.now(UTC))
    )
    await ledger.bus.publish(_sell())

    assert ledger.closed_trades()[0].worst_price == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_the_diagnostics_reach_the_csv():
    """The trial's artefact is the file, not the in-memory list."""
    ledger = await _ledger()
    await ledger.bus.publish(
        RegimeEvent(label="bull", probs={"bull": 0.7}, exposure_scalar=1.0, ts=datetime.now(UTC))
    )
    await ledger.bus.publish(_buy())
    await ledger.bus.publish(_sell(reason="stop"))

    header, row = ledger.path.read_text(encoding="utf-8").splitlines()[:2]
    for column in ("regime_at_entry", "exit_reason", "mae_r", "mfe_r", "holding_days"):
        assert column in header
    assert "bull" in row
    assert "stop" in row
