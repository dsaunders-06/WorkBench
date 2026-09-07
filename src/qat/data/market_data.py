"""Real-time ingestion pipeline: source -> bounded queue -> validated events
(spec §D/§17.1), plus the data-staleness monitor (§17.2, §18.2 kill-switch trigger).

MarketDataSource is the extension point: SyntheticMarketDataSource here is
deterministic and seeded for tests/dev. An IBKR-backed implementation
(reqMktData over ib_async) is added in M7 behind this same interface -
nothing else in the pipeline needs to change when that lands.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Protocol

from qat.domain.bus import EventBus
from qat.domain.events import DataStaleEvent, MarketDataEvent, MarketDataFeedEvent

logger = logging.getLogger(__name__)

# How many ticks to observe before saying anything about the feed's real lag,
# and how far it may drift from the configured claim before that is worth
# saying. Five minutes, because a vendor's publication delay moves in steps of
# minutes and a tighter band would just report jitter.
_LAG_SAMPLE_SIZE = 200
_MIN_LAG_SAMPLES = 20
_LAG_TOLERANCE_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class RawTick:
    symbol: str
    ts: datetime
    price: float
    volume: float


class MarketDataSource(Protocol):
    def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]: ...


class SyntheticMarketDataSource:
    """Deterministic seeded random-walk tick generator."""

    def __init__(
        self, seed: int = 0, interval_seconds: float = 0.0, base_price: float = 100.0
    ) -> None:
        self._rng = random.Random(seed)  # nosec B311 - deterministic synthetic ticks, not crypto
        self._interval = interval_seconds
        self._base_price = base_price
        self._prices: dict[str, float] = {}

    async def stream_ticks(self, symbols: Sequence[str]) -> AsyncIterator[RawTick]:
        while True:
            for symbol in symbols:
                price = self._prices.setdefault(symbol, self._base_price)
                price = max(0.01, price + self._rng.uniform(-0.5, 0.5))
                self._prices[symbol] = price
                yield RawTick(
                    symbol=symbol,
                    ts=datetime.now(UTC),
                    price=round(price, 2),
                    volume=float(self._rng.randint(1, 1000)),
                )
            if self._interval:
                await asyncio.sleep(self._interval)


class MarketDataFeed:
    """Engine (per domain.orchestrator.Engine protocol): ingests from a
    MarketDataSource, publishes MarketDataEvent per tick, and raises
    DataStaleEvent when a symbol stops updating within staleness_seconds."""

    name = "market-data-feed"

    def __init__(
        self,
        bus: EventBus,
        source: MarketDataSource,
        symbols: Sequence[str],
        staleness_seconds: float = 60.0,
        staleness_check_interval: float = 5.0,
        queue_maxsize: int = 1000,
        feed_down_seconds: float = 300.0,
        # How far behind the market this SOURCE structurally is (M128). Yahoo
        # publishes ASX intraday roughly twenty minutes late; that is a property
        # of the feed, not a symptom of a thin symbol, and the staleness rail
        # must not read it as one. Zero for a real-time source.
        source_delay_seconds: float = 0.0,
    ) -> None:
        self.bus = bus
        self.source = source
        self.symbols = list(symbols)
        self.staleness_seconds = staleness_seconds
        self.source_delay_seconds = source_delay_seconds
        self.staleness_check_interval = staleness_check_interval
        self.feed_down_seconds = feed_down_seconds
        self._queue: asyncio.Queue[RawTick] = asyncio.Queue(maxsize=queue_maxsize)
        self._last_seen: dict[str, datetime] = {}
        # Item 33. Reported once on transition rather than on every pass.
        self._absence_reported = False
        # Which symbols are currently excluded, so only the edges are published.
        self._stale_symbols: dict[str, bool] = {}
        self._tasks: list[asyncio.Task[None]] = []
        # Feed-level health, tracked separately from per-symbol staleness.
        # Measured from when the feed started rather than from the first tick,
        # which is the case per-symbol staleness cannot see: a source that has
        # never produced anything leaves _last_seen empty, so every symbol is
        # skipped and nothing is ever reported.
        self._started_at: datetime | None = None
        self._last_tick_at: datetime | None = None
        self._feed_healthy = True
        # M130. What the feed's delay ACTUALLY is, watched against what it was
        # configured to be. `source_delay_seconds` is a measured claim about a
        # vendor, taken on one morning, and nothing else in this system checks
        # it - not the replay harness, which bypasses this class entirely, and
        # not the unit tests, which supply their own timestamps. A number that
        # only one observation supports should be re-observed continuously.
        #
        # IT NEVER CHANGES THE THRESHOLD. A safety rail that widens its own
        # tolerance when the feed degrades is blind exactly when it matters, so
        # this only ever reports.
        self._observed_lags: deque[float] = deque(maxlen=_LAG_SAMPLE_SIZE)
        self._delay_claim_warned = False

    async def start(self) -> None:
        # Cleared so a feed restarted after a break (M19: the overnight stand
        # down) does not immediately report every symbol as stale against a
        # last-seen timestamp from before it slept.
        self._last_seen.clear()
        self._absence_reported = False
        self._stale_symbols.clear()
        self._started_at = datetime.now(UTC)
        self._last_tick_at = None
        self._feed_healthy = True
        self._tasks = [
            asyncio.create_task(self._ingest_loop()),
            asyncio.create_task(self._process_loop()),
            asyncio.create_task(self._staleness_loop()),
            asyncio.create_task(self._feed_health_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def _ingest_loop(self) -> None:
        async for tick in self.source.stream_ticks(self.symbols):
            await self._queue.put(tick)

    async def _process_loop(self) -> None:
        while True:
            tick = await self._queue.get()
            self._last_seen[tick.symbol] = tick.ts
            self._last_tick_at = datetime.now(UTC)
            self._observe_lag(tick.ts, self._last_tick_at)
            if not self._feed_healthy:
                self._feed_healthy = True
                await self.bus.publish(
                    MarketDataFeedEvent(healthy=True, reason="market data is flowing again")
                )
            await self.bus.publish(
                MarketDataEvent(
                    symbol=tick.symbol, price=tick.price, volume=tick.volume, ts=tick.ts
                )
            )

    async def _feed_health_loop(self) -> None:
        """Is anything arriving at all?

        Deliberately not a kill-switch trigger. No ticks means no feature
        snapshots, so no signals and no orders - the danger of a dead feed is
        not that it trades wrongly but that nobody notices it has stopped. The
        answer to that is to say so, loudly, not to demand a manual reset for
        an outage that may clear itself.
        """
        while True:
            await asyncio.sleep(self.staleness_check_interval)
            if not self._feed_healthy:
                continue
            reference = self._last_tick_at or self._started_at
            if reference is None:
                continue
            quiet = (datetime.now(UTC) - reference).total_seconds()
            if quiet <= self.feed_down_seconds:
                continue
            self._feed_healthy = False
            # ⚠️ TWO DIFFERENT CONDITIONS, AND THEY WERE LOGGED THE SAME WAY.
            # A feed that has NEVER ticked has not started; a feed that ticked
            # and then went quiet has stopped. Only the second is an outage.
            #
            # Measured, not assumed: `MARKET DATA DOWN` appears eight times in
            # the live log - 26, 27, 28 August, 31 August, 1, 2, 4 and
            # 7 September - and every one is at 00:05 UTC, five minutes after
            # the ASX opens, on a feed that had never ticked. Eight for eight
            # false. Yahoo publishes ASX intraday about twenty minutes late, so
            # at the open nothing has printed yet.
            #
            # ⚠️ The sibling of the yfinance rail corrected in M167, which had
            # the identical defect and was fixed on the identical evidence.
            # Removing that alarm alone only left the operator receiving this
            # one, because nobody looked for the sibling.
            #
            # ⚠️ THE EVENT IS UNCHANGED. `MarketDataFeedEvent(healthy=False)` is
            # still published below in both cases - the UI banner should still
            # say the feed is not flowing, because at the open that is true.
            # Only the severity and the wording change.
            if self._last_tick_at is not None:
                reason = f"no market data for {quiet / 60:.0f} minutes"
                logger.error("MARKET DATA DOWN: %s", reason)
            else:
                reason = f"no market data since the feed started {quiet / 60:.0f} minutes ago"
                logger.warning(
                    "Market data has not started: %s. No symbol has printed yet, which at "
                    "the open is this feed's own ~20 minute delay rather than an outage. "
                    "If it persists once prices are printing, the per-symbol staleness "
                    "rail is what reports it.",
                    reason,
                )
            await self.bus.publish(
                MarketDataFeedEvent(healthy=False, reason=reason, seconds_since_last_tick=quiet)
            )

    async def _staleness_loop(self) -> None:
        """Per-symbol quote freshness, reported on transitions only (M28a).

        Publishing on every check would republish the same stale symbol every
        interval for as long as it stayed thin, which is how a rail becomes
        noise. The edges are the news: this symbol just went stale, this one
        just came back.
        """
        while True:
            await asyncio.sleep(self.staleness_check_interval)
            await self._check_staleness_once()

    def _observe_lag(self, bar_ts: datetime, arrived_at: datetime) -> None:
        """How far behind this tick actually was (M130).

        Skips a naive timestamp rather than guessing at its zone: a source that
        does not say which clock it used cannot be measured against ours, and
        inventing UTC would manufacture a lag rather than observe one.
        """
        if bar_ts.tzinfo is None:
            return
        lag = (arrived_at - bar_ts).total_seconds()
        # A negative lag means the bar is stamped in the future, which is a
        # clock problem rather than a delay - excluded so it cannot drag the
        # median toward a reassuring number.
        if lag >= 0:
            self._observed_lags.append(lag)

    def observed_delay_seconds(self) -> float | None:
        """The feed's measured lag, or None before there is enough to say.

        Median rather than mean: one tick arriving after a stall would drag a
        mean and says nothing about the feed's normal behaviour.
        """
        if len(self._observed_lags) < _MIN_LAG_SAMPLES:
            return None
        return median(self._observed_lags)

    def _check_delay_claim(self) -> None:
        """Say so when the vendor stops behaving the way the config claims.

        Reports on the EDGE only, both ways, so a feed that drifts and comes
        back does not repeat itself every interval - the same rule the staleness
        rail follows for the same reason.
        """
        observed = self.observed_delay_seconds()
        if observed is None:
            return

        drift = observed - self.source_delay_seconds
        if abs(drift) <= _LAG_TOLERANCE_SECONDS:
            if self._delay_claim_warned:
                self._delay_claim_warned = False
                logger.info(
                    "Feed delay is back in line with the configured %.0fs (observed %.0fs)",
                    self.source_delay_seconds,
                    observed,
                )
            return

        if self._delay_claim_warned:
            return
        self._delay_claim_warned = True
        logger.warning(
            "FEED DELAY CLAIM IS OUT OF DATE: configured %.0fs, observed %.0fs (%+.0fs). "
            "Staleness is measured beyond the configured figure, so the rail is currently "
            "%s. This does NOT adjust itself - re-measure the vendor and set "
            "QAT_MARKET_DATA_DELAY_SECONDS.",
            self.source_delay_seconds,
            observed,
            drift,
            "blind by the difference" if drift > 0 else "tighter than intended",
        )

    def last_print_at(self, symbol: str) -> datetime | None:
        """When this symbol's most recent print was STAMPED, or None if it has
        not printed since `start()` (item 33).

        The trade's own timestamp, not its arrival time, for the reason M128
        gives - which is what makes it usable as "does this price belong to
        today's session".

        ⚠️ `start()` clears `_last_seen`, so after the overnight stand-down every
        symbol reads None until it prints again. That is correct: nothing from
        before the restart is a current price.
        """
        return self._last_seen.get(symbol)

    async def _check_staleness_once(self) -> None:
        """One pass of the rail, extracted so it can be tested without driving
        a loop (M128). The arithmetic below is a risk decision; it deserves a
        test that does not depend on sleeping."""
        # M130. Checked on the same interval, because "is the feed as delayed as
        # we think" and "is this print too old" are the same question asked from
        # two directions, and an answer to the second is only as good as the
        # first.
        self._check_delay_claim()
        now = datetime.now(UTC)

        # Item 33. A symbol with no recorded print is skipped by the loop below
        # - `if last is None: continue` - so it is never marked stale and never
        # excluded. It is ABSENT, not stale, and until now nothing said so.
        #
        # ⚠️ Reported only once SOMETHING has printed. This component holds no
        # market and no session, so it cannot say "the session has opened" - and
        # does not need to. "The feed is working and these symbols are not in
        # it" is the condition that matters, and before the first tick there is
        # no line at all rather than a false "94 of 94 absent" at every bell.
        # A wholly dead feed stays MarketDataFeedEvent's question, which keeps
        # M28a's separation between one silent symbol and a down feed.
        absent = [symbol for symbol in self.symbols if self._last_seen.get(symbol) is None]
        if absent and len(absent) < len(self.symbols) and not self._absence_reported:
            self._absence_reported = True
            logger.warning(
                "%d of %d watched symbol(s) have not printed at all this session, so they are "
                "ABSENT rather than stale and the staleness rail cannot see them - it skips a "
                "symbol it has never seen. They cannot be entered: %s",
                len(absent),
                len(self.symbols),
                ", ".join(sorted(absent)[:10]) + (" ..." if len(absent) > 10 else ""),
            )

        for symbol in self.symbols:
            last = self._last_seen.get(symbol)
            if last is None:
                continue
            # M128. Measured BEYOND the feed's own lag. `elapsed` is now the
            # true age of the price, because the tick carries the bar's
            # timestamp rather than its arrival time - so on a feed that is
            # structurally twenty minutes behind, every symbol would be
            # permanently stale and nothing would ever signal. Subtracting
            # the known delay keeps `staleness_seconds` meaning what its
            # own config comment says: how far past the feed's normal lag a
            # print has to be before sizing against it is a hazard.
            elapsed = (now - last).total_seconds() - self.source_delay_seconds
            stale = elapsed > self.staleness_seconds
            if stale == self._stale_symbols.get(symbol, False):
                continue
            self._stale_symbols[symbol] = stale
            if stale:
                logger.warning(
                    "%s last printed %.0fs ago - excluded from signals until it trades "
                    "again. The account is NOT halted",
                    symbol,
                    elapsed,
                )
            else:
                logger.info("%s is printing again after %.0fs", symbol, elapsed)
            await self.bus.publish(
                DataStaleEvent(symbol=symbol, seconds_since_update=elapsed, stale=stale)
            )
