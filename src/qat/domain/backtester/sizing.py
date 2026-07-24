"""Position sizing (spec §G/§H, paper Appendix A fixed-fractional formula).

FixedFractionalSizer implements the same core formula M6's RiskEngine will
use (shares = risk_fraction * equity / stop_distance); M6 will extend this
with VaR/ES/correlation/kill-switch checks layered on top. Sizing sits
behind a Protocol so swapping in the real engine later is a constructor
argument change to VectorizedBacktester, not a rewrite.
"""

from __future__ import annotations

from typing import Protocol

from qat.config import Settings


class PositionSizer(Protocol):
    def size(self, equity: float, price: float, atr: float) -> float:
        """Return the number of shares/units to trade (0.0 if sizing is not possible)."""
        ...


class FixedFractionalSizer:
    def __init__(
        self,
        risk_fraction: float | None = None,
        atr_stop_multiple: float | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings or Settings()
        self.risk_fraction = (
            risk_fraction if risk_fraction is not None else settings.per_trade_risk_pct
        )
        self.atr_stop_multiple = (
            atr_stop_multiple if atr_stop_multiple is not None else settings.atr_stop_multiple
        )

    def size(self, equity: float, price: float, atr: float) -> float:
        if atr <= 0 or equity <= 0 or price <= 0:
            return 0.0
        stop_distance = self.atr_stop_multiple * atr
        if stop_distance <= 0:
            return 0.0
        shares = (self.risk_fraction * equity) / stop_distance
        return max(0.0, shares)
