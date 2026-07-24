"""Shared placeholder scaffolding for screens not yet built out.

Views render state and capture intent only - no trading logic lives here
(spec §K). Each concrete screen subclasses PlaceholderScreen until its
milestone implements the real content.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderScreen(QWidget):
    def __init__(self, title: str, milestone_note: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.content_layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: bold;")
        note = QLabel(milestone_note)
        note.setStyleSheet("color: gray;")
        note.setWordWrap(True)
        self.content_layout.addWidget(heading)
        self.content_layout.addWidget(note)
        self.content_layout.addStretch(1)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
