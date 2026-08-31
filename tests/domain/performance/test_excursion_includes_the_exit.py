"""The exit is part of the excursion, and a gapped stop proves it.

⚠️ MEASURED LIVE, 31 August 2026, on the PNI.AX stop-out - the first trade this
system ever produced with `mae_r` populated, and the field was wrong:

    entry 17.9258  stop 16.46  exit 15.56
    r_multiple -1.6455   mae_r -0.633   worst_price 16.9979

`worst_price` is HIGHER than the exit price. MAE says the trade went 0.63R
against; it realised -1.6455R.

**On a losing trade MAE cannot be less severe than the realised R.** The trade
reached the exit price by definition, so the excursion includes it.

**Root cause:** `_close_against_lots` never touched `worst_price`/`best_price`.
They were only updated by `_on_price` from a MarketDataEvent, so a broker-side
stop filling at a price the app never saw as a tick was invisible to MAE - and
PNI's exit landed at 10:00:13, inside the blind window, with the feed delivering
nothing.

⚠️ **The direction is the dangerous one:** it made a trade look like it went
LESS against than it did, on exactly the case M44 exists to measure - a stop that
gaps. Two stop-outs so far, both about 1.6R against an intended 1R.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, OrderFilledEvent
from qat.domain.performance.trades import TradeLedger

_BASE = datetime(2026, 8, 25, 4, 4, 53, tzinfo=UTC)


async def _ledger(tmp_path) -> TradeLedger:
    ledger = TradeLedger(EventBus(), tmp_path)
    await ledger.start()
    return ledger


async def _open(ledger: TradeLedger, price: float, stop: float, qty: float) -> None:
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="buy-1",
            symbol="PNI.AX",
            side="buy",
            quantity=qty,
            price=price,
            strategy="swing",
            stop_price=stop,
            ts=_BASE,
        )
    )


async def _sell(ledger: TradeLedger, price: float, qty: float, day: int = 6) -> None:
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="sell-1",
            symbol="PNI.AX",
            side="sell",
            quantity=qty,
            price=price,
            strategy="swing",
            exit_reason="stop",
            ts=_BASE + timedelta(days=day),
        )
    )


@pytest.mark.asyncio
async def test_a_gapped_stop_records_the_exit_as_the_worst_price(tmp_path) -> None:
    """PNI's real numbers. No tick ever carried the exit price, exactly as on
    the day: the feed was blind and the stop filled at the broker."""
    ledger = await _ledger(tmp_path)
    await _open(ledger, price=17.9258, stop=16.46, qty=2973.0)
    # The only prices the app ever saw - none of them near the exit.
    for price in (17.7985, 16.9979):
        await ledger._on_price(MarketDataEvent(symbol="PNI.AX", price=price, ts=_BASE, volume=1.0))
    await _sell(ledger, price=15.56, qty=2973.0)

    trade = ledger.closed_trades("swing")[0]
    assert trade.worst_price == pytest.approx(15.56)


@pytest.mark.asyncio
async def test_mae_is_never_less_severe_than_the_realised_r(tmp_path) -> None:
    """⚠️ THE INVARIANT, and nothing asserted it. A loser reached its own exit,
    so MAE is at least as bad as the realised R."""
    ledger = await _ledger(tmp_path)
    await _open(ledger, price=17.9258, stop=16.46, qty=2973.0)
    for price in (17.7985, 16.9979):
        await ledger._on_price(MarketDataEvent(symbol="PNI.AX", price=price, ts=_BASE, volume=1.0))
    await _sell(ledger, price=15.56, qty=2973.0)

    trade = ledger.closed_trades("swing")[0]
    assert trade.mae_r is not None and trade.gross_r_multiple is not None
    # ⚠️ GROSS, not net. `mae_r` is a PRICE excursion and carries no costs, while
    # `r_multiple` is net of commission - so comparing them is apples to oranges
    # and the first version of this assertion did exactly that. It still failed
    # on the live numbers either way: PNI's gross was -1.614 against mae_r -0.633.
    assert trade.mae_r <= trade.gross_r_multiple + 1e-9, (
        f"mae_r {trade.mae_r} is LESS severe than the gross {trade.gross_r_multiple} - "
        f"the trade reached its own exit price, so the excursion must include it"
    )


@pytest.mark.asyncio
async def test_a_winner_records_the_exit_as_the_best_price(tmp_path) -> None:
    """The same rule the other way, so the fix is not one-sided: a target that
    fills above every tick the app saw is still the best price reached."""
    ledger = await _ledger(tmp_path)
    await _open(ledger, price=17.9258, stop=16.46, qty=2973.0)
    await ledger._on_price(MarketDataEvent(symbol="PNI.AX", price=18.2, ts=_BASE, volume=1.0))
    await _sell(ledger, price=21.5, qty=2973.0)

    trade = ledger.closed_trades("swing")[0]
    assert trade.best_price == pytest.approx(21.5)
    assert trade.mfe_r is not None and trade.gross_r_multiple is not None
    assert trade.mfe_r >= trade.gross_r_multiple - 1e-9


@pytest.mark.asyncio
async def test_a_tick_worse_than_the_exit_still_wins(tmp_path) -> None:
    """⚠️ THE CONTROL. Folding the exit in must not OVERWRITE a genuinely worse
    excursion the app did see - it is a min, not an assignment."""
    ledger = await _ledger(tmp_path)
    await _open(ledger, price=17.9258, stop=16.46, qty=2973.0)
    await ledger._on_price(MarketDataEvent(symbol="PNI.AX", price=14.0, ts=_BASE, volume=1.0))
    await _sell(ledger, price=15.56, qty=2973.0)

    trade = ledger.closed_trades("swing")[0]
    assert trade.worst_price == pytest.approx(14.0)
