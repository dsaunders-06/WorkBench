from __future__ import annotations

from PySide6.QtWidgets import QWidget

from qat.presentation.base import PlaceholderScreen


class WorkbenchScreen(PlaceholderScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Strategy Workbench",
            "Parameter panel, backtest equity vs benchmark, metric panel, "
            "regime overlay and Monte-Carlo cone arrive with the backtester (M4).",
            parent,
        )
