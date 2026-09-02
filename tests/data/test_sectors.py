"""Real sector classifications (spec M12).

MockFundamentalsSource used to pick a sector at random per symbol, which
rendered AAPL as "Materials" in the Screener - deterministic, but wrong.
"""

from __future__ import annotations

import pytest

from qat.data import sectors
from qat.data.fundamentals import SECTORS, MockFundamentalsSource


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("AAPL", "Information Technology"),
        ("MSFT", "Information Technology"),
        ("XOM", "Energy"),
        ("JPM", "Financials"),
        ("SPY", "Index ETF"),
        ("BHP.AX", "Materials"),
        ("CBA.AX", "Financials"),
        ("CSL.AX", "Health Care"),
    ],
)
def test_known_symbols_map_to_their_real_sector(symbol, expected):
    assert sectors.sector_for(symbol) == expected


def test_lookup_is_case_insensitive():
    assert sectors.sector_for("aapl") == sectors.sector_for("AAPL")


def test_unknown_symbol_is_reported_as_unknown_not_invented():
    assert sectors.sector_for("NOTATICKER") == sectors.UNKNOWN_SECTOR


async def test_fundamentals_uses_the_real_sector():
    source = MockFundamentalsSource(seed=1)

    apple = await source.get_fundamentals("AAPL")
    bhp = await source.get_fundamentals("BHP.AX")

    assert apple.sector == "Information Technology"
    assert bhp.sector == "Materials"


async def test_synthetic_test_symbols_still_work():
    source = MockFundamentalsSource(seed=1)

    snapshot = await source.get_fundamentals("SYM0")

    assert snapshot.sector == sectors.UNKNOWN_SECTOR
    assert snapshot.symbol == "SYM0"


def test_screener_filter_options_cover_every_value_sector_for_can_return():
    """The Screener's dropdown is built from SECTORS; a value it cannot offer
    would be unfilterable."""
    assert set(sectors.SECTOR_BY_SYMBOL.values()) <= set(SECTORS)
    assert sectors.UNKNOWN_SECTOR in SECTORS


def test_watchlist_symbols_all_have_sectors() -> None:
    """Every symbol the app will actually TRADE must have a sector mapping.

    ⚠️ THIS EXISTS BECAUSE M161 WIDENED THE WATCHLIST WITHOUT IT. Five names
    (ALX, CWY, SDF, SOL, ANN) were added to the megacap list and not to
    `SECTOR_BY_SYMBOL`, so for a day they were tradable with the 30% sector
    concentration cap SKIPPED entirely - `signal_bridge` reads
    `SECTOR_BY_SYMBOL.get`, deliberately, so unmapped means "no cap applies"
    rather than a shared "Unknown" bucket.

    Nothing caught it. The app's own warning only fires when a SIGNAL for the
    symbol reaches the bridge, and none did that day; the operator found it in
    the Screener, which rendered a ticker with an empty Sector column.

    ⚠️ Scoped to the RESOLVED watchlist, not to every symbol the app knows.
    `IOZ.AX` is mapped and legitimately unwatched - it belongs to the `etf`
    category - and asserting over everything would fail on it for no reason.

    The reverse leak is deliberately NOT asserted: AWC, BKW, DHG, IPL, NSR and
    SVW are still mapped after M110 pruned them from the watchlist as dead.
    Harmless - a lookup nobody queries - and failing on it would only tempt
    someone to delete history that costs nothing to keep.
    """
    from qat.config import Settings
    from qat.data.universe import resolve_watchlist

    settings = Settings(
        _env_file=None,
        market="ASX",
        watchlist_category="megacap",
        watchlist_max_symbols=200,
    )
    watched = resolve_watchlist(settings)
    unmapped = sorted(s for s in watched if s not in sectors.SECTOR_BY_SYMBOL)
    assert not unmapped, (
        f"{len(unmapped)} watchlist symbol(s) have no sector mapping, so the sector "
        f"concentration cap will not apply to them: {unmapped}. "
        f"Add them to qat.data.sectors.SECTOR_BY_SYMBOL."
    )
