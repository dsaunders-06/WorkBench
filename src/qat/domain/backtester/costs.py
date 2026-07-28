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
    third_party_bps: float = 0.0
    """Exchange and clearing fees passed through by the broker.

    Kept separate from commission rather than folded into the rate because the
    per-order minimum applies to the COMMISSION only. Folding these in would
    let the floor swallow them on small orders, understating exactly the trades
    where every dollar is a large share of the risk."""

    @classmethod
    def from_settings(cls, settings: Settings) -> CostModel:
        """The model the live system reasons with, built from configuration.

        Market-aware, because IBKR prices each market differently and live
        trading starts on ASX. Explicit per-market settings still win, so a
        deliberate override is never silently replaced by a published profile.
        """
        profile = MARKET_COST_PROFILES.get((settings.market, settings.ibkr_pricing_model))
        fields = set(settings.model_fields_set)
        commission = settings.commission_bps
        floor = settings.broker_min_commission
        if profile is not None:
            if "commission_bps" not in fields:
                commission = profile.commission_bps
            if "broker_min_commission" not in fields:
                floor = profile.min_commission
        return cls(
            commission_bps=commission,
            slippage_bps=settings.slippage_bps,
            min_commission=floor,
            third_party_bps=profile.third_party_bps if profile is not None else 0.0,
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

    def third_party(self, notional: float) -> float:
        """Exchange + clearing, proportional and never floored."""
        return abs(notional) * (self.third_party_bps / 10_000.0)

    def apply(self, notional: float) -> float:
        """Dollar cost of ONE transaction of the given notional value."""
        return self.commission(notional) + self.third_party(notional) + self.slippage(notional)

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


@dataclass(frozen=True, slots=True)
class MarketCostProfile:
    """A broker's published schedule for one market and pricing model.

    Rates are held **inclusive of GST** for Australia, matching the figures the
    operator actually pays. Mixing bases is the trap here: grossing up the
    per-order floor while leaving the rate exclusive would be right for small
    orders and understate every large one, which is precisely the error the
    fixed-fee floor was added to remove.
    """

    label: str
    commission_bps: float
    min_commission: float
    currency: str
    third_party_fees_passed_through: bool
    third_party_bps: float = 0.0
    note: str = ""

    @property
    def floor_binds_below(self) -> float:
        """Trade value under which the per-order minimum decides the cost.

        Below it the charge is flat, so cost-to-risk falls as position size
        grows; above it the charge is proportional and the ratio goes flat.
        Scaling up is a cost lever only up to this point.
        """
        if self.commission_bps <= 0:
            return float("inf")
        return self.min_commission / (self.commission_bps / 10_000.0)


# Interactive Brokers Australia, verified against the vendor's own worked
# example on the APAC stocks pricing page: 400 shares at AUD 50 is a trade
# value of AUD 20,000, and 0.088% of that is AUD 17.60 inclusive of GST
# (AUD 16.00 at the 0.08% exclusive rate). Both figures reproduce exactly.
_ASX_FIXED = MarketCostProfile(
    label="IBKR Australia - Fixed (inc GST)",
    commission_bps=8.8,  # 0.088% of trade value
    min_commission=6.60,
    currency="AUD",
    third_party_fees_passed_through=False,  # Fixed lists third party fees as None
)

# Tier I applies up to AUD 3,000,000 of monthly trade value. Same rate as
# Fixed with a lower floor, but exchange and clearing fees are passed through
# on top and are NOT modelled here - so this profile understates the true cost
# by whatever those come to.
_ASX_TIERED_1 = MarketCostProfile(
    label="IBKR Australia - Tiered Tier I (inc GST)",
    commission_bps=8.8,
    min_commission=5.50,
    currency="AUD",
    third_party_fees_passed_through=True,
    # ASX stocks, inclusive of GST: exchange 0.00001815 + clearing 0.000027225
    # = 0.000045375 of trade value. Auction trades carry a higher exchange fee
    # (0.00003388) and are not separately modelled, so an auction-heavy
    # strategy is understated by roughly 0.16bps a side.
    third_party_bps=0.45375,
    note=(
        "Tier I matches Fixed on rate (0.088%) with a lower floor (AUD 5.50), but "
        "passes exchange and clearing fees through on top. Tiered is cheaper only "
        "below about AUD 7,130 a trade, and by at most ~AUD 1.10; above that Fixed "
        "wins and its advantage grows with size."
    ),
)

MARKET_COST_PROFILES: dict[tuple[str, str], MarketCostProfile] = {
    ("ASX", "fixed"): _ASX_FIXED,
    ("ASX", "tiered"): _ASX_TIERED_1,
}
