"""Realised trade matching (spec M16).

The decision journal records decisions; this records outcomes. Everything the
promotion gate concludes rests on these numbers being right.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import UTC, date, datetime, timedelta

import pytest

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.events import ExitPriceCorrectedEvent, MarketDataEvent, OrderFilledEvent
from qat.domain.performance import trades as trades_module
from qat.domain.performance.trades import _FIELDS, ClosedTrade, EquityCurve, TradeLedger

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
    assert trade.gross_pnl == pytest.approx(100.0)
    # Net of the modelled round trip, which the shipped defaults apply in
    # paper as well as live: 2R gross is less than 2R kept.
    assert trade.net_pnl < trade.gross_pnl
    assert trade.r_multiple is not None and 0 < trade.r_multiple < 2.0
    assert trade.gross_r_multiple == pytest.approx(2.0)  # +10 on 5 of risk
    assert trade.is_win is True


@pytest.mark.asyncio
async def test_a_stop_out_on_a_position_from_an_earlier_session_records_a_trade(tmp_path):
    """M49. Entry lots lived in memory alone, so a position opened in an earlier
    session had none - and with a ten-day minimum hold and a session per night,
    that is every position this system holds. The sell was absorbed correctly,
    logged "this is now a closed trade", and recorded nothing."""
    ledger = await _ledger(tmp_path)

    assert ledger.restore_open_lot(
        symbol="AAA",
        quantity=20.0,
        price=50.0,
        stop_price=45.0,
        strategy="swing",
        opened_at=_BASE - timedelta(days=16),
    )
    await _fill(ledger, "sell", 20, 44.80)

    trades = ledger.closed_trades("swing")
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(50.0)
    assert trades[0].stop_price == pytest.approx(45.0)
    assert trades[0].gross_r_multiple == pytest.approx(-1.04)
    assert trades[0].holding_days == pytest.approx(16.0)


@pytest.mark.asyncio
async def test_restoring_never_overwrites_a_lot_the_session_already_has(tmp_path):
    """Restoration is a startup step and must never compete with a live fill.
    The running record is always the better one - it has the real fill price."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)

    assert not ledger.restore_open_lot(
        symbol="AAA",
        quantity=10.0,
        price=999.0,
        stop_price=1.0,
        strategy="swing",
        opened_at=_BASE,
    )
    assert ledger.open_lots("AAA")[0].price == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_the_closed_trade_count_survives_a_restart(tmp_path):
    """The promotion gate needs 30 closed trades per strategy and the app
    restarts every session. The list was in-memory while the file beside it was
    append-only and never opened, so the count reset to zero every night and
    could never have reached the gate."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=3)
    assert len(ledger.closed_trades()) == 1

    restarted = TradeLedger(EventBus(), tmp_path)

    assert len(restarted.closed_trades()) == 1
    assert len(restarted.closed_trades("swing")) == 1
    assert restarted.strategies() == ["swing"]


@pytest.mark.asyncio
async def test_a_reloaded_trade_keeps_its_excursion_diagnostics(tmp_path):
    """Only the DERIVED figures were written, so a reloaded trade could never
    recompute MAE or MFE and the M37 diagnostics would blank on first restart."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    for price in (92.0, 118.0):
        await ledger._on_price(
            MarketDataEvent(symbol="AAA", price=price, volume=1, ts=_BASE + timedelta(days=1))
        )
    await _fill(ledger, "sell", 10, 110.0, day=3)

    before = ledger.closed_trades()[0]
    after = TradeLedger(EventBus(), tmp_path).closed_trades()[0]

    assert before.mae_r is not None
    assert after.mae_r == pytest.approx(before.mae_r)
    assert after.mfe_r == pytest.approx(before.mfe_r)


@pytest.mark.asyncio
async def test_an_unreadable_row_does_not_cost_the_rows_after_it(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=3)

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    corrupt = lines[1].replace("110.0", "not-a-price")
    ledger.path.write_text("\n".join([lines[0], corrupt, lines[1]]) + "\n", encoding="utf-8")

    assert len(TradeLedger(EventBus(), tmp_path).closed_trades()) == 1


