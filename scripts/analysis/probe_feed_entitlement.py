"""Is SIP actually PAID for on this account, or just free historical?

Read-only.

Alpaca's free tier serves SIP history older than 15 minutes. So a successful
query for last week's daily bars proves nothing about entitlement - only a
request for RECENT data separates the two, because that is exactly what the
free tier withholds.

This matters because the whole market-data question reduces to "do we already
have the good feed". Getting it wrong in the optimistic direction would mean
building on a feed that fails the moment it is asked for something live.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, r"C:\Claude Programming\src")

from alpaca.data.enums import DataFeed  # noqa: E402
from alpaca.data.historical.stock import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import (  # noqa: E402
    StockBarsRequest,
    StockLatestTradeRequest,
)
from alpaca.data.timeframe import TimeFrame  # noqa: E402

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

client = StockHistoricalDataClient(
    api_key=get_secret(API_KEY_SECRET_NAME),
    secret_key=get_secret(SECRET_KEY_SECRET_NAME),
)


def attempt(label: str, fn) -> None:
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - the failure IS the answer
        print(f"  {label:<46} REFUSED  {str(exc)[:80]}")
        return
    print(f"  {label:<46} OK       {result}")


print("=" * 78)
print("THE ENTITLEMENT TEST - recent data is what the free tier withholds")
print("=" * 78)


def latest(feed: DataFeed) -> str:
    request = StockLatestTradeRequest(symbol_or_symbols="AAPL", feed=feed)
    return f"AAPL {client.get_stock_latest_trade(request)['AAPL'].price}"


attempt("SIP latest trade (real time)", lambda: latest(DataFeed.SIP))
attempt("IEX latest trade (free on any account)", lambda: latest(DataFeed.IEX))
attempt(
    "SIP 1-minute bars from the last 10 minutes",
    lambda: str(
        len(
            client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols="AAPL",
                    timeframe=TimeFrame.Minute,
                    start=datetime.now(UTC) - timedelta(minutes=10),
                    feed=DataFeed.SIP,
                )
            ).data.get("AAPL", [])
        )
    )
    + " bars",
)
attempt(
    "SIP daily bars from last week (free tier allows)",
    lambda: str(
        len(
            client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols="AAPL",
                    timeframe=TimeFrame.Day,
                    start=datetime.now(UTC) - timedelta(days=10),
                    feed=DataFeed.SIP,
                )
            ).data.get("AAPL", [])
        )
    )
    + " bars",
)

print()
print("Reading: if the first line is REFUSED and the last is OK, this is the FREE")
print("tier - SIP history only. If both are OK, a paid subscription is in place.")
print("The market is shut, so 'recent minute bars' may legitimately be 0 either way;")
print("the LATEST TRADE line is the one that discriminates.")
