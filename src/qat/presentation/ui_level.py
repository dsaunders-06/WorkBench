"""How much the interface explains, and how much it shows (M45).

A trading interface has two audiences that want opposite things. Someone new
needs fewer numbers and to be told what each one means. Someone institutional
needs density and speed, and finds explanation patronising. Building for the
average of the two serves neither.

So the level is a property of the operator, not of the screen, and screens ask
for it rather than deciding for themselves.

Two rules hold this together, and both matter more than the levels do:

* **Safety is not a level.** Warnings, the mode and execution banners, refusal
  reasons and the sign-off gate are identical at every level. Nothing here may
  be used to quieten a rail.
* **Hidden, never disabled.** A greyed-out control invites a fight with the
  interface and tells the operator nothing. A control that is absent is one
  level away, and the level selector says so.

This module is plumbing. It changes no screen on its own - each screen adopts
it deliberately, one at a time.
"""

from __future__ import annotations

from enum import IntEnum

from qat.config import Settings


class UiLevel(IntEnum):
    """Ordered, so a screen can ask "at least this much" in one comparison.

    An IntEnum rather than a string set precisely so that
    `level >= UiLevel.STANDARD` reads as intended and cannot be got wrong by
    comparing spellings.
    """

    GUIDED = 0
    STANDARD = 1
    PROFESSIONAL = 2

    @classmethod
    def from_settings(cls, settings: Settings) -> UiLevel:
        return _BY_NAME.get(settings.ui_level, cls.STANDARD)

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def describes_itself(self) -> str:
        return _DESCRIPTIONS[self]

    def explains(self) -> bool:
        """Whether a figure should be accompanied by what it means."""
        return self <= UiLevel.STANDARD

    def shows_advanced(self) -> bool:
        """Whether controls that need judgement to set should be present."""
        return self >= UiLevel.STANDARD


_BY_NAME = {
    "guided": UiLevel.GUIDED,
    "standard": UiLevel.STANDARD,
    "professional": UiLevel.PROFESSIONAL,
}

_LABELS = {
    UiLevel.GUIDED: "Guided",
    UiLevel.STANDARD: "Standard",
    UiLevel.PROFESSIONAL: "Professional",
}

_DESCRIPTIONS = {
    UiLevel.GUIDED: (
        "Fewer figures, each explained. Controls that need judgement to set are "
        "hidden - the risk limits stay visible, but read-only."
    ),
    UiLevel.STANDARD: (
        "Everything present, with explanations where a figure is not " "self-evident. The default."
    ),
    UiLevel.PROFESSIONAL: (
        "Maximum density, explanations off, raw figures alongside derived ones. "
        "Warnings and the sign-off gate are unchanged."
    ),
}
