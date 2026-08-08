"""Asking for the detail level once, on the first run (M58a).

`ui_level` has a default, so Settings always has an answer and the operator has
never been asked for one. Agreed as a first-run prompt and never built.

The condition is deliberately "has this ever been written down", not "does it
differ from the default". Standard IS the default, so an operator who chose it
on purpose and one who has never seen the question are indistinguishable by
value - only the `.env` can tell them apart. Anything else would re-ask someone
who has already answered, which is the behaviour this replaces.

**Not a safety control**, and the dialog says so. Warnings, the mode and
execution banners, refusal reasons and the sign-off gate are identical at every
level; this decides how much is explained and whether controls needing
judgement are present. A first-run dialog that appeared to be about risk would
be worse than no dialog at all.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from qat import env_file
from qat.paths import env_path
from qat.presentation.ui_level import UiLevel

logger = logging.getLogger(__name__)

UI_LEVEL_KEY = "QAT_UI_LEVEL"


def level_has_been_chosen(path: object | None = None) -> bool:
    return env_file.has_key(UI_LEVEL_KEY, path=path)  # type: ignore[arg-type]


class DetailLevelDialog(QDialog):
    """One question, asked once, with each answer describing itself."""

    def __init__(self, current: UiLevel = UiLevel.STANDARD, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How much should the interface explain?")
        self.setModal(True)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "This decides how much is EXPLAINED and how much is SHOWN. It changes nothing "
            "about what the system does: warnings, the mode banners, refusal reasons, the "
            "sign-off gate and every risk limit behave identically at all three levels."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._buttons: dict[UiLevel, QRadioButton] = {}
        for level in (UiLevel.GUIDED, UiLevel.STANDARD, UiLevel.PROFESSIONAL):
            button = QRadioButton(level.label)
            button.setChecked(level == current)
            layout.addWidget(button)
            description = QLabel(level.describes_itself)
            description.setWordWrap(True)
            description.setIndent(24)
            layout.addWidget(description)
            self._buttons[level] = button

        footer = QLabel("You can change this at any time in Settings, on the Basic tab.")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

    def selected_level(self) -> UiLevel:
        for level, button in self._buttons.items():
            if button.isChecked():
                return level
        return UiLevel.STANDARD


def prompt_for_detail_level_if_never_chosen(parent: QWidget | None = None) -> UiLevel | None:
    """Ask, once, and remember the answer. Returns the level if it asked.

    Writing the answer is what stops it asking again, so the write happens even
    when the operator accepts the default - "I chose Standard" and "I was never
    asked" have to stop being the same state, and that is the entire point.

    Every failure is swallowed. A prompt that cannot be shown or a setting that
    cannot be written must not stop the application starting.
    """
    try:
        if level_has_been_chosen():
            return None
        dialog = DetailLevelDialog(parent=parent)
        dialog.exec()
        level = dialog.selected_level()
        env_file.update_env_file({UI_LEVEL_KEY: level.name.lower()}, path=env_path())
        logger.info(
            "Detail level set to %s on first run. It will not be asked again; change it in "
            "Settings at any time.",
            level.label,
        )
        return level
    except Exception:  # noqa: BLE001 - a first-run nicety must never block startup
        logger.warning("Could not ask for the detail level", exc_info=True)
        return None


__all__ = [
    "UI_LEVEL_KEY",
    "DetailLevelDialog",
    "level_has_been_chosen",
    "prompt_for_detail_level_if_never_chosen",
]
