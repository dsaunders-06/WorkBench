"""The console must not call a parked order "approved" (item 38).

On 25 August RHC.AX, IAG.AX and PNI.AX all rendered as `approved  approved` in
the Risk Console's audit panel while the Blotter showed them `pending_signoff -
session phase 'Midday Lull' is not eligible`, under a headline reading
"7 candidate(s) considered, none refused."

The panel was not lying. It renders `risk_engine.audit_log.entries()`, where
`approved` means **the risk engine approved the sizing** - and `RiskDecision`
carries no order id, so it cannot know whether the order later went out. An
order can be risk-approved and then blocked by the autonomy gate, which is
exactly what those three were.

`approvals.py:9` already documents this collision on a different surface: "the
trade ledger cannot tell them apart. Both read `approved`." It was reproduced
on the screen an operator checks to answer "did my orders go out" - and on that
day it answered yes for three that had not.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.risk_engine.audit import RiskDecision
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _build_screen(qtbot, tmp_path) -> tuple[RiskConsoleScreen, Runtime]:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime


def _record(runtime: Runtime, symbol: str, approved: bool) -> None:
    runtime.risk_engine.audit_log.record(
        RiskDecision(
            symbol=symbol,
            approved=approved,
            final_shares=1194.0 if approved else 0.0,
            reason="approved" if approved else "refused",
            inputs={},
            stop_price=42.5,
        )
    )


def test_the_panel_does_not_say_plain_approved(qtbot, tmp_path):
    """THE regression. "approved" reads as "it went out"; this panel cannot
    know that and must not imply it."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _record(runtime, "RHC.AX", approved=True)
    screen.refresh_refusals()

    text = screen.audit_log.toPlainText()
    assert "RHC.AX" in text
    assert "risk-approved" in text, (
        "the verdict must name WHOSE approval it is - the risk engine's sizing "
        "verdict, not the order's fate"
    )


def test_the_panel_says_what_the_verdict_does_NOT_mean(qtbot, tmp_path):
    """A label alone is a weak fix: 'risk-approved' still reads as 'approved'
    to someone scanning. The panel carries a caption saying plainly that this
    is not whether the order reached the broker."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _record(runtime, "RHC.AX", approved=True)
    screen.refresh_refusals()

    caption = screen.audit_caption.text().lower()
    assert "sizing" in caption or "risk engine" in caption
    assert "not" in caption


def test_a_refusal_still_reads_as_a_refusal(qtbot, tmp_path):
    """The other half must not regress: a refused candidate has to stay
    obviously refused."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    _record(runtime, "BHP.AX", approved=False)
    screen.refresh_refusals()

    assert "risk-refused" in screen.audit_log.toPlainText()
