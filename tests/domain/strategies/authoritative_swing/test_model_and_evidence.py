"""Immutable model and canonical evidence tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from qat.domain.strategies.authoritative_swing.evidence import (
    canonical_payload,
    stable_decision_id,
)
from qat.domain.strategies.authoritative_swing.model import (
    AdjustmentStatus,
    DataQuality,
    FinalBar,
    Ohlcv,
    RuleEvidence,
    RuleOutcome,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor


def _bar(
    *,
    symbol: str = "BHP.AX",
    session: date = date(2026, 1, 5),
    finalized: bool = True,
    close: Decimal = Decimal("10.00"),
) -> FinalBar:
    prices = Ohlcv(
        open=Decimal("9.90"),
        high=Decimal("10.10"),
        low=Decimal("9.80"),
        close=close,
        volume=1_000,
    )
    return FinalBar(
        symbol=symbol,
        session=session,
        raw=prices,
        adjusted=prices,
        source="fixture",
        quality=DataQuality.VERIFIED,
        adjustment=AdjustmentStatus.SPLIT_NORMALIZED,
        raw_to_adjusted_price_factor=SplitFactor(1, 1),
        finalized=finalized,
        digest=f"digest-{session.isoformat()}",
    )


def test_partial_bar_quality_is_preserved_for_engine_abstention() -> None:
    bar = _bar(finalized=False)
    history = SwingHistory(symbol="BHP.AX", daily=(bar,))

    assert history.daily[-1].finalized is False


def test_history_rejects_mixed_symbols() -> None:
    with pytest.raises(ValueError, match="symbol"):
        SwingHistory(symbol="BHP.AX", daily=(_bar(), _bar(symbol="CBA.AX")))


@pytest.mark.parametrize(
    "sessions",
    [
        (date(2026, 1, 5), date(2026, 1, 5)),
        (date(2026, 1, 6), date(2026, 1, 5)),
    ],
)
def test_history_rejects_duplicate_or_out_of_order_sessions(
    sessions: tuple[date, date],
) -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        SwingHistory(
            symbol="BHP.AX",
            daily=tuple(_bar(session=session) for session in sessions),
        )


def test_market_types_are_immutable() -> None:
    history = SwingHistory(symbol="BHP.AX", daily=(_bar(),))

    with pytest.raises(FrozenInstanceError):
        history.symbol = "CBA.AX"  # type: ignore[misc]


def test_semantically_identical_payloads_have_one_id() -> None:
    left = {"symbol": "BHP.AX", "rules": {"b": 2, "a": 1}}
    right = {"rules": {"a": 1, "b": 2}, "symbol": "BHP.AX"}

    assert stable_decision_id(left) == stable_decision_id(right)


def test_non_finite_evidence_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        RuleEvidence("close", RuleOutcome.PASS, measured=Decimal("NaN"))


def test_non_finite_threshold_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        RuleEvidence("close", RuleOutcome.PASS, threshold=Decimal("Infinity"))


def test_decimal_prices_have_one_canonical_identity() -> None:
    assert stable_decision_id({"price": Decimal("10.0")}) == stable_decision_id(
        {"price": Decimal("10.000")}
    )


def test_canonical_payload_supports_domain_values_without_wall_clock_state() -> None:
    evidence = RuleEvidence(
        "close",
        RuleOutcome.PASS,
        measured=Decimal("10.000"),
        threshold=Decimal("9.50"),
    )

    assert canonical_payload({"on": date(2026, 1, 5), "evidence": evidence}) == (
        b'{"evidence":{"code":"close","measured":"10","outcome":"pass",'
        b'"reason":null,"threshold":"9.5"},"on":"2026-01-05"}'
    )


def test_canonical_payload_rejects_binary_floats() -> None:
    with pytest.raises(TypeError, match="float"):
        canonical_payload({"price": 10.0})


def test_canonical_payload_rejects_non_finite_decimal_anywhere() -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_payload({"price": Decimal("-Infinity")})


def test_split_factor_reduces_and_rejects_non_integer_or_non_positive_values() -> None:
    assert SplitFactor(6, 10) == SplitFactor(3, 5)

    with pytest.raises(ValueError, match="positive"):
        SplitFactor(0, 1)
    with pytest.raises(TypeError, match="integers"):
        SplitFactor(Decimal("1"), 2)  # type: ignore[arg-type]
