"""Signal-level swing metrics and frozen cluster inference.

Decimal trade observations cross into versioned binary64 arrays only inside
the inferential routines. They never feed decisions, orders, or identifiers.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

import numpy as np

from qat.domain.backtester.swing_results import ReplayEquityPoint, SwingTrade

STATISTICS_NUMERIC_POLICY = "numpy-binary64-pcg64-wcr-s-cv1-v2"


@dataclass(frozen=True, slots=True)
class WCRSResult:
    observed_t: float
    bootstrap_count: int
    nonempty_clusters: int
    p_value: Decimal
    lower_bound: Decimal
    numeric_policy: str = STATISTICS_NUMERIC_POLICY


@dataclass(frozen=True, slots=True)
class RomanoWolfResult:
    order: tuple[str, ...]
    adjusted_p_values: Mapping[str, Decimal]
    observed_statistics: Mapping[str, float]
    bootstrap_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "adjusted_p_values", MappingProxyType(dict(self.adjusted_p_values))
        )
        object.__setattr__(
            self, "observed_statistics", MappingProxyType(dict(self.observed_statistics))
        )


@dataclass(frozen=True, slots=True)
class SwingStatistics:
    eligible_trades: int
    overlap_suppressed_trades: int
    mean_r_order: Decimal | None
    mean_r_fill: Decimal | None
    profit_factor: Decimal | None
    total_costs: Decimal
    maximum_drawdown: Decimal
    maximum_exposure: Decimal
    average_exposure: Decimal
    turnover: Decimal
    cost_to_risk: Decimal | None
    signal_es1: Decimal | None
    signal_es5: Decimal | None
    symbol_groups: Mapping[str, Decimal]
    year_groups: Mapping[int, Decimal]
    regime_groups: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        for name in ("symbol_groups", "year_groups", "regime_groups"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else None


def _expected_shortfall(values: Sequence[Decimal], fraction: Decimal) -> Decimal | None:
    if not values:
        return None
    count = max(1, math.ceil(Decimal(len(values)) * fraction))
    return sum(sorted(values)[:count], Decimal(0)) / Decimal(count)


def summarize_swing_statistics(
    *,
    signal_trades: Sequence[SwingTrade],
    equity: Sequence[ReplayEquityPoint],
    signal_reference_equity: Decimal,
) -> SwingStatistics:
    """Keep signal edge separate from the cash-funded portfolio equity path."""
    if not signal_reference_equity.is_finite() or signal_reference_equity <= 0:
        raise ValueError("fixed signal reference equity must be positive and finite")
    eligible = tuple(trade for trade in signal_trades if trade.edge_sample_eligible)
    suppressed = len(signal_trades) - len(eligible)
    order_r = tuple(trade.order_r_multiple for trade in eligible)
    fill_r = tuple(trade.fill_r_multiple for trade in eligible)
    gains = sum((trade.net_pnl for trade in eligible if trade.net_pnl > 0), Decimal(0))
    losses = -sum((trade.net_pnl for trade in eligible if trade.net_pnl < 0), Decimal(0))
    symbol_groups: dict[str, list[Decimal]] = defaultdict(list)
    year_groups: dict[int, list[Decimal]] = defaultdict(list)
    regime_groups: dict[str, list[Decimal]] = defaultdict(list)
    for trade in eligible:
        symbol_groups[trade.symbol].append(trade.order_r_multiple)
        year_groups[trade.entry_session.year].append(trade.order_r_multiple)
        regime_groups[trade.analysis_regime or "unknown"].append(trade.order_r_multiple)

    peak: Decimal | None = None
    maximum_drawdown = Decimal(0)
    exposures: list[Decimal] = []
    for point in equity:
        if not point.equity.is_finite() or point.equity <= 0:
            raise ValueError("cash-funded equity must remain finite and positive")
        peak = point.equity if peak is None else max(peak, point.equity)
        maximum_drawdown = max(maximum_drawdown, (peak - point.equity) / peak)
        exposures.append(point.position_value / point.equity)
    total_risk = sum((trade.order_initial_risk_dollars for trade in eligible), Decimal(0))
    total_costs = sum((trade.costs for trade in eligible), Decimal(0))
    entry_notional = sum(
        (trade.entry_price * Decimal(trade.quantity) for trade in eligible), Decimal(0)
    )
    return SwingStatistics(
        eligible_trades=len(eligible),
        overlap_suppressed_trades=suppressed,
        mean_r_order=_mean(order_r),
        mean_r_fill=_mean(fill_r),
        profit_factor=gains / losses if losses else None,
        total_costs=total_costs,
        maximum_drawdown=maximum_drawdown,
        maximum_exposure=max(exposures, default=Decimal(0)),
        average_exposure=_mean(exposures) or Decimal(0),
        turnover=entry_notional / signal_reference_equity,
        cost_to_risk=total_costs / total_risk if total_risk else None,
        signal_es1=_expected_shortfall(order_r, Decimal("0.01")),
        signal_es5=_expected_shortfall(order_r, Decimal("0.05")),
        symbol_groups={name: _mean(values) or Decimal(0) for name, values in symbol_groups.items()},
        year_groups={year: _mean(values) or Decimal(0) for year, values in year_groups.items()},
        regime_groups={name: _mean(values) or Decimal(0) for name, values in regime_groups.items()},
    )


@dataclass(frozen=True, slots=True)
class _ClusterFrame:
    sums: np.ndarray
    counts: np.ndarray
    total_count: int
    nonempty_clusters: int
    mean: float
    standard_error: float


def _cluster_frame(months: Sequence[Sequence[Decimal]]) -> _ClusterFrame:
    if not months or not any(months):
        raise ValueError("WCR-S requires at least one trade")
    counts = np.asarray([len(month) for month in months], dtype=np.float64)
    sums = np.asarray([sum((float(value) for value in month), 0.0) for month in months])
    total_count = int(counts.sum())
    nonempty = int(np.count_nonzero(counts))
    if nonempty < 2 or total_count <= 1:
        raise ValueError("WCR-S variance needs at least two nonempty clusters")
    mean = float(sums.sum() / total_count)
    # WCR-S uses CV1 for the observed statistic. The restricted score
    # transformation changes only the bootstrap DGP (MacKinnon et al., 2023,
    # Table 1); with one coefficient fixed by the null it reduces to raw scores.
    scores = sums - counts * mean
    variance = nonempty / (nonempty - 1) * float(np.sum(scores**2)) / total_count**2
    if not math.isfinite(variance) or variance <= 0:
        raise ValueError("WCR-S variance is undefined or collapsed")
    return _ClusterFrame(sums, counts, total_count, nonempty, mean, math.sqrt(variance))


def _weight_matrix(
    month_count: int,
    weights: Sequence[Sequence[int]] | None,
    *,
    draws: int,
    seed: int,
) -> np.ndarray:
    if weights is None:
        if draws <= 0:
            raise ValueError("bootstrap draws must be positive")
        return np.random.Generator(np.random.PCG64(seed)).choice(
            np.asarray([-1, 1], dtype=np.int8), size=(draws, month_count)
        )
    matrix = np.asarray(weights, dtype=np.int8)
    if matrix.ndim != 2 or matrix.shape[1] != month_count or matrix.shape[0] == 0:
        raise ValueError("common weights must cover every entry month")
    if not np.all((matrix == -1) | (matrix == 1)):
        raise ValueError("WCR-S supports only Rademacher month weights")
    return matrix


def _bootstrap_statistics(
    frame: _ClusterFrame, weights: np.ndarray, null_mean: float
) -> np.ndarray:
    leverage = frame.counts / frame.total_count
    # Equation (37) of MacKinnon et al. (2023): there are no unrestricted
    # nuisance regressors in this intercept-only model, so the restricted
    # transformed score is sum(y_g - null_mean) without a leverage divisor.
    restricted = frame.sums - frame.counts * null_mean
    weighted = weights * restricted
    numerators = np.sum(weighted, axis=1)
    centered = weighted - numerators[:, None] * leverage
    denominators = np.sqrt(
        frame.nonempty_clusters / (frame.nonempty_clusters - 1) * np.sum(centered**2, axis=1)
    )
    if np.any(denominators <= 0) or not np.all(np.isfinite(denominators)):
        raise ValueError("WCR-S bootstrap variance collapsed")
    return np.asarray(numerators / denominators, dtype=np.float64)


def _one_sided_p(frame: _ClusterFrame, weights: np.ndarray, null_mean: float) -> Decimal:
    observed = (frame.mean - null_mean) / frame.standard_error
    bootstrap = _bootstrap_statistics(frame, weights, null_mean)
    return Decimal(1 + int(np.count_nonzero(bootstrap >= observed))) / Decimal(len(bootstrap) + 1)


def _lower_bound(frame: _ClusterFrame, weights: np.ndarray) -> Decimal:
    if len(weights) < 39:
        raise ValueError("WCR-S needs at least 39 draws for 2.5% bound inversion")
    target = Decimal("0.025")
    high = frame.mean
    low = high - 2 * frame.standard_error
    for _ in range(24):
        if _one_sided_p(frame, weights, low) <= target:
            break
        low -= 2 * frame.standard_error
    else:
        raise ValueError("WCR-S lower-bound inversion could not be bracketed")
    for _ in range(42):
        midpoint = (low + high) / 2
        if _one_sided_p(frame, weights, midpoint) <= target:
            low = midpoint
        else:
            high = midpoint
    return Decimal(str(low))


def wcr_s_mean_test(
    months: Sequence[Sequence[Decimal]],
    *,
    null_mean: Decimal = Decimal(0),
    weights: Sequence[Sequence[int]] | None = None,
    draws: int = 9_999,
    seed: int = 0,
) -> WCRSResult:
    """Restricted wild-cluster score test and inverted one-sided lower bound."""
    frame = _cluster_frame(months)
    matrix = _weight_matrix(len(months), weights, draws=draws, seed=seed)
    if not null_mean.is_finite():
        raise ValueError("null mean must be finite")
    return WCRSResult(
        observed_t=(frame.mean - float(null_mean)) / frame.standard_error,
        bootstrap_count=len(matrix),
        nonempty_clusters=frame.nonempty_clusters,
        p_value=_one_sided_p(frame, matrix, float(null_mean)),
        lower_bound=_lower_bound(frame, matrix),
    )


def wcr_s_pvalue(
    months: Sequence[Sequence[Decimal]],
    *,
    null_mean: Decimal = Decimal(0),
    weights: Sequence[Sequence[int]] | None = None,
    draws: int = 9_999,
    seed: int = 0,
) -> Decimal:
    """Run the same restricted test without repeated lower-bound inversion."""
    if not null_mean.is_finite():
        raise ValueError("null mean must be finite")
    frame = _cluster_frame(months)
    matrix = _weight_matrix(len(months), weights, draws=draws, seed=seed)
    return _one_sided_p(frame, matrix, float(null_mean))


def romano_wolf_stepdown(
    samples: Mapping[str, Sequence[Sequence[Decimal]]],
    *,
    weights: Sequence[Sequence[int]] | None = None,
    draws: int = 9_999,
    seed: int = 0,
) -> RomanoWolfResult:
    """One-sided max-statistic stepdown with one common month-weight matrix."""
    if not samples:
        raise ValueError("Romano-Wolf requires pattern samples")
    month_counts = {len(months) for months in samples.values()}
    if len(month_counts) != 1:
        raise ValueError("patterns must share a complete entry-month frame")
    matrix = _weight_matrix(month_counts.pop(), weights, draws=draws, seed=seed)
    frames = {name: _cluster_frame(months) for name, months in samples.items()}
    observed = {name: frame.mean / frame.standard_error for name, frame in frames.items()}
    bootstrap = {name: _bootstrap_statistics(frame, matrix, 0.0) for name, frame in frames.items()}
    order = tuple(sorted(observed, key=lambda name: (-observed[name], name)))
    adjusted: dict[str, Decimal] = {}
    previous = Decimal(0)
    for index, name in enumerate(order):
        maximum = np.maximum.reduce([bootstrap[other] for other in order[index:]])
        raw = Decimal(1 + int(np.count_nonzero(maximum >= observed[name]))) / Decimal(
            len(matrix) + 1
        )
        previous = max(previous, raw)
        adjusted[name] = previous
    return RomanoWolfResult(order, adjusted, observed, len(matrix))
