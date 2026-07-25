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
