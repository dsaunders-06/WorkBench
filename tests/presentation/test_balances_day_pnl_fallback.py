"""Today's P/L must use the figure the rails use (item 46).

The Balances panel rendered "-" for Today's P/L on M142 while the decision
journal recorded day_pnl_pct 0.0031 the same session. Two different
computations:

  * `EquityMonitor.day_pnl_pct()` measures against a PERSISTED
    `day_start_equity`. It works, and it is what `AutonomyGate` gates on -
    `autonomous_pause_buys_below_day_pnl_pct` and
    `autonomous_halve_size_below_day_pnl_pct` both read it.
  * `AccountBalances.day_pnl` measures against `last_equity`, described in its
    own comment as "previous close, for the day's P&L". **IBKR never populates
    it** - `from_ib_account_values` does not set it - so on this broker the
    panel showed a dead computation while a working one sat beside it.

The panel now prefers the broker's own figure when there is one (Alpaca
supplies it) and falls back to the day-start basis otherwise, saying which it
used. The two are NOT the same measure - previous close versus this session's
first equity sample - so the panel must not silently present one as the other.
"""

from __future__ import annotations

from qat.presentation.balances_panel import day_pnl_from

_EQUITY = 1_004_286.0


def test_the_brokers_own_figure_wins_when_it_exists():
    change, pct, basis = day_pnl_from(
        broker_change=1_234.0, broker_pct=0.00123, equity=_EQUITY, day_start_equity=None
    )
    assert change == 1_234.0
    assert pct == 0.00123
    assert "close" in basis.lower()


def test_it_falls_back_to_the_day_start_basis():
    """The IBKR case: no broker figure, but the equity monitor has one."""
    change, pct, basis = day_pnl_from(
        broker_change=None, broker_pct=None, equity=_EQUITY, day_start_equity=1_000_000.0
    )
    assert change == 4_286.0
    assert pct is not None and abs(pct - 0.004286) < 1e-9
    assert "session" in basis.lower() or "start" in basis.lower()


def test_the_basis_is_NAMED_because_the_two_are_different_measures():
    """Previous close and this session's first sample are not the same thing.
    Presenting one under the other's label is the failure this fixes."""
    _, _, from_broker = day_pnl_from(
        broker_change=1.0, broker_pct=0.1, equity=_EQUITY, day_start_equity=1.0
    )
    _, _, from_start = day_pnl_from(
        broker_change=None, broker_pct=None, equity=_EQUITY, day_start_equity=1_000_000.0
    )
    assert from_broker != from_start


def test_neither_source_still_reports_nothing():
    """No fabricated zero. A day P&L of 0.00 is a claim, and an unknown one is
    not that claim."""
    change, pct, _ = day_pnl_from(
        broker_change=None, broker_pct=None, equity=_EQUITY, day_start_equity=None
    )
    assert change is None and pct is None


def test_a_zero_day_start_is_not_a_basis():
    """Division guard, and an equity of zero is not a day that started."""
    change, _, _ = day_pnl_from(
        broker_change=None, broker_pct=None, equity=_EQUITY, day_start_equity=0.0
    )
    assert change is None
