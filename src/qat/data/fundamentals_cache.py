"""On-disk cache for fundamentals (spec M18).

Fundamentals move quarterly but the strategy engine asks for them on every
start, and yfinance is rate-limited and unofficial. Without a cache a restart
costs one network round trip per symbol for figures that cannot have changed,
and a rate-limited refetch turns into a screen full of abstentions.

The cache is deliberately dumb: a JSON file keyed by symbol, with the fetch
time alongside each entry. It is an optimisation, never a source of truth, so
every failure mode - missing file, unreadable file, corrupt JSON, an entry
written by an older schema - degrades to a cache miss and a refetch rather
than an error. Losing the cache costs a round trip; trusting a bad entry would
cost a wrong trading decision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qat.data.fundamentals import FundamentalSnapshot, FundamentalsSource

logger = logging.getLogger(__name__)

CACHE_FILENAME = "fundamentals_cache.json"
_FETCHED_AT = "fetched_at"


class FundamentalsCache:
    def __init__(
        self,
        data_dir: str | Path,
        ttl_days: float = 7.0,
        filename: str = CACHE_FILENAME,
    ) -> None:
        self.path = Path(data_dir) / filename
        self.ttl = timedelta(days=ttl_days)
        self._entries: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning(
                "Could not read the fundamentals cache at %s - starting empty and refetching",
                self.path,
                exc_info=True,
            )
            return {}
        if not isinstance(raw, dict):
            logger.warning("Fundamentals cache at %s is not an object - ignoring it", self.path)
            return {}
        return {key: value for key, value in raw.items() if isinstance(value, dict)}

    def get(self, symbol: str) -> FundamentalSnapshot | None:
        entry = self._entries.get(symbol)
        if entry is None:
            return None

        fetched_at = _parse_timestamp(entry.get(_FETCHED_AT))
        if fetched_at is None or datetime.now(UTC) - fetched_at > self.ttl:
            return None

        payload = {key: value for key, value in entry.items() if key != _FETCHED_AT}
        try:
            return FundamentalSnapshot(**payload)  # type: ignore[arg-type]
        except TypeError:
            # Written by a different version of the snapshot. A refetch is
            # always correct here; guessing at the missing fields is not.
            logger.info("Ignoring a stale-schema fundamentals cache entry for %s", symbol)
            return None

    def put(self, symbol: str, snapshot: FundamentalSnapshot) -> None:
        entry: dict[str, object] = dict(asdict(snapshot))
        entry[_FETCHED_AT] = datetime.now(UTC).isoformat(timespec="seconds")
        self._entries[symbol] = entry
        self._flush()

    def _flush(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._entries, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            # In-memory caching still works for this session.
            logger.warning("Could not write the fundamentals cache to %s", self.path, exc_info=True)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class CachingFundamentalsSource:
    """Wraps any FundamentalsSource with the cache above.

    Composed rather than built into the vendor adapter so the caching policy is
    testable on its own, and so a second vendor gets it for free.
    """

    def __init__(self, inner: FundamentalsSource, cache: FundamentalsCache) -> None:
        self.inner = inner
        self.cache = cache

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        cached = self.cache.get(symbol)
        if cached is not None:
            return cached

        snapshot = await self.inner.get_fundamentals(symbol)
        # Synthetic snapshots are never cached: they cost nothing to
        # regenerate, and a cache file full of invented figures that outlives
        # the setting that produced them is a trap.
        if not snapshot.is_synthetic:
            self.cache.put(symbol, snapshot)
        return snapshot
