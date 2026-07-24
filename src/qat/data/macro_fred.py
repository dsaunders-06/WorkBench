"""Macro/fundamental data source: daily FRED pulls (spec §D/§17.1).

FredMacroSource is the real client (requests-based, run off-thread so it
never blocks the asyncio loop); MockMacroSource is used for tests and for
local dev when no FRED_API_KEY is configured. Both implement MacroDataSource.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import requests

from qat.domain.bus import EventBus
from qat.domain.events import MacroEvent
from qat.security import get_secret

_FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_FRED_MISSING_VALUE = "."


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series: str
    ts: datetime
    value: float


class MacroDataSource(Protocol):
    async def fetch_series(self, series_id: str) -> list[MacroObservation]: ...


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


class MacroFeed:
    """Engine (per domain.orchestrator.Engine protocol): polls each configured
    series on a daily (default) cadence and publishes MacroEvent per observation."""

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
            for observation in await self.source.fetch_series(series_id):
                await self.bus.publish(
                    MacroEvent(
                        series=observation.series, value=observation.value, ts=observation.ts
                    )
                )

    async def _poll_loop(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self.poll_interval_seconds)
