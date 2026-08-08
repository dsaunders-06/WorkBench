"""The expertise level actually changes a screen (M58c).

`ui_level` was settable from M55 and asked for on first run from M58a, and no
screen anywhere branched on it - so an operator could choose a level, be told it
decides how much is explained and how much is shown, and watch nothing change.
M58a therefore shipped a promise the application did not keep.

These pin both halves of that promise being kept, and the boundary it must not
cross: **safety is not a level**. The headline is a warning and is identical at
every level; only the explanation of it moves.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.oms.adopted import AdoptedPosition, AdoptedPositionReport
from qat.presentation.adopted_panel import AdoptedPositionsPanel
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime
from qat.presentation.ui_level import UiLevel


def _report() -> AdoptedPositionReport:
    return AdoptedPositionReport(
        positions=(AdoptedPosition(symbol="AAA", quantity=10.0, price=100.0, has_stop=True),),
        equity=100_000.0,
        risk_at_stop_dollars=5_040.0,
        adopted_risk_dollars=5_040.0,
        cap_pct=0.05,
    )


def _panel(qtbot, level: UiLevel) -> AdoptedPositionsPanel:
    panel = AdoptedPositionsPanel(level=level)
    qtbot.addWidget(panel)
    panel.show()
    panel.update_from(_report())
    return panel


def test_professional_drops_the_explanation(qtbot):
    """The whole point: choosing Professional now visibly does something."""
    panel = _panel(qtbot, UiLevel.PROFESSIONAL)

    assert panel.body.isVisible() is False


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD])
def test_the_explaining_levels_keep_it(qtbot, level):
    panel = _panel(qtbot, level)

    assert panel.body.isVisible() is True


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_the_warning_itself_is_identical_at_every_level(qtbot, level):
    """Safety is not a level. A professional operator gets a denser screen,
    never a quieter one - the headline, the fact the panel appears at all, and
    what it says are the same at all three."""
    panel = _panel(qtbot, level)

    assert panel.isVisible() is True
    assert panel.headline.isVisible() is True
    assert panel.headline.text() == _report().headline()


@pytest.mark.parametrize("level", [UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL])
def test_the_explanation_text_is_always_set_even_when_hidden(qtbot, level):
    """Hidden, never absent. Anything reading the panel programmatically - a
    test, a screenshot, a future export - still sees the whole story."""
    panel = _panel(qtbot, level)

    assert panel.body.text() == _report().explanation()


def test_an_empty_report_still_hides_the_whole_panel(qtbot):
    """The pre-existing behaviour, which the level must not disturb."""
    panel = AdoptedPositionsPanel(level=UiLevel.PROFESSIONAL)
    qtbot.addWidget(panel)

    panel.update_from(None)

    assert panel.isVisible() is False


def test_the_dashboard_passes_the_configured_level_through(qtbot):
    """The wiring, not just the panel. A panel that can honour the level and a
    screen that never tells it the level are the same as no feature at all -
    which is exactly the state this fixes."""
    settings = Settings(_env_file=None, ui_level="professional")
    screen = DashboardScreen(Runtime.build_demo(settings=settings))
    qtbot.addWidget(screen)

    assert screen.adopted_panel.level is UiLevel.PROFESSIONAL
