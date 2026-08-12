"""What the stop becomes, and the two guards it must pass (M39).

The asymmetry is deliberate. A wrong ratio that leaves the stop too FAR away
costs more if the position runs against us; a wrong ratio that leaves it too
CLOSE liquidates on contact. One is a worse loss, the other is a guaranteed one,
so both guards fail in the same direction: refuse, and say why.

**This computes and judges. It never places.** The monitor does that, which is
what lets the invariant be tested without a broker at all.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from qat.domain.corporate_actions.detector import PendingAction

logger = logging.getLogger(__name__)

SHADOW = "shadow"
ACT = "act"

# A split preserves relative stop distance exactly, so this absorbs rounding and
# the drift between the price observed before the action and the current one.
# Without it an ordinary tick between the two reads as a tightening and refuses a
# correct adjustment.
_DISTANCE_TOLERANCE = 1e-3


class StopAdjuster:
    def __init__(self, mode: str = SHADOW) -> None:
        self.mode = mode

    def assess(self, action: PendingAction, price: float, pre_action_price: float) -> PendingAction:
        """The new stop and whether it may be placed.

        Returns a copy - `PendingAction` is frozen - so a caller holding the
        original still sees the un-assessed state.
        """
        stop = action.current_stop
        if stop is None or stop <= 0:
            return self._refuse(action, "there is no resting stop to adjust")
        if price <= 0 or pre_action_price <= 0:
            return self._refuse(action, "no usable price to judge the adjustment against")

        adjusted = round(stop / action.ratio, 2)

        if adjusted >= price:
            return self._refuse(
                action,
                f"the adjusted stop {adjusted:.2f} is at or above the {price:.2f} market, so "
                f"placing it would be a market order rather than protection",
                adjusted,
            )

        before = (pre_action_price - stop) / pre_action_price
        after = (price - adjusted) / price
        if after < before - _DISTANCE_TOLERANCE:
            return self._refuse(
                action,
                f"the adjustment would tighten the stop from {before:.2%} to {after:.2%} of "
                f"price, and tightening is the direction that liquidates",
                adjusted,
            )

        state = "applied" if self.mode == ACT else "shadowed"
        return replace(action, adjusted_stop=adjusted, state=state, refusal=None)

    def _refuse(
        self, action: PendingAction, reason: str, adjusted: float | None = None
    ) -> PendingAction:
        """Refusing leaves the stop where it is, which is itself dangerous - so
        this is a WARNING naming the symbol, and the monitor quarantines the
        position on top of it. An unadjusted stop is a known hazard; a wrongly
        adjusted one is a certainty."""
        logger.warning(
            "Split adjustment on %s REFUSED: %s. The resting stop is unchanged and the "
            "position is quarantined - the records are NOT corrected by this.",
            action.symbol,
            reason,
        )
        return replace(action, adjusted_stop=adjusted, state="refused", refusal=reason)
