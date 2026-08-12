"""What each broker adapter can actually do, derived rather than listed.

`BrokerAdapter` marks most of its surface optional and documents a fallback for
each - "Adapters that cannot answer return an empty tuple, which reads as
'unknown' rather than 'none'" - and every caller guards with `getattr`. Nothing
crashes and nothing corrupts on an adapter that lacks them.

That is exactly why the absence is invisible. Without `resting_stops` the app
stops verifying its own belief about what protects the book; without
`recent_fills` a protective order firing is never absorbed as a closed trade;
without `announcements` a split on a held position is not seen before the
ex-date open. None of it errors. None of it logs. A full suite passes.

The method list is derived from the Protocol so that a method added there and
classified nowhere fails a test rather than going unaudited - M80's register
pattern, pointed at the broker port. Nothing here reads configuration, touches
a network, or instantiates an adapter: it inspects classes.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from qat.data.broker.adapter import BrokerAdapter

CORE: frozenset[str] = frozenset(
    {
        "account",
        "cancel_order",
        "get_historical",
        "get_market_data",
        "modify_order",
        "place_order",
        "positions",
    }
)
"""Without any one of these there is no trading path at all - no price, no
order, no position, no balance. An adapter missing one is not a degraded
broker, it is not a broker, and `resolve_broker` refuses it."""

OPTIONAL: dict[str, str] = {
    "balances": (
        "M21's richer balance display falls back to the three core figures from "
        "the account summary - a display degradation, and the only harmless one here"
    ),
    "recent_fills": (
        "M34/M48 broker-side fill absorption stops: a protective order firing at "
        "the broker is never recorded as a closed trade, so the ledger silently "
        "misses exits the app did not itself transmit"
    ),
    "resting_stops": (
        "M31b protection verification stops: the app can no longer check its own "
        "belief about what rests at the broker, and a stop that was cancelled or "
        "never placed reads exactly like one that is working"
    ),
    "resting_stop_orders": (
        "M39 cannot re-price a resting stop through a corporate action, because "
        "it has no order id to call modify_order on - the MNST failure, unrepaired"
    ),
    "announcements": (
        "M39 corporate-action detection stops: a split on a held position is not "
        "seen before the ex-date open, and an unadjusted stop through a split "
        "cost this account $375.23 on 11 August"
    ),
}
"""Optional by the Protocol's own design - and each entry says what stops
happening when an adapter does not implement it. A new optional method with no
consequence sentence fails `test_every_optional_capability_names_what_is_lost`,
because an absence nobody described is the silence this module exists to end."""


def protocol_methods() -> frozenset[str]:
    """The public method names on BrokerAdapter, from the Protocol itself.

    Derived rather than listed, so this cannot drift from the port it audits.
    """
    return frozenset(
        name
        for name, _ in inspect.getmembers(BrokerAdapter, inspect.isfunction)
        if not name.startswith("_")
    )


def unclassified() -> frozenset[str]:
    """Protocol methods that are neither CORE nor OPTIONAL - i.e. unaudited."""
    return protocol_methods() - CORE - frozenset(OPTIONAL)


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    adapter: str
    implemented: frozenset[str]
    missing_core: frozenset[str]
    missing_optional: frozenset[str]

    @property
    def disabled(self) -> tuple[str, ...]:
        """What stops working on this adapter, in the words of OPTIONAL."""
        return tuple(OPTIONAL[name] for name in sorted(self.missing_optional))

    @property
    def can_trade(self) -> bool:
        return not self.missing_core


def inspect_adapter(adapter: type) -> AdapterCapabilities:
    """Classify one adapter CLASS against the Protocol. Never instantiates it -
    IBAdapter's constructor alone can raise, and an audit must not need a
    broker session to run."""
    methods = protocol_methods()
    implemented = frozenset(name for name in methods if hasattr(adapter, name))
    absent = methods - implemented
    return AdapterCapabilities(
        adapter=adapter.__name__,
        implemented=implemented,
        missing_core=absent & CORE,
        missing_optional=absent & frozenset(OPTIONAL),
    )


def KNOWN_ADAPTERS() -> dict[str, type]:  # noqa: N802 - a registry, named as one
    """Every adapter that can be resolved as a broker, keyed by its config value.

    A function rather than a module constant because importing IBAdapter pulls
    in ib_async, and an import-time failure in a reporting module would take
    the application down with it.
    """
    from qat.data.broker.alpaca_adapter import AlpacaAdapter
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.mock_broker import MockBroker

    return {"alpaca": AlpacaAdapter, "ibkr": IBAdapter, "mock": MockBroker}
