"""One position exiting in five fills was counted as five trades.

⚠️ MEASURED IN THE LIVE LEDGER, 7 September 2026. Five LOV.AX rows share one
`opened_at`, one `order_id` (1216552509), and closed within 25 seconds of each
other in quantities 10 / 15 / 26 / 323 / 2843. That is ONE position filling its
target in pieces, written as five closed trades.

⚠️ THE SAMPLE-SIZE GATES COUNT ROWS. `edge_min_trades = 20` is what stops the
sizer using invented constants (win rate 0.55, payoff 1.5), and it counts what
`closed_trades()` returns. One fragmented exit yielded five, so the gate flips
from "default" to "measured" on an unpredictable fraction of twenty real trades
- the protection against acting on too small a sample is itself miscounting.
The promotion gate at thirty reads the same list.

⚠️ AND EVERY STATISTIC DERIVED FROM THEM IS DISTORTED. The live ledger reported
9 trades, 55.6% win rate, 0.47 payoff. Collapsed to distinct positions it is
5 trades, 40% win rate, 0.87 payoff - different numbers from identical data,
because four winning fragments of one position outvoted three whole losers.

A merged position must reproduce the totals exactly: `net_pnl`, `gross_pnl` and
`r_multiple` are computed properties over quantity, prices and costs, so summing
quantity and cost and taking a QUANTITY-WEIGHTED average price is the only
merge that leaves the arithmetic unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.domain.performance.trades import ClosedTrade, collapse_to_positions

_OPENED = datetime(2026, 8, 25, 0, 28, 52, tzinfo=UTC)


def _fill(quantity: float, exit_price: float, *, seconds: int, order_id: str = "1216552509"):
    return ClosedTrade(
        symbol="LOV.AX",
        strategy="swing",
        quantity=quantity,
        entry_price=30.0,
        exit_price=exit_price,
        stop_price=27.0,
        opened_at=_OPENED,
        closed_at=_OPENED + timedelta(days=1, seconds=seconds),
        order_id=order_id,
        market="ASX",
    )


def test_five_fills_of_one_position_are_one_trade() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR - the real LOV.AX shape."""
    fills = [
        _fill(10.0, 33.5, seconds=1),
        _fill(15.0, 33.7, seconds=14),
        _fill(26.0, 33.9, seconds=15),
        _fill(323.0, 34.1, seconds=26),
        _fill(2843.0, 34.2, seconds=26),
    ]

    positions = collapse_to_positions(fills)

    assert len(positions) == 1
    assert positions[0].quantity == 3217.0


def test_the_merged_position_keeps_the_same_money() -> None:
    """⚠️ The merge must not move a cent. A quantity-weighted exit price is the
    only average that reproduces the total."""
    fills = [_fill(100.0, 33.0, seconds=1), _fill(300.0, 35.0, seconds=2)]

    merged = collapse_to_positions(fills)[0]

    assert merged.net_pnl == sum(f.net_pnl for f in fills)
    assert merged.gross_pnl == sum(f.gross_pnl for f in fills)


def test_separate_positions_in_one_symbol_stay_separate() -> None:
    """Two real trades in the same name are two trades. Grouping on symbol
    alone would merge a round trip in August with one in September."""
    fills = [_fill(100.0, 33.0, seconds=1), _fill(100.0, 33.0, seconds=1, order_id="other")]

    assert len(collapse_to_positions(fills)) == 2


def test_rows_without_an_order_id_are_not_merged_together() -> None:
    """⚠️ Older rows predate `order_id`. A missing id is NOT evidence that two
    trades are the same one - merging on it would silently combine unrelated
    history, so each stands alone."""
    a = _fill(100.0, 33.0, seconds=1, order_id=None)
    b = ClosedTrade(
        symbol="LOV.AX",
        strategy="swing",
        quantity=50.0,
        entry_price=30.0,
        exit_price=33.0,
        stop_price=27.0,
        opened_at=_OPENED + timedelta(days=9),
        closed_at=_OPENED + timedelta(days=10),
        order_id=None,
        market="ASX",
    )

    assert len(collapse_to_positions([a, b])) == 2


def test_the_earliest_open_and_latest_close_survive() -> None:
    """Holding period is entry to final exit, not to the first partial."""
    fills = [_fill(10.0, 33.0, seconds=1), _fill(90.0, 33.0, seconds=600)]

    merged = collapse_to_positions(fills)[0]

    assert merged.opened_at == _OPENED
    assert merged.closed_at == _OPENED + timedelta(days=1, seconds=600)


def test_an_empty_ledger_collapses_to_nothing() -> None:
    assert collapse_to_positions([]) == []


class _LedgerOfFragments:
    """A ledger holding ONE position that closed in five fills."""

    def __init__(self, order_id: str = "1216552509") -> None:
        self._rows = [
            _fill(10.0, 33.5, seconds=1, order_id=order_id),
            _fill(15.0, 33.7, seconds=14, order_id=order_id),
            _fill(26.0, 33.9, seconds=15, order_id=order_id),
            _fill(323.0, 34.1, seconds=26, order_id=order_id),
            _fill(2843.0, 34.2, seconds=26, order_id=order_id),
        ]

    def closed_trades(self, strategy=None, market=None):
        return list(self._rows)


def test_the_sizer_gate_counts_positions_not_fills() -> None:
    """⚠️ THE CONSEQUENCE THAT REACHES REAL MONEY. `edge_min_trades` is what
    keeps the sizer on its priors until there is a real sample. Five fills of
    ONE position must count as one, or the gate opens early on evidence that
    does not exist."""
    from qat.config import Settings
    from qat.domain.performance.edge import EdgeEstimator

    settings = Settings(_env_file=None, edge_min_trades=5, market="ASX")
    edge = EdgeEstimator(_LedgerOfFragments(), settings=settings)

    result = edge.estimate("swing")

    assert result.trade_count == 1, "five fills of one position counted as five trades"
    assert result.source == "default", "the gate opened on one real trade"
