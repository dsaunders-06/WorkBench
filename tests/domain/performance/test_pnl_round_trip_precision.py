"""A trade written and read back must report the same P&L.

⚠️ MEASURED 10 September 2026 on the live ledger. IAG.AX, 6,699 shares, true
entry ~7.92697, written as `round(entry_price, 4)` = 7.9270:

    stored gross_pnl        -1,721.44
    (exit - entry) x qty    -1,721.643      <- what every report actually uses
                                     0.203

`ClosedTrade.gross_pnl` and `net_pnl` are DERIVED properties and `from_row`
recomputes them deliberately - *"everything else on this class is derived, and
recomputing it is the point"*. That design is correct and the SEK repair proves
it: when a ledger is repaired, prices are corrected, and an app that trusted a
stored P&L column would carry the old number forever.

**So the fix is not to trust the column. It is to stop losing the price.** The
error scales with SHARE COUNT - twenty cents on 6,699 shares, and TAH is 64,229.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.domain.performance.trades import ClosedTrade


def _trade(entry: float, quantity: float) -> ClosedTrade:
    return ClosedTrade(
        symbol="IAG.AX",
        strategy="swing",
        quantity=quantity,
        entry_price=entry,
        exit_price=7.67,
        stop_price=7.28,
        opened_at=datetime(2026, 8, 25, tzinfo=UTC),
        closed_at=datetime(2026, 9, 9, tzinfo=UTC),
        entry_cost=73.28,
        exit_cost=70.91,
    )


@pytest.mark.parametrize(
    ("entry", "quantity"),
    [
        (7.9269786, 6699.0),  # the live IAG row
        (1.0490135, 64229.0),  # TAH's share count, where the error is worst
        (14.8836, 2978.0),  # SEK, which happened to round cleanly
    ],
)
def test_pnl_survives_the_csv_round_trip(entry: float, quantity: float) -> None:
    original = _trade(entry, quantity)

    restored = ClosedTrade.from_row({k: str(v) for k, v in original.as_row().items()})

    assert restored is not None
    # To the CENT. The ledger is a financial record and a report derived from it
    # must not disagree with it in the currency it is denominated in.
    assert restored.gross_pnl == pytest.approx(original.gross_pnl, abs=0.005)
    assert restored.net_pnl == pytest.approx(original.net_pnl, abs=0.005)


def test_the_stored_column_agrees_with_the_derivation() -> None:
    """⚠️ The two must not be allowed to drift. The column is what a human reads
    in the CSV; the derivation is what every metric uses."""
    trade = _trade(7.9269786, 6699.0)
    row = trade.as_row()

    restored = ClosedTrade.from_row({k: str(v) for k, v in row.items()})

    assert restored is not None
    assert float(row["gross_pnl"]) == pytest.approx(restored.gross_pnl, abs=0.005)
    assert float(row["net_pnl"]) == pytest.approx(restored.net_pnl, abs=0.005)
