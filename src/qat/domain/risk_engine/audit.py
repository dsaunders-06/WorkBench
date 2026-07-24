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
