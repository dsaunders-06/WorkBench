"""The mandatory pre-trade checkpoint (spec §H, paper §18.1): sizing ->
stop/max-loss confirmation -> portfolio VaR/ES/concentration checks ->
regime scalar -> gate. Every decision - approved, rejected, or resized - is
logged to the AuditLog with its reason and inputs.

Also an Engine (per domain.orchestrator.Engine protocol): subscribes to
RegimeEvent so its exposure scalar always reflects the current regime
without a separate wiring step, exactly as spec §H requires ("multiply
exposure by RegimeEvent.exposure_scalar").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.events import RegimeEvent
from qat.domain.risk_engine.audit import AuditLog, RiskDecision
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.domain.risk_engine.portfolio_risk import PortfolioRiskChecker
from qat.domain.risk_engine.sizing import KellyVolTargetSizer


@dataclass(frozen=True, slots=True)
class OrderCandidate:
    symbol: str
    side: Literal["buy", "sell"]
    price: float
    atr: float
    win_rate: float
    win_loss_ratio: float
    candidate_returns: pd.Series
    sector: str | None = None


class RiskEngine:
    name = "risk-engine"

    def __init__(
        self,
        bus: EventBus,
        kill_switch: KillSwitch,
        settings: Settings | None = None,
        sizer: KellyVolTargetSizer | None = None,
        portfolio_checker: PortfolioRiskChecker | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self.bus = bus
        self.settings = settings or Settings()
        self.kill_switch = kill_switch
        self.sizer = sizer or KellyVolTargetSizer(settings=self.settings)
        self.portfolio_checker = portfolio_checker or PortfolioRiskChecker(settings=self.settings)
        self.audit_log = audit_log or AuditLog()
        self.regime_scalar = 1.0

    async def start(self) -> None:
        self.bus.subscribe(RegimeEvent, self._on_regime)

    async def stop(self) -> None:
        self.bus.unsubscribe(RegimeEvent, self._on_regime)

    async def _on_regime(self, event: RegimeEvent) -> None:
        self.regime_scalar = event.exposure_scalar

    def evaluate_order(
        self,
        candidate: OrderCandidate,
        equity: float,
        existing_weights: dict[str, float],
        existing_returns: dict[str, pd.Series],
        sector_by_symbol: dict[str, str] | None = None,
        available_cash: float | None = None,
    ) -> RiskDecision:
        """`available_cash` enforces the no-leverage rule (spec M12) and is
        always supplied by OMS, which owns the broker reference and fetches it
        itself so no order path can omit it.

        It is optional only because ai_advisory/guards.py re-verifies an AI
        recommendation without a broker to ask; that path is advisory and can
        never place an order, so skipping the cash check there is safe.
        """
        inputs: dict[str, Any] = {
            "symbol": candidate.symbol,
            "side": candidate.side,
            "price": candidate.price,
            "equity": equity,
            "regime_scalar": self.regime_scalar,
            "available_cash": available_cash,
        }

        if self.kill_switch.tripped:
            return self._reject(
                candidate.symbol, f"Kill-switch active: {self.kill_switch.reason}", inputs
            )

        raw_shares = self.sizer.size(
            equity, candidate.price, candidate.atr, candidate.win_rate, candidate.win_loss_ratio
        )
        if raw_shares <= 0:
            return self._reject(
                candidate.symbol, "Sizing produced zero shares (no edge or no ATR)", inputs
            )

        # Stop/max-loss confirmation (paper §18.1): the implied dollar loss at
        # the ATR stop must not exceed the per-trade risk budget - an explicit,
        # audited gate rather than an assumption baked silently into the sizer.
        stop_distance = self.settings.atr_stop_multiple * candidate.atr
        risk_budget = self.settings.per_trade_risk_pct * equity
        if stop_distance > 0 and raw_shares * stop_distance > risk_budget:
            raw_shares = risk_budget / stop_distance
            inputs["resized_for_stop_budget"] = True

        scaled_shares = raw_shares * self.regime_scalar

        # No-leverage rule (spec M12): a buy can never cost more than the cash
        # actually available, less a reserve that can never be zero. Applies to
        # buys only - a sell raises cash rather than consuming it, and refusing
        # to let the account de-risk because it is short of cash would be
        # exactly backwards.
        if candidate.side == "buy" and available_cash is not None:
            spendable = available_cash - self.settings.min_cash_reserve
            affordable_shares = spendable / candidate.price if candidate.price > 0 else 0.0
            if affordable_shares < 1:
                return self._reject(
                    candidate.symbol,
                    f"Insufficient cash: ${available_cash:,.2f} available less "
                    f"${self.settings.min_cash_reserve:,.2f} reserve affords no shares "
                    f"at ${candidate.price:,.2f}",
                    inputs,
                )
            if scaled_shares > affordable_shares:
                scaled_shares = affordable_shares
                inputs["resized_for_cash"] = True

        signed_multiplier = 1 if candidate.side == "buy" else -1
        candidate_dollar_exposure = scaled_shares * candidate.price * signed_multiplier

        portfolio_result = self.portfolio_checker.check(
            existing_weights=existing_weights,
            existing_returns=existing_returns,
            candidate_symbol=candidate.symbol,
            candidate_dollar_exposure=candidate_dollar_exposure,
            candidate_returns=candidate.candidate_returns,
            total_equity=equity,
            candidate_sector=candidate.sector,
            sector_by_symbol=sector_by_symbol,
        )
        inputs["portfolio_check"] = {
            "var_95": portfolio_result.historical_var_95,
            "var_99": portfolio_result.historical_var_99,
            "es_975": portfolio_result.expected_shortfall_975,
            "single_name_pct": portfolio_result.single_name_pct,
            "sector_pct": portfolio_result.sector_pct,
        }
        if not portfolio_result.approved:
            return self._reject(candidate.symbol, portfolio_result.reason, inputs)

        decision = RiskDecision(
            symbol=candidate.symbol,
            approved=True,
            final_shares=scaled_shares,
            reason="approved",
            inputs=inputs,
        )
        self.audit_log.record(decision)
        return decision

    def evaluate_exit(self, symbol: str, quantity: float, price: float) -> RiskDecision:
        """Approves closing an existing position at exactly `quantity` shares.

        Deliberately skips the sizing and portfolio VaR/ES/concentration checks
        that evaluate_order() applies: those gate *added* exposure, whereas an
        exit reduces it - sizing a close with the Kelly/ATR sizer would sell an
        arbitrary quantity unrelated to what is actually held, and a portfolio
        limit breach must never be a reason to refuse to de-risk.

        The kill-switch is still honoured (same semantics as every other order
        path) and the decision is still written to the AuditLog, so "every
        order carries an audited risk decision" remains true.
        """
        inputs: dict[str, Any] = {
            "symbol": symbol,
            "side": "sell",
            "price": price,
            "quantity": quantity,
            "exit": True,
        }

        if self.kill_switch.tripped:
            return self._reject(symbol, f"Kill-switch active: {self.kill_switch.reason}", inputs)
        if quantity <= 0:
            return self._reject(symbol, "Exit quantity must be positive", inputs)

        decision = RiskDecision(
            symbol=symbol,
            approved=True,
            final_shares=quantity,
            reason="exit - closing existing position (entry sizing bypassed)",
            inputs=inputs,
        )
        self.audit_log.record(decision)
        return decision

    def _reject(self, symbol: str, reason: str, inputs: dict[str, Any]) -> RiskDecision:
        decision = RiskDecision(
            symbol=symbol, approved=False, final_shares=0.0, reason=reason, inputs=inputs
        )
        self.audit_log.record(decision)
        return decision
