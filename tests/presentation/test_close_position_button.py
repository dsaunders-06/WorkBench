"""Dashboard: Close Position button (Task 7, 2026-09-01 manual position close
plan). The widget's whole job is to gate the button on selection, ask the
operator, call `close_position`, and render `CloseResult.detail` - no
sequencing logic belongs in Qt.

`_confirm_close` is kept separate from the click handler for the same reason
`blotter.py`'s `_confirm()`/`_show_error()` are (see that module's docstring):
so a test can answer the dialog without driving a real modal.
`tests/presentation/conftest.py`'s autouse `no_blocking_dialogs` fixture makes
any UNPATCHED modal fail loudly rather than hang the suite, which is why every
test here monkeypatches `_confirm_close` rather than clicking through a real
QMessageBox.

⚠️ There is no `fake_runtime` fixture anywhere in this test tree - checked
`tests/presentation/conftest.py` before writing this file (it provides only
`no_blocking_dialogs`, autouse) and `tests/conftest.py` (session-scoped data
isolation only). Every other dashboard test in this directory instead builds
a real `Runtime.build_demo(...)` and reaches into it directly (see
`test_positions_table.py`, `test_balances_panel.py`, `test_chart_axes.py`,
...) - that convention is followed here rather than inventing a second "fake
runtime" shape that would drift from it.
"""

from __future__ import annotations

import asyncio

import pytest
from PySide6.QtWidgets import QTableWidgetItem

from qat.config import Settings
from qat.domain.oms.position_closer import CloseOutcome, CloseResult
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime


def _cell(text: str) -> QTableWidgetItem:
    return QTableWidgetItem(text)


class _FakeCloser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def believed_legs_for(self, symbol: str) -> tuple[object, ...]:
        return ()

    # ⚠️ NO `acknowledge_halt`. The real `close_position` no longer takes one
    # (spec, 1 September reversal), so a fake that still accepted it would let
    # a dashboard still passing it stay green - which is precisely the class
    # of failure this branch's review was about.
    async def close_position(self, symbol: str, *, operator: str, quantity=None) -> CloseResult:
        self.calls.append((symbol, operator))
        # A real CloseResult, not None - the brief's fake returns nothing,
        # which is fine for the "was it called" assertions but leaves
        # `_run_close`'s `result.outcome` lookup with nothing to read once the
        # scheduled task actually runs to completion in these (async) tests.
        return CloseResult(CloseOutcome.CLOSED, symbol, 100.0, (), f"closed 100 {symbol}")


class _FakeKillSwitch:
    def __init__(self) -> None:
        self.tripped = False
        self.reason: str | None = None

    def trip(self, reason: str) -> None:
        self.tripped, self.reason = True, reason


@pytest.fixture
def dashboard(qtbot, tmp_path):
    # data_dir per test (isolate_data_dir is session-scoped): the same reason
    # test_positions_table.py's `_runtime` helper passes tmp_path through.
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    runtime.closer = _FakeCloser()
    runtime.kill_switch = _FakeKillSwitch()
    screen = DashboardScreen(runtime)
    qtbot.addWidget(screen)
    screen.positions_table.setRowCount(1)
    screen.positions_table.setItem(0, 0, _cell("CBA.AX"))
    screen.positions_table.setItem(0, 1, _cell("100"))
    return screen


def test_button_is_disabled_until_one_row_is_selected(dashboard):
    assert not dashboard.close_position_button.isEnabled()
    dashboard.positions_table.selectRow(0)
    assert dashboard.close_position_button.isEnabled()


# ⚠️ These four are `async def` with a trailing `await asyncio.sleep(...)`,
# unlike the brief's plain `def`. `_on_close_clicked` schedules the actual
# close with `asyncio.ensure_future` (blotter.py's own pattern - see
# `_on_sign_off_clicked`/`_on_reject_clicked`), which requires a running
# event loop; a plain `def` test has none (`asyncio_mode = "auto"` in
# pyproject.toml only gives one to `async def` tests). Every existing test of
# an async-scheduling click handler in this directory
# (test_blotter_signoff_dialog.py) is `async def ... await asyncio.sleep(0.05)`
# for exactly this reason, so that pattern is followed here instead of the
# brief's sketch.


