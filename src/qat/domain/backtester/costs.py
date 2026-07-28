"""Trading cost model: commission with a floor, plus slippage (spec §G, M27).

A zero-cost model is deliberately easy to construct (CostModel(0, 0)) so the
vectorized engine's guardrail can warn loudly when it's used - the spec
explicitly calls zero-cost backtests a red flag for unrealistic assumptions.

M27 added the floor, and it matters more than it looks. Until then the model
was purely proportional, which cannot express "IBKR charges a minimum of $6 per
transaction": at 5bps a $20,000 trade modelled as $10 and a $2,000 trade as
$1, against a real $6. The error was largest exactly where it hurts - a fixed
fee is trivial on a large position and ruinous on a small one, so a
proportional-only model is most wrong about the trades most worth refusing.

Slippage stays purely proportional and takes no floor: it is a market-impact
estimate rather than a charge, and a minimum dollar slippage on a tiny order
would be inventing a cost rather than modelling one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module import-light
    from qat.config import Settings


@dataclass(frozen=True, slots=True)
class CostModel:
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    min_commission: float = 0.0
    """Dollar floor per transaction. Zero keeps the pre-M27 behaviour, which is
    what every backtest written against the old model still expects."""

    @classmethod
    def from_settings(cls, settings: Settings) -> CostModel:
        """The model the live system reasons with, built from configuration."""
        return cls(
            commission_bps=settings.commission_bps,
            slippage_bps=settings.slippage_bps,
            min_commission=settings.broker_min_commission,
        )

    @property
    def total_bps(self) -> float:
        return self.commission_bps + self.slippage_bps

    def cost_fraction(self) -> float:
        return self.total_bps / 10_000.0

    def commission(self, notional: float) -> float:
        """Per-transaction commission, never below the broker's floor."""
        proportional = abs(notional) * (self.commission_bps / 10_000.0)
        return max(self.min_commission, proportional)

    def slippage(self, notional: float) -> float:
        return abs(notional) * (self.slippage_bps / 10_000.0)

    def apply(self, notional: float) -> float:
        """Dollar cost of ONE transaction of the given notional value."""
        return self.commission(notional) + self.slippage(notional)

    def round_trip(self, entry_notional: float, exit_notional: float | None = None) -> float:
        """Cost of getting in and back out again.

        The figure that actually decides whether a trade is worth taking. The
        exit notional defaults to the entry's, which is the right assumption
        before the trade happens and the wrong one afterwards - so realised
        accounting passes both.
        """
        return self.apply(entry_notional) + self.apply(
            entry_notional if exit_notional is None else exit_notional
        )
