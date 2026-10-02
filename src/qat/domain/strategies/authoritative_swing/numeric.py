"""Exact numeric types shared by authoritative swing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from math import gcd
from typing import cast


@dataclass(frozen=True, slots=True)
class NumericPolicy:
    version: str
    precision: int
    rounding: str
    analytical_quantum: Decimal


NUMERIC_POLICY = NumericPolicy(
    version="phase2-decimal-v1",
    precision=50,
    rounding=ROUND_HALF_EVEN,
    analytical_quantum=Decimal("1E-12"),
)


def _context() -> Context:
    return Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)


@dataclass(frozen=True, slots=True)
class SplitFactor:
    """A positive, reduced raw-to-analytical price factor."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.numerator, bool)
            or isinstance(self.denominator, bool)
            or not isinstance(self.numerator, int)
            or not isinstance(self.denominator, int)
        ):
            raise TypeError("split-factor numerator and denominator must be integers")
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("split-factor numerator and denominator must be positive")
        divisor = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)


def parse_decimal(value: str | int | Decimal) -> Decimal:
    """Parse an exact source representation without admitting binary floats."""

    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("binary float values are forbidden by phase2-decimal-v1")
    if not isinstance(value, (str, int, Decimal)):
        raise TypeError("decimal sources must be text, integers, or Decimal values")
    parsed = value if isinstance(value, Decimal) else Decimal(value)
    if not parsed.is_finite():
        raise ValueError("decimal source values must be finite")
    return parsed


def canonical_decimal(value: Decimal) -> str:
    """Render one finite decimal identity without scientific notation."""

    if not value.is_finite():
        raise ValueError("canonical decimal values must be finite")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fraction_to_decimal(value: Fraction) -> Decimal:
    with localcontext(_context()):
        return Decimal(value.numerator) / Decimal(value.denominator)


def to_analytical_price(raw_price: Decimal, factor: SplitFactor) -> Decimal:
    """Convert raw price through an exact rational and quantize once."""

    raw = parse_decimal(raw_price)
    exact = Fraction(raw) * Fraction(factor.numerator, factor.denominator)
    with localcontext(_context()):
        return _fraction_to_decimal(exact).quantize(NUMERIC_POLICY.analytical_quantum)


def to_raw_price(analytical_price: Decimal, factor: SplitFactor) -> Decimal:
    """Reconstruct raw basis without applying an invented raw-price quantum."""

    analytical = parse_decimal(analytical_price)
    exact = Fraction(analytical) * Fraction(factor.denominator, factor.numerator)
    return _fraction_to_decimal(exact)


def normalize_reconstructed_raw(reconstructed: Decimal, source_raw: Decimal) -> Decimal:
    """Compare a reconstructed raw price at the source price's declared precision."""

    value = parse_decimal(reconstructed)
    source = parse_decimal(source_raw)
    source_quantum = Decimal(1).scaleb(cast(int, source.as_tuple().exponent))
    with localcontext(_context()):
        return value.quantize(source_quantum)