@pytest.mark.asyncio
async def test_a_trade_stopped_out_loses_more_than_one_r(tmp_path):
    """Stopped at exactly the stop, the loss is 1R of price movement plus the
    cost of having been in the trade at all. A system sized on the assumption
    that a stop costs exactly 1R is understating every loss it takes."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 95.0, day=1)

    trade = ledger.closed_trades()[0]
    assert trade.gross_pnl == pytest.approx(-50.0)
    assert trade.gross_r_multiple == pytest.approx(-1.0)
    assert trade.r_multiple is not None and trade.r_multiple < -1.0
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
    assert trade.gross_pnl == pytest.approx(200.0)


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
    assert trades[0].gross_pnl == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_one_sell_can_close_several_lots(tmp_path):
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0, day=0)
    await _fill(ledger, "buy", 10, 120.0, stop=115.0, day=1)
    await _fill(ledger, "sell", 20, 130.0, day=2)

    trades = ledger.closed_trades()
    assert len(trades) == 2
    assert sorted(t.entry_price for t in trades) == [100.0, 120.0]
    assert sum(t.gross_pnl for t in trades) == pytest.approx(300.0 + 100.0)
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
async def test_the_earnings_date_survives_the_round_trip_to_disk(tmp_path):
    """M41. The date is carried from the entry order and cannot be recovered
    afterwards - by the time the trade closes the calendar has rolled to the
    next quarter, so a column that failed to persist would lose the fact
    permanently rather than merely delay it."""
    bus = EventBus()
    ledger = TradeLedger(bus, tmp_path)
    await ledger.start()

    await bus.publish(
        OrderFilledEvent(
            order_id="1",
            symbol="AAA",
            side="buy",
            quantity=10,
            price=100.0,
            stop_price=95.0,
            strategy="swing",
            ts=_BASE,
            earnings_at_entry=date(2026, 7, 22),
        )
    )
    await bus.publish(
        OrderFilledEvent(
            order_id="2",
            symbol="AAA",
            side="sell",
            quantity=10,
            price=110.0,
            strategy="swing",
            ts=_BASE + timedelta(days=5),
        )
    )
    await ledger.stop()

    text = (tmp_path / "closed_trades.csv").read_text(encoding="utf-8")
    assert "earnings_at_entry" in text
    assert "2026-07-22" in text

    reloaded = TradeLedger(EventBus(), tmp_path).closed_trades()
    assert len(reloaded) == 1
    assert reloaded[0].earnings_at_entry == date(2026, 7, 22)
    assert reloaded[0].held_through_earnings is True


@pytest.mark.asyncio
async def test_a_trade_with_no_earnings_date_reloads_as_unknown_not_as_false(tmp_path):
    """Three states kept as three across the file boundary. Writing an unknown
    as False would merge it permanently with trades that genuinely avoided a
    print, and no later read could separate them again."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=1)
    await ledger.stop()

    reloaded = TradeLedger(EventBus(), tmp_path).closed_trades()

    assert reloaded[0].earnings_at_entry is None
    assert reloaded[0].held_through_earnings is None


def test_a_pre_m41_file_still_loads(tmp_path):
    """Every closed_trades.csv written before this column exists lacks it, and
    a restart that discarded its whole trade history over a missing diagnostic
    would be the M33 mistake a second time."""
    (tmp_path / "closed_trades.csv").write_text(
        "opened_at,closed_at,symbol,strategy,quantity,entry_price,exit_price,stop_price\n"
        "2026-08-01T00:00:00+00:00,2026-08-05T00:00:00+00:00,CVS,swing,47,105.475,95.597,99.355\n",
        encoding="utf-8",
    )

    trades = TradeLedger(EventBus(), tmp_path).closed_trades()

    assert len(trades) == 1
    assert trades[0].earnings_at_entry is None


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


# --- Costs are part of the trade (M28) ------------------------------------
#
# `pnl` was (exit - entry) x quantity with no fee term, so expectancy, average
# R, profit factor and the promotion gate that reads them were all computed on
# money the account never kept.


async def _costed_ledger(tmp_path, **overrides) -> TradeLedger:
    base = {"_env_file": None, "commission_bps": 5.0, "slippage_bps": 5.0}
    base.update(overrides)
    ledger = TradeLedger(EventBus(), tmp_path, settings=Settings(**base))  # type: ignore[arg-type]
    await ledger.start()
    return ledger


