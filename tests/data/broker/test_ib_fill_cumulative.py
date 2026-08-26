"""A BrokerFill from IBKR carries the order's CUMULATIVE filled quantity and
CUMULATIVE AVERAGE fill price.

IBKR returns one Fill per EXECUTION, each with its own `shares` and `price`.
Every consumer of BrokerFill.quantity/price subtracts or blends against a
stored cumulative, so per-execution figures discard fills, or worse, record
the wrong realised price, silently.

Measured 26 August 2026: LOV.AX order 1216552509 filled 3,217 shares in 183
executions. With `shares`, only executions setting a new running maximum were
absorbed - 374 reached the ledger and 2,843 did not. `price` has the same
defect and the same fix: `avgPrice`, not `price`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from qat.data.broker.ib_translate import from_ib_fill


def _fill(shares: float, cum_qty: float, price: float = 28.45, avg_price: float | None = None):
    """The shape ib_async returns: Fill(contract=..., execution=...).

    `avg_price` defaults to `price` so every call written before this
    parameter existed still exercises a fill whose execution price and
    cumulative average happen to coincide - which is exactly the condition
    that hid the `price` defect until a genuinely multi-price fill was
    measured live.
    """
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="LOV"),
        execution=SimpleNamespace(
            execId="x",
            permId=1216552509,
            side="SLD",
            shares=shares,
            cumQty=cum_qty,
            price=price,
            avgPrice=avg_price if avg_price is not None else price,
            time=datetime(2026, 8, 26, 0, 6, 31, tzinfo=UTC),
        ),
    )


def test_quantity_is_the_cumulative_not_the_execution():
    """The execution moved 25 shares; the ORDER has now filled 35."""
    out = from_ib_fill(_fill(shares=25.0, cum_qty=35.0), "ASX")

    assert out is not None
    assert out.quantity == 35.0, (
        f"got {out.quantity} - that is this execution's own size, and every "
        "consumer will treat it as the order's running total"
    )


def test_the_last_execution_carries_the_whole_order():
    """The real LOV order's final execution: 3 shares, cumulative 3,217."""
    out = from_ib_fill(_fill(shares=3.0, cum_qty=3217.0), "ASX")

    assert out is not None
    assert out.quantity == 3217.0


def test_price_is_the_cumulative_average_not_the_execution_price():
    """The execution itself filled at 30.00; the ORDER's running average is
    28.75 - the blend of an earlier, larger piece filled at 28.00. A
    per-execution price here would read 30.00, and `OMS._unabsorbed_part`
    would then blend it against the PRIOR average as though it were itself a
    running average, recovering the wrong price for the next increment."""
    out = from_ib_fill(_fill(shares=1217.0, cum_qty=3217.0, price=30.00, avg_price=28.75), "ASX")

    assert out is not None
    assert out.price == 28.75, (
        f"got {out.price} - that is this execution's own fill price, and "
        "OMS._unabsorbed_part will treat it as the order's cumulative average"
    )


def test_the_symbol_is_still_translated_back():
    """Unchanged behaviour, pinned because this task edits the same return."""
    out = from_ib_fill(_fill(shares=10.0, cum_qty=10.0), "ASX")

    assert out is not None
    assert out.symbol == "LOV.AX"
    assert out.order_id == "1216552509"
    assert out.side == "sell"
