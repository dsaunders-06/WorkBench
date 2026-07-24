"""The seven market regimes (spec §E/§F, paper §9.1).

Declared now, ahead of the actual regime engine (M5), so strategies can
declare suitable_regimes() - the same pattern M1 used to pre-declare events
before their producers/consumers existed.
"""

from __future__ import annotations

from enum import StrEnum


class Regime(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    RECESSION = "recession"
    RECOVERY = "recovery"


ALL_REGIMES: frozenset[Regime] = frozenset(Regime)