async def test_declining_the_dialog_sends_nothing(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: False)
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)
    assert dashboard.runtime.closer.calls == []


async def test_confirming_calls_the_closer_with_the_operator(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)
    # ⚠️ "operator (dashboard)", not the brief's literal "operator". The
    # brief's own operator="operator" line was flagged as a placeholder: risk
    # console and blotter each source their operator identity from their own
    # module-level `_OPERATOR = "operator (<screen>)"` constant
    # (risk_console.py, blotter.py) rather than a single shared literal -
    # there is no app-wide operator identity to import instead (checked
    # config.py: nothing named `operator`). Dashboard follows that same
    # established convention rather than the brief's hardcoded string.
    assert dashboard.runtime.closer.calls == [("CBA.AX", "operator (dashboard)")]


def test_confirm_dialog_does_not_overclaim_the_legs_shown(dashboard, monkeypatch):
    """The leg count comes from `believed_legs_for` - the app's own local
    record, not a re-read of the broker (see `PositionCloser.believed_legs_for`'s
    docstring). `_cancel_legs` re-reads and acts on the broker independently,
    so the dialog must say that plainly rather than presenting the count as
    definitely what gets cancelled - the finding this test pins.

    Calls the real `_confirm_close` with `QMessageBox.question` patched, so
    the ACTUAL string this dialog builds is what gets pinned - not a
    hand-reconstruction of it that could drift from the source unnoticed.
    """
    from PySide6.QtWidgets import QMessageBox

    seen = {}

    def _fake_question(parent, title, text, buttons, default):
        seen["text"] = text
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", _fake_question)
    dashboard._confirm_close("CBA.AX", "100", (), None)

    shown_text = seen["text"]
    assert "BELIEVES" in shown_text
    assert "re-reads the broker" in shown_text
    assert "acts on whatever is actually there" in shown_text
    # Must not present the count as unconditionally what will be cancelled.
    assert "will be cancelled first" not in shown_text


async def test_the_dialog_is_told_the_halt_reason_verbatim(dashboard, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        dashboard,
        "_confirm_close",
        lambda symbol, qty, legs, halt_reason: seen.update(halt_reason=halt_reason) or False,
    )
    dashboard.runtime.kill_switch.trip("IBKR connection lost")
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)
    assert seen["halt_reason"] == "IBKR connection lost"


# The two below are not in the brief's four - added because the task's own
# framing note #3 singles this out as something that "must be impossible to
# miss ... not a status line", which is a rendering-routing decision worth
# pinning down rather than leaving unverified.


async def test_unprotected_outcome_is_shown_as_a_blocking_error(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    shown: dict[str, str] = {}
    monkeypatch.setattr(dashboard, "_show_error", lambda msg: shown.setdefault("error", msg))
    monkeypatch.setattr(dashboard, "_show_result", lambda msg: shown.setdefault("result", msg))

    async def _unprotected(symbol, *, operator, quantity=None):
        return CloseResult(
            CloseOutcome.UNPROTECTED, symbol, 0.0, (), f"{symbol} is held with NO STOP"
        )

    dashboard.runtime.closer.close_position = _unprotected
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)

    assert shown == {"error": "CBA.AX is held with NO STOP"}


async def test_a_closed_outcome_is_rendered_as_a_result_not_an_error(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    shown: dict[str, str] = {}
    monkeypatch.setattr(dashboard, "_show_error", lambda msg: shown.setdefault("error", msg))
    monkeypatch.setattr(dashboard, "_show_result", lambda msg: shown.setdefault("result", msg))
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)

    assert shown == {"result": "closed 100 CBA.AX"}


# --- re-entrancy: one click, one market sell ----------------------------


class _BlockingCloser(_FakeCloser):
    """A close that does not finish until the test lets it, so the window
    between the click and the result can be inspected."""

    def __init__(self) -> None:
        super().__init__()
        self.released = asyncio.Event()

    async def close_position(self, symbol: str, *, operator: str, quantity=None) -> CloseResult:
        self.calls.append((symbol, operator))
        await self.released.wait()
        return CloseResult(CloseOutcome.CLOSED, symbol, 100.0, (), f"closed 100 {symbol}")


