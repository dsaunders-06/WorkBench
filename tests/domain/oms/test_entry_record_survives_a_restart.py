"""A restored lot keeps the price it was SIZED against (M44).

M44 says the execution-quality instrument exists and only trade count is
missing. ⚠️ **That premise is false in practice.** All six closed trades on
28 August carry an EMPTY `entry_slippage`, and they would still be empty at
twenty trades:

    entry_slippage   (empty on all 6)
    reference_price  (empty on all 6)

`ClosedTrade.entry_slippage` returns `None` whenever `reference_price` is
missing, and `open_position_entries.json` stores only
`opened_at, price, stop_price, target_price, strategy`. So every restart
discards it, and this app restarts most days.

⚠️ **THIS IS THE THIRD TIME THIS DATACLASS HAS LOST A FIELD ACROSS A RESTART**,
and the previous two are recorded in its own comments:

* M33 - `target_price` was not stored, so "six positions came back with
  downside protection and no way to bank a gain".
* M49 - `strategy` was not stored, so a restored lot "would rebuild the trade
  and still not count towards anything".

Same shape, third occurrence. What is persisted is what survives, and the test
below is anchored on that rather than on the three field names.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.domain.oms.signal_bridge import PositionEntry, _Entry


def test_the_entry_record_carries_the_reference_price() -> None:
    """The price the order was SIZED against. Without it `entry_slippage` is
    None, which is the whole of M44's instrument."""
    assert "reference_price" in _Entry.__dataclass_fields__
    assert "reference_price" in PositionEntry.__dataclass_fields__


def test_the_public_view_exposes_every_stored_field() -> None:
    """⚠️ Anchored on the SHAPE, not on a list of names. `PositionEntry` is the
    read-only view of `_Entry`, and a field added to one and not the other is
    exactly how M33 and M49 happened - the record grew and something that reads
    it did not."""
    private = set(_Entry.__dataclass_fields__)
    public = set(PositionEntry.__dataclass_fields__)

    assert private == public, (
        f"the stored record and its public view disagree: only in _Entry "
        f"{sorted(private - public)}, only in PositionEntry {sorted(public - private)}"
    )


def test_a_reference_price_round_trips_through_the_public_view() -> None:
    entry = _Entry(
        opened_at=datetime(2026, 8, 24, tzinfo=UTC),
        price=32.9782546,
        stop_price=30.69,
        target_price=36.86,
        strategy="swing",
        reference_price=32.90,
    )

    view = PositionEntry(**{f: getattr(entry, f) for f in _Entry.__dataclass_fields__})

    assert view.reference_price == 32.90


def test_an_older_record_without_it_still_loads() -> None:
    """⚠️ `open_position_entries.json` on disk has records written before this
    field existed. They must restore as `None` - unknown - never as the entry
    price, which would report zero slippage on a trade nobody measured."""
    entry = _Entry(
        opened_at=datetime(2026, 8, 24, tzinfo=UTC),
        price=32.9782546,
        stop_price=30.69,
    )

    assert entry.reference_price is None


def test_the_reference_price_is_persisted_and_read_back(tmp_path) -> None:
    """⚠️ THE WIRING, which the dataclass tests above do not touch. A field on
    the record that is never written is inert - the shape of items 59, 67 and
    Milestone C's Task 1 this same week.

    Read from source rather than by driving the bridge: constructing one needs a
    bus, an OMS, an aggregator and an earnings calendar, and what is guarded
    here is that three specific lines exist - the construct, the write and the
    read.
    """
    from pathlib import Path

    import qat

    source = (Path(qat.__file__).parent / "domain" / "oms" / "signal_bridge.py").read_text(
        encoding="utf-8"
    )

    assert "reference_price=event.reference_price" in source, (
        "the fill event carries reference_price and the bridge drops it, so it never "
        "reaches the record"
    )
    assert (
        '"reference_price": entry.reference_price' in source
    ), "the record holds it and _save_entries does not write it, so it dies at restart"
    assert (
        'row.get("reference_price")' in source
    ), "it is written and never read back, which is the same loss one launch later"


def test_the_fill_event_still_carries_it() -> None:
    """The upstream half. It has been on OrderFilledEvent since M37 - the bridge
    was simply dropping it - so this pins the source rather than assuming it."""
    from qat.domain.events import OrderFilledEvent

    assert "reference_price" in OrderFilledEvent.__dataclass_fields__
