"""Explain the positions this application did not open (spec M25).

`OMS.adopt_broker_positions` seeds the reconciliation baseline from whatever
the account already holds, so a healthy account is not read as a discrepancy.
That is correct, and it has a consequence nobody was ever told about.

An adopted position has no stop this application placed, and `PortfolioGovernor`
treats an unknown stop as no protection - the whole position value counts as
risk-at-stop. Seven adopted holdings were therefore enough to put aggregate
risk-at-stop at 30% against a 5% cap, and every new entry for the rest of the
session was refused with "aggregate risk-at-stop is at or above the cap". Each
part of that was working as designed. The operator saw a system that had
stopped trading and no statement anywhere of why, which is the same failure the
silent kill-switch had: a correct decision nobody can account for.

This module turns that into a named condition. It computes nothing new - the
governor's arithmetic is reused rather than reimplemented, so the figure shown
is the figure that does the blocking, and the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.risk_engine.governor import PortfolioGovernor


@dataclass(frozen=True, slots=True)
class AdoptedPosition:
    symbol: str
    quantity: float
    price: float
    has_stop: bool

    @property
    def value(self) -> float:
        return abs(self.quantity) * self.price


@dataclass(frozen=True, slots=True)
class AdoptedPositionReport:
    """What was already held, and what it costs in risk budget."""

    positions: tuple[AdoptedPosition, ...]
    equity: float
    risk_at_stop_dollars: float
    """Aggregate across ALL positions - the figure the governor gates on."""
    adopted_risk_dollars: float
    """The share of it contributed by adopted positions."""
    cap_pct: float

    @property
    def count(self) -> int:
        return len(self.positions)

    @property
    def unprotected(self) -> tuple[AdoptedPosition, ...]:
        return tuple(p for p in self.positions if not p.has_stop)

    @property
    def risk_at_stop_pct(self) -> float:
        return self.risk_at_stop_dollars / self.equity if self.equity > 0 else 0.0

    @property
    def adopted_risk_pct(self) -> float:
        return self.adopted_risk_dollars / self.equity if self.equity > 0 else 0.0

    @property
    def blocking(self) -> bool:
        """True when new entries are being refused, on this evidence alone.

        Deliberately not "adopted risk is large" but "the cap is breached":
        an alarm that fires before anything is actually blocked is one the
        operator learns to scroll past.
        """
        return self.equity > 0 and self.risk_at_stop_pct >= self.cap_pct

    def headline(self) -> str:
        if not self.positions:
            return ""
        held = f"{self.count} position{'s' if self.count != 1 else ''} not opened by this app"
        if self.blocking:
            return (
                f"{held} - aggregate risk-at-stop {self.risk_at_stop_pct:.2%} is at or above "
                f"the {self.cap_pct:.2%} cap, so new entries are being refused"
            )
        return (
            f"{held} - using {self.adopted_risk_pct:.2%} of the "
            f"{self.cap_pct:.2%} risk-at-stop budget"
        )

    def explanation(self) -> str:
        if not self.positions:
            return ""
        unprotected = self.unprotected
        lines = [
            "These were already in the account when the session started, so this "
            "application did not choose them. Whatever is resting at the broker is "
            "what their risk is measured to.",
        ]
        if not unprotected:
            lines.append("Every one of them has a stop resting, so none is counted at full value.")
            return " ".join(lines)
        # Only the naked ones consume the budget, and only they are worth
        # naming. Before M31d this paragraph described every adopted position
        # that way, because the app asked nothing and assumed the worst of all
        # of them.
        names = ", ".join(f"{p.symbol} ({p.value:,.0f})" for p in sorted_by_value(unprotected))
        lines.append(
            f"No stop is resting for {names}. Unknown protection is treated as none, so the "
            f"whole position value counts against the risk budget."
        )
        lines.append(
            "Two ways out: attach a stop to each, which reduces the counted risk to "
            "the distance down to it, or close them and let the strategies open "
            "positions they have a record of."
        )
        return " ".join(lines)


def sorted_by_value(positions: tuple[AdoptedPosition, ...]) -> tuple[AdoptedPosition, ...]:
    """Biggest first: the one worth acting on leads."""
    return tuple(sorted(positions, key=lambda p: p.value, reverse=True))


def assess_adopted_positions(
    *,
    adopted_baseline: dict[str, float],
    positions: list[Position],
    stops: dict[str, float],
    equity: float,
    settings: Settings,
    prices: dict[str, float] | None = None,
    governor: PortfolioGovernor | None = None,
) -> AdoptedPositionReport | None:
    """None when nothing was adopted - the normal case, and no news.

    Returning None rather than an empty report keeps the caller from having to
    decide whether zero adopted positions is worth showing. It is not.
    """
    if not adopted_baseline:
        return None

    prices = prices or {}
    by_symbol = {pos.symbol: pos for pos in positions}
    governor = governor or PortfolioGovernor(settings)

    still_held: list[AdoptedPosition] = []
    for symbol in adopted_baseline:
        # Adopted-then-sold is gone, not adopted. The baseline is a record of
        # what was here at startup and is never rewritten, so the live position
        # list is what decides whether it still matters.
        position = by_symbol.get(symbol)
        if position is None or position.quantity == 0:
            continue
        still_held.append(
            AdoptedPosition(
                symbol=symbol,
                quantity=position.quantity,
                price=prices.get(symbol) or position.avg_price,
                has_stop=symbol in stops,
            )
        )

    if not still_held:
        return None

    total = governor.snapshot(positions=positions, stops=stops, equity=equity, prices=prices)
    adopted_only = governor.snapshot(
        positions=[by_symbol[p.symbol] for p in still_held],
        stops=stops,
        equity=equity,
        prices=prices,
    )

    return AdoptedPositionReport(
        positions=tuple(still_held),
        equity=equity,
        risk_at_stop_dollars=total.risk_at_stop_dollars,
        adopted_risk_dollars=adopted_only.risk_at_stop_dollars,
        cap_pct=settings.max_aggregate_risk_at_stop_pct,
    )
