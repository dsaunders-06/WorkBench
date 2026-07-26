"""Portfolio-level exposure governor (spec M15).

PortfolioRiskChecker already covers ES, single-name and sector concentration.
Three things it does not, all of which the original ShareTrader app added only
after they bit in production:

* **Aggregate risk-at-stop.** The sum across every position of what would be
  lost if each one hit its stop. Per-trade risk limits bound one trade; they
  say nothing about ten trades each individually within budget. The original
  measured this at 36.8% and then 30.4% against a 5% cap.
* **Max concurrent positions.** A count, not a percentage - the simplest
  possible bound on how thinly the portfolio is spread.
* **Pending orders count as exposure.** This is the subtle one. An order
  awaiting sign-off is committed but unfilled, and a governor that only looks
  at *filled* positions will happily approve a tenth candidate while nine sit
  in the blotter. The original's version of this bug let eight setups pass a
  six-position cap because all eight were tested against the same pre-scan
  snapshot.

A position with no known stop is treated as risking its **entire value**, not
zero. That is the conservative reading and it matters for adopted positions:
this app did not open them and has no idea what protects them, so assuming
they are covered would understate portfolio risk by exactly the amount that is
unknown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from qat.config import Settings
from qat.data.broker.adapter import Order, Position

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExposureSnapshot:
    """What the portfolio currently has at risk, filled and pending."""

    position_count: int
    risk_at_stop_dollars: float
    gross_exposure_dollars: float
    equity: float

    @property
    def risk_at_stop_pct(self) -> float:
        return self.risk_at_stop_dollars / self.equity if self.equity > 0 else 0.0

    @property
    def gross_exposure_pct(self) -> float:
        return self.gross_exposure_dollars / self.equity if self.equity > 0 else 0.0


@dataclass(frozen=True, slots=True)
class GovernorDecision:
    allowed: bool
    reason: str
    max_shares: float = 0.0
    snapshot: ExposureSnapshot | None = None
    inputs: dict[str, float] = field(default_factory=dict)


class PortfolioGovernor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # --- measurement ---------------------------------------------------------

    def snapshot(
        self,
        positions: list[Position],
        stops: dict[str, float],
        equity: float,
        pending_orders: list[Order] | None = None,
        prices: dict[str, float] | None = None,
    ) -> ExposureSnapshot:
        prices = prices or {}
        held: dict[str, float] = {}
        risk = 0.0
        gross = 0.0

        for pos in positions:
            quantity = abs(pos.quantity)
            if quantity <= 0:
                continue
            held[pos.symbol] = held.get(pos.symbol, 0.0) + quantity
            price = prices.get(pos.symbol) or pos.avg_price
            gross += quantity * price
            risk += quantity * self._per_share_risk(pos.symbol, price, stops)

        for order in pending_orders or []:
            # Only buys add exposure. A pending sell reduces it, and counting
            # that reduction before it fills would let the governor approve new
            # risk against headroom that does not exist yet.
            if order.side != "buy" or order.quantity <= 0:
                continue
            price = order.reference_price or prices.get(order.symbol) or 0.0
            if price <= 0:
                continue
            if order.symbol not in held:
                held[order.symbol] = order.quantity
            gross += order.quantity * price
            if order.stop_price and order.stop_price < price:
                risk += order.quantity * (price - order.stop_price)
            else:
                risk += order.quantity * price

        return ExposureSnapshot(
            position_count=len(held),
            risk_at_stop_dollars=risk,
            gross_exposure_dollars=gross,
            equity=equity,
        )

    @staticmethod
    def _per_share_risk(symbol: str, price: float, stops: dict[str, float]) -> float:
        """Risk per share down to the stop, or the whole price when no stop is
        known. Unknown protection is treated as no protection."""
        stop = stops.get(symbol)
        if stop is None or stop >= price:
            return price
        return price - stop

    # --- gating --------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        price: float,
        proposed_shares: float,
        stop_price: float | None,
        positions: list[Position],
        stops: dict[str, float],
        equity: float,
        pending_orders: list[Order] | None = None,
        prices: dict[str, float] | None = None,
    ) -> GovernorDecision:
        """Approves, trims, or rejects a candidate against portfolio-level caps."""
        snap = self.snapshot(positions, stops, equity, pending_orders, prices)
        already_held = any(
            pos.symbol == symbol and abs(pos.quantity) > 0 for pos in positions
        ) or any(order.symbol == symbol and order.side == "buy" for order in (pending_orders or []))

        def reject(reason: str) -> GovernorDecision:
            return GovernorDecision(False, reason, 0.0, snap)

        if equity <= 0:
            return reject("equity is not positive")
        if proposed_shares <= 0:
            return reject("proposed size is not positive")

        # A new *name* consumes a position slot; adding to one already held or
        # already pending does not.
        if not already_held and snap.position_count >= self.settings.max_concurrent_positions:
            return reject(
                f"already at the {self.settings.max_concurrent_positions}-position limit "
                f"({snap.position_count} held or pending)"
            )

        cap_dollars = self.settings.max_aggregate_risk_at_stop_pct * equity
        headroom = cap_dollars - snap.risk_at_stop_dollars
        if headroom <= 0:
            return reject(
                f"aggregate risk-at-stop {snap.risk_at_stop_pct:.2%} is at or above the "
                f"{self.settings.max_aggregate_risk_at_stop_pct:.2%} cap"
            )

        per_share_risk = (
            price - stop_price if stop_price is not None and stop_price < price else price
        )
        if per_share_risk <= 0:
            return reject("candidate has no measurable risk per share")

        affordable_shares = headroom / per_share_risk
        if affordable_shares < 1:
            return reject(
                f"remaining aggregate risk headroom (${headroom:,.2f}) does not cover one "
                f"share at ${per_share_risk:,.2f} of risk"
            )

        final_shares = min(proposed_shares, affordable_shares)
        trimmed = final_shares < proposed_shares

        reason = "within portfolio limits"
        if trimmed:
            reason = (
                f"trimmed from {proposed_shares:.4g} to {final_shares:.4g} shares to stay "
                f"under the {self.settings.max_aggregate_risk_at_stop_pct:.2%} aggregate "
                f"risk-at-stop cap"
            )

        return GovernorDecision(
            allowed=True,
            reason=reason,
            max_shares=final_shares,
            snapshot=snap,
            inputs={
                "aggregate_risk_pct": snap.risk_at_stop_pct,
                "position_count": float(snap.position_count),
                "headroom_dollars": headroom,
                "per_share_risk": per_share_risk,
            },
        )

    # --- de-levering ---------------------------------------------------------

    def delever_fraction(
        self,
        positions: list[Position],
        stops: dict[str, float],
        equity: float,
        prices: dict[str, float] | None = None,
    ) -> float:
        """The fraction by which EVERY position must shrink to get back under
        the aggregate cap, or 0.0 when already within it.

        Proportional rather than a judgement about which position is worst:
        aggregate risk-at-stop is a linear sum of each position's
        (quantity x per-share risk), so scaling every quantity by the same
        fraction scales the whole sum by that fraction, hitting the target
        exactly without needing to rank anything.

        Targets slightly *under* the cap rather than exactly at it - landing on
        the boundary would re-trigger this from ordinary price movement alone
        on the next check.
        """
        snap = self.snapshot(positions, stops, equity, prices=prices)
        cap = self.settings.max_aggregate_risk_at_stop_pct
        if equity <= 0 or snap.risk_at_stop_pct <= cap:
            return 0.0

        target_dollars = cap * self.settings.delever_target_fraction_of_cap * equity
        current = snap.risk_at_stop_dollars
        if current <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (target_dollars / current)))
