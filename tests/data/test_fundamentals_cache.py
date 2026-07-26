"""Fundamentals TTL cache (spec M18).

The cache is an optimisation, never a source of truth, so the tests that
matter are the failure modes: every one of them must degrade to a refetch
rather than to an error or, worse, to a confidently wrong entry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from qat.data.fundamentals import FundamentalSnapshot, MockFundamentalsSource
from qat.data.fundamentals_cache import (
    CACHE_FILENAME,
    CachingFundamentalsSource,
    FundamentalsCache,
)


def _snapshot(symbol: str = "AAPL", roe: float | None = 0.31) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        sector="Information Technology",
        eps_growth_yoy=0.12,
        eps_growth_accelerating=True,
        peg_ratio=1.4,
        roe=roe,
        roic=0.25,
        debt_to_equity=0.3,
        book_to_market=0.15,
        earnings_yield=0.04,
        ev_to_ebit=18.0,
        fcf_yield=0.03,
        dividend_yield=0.005,
        dividend_growth_streak_years=12,
        payout_ratio=0.16,
        institutional_ownership_pct=0.61,
        relative_strength_rank=72.0,
        is_synthetic=False,
    )


class CountingSource:
    def __init__(self, snapshot: FundamentalSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        self.calls += 1
        return self.snapshot


def test_a_fresh_entry_round_trips_through_the_file(tmp_path):
    FundamentalsCache(tmp_path).put("AAPL", _snapshot())

    reloaded = FundamentalsCache(tmp_path).get("AAPL")

    assert reloaded == _snapshot()


def test_an_expired_entry_is_a_miss(tmp_path):
    cache = FundamentalsCache(tmp_path, ttl_days=7.0)
    cache.put("AAPL", _snapshot())
    # Backdate the stored fetch time past the TTL.
    cache._entries["AAPL"]["fetched_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat(
        timespec="seconds"
    )

    assert cache.get("AAPL") is None


def test_an_unknown_symbol_is_a_miss(tmp_path):
    assert FundamentalsCache(tmp_path).get("NOPE") is None


def test_a_corrupt_cache_file_is_ignored_rather_than_raising(tmp_path):
    (tmp_path / CACHE_FILENAME).write_text("{not json at all", encoding="utf-8")

    cache = FundamentalsCache(tmp_path)

    assert cache.get("AAPL") is None
    # And it still works from here on.
    cache.put("AAPL", _snapshot())
    assert cache.get("AAPL") == _snapshot()


def test_an_entry_from_an_older_schema_is_a_miss_not_a_crash(tmp_path):
    """Refetching is always correct here. Filling in the fields a previous
    version did not store would be inventing them."""
    path = tmp_path / CACHE_FILENAME
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    path.write_text(
        json.dumps({"AAPL": {"symbol": "AAPL", "sector": "X", "fetched_at": fetched_at}}),
        encoding="utf-8",
    )

    assert FundamentalsCache(tmp_path).get("AAPL") is None


def test_an_entry_with_no_timestamp_is_a_miss(tmp_path):
    path = tmp_path / CACHE_FILENAME
    path.write_text('{"AAPL": {"symbol": "AAPL"}}', encoding="utf-8")

    assert FundamentalsCache(tmp_path).get("AAPL") is None


async def test_the_wrapper_only_calls_the_vendor_once_per_symbol(tmp_path):
    inner = CountingSource(_snapshot())
    source = CachingFundamentalsSource(inner, FundamentalsCache(tmp_path))

    first = await source.get_fundamentals("AAPL")
    second = await source.get_fundamentals("AAPL")

    assert inner.calls == 1
    assert first == second


async def test_the_cache_survives_a_restart(tmp_path):
    inner = CountingSource(_snapshot())
    await CachingFundamentalsSource(inner, FundamentalsCache(tmp_path)).get_fundamentals("AAPL")

    # A second run, with its own cache object reading the same directory.
    await CachingFundamentalsSource(inner, FundamentalsCache(tmp_path)).get_fundamentals("AAPL")

    assert inner.calls == 1


async def test_synthetic_snapshots_are_never_written_to_disk(tmp_path):
    """A cache file full of invented figures would outlive the setting that
    produced them, and nothing downstream would know."""
    source = CachingFundamentalsSource(MockFundamentalsSource(seed=1), FundamentalsCache(tmp_path))

    snapshot = await source.get_fundamentals("AAPL")

    assert snapshot.is_synthetic is True
    assert not (tmp_path / CACHE_FILENAME).exists()


async def test_missing_values_survive_the_round_trip(tmp_path):
    """None must come back as None. Restored as 0.0 it would turn an ETF that
    abstains into one that scores badly."""
    inner = CountingSource(_snapshot(symbol="SPY", roe=None))
    cache_dir = tmp_path
    await CachingFundamentalsSource(inner, FundamentalsCache(cache_dir)).get_fundamentals("SPY")

    restored = FundamentalsCache(cache_dir).get("SPY")

    assert restored is not None
    assert restored.roe is None
