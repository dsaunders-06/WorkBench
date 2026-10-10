"""ASX-authority consolidation accounting against the broker's reported holding."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Protocol

from qat.data.broker.adapter import Position
from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.operational.history import OPERATIONAL, CorporateAction, digest, require_operational_file


class HoldingSource(Protocol):
    async def positions(self) -> list[Position]: ...


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    symbol: str
    ex_session: date
    expected_whole_quantity: int
    broker_quantity: int | None
    fractional_quantity: Fraction
    cash_in_lieu_cents: int
    basis_sold_cents: int
    remaining_basis_cents: int
    realised_profit_cents: int
    frozen: bool
    reason: str
    evidence_reference: str

    @property
    def display_basis_per_share(self) -> Fraction | None:
        if self.broker_quantity is None or self.broker_quantity <= 0:
            return None
        return Fraction(self.remaining_basis_cents, self.broker_quantity)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY,
 symbol TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('matched','frozen','reconciled')),
 payload TEXT NOT NULL,
 previous_hash TEXT NOT NULL,
 content_hash TEXT NOT NULL,
 label TEXT NOT NULL CHECK(label='OPERATIONAL'));
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN
 SELECT RAISE(ABORT,'append only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN
 SELECT RAISE(ABORT,'append only'); END;
"""


class ConsolidationLedger:
    def __init__(self, path: Path) -> None:
        require_operational_file(path)
        self.path = path
        with sqlite3.connect(path) as conn:
            conn.executescript(_SCHEMA)
        self._verify_chain()

    def _verify_chain(self) -> None:
        require_operational_file(self.path)
        previous = ""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT * FROM events ORDER BY sequence").fetchall()
        for expected, (sequence, symbol, kind, payload, prior, content_hash, label) in enumerate(
            rows, start=1
        ):
            detail = json.loads(payload)
            identity = {
                "sequence": sequence,
                "symbol": symbol,
                "kind": kind,
                "detail": detail,
                "previous_hash": prior,
            }
            if (
                sequence != expected
                or prior != previous
                or content_hash != digest(identity)
                or label != OPERATIONAL
            ):
                raise ValueError("consolidation ledger chain invalid")
            previous = content_hash

    def append(self, symbol: str, kind: str, detail: dict[str, object]) -> None:
        if kind not in {"matched", "frozen", "reconciled"} or not symbol.endswith(".AX"):
            raise ValueError("invalid consolidation event")
        require_operational_file(self.path)
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT sequence,content_hash FROM events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = row[0] + 1 if row else 1
            previous = row[1] if row else ""
            identity = {
                "sequence": sequence,
                "symbol": symbol,
                "kind": kind,
                "detail": detail,
                "previous_hash": previous,
            }
            conn.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                (
                    sequence,
                    symbol,
                    kind,
                    canonical_payload(detail).decode("utf-8"),
                    previous,
                    digest(identity),
                    OPERATIONAL,
                ),
            )

    def is_frozen(self, symbol: str) -> bool:
        self._verify_chain()
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT kind FROM events WHERE symbol=? ORDER BY sequence DESC LIMIT 1", (symbol,)
            ).fetchone()
        return row is not None and row[0] == "frozen"

    def reconcile(self, symbol: str, operator: str, reason: str) -> None:
        if not operator or not reason or not self.is_frozen(symbol):
            raise ValueError("frozen symbol, operator and reason required")
        self.append(symbol, "reconciled", {"operator": operator, "reason": reason})


class ConsolidationReconciler:
    def __init__(self, broker: HoldingSource, ledger: ConsolidationLedger) -> None:
        self.broker = broker
        self.ledger = ledger

    async def apply(
        self,
        action: CorporateAction,
        *,
        previous_quantity: int,
        total_basis_cents: int,
        cash_in_lieu_cents: int,
    ) -> ConsolidationResult:
        if (
            type(previous_quantity) is not int
            or previous_quantity <= 0
            or type(total_basis_cents) is not int
            or total_basis_cents < 0
            or type(cash_in_lieu_cents) is not int
            or cash_in_lieu_cents < 0
            or action.split_ratio.numerator <= action.split_ratio.denominator
        ):
            raise ValueError("positive whole shares, cent basis and consolidation required")
        exact_quantity = Fraction(
            previous_quantity * action.split_ratio.denominator, action.split_ratio.numerator
        )
        whole = exact_quantity.numerator // exact_quantity.denominator
        fractional = exact_quantity - whole
        if (fractional == 0 and cash_in_lieu_cents != 0) or (
            fractional > 0 and cash_in_lieu_cents == 0
        ):
            raise ValueError("cash in lieu must match the fractional share treatment")
        positions = await self.broker.positions()
        reported = [position.quantity for position in positions if position.symbol == action.symbol]
        broker_quantity = None
        if (
            len(reported) == 1
            and math.isfinite(reported[0])
            and reported[0] >= 0
            and reported[0].is_integer()
        ):
            broker_quantity = int(reported[0])
        elif not reported:
            broker_quantity = 0
        reason = "matched ASX action authority to broker holding"
        if self.ledger.is_frozen(action.symbol):
            reason = "symbol remains frozen pending operator reconciliation"
        elif broker_quantity != whole:
            reason = f"broker holding mismatch: expected {whole}, reported {broker_quantity}"
        frozen = reason != "matched ASX action authority to broker holding"
        if frozen:
            result = ConsolidationResult(
                action.symbol,
                action.ex_session,
                whole,
                broker_quantity,
                fractional,
                cash_in_lieu_cents,
                0,
                total_basis_cents,
                0,
                True,
                reason,
                action.evidence_reference,
            )
            if not self.ledger.is_frozen(action.symbol):
                self.ledger.append(
                    action.symbol,
                    "frozen",
                    {"reason": reason, "evidence": action.evidence_reference},
                )
            return result
        # Python's exact Fraction round uses bankers' rounding, and the
        # difference stays with the held whole shares so cents are conserved.
        sold_basis = round(Fraction(total_basis_cents) * fractional / exact_quantity)
        result = ConsolidationResult(
            action.symbol,
            action.ex_session,
            whole,
            broker_quantity,
            fractional,
            cash_in_lieu_cents,
            sold_basis,
            total_basis_cents - sold_basis,
            cash_in_lieu_cents - sold_basis,
            False,
            reason,
            action.evidence_reference,
        )
        self.ledger.append(
            action.symbol,
            "matched",
            {
                "ex_session": action.ex_session,
                "expected_quantity": whole,
                "broker_quantity": broker_quantity,
                "fractional_quantity": [fractional.numerator, fractional.denominator],
                "cash_in_lieu_cents": cash_in_lieu_cents,
                "basis_sold_cents": sold_basis,
                "remaining_basis_cents": result.remaining_basis_cents,
                "realised_profit_cents": result.realised_profit_cents,
                "evidence": action.evidence_reference,
                "rounding": "half-even; residual cents to held shares",
            },
        )
        return result
