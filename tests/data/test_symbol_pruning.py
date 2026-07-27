"""One bad ticker must not mute the whole feed (spec M26).

Alpaca fails a multi-symbol request whole. `BRK-B` - Yahoo's spelling of
`BRK.B` - sat in the watchlist, so a hundred-symbol request returned HTTP 400
and no prices for any of them, every minute, for a whole session.
"""

from __future__ import annotations

import logging

from qat.data.alpaca_source import AlpacaMarketDataSource
from qat.data.symbols import canonical, from_yfinance, to_yfinance


class _PickyClient:
    """Rejects the batch if it contains any symbol Alpaca does not know."""

    def __init__(self, unknown: set[str]) -> None:
        self.unknown = unknown
        self.batches: list[list[str]] = []

    def get_stock_latest_trade(self, request_params):
        symbols = list(request_params.symbol_or_symbols)
        self.batches.append(symbols)
        bad = self.unknown.intersection(symbols)
        if bad:
            raise RuntimeError(f"invalid symbol: {sorted(bad)[0]}")
        return {}

    def get_stock_bars(self, request_params):  # pragma: no cover - unused here
        return {}


async def test_the_one_bad_symbol_is_found_and_dropped(caplog):
    watchlist = ["AAPL", "MSFT", "BRK-B", "NVDA", "AMZN", "META", "TSLA"]
    source = AlpacaMarketDataSource(client=_PickyClient({"BRK-B"}))

    with caplog.at_level(logging.ERROR, logger="qat.data.alpaca_source"):
        kept = await source._prune_unknown(watchlist)

    assert kept == ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA"]
    assert "BRK-B" in caplog.records[-1].getMessage()


async def test_several_bad_symbols_are_all_found() -> None:
    source = AlpacaMarketDataSource(client=_PickyClient({"BRK-B", "BF-B"}))

    kept = await source._prune_unknown(["AAPL", "BRK-B", "MSFT", "BF-B", "NVDA"])

    assert kept == ["AAPL", "MSFT", "NVDA"]


async def test_a_clean_watchlist_costs_exactly_one_probe() -> None:
    """The healthy path must not pay for the unhealthy one."""
    client = _PickyClient(set())
    source = AlpacaMarketDataSource(client=client)

    kept = await source._prune_unknown(["AAPL", "MSFT", "NVDA"])

    assert kept == ["AAPL", "MSFT", "NVDA"]
    assert len(client.batches) == 1


async def test_a_total_outage_does_not_empty_the_watchlist(caplog) -> None:
    """The distinction that keeps this from being dangerous.

    Every symbol failing means the network is down, the key is wrong or the
    feed is unentitled - not that a hundred tickers were delisted at once.
    Pruning on that evidence would silently leave nothing to trade.
    """
    source = AlpacaMarketDataSource(client=_PickyClient({"AAPL", "MSFT", "NVDA"}))

    with caplog.at_level(logging.ERROR, logger="qat.data.alpaca_source"):
        kept = await source._prune_unknown(["AAPL", "MSFT", "NVDA"])

    assert kept == ["AAPL", "MSFT", "NVDA"]
    assert "outage" in caplog.records[-1].getMessage()


def test_class_shares_translate_between_vendor_conventions() -> None:
    assert to_yfinance("BRK.B") == "BRK-B"
    assert from_yfinance("BRK-B") == "BRK.B"
    # Ordinary tickers are untouched in both directions.
    assert to_yfinance("AAPL") == "AAPL"
    assert from_yfinance("AAPL") == "AAPL"


def test_canonical_accepts_a_watchlist_typed_either_way() -> None:
    """Whichever convention someone types, the broker gets the one it takes."""
    assert canonical("brk-b") == "BRK.B"
    assert canonical(" BRK.B ") == "BRK.B"
    assert canonical("aapl") == "AAPL"


def test_the_default_watchlist_uses_the_broker_convention() -> None:
    """The regression itself: this is the line that cost a session.

    Checked across every built-in list rather than just the one that broke,
    because the next Yahoo-shaped ticker to be added would fail exactly the
    same way and nothing else in the app would notice until a session died.
    """
    from qat.data import sectors, universe

    every_symbol = [
        symbol
        for lists in (universe._WATCHLISTS_US, universe._WATCHLISTS_ASX)
        for symbols in lists.values()
        for symbol in symbols
    ]
    assert "BRK.B" in every_symbol
    hyphenated = [s for s in every_symbol if "-" in s]
    assert hyphenated == [], f"Yahoo-style tickers Alpaca will reject: {hyphenated}"

    # Every side table is keyed the same way, or the Screener silently loses
    # the entry and falls back to showing the bare symbol. Renaming the
    # watchlist alone missed the instrument-name map, and only a test caught
    # it - which is the argument for checking all three together rather than
    # the one that happened to break.
    from qat.data import instruments

    assert sectors.sector_for("BRK.B") == "Financials"
    assert instruments.name_for("BRK.B") != "BRK.B"
    for table in (sectors.SECTOR_BY_SYMBOL, instruments.INSTRUMENT_NAMES):
        assert not [key for key in table if "-" in key]
