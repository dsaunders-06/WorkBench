"""One canonical symbol form, translated at each vendor boundary (spec M26).

Class-share tickers are written differently by different vendors: Alpaca and
most US brokers use a dot (``BRK.B``), Yahoo Finance uses a hyphen (``BRK-B``).
The watchlist carried the Yahoo form, and that single character cost an entire
trading session.

It was not a degraded symbol. Alpaca's latest-trade endpoint rejects the
*whole request* with HTTP 400 when any symbol in it is unknown, so one bad
entry in a hundred-symbol batch returned nothing for all hundred. Five empty
polls later the feed shut itself down, and the session ran six hours seventeen
minutes with no market data at all - strategies, risk engine and execution
path all healthy and never given a price to act on.

The lesson is not "fix BRK-B". It is that a symbol has no single correct
spelling, so the app needs one internal form and a translation at each
boundary. Canonical here is the **broker's** form, because that is what
positions, fills and reconciliation all speak: a symbol that round-trips
wrongly against the broker is a reconciliation mismatch and a halted session,
which is worse than a missing fundamentals lookup.
"""

from __future__ import annotations

# Yahoo writes class shares with a hyphen where the brokers use a dot. This is
# the only systematic divergence between the two in US equities; anything else
# is a genuinely different listing and must not be papered over here.
_YFINANCE_CLASS_SEPARATOR = "-"
_CANONICAL_CLASS_SEPARATOR = "."


def to_yfinance(symbol: str) -> str:
    """Canonical (broker) form -> the form Yahoo Finance expects."""
    return symbol.replace(_CANONICAL_CLASS_SEPARATOR, _YFINANCE_CLASS_SEPARATOR)


def from_yfinance(symbol: str) -> str:
    """Yahoo form -> canonical. Used when reading vendor-shaped input back."""
    return symbol.replace(_YFINANCE_CLASS_SEPARATOR, _CANONICAL_CLASS_SEPARATOR)


def canonical(symbol: str) -> str:
    """Normalise a symbol from any source into the app's internal form.

    Uppercased and hyphen-to-dot, so a watchlist typed by hand in either
    convention reaches the broker in the one it accepts.
    """
    return from_yfinance(symbol.strip().upper())


__all__ = ["canonical", "from_yfinance", "to_yfinance"]
