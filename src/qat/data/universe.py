"""Market/watchlist universe (spec M10): curated/ETF/mega-cap ticker lists
per market, benchmark symbols, and a deterministic synthetic average-daily-
volume figure that LOOKS like a liquidity filter and is not one (M134).

The US/ASX curated+ETF+mega-cap lists are ported directly from the original
ShareTrader app's WATCHLISTS_US / WATCHLISTS_ASX
(C:\\ShareTrader\\claude_market_dashboard.py, lines 306-362) rather than
re-derived - same caveat as that source: static snapshots, not a live pull of
official index membership, so they'll drift from real market composition
over time (mergers/delistings, index reweighting). Update the tuples below if
you want them current.

synthetic_average_daily_volume uses the same seeded-per-symbol pattern as
MockFundamentalsSource._generate (data/fundamentals.py) - deterministic, so
watchlist resolution is reproducible, and symbol-agnostic (works the same for
plain US tickers and ".AX"-suffixed ASX ones since nothing here is
currency-aware, matching the mock-everywhere stance used throughout).
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from qat.config import Settings

Market = Literal["US", "ASX"]
logger = logging.getLogger(__name__)

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
        "PME.AX",
        "RHC.AX",
        "SHL.AX",
        "FPH.AX",
        "EDV.AX",
        "A2M.AX",
        "ILU.AX",
        "LYC.AX",
        "EVN.AX",
        "WHC.AX",
        "NHC.AX",
        "KAR.AX",
        "BSL.AX",
        "ORA.AX",
        "CIA.AX",
        "DXS.AX",
        "CHC.AX",
        "ARF.AX",
        "GOZ.AX",
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
        "ALQ.AX",
        # --- added 1 September 2026, taking the list 94 -> 99 -------------
        #
        # ⚠️ 94 WAS THE LIST'S LENGTH, NOT A LIMIT. The list shipped at 100;
        # M110 pruned six that returned no real bars (AWC, BKW, DHG, IPL, NSR,
        # SVW) and the remainder read as a cap it never was.
        # `watchlist_max_symbols` is 100 and was not binding at 94.
        #
        # ⚠️ AND "101" WAS OUR OWN COUNT, NOT A VENDOR THRESHOLD. The
        # 20 August yfinance block happened while polling 101 - the unpruned
        # 100 plus the STW.AX benchmark - so it says how many we asked for and
        # nothing about where the vendor's limit is. 99 + STW.AX = 100 polled,
        # which stays below the one count ever observed to fail while using the
        # headroom the cap already allowed.
        #
        # ⚠️ VERIFIED BEFORE ADDING, because M110 is what happens otherwise.
        # Each returned a full 129 daily bars over six months with real volume,
        # and each passes `synthetic_average_daily_volume`. Chosen as the top
        # five of fourteen candidates by REAL turnover (price x 60-day average
        # volume), which is the liquidity screen this app does not otherwise
        # have - the configured filter runs on a synthetic volume derived from
        # the ticker string.
        #
        #   ALX.AX  $43.5M/day   toll roads
        #   CWY.AX  $37.4M/day   waste management - sector not otherwise held
        #   SDF.AX  $33.3M/day   insurance broking
        #   SOL.AX  $21.5M/day   diversified investment house
        #   ANN.AX  $20.2M/day   healthcare products
        "ALX.AX",
        "CWY.AX",
        "SDF.AX",
        "SOL.AX",
        "ANN.AX",
    ),
}

MARKET_WATCHLISTS: dict[Market, dict[WatchlistCategory, tuple[str, ...]]] = {
    "US": _WATCHLISTS_US,
    "ASX": _WATCHLISTS_ASX,
}


def synthetic_average_daily_volume(symbol: str) -> int:
    """A DETERMINISTIC RANDOM NUMBER, not a liquidity measurement (M134).

    Named `average_daily_volume` until 21 August, which is what a caller reads
    and what `QAT_WATCHLIST_MIN_AVG_VOLUME` appears to screen on. It has never
    been volume: it is `random.Random(symbol).randint(10_000, 20_000_000)`, so
    the filter admits or rejects a symbol on the hash of its ticker.

    Harmless across the 99 ASX megacaps, which are liquid by construction —
    none is excluded at the default threshold, and the five added on
    1 September were checked against it explicitly rather than assumed.
    Actively misleading the moment the universe widens beyond them, because it
    looks like a liquidity rail and is not one. ⚠️ That is why those five were
    picked on REAL turnover: this filter would have admitted anything.

    Left in place rather than deleted: removing it would silently widen the
    universe, and the setting is documented. Renamed so no call site can read
    it as real, and `resolve_watchlist` says so out loud once.
    """
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
        if synthetic_average_daily_volume(symbol) >= settings.watchlist_min_avg_volume
    )
    if len(filtered) != len(candidates):
        # Said once, at the point it changes the answer (M134). A reader seeing
        # symbols disappear would otherwise conclude a liquidity rail had
        # judged them, and no such rail exists.
        logger.warning(
            "%d of %d symbol(s) were dropped by QAT_WATCHLIST_MIN_AVG_VOLUME, which screens "
            "on a SYNTHETIC volume derived from the ticker string - not on real liquidity. "
            "See universe.synthetic_average_daily_volume.",
            len(candidates) - len(filtered),
            len(candidates),
        )
    if not filtered:
        # The volume filter excluded every candidate - fall back to the
        # unfiltered pool rather than leaving the app with an empty watchlist.
        filtered = candidates

    return filtered[: settings.watchlist_max_symbols]


# --- what may actually be entered (M109) -----------------------------------
#
# Derived in one place because two readers need the same answer: the hand-run
# pre-flight, and the app announcing itself at startup. M106 gave the
# pre-flight its own copy of this arithmetic and it was the only reader, which
# is exactly why nobody learned anything on 20 August - the pre-flight is
# optional and the session is not.


@dataclass(frozen=True)
class TradableUniverse:
    """The watchlist split by what the entry allow list permits.

    `refused` is the interesting one. Those symbols are polled, evaluated and
    may signal - and every entry they produce is thrown away. They cost a feed
    subscription and produce nothing, and until M109 they did it silently.
    """

    watched: tuple[str, ...]
    tradable: tuple[str, ...]
    refused: tuple[str, ...]
    unwatched: tuple[str, ...]
    restricted: bool


def describe_tradable(watchlist: Iterable[str], allowed: set[str] | None) -> TradableUniverse:
    """Split the watchlist by the allow list. `allowed=None` is no restriction.

    None and an empty set mean opposite things here, as they do in
    Settings.entry_allow_list_set: None permits everything, and an empty set
    would permit nothing. Only the first is a valid configuration.
    """
    watched = tuple(sorted({s.strip().upper() for s in watchlist if s.strip()}))
    if allowed is None:
        return TradableUniverse(
            watched=watched,
            tradable=watched,
            refused=(),
            unwatched=(),
            restricted=False,
        )
    permitted = {s.strip().upper() for s in allowed if s.strip()}
    return TradableUniverse(
        watched=watched,
        tradable=tuple(s for s in watched if s in permitted),
        refused=tuple(s for s in watched if s not in permitted),
        unwatched=tuple(sorted(permitted - set(watched))),
        restricted=True,
    )


def allow_list_banner(universe: TradableUniverse) -> str | None:
    """The startup line, or None when no allow list is in force.

    Announced whether or not anything is wrong. A banner that appears only on
    a bad configuration teaches its reader that silence means "fine", and then
    the one session it stays quiet on is the one nobody checks - the same
    argument M108 made for the session-started line.

    It names the tradable symbols rather than only counting them because the
    20 August error was about IDENTITY, not arithmetic: three permitted names
    is a perfectly ordinary machinery-test setting, and the only thing wrong
    with BHP/CBA/STW was that they were yesterday's three.
    """
    if not universe.restricted:
        return None
    shown = ", ".join(universe.tradable[:10]) + (" ..." if len(universe.tradable) > 10 else "")
    parts = [
        f"ENTRY ALLOW LIST ACTIVE - {len(universe.tradable)} of {len(universe.watched)} "
        f"watched symbol(s) may be entered: {shown or '(none)'}."
    ]
    if universe.refused:
        parts.append(
            f"The other {len(universe.refused)} are polled and evaluated, and every entry "
            f"they signal will be REFUSED. Exits are never gated, so anything already held "
            f"can still leave."
        )
    else:
        parts.append("Exits are never gated.")
    if universe.unwatched:
        parts.append(
            f"{len(universe.unwatched)} permitted symbol(s) are not watched at all and can "
            f"never trade: {', '.join(universe.unwatched[:10])}. That is a dead setting - "
            f"usually an allow list left behind by a watchlist change."
        )
    return " ".join(parts)
