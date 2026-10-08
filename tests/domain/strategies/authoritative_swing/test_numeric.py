"""Frozen decimal policy and price-basis conversion tests."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

import pytest

from qat.domain.strategies.authoritative_swing.numeric import (
    NUMERIC_POLICY,
    SplitFactor,
    canonical_decimal,
    normalize_reconstructed_raw,
    parse_decimal,
    to_analytical_price,
    to_raw_price,
)


def D(value: str) -> Decimal:
    return Decimal(value)


def test_split_factor_is_reduced_and_conversion_uses_declared_quantum() -> None:
    factor = SplitFactor(3, 10)

    adjusted = to_analytical_price(D("1"), factor)

    assert adjusted == D("0.300000000000")
    assert normalize_reconstructed_raw(to_raw_price(adjusted, factor), D("1")) == D("1")


def test_numeric_policy_is_frozen() -> None:
    assert NUMERIC_POLICY.version == "phase2-decimal-v1"
    assert NUMERIC_POLICY.precision == 50
    assert NUMERIC_POLICY.rounding == ROUND_HALF_EVEN
    assert NUMERIC_POLICY.analytical_quantum == D("1E-12")


@pytest.mark.parametrize(
    ("source", "expected"),
    [("10.000", "10.000"), (7, "7")],
)
def test_parse_decimal_accepts_only_exact_source_forms(source: str | int, expected: str) -> None:
    assert parse_decimal(source) == D(expected)


def test_parse_decimal_refuses_binary_float_and_non_finite_text() -> None:
    with pytest.raises(TypeError, match="float"):
        parse_decimal(0.1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        parse_decimal("NaN")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("10.000", "10"), ("0.000", "0"), ("-0", "0"), ("1E+3", "1000")],
)
def test_canonical_decimal_is_non_scientific_and_normalized(value: str, expected: str) -> None:
    assert canonical_decimal(D(value)) == expected


def test_recurring_factor_round_trip_uses_the_declared_source_quantum() -> None:
    factor = SplitFactor(7, 13)
    raw = D("12.345")

    analytical = to_analytical_price(raw, factor)
    reconstructed = to_raw_price(analytical, factor)

    assert analytical.as_tuple().exponent == -12
    assert normalize_reconstructed_raw(reconstructed, raw) == raw
