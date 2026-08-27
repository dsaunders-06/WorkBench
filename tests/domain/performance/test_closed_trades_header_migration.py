"""A ledger header written once must not outlive the schema (item 63).

Found 27 August after the close. `closed_trades.csv` had a 30-field header and
32-field rows, because `_record` writes the header only when the file is NEW and
then appends under the current `_FIELDS` forever. Every field added since the
file was created was written into rows and never named.

Read back the way the app reads it:

    market   = ''     should be 'ASX'
    currency = ''     should be 'AUD'
    order_id = None   the key does not exist
    restkey  = ['AUD', '1216558924']

⚠️ **The cost is `EdgeEstimator`.** It filters `closed_trades(market=...)` on a
strict `trade.market == market`, so with every restored row carrying
`market=None` it matches nothing at 6 trades and nothing at 200 - the sizer
stays on its invented constants permanently, reporting "default" for a reason
that has nothing to do with sample size.

⚠️ **The rows are read POSITIONALLY here, never with `DictReader`.** Under a
stale header the surplus values land in the restkey, and a rewrite driven by
`DictWriter` would silently drop them - turning a mislabelling into data loss.
That is the trap this migration exists to walk past, so it is what the tests
pin.
"""

from __future__ import annotations

import csv

import pytest

from qat.domain.performance.trades import _FIELDS, TradeLedger


def _stale_file(path, drop: bool = True):
    """The shape actually found on disk, not a convenient approximation.

    ⚠️ The live header was missing MIDDLE fields as well as a trailing one -
    `earnings_at_entry` and `held_through_earnings` were added between
    `best_price` and `market`, and `order_id` after `currency`. That is why
    `market` read back as `""` rather than raising: the NAME was still in the
    header, pointing three columns to its left.

    An earlier version of this fixture just truncated the tail. It reproduced a
    KeyError, which is a different and more obvious failure than the silent
    mislabelling that actually happened - and a fix tested against it would not
    have been tested against this.
    """
    missing = {"earnings_at_entry", "held_through_earnings", "order_id"}
    header = [f for f in _FIELDS if f not in missing] if drop else list(_FIELDS)
    row = [""] * len(_FIELDS)
    row[_FIELDS.index("symbol")] = "RHC.AX"
    row[_FIELDS.index("strategy")] = "swing"
    row[_FIELDS.index("quantity")] = "1194.0"
    row[_FIELDS.index("market")] = "ASX"
    row[_FIELDS.index("currency")] = "AUD"
    row[_FIELDS.index("order_id")] = "1216558924"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerow(row)
    return row


def test_the_stale_shape_is_what_we_think_it_is(tmp_path) -> None:
    """The fixture reproduces the defect before anything is asserted about the
    fix - or the tests below could pass against a file that never had it."""
    path = tmp_path / "closed_trades.csv"
    _stale_file(path)

    with path.open(encoding="utf-8", newline="") as handle:
        row = next(iter(csv.DictReader(handle)))

    assert row["market"] == ""
    assert row.get("order_id") is None
    assert row.get(None) is not None, "the surplus values should be stranded in the restkey"


def test_a_stale_header_is_repaired(tmp_path) -> None:
    path = tmp_path / "closed_trades.csv"
    _stale_file(path)

    TradeLedger.repair_header(path)

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == list(_FIELDS)


def test_repair_does_not_lose_or_move_a_single_value(tmp_path) -> None:
    """The whole risk. A `DictReader`-driven rewrite would drop the restkey."""
    path = tmp_path / "closed_trades.csv"
    original = _stale_file(path)

    TradeLedger.repair_header(path)

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 2, "a row was lost or invented"
    assert rows[1] == original, "a value moved column"


def test_the_values_now_read_back_under_their_own_names(tmp_path) -> None:
    """The point of the exercise: `market` is what `EdgeEstimator` filters on."""
    path = tmp_path / "closed_trades.csv"
    _stale_file(path)

    TradeLedger.repair_header(path)

    with path.open(encoding="utf-8", newline="") as handle:
        row = next(iter(csv.DictReader(handle)))
    assert row["market"] == "ASX"
    assert row["currency"] == "AUD"
    assert row["order_id"] == "1216558924"
    assert row.get(None) is None, "nothing should be left in the restkey"


def test_a_correct_header_is_left_alone(tmp_path) -> None:
    """Rewriting a file that does not need it is gratuitous risk on the only
    record of realised P&L there is."""
    path = tmp_path / "closed_trades.csv"
    _stale_file(path, drop=False)
    before = path.read_bytes()

    assert TradeLedger.repair_header(path) is False
    assert path.read_bytes() == before


def test_a_row_WIDER_than_the_schema_is_refused(tmp_path) -> None:
    """⚠️ The migration assumes `_FIELDS` only ever GREW by appending, which is
    what makes a short row a prefix and a positional remap safe. A row wider
    than the schema breaks that assumption - fields were removed or reordered -
    and remapping it would move values between columns. Refuse loudly."""
    path = tmp_path / "closed_trades.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(_FIELDS[:-1]))
        writer.writerow([""] * (len(_FIELDS) + 1))

    with pytest.raises(ValueError, match="wider"):
        TradeLedger.repair_header(path)


def test_a_missing_file_is_not_an_error(tmp_path) -> None:
    assert TradeLedger.repair_header(tmp_path / "nothing.csv") is False
