"""Pure, deterministic Phase 2 swing-strategy evidence engine."""

from qat.domain.strategies.authoritative_swing.evidence import (
    canonical_payload,
    stable_decision_id,
)
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    DecisionStatus,
    FinalBar,
    Ohlcv,
    Pattern,
    PatternCandidate,
    PatternDecision,
    RuleEvidence,
    RuleOutcome,
    SetupDecision,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor

__all__ = [
    "AdjustmentStatus",
    "DataQuality",
    "DecisionStatus",
    "FinalBar",
    "Ohlcv",
    "Pattern",
    "PatternCandidate",
    "PatternDecision",
    "RuleEvidence",
    "RuleOutcome",
    "SetupDecision",
    "SplitFactor",
    "SwingHistory",
    "canonical_payload",
    "stable_decision_id",
]
