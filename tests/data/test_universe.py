"""qat.data.universe (spec M10): watchlist tables, benchmarks, and the
synthetic volume-based liquidity filter feeding resolve_watchlist."""

from __future__ import annotations

from qat.config import Settings
from qat.data import universe


def test_watchlist_tables_are_non_empty_for_both_markets():
    for market in ("US", "ASX"):
        assert market in universe.MARKET_BENCHMARKS
        for category in ("curated", "etf", "megacap"):
            assert len(universe.MARKET_WATCHLISTS[market][category]) > 0  # type: ignore[literal-required]


def test_synthetic_average_daily_volume_is_deterministic():
    assert universe.synthetic_average_daily_volume(
        "AAPL"
    ) == universe.synthetic_average_daily_volume("AAPL")
    assert universe.synthetic_average_daily_volume(
        "AAPL"
    ) != universe.synthetic_average_daily_volume("MSFT")


def test_resolve_watchlist_curated_matches_settings_default():
    settings = Settings(_env_file=None)
    assert universe.resolve_watchlist(settings) == ("SPY", "AAPL", "MSFT", "GOOGL")


def test_resolve_watchlist_uses_asx_curated_when_market_is_asx():
    settings = Settings(_env_file=None, market="ASX")
    assert universe.resolve_watchlist(settings) == settings.watchlist_curated_asx_tuple


def test_resolve_watchlist_megacap_category_uses_full_pool():
    settings = Settings(_env_file=None, watchlist_category="megacap", watchlist_max_symbols=200)
    resolved = universe.resolve_watchlist(settings)
    assert resolved == universe.MARKET_WATCHLISTS["US"]["megacap"]


def test_resolve_watchlist_caps_at_max_symbols():
    settings = Settings(_env_file=None, watchlist_category="megacap", watchlist_max_symbols=5)
    assert len(universe.resolve_watchlist(settings)) == 5


def test_resolve_watchlist_min_volume_filter_narrows_pool():
    settings = Settings(_env_file=None, watchlist_category="megacap", watchlist_max_symbols=200)
    unfiltered = universe.resolve_watchlist(settings)

    high_bar = Settings(
        _env_file=None,
        watchlist_category="megacap",
        watchlist_max_symbols=200,
        watchlist_min_avg_volume=15_000_000,
    )
    filtered = universe.resolve_watchlist(high_bar)

    assert len(filtered) < len(unfiltered)
    assert all(universe.synthetic_average_daily_volume(symbol) >= 15_000_000 for symbol in filtered)


def test_resolve_watchlist_falls_back_when_volume_filter_excludes_everything():
    settings = Settings(_env_file=None, watchlist_min_avg_volume=1_000_000_000)
    assert universe.resolve_watchlist(settings) == settings.watchlist_curated_us_tuple
