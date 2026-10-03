"""Small, independent arithmetic oracles for Phase 2 verification.

This module deliberately imports no QAT code or QAT decimal policy. It is not
part of replay and must never be used to make production decisions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction


def analytical_price(raw: Decimal, numerator: int, denominator: int) -> Decimal:
    rational = Fraction(raw) * Fraction(numerator, denominator)
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        return (Decimal(rational.numerator) / Decimal(rational.denominator)).quantize(
            Decimal("0.000000000001")
        )


def raw_price(analytical: Decimal, numerator: int, denominator: int) -> Decimal:
    rational = Fraction(analytical) * Fraction(denominator, numerator)
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        return Decimal(rational.numerator) / Decimal(rational.denominator)


def prior_asx_tick(price: Decimal) -> Decimal:
    candidates = []
    for floor, ceiling, step in (
        (Decimal(0), Decimal("0.10"), Decimal("0.001")),
        (Decimal("0.10"), Decimal("2"), Decimal("0.005")),
        (Decimal("2"), None, Decimal("0.01")),
    ):
        count = int(price // step)
        if step * count >= price:
            count -= 1
        candidate = step * count
        if candidate > 0 and candidate >= floor and (ceiling is None or candidate < ceiling):
            candidates.append(candidate)
    return max(candidates)


def ema(values: Sequence[Decimal], period: int) -> tuple[Decimal | None, ...]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return tuple(result)
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        current = sum(values[:period], Decimal(0)) / period
        result[period - 1] = current
        for index in range(period, len(values)):
            current += (values[index] - current) * Decimal(2) / (period + 1)
            result[index] = current
    return tuple(result)


def atr(
    ohlc: Sequence[tuple[Decimal, Decimal, Decimal]], period: int
) -> tuple[Decimal | None, ...]:
    ranges = []
    for index, (high, low, _close) in enumerate(ohlc):
        previous = ohlc[index - 1][2] if index else None
        ranges.append(
            max((high - low, abs(high - previous), abs(low - previous)))
            if previous is not None
            else high - low
        )
    result: list[Decimal | None] = [None] * len(ranges)
    if len(ranges) < period:
        return tuple(result)
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        current = sum(ranges[:period], Decimal(0)) / period
        result[period - 1] = current
        for index in range(period, len(ranges)):
            current = (current * (period - 1) + ranges[index]) / period
            result[index] = current
    return tuple(result)


def resistance_zones(highs: Sequence[Decimal]) -> tuple[tuple[Decimal, Decimal], ...]:
    peaks = [
        (value, index)
        for index, value in enumerate(highs)
        if 5 <= index < len(highs) - 5
        and all(value > highs[other] for other in range(index - 5, index + 6) if other != index)
    ]
    peaks.sort()
    groups: list[frozenset[int]] = []
    for start in range(len(peaks)):
        for end in range(start + 2, len(peaks) + 1):
            group = peaks[start:end]
            prices = [price for price, _ in group]
            median = (
                prices[len(prices) // 2]
                if len(prices) % 2
                else (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2
            )
            if max(index for _, index in group) - min(index for _, index in group) < 20:
                continue
            if all(abs(price - median) / median <= Decimal("0.01") for price in prices):
                groups.append(frozenset(index for _, index in group))
    maximal = [group for group in groups if not any(group < other for other in groups)]
    return tuple(
        sorted(
            (min(highs[index] for index in group), max(highs[index] for index in group))
            for group in set(maximal)
        )
    )


def risk_quantity(
    equity: Decimal,
    limit: Decimal,
    stop: Decimal,
    commission_bps: Decimal,
    minimum: Decimal,
    entry_impact_bps: Decimal,
    exit_impact_bps: Decimal,
) -> int:
    budget = equity / 100

    def total(quantity: int) -> Decimal:
        if not quantity:
            return Decimal(0)
        entry = quantity * limit
        exit_value = quantity * stop
        return (
            quantity * (limit - stop)
            + max(minimum, entry * commission_bps / 10_000)
            + max(minimum, exit_value * commission_bps / 10_000)
            + entry * entry_impact_bps / 10_000
            + exit_value * exit_impact_bps / 10_000
        )

    quantity = 0
    while total(quantity + 1) <= budget:
        quantity += 1
    return quantity


def wcr_s_pvalue(
    months: Sequence[Sequence[Decimal]], weights: Sequence[Sequence[int]], null: float = 0.0
) -> tuple[float, Decimal]:
    totals = [sum(map(float, month)) for month in months]
    sizes = [len(month) for month in months]
    count = sum(sizes)
    clusters = sum(bool(size) for size in sizes)
    mean = sum(totals) / count
    centered = [total - size * mean for total, size in zip(totals, sizes, strict=True)]
    se = math.sqrt(clusters / (clusters - 1) * sum(score * score for score in centered)) / count
    observed = (mean - null) / se
    boot = []
    for row in weights:
        scores = [
            (total - size * null) * weight
            for total, size, weight in zip(totals, sizes, row, strict=True)
        ]
        numerator = sum(scores)
        residuals = [
            score - numerator * size / count for score, size in zip(scores, sizes, strict=True)
        ]
        denominator = math.sqrt(clusters / (clusters - 1) * sum(item * item for item in residuals))
        boot.append(numerator / denominator)
    return observed, Decimal(1 + sum(value >= observed for value in boot)) / Decimal(len(boot) + 1)


def romano_wolf(
    samples: dict[str, Sequence[Sequence[Decimal]]], weights: Sequence[Sequence[int]]
) -> tuple[tuple[str, ...], dict[str, Decimal]]:
    observed = {name: wcr_s_pvalue(months, weights)[0] for name, months in samples.items()}
    order = tuple(sorted(samples, key=lambda name: (-observed[name], name)))
    bootstrap = {}
    for name, months in samples.items():
        totals = [sum(map(float, month)) for month in months]
        sizes = [len(month) for month in months]
        count = sum(sizes)
        clusters = sum(bool(size) for size in sizes)
        values = []
        for row in weights:
            scores = [total * weight for total, weight in zip(totals, row, strict=True)]
            numerator = sum(scores)
            residuals = [
                score - numerator * size / count for score, size in zip(scores, sizes, strict=True)
            ]
            values.append(
                numerator
                / math.sqrt(clusters / (clusters - 1) * sum(item * item for item in residuals))
            )
        bootstrap[name] = values
    adjusted = {}
    previous = Decimal(0)
    for index, name in enumerate(order):
        exceeded = sum(
            max(bootstrap[other][draw] for other in order[index:]) >= observed[name]
            for draw in range(len(weights))
        )
        previous = max(previous, Decimal(1 + exceeded) / Decimal(len(weights) + 1))
        adjusted[name] = previous
    return order, adjusted


def binomial_upper(events: int, windows: int) -> Decimal:
    if events == windows:
        return Decimal(1)

    def tail(probability: float) -> float:
        return sum(
            math.comb(windows, count) * probability**count * (1 - probability) ** (windows - count)
            for count in range(events + 1)
        )

    left, right = 0.0, 1.0
    for _ in range(80):
        middle = (left + right) / 2
        if tail(middle) > 0.05:
            left = middle
        else:
            right = middle
    return Decimal(str(right))


def constant_month_duration(monthly_count: int, n_required: int, g_required: int) -> int:
    """Exact duration for a constant, nonzero incidence path."""
    if monthly_count <= 0:
        raise ValueError("positive monthly count required")
    return max(36, math.ceil(n_required / monthly_count), g_required)
