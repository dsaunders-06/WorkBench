"""A pending action must reach a widget, not just a module (M39, R1).

`test_corporate_action_has_every_reader` scans the source and proves the wiring
exists. It cannot prove anything renders - M63's orphaned grid row and M74's
"Grew -0.0% a year" both passed every logic test they had. So these put a pending
action into the runtime and read the text back out.

The mode wording is asserted deliberately. In shadow nothing has been placed, and
an operator reading "adjusted to 36.34" and believing the broker holds that order
would be misled in the direction that costs money - the same failure as reading
M60's "declared" as "fixed".
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.config import Settings
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.detector import PendingAction
from qat.domain.performance.reports import build_report
from qat.presentation.blotter import BlotterScreen
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _action(state: str = "shadowed", adjusted: float | None = 36.34) -> PendingAction:
    return PendingAction(
        announcement=Announcement(
            symbol="MNST",
            ex_date=date(2026, 8, 11),
            ratio=2.0,
            action_id="ca-1",
            payable_date=None,
            fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
        ),
        position_opened_at=datetime(2026, 8, 10, tzinfo=UTC),
        current_stop=72.68,
        adjusted_stop=adjusted,
        state=state,
    )


class _StubMonitor:
    def __init__(self, actions: list[PendingAction]) -> None:
        self._actions = actions

    def pending_actions(self) -> list[PendingAction]:
        return self._actions

    def pending_action(self, symbol: str) -> PendingAction | None:
        return next((a for a in self._actions if a.symbol == symbol), None)


def _runtime(mode: str = "shadow", actions: list[PendingAction] | None = None) -> Runtime:
    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, corporate_action_mode=mode, ui_level="professional")
    )
    runtime.corporate_action_monitor = _StubMonitor(actions if actions is not None else [_action()])
    return runtime


# --- Dashboard ----------------------------------------------------------------


async def test_the_dashboard_banner_names_the_action(qtbot):
    screen = DashboardScreen(_runtime())
    qtbot.addWidget(screen)

    await screen._refresh()

    assert screen.corporate_action_banner.isVisibleTo(screen)
    text = screen.corporate_action_banner.text()
    assert "MNST 2-for-1 split" in text
    assert "2026-08-11" in text


async def test_the_dashboard_banner_says_shadow_mode_has_adjusted_nothing(qtbot):
    """The sentence an operator must not be able to misread."""
    screen = DashboardScreen(_runtime(mode="shadow"))
    qtbot.addWidget(screen)

    await screen._refresh()

    assert "nothing has been adjusted" in screen.corporate_action_banner.text()


async def test_the_dashboard_banner_says_act_mode_HAS_adjusted(qtbot):
    screen = DashboardScreen(_runtime(mode="act", actions=[_action(state="applied")]))
    qtbot.addWidget(screen)

    await screen._refresh()

    assert "has been adjusted" in screen.corporate_action_banner.text()


async def test_the_dashboard_banner_is_hidden_when_nothing_is_pending(qtbot):
    """A permanent empty notice is what M74 was partly for."""
    screen = DashboardScreen(_runtime(actions=[]))
    qtbot.addWidget(screen)

    await screen._refresh()

    assert not screen.corporate_action_banner.isVisibleTo(screen)


# --- Risk Console -------------------------------------------------------------


def test_the_risk_console_shows_both_stop_levels(qtbot):
    screen = RiskConsoleScreen(_runtime())
    qtbot.addWidget(screen)

    text = screen.corporate_action_label.text()

    assert "72.68" in text
    assert "36.34" in text
    assert "shadow" in text


def test_the_risk_console_shows_a_refusal_reason_when_there_is_one(qtbot):
    refused = PendingAction(
        announcement=_action().announcement,
        position_opened_at=datetime(2026, 8, 10, tzinfo=UTC),
        current_stop=72.68,
        adjusted_stop=145.36,
        state="refused",
        refusal="the adjusted stop 145.36 is at or above the 46.30 market",
    )
    screen = RiskConsoleScreen(_runtime(actions=[refused]))
    qtbot.addWidget(screen)

    assert "at or above" in screen.corporate_action_label.text()


def test_the_risk_console_says_none_pending_rather_than_going_blank(qtbot):
    """Distinct from an empty label, which reads as a rendering fault."""
    screen = RiskConsoleScreen(_runtime(actions=[]))
    qtbot.addWidget(screen)

    assert "none pending" in screen.corporate_action_label.text()


# --- Blotter ------------------------------------------------------------------


def test_the_blotter_names_the_symbol(qtbot):
    screen = BlotterScreen(_runtime())
    qtbot.addWidget(screen)

    screen._timer_refresh()

    assert screen.corporate_action_note.isVisibleTo(screen)
    assert "MNST" in screen.corporate_action_note.text()


def test_the_blotter_note_is_hidden_when_nothing_is_pending(qtbot):
    screen = BlotterScreen(_runtime(actions=[]))
    qtbot.addWidget(screen)

    screen._timer_refresh()

    assert not screen.corporate_action_note.isVisibleTo(screen)


# --- The daily report ---------------------------------------------------------


def test_the_report_has_a_corporate_actions_section():
    report = build_report(
        period="daily",
        period_label="12 August 2026",
        trades=[],
        equity_points=[],
        start=date(2026, 8, 12),
        end=date(2026, 8, 12),
        pending_actions=("MNST 2-for-1 split, ex-date 2026-08-11",),
    )

    markdown = report.to_markdown()

    assert "### Corporate actions pending" in markdown
    assert "MNST 2-for-1 split" in markdown


def test_the_report_omits_the_section_entirely_when_nothing_is_pending():
    """A heading over nothing is worse than no heading, and this report is long
    enough that an always-present empty section would be scrolled past along
    with the one that matters."""
    report = build_report(
        period="daily",
        period_label="12 August 2026",
        trades=[],
        equity_points=[],
        start=date(2026, 8, 12),
        end=date(2026, 8, 12),
    )

    assert "Corporate actions pending" not in report.to_markdown()


# --- The AI advisor's context -------------------------------------------------


def test_the_model_is_told_the_stop_was_not_adjusted_in_shadow_mode(qtbot):
    """R2. Advice about a position whose share count is about to change, given
    without knowing that, is confidently wrong."""
    from qat.presentation.ai_advisor import AiAdvisorScreen

    screen = AiAdvisorScreen(_runtime(mode="shadow"))
    qtbot.addWidget(screen)

    notes = screen._corporate_action_notes()

    assert len(notes) == 1
    assert "MNST 2-for-1 split" in notes[0]
    assert "NOT adjusted" in notes[0]


def test_the_model_gets_nothing_when_nothing_is_pending(qtbot):
    from qat.presentation.ai_advisor import AiAdvisorScreen

    screen = AiAdvisorScreen(_runtime(actions=[]))
    qtbot.addWidget(screen)

    assert screen._corporate_action_notes() == []


@pytest.mark.parametrize("mode", ["shadow", "act"])
def test_the_notes_always_say_entries_are_refused(qtbot, mode):
    from qat.presentation.ai_advisor import AiAdvisorScreen

    screen = AiAdvisorScreen(_runtime(mode=mode, actions=[_action(state="applied")]))
    qtbot.addWidget(screen)

    assert "refused" in screen._corporate_action_notes()[0]
