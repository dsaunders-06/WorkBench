"""Position sizing (spec §H, paper §18.1): fractional-Kelly blended with
volatility targeting, capped at the per-trade risk fraction.

"Capped at" is read literally: the Kelly-derived share count and M4's
FixedFractionalSizer (domain.backtester.sizing) - which already *is* the
ATR-stop-implied volatility-targeting formula - are both computed, and the
smaller of the two wins. Reusing FixedFractionalSizer avoids a third copy
of the same ATR-stop formula.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.backtester.sizing import FixedFractionalSizer
from qat.domain.risk_engine.kelly import compute_fractional_kelly


class KellyVolTargetSizer:
    def __init__(
        self,
        kelly_fraction: float | None = None,
        risk_fraction: float | None = None,
        atr_stop_multiple: float | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or Settings()
        self.kelly_fraction = (
            kelly_fraction if kelly_fraction is not None else settings.kelly_fraction
        )
        self._cap_sizer = FixedFractionalSizer(risk_fraction, atr_stop_multiple, settings)

    def size(
        self, equity: float, price: float, atr: float, win_rate: float, win_loss_ratio: float
    ) -> float:
        if equity <= 0 or price <= 0:
            return 0.0
        kelly_f = compute_fractional_kelly(win_rate, win_loss_ratio, self.kelly_fraction)
        kelly_shares = (kelly_f * equity) / price
        cap_shares = self._cap_sizer.size(equity, price, atr)
        return max(0.0, min(kelly_shares, cap_shares))
