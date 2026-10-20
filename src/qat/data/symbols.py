"""ASX symbol normalisation at vendor and IBKR boundaries (spec M26).

QAT stores ``.AX`` symbols. Legacy ASX inputs such as ``BHP-AX`` are accepted
and normalised to ``BHP.AX`` before positions, fills and reconciliation use
them. IBKR contract symbols omit the exchange suffix and are restored on
the return path.
"""

from __future__ import annotations

# Legacy ASX watchlists may spell the exchange suffix with a hyphen. Keep that
# accepted input form while removing the retired US class-share translation.
_ASX_INPUT_SUFFIX = "-AX"

# Yahoo expects ``.AX`` for an ASX listing. Keep the exchange suffix explicit
# rather than inferring it from the shape of the last component.
_EXCHANGE_SUFFIXES = (".AX",)


def _split_exchange(symbol: str) -> tuple[str, str]:
    """`BHP.AX` -> `("BHP", ".AX")`, `BRK.B` -> `("BRK.B", "")`."""
    upper = symbol.upper()
    for suffix in _EXCHANGE_SUFFIXES:
        if upper.endswith(suffix):
            return symbol[: -len(suffix)], symbol[-len(suffix) :]
    return symbol, ""


def to_yfinance(symbol: str) -> str:
    """Canonical (broker) form -> the form Yahoo Finance expects.

    The exchange suffix is preserved: Yahoo wants `.AX` and translating it is
    a lookup failure that degrades to synthetic prices rather than to an error.
    """
    return symbol


def from_yfinance(symbol: str) -> str:
    """Yahoo form -> canonical. Used when reading vendor-shaped input back."""
    if symbol.upper().endswith(_ASX_INPUT_SUFFIX):
        return symbol[: -len(_ASX_INPUT_SUFFIX)] + ".AX"
    return symbol


def to_ibkr(symbol: str) -> str:
    """Canonical form -> the form IBKR expects: the BASE symbol, no exchange.

    IBKR learns the venue from the contract's `exchange`, `currency` and
    `primaryExchange` fields, never from a suffix, and it does not merely
    ignore one it does not want. Measured against the live paper Gateway on
    19 August: `Stock("BHP.AX", "SMART", ...)` returns error 200, "no security
    definition has been found", in AUD as well as USD. Every ASX order the
    application could place would have been rejected outright (M96).

    `_split_exchange` lists the ASX exchange suffix rather than stripping
    arbitrary dotted components.
    """
    base, _ = _split_exchange(symbol)
    return base


# Which suffix each market's symbols carry in the app's own form. IBKR speaks
# the base symbol and learns the venue from the contract, so the suffix has to
# be removed on the way out and put back on the way in (M96, Task 2).
_MARKET_SUFFIX = {"ASX": ".AX"}


def from_ibkr(symbol: str, market: str = "ASX") -> str:
    """IBKR's form -> canonical, the return leg of `to_ibkr`.

    The app tracks `BHP.AX` and IBKR answers `BHP`. A fill returned as `BHP`
    matches no tracked position: the `symbols` filter drops it and the OMS
    never recognises it, so a stop firing at the broker still goes unrecorded -
    the exact outcome `recent_fills` exists to prevent, reached by a different
    road.

    M26's rule is the reason this is a pair rather than a one-way convenience:
    a symbol that round-trips wrongly against the broker is a reconciliation
    mismatch and a halted session.
    """
    if market != "ASX":
        raise ValueError(f"unsupported market: {market}")
    suffix = _MARKET_SUFFIX[market]
    if not suffix:
        return symbol
    base, existing = _split_exchange(symbol)
    # Idempotent: a symbol that already carries its suffix must not gain a
    # second one, because `BHP.AX.AX` fails silently as a lookup miss.
    return base + (existing or suffix)


def canonical(symbol: str) -> str:
    """Normalise a symbol from any source into the app's internal form.

    Uppercased, with the ASX exchange suffix normalised to ``.AX``.
    """
    return from_yfinance(symbol.strip().upper())


__all__ = ["canonical", "from_ibkr", "from_yfinance", "to_ibkr", "to_yfinance"]
