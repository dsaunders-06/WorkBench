"""Typed events published on the in-process EventBus.

All inter-engine communication happens exclusively through these events
(spec §C) - engines never call each other directly. Every event carries a
UTC timestamp so downstream consumers can enforce point-in-time discipline.

Most event types below are declared now but not yet published by anything -
they exist so the domain vocabulary is fixed early; later milestones wire
producers and consumers for each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    ts: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataEvent(Event):
    symbol: str
    price: float
    volume: float


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureEvent(Event):
    symbol: str
    features: dict[str, float]
    as_of: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MacroEvent(Event):
    series: str
    value: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RegimeEvent(Event):
    label: str
    probs: dict[str, float]
    exposure_scalar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalEvent(Event):
    symbol: str
    side: Literal["buy", "sell"]
    conviction: float
    strategy: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderPendingSignoffEvent(Event):
    """An order has been risk-approved and now awaits a decision.

    In "recommend" mode the decision is a human's, in the Order Blotter. In
    "auto" mode AutonomousExecutor subscribes to this and may make it. Both
    paths still go through OMS.sign_off - this event announces that an order is
    waiting, it does not bypass anything.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    strategy: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderFilledEvent(Event):
    """An order actually filled at the broker.

    Distinct from OrderPendingSignoffEvent: that one announces an intention,
    this one records a fact. Performance measurement can only ever be built on
    the second - a decision journal tells you what the system chose, never
    whether it worked.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    strategy: str | None = None
    stop_price: float | None = None
    operator: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class DataStaleEvent(Event):
    symbol: str
    seconds_since_update: float


@dataclass(frozen=True, slots=True, kw_only=True)
class KillSwitchEvent(Event):
    reason: str
    triggered_by: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataFeedEvent(Event):
    """The feed as a whole is up or down (spec M26).

    DataStaleEvent is per-symbol and only fires for a symbol that has ticked
    at least once, so a feed that never delivered anything raised nothing at
    all: the app ran a full session on no data while the banner read
    AUTO-TRADE ACTIVE. This event is about the feed rather than a symbol, and
    so it can be raised on exactly that case.
    """

    healthy: bool
    reason: str
    seconds_since_last_tick: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RegimeHealthEvent(Event):
    """The regime classifier is producing labels, or it is not (M27a).

    StrategyEngine falls open to its default regime when no RegimeEvent has
    arrived, which keeps the application trading through a dead classifier -
    defensible for availability, and invisible until now. On 28 July the HMM
    crashed on every fit and the only trace was hmmlearn's traceback in the
    bus; the screen said nothing at all.

    Unhealthy covers both "it has failed" and "it has never yet succeeded",
    because the consequence is identical: the regime gate is not gating, and
    every strategy is being permitted or refused on a default rather than on a
    reading of the market.
    """

    healthy: bool
    reason: str
