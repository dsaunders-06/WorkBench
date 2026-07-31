"""Cost drag in the performance statistics (M28).

Every metric here is net. The gross figure and the costs are kept beside it so
the gap is a number the operator can act on rather than an adjustment applied
somewhere out of sight.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qat.domain.performance.metrics import compute_stats
from qat.domain.performance.trades import ClosedTrade

_BASE = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)


# --- Cost drag (M28) -------------------------------------------------------


def test_stats_report_gross_costs_and_the_drag_between_them():
    """Subtracting costs without showing them answers "how did we do" while
    hiding the one lever fully under the operator's control."""
    trades = [
        ClosedTrade(
            symbol="AAA",
            strategy="swing",
            quantity=10,
            entry_price=100.0,
            exit_price=110.0,
            stop_price=95.0,
            opened_at=_BASE,
            closed_at=_BASE,
            entry_cost=6.0,
            exit_cost=6.0,
        )
    ]

    stats = compute_stats(trades)

    assert stats.gross_pnl == pytest.approx(100.0)
    assert stats.total_costs == pytest.approx(12.0)
    assert stats.total_pnl == pytest.approx(88.0)
    assert stats.cost_drag == pytest.approx(0.12)


def test_cost_drag_is_none_when_gross_is_not_positive():
    """There is no meaningful ratio between a fee and a loss, and printing one
    invites the wrong conclusion."""
    trades = [
        ClosedTrade(
            symbol="AAA",
            strategy="swing",
            quantity=10,
            entry_price=100.0,
            exit_price=90.0,
            stop_price=95.0,
            opened_at=_BASE,
            closed_at=_BASE,
            entry_cost=6.0,
            exit_cost=6.0,
        )
    ]

    assert compute_stats(trades).cost_drag is None
