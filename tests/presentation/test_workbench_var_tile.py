"""The Workbench VaR tile measured the last DECISION, not the book.

Same root cause as the Risk Console tiles: `portfolio_check` is written one rail
after the governor's position-count refusal, so at 10 of 10 it is never written,
and the audit log is in-memory so it is empty at startup regardless. This tile
now reads the book actually held. No side-by-side here - one summary tile on a
crowded screen; the Risk Console carries the comparison.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from qat.config import Settings
from qat.data.broker.account_poller import AccountBalances, AccountSnapshot
from qat.domain.risk_engine.book_risk import BookRisk
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime


def _book_risk(**overrides) -> BookRisk:
    base = dict(
        computed_at=datetime.now(UTC),
        symbols=10,
        observations=299,
        var_95=0.011,
        var_99=0.015,
        es_975=0.017,
        single_name_pct=0.12,
        sector_pct=0.15,
        notes=(),
    )
    base.update(overrides)
    return BookRisk(**base)


class _Monitor:
    name = "book-risk-monitor"

    def __init__(self, value):
        self._value = value

    def fresh(self, now=None):
        return self._value


def _seed_snapshot(runtime: Runtime) -> None:
    """`_refresh` awaits `account_poller.snapshot()` on its way to the VaR
    tile. Seeding the cache AND its fetch time is what makes the throttle's
    own freshness check treat it as current (account_poller.py's
    `fresh_enough`), so `snapshot()` returns this immediately rather than
    exercising the demo broker for a test that is about the VaR tile, not the
    balances it passes on the way there.
    """
    runtime.account_poller._snapshot = AccountSnapshot(
        summary=None,
        balances=AccountBalances(cash=0.0, buying_power=0.0, equity=100_000.0),
        positions=(),
        taken_at=datetime.now(UTC),
    )
    runtime.account_poller._fetched_at = time.monotonic()


def _build(qtbot, tmp_path, book_risk) -> DashboardScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    runtime.book_risk_monitor = _Monitor(book_risk)
    _seed_snapshot(runtime)
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)
    # test_risk_tiles_read_the_live_book.py hit this first, on the Risk
    # Console: __init__ subscribes a bound method on runtime.bus, a strong
    # reference back to this screen that cycles with screen.runtime and is
    # broken only by the cyclic GC - so an unstopped 2s QTimer can survive
    # this test and fire during a LATER, unrelated one. Every test here
    # drives `_refresh` directly, never by waiting on the timer, so stopping
    # it is exactly scoped to the actual cause.
    screen._timer.stop()
    return screen


async def test_the_var_tile_reads_the_live_book(qtbot, tmp_path):
    dashboard = _build(qtbot, tmp_path, _book_risk())

    await dashboard._refresh()

    assert dashboard.var_tile._value.text() == "1.10%"


async def test_the_var_tile_shows_a_dash_with_no_live_measurement(qtbot, tmp_path):
    dashboard = _build(qtbot, tmp_path, None)

    await dashboard._refresh()

    assert dashboard.var_tile._value.text() == "-"
