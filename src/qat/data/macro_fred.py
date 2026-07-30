"""Macro/fundamental data source: daily FRED pulls (spec §D/§17.1).

FredMacroSource is the real client (requests-based, run off-thread so it
never blocks the asyncio loop); MockMacroSource is used for tests and for
local dev when no FRED_API_KEY is configured. Both implement MacroDataSource.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import requests

from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent
from qat.security import get_secret

logger = logging.getLogger(__name__)

_FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_FRED_MISSING_VALUE = "."


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series: str
    ts: datetime
    value: float


class MacroDataSource(Protocol):
    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        """The series' full available history, oldest observation first.

        Full history rather than the latest reading because the daily-bar
        warm-start needs an as-of join against dates already in the past.
        MacroFeed, which only ever wants the current reading, takes the last
        element - see its poll_once.
        """
        ...


class FredMacroSource:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None) -> None:
        self._api_key = api_key or get_secret("FRED_API_KEY")
        self._session = session or requests.Session()

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        if not self._api_key:
            raise RuntimeError(
                "FRED_API_KEY not configured - set via qat.security.set_secret('FRED_API_KEY', ...)"
            )
        return await asyncio.to_thread(self._fetch_sync, series_id)

    def _fetch_sync(self, series_id: str) -> list[MacroObservation]:
        params = {"series_id": series_id, "api_key": self._api_key, "file_type": "json"}
        response = self._session.get(_FRED_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        return self._parse_observations(series_id, response.json())

    @staticmethod
    def _parse_observations(series_id: str, payload: dict[str, Any]) -> list[MacroObservation]:
        observations: list[MacroObservation] = []
        for raw in payload.get("observations", []):
            value_str = raw.get("value")
            if not value_str or value_str == _FRED_MISSING_VALUE:
                continue
            observations.append(
                MacroObservation(
                    series=series_id,
                    ts=datetime.strptime(raw["date"], "%Y-%m-%d").replace(tzinfo=UTC),
                    value=float(value_str),
                )
            )
        return observations


class MockMacroSource:
    """Deterministic seeded macro source for tests/dev without a FRED key."""

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)  # nosec B311 - deterministic synthetic data, not crypto

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        return [
            MacroObservation(
                series=series_id, ts=datetime.now(UTC), value=round(self._rng.uniform(-1, 5), 3)
            )
        ]


class MacroHistory:
    """Point-in-time macro lookups for the warm start (M27a).

    Seeding a daily bar from three months ago with today's VIX would be
    lookahead of the plainest kind, so each historical bar is paired with the
    reading that was current on its own date. Values are carried forward, not
    interpolated: a series that publishes on Friday is genuinely the market's
    best information all weekend, where an interpolated value is a number
    nobody could have seen.

    Returns None before a series' first observation rather than guessing, so
    the caller can leave that feature at its default instead of inventing
    history for a period the data does not cover.
    """

    def __init__(self, observations: dict[str, Sequence[MacroObservation]]) -> None:
        self._by_series: dict[str, tuple[list[datetime], list[float]]] = {}
        for series, series_observations in observations.items():
            ordered = sorted(series_observations, key=lambda obs: obs.ts)
            self._by_series[series] = (
                [obs.ts for obs in ordered],
                [obs.value for obs in ordered],
            )

    @property
    def series(self) -> tuple[str, ...]:
        return tuple(self._by_series)

    def coverage(self, series: str) -> tuple[datetime, datetime] | None:
        timestamps, _ = self._by_series.get(series, ([], []))
        return (timestamps[0], timestamps[-1]) if timestamps else None

    def as_of(self, series: str, ts: datetime) -> float | None:
        timestamps, values = self._by_series.get(series, ([], []))
        if not timestamps:
            return None
        index = bisect_right(timestamps, ts)
        return values[index - 1] if index else None


async def load_macro_history(source: MacroDataSource, series_ids: Sequence[str]) -> MacroHistory:
    """Every configured series' full history, for the warm start's as-of join.

    A series that cannot be fetched is omitted rather than failing the load:
    seeding with two of the three macro features is worse than three and much
    better than none, and the gap is logged where the operator will see it.
    """
    observations: dict[str, Sequence[MacroObservation]] = {}
    for series_id in series_ids:
        try:
            observations[series_id] = await source.fetch_series(series_id)
        except Exception:  # noqa: BLE001 - seed with what is available, say what is not
            logger.exception("Could not load macro history for %s - seeding without it", series_id)
    return MacroHistory(observations)


class MacroFeed:
    """Engine (per domain.orchestrator.Engine protocol): polls each configured
    series on a daily (default) cadence and publishes the current reading of
    each as a MacroEvent.

    One event per series per poll, not one per observation. A source returns
    the series' whole history (VIXCLS alone is over nine thousand daily
    observations back to 1990), and replaying all of it onto the bus every
    poll would publish tens of thousands of events - to the regime engine and
    the Regime Monitor alike - to communicate five current numbers. History is
    the warm-start's business; the feed's business is what the value is now.
    """

    name = "macro-feed"

    def __init__(
        self,
        bus: EventBus,
        source: MacroDataSource,
        series_ids: Sequence[str],
        poll_interval_seconds: float = 86_400.0,
    ) -> None:
        self.bus = bus
        self.source = source
        self.series_ids = list(series_ids)
        self.poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def poll_once(self) -> None:
        for series_id in self.series_ids:
            try:
                observations = await self.source.fetch_series(series_id)
            except Exception:  # noqa: BLE001 - one bad series must not mute the rest
                logger.exception(
                    "Macro series %s could not be fetched - the regime engine keeps its "
                    "previous value for this series",
                    series_id,
                )
                continue

            if not observations:
                logger.warning("Macro series %s returned no observations", series_id)
                continue

            latest = observations[-1]
            logger.info(
                "Macro %s = %s (as of %s, %d observations available)",
                latest.series,
                latest.value,
                latest.ts.date().isoformat(),
                len(observations),
            )
            await self.bus.publish(
                MacroEvent(series=latest.series, value=latest.value, ts=latest.ts)
            )

    async def _poll_loop(self) -> None:
        # A poll that raises must never end the loop. The mock source could not
        # fail; a real one is a network call, and an unhandled exception here
        # would kill the task silently and freeze every macro feature at its
        # last value for the rest of the session.
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - degrade to a stale reading, but loudly
                logger.exception(
                    "Macro poll failed - retrying in %.0fs", self.poll_interval_seconds
                )
            await asyncio.sleep(self.poll_interval_seconds)
