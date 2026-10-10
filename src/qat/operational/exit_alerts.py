"""Approved Phase 2 exit plans as exact manual-TWS alerts in advisory mode.

The pure Phase 2 lifecycle defines quantities, target, breakeven, trailing,
invalidation and time-stop precedence. This layer records what the operator
must enter; it has no order-submission method or network access.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from decimal import Decimal
from typing import cast

from qat.domain.strategies.authoritative_swing.lifecycle import (
    CompletedSession,
    ConfirmedFill,
    PositionState,
    SwingPosition,
    apply_entry_fill,
    apply_target_fill,
    evaluate_completed_close,
    pending_entry_from_setup,
)
from qat.domain.strategies.authoritative_swing.model import Pattern
from qat.operational.cards import CardService


@dataclass(frozen=True, slots=True)
class ExitAlert:
    card_id: str
    position_id: str
    symbol: str
    kind: str
    side: str
    quantity: int
    order_type: str
    price: Decimal | None
    effective_open: datetime | None
    reason: str
    manual_tws_only: bool = True
    oca_group: str | None = None


class ExitAlertService:
    def __init__(self, cards: CardService) -> None:
        self.cards = cards
        self.positions: dict[str, SwingPosition] = {}
        self._manual: set[str] = set()
        self._due: dict[str, ExitAlert] = {}
        for event in cards.events.events:
            if event.kind == "position_state":
                self.positions[event.card_id] = self._restore_position(event.detail)
            elif event.kind == "manual_management":
                self._manual.add(event.card_id)
            elif event.kind == "exit_alert" and event.detail.get("kind") == "next_open_exit":
                detail = event.detail
                self._due[event.card_id] = ExitAlert(
                    event.card_id,
                    str(detail["position_id"]),
                    str(detail["symbol"]),
                    "next_open_exit",
                    str(detail["side"]),
                    int(str(detail["quantity"])),
                    str(detail["order_type"]),
                    None,
                    datetime.fromisoformat(str(detail["effective_open"])),
                    str(detail["reason"]),
                )

    @staticmethod
    def _restore_position(detail: dict[str, object]) -> SwingPosition:
        decimals = {
            "submitted_limit",
            "entry_fill",
            "initial_stop",
            "current_stop",
            "initial_r",
            "order_initial_risk_dollars",
            "fill_initial_risk_dollars",
            "target_price",
            "highest_high",
        }
        dates = {"entry_session", "target_fill_session", "last_close_evaluation_session"}
        sets = {"used_breakout_event_ids", "consumed_pattern_instance_ids", "applied_event_ids"}
        values: dict[str, object] = {}
        for field in fields(SwingPosition):
            value = detail[field.name]
            if field.name in decimals:
                value = Decimal(str(value))
            elif field.name in dates and value is not None:
                value = date.fromisoformat(str(value))
            elif field.name in sets:
                value = frozenset(cast(list[str], value))
            elif field.name == "patterns":
                value = tuple(Pattern(item) for item in cast(list[str], value))
            elif field.name == "scheduled_exit_triggers":
                value = tuple(cast(list[str], value))
            elif field.name == "state":
                value = PositionState(str(value))
            values[field.name] = value
        return SwingPosition(**values)  # type: ignore[arg-type]

    def _save_position(self, card_id: str, position: SwingPosition) -> None:
        detail: dict[str, object] = {}
        for field in fields(SwingPosition):
            value = getattr(position, field.name)
            if isinstance(value, (frozenset, tuple)):
                value = sorted(value) if isinstance(value, frozenset) else list(value)
            detail[field.name] = value
        self.cards.events.append("position_state", card_id, detail)

    def _approved_quantity(self, card_id: str) -> int:
        approved = next(
            (
                event
                for event in reversed(self.cards.events.events)
                if event.card_id == card_id and event.kind == "approved"
            ),
            None,
        )
        if approved is None:
            raise ValueError("entry exit plan has no operator approval")
        if approved.detail.get("exit_plan_approved") is not True:
            raise ValueError("full exit plan was not covered by sign-off")
        return int(str(approved.detail["quantity"]))

    async def _holding_matches(self, symbol: str, expected: int) -> bool:
        reported = [
            position.quantity
            for position in await self.cards.oms.broker.positions()
            if position.symbol == symbol
        ]
        return (
            len(reported) == 1
            and math.isfinite(reported[0])
            and reported[0].is_integer()
            and int(reported[0]) == expected
        )

    async def _require_holding(self, symbol: str, expected: int) -> None:
        if not await self._holding_matches(symbol, expected):
            self.cards.managed_positions.append(
                symbol,
                "frozen",
                {"reason": f"broker holding mismatch against planned {expected} shares"},
            )
            raise ValueError("broker holding mismatch: symbol frozen")

    def _record(self, alert: ExitAlert) -> ExitAlert:
        self.cards.events.append(
            "exit_alert",
            alert.card_id,
            {
                "position_id": alert.position_id,
                "symbol": alert.symbol,
                "kind": alert.kind,
                "side": alert.side,
                "quantity": alert.quantity,
                "order_type": alert.order_type,
                "price": str(alert.price) if alert.price is not None else None,
                "effective_open": alert.effective_open,
                "reason": alert.reason,
                "manual_tws_only": True,
                "oca_group": alert.oca_group,
            },
        )
        return alert

    async def entry_fill(self, card_id: str, fill: ConfirmedFill) -> tuple[ExitAlert, ...]:
        card = self.cards.cards[card_id]
        quantity = self._approved_quantity(card_id)
        if self.cards.managed_positions.is_frozen(card.candidate.symbol):
            raise ValueError("broker holding mismatch: symbol frozen")
        await self._require_holding(card.candidate.symbol, quantity)
        if card_id in self.positions:
            if fill.event_id in self.positions[card_id].applied_event_ids:
                return ()
            raise ValueError("entry already confirmed")
        setup = replace(card.candidate.evidence, quantity=quantity)
        position = apply_entry_fill(pending_entry_from_setup(setup), fill)
        self.positions[card_id] = position
        self._save_position(card_id, position)
        oca_group = f"QAT-{position.position_id[:16]}-BANKED"
        banked_stop = ExitAlert(
            card_id,
            position.position_id,
            position.symbol,
            "banked_protective_stop",
            "sell",
            position.banked_quantity,
            "STOP_GTC_OCA_WITH_TARGET",
            position.initial_stop,
            None,
            "Protect the banked half with an OCA stop; keep it resting during halts.",
            oca_group=oca_group,
        )
        runner_stop = ExitAlert(
            card_id,
            position.position_id,
            position.symbol,
            "runner_protective_stop",
            "sell",
            position.runner_quantity,
            "STOP_GTC",
            position.initial_stop,
            None,
            "Protect the runner independently; keep it resting during halts.",
        )
        target = ExitAlert(
            card_id,
            position.position_id,
            position.symbol,
            "partial_target",
            "sell",
            position.banked_quantity,
            "LIMIT_GTC_OCA_WITH_BANKED_STOP",
            position.target_price,
            None,
            "Rest +1R limit for the rounded-up half in an OCA group with its stop.",
            oca_group=oca_group,
        )
        return self._record(banked_stop), self._record(runner_stop), self._record(target)

    async def target_fill(self, card_id: str, fill: ConfirmedFill) -> tuple[ExitAlert, ...]:
        position = self.positions[card_id]
        if self.cards.managed_positions.is_frozen(position.symbol):
            raise ValueError("broker holding mismatch: symbol frozen")
        if fill.event_id in position.applied_event_ids:
            return ()
        updated = apply_target_fill(position, fill)
        await self._require_holding(updated.symbol, updated.runner_quantity)
        self.positions[card_id] = updated
        self._save_position(card_id, updated)
        return (
            self._record(
                ExitAlert(
                    card_id,
                    updated.position_id,
                    updated.symbol,
                    "breakeven_stop",
                    "sell",
                    updated.runner_quantity,
                    "MODIFY_STOP_GTC",
                    updated.current_stop,
                    None,
                    "After target fill, move runner stop to entry-fill breakeven; "
                    "existing stop stays until replacement is confirmed.",
                )
            ),
        )

    def _next_resumed_open(self, symbol: str, after: date) -> datetime:
        for entry in self.cards.snapshot.calendar.sessions:
            if entry.session > after and not self.cards.snapshot.halts.covers(
                symbol, entry.session
            ):
                return entry.open
        raise ValueError("no documented resumed ASX open in calendar authority")

    async def completed_close(
        self,
        card_id: str,
        *,
        session: date,
        high: Decimal,
        close: Decimal,
        ema20: Decimal,
        atr14: Decimal,
    ) -> tuple[ExitAlert, ...]:
        position = self.positions[card_id]
        if self.cards.managed_positions.is_frozen(position.symbol):
            raise ValueError("broker holding mismatch: symbol frozen")
        await self._require_holding(position.symbol, position.open_quantity)
        evaluation = evaluate_completed_close(
            position, CompletedSession(session, high, close), ema20=ema20, atr14=atr14
        )
        updated = evaluation.position
        self.positions[card_id] = updated
        self._save_position(card_id, updated)
        alerts = []
        if updated.current_stop > position.current_stop:
            alerts.append(
                self._record(
                    ExitAlert(
                        card_id,
                        updated.position_id,
                        updated.symbol,
                        "trailing_stop",
                        "sell",
                        updated.open_quantity,
                        "MODIFY_STOP_GTC",
                        updated.current_stop,
                        None,
                        "Upward-only 2x ATR trail; retain old stop until modification confirmed.",
                    )
                )
            )
        if updated.scheduled_exit_triggers and card_id not in self._due:
            due = self._record(
                ExitAlert(
                    card_id,
                    updated.position_id,
                    updated.symbol,
                    "next_open_exit",
                    "sell",
                    updated.open_quantity,
                    "MARKET_ON_OPEN",
                    None,
                    self._next_resumed_open(updated.symbol, session),
                    ", ".join(updated.scheduled_exit_triggers),
                )
            )
            self._due[card_id] = due
            alerts.append(due)
        return tuple(alerts)

    def switch_to_manual(self, card_id: str, operator: str, reason: str) -> None:
        if not operator or not reason or card_id not in self.cards.cards:
            raise ValueError("card, operator and reason required")
        self._manual.add(card_id)
        self.cards.events.append(
            "manual_management", card_id, {"operator": operator, "reason": reason}
        )

    def is_manual(self, card_id: str) -> bool:
        return card_id in self._manual or any(
            event.kind == "manual_management" and event.card_id == card_id
            for event in self.cards.events.events
        )

    def approve_manual_change(
        self,
        card_id: str,
        operator: str,
        reason: str,
        *,
        adds_exposure: bool,
        loosens_protection: bool,
        signed_off: bool,
    ) -> None:
        if not operator or not reason or not signed_off:
            raise ValueError("manual change requires fresh operator sign-off")
        self.cards.events.append(
            "change_approval",
            card_id,
            {
                "operator": operator,
                "reason": reason,
                "adds_exposure": adds_exposure,
                "loosens_protection": loosens_protection,
            },
        )
