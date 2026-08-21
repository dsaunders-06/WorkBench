"""The Dashboard balances panel (spec M21)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qat.config import Settings
from qat.data.broker.account_poller import STALE_AFTER_SECONDS, AccountSnapshot
from qat.data.broker.adapter import AccountBalances
from qat.presentation.balances_panel import NOT_REPORTED, BalancesPanel
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime

# The live shape of a funded Alpaca paper account, including the fields it
# declines to report.
LIVE = AccountBalances(
    equity=100_481.55,
    last_equity=100_415.94,
    cash=69_845.06,
    long_market_value=30_636.49,
    short_market_value=0.0,
    buying_power=365_162.41,
    multiplier=4.0,
    initial_margin=15_318.25,
    maintenance_margin=9_190.95,
    currency="USD",
    status="ACTIVE",
    daytrade_count=None,
    pattern_day_trader=None,
)


def _snapshot(balances: AccountBalances = LIVE, **kwargs) -> AccountSnapshot:
    return AccountSnapshot(
        summary=None,
        balances=balances,
        positions=(),
        taken_at=kwargs.pop("taken_at", datetime.now(UTC)),
        error=kwargs.pop("error", None),
    )


def _panel(qtbot, reserve: float = 1.0) -> BalancesPanel:
    panel = BalancesPanel(reserve)
    qtbot.addWidget(panel)
    return panel


def test_the_headline_figures_are_rendered_as_money(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot())

    assert panel.portfolio_value._value.text() == "$100,481.55"
    assert panel.cash._value.text() == "$69,845.06"
    assert panel.long_value._value.text() == "$30,636.49"


def test_the_day_pnl_shows_amount_and_percentage(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot())

    assert panel.day_pnl._value.text() == "+65.61 (+0.07%)"


def test_a_losing_day_is_coloured_differently_from_a_winning_one(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot())
    winning = panel.day_pnl._value.styleSheet()
    panel.update_from(_snapshot(AccountBalances(equity=99_000.0, last_equity=100_000.0)))
    losing = panel.day_pnl._value.styleSheet()

    assert winning != losing
    assert panel.day_pnl._value.text().startswith("-1,000.00")


def test_buying_power_carries_its_multiplier(qtbot):
    """Seeing 365k next to an order refused for insufficient cash is the most
    confusing thing about running this beside the broker's own screen."""
    panel = _panel(qtbot)

    panel.update_from(_snapshot())

    assert panel.buying_power._value.text() == "$365,162.41  (4x)"


def test_spendable_cash_is_shown_and_is_far_below_buying_power(qtbot):
    panel = _panel(qtbot, reserve=1.0)

    panel.update_from(_snapshot())

    assert panel.spendable._value.text() == "$69,844.06"


def test_the_reserve_is_deducted_from_spendable_cash(qtbot):
    panel = _panel(qtbot, reserve=5_000.0)

    panel.update_from(_snapshot())

    assert panel.spendable._value.text() == "$64,845.06"


def test_unreported_fields_render_as_a_dash_not_zero(qtbot):
    """ "Not reported" and zero are different claims. This used to be asserted
    on the day-trade count, which was removed from the panel on 21 August; the
    PROPERTY is not about that field, so it is asserted on the two that remain
    and can genuinely be absent."""
    panel = _panel(qtbot)

    panel.update_from(_snapshot(AccountBalances(currency="AUD")))

    assert panel.account_status._value.text() == NOT_REPORTED
    assert panel.day_pnl._value.text() == NOT_REPORTED


# REMOVED 21 August 2026: test_a_pattern_day_trader_flag_is_called_out.
#
# Its subject was the "Day trades (5d)" cell, which no longer exists. It was
# not failing and it was not wrong - it guarded a real behaviour of a field that
# IBKR never fills and that belongs to a US pattern-day-trader rule with no
# application to an ASX account. Recorded here rather than deleted silently,
# because a test disappearing from a safety-conscious suite should say whether
# it was retired or lost.


def test_a_blocked_account_is_unmistakable(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot(AccountBalances(status="ACTIVE", trading_blocked=True)))

    assert panel.account_status._value.text() == "BLOCKED"


def test_an_empty_snapshot_renders_dashes_rather_than_zeros(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot(AccountBalances()))

    assert panel.portfolio_value._value.text() == NOT_REPORTED
    assert panel.cash._value.text() == NOT_REPORTED
    assert panel.spendable._value.text() == NOT_REPORTED


# --- freshness ---------------------------------------------------------------


def test_a_fresh_reading_shows_its_time(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot())

    assert panel.freshness.text().startswith("as of")


def test_a_stale_reading_says_so(qtbot):
    panel = _panel(qtbot)
    old = datetime.now(UTC) - timedelta(seconds=STALE_AFTER_SECONDS + 10)

    panel.update_from(_snapshot(taken_at=old))

    assert "STALE" in panel.freshness.text()


def test_a_broker_error_is_shown_beside_the_last_good_reading(qtbot):
    panel = _panel(qtbot)

    panel.update_from(_snapshot(error="rate limited"))

    assert "rate limited" in panel.freshness.text()
    # The figures are still the last good ones rather than blanked.
    assert panel.portfolio_value._value.text() == "$100,481.55"


# --- on the Dashboard --------------------------------------------------------


async def test_the_dashboard_shows_balances_instead_of_a_nav_tile(qtbot):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    dashboard = DashboardScreen(runtime)
    qtbot.addWidget(dashboard)

    await dashboard._refresh()

    assert dashboard.balances_panel.portfolio_value._value.text().startswith("$")
    assert not hasattr(dashboard, "nav_tile")


async def test_the_risk_tiles_survive_the_rework(qtbot):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    dashboard = DashboardScreen(runtime)
    qtbot.addWidget(dashboard)

    await dashboard._refresh()

    assert dashboard.var_tile is not None
    assert dashboard.sharpe_tile is not None
    assert dashboard.drawdown_tile is not None


async def test_the_dashboard_reads_through_the_shared_poller(qtbot):
    """Not straight off the broker: several screens refreshing on the same tick
    would otherwise each issue their own request."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))
    dashboard = DashboardScreen(runtime)
    qtbot.addWidget(dashboard)

    await dashboard._refresh()
    first = await runtime.account_poller.snapshot()
    await dashboard._refresh()
    second = await runtime.account_poller.snapshot()

    assert first.taken_at == second.taken_at  # served from cache, not refetched
