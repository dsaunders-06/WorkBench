from __future__ import annotations

from PySide6.QtWidgets import QWidget

from qat.presentation.base import PlaceholderScreen


class ScreenerScreen(PlaceholderScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Screener",
            "Fundamental/technical universe screening arrives alongside the "
            "strategy engine (M3) and data pipeline (M2).",
            parent,
        )
