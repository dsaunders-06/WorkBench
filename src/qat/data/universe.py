"""Market/watchlist universe (spec M10): curated/ETF/mega-cap ticker lists
per market, benchmark symbols, and a deterministic synthetic average-daily-
volume figure used as a liquidity filter.

The US/ASX curated+ETF+mega-cap lists are ported directly from the original
ShareTrader app's WATCHLISTS_US / WATCHLISTS_ASX
(C:\\ShareTrader\\claude_market_dashboard.py, lines 306-362) rather than
re-derived - same caveat as that source: static snapshots, not a live pull of
official index membership, so they'll drift from real market composition
over time (mergers/delistings, index reweighting). Update the tuples below if
you want them current.

average_daily_volume uses the same seeded-per-symbol pattern as
MockFundamentalsSource._generate (data/fundamentals.py) - deterministic, so
watchlist resolution is reproducible, and symbol-agnostic (works the same for
plain US tickers and ".AX"-suffixed ASX ones since nothing here is
currency-aware, matching the mock-everywhere stance used throughout).
"""

from __future__ import annotations

import random
from typing import Literal

from qat.config import Settings

Market = Literal["US", "ASX"]
WatchlistCategory = Literal["curated", "etf", "megacap"]

MARKET_BENCHMARKS: dict[Market, str] = {"US": "SPY", "ASX": "STW.AX"}

_WATCHLISTS_US: dict[WatchlistCategory, tuple[str, ...]] = {
    "curated": ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"),
    "etf": ("SPY", "QQQ"),
    "megacap": (
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "GOOG",
        "META",
        "AVGO",
        "TSLA",
        "BRK.B",
        "LLY",
        "JPM",
        "V",
        "UNH",
        "XOM",
        "MA",
        "COST",
        "HD",
        "PG",
        "JNJ",
        "NFLX",
        "ABBV",
        "BAC",
        "KO",
        "MRK",
        "ORCL",
        "CRM",
        "ADBE",
        "AMD",
        "PEP",
        "TMO",
        "ABT",
        "CSCO",
        "ACN",
        "MCD",
        "DHR",
        "LIN",
        "WFC",
        "TXN",
        "IBM",
        "GE",
        "CAT",
        "VZ",
        "CMCSA",
        "PM",
        "NKE",
        "UNP",
        "HON",
        "QCOM",
        "INTU",
        "WMT",
        "DIS",
        "NOW",
        "INTC",
        "BA",
        "RTX",
        "LOW",
        "SBUX",
        "MDT",
        "GS",
        "MS",
        "BLK",
        "AXP",
        "SPGI",
        "SCHW",
        "C",
        "PGR",
        "PLTR",
        "AMAT",
        "MU",
        "ADI",
        "LRCX",
        "KLAC",
        "PANW",
        "CRWD",
        "ISRG",
        "VRTX",
        "REGN",
        "GILD",
        "BMY",
        "PFE",
        "CVS",
        "SYK",
        "DE",
        "LMT",
        "NOC",
        "UPS",
        "MMM",
        "DUK",
        "SO",
        "NEE",
        "SHW",
        "FCX",
        "NEM",
        "TJX",
        "BKNG",
        "MAR",
        "GM",
        "F",
        "MO",
    ),
}

# ASX tickers use the ".AX" suffix, matching ShareTrader's convention.
_WATCHLISTS_ASX: dict[WatchlistCategory, tuple[str, ...]] = {
    "curated": ("BHP.AX", "CBA.AX", "CSL.AX", "NAB.AX", "WBC.AX"),
    "etf": ("STW.AX", "IOZ.AX"),
    "megacap": (
        "BHP.AX",
        "CBA.AX",
        "CSL.AX",
        "NAB.AX",
        "WBC.AX",
        "ANZ.AX",
        "WES.AX",
        "WOW.AX",
        "TLS.AX",
        "RIO.AX",
        "FMG.AX",
        "MQG.AX",
        "GMG.AX",
        "TCL.AX",
        "WDS.AX",
        "STO.AX",
        "QBE.AX",
        "SUN.AX",
        "ALL.AX",
        "COL.AX",
        "XRO.AX",
        "REA.AX",
        "COH.AX",
        "RMD.AX",
        "APA.AX",
        "ORG.AX",
        "AMC.AX",
        "BXB.AX",
        "IAG.AX",
        "QAN.AX",
        "JHX.AX",
        "NST.AX",
        "S32.AX",
        "MIN.AX",
        "PLS.AX",
        "TWE.AX",
        "SCG.AX",
        "MGR.AX",
        "GPT.AX",
        "VCX.AX",
        "ASX.AX",
        "SEK.AX",
        "CPU.AX",
        "ORI.AX",
        "AGL.AX",
        "BEN.AX",
        "SGP.AX",
        "LLC.AX",
        "IGO.AX",
        "WOR.AX",
        "WTC.AX",
        "TNE.AX",
        "NXT.AX",
        "CAR.AX",
        "DHG.AX",
        "PME.AX",
        "RHC.AX",
        "SHL.AX",
        "FPH.AX",
        "EDV.AX",
        "A2M.AX",
        "BKW.AX",
        "ILU.AX",
        "LYC.AX",
        "EVN.AX",
        "WHC.AX",
        "NHC.AX",
        "KAR.AX",
        "AWC.AX",
        "BSL.AX",
        "ORA.AX",
        "CIA.AX",
        "DXS.AX",
        "CHC.AX",
        "ARF.AX",
        "GOZ.AX",
        "NSR.AX",
        "HVN.AX",
        "JBH.AX",
        "SUL.AX",
        "PMV.AX",
        "FLT.AX",
        "WEB.AX",
        "DMP.AX",
        "TAH.AX",
        "LOV.AX",
        "BOQ.AX",
        "BWP.AX",
        "AMP.AX",
        "MPL.AX",
        "NHF.AX",
        "HUB.AX",
        "PNI.AX",
        "MFG.AX",
        "GQG.AX",
        "CGF.AX",
        "AZJ.AX",
        "SVW.AX",
        "IPL.AX",
        "ALQ.AX",
    ),
}

MARKET_WATCHLISTS: dict[Market, dict[WatchlistCategory, tuple[str, ...]]] = {
    "US": _WATCHLISTS_US,
    "ASX": _WATCHLISTS_ASX,
}


def average_daily_volume(symbol: str) -> int:
    """Deterministic synthetic average daily volume (shares/day), used as a
    liquidity filter since no real market-data vendor backs this app."""
    rng = random.Random(f"volume:{symbol}")  # nosec B311 - deterministic synthetic data, not crypto
    return rng.randint(10_000, 20_000_000)


def resolve_watchlist(settings: Settings) -> tuple[str, ...]:
    """category -> candidate pool -> min-volume filter -> size cap (spec M10)."""
    if settings.watchlist_category == "curated":
        candidates = (
            settings.watchlist_curated_us_tuple
            if settings.market == "US"
            else settings.watchlist_curated_asx_tuple
        )
    else:
        candidates = MARKET_WATCHLISTS[settings.market][settings.watchlist_category]

    filtered = tuple(
        symbol
        for symbol in candidates
        if average_daily_volume(symbol) >= settings.watchlist_min_avg_volume
    )
    if not filtered:
        # The volume filter excluded every candidate - fall back to the
        # unfiltered pool rather than leaving the app with an empty watchlist.
        filtered = candidates

    return filtered[: settings.watchlist_max_symbols]
