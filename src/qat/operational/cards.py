"""Paper-only recommendation decisions and manual opening-auction instructions.

The Phase 2 engine and operational adapter do not import this hand-off layer.
There is deliberately no broker submission path: auction capability has not
been verified against the Gateway GTC preset. Card events are operational
decisions, not the Phase 3 shadow lifecycle reserved for step 5.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Literal

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.sectors import SECTOR_BY_SYMBOL
from qat.domain.oms.card_orders import CardOrderStore, card_order_id
from qat.domain.oms.oms import OMS
from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
)
from qat.domain.strategies.authoritative_swing.sizing import modeled_total_risk, size_instruction
from qat.operational.adapter import AdapterResult, CardCandidate, FrozenSnapshot, OperationalAdapter
from qat.operational.consolidations import ConsolidationLedger
from qat.operational.history import OPERATIONAL, HistoryStore, digest, require_operational_file

SIZING_BASIS = "fixed 1% risk to stop, no edge assumed"
# Explicit capability flag. This build contains no path that can enable it:
# OMS and both real broker adapters independently refuse the auction intent.
OPENING_AUCTION_TRANSMISSION_ENABLED = False
CardEventKind = Literal[
    "created",
    "approved",
    "declined",
    "revoked",
    "expired",
    "exit_alert",
    "manual_management",
    "change_approval",
    "position_state",
]
_CARD_STATUSES = {"created", "approved", "declined", "revoked", "expired"}


class TransmissionDisabled(ValueError):
    """No paper capability has been verified; manual TWS entry only."""


class ReconfirmationRequired(ValueError):
    def __init__(
        self,
        previous: int,
        current: int,
        previous_risk: Decimal = Decimal(0),
        current_risk: Decimal = Decimal(0),
    ) -> None:
        self.previous = previous
        self.current = current
        self.previous_risk = previous_risk
        self.current_risk = current_risk
        super().__init__(f"quantity changed from {previous} to {current}; reconfirmation required")


@dataclass(frozen=True, slots=True)
class CardEvent:
    sequence: int
    kind: CardEventKind
    card_id: str
    detail: dict[str, object]
    previous_hash: str
    content_hash: str


class CardEventStore:
    """Append-only, hash-chained decisions under an existing OPERATIONAL root."""

    def __init__(self, path: Path) -> None:
        require_operational_file(path)
        self.path = path
        self.events: list[CardEvent] = []
        if path.exists():
            if path.is_symlink():
                raise ValueError("linked card decision store")
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("invalid card event")
                event = CardEvent(**row)
                self._validate_next(event)
                self.events.append(event)

    def _validate_next(self, event: CardEvent) -> None:
        identity = {
            "sequence": event.sequence,
            "kind": event.kind,
            "card_id": event.card_id,
            "detail": event.detail,
            "previous_hash": event.previous_hash,
        }
        if (
            event.sequence != len(self.events) + 1
            or event.previous_hash != (self.events[-1].content_hash if self.events else "")
            or digest(identity) != event.content_hash
            or event.kind
            not in _CARD_STATUSES
            | {
                "exit_alert",
                "manual_management",
                "change_approval",
                "position_state",
            }
            or not event.card_id
        ):
            raise ValueError("card decision chain invalid")

    def _verify_disk(self) -> None:
        current = CardEventStore(self.path)
        if [event.content_hash for event in current.events] != [
            event.content_hash for event in self.events
        ]:
            raise ValueError("card decision rollback or truncation")

    def append(self, kind: CardEventKind, card_id: str, detail: dict[str, object]) -> CardEvent:
        require_operational_file(self.path)
        self._verify_disk()
        identity = {
            "sequence": len(self.events) + 1,
            "kind": kind,
            "card_id": card_id,
            "detail": detail,
            "previous_hash": self.events[-1].content_hash if self.events else "",
        }
        event = CardEvent(
            len(self.events) + 1,
            kind,
            card_id,
            detail,
            self.events[-1].content_hash if self.events else "",
            digest(identity),
        )
        self._validate_next(event)
        payload = canonical_payload(event) + b"\n"
        with self.path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        return event

    def status(self, card_id: str) -> str | None:
        self._verify_disk()
        return next(
            (
                event.kind
                for event in reversed(self.events)
                if event.card_id == card_id and event.kind in _CARD_STATUSES
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class RecommendationCard:
    card_id: str
    candidate: CardCandidate
    quantity: int
    risk: Decimal
    sizing_basis: str
    reasons: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class ManualOrderInstruction:
    card_id: str
    order_id: str
    symbol: str
    quantity: int
    entry_limit: Decimal
    structural_stop: Decimal
    auction_open: datetime
    risk: Decimal
    exit_plan: tuple[str, ...]


def card_identity(candidate: CardCandidate) -> str:
    return digest(
        {
            "snapshot": candidate.snapshot_hash,
            "decision": candidate.evidence.decision_id,
            "symbol": candidate.symbol,
            "session": candidate.session,
        }
    )


def _decimal(value: float) -> Decimal:
    if not math.isfinite(value):
        raise ValueError("account value is not finite")
    return Decimal(str(value))


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _returns(records: tuple[FinalBar, ...]) -> pd.Series:
    closes = pd.Series(
        (float(bar.adjusted.close) for bar in records),
        index=pd.to_datetime([bar.session for bar in records]),
        dtype=float,
    )
    return closes.pct_change().dropna()


class CardService:
    def __init__(
        self,
        adapter: OperationalAdapter,
        snapshot: FrozenSnapshot,
        oms: OMS,
        settings: Settings,
        events: CardEventStore,
        history: HistoryStore,
    ) -> None:
        if settings.is_live or settings.trading_mode != "paper":
            raise ValueError("recommendation hand-off requires a paper account")
        if settings.execution_mode != "recommend":
            raise ValueError("recommendation hand-off requires recommend mode")
        if snapshot.label != OPERATIONAL or snapshot.content_hash != digest(snapshot.identity()):
            raise ValueError("frozen OPERATIONAL snapshot required")
        if events.path.parent.resolve() != history.database.parent.resolve():
            raise ValueError("card decisions must share the operational namespace")
        self.adapter = adapter
        self.snapshot = snapshot
        self.oms = oms
        self.settings = settings
        self.events = events
        self.history = history
        self.order_store = CardOrderStore(history.database.parent / "card_orders.json")
        self.cards: dict[str, RecommendationCard] = {}
        self.managed_positions = ConsolidationLedger(
            history.database.parent / "managed_positions.sqlite3"
        )

    def _bars(self, symbol: str) -> tuple[FinalBar, ...]:
        record = next((item for item in self.snapshot.symbols if item.symbol == symbol), None)
        if record is None:
            raise ValueError("candidate symbol absent from frozen snapshot")
        return tuple(
            FinalBar(
                bar.bar.symbol,
                bar.bar.session,
                bar.bar.raw,
                bar.bar.analytical,
                bar.bar.source,
                DataQuality.VERIFIED,
                AdjustmentStatus.SPLIT_NORMALIZED,
                bar.bar.factor,
                bar.bar.finalised,
                bar.content_hash,
            )
            for bar in record.records
        )

    def _refusal(self, symbol: str) -> str | None:
        if self.managed_positions.is_frozen(symbol):
            return "broker holding mismatch: symbol frozen pending operator reconciliation"
        if self.oms.kill_switch.tripped:
            return "kill-switch tripped"
        if reason := self.oms.entry_permitted(symbol):
            return reason
        if anomaly := self.oms.anomalies.get(symbol):
            return f"position anomaly: {anomaly.reason}"
        if resting_anomaly := self.oms.resting_order_anomalies.get(symbol):
            return f"resting order anomaly: {resting_anomaly.reason}"
        if action := self.oms._pending_action(symbol):
            return f"corporate action pending: {action}"
        return None

    async def _size(
        self, candidate: CardCandidate, *, equity: Decimal, cash: Decimal
    ) -> tuple[int, Decimal, tuple[str, ...]]:
        refusal = self._refusal(candidate.symbol)
        if refusal:
            return 0, Decimal(0), (refusal,)
        bars = self._bars(candidate.symbol)
        params = self.snapshot.parameters
        sizing = size_instruction(
            equity=equity,
            available_cash=cash,
            limit=candidate.entry_limit_raw,
            stop=candidate.structural_stop_raw,
            bars=bars,
            signal_session=candidate.session,
            cost_profile=params.costs,
            liquidity_profile=params.liquidity,
        )
        if sizing.status is not DecisionStatus.QUALIFIED or params.liquidity is None:
            return 0, Decimal(0), ("fixed-risk or liquidity sizing blocked",)
        quantity = sizing.quantity
        reasons: list[str] = []
        spendable = max(Decimal(0), cash - _decimal(self.settings.min_cash_reserve))
        cash_cap = _floor(
            spendable * _decimal(self.oms.max_order_pct_of_cash) / candidate.entry_limit_raw
        )
        if cash_cap < quantity:
            quantity = cash_cap
            reasons.append("Phase 1 per-order spendable-cash cap reduced quantity")
        ceiling = self.settings.broker_max_order_shares
        if ceiling is not None and ceiling < quantity:
            quantity = ceiling
            reasons.append("Phase 1 broker order-size ceiling reduced quantity")
        scalar = _decimal(self.oms.risk_engine.regime_scalar)
        if scalar < 1:
            quantity = min(quantity, _floor(Decimal(quantity) * scalar))
            reasons.append("Phase 1 regime scalar reduced quantity")
        if quantity < 2:
            return 0, Decimal(0), (*reasons, "fewer than two whole shares")
        positions = await self.oms.broker.positions()
        pending = self.oms.pending_orders()
        history_by_symbol = {item.symbol: item for item in self.snapshot.symbols}
        for symbol in {pos.symbol for pos in positions} | {
            order.symbol for order in pending if order.side == "buy"
        }:
            record = history_by_symbol.get(symbol)
            if record is None or not record.quality.eligible:
                return (
                    0,
                    Decimal(0),
                    (
                        *reasons,
                        f"holding {symbol} lacks eligible OPERATIONAL history",
                    ),
                )
        current_returns = _returns(bars)
        existing_returns = {
            pos.symbol: _returns(self._bars(pos.symbol))
            for pos in positions
            if any(item.symbol == pos.symbol for item in self.snapshot.symbols)
        }
        sector = SECTOR_BY_SYMBOL.get(candidate.symbol)
        sectors = {symbol: name for symbol, name in SECTOR_BY_SYMBOL.items()}
        governor = self.oms.risk_engine.governor.evaluate(
            symbol=candidate.symbol,
            price=float(candidate.entry_limit_raw),
            proposed_shares=float(quantity),
            stop_price=float(candidate.structural_stop_raw),
            positions=positions,
            stops=self.oms.position_stops(),
            equity=float(equity),
            pending_orders=pending,
            candidate_sector=sector,
            sector_by_symbol=sectors,
            candidate_returns=current_returns,
            existing_returns=existing_returns,
        )
        if not governor.allowed:
            return 0, Decimal(0), (*reasons, governor.reason)
        governed = min(quantity, math.floor(governor.max_shares))
        if governed < quantity:
            quantity = governed
            reasons.append(governor.reason)
        if quantity < 2:
            return 0, Decimal(0), (*reasons, "fewer than two whole shares")
        weights = {
            pos.symbol: pos.quantity * (pos.current_price or pos.avg_price) for pos in positions
        }
        for order in pending:
            if order.side == "buy":
                weights[order.symbol] = weights.get(order.symbol, 0.0) + order.quantity * (
                    order.reference_price or 0.0
                )
        check = self.oms.risk_engine.portfolio_checker.check(
            weights,
            existing_returns,
            candidate.symbol,
            float(Decimal(quantity) * candidate.entry_limit_raw),
            current_returns,
            float(equity),
            sector,
            sectors,
        )
        if not check.approved:
            return 0, Decimal(0), (*reasons, check.reason)
        risk = modeled_total_risk(
            quantity,
            candidate.entry_limit_raw,
            candidate.structural_stop_raw,
            params.costs,
            params.liquidity,
        )
        phase1_budget = equity * _decimal(self.settings.per_trade_risk_pct)
        while quantity > 0 and risk > phase1_budget:
            quantity -= 1
            risk = modeled_total_risk(
                quantity,
                candidate.entry_limit_raw,
                candidate.structural_stop_raw,
                params.costs,
                params.liquidity,
            )
        if quantity < 2:
            return 0, Decimal(0), (*reasons, "Phase 1 stop-risk budget blocked")
        if self.oms.risk_engine._costs_apply():
            round_trip = self.oms.risk_engine.cost_model.round_trip(
                float(Decimal(quantity) * candidate.entry_limit_raw)
            )
            price_risk = Decimal(quantity) * (
                candidate.entry_limit_raw - candidate.structural_stop_raw
            )
            if Decimal(str(round_trip)) > _decimal(self.settings.max_cost_to_risk_pct) * price_risk:
                return 0, Decimal(0), (*reasons, "Phase 1 cost-to-risk rail blocked")
        return quantity, risk, tuple(reasons)

    async def publish(
        self, result: AdapterResult, *, now: datetime
    ) -> tuple[RecommendationCard, ...]:
        if now >= self.snapshot.calendar.next_open(self.snapshot.session):
            return ()
        cards = []
        for candidate in result.candidates:
            if self.managed_positions.is_frozen(candidate.symbol):
                continue
            if candidate.snapshot_hash != self.snapshot.content_hash:
                raise ValueError("card candidate snapshot mismatch")
            card_id = card_identity(candidate)
            if card_id in self.cards:
                cards.append(self.display(card_id, now=now))
                continue
            quantity, risk, reasons = await self._size(
                candidate,
                equity=self.snapshot.parameters.equity,
                cash=self.snapshot.parameters.available_cash,
            )
            if self.events.status(card_id) is None:
                self.events.append(
                    "created",
                    card_id,
                    {"snapshot": candidate.snapshot_hash, "symbol": candidate.symbol},
                )
            card = RecommendationCard(
                card_id, candidate, quantity, risk, SIZING_BASIS, reasons, "created"
            )
            self.cards[card_id] = card
            cards.append(self.display(card_id, now=now))
        return tuple(cards)

    def _source_changed(self, candidate: CardCandidate) -> bool:
        if (
            self.snapshot.content_hash != candidate.snapshot_hash
            or digest(self.snapshot.identity()) != self.snapshot.content_hash
        ):
            return True
        current = self.history.decision_bars(candidate.symbol, candidate.session)
        old = tuple((r.session, r.version, r.content_hash) for r in candidate.source_records)
        new = tuple((r.bar.session, r.version, r.content_hash) for r in current)
        return old != new

    def display(self, card_id: str, *, now: datetime) -> RecommendationCard:
        card = self.cards[card_id]
        status = self.events.status(card_id)
        if status not in {"revoked", "expired", "declined"}:
            try:
                changed = self._source_changed(card.candidate)
                reason = "accepted input correction"
            except (ValueError, OSError, sqlite3.Error):
                changed = True
                reason = "operational input integrity unavailable"
            if changed:
                self.events.append("revoked", card_id, {"reason": reason})
                status = "revoked"
            elif now >= card.candidate.expires_at:
                self.events.append("expired", card_id, {"reason": "next ASX open"})
                status = "expired"
        return replace(card, status=status or "created")

    def _active(self, card_id: str, now: datetime) -> RecommendationCard:
        card = self.display(card_id, now=now)
        if card.status in {"revoked", "expired", "declined"}:
            raise ValueError(f"card {card.status}")
        if reason := self._refusal(card.candidate.symbol):
            raise ValueError(reason)
        return card

    def decline(self, card_id: str, operator: str, *, now: datetime) -> None:
        self._active(card_id, now)
        if not operator:
            raise ValueError("operator identity required")
        self.events.append("declined", card_id, {"operator": operator})

    def _manual_instruction(
        self, card: RecommendationCard, quantity: int, risk: Decimal
    ) -> ManualOrderInstruction:
        candidate = card.candidate
        return ManualOrderInstruction(
            card.card_id,
            card_order_id(card.card_id),
            candidate.symbol,
            quantity,
            candidate.entry_limit_raw,
            candidate.structural_stop_raw,
            candidate.expires_at,
            risk,
            (
                "At the entry fill: place the structural protective stop for all held shares.",
                "At fill +1R: rest a sell limit for the rounded-up half; "
                "after fill move the runner stop to breakeven.",
                "Thereafter trail the runner stop upward only, using the Phase 2 2x ATR rule.",
                "Close invalidation or ten completed sessions: present one exit "
                "for the next ASX open.",
                "A documented halt keeps protection resting and defers a due exit to resumption.",
            ),
        )

    def preview(self, card_id: str, *, now: datetime) -> ManualOrderInstruction:
        card = self._active(card_id, now)
        if card.quantity < 2:
            raise ValueError("Phase 1 safeguards blocked this card")
        return self._manual_instruction(card, card.quantity, card.risk)

    async def approve(
        self, card_id: str, operator: str, *, now: datetime, reconfirm: bool = False
    ) -> ManualOrderInstruction:
        card = self._active(card_id, now)
        if not operator:
            raise ValueError("operator identity required")
        if card.status == "approved":
            record = next(
                event
                for event in reversed(self.events.events)
                if event.card_id == card_id and event.kind == "approved"
            )
            quantity = int(str(record.detail["quantity"]))
            risk = Decimal(str(record.detail["risk"]))
            return self._manual_instruction(card, quantity, risk)
        account = await self.oms.broker.account()
        quantity, risk, reasons = await self._size(
            card.candidate, equity=_decimal(account.net_liquidation), cash=_decimal(account.cash)
        )
        if quantity < 2:
            raise ValueError("fresh Phase 1 safeguards blocked: " + "; ".join(reasons))
        if (quantity != card.quantity or risk != card.risk) and not reconfirm:
            raise ReconfirmationRequired(card.quantity, quantity, card.risk, risk)
        self._active(card_id, now)
        instruction = self._manual_instruction(card, quantity, risk)
        self.order_store.reserve(
            card_id,
            Order(
                symbol=instruction.symbol,
                side="buy",
                quantity=quantity,
                order_id=instruction.order_id,
                order_type="opening_auction_limit",
                limit_price=float(instruction.entry_limit),
                reference_price=float(instruction.entry_limit),
                stop_price=float(instruction.structural_stop),
                auction_open=instruction.auction_open,
                strategy="authoritative_swing",
            ),
        )
        self.events.append(
            "approved",
            card_id,
            {
                "operator": operator,
                "quantity": quantity,
                "risk": str(risk),
                "reconfirmed": reconfirm,
                "reasons": reasons,
                "order_id": instruction.order_id,
                "exit_plan": instruction.exit_plan,
                "exit_plan_approved": True,
            },
        )
        return instruction

    async def submit(self, card_id: str, *, now: datetime) -> None:
        self._active(card_id, now)
        if self.events.status(card_id) != "approved":
            raise ValueError("card has no approval")
        if not OPENING_AUCTION_TRANSMISSION_ENABLED:
            raise TransmissionDisabled("opening auction capability unverified; manual TWS only")
        # A separate reviewed change must build the verified broker path.
        raise TransmissionDisabled("opening auction broker translation is not implemented")
