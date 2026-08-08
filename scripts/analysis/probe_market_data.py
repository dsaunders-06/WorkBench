"""Does the feed change the position SIZE? Read-only.

Daily bars are requested on the same feed as live ticks, so with
`alpaca_data_feed=iex` every indicator is computed on IEX's ~4% of consolidated
volume. Closes differ by only 1-8 bps, which sounds harmless.

ATR does not use closes. It uses HIGH and LOW, and a single exchange sees a
narrower range than the consolidated tape by construction - it simply was not
there for the prints that made the extremes. ATR sets the stop distance, the
stop distance sets the risk per share, and risk per share sets the number of
shares. So a narrower ATR does not make the app slightly wrong about
volatility; it makes every position LARGER.

Uses the application's own compute_atr, so this measures what the app would
actually do rather than a reimplementation of it.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, r"C:\Claude Programming\src")

import pandas as pd  # noqa: E402
from alpaca.data.enums import Adjustment, DataFeed  # noqa: E402
from alpaca.data.historical.stock import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.data.features import compute_atr  # noqa: E402
from qat.security import get_secret  # noqa: E402

HELD = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]
BARS = 60

client = StockHistoricalDataClient(
    api_key=get_secret(API_KEY_SECRET_NAME),
    secret_key=get_secret(SECRET_KEY_SECRET_NAME),
)


def frames(feed: DataFeed) -> dict[str, pd.DataFrame]:
    request = StockBarsRequest(
        symbol_or_symbols=HELD,
        timeframe=TimeFrame.Day,
        start=datetime.now(UTC) - timedelta(days=int(BARS * 1.5) + 7),
        feed=feed,
        adjustment=Adjustment.ALL,
    )
    data = client.get_stock_bars(request).data
    out = {}
    for symbol, bars in data.items():
        out[symbol] = pd.DataFrame(
            {
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
            }
        )
    return out


iex, sip = frames(DataFeed.IEX), frames(DataFeed.SIP)

print(
    f"{'sym':<7}{'ATR iex':>10}{'ATR sip':>10}{'iex/sip':>9}"
    f"{'stop dist':>11}{'shares iex':>12}{'shares sip':>12}{'oversize':>10}"
)
print("-" * 81)

ratios, oversizes = [], []
EQUITY, RISK_PCT, ATR_MULT = 101_245.0, 0.005, 2.0
for symbol in HELD:
    if symbol not in iex or symbol not in sip:
        continue

    def atr_of(frame: pd.DataFrame) -> float:
        return float(compute_atr(frame["high"], frame["low"], frame["close"]).iloc[-1])

    a_iex, a_sip = atr_of(iex[symbol]), atr_of(sip[symbol])
    if not a_sip:
        continue
    ratio = a_iex / a_sip
    # The sizing chain: risk budget / (ATR x multiple) = shares.
    budget = EQUITY * RISK_PCT
    shares_iex = budget / (a_iex * ATR_MULT)
    shares_sip = budget / (a_sip * ATR_MULT)
    oversize = (shares_iex / shares_sip - 1) * 100
    ratios.append(ratio)
    oversizes.append(oversize)
    print(
        f"{symbol:<7}{a_iex:>10.3f}{a_sip:>10.3f}{ratio:>9.3f}"
        f"{a_sip * ATR_MULT:>11.2f}{shares_iex:>12.1f}{shares_sip:>12.1f}{oversize:>9.1f}%"
    )

if ratios:
    ratios.sort()
    oversizes.sort()
    print("-" * 81)
    print(f"  median ATR ratio (iex/sip): {ratios[len(ratios) // 2]:.3f}")
    print(f"  median position oversize  : {oversizes[len(oversizes) // 2]:+.1f}%")
    print(f"  worst  position oversize  : {max(oversizes):+.1f}%")
    print()
    print("  A ratio below 1.000 means IEX sees a NARROWER range, so the stop is")
    print("  placed closer, so more shares fit the same risk budget.")
