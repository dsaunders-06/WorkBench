"""Exact immutable historical market events for authoritative swing replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


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
        if self.realizable_price is not None and (
            not self.realizable_price.is_finite() or self.realizable_price < 0
        ):
            raise ValueError("delisting value must be finite and non-negative")


SwingMarketEvent = (
    SplitEvent
    | CashDividendEvent
    | SymbolChangeEvent
    | SuspensionEvent
    | DelistingEvent
)
