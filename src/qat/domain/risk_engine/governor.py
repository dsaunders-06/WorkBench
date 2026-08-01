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

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Order, Position

logger = logging.getLogger(__name__)

# Below this many shared observations a correlation is noise. Trimming a real
# position on the strength of three overlapping days would be worse than not
# measuring at all.
_MIN_CORRELATION_OBSERVATIONS = 20


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

    def _correlated_holdings(
        self,
        candidate_returns: pd.Series,
        existing_returns: dict[str, pd.Series],
        positions: list[Position],
    ) -> list[str]:
        """Held symbols whose returns track the candidate's at or above the
        threshold.

        Pairs are aligned on their shared index before correlating, and a pair
        with too little overlap is skipped rather than counted. Correlation on
        three shared observations is noise, and treating noise as "these move
        together" would trim real positions for no reason.

        A holding that cannot be measured is NOT assumed correlated. That is
        the opposite of the unknown-stop rule, and deliberately so: an unknown
        stop is a position that might be unprotected, where the conservative
        reading costs nothing but size. An unknown correlation defaults to
        refusing to trade anything the app has no history for, which is every
        new symbol.
        """
        held = {pos.symbol for pos in positions if abs(pos.quantity) > 0}
        correlated: list[str] = []
        for symbol in held:
            other = existing_returns.get(symbol)
            if other is None:
                continue
            aligned_candidate, aligned_other = candidate_returns.align(other, join="inner")
            if len(aligned_candidate) < _MIN_CORRELATION_OBSERVATIONS:
                continue
            corr = aligned_candidate.corr(aligned_other)
            if pd.notna(corr) and corr >= self.settings.correlation_cluster_threshold:
                correlated.append(symbol)
        return correlated

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
        candidate_sector: str | None = None,
        sector_by_symbol: dict[str, str] | None = None,
        candidate_returns: pd.Series | None = None,
        existing_returns: dict[str, pd.Series] | None = None,
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

        # --- single-name concentration, TRIMMED not refused (M30) ------------
        #
        # PortfolioRiskChecker also tests this, but as a pass/fail. That is the
        # wrong shape for a cap that binds in normal operation: 1% risk over a
        # ~5% stop sizes a position at about 20% of equity, so lowering the cap
        # to 15% under reject semantics would refuse every swing trade outright
        # rather than making it smaller. Trimming is the established pattern
        # here - the aggregate risk cap has always worked this way - and it
        # leaves the checker downstream as a backstop that now never has cause
        # to fire.
        name_cap_dollars = self.settings.max_single_name_concentration_pct * equity
        held_in_name = sum(
            abs(pos.quantity) * (prices or {}).get(pos.symbol, pos.avg_price)
            for pos in positions
            if pos.symbol == symbol
        ) + sum(
            order.quantity * (order.reference_price or price)
            for order in (pending_orders or [])
            if order.symbol == symbol and order.side == "buy"
        )
        name_affordable_shares = max(0.0, name_cap_dollars - held_in_name) / price
        if name_affordable_shares < 1:
            return reject(
                f"{symbol} already holds ${held_in_name:,.0f}, at or above the "
                f"{self.settings.max_single_name_concentration_pct:.0%} single-name cap"
            )

        # --- sector concentration, TRIMMED not refused (M31c) ----------------
        #
        # The same change single-name got in M30, and for the same reason:
        # PortfolioRiskChecker tests this as a pass/fail, so lowering the cap
        # under reject semantics refuses a candidate outright rather than
        # sizing it down. With 15% names, a 30% sector cap is reached by the
        # third position in a sector, and refusing there would silently stop a
        # strategy trading a sector it is already in rather than letting it
        # take a smaller position.
        #
        # Sectors that look diversified in calm markets converge in a crisis,
        # which is exactly when the cap is supposed to be doing something.
        sector_affordable_shares = float("inf")
        held_in_sector = 0.0
        if candidate_sector and sector_by_symbol:
            sector_cap_dollars = self.settings.max_sector_concentration_pct * equity
            held_in_sector = sum(
                abs(pos.quantity) * (prices or {}).get(pos.symbol, pos.avg_price)
                for pos in positions
                if sector_by_symbol.get(pos.symbol) == candidate_sector
            ) + sum(
                order.quantity * (order.reference_price or price)
                for order in (pending_orders or [])
                if order.side == "buy" and sector_by_symbol.get(order.symbol) == candidate_sector
            )
            sector_affordable_shares = max(0.0, sector_cap_dollars - held_in_sector) / price
            if sector_affordable_shares < 1:
                return reject(
                    f"{candidate_sector} already holds ${held_in_sector:,.0f}, at or above the "
                    f"{self.settings.max_sector_concentration_pct:.0%} sector cap"
                )

        # --- correlated cluster, TRIMMED not refused (M33) --------------------
        #
        # Single-name bounds one ticker. Sector bounds one GICS label. Neither
        # catches six names that simply move together, and eight "different"
        # positions at 0.85 pairwise correlation are one position taken eight
        # times, with eight lots of commission and none of the diversification
        # the position count implies.
        #
        # Sector has been this system's proxy for it, and the proxy fails in
        # exactly the conditions the limit exists for: correlations converge in
        # a crisis, and a bank and a homebuilder in different sectors stop
        # being different at the moment that matters.
        #
        # Measured, not labelled. A holding counts toward the candidate's
        # cluster when their returns correlate at or above the threshold, so
        # the cluster is defined per-candidate rather than being a fixed
        # partition of the universe - which is what correlation actually is.
        cluster_affordable_shares = float("inf")
        held_in_cluster = 0.0
        cluster_members: list[str] = []
        if candidate_returns is not None and existing_returns:
            cluster_members = self._correlated_holdings(
                candidate_returns, existing_returns, positions
            )
            if cluster_members:
                cluster_cap_dollars = self.settings.max_correlated_cluster_pct * equity
                held_in_cluster = sum(
                    abs(pos.quantity) * (prices or {}).get(pos.symbol, pos.avg_price)
                    for pos in positions
                    if pos.symbol in cluster_members
                )
                cluster_affordable_shares = max(0.0, cluster_cap_dollars - held_in_cluster) / price
                if cluster_affordable_shares < 1:
                    return reject(
                        f"{len(cluster_members)} holding(s) correlated at or above "
                        f"{self.settings.correlation_cluster_threshold:.2f} "
                        f"({', '.join(sorted(cluster_members))}) already hold "
                        f"${held_in_cluster:,.0f}, at or above the "
                        f"{self.settings.max_correlated_cluster_pct:.0%} cluster cap"
                    )

        # --- gap risk, budgeted separately from stop risk (M30) --------------
        #
        # Every figure above means "if the stop fills". A gap opens through it:
        # measured across 28,987 overnight holds on this universe, 45 (0.16%)
        # jumped a 2.5x ATR stop, the worst costing 2.0R instead of 1R on a
        # -22.1% gap. A different hazard from the one the risk-at-stop cap
        # governs, so it gets its own budget rather than being squeezed through
        # the concentration cap.
        #
        # The shock applies to NOTIONAL, because that is what a gap moves - the
        # stop is irrelevant to a price that never traded there.
        gap_cap_dollars = self.settings.max_gap_risk_at_shock_pct * equity
        gap_affordable_notional = (
            gap_cap_dollars / self.settings.gap_shock_pct
        ) - snap.gross_exposure_dollars
        gap_affordable_shares = max(0.0, gap_affordable_notional) / price
        if gap_affordable_shares < 1:
            return reject(
                f"a {self.settings.gap_shock_pct:.1%} overnight gap across "
                f"${snap.gross_exposure_dollars:,.0f} already held would cost more than the "
                f"{self.settings.max_gap_risk_at_shock_pct:.1%} gap budget"
            )

        limits = {
            f"{self.settings.max_aggregate_risk_at_stop_pct:.0%} aggregate risk-at-stop": (
                affordable_shares
            ),
            f"{self.settings.max_single_name_concentration_pct:.0%} single-name": (
                name_affordable_shares
            ),
            f"{self.settings.gap_shock_pct:.0%} overnight-gap": gap_affordable_shares,
        }
        if candidate_sector and sector_by_symbol:
            limits[
                f"{self.settings.max_sector_concentration_pct:.0%} {candidate_sector} sector"
            ] = sector_affordable_shares
        if cluster_members:
            limits[
                f"{self.settings.max_correlated_cluster_pct:.0%} correlated-cluster "
                f"({len(cluster_members)} name(s))"
            ] = cluster_affordable_shares
        final_shares = min(proposed_shares, *limits.values())
        trimmed = final_shares < proposed_shares

        reason = "within portfolio limits"
        if trimmed:
            binding = min(limits, key=lambda name: limits[name])
            reason = (
                f"trimmed from {proposed_shares:.4g} to {final_shares:.4g} shares to stay "
                f"under the {binding} cap"
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
                "held_in_name_dollars": held_in_name,
                "held_in_sector_dollars": held_in_sector,
                "held_in_cluster_dollars": held_in_cluster,
                "cluster_size": float(len(cluster_members)),
                "gross_exposure_pct": snap.gross_exposure_pct,
                "gap_loss_at_shock_dollars": snap.gross_exposure_dollars
                * self.settings.gap_shock_pct,
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
