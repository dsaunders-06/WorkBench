"""Dashboard panel for positions this application did not open (spec M25).

Hidden entirely when there is nothing to say, which is the normal case. A
panel that is always present and usually empty teaches the operator to stop
reading it, and this one only appears when it is explaining why the system is
refusing to trade.

All of the wording comes from AdoptedPositionReport. The panel decides how
loud to be, never what is true.

**The first screen to consume the expertise level (M58c).** `ui_level` had been
settable since M55 and asked for on first run since M58a, and no screen anywhere
branched on it - so an operator could choose a level and watch nothing change.
This panel is where it becomes real, because it already separates the two things
the level distinguishes: `headline()` is the warning and `explanation()` is the
explanation of it.

Only the explanation moves. **Safety is not a level**: the headline, its colour
and the fact that the panel appears at all are identical at every level. A
professional operator gets a denser screen, never a quieter one.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from qat.domain.oms.adopted import AdoptedPositionReport
from qat.presentation import theme
from qat.presentation.ui_level import UiLevel

# Amber for "you should deal with this", red for "nothing new is being
# opened until you do". The distinction is the point: an adopted position
# using some of the budget is a note, one that has exhausted it is a stop.
_NOTE_COLOUR = theme.WARNING
_BLOCKING_COLOUR = theme.DANGER

_HEADLINE_STYLE = (
    "background-color: {fill}; color: " + theme.WHITE + "; padding: 8px; "
    "border-radius: 4px; " + theme.text(size=theme.SUBHEAD, bold=True)
)
_BODY_STYLE = f"color: {theme.BORDER}; padding: 4px 8px; font-size: {theme.BODY}px;"


class AdoptedPositionsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None, level: UiLevel = UiLevel.STANDARD) -> None:
        super().__init__(parent)
        # Standard by default so every existing caller and test is unchanged -
        # and because Standard explains, which is the safer default of the two.
        self.level = level
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.headline = QLabel()
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)

        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setStyleSheet(_BODY_STYLE)
        layout.addWidget(self.body)

        self.setVisible(False)

    def update_from(self, report: AdoptedPositionReport | None) -> None:
        if report is None or not report.positions:
            self.setVisible(False)
            return

        fill = _BLOCKING_COLOUR if report.blocking else _NOTE_COLOUR
        self.headline.setText(report.headline())
        self.headline.setStyleSheet(_HEADLINE_STYLE.format(fill=fill))
        # Set regardless of level, so the text is present for anything reading
        # the panel programmatically and the only difference is what is SHOWN.
        self.body.setText(report.explanation())
        self.body.setVisible(self.level.explains())
        self.setVisible(True)