@pytest.mark.asyncio
async def test_a_trade_records_what_it_cost_to_open_and_close(tmp_path):
    ledger = await _costed_ledger(tmp_path, broker_min_commission=0.0)
    await _fill(ledger, "buy", 100, 100.0, stop=95.0)
    await _fill(ledger, "sell", 100, 110.0, day=5)

    trade = ledger.closed_trades()[0]

    assert trade.gross_pnl == pytest.approx(1000.0)
    # 10bps of $10,000 in, 10bps of $11,000 out.
    assert trade.entry_cost == pytest.approx(10.0)
    assert trade.exit_cost == pytest.approx(11.0)
    assert trade.net_pnl == pytest.approx(979.0)
    assert trade.costs == pytest.approx(21.0)


@pytest.mark.asyncio
async def test_a_small_gain_swallowed_by_costs_is_a_loss(tmp_path):
    """The case the whole milestone exists for: at IBKR's minimums a round
    trip costs at least $12, which is decisive on a small position."""
    ledger = await _costed_ledger(tmp_path, broker_min_commission=6.0, slippage_bps=0.0)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 100.5, day=3)

    trade = ledger.closed_trades()[0]

    assert trade.gross_pnl == pytest.approx(5.0)
    assert trade.net_pnl < 0
    assert not trade.is_win, "a $5 gain costing $12 is not a win"
    assert trade.r_multiple is not None and trade.r_multiple < 0


@pytest.mark.asyncio
async def test_the_commission_floor_is_charged_once_not_once_per_piece(tmp_path):
    """A position closed in three pieces pays one entry commission. Charging
    the floor per closed trade would invent fees that were never billed."""
    ledger = await _costed_ledger(tmp_path, broker_min_commission=6.0, slippage_bps=0.0)
    await _fill(ledger, "buy", 300, 100.0, stop=95.0)
    await _fill(ledger, "sell", 100, 110.0, day=1)
    await _fill(ledger, "sell", 100, 110.0, day=2)
    await _fill(ledger, "sell", 100, 110.0, day=3)

    trades = ledger.closed_trades()

    assert len(trades) == 3
    # One entry commission of $15 (5bps of $30,000) spread across the three.
    assert sum(t.entry_cost for t in trades) == pytest.approx(15.0)
    # And each exit charged its own floor, because each was its own order.
    assert [round(t.exit_cost, 2) for t in trades] == [6.0, 6.0, 6.0]


@pytest.mark.asyncio
async def test_one_sell_closing_several_lots_splits_its_cost(tmp_path):
    ledger = await _costed_ledger(tmp_path, broker_min_commission=6.0, slippage_bps=0.0)
    await _fill(ledger, "buy", 100, 100.0, stop=95.0)
    await _fill(ledger, "buy", 100, 105.0, stop=99.0, day=1)
    await _fill(ledger, "sell", 200, 110.0, day=2)

    trades = ledger.closed_trades()

    assert len(trades) == 2
    # The single sell's cost, once, divided between the lots it closed.
    assert sum(t.exit_cost for t in trades) == pytest.approx(11.0)


@pytest.mark.asyncio
async def test_costs_can_be_switched_off_for_a_pure_price_measurement(tmp_path):
    ledger = await _costed_ledger(tmp_path, apply_costs_in_paper=False)
    await _fill(ledger, "buy", 100, 100.0, stop=95.0)
    await _fill(ledger, "sell", 100, 110.0, day=5)

    trade = ledger.closed_trades()[0]

    assert trade.costs == 0.0
    assert trade.net_pnl == trade.gross_pnl


# --- M71: amending an app-transmitted sell after the true fill arrives ------
#
# The OMS-level end-to-end path - `_correct_announced_price` publishing
# `ExitPriceCorrectedEvent` for a sell - is covered in
# tests/safety/test_live_exit_price_correction.py. These test the ledger's
# amendment in isolation: matching on order_id, re-apportioning cost, and the
# backup discipline.


