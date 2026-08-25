"""The console must be able to force a reconciliation, and must not halt the
account by accident (item 36).

`ReconciliationMonitor.poll`'s docstring said it was "Public so a test or the
Risk Console can force a check without waiting on the interval." **The Risk
Console could not.** That screen had exactly three buttons - the kill switch,
"Declare a difference explained...", and "Clear a quarantine..." - and nothing
outside tests called `poll()`.

On 25 August that sentence was read as fact and the operator was told to force
a reconciliation from the Risk Console while diagnosing a wedged poll. There
was no such control. The kill switch was tripped at 12:09:27 with "Manual
trigger by operator (risk console)" - the only code path that emits it - and
the operator reports not pressing it. `_on_kill_switch_clicked` is a TOGGLE
bound to Qt's `clicked`, which fires on Space or Enter when focused, and it was
the first widget constructed on that screen.

So halting a live account was one stray keystroke away from an instruction to
do something else. Both halves are fixed here: the button that should have
existed, and a confirmation on TRIP.

The confirm is on trip ONLY. De-risking must stay one click - a rail whose
effect is "the account may not stop trading" would be worse than the accident.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _build(qtbot, tmp_path):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime


def test_the_console_can_force_a_reconciliation(qtbot, tmp_path):
    """The control the docstring promised for long enough that it was believed."""
    screen, runtime = _build(qtbot, tmp_path)
    assert hasattr(screen, "force_check_button")

    called: list[str] = []
    screen._schedule = lambda coro: called.append("scheduled") or coro.close()  # type: ignore[assignment]
    screen._on_force_check_clicked()

    assert called == ["scheduled"], "the button did not reach the reconciliation poll"


def test_tripping_the_switch_asks_first(qtbot, tmp_path):
    """A stray Enter must not halt a live account."""
    screen, runtime = _build(qtbot, tmp_path)
    assert not runtime.kill_switch.tripped

    screen._confirm_trip = lambda: False  # type: ignore[assignment]
    screen._on_kill_switch_clicked()

    assert not runtime.kill_switch.tripped, "declining the confirmation still halted trading"

    screen._confirm_trip = lambda: True  # type: ignore[assignment]
    screen._on_kill_switch_clicked()

    assert runtime.kill_switch.tripped


def test_RESETTING_never_asks(qtbot, tmp_path):
    """The asymmetry is the point. Halting is confirmed; clearing a halt is
    one click, because a confirmation in front of de-risking is a worse
    failure than the one this fixes."""
    screen, runtime = _build(qtbot, tmp_path)
    runtime.kill_switch.trip("Broker reconciliation mismatch")

    def _must_not_be_called() -> bool:
        raise AssertionError("reset must never ask for confirmation")

    screen._confirm_trip = _must_not_be_called  # type: ignore[assignment]
    screen._on_kill_switch_clicked()

    assert not runtime.kill_switch.tripped
