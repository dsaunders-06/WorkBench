"""Scheduled earnings dates, for the event-risk rail (M57).

Every other risk figure in this system is derived from how prices have moved.
An earnings announcement is different in kind: it is a known date on which a
binary outcome is published, and the resulting gap can open straight through a
resting stop. A stop is a promise to sell at a price; a gap is the price never
trading there.

The calendar is an OPTIONAL input by design. A vendor genuinely cannot answer
for every listing - an ETF has no earnings at all - and every failure mode here
returns None rather than raising. None means "this rail abstains", never
"safe": sizing full into an unknown date is the status quo, and the rail can
only ever make a position smaller, so an outage costs the protection and
nothing else.

Distances are in TRADING days, matching the minimum hold and the time stop.
Five calendar days spanning a weekend is three sessions, and a rail specified
in sessions should count them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from qat.domain import market_calendar as mc

logger = logging.getLogger(__name__)

CACHE_FILENAME = "earnings_cache.json"
_FETCHED_AT = "fetched_at"
_NEXT_EARNINGS = "next_earnings"

# Beyond this the answer cannot matter - no blackout window reaches a year out -
# so counting stops rather than walking the calendar indefinitely.
_MAX_LOOKAHEAD_TRADING_DAYS = 400


class EarningsCalendar(Protocol):
    def trading_days_until(self, symbol: str, as_of: date | None = None) -> int | None: ...

    def next_earnings(self, symbol: str) -> date | None: ...

    def refresh(self, symbols: Iterable[str]) -> int: ...


class NullEarningsCalendar:
    """Answers nothing, for runs and tests that are not about this rail.

    Explicit rather than an absent dependency, so the abstain path is exercised
    by ordinary use rather than only when something breaks.
    """

    def trading_days_until(self, symbol: str, as_of: date | None = None) -> int | None:
        return None

    def next_earnings(self, symbol: str) -> date | None:
        return None

    def refresh(self, symbols: Iterable[str]) -> int:
        return 0


def trading_days_between(start: date, end: date, market: mc.Market = "US") -> int:
    """Sessions from `start` up to and including `end`.

    Negative when `end` is already behind `start`, which is how a stale
    calendar entry reads - the risk it names has happened and must not size
    the next trade down forever.

    Counted rather than approximated: a fixed 5/7 ratio is wrong across every
    exchange holiday, and being right about which session a print lands on is
    this rail's entire job.
    """
    if end == start:
        return 0
    step = timedelta(days=1 if end > start else -1)
    sign = 1 if end > start else -1
    sessions = 0
    day = start
    while day != end and sessions < _MAX_LOOKAHEAD_TRADING_DAYS:
        day += step
        if mc.is_trading_day(market, day):
            sessions += 1
    return sign * sessions


class YFinanceEarningsCalendar:
    """Next scheduled announcement per symbol, cached on disk.

    Cached for the same reason fundamentals are: the date moves quarterly, the
    risk engine asks on every candidate, and yfinance is rate-limited and
    unofficial. The cache is an optimisation and never a source of truth, so
    every failure - missing file, corrupt JSON, an unparseable date, no network
    - degrades to "unknown" and the rail abstains.
    """

    def __init__(
        self,
        data_dir: str | Path,
        ttl_days: float = 1.0,
        filename: str = CACHE_FILENAME,
        market: mc.Market = "US",
    ) -> None:
        self.path = Path(data_dir) / filename
        self.ttl = timedelta(days=ttl_days)
        self.market = market
        self._entries: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning(
                "Could not read the earnings cache at %s - starting empty", self.path, exc_info=True
            )
            return {}
        if not isinstance(raw, dict):
            return {}
        return {key: value for key, value in raw.items() if isinstance(value, dict)}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("Could not write the earnings cache at %s", self.path, exc_info=True)

    def _cached(self, symbol: str) -> tuple[bool, date | None]:
        """(hit, value). A hit carrying None is a real answer - the vendor was
        asked and does not know - and must not trigger a refetch every tick."""
        entry = self._entries.get(symbol)
        if entry is None:
            return False, None
        fetched = entry.get(_FETCHED_AT)
        try:
            fetched_at = datetime.fromisoformat(str(fetched))
        except (TypeError, ValueError):
            return False, None
        if datetime.now(UTC) - fetched_at > self.ttl:
            return False, None
        raw = entry.get(_NEXT_EARNINGS)
        if raw is None:
            return True, None
        try:
            return True, date.fromisoformat(str(raw))
        except ValueError:
            return False, None

    def refresh(self, symbols: Iterable[str]) -> int:
        """Fetch anything not already cached. Blocking, and meant to be.

        This is the ONLY method that touches the network, so the hot path
        cannot accidentally acquire a vendor call (M57c). Call it from a
        thread, away from the event loop.
        """
        fetched = 0
        for symbol in symbols:
            hit, _ = self._cached(symbol)
            if hit:
                continue
            self._store(symbol, self._fetch_guarded(symbol))
            fetched += 1
        if fetched:
            self._save()
        return fetched

    def _fetch_guarded(self, symbol: str) -> date | None:
        try:
            return self._fetch(symbol)
        except Exception:  # noqa: BLE001 - the guarantee belongs at the boundary
            # _fetch guards its own vendor call too, but this rail's contract
            # is "never raises", and a contract enforced only inside a private
            # helper is not enforced. An outage must cost the protection, never
            # the session.
            logger.debug("Earnings lookup failed for %s", symbol, exc_info=True)
            return None

    def _store(self, symbol: str, announcement: date | None) -> None:
        self._entries[symbol] = {
            _FETCHED_AT: datetime.now(UTC).isoformat(),
            _NEXT_EARNINGS: announcement.isoformat() if announcement else None,
        }

    def next_earnings(self, symbol: str) -> date | None:
        """The cached answer, or None. Never fetches.

        Cache-only by construction, because this is reached from the signal
        path on every candidate. On 7 August it was a blocking vendor call
        there: 1,898 sizing decisions produced two cached symbols, which is the
        shape of something being throttled while an event loop waits for it.
        A miss abstains, exactly as an unknown date does, and `refresh` fills
        the cache in the background so misses become rare rather than blocking.
        """
        _hit, cached = self._cached(symbol)
        return cached

    def _fetch(self, symbol: str) -> date | None:
        try:
            import yfinance as yf  # type: ignore[import-untyped]

            calendar = yf.Ticker(symbol).calendar
        except Exception:  # noqa: BLE001 - an optional rail must never raise
            logger.debug("No earnings date available for %s", symbol, exc_info=True)
            return None
        return _first_future_date(calendar)

    def trading_days_until(self, symbol: str, as_of: date | None = None) -> int | None:
        announcement = self.next_earnings(symbol)
        if announcement is None:
            return None
        return trading_days_between(as_of or datetime.now(UTC).date(), announcement, self.market)


def _first_future_date(calendar: object) -> date | None:
    """The next announcement out of whatever shape yfinance returned.

    Deliberately defensive. `Ticker.calendar` has been a DataFrame and a dict
    across versions, `Earnings Date` holds either one date or a low/high
    estimate pair, and this is an unofficial API on an optional rail - so
    anything unrecognised reads as "unknown" rather than as an error.
    """
    values: list[object] = []
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date")
        values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    else:
        try:
            values = list(calendar.loc["Earnings Date"])  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None

    today = datetime.now(UTC).date()
    found: list[date] = []
    for value in values:
        parsed = _as_date(value)
        if parsed is not None and parsed >= today:
            found.append(parsed)
    return min(found) if found else None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


__all__ = [
    "CACHE_FILENAME",
    "EarningsCalendar",
    "NullEarningsCalendar",
    "YFinanceEarningsCalendar",
    "trading_days_between",
]
