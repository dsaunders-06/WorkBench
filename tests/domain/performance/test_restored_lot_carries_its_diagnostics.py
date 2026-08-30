"""What a lot rebuilt after a restart must carry from the record behind it.

⚠️ THE FOURTH AND FIFTH FIELDS this record has lost across a restart - and the
THIRD was believed fixed. M33 lost `target_price`; M49 lost `strategy`; M44 lost
`reference_price`, and M44's fix on 28 August carried it onto the record, into
the file and back out again, then stopped one call short of the lot a
`ClosedTrade` is actually made from.

The guard below is anchored on SHAPE rather than on a list of names, because a
list of names is the thing that failed three times.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.signal_bridge import _Entry
from qat.domain.performance.trades import OpenLot, TradeLedger

_BASE = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)


async def _ledger(tmp_path) -> TradeLedger:
    ledger = TradeLedger(EventBus(), tmp_path)
    await ledger.start()
    return ledger


async def _sell(ledger: TradeLedger, quantity: float, price: float, day: int) -> None:
    await ledger._on_fill(
        OrderFilledEvent(
            order_id=f"sell-{day}",
            symbol="AAA",
            side="sell",
            quantity=quantity,
            price=price,
            strategy="swing",
            ts=_BASE + timedelta(days=day),
        )
    )


def test_every_field_common_to_the_record_and_the_lot_can_be_restored() -> None:
    """⚠️ THE GUARD THAT WOULD HAVE CAUGHT THIS ON 28 AUGUST.

    A field can be added to the persisted record AND to the lot and still not
    travel between them, because a third thing - this function's signature -
    has to change too, and nothing checked that it did.

    Anchored on the shape, so the SIXTH field to be lost fails the build.
    `target_price` is correctly outside this set: it is on the record and not
    on the lot, so there is nothing for `restore_open_lot` to carry.
    """
    stored = set(_Entry.__dataclass_fields__)
    lot = set(OpenLot.__dataclass_fields__)
    restorable = set(inspect.signature(TradeLedger.restore_open_lot).parameters) - {"self"}

    lost = (stored & lot) - restorable

    assert not lost, (
        f"{sorted(lost)} is persisted on the entry record AND carried on the lot, but "
        f"restore_open_lot cannot accept it - so a restart rebuilds the lot without it "
        f"and every trade closed after a restart loses it silently. That is how M33, "
        f"M49 and M44 each went missing."
    )


@pytest.mark.asyncio
async def test_a_lot_opened_this_session_records_its_slippage(tmp_path) -> None:
    """⚠️ THE CONTROL. This path already worked on 28 August. A test green on
    both paths would have proved nothing about the one that was broken."""
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="buy-1",
            symbol="AAA",
            side="buy",
            quantity=20.0,
            price=50.0,
            strategy="swing",
            stop_price=45.0,
            reference_price=49.90,
            ts=_BASE,
        )
    )
    await _sell(ledger, 20.0, 55.0, day=16)

    trade = ledger.closed_trades("swing")[0]
    assert trade.reference_price == pytest.approx(49.90)
    assert trade.entry_slippage == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_a_lot_that_survived_a_restart_records_its_slippage(tmp_path) -> None:
    """⚠️ THE ONE THAT WAS BROKEN. With a ten-day minimum hold and a session
    most nights, this is the path EVERY trade this system closes takes."""
    ledger = await _ledger(tmp_path)
    assert ledger.restore_open_lot(
        symbol="AAA",
        quantity=20.0,
        price=50.0,
        stop_price=45.0,
        strategy="swing",
        opened_at=_BASE,
        reference_price=49.90,
    )
    await _sell(ledger, 20.0, 55.0, day=16)

    trade = ledger.closed_trades("swing")[0]
    assert trade.reference_price == pytest.approx(49.90)
    assert trade.entry_slippage == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_a_record_without_one_restores_as_unknown(tmp_path) -> None:
    """`None` means UNKNOWN. Falling back to the entry price would report ZERO
    slippage on a trade nobody measured - worse than an empty column, because it
    looks like a measurement. Every record written before 28 August is this."""
    ledger = await _ledger(tmp_path)
    assert ledger.restore_open_lot(
        symbol="AAA",
        quantity=20.0,
        price=50.0,
        stop_price=45.0,
        strategy="swing",
        opened_at=_BASE,
    )
    await _sell(ledger, 20.0, 55.0, day=16)

    trade = ledger.closed_trades("swing")[0]
    assert trade.reference_price is None
    assert trade.entry_slippage is None
