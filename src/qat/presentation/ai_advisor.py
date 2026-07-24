from __future__ import annotations

from PySide6.QtWidgets import QWidget

from qat.presentation.base import PlaceholderScreen


class AiAdvisorScreen(PlaceholderScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "AI Advisor",
            "Chat/Q&A with the advisory layer, every answer carrying its rationale "
            "and risk checks, arrives with the AI advisory service (M8).",
            parent,
        )
