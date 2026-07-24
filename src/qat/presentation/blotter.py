from __future__ import annotations

from PySide6.QtWidgets import QWidget

from qat.presentation.base import PlaceholderScreen


class BlotterScreen(PlaceholderScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Order Blotter",
            "Order lifecycle with the mandatory human sign-off dialog and "
            "paper-vs-live colour coding arrives with the OMS (M6).",
            parent,
        )
