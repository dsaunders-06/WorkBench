"""An ASX ticker must survive the trip to Yahoo and back (M26, extended).

`to_yfinance` replaced every dot with a hyphen. That is right for US class
shares - Alpaca writes `BRK.B`, Yahoo writes `BRK-B` - and wrong for every ASX
listing, where `.AX` is the exchange suffix Yahoo itself requires. `BHP.AX`
went out as `BHP-AX` and came back 404.

**The 404 was not the damage.** `YFinanceHistorySource` falls back to SYNTHETIC
bars when a real fetch returns nothing, so the caller received 500 fabricated
daily bars with a warning in the log and no exception. A research run on that
data would have produced expectancy figures, rail bindings and an ablation
verdict - all of them invented, and all of them plausible.

The module's own docstring already scoped the rule correctly: the dot/hyphen
divergence is *"the only systematic divergence between the two in US equities;
anything else is a genuinely different listing and must not be papered over
here."* `.AX` is a different listing.
"""

from __future__ import annotations

import pytest

from qat.data.symbols import canonical, from_ibkr, from_yfinance, to_ibkr, to_yfinance


def test_builtin_asx_watchlists_and_side_tables_use_canonical_symbols() -> None:
    """Preserve the ASX half of the retired Alpaca symbol-pruning guard."""
    from qat.data import instruments, sectors, universe

    symbols = [symbol for entries in universe._WATCHLISTS_ASX.values() for symbol in entries]
    assert not [symbol for symbol in symbols if "-" in symbol]
    assert all(canonical(symbol) == symbol for symbol in symbols)
    for table in (sectors.SECTOR_BY_SYMBOL, instruments.INSTRUMENT_NAMES):
        assert not [symbol for symbol in table if symbol.endswith("-AX")]


@pytest.mark.parametrize("symbol", ["BHP.AX", "CBA.AX", "STW.AX", "CSL.AX"])
def test_an_asx_ticker_reaches_yahoo_unchanged(symbol: str):
    """`.AX` is what Yahoo wants. Rewriting it to `-AX` is a 404, and a 404 is a
    silent switch to synthetic data."""
    assert to_yfinance(symbol) == symbol


def test_the_round_trip_is_stable_for_asx():
    for symbol in ("BHP.AX", "STW.AX"):
        assert from_yfinance(to_yfinance(symbol)) == symbol


def test_canonical_does_not_mangle_an_asx_suffix():
    """A watchlist typed by hand must not become `BHP.AX` -> `BHP.AX` via a
    hyphen that was never there, nor `BHP-AX` -> `BHP.AX` losing the market."""
    assert canonical("bhp.ax") == "BHP.AX"
    assert canonical("BHP.AX") == "BHP.AX"


@pytest.mark.parametrize(
    "raw,canonical_symbol",
    [
        ("BHP-AX", "BHP.AX"),
        ("cba-ax", "CBA.AX"),
        ("STW-AX", "STW.AX"),
        ("TAH-AX", "TAH.AX"),
    ],
)
def test_hyphenated_asx_input_keeps_its_existing_normalisation(raw: str, canonical_symbol: str):
    assert canonical(raw) == canonical_symbol
    assert from_yfinance(raw.upper()) == canonical_symbol
    assert to_yfinance(canonical_symbol) == canonical_symbol
    assert to_ibkr(canonical(raw)) == canonical_symbol.removesuffix(".AX")


def test_ibkr_asx_symbol_conversion_is_idempotent_and_default_is_asx():
    assert from_ibkr("BHP", market="ASX") == "BHP.AX"
    assert from_ibkr("BHP.AX", market="ASX") == "BHP.AX"
    assert from_ibkr("BHP") == "BHP.AX"


def test_ibkr_symbol_conversion_refuses_an_unsupported_market():
    with pytest.raises(ValueError, match="unsupported market"):
        from_ibkr("AAPL", market="US")
