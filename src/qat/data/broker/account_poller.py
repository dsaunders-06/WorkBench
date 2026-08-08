"""One throttled, shared read of the broker's account state (spec M21).

The Dashboard's two-second timer called broker.account() and
broker.positions() on every tick. Against Alpaca that is sixty requests a
minute, permanently, to redraw one tile - and the documented per-account limit
read straight off the response headers is:

    X-Ratelimit-Limit: 200

so a third of the budget was going on repainting, before the market data feed,
the equity monitor and reconciliation had asked for anything. Adding a
balances call per tick would have taken it to ninety.

This is the fix: every screen reads the same cached snapshot, and exactly one
fetch happens per interval no matter how many screens are watching. At the
five-second default that is twelve requests a minute for account, balances and
positions together - cheaper than what it replaces.

The other half is honesty about staleness. A cached figure that silently keeps
displaying after the broker stopped answering is worse than no figure, so the
snapshot carries the time it was taken and the panel shows its age.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    BrokerAdapter,
    Position,
    balances_from_summary,
)

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 5.0

# Treat a snapshot older than this as stale in the UI. Comfortably above the
# poll interval so an ordinary slow response is not reported as a fault.
STALE_AFTER_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    summary: AccountSummary | None
    balances: AccountBalances
    positions: tuple[Position, ...]
    taken_at: datetime
    error: str | None = None

    @property
    def age_seconds(self) -> float:
        return (datetime.now(UTC) - self.taken_at).total_seconds()

    @property
    def is_stale(self) -> bool:
        return self.age_seconds > STALE_AFTER_SECONDS

    def age_line(self) -> str:
        if self.error:
            return f"last good reading {self.taken_at:%H:%M:%S} - {self.error}"
        if self.is_stale:
            return f"STALE - as of {self.taken_at:%H:%M:%S}"
        return f"as of {self.taken_at:%H:%M:%S}"


@dataclass
class AccountPoller:
    """Shared, throttled account reader. Not an Engine: it is pull-driven, so
    it does no work at all while nothing is looking at it."""

    broker: BrokerAdapter
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    _snapshot: AccountSnapshot | None = field(default=None, init=False)
    _fetched_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def last_snapshot(self) -> AccountSnapshot | None:
        """The cached snapshot without fetching one, or None if nothing has
        been read yet.

        For synchronous callers - a Qt slot cannot await `snapshot()`, and
        blocking the UI thread on a broker round-trip to avoid that would be
        worse than the problem. None is a real answer here and callers are
        expected to decline rather than to assume a zero.
        """
        return self._snapshot

    async def snapshot(self, force: bool = False) -> AccountSnapshot:
        """The cached snapshot, refreshed at most once per interval.

        The lock matters: several screens refreshing on the same tick would
        otherwise each see a cold cache and each issue their own fetch, which
        is precisely the request storm this exists to prevent.
        """
        async with self._lock:
            fresh_enough = (
                self._snapshot is not None
                and (time.monotonic() - self._fetched_at) < self.interval_seconds
            )
            if fresh_enough and not force:
                return self._snapshot  # type: ignore[return-value]
            return await self._fetch()

    async def _fetch(self) -> AccountSnapshot:
        try:
            summary = await self.broker.account()
            balances = await self._balances(summary)
            positions = await self.broker.positions()
        except Exception as exc:  # noqa: BLE001 - surfaced on the snapshot
            logger.warning("Could not read the account from the broker: %s", exc)
            return self._degrade(str(exc))

        self._snapshot = AccountSnapshot(
            summary=summary,
            balances=balances,
            positions=tuple(positions),
            taken_at=datetime.now(UTC),
        )
        self._fetched_at = time.monotonic()
        return self._snapshot

    async def _balances(self, summary: AccountSummary) -> AccountBalances:
        """The richer view when the adapter has one, derived otherwise."""
        getter = getattr(self.broker, "balances", None)
        if getter is None:
            return balances_from_summary(summary)
        try:
            balances: AccountBalances = await getter()
        except NotImplementedError:
            return balances_from_summary(summary)
        return balances

    def _degrade(self, error: str) -> AccountSnapshot:
        """Keep serving the last good reading, labelled with its real age.

        Blanking the panel on a transient failure would be its own kind of
        lie - the money did not disappear. What must not happen is a stale
        number presented as current, so taken_at is carried forward unchanged
        and the error rides along with it.
        """
        if self._snapshot is None:
            return AccountSnapshot(
                summary=None,
                balances=AccountBalances(),
                positions=(),
                taken_at=datetime.now(UTC),
                error=error,
            )
        previous = self._snapshot
        return AccountSnapshot(
            summary=previous.summary,
            balances=previous.balances,
            positions=previous.positions,
            taken_at=previous.taken_at,
            error=error,
        )