def test_a_row_without_order_id_still_loads(tmp_path):
    """Every closed_trades.csv written before M71 lacks this column - the two
    rows in the live record among them - and a restart that discarded its
    whole trade history over a missing amendment target would be the M33
    mistake again."""
    (tmp_path / "closed_trades.csv").write_text(
        "opened_at,closed_at,symbol,strategy,quantity,entry_price,exit_price,stop_price\n"
        "2026-08-01T00:00:00+00:00,2026-08-05T00:00:00+00:00,CVS,swing,47,105.475,95.597,99.355\n",
        encoding="utf-8",
    )

    trades = TradeLedger(EventBus(), tmp_path).closed_trades()

    assert len(trades) == 1
    assert trades[0].order_id is None


@pytest.mark.asyncio
async def test_one_sell_closing_two_lots_amends_both_rows(tmp_path):
    """The exit-price twin of test_one_sell_closing_several_lots_splits_its_cost.
    One sell can close several lots, producing several ClosedTrade rows from
    one order - every row carrying that order id must be amended, not just
    the first."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 100, 100.0, stop=95.0)
    await _fill(ledger, "buy", 100, 105.0, stop=99.0, day=1)
    await _fill(ledger, "sell", 200, 110.0, day=2)

    trades = ledger.closed_trades()
    assert len(trades) == 2
    order_id = trades[0].order_id
    assert order_id is not None
    assert trades[1].order_id == order_id

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id=order_id, symbol="AAA", price=112.0, announced_price=110.0, quantity=200.0
        )
    )

    amended = ledger.closed_trades()
    assert [t.exit_price for t in amended] == [pytest.approx(112.0), pytest.approx(112.0)]
    # Re-apportioned on quantity, not doubled onto each row - the same basis
    # _close_against_lots split the original exit cost on.
    assert sum(t.exit_cost for t in amended) == pytest.approx(ledger._fill_cost(200, 112.0))

    rows = list(csv.DictReader((tmp_path / "closed_trades.csv").open(encoding="utf-8")))
    assert len(rows) == 2
    assert all(float(row["exit_price"]) == pytest.approx(112.0) for row in rows)


@pytest.mark.asyncio
async def test_an_unmatched_order_id_amends_nothing(tmp_path):
    """Amend nothing you are not sure of. A correction applied to the wrong
    trade is worse than no correction."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=1)
    before = ledger.closed_trades()[0]

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id="no-such-order",
            symbol="AAA",
            price=999.0,
            announced_price=110.0,
            quantity=10.0,
        )
    )

    after = ledger.closed_trades()[0]
    assert after.exit_price == pytest.approx(before.exit_price)
    assert list(tmp_path.glob("closed_trades.csv.bak-*")) == []


