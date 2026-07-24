"""Trading cost model: configurable commission + slippage in bps (spec §G).

A zero-cost model is deliberately easy to construct (CostModel(0, 0)) so the
vectorized engine's guardrail can warn loudly when it's used - the spec
explicitly calls zero-cost backtests a red flag for unrealistic assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CostModel:
    commission_bps: float = 5.0
    slippage_bps: float = 5.0

    @property
    def total_bps(self) -> float:
        return self.commission_bps + self.slippage_bps

    def cost_fraction(self) -> float:
        return self.total_bps / 10_000.0

    def apply(self, notional: float) -> float:
        """Dollar cost for a trade of the given notional value."""
        return abs(notional) * self.cost_fraction()
