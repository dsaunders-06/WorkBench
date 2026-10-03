"""Exact immutable historical market events for authoritative swing replay."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from qat.domain.strategies.authoritative_swing.lifecycle import PendingEntry, SwingPosition
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor, to_raw_price


def _validate_identity(event_id: str, symbol: str) -> None:
    if not event_id or not symbol:
        raise ValueError("event identity and symbol are required")


@dataclass(frozen=True, slots=True)
class SplitEvent:
    event_id: str
    symbol: str
    effective_session: date
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        _validate_identity(self.event_id, self.symbol)
        if (
            isinstance(self.numerator, bool)
            or isinstance(self.denominator, bool)
            or not isinstance(self.numerator, int)
            or not isinstance(self.denominator, int)
        ):
            raise TypeError("split ratio terms must be exact integers")
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("split ratio terms must be positive")


@dataclass(frozen=True, slots=True)
class CashDividendEvent:
    event_id: str
    symbol: str
    effective_session: date
    declaration_date: date
    ex_session: date
    record_date: date
    payment_date: date
    amount_per_share: Decimal

    def __post_init__(self) -> None:
        _validate_identity(self.event_id, self.symbol)
        if not isinstance(self.amount_per_share, Decimal):
            raise TypeError("cash dividend requires an exact Decimal amount")
        if self.effective_session != self.ex_session:
            raise ValueError("cash dividend becomes effective on its ex-session")
        if not (
            self.declaration_date <= self.ex_session <= self.record_date <= self.payment_date
        ):
            raise ValueError("cash dividend dates are out of order")
        if not self.amount_per_share.is_finite() or self.amount_per_share < 0:
            raise ValueError("cash dividend must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class SymbolChangeEvent:
    event_id: str
    symbol: str
    effective_session: date
    new_symbol: str

    def __post_init__(self) -> None:
        _validate_identity(self.event_id, self.symbol)
        if not self.new_symbol or self.new_symbol == self.symbol:
            raise ValueError("symbol change requires a distinct new symbol")


@dataclass(frozen=True, slots=True)
class SuspensionEvent:
    event_id: str
    symbol: str
    effective_session: date
    resume_session: date | None

    def __post_init__(self) -> None:
        _validate_identity(self.event_id, self.symbol)
        if self.resume_session is not None and self.resume_session <= self.effective_session:
            raise ValueError("suspension resumption must follow its effective session")


@dataclass(frozen=True, slots=True)
class DelistingEvent:
    event_id: str
    symbol: str
    effective_session: date
    realizable_price: Decimal | None

    def __post_init__(self) -> None:
        _validate_identity(self.event_id, self.symbol)
        if self.realizable_price is not None and not isinstance(
            self.realizable_price, Decimal
        ):
            raise TypeError("delisting proceeds require an exact Decimal amount")
        if self.realizable_price is not None and (
            not self.realizable_price.is_finite() or self.realizable_price < 0
        ):
            raise ValueError("delisting value must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class DividendReceivable:
    event_id: str
    position_id: str
    symbol: str
    declaration_date: date
    ex_session: date
    record_date: date
    payment_date: date
    quantity: int
    amount_per_share: Decimal
    face_value: Decimal

    def __post_init__(self) -> None:
        _validate_identity(self.event_id, self.symbol)
        if not isinstance(self.amount_per_share, Decimal) or not isinstance(
            self.face_value, Decimal
        ):
            raise TypeError("dividend receivable requires exact Decimal amounts")
        if not self.position_id or self.quantity <= 0:
            raise ValueError("dividend entitlement needs a position and positive quantity")
        if self.face_value != Decimal(self.quantity) * self.amount_per_share:
            raise ValueError("dividend face value must equal exact share entitlement")
        if not self.face_value.is_finite() or self.face_value < 0:
            raise ValueError("dividend face value must be finite and non-negative")


def _split_quantity(quantity: int, event: SplitEvent) -> int:
    numerator = quantity * event.numerator
    if numerator % event.denominator:
        raise ValueError("split requires an unavailable fractional-share outcome")
    return numerator // event.denominator


def apply_split_to_pending(pending: PendingEntry, event: SplitEvent) -> PendingEntry:
    """Transform an unfilled order on the split's effective session."""

    if pending.symbol != event.symbol or event.event_id in pending.applied_event_ids:
        return pending
    factor = SplitFactor(event.numerator, event.denominator)
    return replace(
        pending,
        quantity=_split_quantity(pending.quantity, event),
        submitted_limit=to_raw_price(pending.submitted_limit, factor),
        initial_stop=to_raw_price(pending.initial_stop, factor),
        applied_event_ids=pending.applied_event_ids | {event.event_id},
    )


def apply_split_to_position(position: SwingPosition, event: SplitEvent) -> SwingPosition:
    """Preserve value and original risk dollars while transforming open units."""

    if position.symbol != event.symbol or event.event_id in position.applied_event_ids:
        return position
    factor = SplitFactor(event.numerator, event.denominator)
    return replace(
        position,
        submitted_limit=to_raw_price(position.submitted_limit, factor),
        entry_fill=to_raw_price(position.entry_fill, factor),
        initial_stop=to_raw_price(position.initial_stop, factor),
        current_stop=to_raw_price(position.current_stop, factor),
        initial_r=to_raw_price(position.initial_r, factor),
        total_quantity=_split_quantity(position.total_quantity, event),
        banked_quantity=_split_quantity(position.banked_quantity, event),
        runner_quantity=_split_quantity(position.runner_quantity, event),
        target_price=to_raw_price(position.target_price, factor),
        highest_high=to_raw_price(position.highest_high, factor),
        applied_event_ids=position.applied_event_ids | {event.event_id},
    )


def apply_symbol_change_to_pending(
    pending: PendingEntry, event: SymbolChangeEvent
) -> PendingEntry:
    if pending.symbol != event.symbol or event.event_id in pending.applied_event_ids:
        return pending
    return replace(
        pending,
        symbol=event.new_symbol,
        applied_event_ids=pending.applied_event_ids | {event.event_id},
    )


def apply_symbol_change_to_position(
    position: SwingPosition, event: SymbolChangeEvent
) -> SwingPosition:
    if position.symbol != event.symbol or event.event_id in position.applied_event_ids:
        return position
    return replace(
        position,
        symbol=event.new_symbol,
        applied_event_ids=position.applied_event_ids | {event.event_id},
    )


SwingMarketEvent = (
    SplitEvent
    | CashDividendEvent
    | SymbolChangeEvent
    | SuspensionEvent
    | DelistingEvent
)
