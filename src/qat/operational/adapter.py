"""Offline translation from a frozen OPERATIONAL snapshot to immutable candidates.

This module has no application wiring, network client, position-store discovery,
Phase 1 sizing, UI, OMS, execution or shadow lifecycle. The Phase 2 engine remains
unchanged and receives only immutable exact-decimal inputs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, time
from decimal import Context, Decimal, localcontext
from pathlib import Path

from qat.domain.strategies.authoritative_swing.engine import AuthoritativeSwingEngine
from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    RuleOutcome,
    SetupDecision,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import NUMERIC_POLICY
from qat.domain.strategies.authoritative_swing.sizing import ExactCostProfile, LiquidityProfile
from qat.operational.history import (
    OPERATIONAL,
    SYDNEY,
    BarRecord,
    CalendarLedger,
    HistoryStore,
    Membership,
    QualityResult,
    assess_history,
    digest,
)

LABEL = "unvalidated strategy, no demonstrated edge"


def engine_code_hash() -> str:
    """Fingerprint the unchanged strategy source and its pure QAT dependencies."""
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "domain/strategies/authoritative_swing").glob("*.py"))
    paths += [
        root / p
        for p in ("domain/backtester/costs.py", "data/broker/ticks.py", "domain/market_calendar.py")
    ]
    return digest(
        tuple(
            (
                str(p.relative_to(root)).replace("\\", "/"),
                hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in paths
        )
    )


@dataclass(frozen=True, slots=True)
class EvaluationParameters:
    equity: Decimal
    available_cash: Decimal
    costs: ExactCostProfile
    liquidity: LiquidityProfile | None
    analysis_regime: str | None = None

    def __post_init__(self) -> None:
        for value in (self.equity, self.available_cash):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("evaluation balances must be nonnegative finite Decimal")
        if self.equity == 0:
            raise ValueError("equity must be positive")
        canonical_payload(self)


@dataclass(frozen=True, slots=True)
class SymbolInput:
    symbol: str
    records: tuple[BarRecord, ...]
    quality: QualityResult


@dataclass(frozen=True, slots=True)
class FrozenSnapshot:
    session: date
    calendar: CalendarLedger
    membership: Membership
    parameters: EvaluationParameters
    symbols: tuple[SymbolInput, ...]
    source_failed: bool
    reasons: tuple[str, ...]
    engine_hash: str
    content_hash: str
    label: str = OPERATIONAL

    def identity(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "content_hash"}


@dataclass(frozen=True, slots=True)
class SourceRecord:
    symbol: str
    session: date
    source: str
    version: int
    content_hash: str
    calendar_hash: str
    label: str = OPERATIONAL


@dataclass(frozen=True, slots=True)
class CardCandidate:
    symbol: str
    session: date
    snapshot_hash: str
    engine_hash: str
    source_records: tuple[SourceRecord, ...]
    entry_limit_raw: Decimal
    structural_stop_raw: Decimal
    structural_invalidation_raw: Decimal
    expires_at: datetime
    evidence: SetupDecision
    label: str = LABEL

    def __post_init__(self) -> None:
        if self.label != LABEL:
            raise ValueError("mandatory unvalidated label cannot change")


@dataclass(frozen=True, slots=True)
class Abstention:
    symbol: str | None
    session: date
    snapshot_hash: str
    reasons: tuple[str, ...]
    label: str = OPERATIONAL


@dataclass(frozen=True, slots=True)
class AdapterResult:
    candidates: tuple[CardCandidate, ...]
    abstentions: tuple[Abstention, ...]

    def to_bytes(self) -> bytes:
        return canonical_payload(self)


class OperationalAdapter:
    def __init__(
        self, store: HistoryStore, calendar: CalendarLedger, membership: Membership
    ) -> None:
        self._store = store
        self._calendar = calendar
        self._membership = membership

    def freeze(self, session: date, parameters: EvaluationParameters) -> FrozenSnapshot:
        reasons = []
        symbols = []
        source_failed = False
        try:
            self._calendar.next_open(session)
        except ValueError:
            reasons.append("calendar_session_or_next_open_missing")
        try:
            records, encoded_events = self._store.read_view(session)
            events = [json.loads(e) for e in encoded_events]
            for event in events:
                if event.get("session") == session.isoformat():
                    if event.get("kind") == "source_failure":
                        source_failed = True
                    # Any primary-source failure blocks this entire session.
                    # An unrelated success cannot erase the recorded failure.
            for symbol in sorted(set(self._membership.symbols + self._membership.managed_symbols)):
                history = tuple(r for r in records if r.bar.symbol == symbol)
                with localcontext(
                    Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)
                ):
                    quality = assess_history(
                        symbol, session, self._calendar, self._membership, history, events
                    )
                symbols.append(SymbolInput(symbol, history, quality))
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
            reasons.append("store_integrity_failure")
            symbols = []
        snapshot = FrozenSnapshot(
            session,
            self._calendar,
            self._membership,
            parameters,
            tuple(symbols),
            source_failed,
            tuple(sorted(reasons)),
            engine_code_hash(),
            "",
        )
        return replace(snapshot, content_hash=digest(snapshot.identity()))

    def _result(
        self, candidates: tuple[CardCandidate, ...], abstentions: tuple[Abstention, ...]
    ) -> AdapterResult:
        for abstention in abstentions:
            try:
                self._store.log({"kind": "adapter_abstention", "record": abstention})
            except (ValueError, OSError, sqlite3.Error):
                # The returned immutable record is still available to the caller
                # when the store itself is inaccessible or has been relabelled.
                pass
        return AdapterResult(candidates, abstentions)

    def run(self, snapshot: FrozenSnapshot, *, now: datetime) -> AdapterResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("adapter clock must be timezone-aware")

        def global_abstention(reason: tuple[str, ...]) -> AdapterResult:
            return self._result(
                (), (Abstention(None, snapshot.session, snapshot.content_hash, reason),)
            )

        if digest(snapshot.identity()) != snapshot.content_hash:
            return global_abstention(("snapshot_hash_mismatch",))
        close_gate = datetime.combine(snapshot.session, time(17, 30), SYDNEY)
        if now < close_gate:
            return global_abstention(("before_1730_sydney",))
        if snapshot.reasons:
            return global_abstention(snapshot.reasons)
        expires = snapshot.calendar.next_open(snapshot.session)
        if now >= expires:
            return global_abstention(("session_expired",))
        if snapshot.engine_hash != engine_code_hash():
            return global_abstention(("engine_version_changed",))
        if snapshot.source_failed:
            return global_abstention(("ibkr_source_failure",))
        unfinished = tuple(
            s
            for s in snapshot.symbols
            if not s.records
            or s.records[-1].bar.session != snapshot.session
            or any(not r.bar.finalised for r in s.records)
        )
        if unfinished:
            records = (
                Abstention(
                    None, snapshot.session, snapshot.content_hash, ("required_bars_not_final",)
                ),
            ) + tuple(
                Abstention(
                    s.symbol,
                    snapshot.session,
                    snapshot.content_hash,
                    tuple(sorted({"required_bars_not_final", *s.quality.reasons})),
                )
                for s in unfinished
            )
            return self._result((), records)
        if any(r.received_at > now for s in snapshot.symbols for r in s.records):
            return global_abstention(("snapshot_from_future",))
        engine = AuthoritativeSwingEngine(tuple(s.session for s in snapshot.calendar.sessions))
        cards = []
        abstentions = []
        for symbol in snapshot.symbols:
            if not symbol.quality.eligible:
                abstentions.append(
                    Abstention(
                        symbol.symbol,
                        snapshot.session,
                        snapshot.content_hash,
                        symbol.quality.reasons,
                    )
                )
                continue
            if not symbol.quality.new_cards_allowed:
                abstentions.append(
                    Abstention(
                        symbol.symbol,
                        snapshot.session,
                        snapshot.content_hash,
                        ("departed_managed_symbol",),
                    )
                )
                continue
            history = SwingHistory(
                symbol.symbol,
                tuple(
                    FinalBar(
                        r.bar.symbol,
                        r.bar.session,
                        r.bar.raw,
                        r.bar.analytical,
                        r.bar.source,
                        DataQuality.VERIFIED,
                        AdjustmentStatus.SPLIT_NORMALIZED,
                        r.bar.factor,
                        r.bar.finalised,
                        r.content_hash,
                    )
                    for r in symbol.records
                ),
            )
            params = snapshot.parameters
            try:
                with localcontext(
                    Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)
                ):
                    decision = engine.evaluate(
                        history,
                        params.equity,
                        params.costs,
                        params.liquidity,
                        available_cash=params.available_cash,
                        analysis_regime=params.analysis_regime,
                        evaluation_session=snapshot.session,
                    )
            except Exception as error:
                abstentions.append(
                    Abstention(
                        symbol.symbol,
                        snapshot.session,
                        snapshot.content_hash,
                        ("engine_failure:" + type(error).__name__,),
                    )
                )
                continue
            if decision.status is not DecisionStatus.QUALIFIED:
                rules = decision.setup_rules + tuple(
                    rule for p in decision.pattern_decisions for rule in p.rules
                )
                reasons = tuple(
                    sorted(
                        {
                            "engine_" + decision.status.value,
                            *[
                                r.code + (":" + r.reason if r.reason else "")
                                for r in rules
                                if r.outcome is not RuleOutcome.PASS
                            ],
                        }
                    )
                )
                abstentions.append(
                    Abstention(symbol.symbol, snapshot.session, snapshot.content_hash, reasons)
                )
                continue
            if (
                decision.entry_limit_raw is None
                or decision.initial_stop_raw is None
                or decision.structural_invalidation_raw is None
                or not decision.patterns
                or decision.symbol != symbol.symbol
                or decision.session != snapshot.session
            ):
                abstentions.append(
                    Abstention(
                        symbol.symbol,
                        snapshot.session,
                        snapshot.content_hash,
                        ("invalid_engine_envelope",),
                    )
                )
                continue
            refs = tuple(
                SourceRecord(
                    r.bar.symbol,
                    r.bar.session,
                    r.bar.source,
                    r.version,
                    r.content_hash,
                    r.calendar_hash,
                )
                for r in symbol.records
            )
            cards.append(
                CardCandidate(
                    symbol.symbol,
                    snapshot.session,
                    snapshot.content_hash,
                    snapshot.engine_hash,
                    refs,
                    decision.entry_limit_raw,
                    decision.initial_stop_raw,
                    decision.structural_invalidation_raw,
                    expires,
                    decision,
                )
            )
        return self._result(tuple(cards), tuple(abstentions))
