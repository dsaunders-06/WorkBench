"""The single Phase 1 human sign-off dialog used by blotter and cards."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm_order_action(parent: QWidget, message: str) -> bool:
    result = QMessageBox.question(
        parent,
        "Confirm order action",
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes
