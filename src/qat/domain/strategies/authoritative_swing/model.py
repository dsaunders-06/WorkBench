"""Immutable inputs and evidence emitted by the authoritative swing engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from qat.domain.strategies.authoritative_swing.numeric import SplitFactor


class DataQuality(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    SYNTHETIC = "synthetic"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"


class AdjustmentStatus(StrEnum):
    SPLIT_NORMALIZED = "split_normalized"
    VENDOR_ADJUSTED = "vendor_adjusted"
    UNADJUSTED = "unadjusted"
    UNKNOWN = "unknown"


class DecisionStatus(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    ABSTAIN = "abstain"


class Pattern(StrEnum):
    EMA_PULLBACK = "ema_pullback"
    BULL_FLAG = "bull_flag"
    DOUBLE_BOTTOM = "double_bottom"


class RuleOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class Ohlcv:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class FinalBar:
    symbol: str
    session: date
    raw: Ohlcv
    adjusted: Ohlcv
    source: str
    quality: DataQuality
    adjustment: AdjustmentStatus
    raw_to_adjusted_price_factor: SplitFactor
    finalized: bool
    digest: str


@dataclass(frozen=True, slots=True)
class SwingHistory:
    symbol: str
    daily: tuple[FinalBar, ...]

    def __post_init__(self) -> None:
        if any(bar.symbol != self.symbol for bar in self.daily):
            raise ValueError("every history bar must match the history symbol")
        sessions = tuple(bar.session for bar in self.daily)
        if any(
            current >= following
            for current, following in zip(sessions, sessions[1:], strict=False)
        ):
            raise ValueError("history sessions must be unique and strictly increasing")


@dataclass(frozen=True, slots=True)
class RuleEvidence:
    code: str
    outcome: RuleOutcome
    measured: Decimal | int | str | bool | None = None
    threshold: Decimal | int | str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        for value in (self.measured, self.threshold):
            if isinstance(value, Decimal) and not value.is_finite():
                raise ValueError("evidence decimal values must be finite")


MetadataValue = str | int | Decimal | bool


@dataclass(frozen=True, slots=True)
class PatternCandidate:
    pattern: Pattern
    pattern_instance_id: str
    breakout_event_id: str | None
    signal_session: date
    analytical_signal_close: Decimal
    analytical_invalidation: Decimal
    analytical_atr14: Decimal
    metadata: tuple[tuple[str, MetadataValue], ...] = ()


@dataclass(frozen=True, slots=True)
class PatternDecision:
    pattern: Pattern
    status: DecisionStatus
    rules: tuple[RuleEvidence, ...]
    candidate: PatternCandidate | None = None


@dataclass(frozen=True, slots=True)
class SetupDecision:
    strategy_version: str
    schema_version: str
    decision_id: str
    symbol: str
    session: date
    status: DecisionStatus
    patterns: tuple[Pattern, ...]
    pattern_decisions: tuple[PatternDecision, ...]
    entry_limit_raw: Decimal | None
    initial_stop_raw: Decimal | None
    risk_quantity: int
    capacity_quantity: int
    quantity: int
    input_digests: tuple[str, ...]
    analysis_regime: str | None = None
