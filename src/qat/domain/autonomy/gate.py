"""The autonomy gate (spec M13): may THIS order be signed off unattended?

Design rules this module exists to enforce:

* **Deny by default.** Every path that is not an explicit allow returns a
  block with a reason. A new failure mode that nobody anticipated lands in the
  default branch, which blocks.
* **Buys and sells are not symmetric.** A buy adds risk and passes every gate.
  A sell reduces risk, and a rail whose effect is "the account may not
  de-risk" is a broken rail - so the cash floor, the day-P&L pause and the
  strategy promotion list deliberately do not apply to sells.
* **No LLM anywhere in this file.** The gate is arithmetic and clock checks.
  An earlier build of the original app put a model in the path of protective
  exits and it declined 100% of 494 sell signals in a day, which turned
  "be cautious" into a portfolio that could only ever grow. Nothing here can
  develop an opinion.

This module decides; it does not act. Applying the decision is
AutonomousExecutor's job, and the OMS sign-off gate is still the only thing
that reaches a broker.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain import market_calendar as mc
from qat.domain.performance.scorecard import StrategyScorecard
from qat.domain.risk_engine.kill_switch import KillSwitch


def market_for_symbol(symbol: str) -> mc.Market:
    """ASX symbols carry the '.AX' suffix; everything else is treated as US.

    The same convention the original app used as its order-routing key. It is a
    convention, not a lookup - a symbol from a third market would be
    misclassified, which is a real limit while only two markets are supported.
    """
    return "ASX" if symbol.upper().endswith(".AX") else "US"


@dataclass(frozen=True, slots=True)
class AccountState:
    equity: float
    cash: float
    day_pnl_pct: float


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reason: str
    quantity: float
    market: str = ""
    session_phase: str | None = None
    resized: bool = False

    @property
    def outcome(self) -> str:
        return "auto_signed" if self.allowed else "blocked"


class AutonomyGate:
    def __init__(
        self,
        settings: Settings,
        kill_switch: KillSwitch,
        clock: Callable[[], datetime] | None = None,
        scorecard_source: Callable[[str], StrategyScorecard | None] | None = None,
    ) -> None:
        self.settings = settings
        self.kill_switch = kill_switch
        # Supplied as a callable rather than a ledger reference so the gate
        # stays a pure decision function with no knowledge of where evidence
        # comes from, and so it can be exercised without a trade history.
        self.scorecard_source = scorecard_source
        # Injectable so tests can pin a session rather than depending on when
        # the suite happens to run - a market-hours gate tested against the
        # wall clock passes or fails by time of day.
        self.clock = clock

    def evaluate(
        self,
        order: Order,
        account: AccountState,
        current_price: float | None = None,
        now: datetime | None = None,
    ) -> GateDecision:
        market = market_for_symbol(order.symbol)
        if now is None and self.clock is not None:
            now = self.clock()
        session = mc.session_for(market, now)
        phase = session.phase

        def block(reason: str) -> GateDecision:
            return GateDecision(
                allowed=False,
                reason=reason,
                quantity=0.0,
                market=market,
                session_phase=phase,
            )

        # --- Rails that apply to every order, buy or sell --------------------
        if self.settings.execution_mode != "auto":
            return block("execution mode is 'recommend' - orders await human sign-off")
        if self.settings.is_live and not self.settings.allow_autonomous_live_trading:
            return block("autonomous execution is not permitted on a live account")
        if self.kill_switch.tripped:
            return block(f"kill-switch active: {self.kill_switch.reason}")
        if order.status != "pending_signoff":
            return block(f"order is not pending sign-off (status={order.status})")
        if order.quantity <= 0:
            return block("order quantity is not positive")
        # --- A resting protective order outranks the session check (M33c) ---
        #
        # Found by running it: on 1 August the app detected an unprotected
        # position, proposed the repair, and then blocked ITSELF from applying
        # it because the market was shut - while a manual sign-off of the same
        # order was accepted by Alpaca without complaint, because GTC orders
        # rest fine outside hours.
        #
        # The rail was dormant in precisely the window it exists for. Brackets
        # die AT the close; that is when all six positions lost their stops.
        # Unattended, the fix would have sat in the blotter until Monday with
        # the positions bare all weekend.
        #
        # Deliberately narrower than "any sell". A market sell transmitted into
        # a closed market is an unpriced fill at the open, and stays blocked. A
        # stop or OCO placed GTC executes nothing until its level trades, so
        # placing it early costs nothing and is the entire point.
        if order.is_protective_stop:
            return GateDecision(
                allowed=True,
                reason="resting protective order - rests GTC, so a closed session is "
                "the right time to place it rather than a reason to wait",
                quantity=order.quantity,
                market=market,
                session_phase=phase,
            )

        if not session.is_open:
            return block(f"{market} market is closed ({session.closed_reason})")

        # --- Sells: risk-reducing, so the risk-appetite rails do not apply ---
        if order.side == "sell":
            return GateDecision(
                allowed=True,
                reason="protective/exit sell - risk-reducing orders are not gated on "
                "appetite limits",
                quantity=order.quantity,
                market=market,
                session_phase=phase,
            )

        # --- Buys: every gate ------------------------------------------------
        if not session.is_autonomous_eligible:
            return block(f"session phase '{phase}' is not eligible for unattended execution")

        promoted = self.settings.autonomous_strategies_tuple
        if not order.strategy:
            return block("order carries no strategy attribution, so it cannot be promoted")
        if order.strategy not in promoted:
            return block(
                f"strategy '{order.strategy}' is not on the autonomous list "
                f"({', '.join(promoted) if promoted else 'none promoted'})"
            )

        # Evidence gate (M16, made unskippable on live in M29). Being on the
        # operator's list is necessary but not sufficient: the strategy must
        # also still meet the promotion bar on its own realised trades. A
        # strategy that qualified last month and has since degraded stops
        # trading unattended without anyone having to notice and edit a
        # setting.
        #
        # `promotion_evidence_enforced` is true on any live account regardless
        # of the flag - paper is where the evidence is produced, live is where
        # it is required, and that is not a thing anyone should be able to
        # forget. The bar reads net figures as of M28; before that it would
        # have gated on numbers already known to be optimistic.
        if self.settings.promotion_evidence_enforced and self.scorecard_source is not None:
            card = self.scorecard_source(order.strategy)
            if card is not None and not card.eligible:
                failures = "; ".join(c.detail for c in card.failing)
                return block(
                    f"strategy '{order.strategy}' is promoted but no longer meets the "
                    f"evidence bar: {failures}"
                )

        if account.day_pnl_pct <= self.settings.autonomous_pause_buys_below_day_pnl_pct:
            return block(
                f"day P&L {account.day_pnl_pct:.2%} is at or below the "
                f"{self.settings.autonomous_pause_buys_below_day_pnl_pct:.2%} pause threshold"
            )

        if current_price is not None and order.reference_price:
            drift = abs(current_price - order.reference_price) / order.reference_price
            if drift > self.settings.autonomous_price_drift_limit_pct:
                return block(
                    f"price has drifted {drift:.2%} from the {order.reference_price:.2f} "
                    f"this order was sized against (limit "
                    f"{self.settings.autonomous_price_drift_limit_pct:.2%})"
                )

        quantity = order.quantity
        resized = False
        if account.day_pnl_pct <= self.settings.autonomous_halve_size_below_day_pnl_pct:
            quantity = max(1.0, quantity // 2)
            resized = True
            if quantity <= 0:
                return block("halved size rounds to zero shares")

        reason = "all autonomy preconditions met"
        if resized:
            reason += (
                f"; size halved from {order.quantity:g} to {quantity:g} on day P&L "
                f"{account.day_pnl_pct:.2%}"
            )

        return GateDecision(
            allowed=True,
            reason=reason,
            quantity=quantity,
            market=market,
            session_phase=phase,
            resized=resized,
        )