@pytest.mark.asyncio
async def test_the_backup_is_written_once_not_per_row(tmp_path):
    """Once per process - not once per amended row within a single sell's
    correction, and not again for a second, unrelated one."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 100, 100.0, stop=95.0)
    await _fill(ledger, "buy", 100, 105.0, stop=99.0, day=1)
    await _fill(ledger, "sell", 200, 110.0, day=2)  # two rows, one order id
    await _fill(ledger, "buy", 10, 50.0, stop=45.0, symbol="BBB", day=3)
    await _fill(ledger, "sell", 10, 55.0, symbol="BBB", day=4)  # a second order

    trades = ledger.closed_trades()
    first_order_id = trades[0].order_id
    second_order_id = trades[2].order_id
    assert first_order_id is not None and second_order_id is not None
    assert first_order_id != second_order_id

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id=first_order_id,
            symbol="AAA",
            price=112.0,
            announced_price=110.0,
            quantity=200.0,
        )
    )
    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id=second_order_id,
            symbol="BBB",
            price=56.0,
            announced_price=55.0,
            quantity=10.0,
        )
    )

    backups = list(tmp_path.glob("closed_trades.csv.bak-*"))
    assert len(backups) == 1


# --- M71 review: the rewrite's blast radius ---------------------------------
#
# The correction itself was right - exact matching, genuinely recomputed
# derived values, the buy path untouched. The rewrite that put it on disk
# was not: it regenerated the whole file from `self._closed`, which silently
# drops any row `_load_closed` skipped at startup and restates every
# untouched row's derived figures from whatever blanks `from_row` filled in.


def test_an_untouched_row_survives_amendment_byte_identical(tmp_path):
    """Critical 1 / Important 2, and the Minor 8 test the brief asks for by
    name. Regenerating the file from `self._closed` is wrong two ways at
    once: a row `_load_closed` could not parse is not in `self._closed` at
    all, so it is silently dropped from the rewrite - 3 rows on disk become
    2. And a row that WAS loaded, but with blank (unknown, not zero) cost
    fields, gets those fields coerced to 0.0 by `from_row`, and every
    derived figure downstream of them recomputed on that lie when the row is
    rewritten - even though nothing about that trade was meant to change.

    Proven on the file's exact lines, not on parsed objects - parsing is
    exactly what hides this from the ledger itself.
    """
    path = tmp_path / "closed_trades.csv"
    target = ClosedTrade(
        symbol="AAA",
        strategy="swing",
        quantity=10.0,
        entry_price=100.0,
        exit_price=110.0,
        stop_price=95.0,
        opened_at=_BASE,
        closed_at=_BASE + timedelta(days=1),
        entry_cost=5.0,
        exit_cost=5.5,
        order_id="sell-AAA-1-10",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(target.as_row())
        # A legacy row: blank (unknown) cost fields and no order_id - exactly
        # the shape of the two rows already in the live closed_trades.csv.
        legacy_row = target.as_row()
        legacy_row.update(symbol="ZZZ", order_id="", entry_cost="", exit_cost="")
        writer.writerow(legacy_row)
        # A row `_load_closed` cannot parse at all.
        corrupt_row = target.as_row()
        corrupt_row.update(symbol="YYY", order_id="", quantity="not-a-number")
        writer.writerow(corrupt_row)

    before = path.read_text(encoding="utf-8").splitlines()
    assert len(before) == 4  # header + 3 data rows

    ledger = TradeLedger(EventBus(), tmp_path)
    assert len(ledger.closed_trades()) == 2, "the corrupt row is skipped at load, by design"

    asyncio.run(
        ledger._on_exit_price_corrected(
            ExitPriceCorrectedEvent(
                order_id="sell-AAA-1-10",
                symbol="AAA",
                price=112.0,
                announced_price=110.0,
                quantity=10.0,
            )
        )
    )

    after = path.read_text(encoding="utf-8").splitlines()
    assert len(after) == 4, "no row may vanish - the corrupt row exists on disk and must survive"
    assert after[2] == before[2], "an untouched legacy row must not change in any way"
    assert after[3] == before[3], "a row the loader could not parse must survive unamended"
    assert after[1] != before[1], "the targeted row must actually be amended"


@pytest.mark.asyncio
async def test_a_matching_order_id_for_a_different_symbol_amends_nothing(tmp_path):
    """Minor 5: matching on order_id alone would let a future id collision or
    an adapter's id reuse land a correction on the wrong trade's row. Costs
    nothing to also require the symbol to agree."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0, symbol="AAA")
    await _fill(ledger, "sell", 10, 110.0, symbol="AAA", day=1)
    order_id = ledger.closed_trades()[0].order_id
    assert order_id is not None
    before_price = ledger.closed_trades()[0].exit_price

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id=order_id, symbol="BBB", price=999.0, announced_price=110.0, quantity=10.0
        )
    )

    after = ledger.closed_trades()[0]
    assert after.exit_price == pytest.approx(before_price)
    assert list(tmp_path.glob("closed_trades.csv.bak-*")) == []


