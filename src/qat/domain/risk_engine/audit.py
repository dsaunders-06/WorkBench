"""Append-only audit log (spec §H/§L): every approve/reject/resize decision
is logged with its reason and inputs, sufficient to reconstruct any trading
session's risk decisions.

"Sufficient to reconstruct" was only true within a single process until M20:
the entries lived in a list and died with the application, so the answer to
"why was that order sized at 12 shares, and why was the next one refused"
lasted exactly as long as the session it described. It now also appends to
CSV, in the same append-on-write style the trade ledger uses, so a
post-mortem can be done the next morning without the app running.

The in-memory list is kept as the primary read path - the Risk Console and the
AI advisory context both query it on a timer, and neither should be re-parsing
a file to do it."""

from __future__ import annotations

import csv
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_FILENAME = "risk_decisions.csv"

_FIELDS = ("timestamp", "symbol", "approved", "final_shares", "stop_price", "reason", "inputs")


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
    def __init__(self, data_dir: str | Path | None = None, filename: str = AUDIT_FILENAME) -> None:
        self._entries: list[RiskDecision] = []
        # Optional so an AuditLog built without a directory - every existing
        # test, and any in-memory use - behaves exactly as it always did.
        self.path = Path(data_dir) / filename if data_dir is not None else None
        self._lock = threading.Lock()

    def record(self, decision: RiskDecision) -> None:
        self._entries.append(decision)
        self._append(decision)

    def _append(self, decision: RiskDecision) -> None:
        """A write failure is logged and swallowed.

        Losing an audit row is bad; letting a disk error propagate into the
        sizing path, where it would abort an order mid-decision, is worse. The
        decision has already been made by the time this runs.
        """
        if self.path is None:
            return
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
                    if is_new:
                        writer.writeheader()
                    writer.writerow(
                        {
                            "timestamp": decision.ts.isoformat(timespec="seconds"),
                            "symbol": decision.symbol,
                            "approved": decision.approved,
                            "final_shares": decision.final_shares,
                            "stop_price": decision.stop_price,
                            "reason": decision.reason,
                            # One JSON column rather than a column per input:
                            # the inputs dict grows as rails are added, and a
                            # widening header would break every earlier file.
                            "inputs": json.dumps(decision.inputs, default=str),
                        }
                    )
        except OSError:
            logger.warning("Could not append the risk decision for %s", decision.symbol)

    def entries(self) -> list[RiskDecision]:
        return list(self._entries)

    def rejections(self) -> list[RiskDecision]:
        return [entry for entry in self._entries if not entry.approved]

    def for_symbol(self, symbol: str) -> list[RiskDecision]:
        return [entry for entry in self._entries if entry.symbol == symbol]