async def test_a_second_click_cannot_send_a_second_market_sell(dashboard, monkeypatch):
    """⚠️ The button stayed ENABLED for the whole async close, so a second
    click sent a SECOND full-size market sell - the position sold twice, the
    account short by the second one. `close_position` is irreversible and
    takes a broker round-trip; the operator has no way to know it is running.
    """
    closer = _BlockingCloser()
    dashboard.runtime.closer = closer
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    monkeypatch.setattr(dashboard, "_show_result", lambda msg: None)
    dashboard.positions_table.selectRow(0)

    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)
    assert not dashboard.close_position_button.isEnabled(), "disabled for the duration"

    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)
    assert len(closer.calls) == 1, "a second click must not send a second sell"

    closer.released.set()
    await asyncio.sleep(0.05)
    assert dashboard.close_position_button.isEnabled(), "re-enabled once it finishes"


async def test_a_selection_change_does_not_re_enable_the_button_mid_close(dashboard, monkeypatch):
    """The selection handler sets `enabled` from the row count alone, so any
    selection change during an in-flight close would hand the button back."""
    closer = _BlockingCloser()
    dashboard.runtime.closer = closer
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    monkeypatch.setattr(dashboard, "_show_result", lambda msg: None)
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)

    dashboard.positions_table.clearSelection()
    dashboard.positions_table.selectRow(0)
    assert not dashboard.close_position_button.isEnabled()

    closer.released.set()
    await asyncio.sleep(0.05)


async def test_an_exception_during_the_close_is_surfaced_loudly(dashboard, monkeypatch):
    """⚠️ `asyncio.ensure_future` with no exception handler: anything raising
    AFTER the legs are cancelled left the position BARE with nothing on
    screen, and the traceback swallowed into a "Task exception was never
    retrieved" nobody reads. The operator must be told, and the button must
    come back."""
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    shown: dict[str, str] = {}
    monkeypatch.setattr(dashboard, "_show_error", lambda msg: shown.setdefault("error", msg))
    monkeypatch.setattr(dashboard, "_show_result", lambda msg: shown.setdefault("result", msg))

    async def _explode(symbol, *, operator, quantity=None):
        raise RuntimeError("the broker went away mid-close")

    dashboard.runtime.closer.close_position = _explode
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)

    assert "error" in shown, "a raised close must not vanish"
    assert "the broker went away mid-close" in shown["error"]
    assert "CBA.AX" in shown["error"]
    assert "result" not in shown
    assert dashboard.close_position_button.isEnabled(), "re-enabled in a finally"


# --- no halt override anywhere in the UI --------------------------------


async def test_the_closer_is_never_asked_to_override_a_halt(dashboard, monkeypatch):
    """`acknowledge_halt` is gone from `close_position` (spec, 1 September
    reversal). `_FakeCloser.close_position` above no longer accepts one, so a
    dashboard still passing it raises TypeError here rather than passing."""
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    monkeypatch.setattr(dashboard, "_show_result", lambda msg: None)
    monkeypatch.setattr(dashboard, "_show_error", lambda msg: pytest.fail(f"raised: {msg}"))
    dashboard.runtime.kill_switch.trip("IBKR connection lost")
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    await asyncio.sleep(0.05)
    assert dashboard.runtime.closer.calls == [("CBA.AX", "operator (dashboard)")]


def test_the_dialog_does_not_offer_a_halt_override(dashboard, monkeypatch):
    """The old dialog said "Closing now overrides the halt for this position
    only", which was false AND dangerous: the cancel bypasses sign-off while
    the sell and the re-protect are rejected by it, so the "override" deleted
    the stop and sold nothing."""
    from PySide6.QtWidgets import QMessageBox

    seen = {}

    def _fake_question(parent, title, text, buttons, default):
        seen["text"] = text
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", _fake_question)
    dashboard._confirm_close("CBA.AX", "100", (), "IBKR connection lost")

    shown_text = seen["text"]
    assert "IBKR connection lost" in shown_text, "the reason, verbatim"
    assert "override" not in shown_text.lower()
    assert "REFUSED" in shown_text
    assert "reset" in shown_text.lower()
