"""Exact numeric types shared by authoritative swing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd


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
