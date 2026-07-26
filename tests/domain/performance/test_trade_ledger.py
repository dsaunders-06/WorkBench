"""Realised trade matching (spec M16).

The autonomy journal records decisions; this records outcomes. Everything the
promotion gate concludes rests on these numbers being right.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.performance.trades import EquityCurve, TradeLedger

_BASE = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)


async def _ledger(tmp_path) -> TradeLedger:
    ledger = TradeLedger(EventBus(), tmp_path)
    await ledger.start()
    return ledger


async def _fill(
    ledger: TradeLedger,
    side: str,
    quantity: float,
    price: float,
    symbol: str = "AAA",
    strategy: str | None = "swing",
    stop: float | None = None,
    day: int = 0,
) -> None:
    await ledger._on_fill(
        OrderFilledEvent(
            order_id=f"{side}-{symbol}-{day}-{quantity}",
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            quantity=quantity,
            price=price,
            strategy=strategy,
            stop_price=stop,
            ts=_BASE + timedelta(days=day),
        )
    )


@pytest.mark.asyncio
async def test_a_buy_then_a_sell_produces_one_closed_trade(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=3)

    trades = ledger.closed_trades()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.pnl == pytest.approx(100.0)
    assert trade.pnl_pct == pytest.approx(0.10)
    assert trade.r_multiple == pytest.approx(2.0)  # +10 on 5 of risk
    assert trade.is_win is True


@pytest.mark.asyncio
async def test_a_losing_trade_has_a_negative_r(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 95.0, day=1)

    trade = ledger.closed_trades()[0]
    assert trade.pnl == pytest.approx(-50.0)
    assert trade.r_multiple == pytest.approx(-1.0)
    assert trade.is_win is False


@pytest.mark.asyncio
async def test_a_trade_with_no_stop_has_no_r_rather_than_zero(tmp_path):
    """Counting an unmeasurable R as 0 would drag every average toward zero for
    a reason that has nothing to do with performance."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=None)
    await _fill(ledger, "sell", 10, 120.0, day=1)

    trade = ledger.closed_trades()[0]
    assert trade.r_multiple is None
    assert trade.pnl == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_a_partial_exit_closes_only_what_was_sold(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 100, 100.0, stop=95.0)
    await _fill(ledger, "sell", 40, 110.0, day=1)

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].quantity == 40
    assert ledger.open_lots("AAA")[0].quantity == pytest.approx(60)


@pytest.mark.asyncio
async def test_lots_are_matched_first_in_first_out(tmp_path):
    """FIFO preserves per-trade identity. Average-cost would blend these into
    one number and destroy the distribution the promotion gate needs."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0, day=0)
    await _fill(ledger, "buy", 10, 200.0, stop=190.0, day=1)
    await _fill(ledger, "sell", 10, 150.0, day=2)

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(100.0), "the oldest lot closes first"
    assert trades[0].pnl == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_one_sell_can_close_several_lots(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0, day=0)
    await _fill(ledger, "buy", 10, 120.0, stop=115.0, day=1)
    await _fill(ledger, "sell", 20, 130.0, day=2)

    trades = ledger.closed_trades()
    assert len(trades) == 2
    assert sorted(t.entry_price for t in trades) == [100.0, 120.0]
    assert sum(t.pnl for t in trades) == pytest.approx(300.0 + 100.0)
    assert ledger.open_lots("AAA") == []


@pytest.mark.asyncio
async def test_an_unmatched_sell_is_ignored_not_invented(tmp_path):
    """Real for an adopted position: this app never saw the entry, so it cannot
    compute a P&L and must not guess one."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "sell", 50, 100.0)

    assert ledger.closed_trades() == []


@pytest.mark.asyncio
async def test_the_result_is_attributed_to_the_entry_strategy(tmp_path):
    """A stop sweep or delever trim closes a position it did not open.
    Crediting the closer would attribute the outcome to the wrong strategy."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0, strategy="swing")
    await _fill(ledger, "sell", 10, 110.0, strategy="delever-sweep", day=1)

    assert ledger.closed_trades()[0].strategy == "swing"
    assert ledger.closed_trades("swing") != []
    assert ledger.closed_trades("delever-sweep") == []


@pytest.mark.asyncio
async def test_symbols_are_matched_independently(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, symbol="AAA", stop=95.0)
    await _fill(ledger, "buy", 10, 50.0, symbol="BBB", stop=45.0)
    await _fill(ledger, "sell", 10, 110.0, symbol="AAA", day=1)

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].symbol == "AAA"
    assert len(ledger.open_lots("BBB")) == 1


@pytest.mark.asyncio
async def test_zero_and_negative_fills_are_ignored(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 0, 100.0)
    await _fill(ledger, "buy", 10, 0.0)
    assert ledger.open_lots() == []


@pytest.mark.asyncio
async def test_closed_trades_are_persisted_to_csv(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=1)

    text = (tmp_path / "closed_trades.csv").read_text(encoding="utf-8")
    assert "symbol,strategy" in text
    assert "AAA" in text
    assert "swing" in text


@pytest.mark.asyncio
async def test_fills_reach_the_ledger_through_the_bus(tmp_path):
    bus = EventBus()
    ledger = TradeLedger(bus, tmp_path)
    await ledger.start()

    await bus.publish(
        OrderFilledEvent(
            order_id="1", symbol="AAA", side="buy", quantity=5, price=10.0, strategy="swing"
        )
    )
    await bus.publish(
        OrderFilledEvent(
            order_id="2", symbol="AAA", side="sell", quantity=5, price=12.0, strategy="swing"
        )
    )

    assert len(ledger.closed_trades()) == 1
    await ledger.stop()


# --- Equity curve -------------------------------------------------------------


def test_the_equity_curve_appends_and_persists(tmp_path):
    curve = EquityCurve(tmp_path)
    curve.record(100_000.0, 50_000.0)
    curve.record(101_000.0, 49_000.0)

    assert [p.equity for p in curve.points()] == [100_000.0, 101_000.0]
    text = (tmp_path / "equity_curve.csv").read_text(encoding="utf-8")
    assert "ts,equity,cash" in text
    assert text.count("\n") == 3  # header plus two rows
