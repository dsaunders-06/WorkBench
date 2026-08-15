"""The Dashboard's positions table (positions panel brief, piece 5).

Replaces the three-column Symbol/Quantity/Avg Price table with the nine
columns an operator used to spend an hour hand-computing: what was paid, how
it is tracking, how close it is to being sold, and what is stopping it.

Built through the real `DashboardScreen._refresh`, the same path production
uses, rather than by calling a populate method directly - the M87 class of
defect (a widget that renders correctly in a logic test and wrong on screen)
is only caught by driving the thing that actually runs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Position
from qat.domain.oms.signal_bridge import _Entry
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime

_SYMBOL_COL, _QTY_COL, _ENTRY_COL, _LAST_COL, _PNL_COL = 0, 1, 2, 3, 4
_EXIT_COL, _STOP_COL, _RISK_COL, _STATUS_COL = 5, 6, 7, 8


class _StubBroker:
    """Only the two calls AccountPoller makes: account() and positions(). No
    `balances()`, so AccountPoller falls back to `balances_from_summary` -
    the same path a mock or minimally-implemented adapter takes in
    production."""

    def __init__(self, positions: list[Position]) -> None:
        self._positions = positions

    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=50_000.0, buying_power=50_000.0)

    async def positions(self) -> list[Position]:
        return self._positions


def _runtime(tmp_path, positions: list[Position], **settings_kwargs) -> Runtime:
    # Every test that builds an OMS passes its own data_dir: `isolate_data_dir`
    # (tests/conftest.py) is session-scoped, so without this every test in the
    # session would share one entries file, one decision journal, one trade
    # ledger - and a later test would restore lots and read entries a
    # different test wrote.
    settings = Settings(_env_file=None, data_dir=str(tmp_path), **settings_kwargs)
    return Runtime.build_demo(settings=settings, broker=_StubBroker(positions))


async def test_the_positions_table_has_nine_columns(qtbot, tmp_path):
    runtime = _runtime(tmp_path, [])
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    assert screen.positions_table.columnCount() == 9


async def test_a_position_with_no_entry_record_renders_an_em_dash_not_a_number(qtbot, tmp_path):
    """No entry record means the app's own price is unknown - do not fall
    back to the broker's avg_price, and do not show a zero."""
    positions = [Position(symbol="AAA", quantity=100.0, avg_price=91.18)]
    runtime = _runtime(tmp_path, positions)
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    await screen._refresh()

    assert screen.positions_table.rowCount() == 1
    entry_item = screen.positions_table.item(0, _ENTRY_COL)
    assert entry_item is not None
    assert entry_item.text() == "—"  # em dash
    assert "91.18" not in entry_item.text()

    pnl_item = screen.positions_table.item(0, _PNL_COL)
    assert pnl_item is not None
    assert pnl_item.text() == "—"


async def test_a_blocked_position_shows_its_blocker_text(qtbot, tmp_path):
    """A symbol with no resting stop must show the alarming blocker in the
    Status column - and be coloured DANGER, since this is the same class of
    fact the adopted-positions banner already treats as urgent."""
    positions = [Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)]
    runtime = _runtime(tmp_path, positions)
    runtime.signal_bridge._entries["AAA"] = _Entry(
        opened_at=datetime(2020, 1, 1, tzinfo=UTC),
        price=100.0,
        stop_price=90.0,
        target_price=None,
        strategy="swing",
    )
    # Deliberately nothing written to runtime.oms._position_stops: "AAA" has
    # no resting stop, which is the condition being tested.
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    await screen._refresh()

    status_item = screen.positions_table.item(0, _STATUS_COL)
    assert status_item is not None
    assert "no stop resting" in status_item.text()


async def test_an_unblocked_position_has_a_blank_status(qtbot, tmp_path):
    positions = [Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)]
    runtime = _runtime(
        tmp_path, positions, enforce_min_holding_period=False, enforce_time_stop=False
    )
    runtime.signal_bridge._entries["AAA"] = _Entry(
        opened_at=datetime(2020, 1, 1, tzinfo=UTC),
        price=100.0,
        stop_price=90.0,
        target_price=None,
        strategy="swing",
    )
    runtime.oms._position_stops["AAA"] = 90.0
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    await screen._refresh()

    status_item = screen.positions_table.item(0, _STATUS_COL)
    assert status_item is not None
    assert status_item.text() == ""


async def test_every_cell_carries_a_tooltip_with_its_full_text(qtbot, tmp_path):
    """M87: a label too narrow for its column must still be readable, one
    hover away."""
    positions = [Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)]
    runtime = _runtime(tmp_path, positions)
    runtime.signal_bridge._entries["AAA"] = _Entry(
        opened_at=datetime(2020, 1, 1, tzinfo=UTC),
        price=100.0,
        stop_price=90.0,
        target_price=None,
        strategy="swing",
    )
    runtime.oms._position_stops["AAA"] = 90.0
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)

    await screen._refresh()

    for col in range(screen.positions_table.columnCount()):
        item = screen.positions_table.item(0, col)
        assert item is not None
        assert item.toolTip() == item.text()