@pytest.mark.asyncio
async def test_the_exit_cost_basis_matches_the_write_path(tmp_path):
    """Minor 6: `_close_against_lots` bases the exit cost on the FULL sell
    quantity and apportions on it; the amendment used to base it on the
    matched rows' own quantity total instead. Not the same once a per-order
    commission floor binds at one basis and not the other - exactly the case
    of a sell that partly closed an untracked position, where
    `_close_against_lots` logs "unmatched portion ignored" and only the
    matched part becomes a ClosedTrade row."""
    ledger = await _costed_ledger(
        tmp_path, broker_min_commission=6.0, commission_bps=50.0, slippage_bps=0.0
    )
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    # The sell is for 20; only 10 are tracked, so 10 are unmatched and
    # ignored - one ClosedTrade row, quantity=10, even though the order's OWN
    # quantity (what the write path costed the exit against) was 20.
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="sell-1",
            symbol="AAA",
            side="sell",
            quantity=20,
            price=110.0,
            ts=_BASE + timedelta(days=1),
        )
    )
    assert len(ledger.closed_trades()) == 1

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id="sell-1", symbol="AAA", price=112.0, announced_price=110.0, quantity=20.0
        )
    )

    amended = ledger.closed_trades()[0]
    # Recomputed on the order's full quantity (20) - the basis
    # `_close_against_lots` used - not the 10 that matched a tracked lot.
    # At 50bps: 10 shares @112 = $1,120 notional, 0.5% = $5.60, under the $6
    # floor - so a matched-total basis would charge the FULL $6.00 floor to
    # this one row. 20 shares @112 = $2,240 notional, 0.5% = $11.20, over the
    # floor - so the correct basis charges this row its half-share, $5.60.
    assert amended.exit_cost == pytest.approx(5.60, abs=1e-6)


@pytest.mark.asyncio
async def test_a_failed_write_is_reported_not_asserted_as_success(tmp_path, caplog, monkeypatch):
    """Important 3: `_rewrite_closed_trades` used to swallow OSError and
    return None, and the caller logged 'EXIT PRICE CORRECTED ON DISK ...
    amended' regardless of whether the write actually happened - so a failed
    write left memory and disk diverged while the log asserted the opposite
    of the truth. Separately, `self.path.open("w")` truncated before writing,
    so a failure mid-write left a truncated evidence file.

    Proves both: a failed write must be reported as a failure, not logged as
    a success, and the original file must survive untouched because nothing
    is truncated to make room for a write that does not complete (the atomic
    temp-file-plus-os.replace swap)."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=1)
    order_id = ledger.closed_trades()[0].order_id
    assert order_id is not None
    path = tmp_path / "closed_trades.csv"
    before = path.read_text(encoding="utf-8")

    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "replace", _raise_oserror)
    caplog.set_level(logging.INFO)

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id=order_id, symbol="AAA", price=112.0, announced_price=110.0, quantity=10.0
        )
    )

    assert (
        path.read_text(encoding="utf-8") == before
    ), "an incomplete write must not touch the original file"
    assert ledger.closed_trades()[0].exit_price == pytest.approx(
        110.0
    ), "memory must not diverge from disk on a failed write"
    assert not any(
        "EXIT PRICE CORRECTED ON DISK" in record.message for record in caplog.records
    ), "a failed write must never be logged as a success"
    assert any(
        record.levelno == logging.ERROR for record in caplog.records
    ), "a failed write must be logged at ERROR"


@pytest.mark.asyncio
async def test_the_write_is_verified_by_reading_it_back(tmp_path, caplog, monkeypatch):
    """Important 4 remainder: the CVS/MNST precedent this backup docstring
    claims to follow re-reads from disk after writing and fails loudly if the
    result is wrong. M71's rewrite runs unattended, so it needs that check
    more, not less. Proven by making the file that lands on disk disagree
    with what was intended, after a write that reports success."""
    ledger = await _ledger(tmp_path)
    await _fill(ledger, "buy", 10, 100.0, stop=95.0)
    await _fill(ledger, "sell", 10, 110.0, day=1)
    order_id = ledger.closed_trades()[0].order_id
    assert order_id is not None
    path = tmp_path / "closed_trades.csv"

    original_write = trades_module.TradeLedger._write_closed_rows

    def _write_then_corrupt(self, fieldnames, rows):  # type: ignore[no-untyped-def]
        ok = original_write(self, fieldnames, rows)
        if ok:
            path.write_text("not,what,was,written\n", encoding="utf-8")
        return ok

    monkeypatch.setattr(trades_module.TradeLedger, "_write_closed_rows", _write_then_corrupt)
    caplog.set_level(logging.ERROR)

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id=order_id, symbol="AAA", price=112.0, announced_price=110.0, quantity=10.0
        )
    )

    assert any(
        record.levelno == logging.ERROR for record in caplog.records
    ), "a write that reads back wrong must be reported, not trusted"
