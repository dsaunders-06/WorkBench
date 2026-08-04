"""Dashboard panel for positions this application did not open (spec M25).

Hidden entirely when there is nothing to say, which is the normal case. A
panel that is always present and usually empty teaches the operator to stop
reading it, and this one only appears when it is explaining why the system is
refusing to trade.

All of the wording comes from AdoptedPositionReport. The panel decides how
loud to be, never what is true.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from qat.domain.oms.adopted import AdoptedPositionReport
from qat.presentation import theme

# Amber for "you should deal with this", red for "nothing new is being
# opened until you do". The distinction is the point: an adopted position
# using some of the budget is a note, one that has exhausted it is a stop.
_NOTE_COLOUR = theme.WARNING
_BLOCKING_COLOUR = theme.DANGER

_HEADLINE_STYLE = (
    "background-color: {fill}; color: white; padding: 8px; "
    "border-radius: 4px; font-size: 15px; font-weight: bold;"
)
_BODY_STYLE = "color: #444; padding: 4px 8px; font-size: 13px;"


class AdoptedPositionsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self.body.setText(report.explanation())
        self.setVisible(True)
