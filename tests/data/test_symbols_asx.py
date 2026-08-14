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

from qat.data.symbols import canonical, from_yfinance, to_yfinance


@pytest.mark.parametrize("symbol", ["BHP.AX", "CBA.AX", "STW.AX", "CSL.AX"])
def test_an_asx_ticker_reaches_yahoo_unchanged(symbol: str):
    """`.AX` is what Yahoo wants. Rewriting it to `-AX` is a 404, and a 404 is a
    silent switch to synthetic data."""
    assert to_yfinance(symbol) == symbol


def test_a_us_class_share_is_still_translated():
    """The case the module was written for, unchanged."""
    assert to_yfinance("BRK.B") == "BRK-B"


def test_the_round_trip_is_stable_for_both_markets():
    for symbol in ("BHP.AX", "STW.AX", "AAPL"):
        assert from_yfinance(to_yfinance(symbol)) == symbol
    # BRK.B is the deliberate exception: it goes out hyphenated and comes back
    # dotted, which is the whole point of having a canonical form.
    assert from_yfinance(to_yfinance("BRK.B")) == "BRK.B"


def test_canonical_does_not_mangle_an_asx_suffix():
    """A watchlist typed by hand must not become `BHP.AX` -> `BHP.AX` via a
    hyphen that was never there, nor `BHP-AX` -> `BHP.AX` losing the market."""
    assert canonical("bhp.ax") == "BHP.AX"
    assert canonical("BHP.AX") == "BHP.AX"
