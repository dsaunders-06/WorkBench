"""The console is the only place an operator can say a difference is explained.

If the control does not reach the store, the whole seam is unreachable in the
running application - which is the M58a failure exactly: a first-run dialog
that told the operator their choice decided something, and decided nothing.
A control is built here only because something consumes it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.config import Settings
from qat.data.broker.account_poller import AccountBalances, AccountSnapshot
from qat.data.broker.adapter import Position
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _build_screen(qtbot, tmp_path) -> tuple[RiskConsoleScreen, Runtime]:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime


def _seed_broker_positions(runtime: Runtime, positions: dict[str, float]) -> None:
    """The console reads the poller's cached snapshot rather than awaiting one.

    Seeded here because the declare action must bind to what the BROKER says,
    and a test that let it fall back to zero would be asserting the wrong
    binding.
    """
    runtime.account_poller._snapshot = AccountSnapshot(
        summary=None,
        balances=AccountBalances(cash=0.0, buying_power=0.0, equity=0.0),
        positions=tuple(
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in positions.items()
        ),
        taken_at=datetime.now(UTC),
    )


def test_declaring_reaches_the_store(qtbot, tmp_path):
    """The seam is only real if this call arrives."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"CRWD": 64.0})
    assert runtime.oms.anomalies.is_quarantined("CRWD") is False

    screen._declare_anomaly("CRWD", reason="4-for-1 split, ex 2 July")

    assert runtime.oms.anomalies.is_quarantined("CRWD") is True


def test_the_declaration_binds_to_what_the_broker_reports(qtbot, tmp_path):
    """Captured from the broker rather than typed by the operator. The binding
    is what stops one declaration granting permanent immunity, and a hand-typed
    quantity is exactly what would be typed to match whatever silences the
    alert."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"CRWD": 64.0})

    screen._declare_anomaly("CRWD", reason="4-for-1 split")

    anomaly = runtime.oms.anomalies.get("CRWD")
    assert anomaly is not None
    assert anomaly.broker_quantity == 64.0


def test_declaring_is_refused_without_a_broker_snapshot(qtbot, tmp_path):
    """Binding to a guessed quantity is worse than not declaring at all: it
    would either silence a real divergence or fail to explain the actual one.
    With nothing to bind to, the honest answer is to decline."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    runtime.account_poller._snapshot = None

    screen._declare_anomaly("CRWD", reason="4-for-1 split")

    assert runtime.oms.anomalies.is_quarantined("CRWD") is False


def test_clearing_reaches_the_store(qtbot, tmp_path):
    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"CRWD": 64.0})
    screen._declare_anomaly("CRWD", reason="4-for-1 split")

    screen._clear_anomaly("CRWD")

    assert runtime.oms.anomalies.is_quarantined("CRWD") is False


def test_the_declared_anomaly_is_listed(qtbot, tmp_path):
    """A quarantine nobody can see is one nobody clears."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"CRWD": 64.0})
    screen._declare_anomaly("CRWD", reason="4-for-1 split, ex 2 July")

    screen._refresh_anomalies()

    rendered = screen.anomaly_list.toPlainText()
    assert "CRWD" in rendered
    assert "4-for-1 split" in rendered


def test_the_panel_says_declared_is_not_fixed(qtbot, tmp_path):
    """The one failure this feature could introduce is "declared" reading as
    "fixed". The wording is asserted rather than left to review, because a
    reviewer sees it once and an operator sees it every session."""
    screen, _ = _build_screen(qtbot, tmp_path)

    caption = screen.anomaly_caption.text().lower()

    assert "not" in caption
    assert "correct" in caption or "repair" in caption
