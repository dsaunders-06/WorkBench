"""No test may open a blocking modal dialog.

Added after a confirm-before-halt dialog (item 36) was put in front of the
kill-switch button while an existing test clicked that button for real. The
modal waited for input no test would ever give: the suite hung for ten minutes
and a "Halt trading?" box appeared on the operator's screen mid-session.

A confirmation that can block a headless run is one step from one that blocks a
deploy. This makes any unpatched modal fail LOUDLY and immediately instead of
hanging - the same preference for a noisy failure over a silent stall that runs
through the rest of this codebase.

A test that means to exercise a dialog patches the screen's own `_confirm_*`
helper, which is why those are separated from the handlers.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "a test opened a real modal dialog, which would hang the suite. "
            "Patch the screen's _confirm_* helper (or the dialog call) in the "
            "test instead of letting it block."
        )

    for name in ("question", "warning", "information", "critical", "about"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(_refuse), raising=False)
    for name in ("getText", "getItem", "getInt", "getDouble"):
        monkeypatch.setattr(QInputDialog, name, staticmethod(_refuse), raising=False)
