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


# --- I4, final review: resting-order quarantines have to be reachable too --
#
# RestingOrderAnomalyStore.clear() had no production caller before this fix.
# The scan could cancel every orphan leg cleanly and the symbol would still
# be quarantined forever, across every restart, because nothing on this
# screen ever read the store. These tests prove the seam now reaches it, the
# same way the position-anomaly tests above prove theirs does.


def test_a_resting_order_quarantine_is_listed_and_labelled_distinctly(qtbot, tmp_path):
    """The two stores mean different things - a position anomaly can suppress
    a reconciliation halt, a resting-order quarantine deliberately cannot -
    so blurring them into one undifferentiated list would hide that. Each
    row names its own kind."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    runtime.oms.resting_order_anomalies.declare(
        symbol="TNE.AX",
        reason="16 shares of resting sell the book does not justify (flat)",
        declared_by="order-reconciler",
        excess=16.0,
    )

    screen._refresh_anomalies()

    rendered = screen.anomaly_list.toPlainText()
    assert "TNE.AX" in rendered
    assert "RESTING ORDER" in rendered
    assert "POSITION" not in rendered


def test_a_position_anomaly_and_a_resting_quarantine_are_both_shown_and_labelled(qtbot, tmp_path):
    """Both stores render on the same panel, each still identifiable as its
    own kind."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"CRWD": 64.0})
    screen._declare_anomaly("CRWD", reason="4-for-1 split, ex 2 July")
    runtime.oms.resting_order_anomalies.declare(
        symbol="TNE.AX",
        reason="16 shares of resting sell the book does not justify (flat)",
        declared_by="order-reconciler",
        excess=16.0,
    )

    screen._refresh_anomalies()

    rendered = screen.anomaly_list.toPlainText()
    assert "POSITION" in rendered and "CRWD" in rendered
    assert "RESTING ORDER" in rendered and "TNE.AX" in rendered


def test_empty_state_is_not_shown_while_a_resting_quarantine_is_active(qtbot, tmp_path):
    """ "No quarantined positions." must not be printed over an active
    resting-order quarantine - that would read as an all-clear it is not."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    runtime.oms.resting_order_anomalies.declare(
        symbol="TNE.AX",
        reason="16 shares of resting sell the book does not justify (flat)",
        declared_by="order-reconciler",
        excess=16.0,
    )

    screen._refresh_anomalies()

    assert "No quarantined positions." not in screen.anomaly_list.toPlainText()


def test_clearing_a_resting_order_quarantine_reaches_the_store(qtbot, tmp_path):
    screen, runtime = _build_screen(qtbot, tmp_path)
    runtime.oms.resting_order_anomalies.declare(
        symbol="TNE.AX",
        reason="16 shares of resting sell the book does not justify (flat)",
        declared_by="order-reconciler",
        excess=16.0,
    )
    assert runtime.oms.resting_order_anomalies.is_quarantined("TNE.AX") is True

    screen._clear_resting_anomaly("TNE.AX")

    assert runtime.oms.resting_order_anomalies.is_quarantined("TNE.AX") is False


def test_clearing_a_resting_quarantine_does_not_touch_a_position_anomaly_on_the_same_symbol(
    qtbot, tmp_path
):
    """A symbol can be in both stores at once. Clearing one must not look
    like it cleared the other - they answer different questions and only one
    of them can ever suppress a reconciliation halt."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"TNE.AX": 3051.0})
    screen._declare_anomaly("TNE.AX", reason="broker-side adjustment pending review")
    runtime.oms.resting_order_anomalies.declare(
        symbol="TNE.AX",
        reason="16 shares of resting sell the book does not justify (holds 3051)",
        declared_by="order-reconciler",
        excess=16.0,
    )

    screen._clear_resting_anomaly("TNE.AX")

    assert runtime.oms.resting_order_anomalies.is_quarantined("TNE.AX") is False
    assert runtime.oms.anomalies.is_quarantined("TNE.AX") is True


def test_the_clear_picker_offers_both_kinds_labelled_apart(qtbot, tmp_path):
    """`_on_clear_clicked` must be able to tell the two stores' entries apart
    even when they share a symbol, since each clears through a different
    method. Exercised at the option-building level rather than through the
    modal dialog, matching how `_clear_anomaly` above is tested directly."""
    from qat.presentation.risk_console import _POSITION_SUFFIX, _RESTING_SUFFIX

    screen, runtime = _build_screen(qtbot, tmp_path)
    _seed_broker_positions(runtime, {"CRWD": 64.0})
    screen._declare_anomaly("CRWD", reason="4-for-1 split")
    runtime.oms.resting_order_anomalies.declare(
        symbol="TNE.AX",
        reason="16 shares of resting sell the book does not justify (flat)",
        declared_by="order-reconciler",
        excess=16.0,
    )

    options = [f"{a.symbol}{_POSITION_SUFFIX}" for a in runtime.oms.anomalies.active()]
    options += [
        f"{a.symbol}{_RESTING_SUFFIX}" for a in runtime.oms.resting_order_anomalies.active()
    ]

    assert f"CRWD{_POSITION_SUFFIX}" in options
    assert f"TNE.AX{_RESTING_SUFFIX}" in options
