from __future__ import annotations

from PySide6.QtWidgets import QWidget

from qat.presentation.base import PlaceholderScreen


class RegimeMonitorScreen(PlaceholderScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Regime Monitor",
            "Current regime, probability vector, feature drivers and transition "
            "history arrive with the regime engine (M5).",
            parent,
        )
