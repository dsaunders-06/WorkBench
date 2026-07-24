from __future__ import annotations

from PySide6.QtWidgets import QWidget

from qat.presentation.base import PlaceholderScreen


class SettingsScreen(PlaceholderScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Settings",
            "Risk limits, broker/LLM endpoints and the paper/live trading-mode "
            "switch (gated by explicit confirmation) will be editable here.",
            parent,
        )
