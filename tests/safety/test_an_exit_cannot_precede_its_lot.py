"""A trade cannot close before it opens. The 24 August 2026 ledger corruption.

Seven rows reached `closed_trades.csv` whose `closed_at` preceded their
`opened_at` by about an hour, worth -$167.90 that nobody lost, attributed to
`swing` - in the file the promotion gate reads and the sizer sizes real
positions from below 20 closed trades.

HOW. `absorbed_fills.json` restored a watermark of 10:38 into a process that
started at 15:18, so the first absorb pass replayed four and a half hours: the
duplicate buys from the M139 incident, the operator's MANUAL remediation sells
at 14:24-14:25, and the app's own current fills. Every one read as foreign,
because `_is_foreign_unrecorded` tests `_broker_order_ids` and `_orders` - both
in-memory, both empty after a restart. The 14:24 sells were then matched against
the lot opened at 15:19:36.

WHY THE GUARD IS AT THE MATCH AND NOT THE WATERMARK. The wide replay is what
M50 exists for - a stop that fired while the app was down arrives no other way,
and narrowing the window would break the feature that was working. The
discriminator is not the window's width, it is the arithmetic: in M50's
legitimate case the lot was opened in a PREVIOUS session and restored from
`open_position_entries.json`, so its `opened_at` precedes the exit. In the
corruption the lot was opened by THIS session, AFTER the exit it was matched to.

So the rule is arithmetic rather than a plausibility judgement, and it separates
the two cases exactly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

_OPENED = datetime(2026, 8, 24, 5, 19, 36, tzinfo=UTC)
# The operator's manual sell, an hour before the lot it was matched against.
_EXIT_BEFORE = datetime(2026, 8, 24, 4, 24, 45, tzinfo=UTC)
_EXIT_AFTER = _OPENED + timedelta(minutes=5)


def _ledger(tmp_path):
    """A TradeLedger with its own data_dir, per the standing constraint."""
    from qat.config import Settings
    from qat.domain.bus import EventBus
    from qat.domain.performance.trades import TradeLedger

    return TradeLedger(
        EventBus(), tmp_path, settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )


async def _open_lot(ledger, at: datetime, quantity: float = 3051.0) -> None:
    from qat.domain.events import OrderFilledEvent

    await ledger._on_fill(
        OrderFilledEvent(
            order_id="entry-1",
            symbol="TNE.AX",
            side="buy",
            quantity=quantity,
            price=32.74,
            ts=at,
            strategy="swing",
            stop_price=30.69,
        )
    )


async def _exit(ledger, at: datetime, quantity: float = 487.0) -> None:
    from qat.domain.events import OrderFilledEvent

    await ledger._on_fill(
        OrderFilledEvent(
            order_id="exit-1",
            symbol="TNE.AX",
            side="sell",
            quantity=quantity,
            price=32.52,
            ts=at,
        )
    )


async def test_an_exit_before_its_lot_records_no_trade(tmp_path, caplog):
    """THE test. This is the 24 August signature, and it produced seven rows."""
    ledger = _ledger(tmp_path)
    await _open_lot(ledger, _OPENED)

    with caplog.at_level("ERROR"):
        await _exit(ledger, _EXIT_BEFORE)

    assert ledger.closed_trades() == [], (
        "an exit that precedes its lot was recorded as a closed trade - "
        "this is the 24 August corruption"
    )
    assert (
        "REFUSED an impossible closed trade" in caplog.text
    ), "refused silently; the whole defect was that nobody was told"


async def test_the_lot_survives_the_refusal(tmp_path):
    """Refused, not consumed. The position is real and still held - dropping the
    lot as well would turn a bad record into a bad POSITION."""
    ledger = _ledger(tmp_path)
    await _open_lot(ledger, _OPENED)

    await _exit(ledger, _EXIT_BEFORE)

    assert ledger.open_lots("TNE.AX"), "the refusal consumed the lot it declined to close"


async def test_a_normal_exit_still_closes(tmp_path):
    """The guard must not have cost the feature. An exit AFTER its lot is the
    ordinary case and every closed trade this system will ever record."""
    ledger = _ledger(tmp_path)
    await _open_lot(ledger, _OPENED)

    await _exit(ledger, _EXIT_AFTER)

    trades = ledger.closed_trades()
    assert len(trades) == 1
    assert trades[0].quantity == 487.0
    assert trades[0].closed_at > trades[0].opened_at


async def test_the_m50_replay_still_works(tmp_path):
    """The case the wide replay exists for, and the one a narrower window would
    have broken: a stop that fired while the app was DOWN. The lot was opened in
    a previous session, so the exit is later and the arithmetic passes."""
    ledger = _ledger(tmp_path)
    yesterday = _OPENED - timedelta(days=1)
    await _open_lot(ledger, yesterday)

    # Absorbed on restart, stamped while the app was not running.
    await _exit(ledger, yesterday + timedelta(hours=3))

    assert len(ledger.closed_trades()) == 1, "the M50 startup replay was broken by the guard"


@pytest.mark.parametrize("skew_seconds", [0, 1])
async def test_a_simultaneous_exit_is_allowed(tmp_path, skew_seconds):
    """Equal stamps are not impossible - a same-instant fill is ordinary, and
    the comparison is strictly less-than for that reason. Only a genuinely
    EARLIER exit is refused."""
    ledger = _ledger(tmp_path)
    await _open_lot(ledger, _OPENED)

    await _exit(ledger, _OPENED + timedelta(seconds=skew_seconds))

    assert len(ledger.closed_trades()) == 1


async def test_an_adopted_lot_is_exempt(tmp_path):
    """The narrowing, and why it exists.

    An adopted lot has no strategy and its `opened_at` is a placeholder stamped
    at adoption time, because no entry record existed. An exit genuinely older
    than that placeholder is the legitimate M50 case - a position partially
    closed while this app was down - and refusing it would discard a real closed
    trade to prevent an imaginary one.

    `test_live_exit_price_correction` is what caught this: the first version of
    the guard compared timestamps alone and broke three of its tests.
    """
    from qat.domain.events import OrderFilledEvent

    ledger = _ledger(tmp_path)
    # Adopted: no strategy, opened_at stamped now rather than observed.
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="adopted",
            symbol="TNE.AX",
            side="buy",
            quantity=3051.0,
            price=32.74,
            ts=_OPENED,
            strategy=None,
        )
    )

    await _exit(ledger, _EXIT_BEFORE)

    assert (
        len(ledger.closed_trades()) == 1
    ), "an adopted lot was refused - this breaks the M50 startup replay"
