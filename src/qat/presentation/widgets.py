"""Shared presentation widgets (spec §K) - small, reusable building blocks
so the six screens don't each reinvent a KPI tile or a probability bar.
Views only; no trading logic lives here."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from qat.presentation import theme


class KpiTile(QFrame):
    def __init__(self, label: str, value: str = "-", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(theme.panel())
        layout = QVBoxLayout(self)
        self._label = QLabel(label)
        self._label.setStyleSheet(theme.text(theme.MUTED, size=theme.CAPTION))
        self._value = QLabel(value)
        self._value.setStyleSheet(theme.text(size=theme.TITLE, bold=True))
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, value: str, color: str | None = None) -> None:
        self._value.setText(value)
        self._value.setStyleSheet(theme.text(color, size=theme.TITLE, bold=True))


class ProbabilityBar(QFrame):
    """A labelled horizontal bar for one regime's probability (0-100%)."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(label)
        self._label.setFixedWidth(90)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(True)
        layout.addWidget(self._label)
        layout.addWidget(self._bar)

    def set_probability(self, probability: float) -> None:
        self._bar.setValue(round(probability * 100))
