"""Which feed does the broker's own position mark come from? Read-only.

M66's fix needs a current price. The obvious source is Alpaca's position object,
which already carries `current_price` in every response the app makes anyway.

But the market-data finding says this account's app-side feed is IEX, ~4% narrow
on ranges. If the broker's mark were also IEX, fixing M66 that way would bake
the bias into the risk cap. If it is consolidated, the fix is free of that
question entirely - which would decouple M66 from the feed decision.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, r"C:\Claude Programming\src")

from alpaca.data.enums import Adjustment, DataFeed  # noqa: E402
from alpaca.data.historical.stock import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402
from alpaca.trading.client import TradingClient  # noqa: E402

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

key, secret = get_secret(API_KEY_SECRET_NAME), get_secret(SECRET_KEY_SECRET_NAME)
trading = TradingClient(api_key=key, secret_key=secret, paper=True)
data = StockHistoricalDataClient(api_key=key, secret_key=secret)

positions = trading.get_all_positions()
symbols = [p.symbol for p in positions]


def closes(feed: DataFeed) -> dict[str, float]:
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=datetime.now(UTC) - timedelta(days=10),
        feed=feed,
        adjustment=Adjustment.ALL,
    )
    return {sym: bars[-1].close for sym, bars in data.get_stock_bars(request).data.items()}


iex, sip = closes(DataFeed.IEX), closes(DataFeed.SIP)

print(f"{'sym':<7}{'position mark':>15}{'iex close':>12}{'sip close':>12}   matches")
print("-" * 62)
votes = {"iex": 0, "sip": 0, "neither": 0}
for position in sorted(positions, key=lambda p: p.symbol):
    mark = float(position.current_price)
    i, s = iex.get(position.symbol), sip.get(position.symbol)
    if i is None or s is None:
        continue
    if abs(mark - s) < 0.005:
        which, key_ = "SIP (consolidated)", "sip"
    elif abs(mark - i) < 0.005:
        which, key_ = "IEX", "iex"
    else:
        which, key_ = "neither", "neither"
    votes[key_] += 1
    print(f"{position.symbol:<7}{mark:>15.2f}{i:>12.2f}{s:>12.2f}   {which}")

print("-" * 62)
print(f"  matches SIP: {votes['sip']}   matches IEX: {votes['iex']}   neither: {votes['neither']}")
print()
if votes["sip"] and not votes["iex"]:
    print("  The broker's own mark is the CONSOLIDATED tape. Taking the price from")
    print("  Position.current_price therefore fixes M66 without inheriting the IEX")
    print("  bias, and without needing the feed decision made first.")
