"""Append-only audit log (spec §H/§L): every approve/reject/resize decision
is logged with its reason and inputs, sufficient to reconstruct any trading
session's risk decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RiskDecision:
    symbol: str
    approved: bool
    final_shares: float
    reason: str
    inputs: dict[str, Any]
    # The stop this order was actually sized against - the strategy's own when
    # it supplied one, otherwise the ATR stop the sizer used. Carried out of
    # the decision so OMS can attach it to the order as a real broker bracket:
    # a stop that exists only as a sizing assumption protects nothing.
    stop_price: float | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[RiskDecision] = []

    def record(self, decision: RiskDecision) -> None:
        self._entries.append(decision)

    def entries(self) -> list[RiskDecision]:
        return list(self._entries)

    def rejections(self) -> list[RiskDecision]:
        return [entry for entry in self._entries if not entry.approved]

    def for_symbol(self, symbol: str) -> list[RiskDecision]:
        return [entry for entry in self._entries if entry.symbol == symbol]
