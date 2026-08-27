"""The symbol verdict must not be suppressed by a field IBKR never sets (item 47).

`AiAdvisorScreen._verdict` returns (None, None) when `day_pnl_pct` is unknown,
and that guard is RIGHT: its comment explains that a substituted 0.0 could
never trip the always-negative pause threshold, so an unreported -6% day would
read as "no rail here would refuse it" - M73's var_95=0.0 scar in the verdict.

The problem is the INPUT. It read `balances.day_pnl_pct`, which derives from
`last_equity` - an Alpaca-era "previous close" that `from_ib_account_values`
never sets. So on IBKR the value is ALWAYS None and the verdict has never
rendered in production, across two live sessions.

`EquityMonitor.day_pnl_pct()` measures against a persisted `day_start_equity`,
works on any broker, and is the figure `AutonomyGate` actually gates on. Using
it keeps the guard's reasoning intact - a real measured number, not a
fabricated zero - and makes the verdict agree with the rail it reports.
"""

from __future__ import annotations

from qat.presentation.advisory_account import resolve_day_pnl_pct


def test_the_brokers_figure_wins_when_it_exists():
    assert resolve_day_pnl_pct(broker_pct=-0.0123, monitor_pct=0.5) == -0.0123


def test_it_falls_back_to_the_monitors_figure_on_ibkr():
    """The live case: broker reports nothing, the monitor has a real number."""
    assert resolve_day_pnl_pct(broker_pct=None, monitor_pct=-0.0421) == -0.0421


def test_a_zero_from_the_monitor_is_a_real_zero():
    """0.0 from a measured basis is a fact, unlike a substituted 0.0. It must
    not be discarded as falsy."""
    assert resolve_day_pnl_pct(broker_pct=None, monitor_pct=0.0) == 0.0


def test_neither_source_still_yields_None():
    """The guard stays. Unknown remains unknown - the verdict is suppressed
    rather than computed from an assumption."""
    assert resolve_day_pnl_pct(broker_pct=None, monitor_pct=None) is None
