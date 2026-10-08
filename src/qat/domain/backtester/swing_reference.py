"""Field-limited, support-matched reference incidence calibration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

import numpy as np

from qat.domain.backtester.swing_dataset import DatasetIntegrityError


class PromotionStatus(StrEnum):
    PORTFOLIO_RISK_DESIGN_PENDING = "PORTFOLIO_RISK_DESIGN_PENDING"
    INCIDENCE_DATA_INSUFFICIENT = "INCIDENCE_DATA_INSUFFICIENT"
    PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE = "PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    METHOD_INADEQUATE = "METHOD_INADEQUATE"
    TERMINAL_OUTCOME_SENSITIVE = "TERMINAL_OUTCOME_SENSITIVE"
    EDGE_PASS_PORTFOLIO_RISK_BLOCKED = (
        "EDGE_PASS_PORTFOLIO_RISK_BLOCKED"  # nosec B105 # Enum outcome label, not a credential.
    )
    INVALID = "INVALID"
    FAIL = "FAIL"
    PASS = "PASS"  # nosec B105 # Enum outcome label, not a credential.


@dataclass(frozen=True, slots=True)
class ReferenceObservation:
    issuer_id: str
    session: date
    market_cap: Decimal
    price: Decimal
    traded_value: Decimal
    ordinary_equity: bool
    member_at_start: bool


@dataclass(frozen=True, slots=True)
class ReferenceEvent:
    event_id: str
    issuer_id: str
    onset_session: date
    category: str
    irrevocable_consideration: bool = False
    unresolved_at_t64: bool = False


@dataclass(frozen=True, slots=True)
class StrategyExposure:
    market_cap: Decimal
    price: Decimal
    traded_value: Decimal
    entry_count: int


@dataclass(frozen=True, slots=True)
class ReferenceView:
    official_sessions: tuple[date, ...]
    holdout_start: date
    observations: tuple[ReferenceObservation, ...]
    events: tuple[ReferenceEvent, ...]
    strategy_exposures: tuple[StrategyExposure, ...]


@dataclass(frozen=True, slots=True)
class IncidenceWindow:
    issuer_id: str
    start: date
    issuer_year: tuple[str, int]
    initial_bucket: str
    event_within_ten_sessions: bool
    member_at_start: bool


@dataclass(frozen=True, slots=True)
class BucketIncidence:
    bucket: str
    window_count: int
    event_count: int
    unique_issuer_years: int
    unique_issuers: int
    clustered_upper: Decimal
    landmark_exact_upper: Decimal
    primary_upper: Decimal
    strategy_weight: Decimal


@dataclass(frozen=True, slots=True)
class MicrocapSensitivity:
    window_count: int
    event_count: int
    unique_issuer_years: int
    unique_issuers: int
    clustered_upper: Decimal | None
    landmark_exact_upper: Decimal | None
    upper_bound: Decimal | None
    primary_weight: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class IncidenceCalibration:
    status: PromotionStatus
    eligible_window_count: int
    excluded_outside_support: int
    merge_path: Mapping[str, str]
    buckets: tuple[BucketIncidence, ...]
    clustered_upper: Decimal | None
    landmark_exact_upper: Decimal | None
    primary_bound: Decimal | None
    stressed_bound: Decimal | None
    worst_bucket_bound: Decimal | None
    recommended_holdout_months: int | None = None
    support_bounds: Mapping[str, tuple[Decimal, Decimal]] = field(default_factory=dict)
    available_bucket_support: Mapping[str, tuple[int, int, int]] = field(default_factory=dict)
    microcap_sensitivity: MicrocapSensitivity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "merge_path", MappingProxyType(dict(self.merge_path)))
        object.__setattr__(self, "support_bounds", MappingProxyType(dict(self.support_bounds)))
        object.__setattr__(
            self, "available_bucket_support", MappingProxyType(dict(self.available_bucket_support))
        )


BUCKETS = ("small_low", "small_high", "large_low", "large_high")
QUALIFYING = {
    "administration",
    "receivership",
    "liquidation",
    "ordinary_equity_cancellation",
}


def _weighted_median(pairs: Sequence[tuple[Decimal, int]]) -> Decimal:
    ordered = sorted(pairs, key=lambda pair: pair[0])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        raise DatasetIntegrityError("strategy exposure weights must be positive")
    running = 0
    for value, weight in ordered:
        running += weight
        if running * 2 >= total:
            return value
    raise AssertionError("positive weights always have a median")


def _support(
    view: ReferenceView,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    exposures = view.strategy_exposures
    if not exposures or any(
        item.entry_count <= 0
        or any(
            not value.is_finite() or value <= 0
            for value in (item.market_cap, item.price, item.traded_value)
        )
        for item in exposures
    ):
        raise DatasetIntegrityError("field-limited strategy support is absent or invalid")
    return (
        min(item.market_cap for item in exposures),
        max(item.market_cap for item in exposures),
        min(item.price for item in exposures),
        max(item.price for item in exposures),
        min(item.traded_value for item in exposures),
        max(item.traded_value for item in exposures),
        _weighted_median(tuple((item.market_cap, item.entry_count) for item in exposures)),
        _weighted_median(tuple((item.traded_value, item.entry_count) for item in exposures)),
    )


def _bucket(
    market_cap: Decimal, traded_value: Decimal, median_cap: Decimal, median_liquidity: Decimal
) -> str:
    size = "small" if market_cap <= median_cap else "large"
    liquidity = "low" if traded_value <= median_liquidity else "high"
    return f"{size}_{liquidity}"


def _qualifies(event: ReferenceEvent) -> bool:
    if event.category == "vendor_omission":
        raise DatasetIntegrityError("vendor omission is an integrity failure")
    if event.category in QUALIFYING:
        return True
    if event.category == "delisting":
        return not event.irrevocable_consideration
    if event.category == "suspension":
        return event.unresolved_at_t64
    if event.category in {"short_halt", "symbol_change", "known_consideration"}:
        return False
    raise DatasetIntegrityError(f"unknown reference event category: {event.category}")


def build_incidence_windows(view: ReferenceView) -> tuple[IncidenceWindow, ...]:
    """Freeze each support-matched ten-session start before later deterioration."""
    sessions = view.official_sessions
    if not sessions or tuple(sorted(set(sessions))) != sessions:
        raise DatasetIntegrityError("reference official sessions must be ordered and unique")
    support = _support(view)
    session_index = {session: index for index, session in enumerate(sessions)}
    events: dict[str, list[ReferenceEvent]] = defaultdict(list)
    for event in view.events:
        _qualifies(event)
        if event.onset_session not in session_index:
            raise DatasetIntegrityError("reference event onset lacks an official session")
        events[event.issuer_id].append(event)
    windows: list[IncidenceWindow] = []
    for observation in view.observations:
        values = (observation.market_cap, observation.price, observation.traded_value)
        if not observation.issuer_id or any(
            not value.is_finite() or value <= 0 for value in values
        ):
            raise DatasetIntegrityError("reference start has invalid field-limited support")
        ordinal = session_index.get(observation.session)
        if ordinal is None:
            raise DatasetIntegrityError("reference start lacks an official session")
        if not observation.ordinary_equity or ordinal + 10 >= len(sessions):
            continue
        if sessions[ordinal + 10] >= view.holdout_start:
            continue
        if not (
            support[0] <= observation.market_cap <= support[1]
            and support[2] <= observation.price <= support[3]
            and support[4] <= observation.traded_value <= support[5]
        ):
            continue
        qualifying = any(
            ordinal < session_index[event.onset_session] <= ordinal + 10 and _qualifies(event)
            for event in events[observation.issuer_id]
        )
        windows.append(
            IncidenceWindow(
                observation.issuer_id,
                observation.session,
                (observation.issuer_id, observation.session.year),
                _bucket(observation.market_cap, observation.traded_value, support[6], support[7]),
                qualifying,
                observation.member_at_start,
            )
        )
    return tuple(sorted(windows, key=lambda window: (window.start, window.issuer_id)))


def _support_count(windows: Sequence[IncidenceWindow]) -> tuple[int, int]:
    return len({window.issuer_year for window in windows}), len(
        {window.issuer_id for window in windows}
    )


def merge_buckets(
    windows: Sequence[IncidenceWindow], *, min_issuer_years: int = 500, min_issuers: int = 100
) -> Mapping[str, str]:
    """Merge by exposure support only; event labels cannot affect the path."""
    if min_issuer_years <= 0 or min_issuers <= 0:
        raise ValueError("support minima must be positive")
    mapping = {bucket: bucket for bucket in BUCKETS}
    for size in ("small", "large"):
        lower, higher = f"{size}_low", f"{size}_high"
        for bucket in (lower, higher):
            members = [window for window in windows if window.initial_bucket == bucket]
            years, issuers = _support_count(members)
            if years < min_issuer_years or issuers < min_issuers:
                mapping[lower] = f"{size}_all"
                mapping[higher] = f"{size}_all"
                break
    for effective in set(mapping.values()):
        members = [window for window in windows if mapping[window.initial_bucket] == effective]
        years, issuers = _support_count(members)
        if years < min_issuer_years or issuers < min_issuers:
            return MappingProxyType({bucket: "all" for bucket in BUCKETS})
    return MappingProxyType(mapping)


def _exact_binomial_upper(events: int, windows: int) -> Decimal:
    if windows <= 0 or not 0 <= events <= windows:
        raise ValueError("exact landmark count is invalid")
    if events == windows:
        return Decimal(1)
    if events == 0:
        return Decimal(str(1 - 0.05 ** (1 / windows)))

    def cumulative(probability: float) -> float:
        term = (1 - probability) ** windows
        total = term
        for count in range(1, events + 1):
            term *= (windows - count + 1) / count * probability / (1 - probability)
            total += term
        return total

    low, high = 0.0, 1.0 - 1e-12
    for _ in range(80):
        middle = (low + high) / 2
        if cumulative(middle) > 0.05:
            low = middle
        else:
            high = middle
    return Decimal(str(high))


def _clustered_upper(windows: Sequence[IncidenceWindow], *, draws: int, seed: int) -> Decimal:
    groups: dict[tuple[str, int], list[IncidenceWindow]] = defaultdict(list)
    for window in windows:
        groups[window.issuer_year].append(window)
    totals = np.asarray(
        [
            (sum(window.event_within_ten_sessions for window in group), len(group))
            for group in groups.values()
        ],
        dtype=np.int64,
    )
    if len(totals) == 0:
        raise ValueError("clustered incidence needs exposure windows")
    rng = np.random.Generator(np.random.PCG64(seed))
    rates = []
    for _ in range(draws):
        selected = totals[rng.integers(0, len(totals), size=len(totals))]
        rates.append(float(np.sum(selected[:, 0]) / np.sum(selected[:, 1])))
    return Decimal(str(float(np.quantile(rates, 0.95, method="higher"))))


def _landmark_upper(
    windows: Sequence[IncidenceWindow], session_index: Mapping[date, int]
) -> Decimal:
    by_issuer: dict[str, list[IncidenceWindow]] = defaultdict(list)
    for window in windows:
        by_issuer[window.issuer_id].append(window)
    landmarks: list[IncidenceWindow] = []
    for group in by_issuer.values():
        last_start = -11
        for window in sorted(group, key=lambda item: item.start):
            ordinal = session_index[window.start]
            if ordinal >= last_start + 10:
                landmarks.append(window)
                last_start = ordinal
    return _exact_binomial_upper(
        sum(window.event_within_ten_sessions for window in landmarks), len(landmarks)
    )


def _outside_support_windows(
    view: ReferenceView,
    support: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal],
) -> tuple[int, tuple[IncidenceWindow, ...]]:
    """Keep low-cap starts separate from the support-matched primary sample."""
    index = {session: ordinal for ordinal, session in enumerate(view.official_sessions)}
    events: dict[str, list[ReferenceEvent]] = defaultdict(list)
    for event in view.events:
        events[event.issuer_id].append(event)
    excluded = 0
    microcaps: list[IncidenceWindow] = []
    for observation in view.observations:
        ordinal = index[observation.session]
        if (
            not observation.ordinary_equity
            or ordinal + 10 >= len(view.official_sessions)
            or view.official_sessions[ordinal + 10] >= view.holdout_start
        ):
            continue
        in_support = (
            support[0] <= observation.market_cap <= support[1]
            and support[2] <= observation.price <= support[3]
            and support[4] <= observation.traded_value <= support[5]
        )
        if in_support:
            continue
        excluded += 1
        if observation.market_cap >= support[0]:
            continue
        qualifying = any(
            ordinal < index[event.onset_session] <= ordinal + 10 and _qualifies(event)
            for event in events[observation.issuer_id]
        )
        microcaps.append(
            IncidenceWindow(
                observation.issuer_id,
                observation.session,
                (observation.issuer_id, observation.session.year),
                "outside_support_microcap",
                qualifying,
                observation.member_at_start,
            )
        )
    return excluded, tuple(sorted(microcaps, key=lambda item: (item.start, item.issuer_id)))


def _microcap_sensitivity(
    windows: tuple[IncidenceWindow, ...],
    session_index: Mapping[date, int],
    *,
    draws: int,
    seed: int,
) -> MicrocapSensitivity:
    years, issuers = _support_count(windows)
    if not windows:
        return MicrocapSensitivity(0, 0, 0, 0, None, None, None)
    clustered = _clustered_upper(windows, draws=draws, seed=seed)
    exact = _landmark_upper(windows, session_index)
    event_clusters = len({item.issuer_year for item in windows if item.event_within_ten_sessions})
    return MicrocapSensitivity(
        len(windows),
        sum(item.event_within_ten_sessions for item in windows),
        years,
        issuers,
        clustered,
        exact,
        exact if event_clusters < 5 else max(clustered, exact),
    )


def calibrate_terminal_incidence(
    view: ReferenceView,
    *,
    min_issuer_years: int = 500,
    min_issuers: int = 100,
    bootstrap_draws: int = 9_999,
    seed: int = 0,
) -> IncidenceCalibration:
    """Bound qualifying onset risk without opening strategy outcome paths."""
    if bootstrap_draws <= 0:
        raise ValueError("cluster bootstrap draws must be positive")
    windows = build_incidence_windows(view)
    merged = merge_buckets(windows, min_issuer_years=min_issuer_years, min_issuers=min_issuers)
    support = _support(view)
    excluded, microcap_windows = _outside_support_windows(view, support)
    session_index = {session: index for index, session in enumerate(view.official_sessions)}
    microcap = _microcap_sensitivity(
        microcap_windows, session_index, draws=bootstrap_draws, seed=seed + 1000
    )
    support_bounds = {
        "market_cap": (support[0], support[1]),
        "price": (support[2], support[3]),
        "traded_value": (support[4], support[5]),
    }
    effective = tuple(sorted(set(merged.values())))
    by_bucket = {
        bucket: tuple(window for window in windows if merged[window.initial_bucket] == bucket)
        for bucket in effective
    }
    available_bucket_support = {
        bucket: (*_support_count(group), len(group)) for bucket, group in by_bucket.items()
    }
    if any(
        (counts := _support_count(group))[0] < min_issuer_years or counts[1] < min_issuers
        for group in by_bucket.values()
    ):
        return IncidenceCalibration(
            PromotionStatus.INCIDENCE_DATA_INSUFFICIENT,
            len(windows),
            excluded,
            merged,
            (),
            None,
            None,
            None,
            None,
            None,
            support_bounds=support_bounds,
            available_bucket_support=available_bucket_support,
            microcap_sensitivity=microcap,
        )
    entry_weights = {bucket: 0 for bucket in effective}
    for exposure in view.strategy_exposures:
        initial = _bucket(exposure.market_cap, exposure.traded_value, support[6], support[7])
        entry_weights[merged[initial]] += exposure.entry_count
    total_entries = sum(entry_weights.values())
    buckets: list[BucketIncidence] = []
    for index, bucket in enumerate(effective):
        group = by_bucket[bucket]
        clustered = _clustered_upper(group, draws=bootstrap_draws, seed=seed + index)
        exact = _landmark_upper(group, session_index)
        event_clusters = len(
            {window.issuer_year for window in group if window.event_within_ten_sessions}
        )
        if event_clusters < 5:
            clustered = min(clustered, exact)
        years, issuers = _support_count(group)
        buckets.append(
            BucketIncidence(
                bucket,
                len(group),
                sum(window.event_within_ten_sessions for window in group),
                years,
                issuers,
                clustered,
                exact,
                max(clustered, exact),
                Decimal(entry_weights[bucket]) / Decimal(total_entries),
            )
        )
    weighted_cluster = sum(
        (bucket.strategy_weight * bucket.clustered_upper for bucket in buckets), Decimal(0)
    )
    weighted_exact = sum(
        (bucket.strategy_weight * bucket.landmark_exact_upper for bucket in buckets), Decimal(0)
    )
    primary = sum((bucket.strategy_weight * bucket.primary_upper for bucket in buckets), Decimal(0))
    highest = max(buckets, key=lambda bucket: bucket.primary_upper)
    stressed = Decimal("0.75") * primary + Decimal("0.25") * highest.primary_upper
    return IncidenceCalibration(
        PromotionStatus.PASS,
        len(windows),
        excluded,
        merged,
        tuple(buckets),
        weighted_cluster,
        weighted_exact,
        primary,
        stressed,
        highest.primary_upper,
        support_bounds=support_bounds,
        available_bucket_support=available_bucket_support,
        microcap_sensitivity=microcap,
    )
