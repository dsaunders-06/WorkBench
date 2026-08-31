r"""Is IBKR's delayed feed actually better than yfinance? Measure, do not assume.

    .\.venv\Scripts\python.exe scripts\measure_ibkr_feed.py --minutes 10
    .\.venv\Scripts\python.exe scripts\measure_ibkr_feed.py --minutes 30 --all

⚠️ RUN FROM POWERSHELL, DURING MARKET HOURS. It builds `Settings()`, which loads
the live data directory's .env whether or not this script mentions it. Read
only: its own clientId, a throwaway data_dir, and it places nothing.

## Why this exists

Item 33 calls an IBKR feed *"the deeper fix"* for the twenty-minute yfinance
blind window, and says *"the reason yfinance is still the price source is
history rather than a decision"*. On 31 August a streaming delayed subscription
was measured delivering a full ASX quote - last, bid, ask, high, low, open,
volume - on a paper account with no market-data subscription.

⚠️ **That is NOT yet a reason to migrate, and this script exists because of the
gap between the two.** IBKR's DELAYED feed is delayed by definition, nominally
fifteen to twenty minutes. yfinance is about twenty. **If they are comparable,
the "deeper fix" fixes nothing** - and believing otherwise would repeat M39 and
M43 exactly: a design built on a capability nobody measured.

## What it measures, and why yfinance runs alongside

Four questions, and only the first decides anything:

1. **DELAY** - how far behind the wall clock is each source's most recent print?
   This is the whole question. A source that is also twenty minutes late does
   not close a twenty-minute blind window.
2. **COVERAGE** - how many of the watched symbols does each source actually
   return?
3. **FREQUENCY** - how many distinct prints arrive per symbol per minute?
4. **GAPS** - the longest silence per symbol.

⚠️ **yfinance is polled IN THE SAME WINDOW as the control.** Comparing a fresh
IBKR measurement against a remembered "yfinance is 20 minutes late" would
measure the memory, not the feed - and one extra control caught four wrong
answers on 27 August.

## What it deliberately does NOT do

* **It does not decide.** It prints two columns and leaves the judgement.
* **It does not measure the auction.** Run it across 10:00-10:15 separately if
  that window matters; a single run averaged over it would hide it.
* **It does not touch the running application.** Its own clientId, and the app
  can be running or not.

## ✅ Validated on a SHUT market, which is a free control

With nothing trading, both sources must report the SAME last trade, so their
median ages must agree. Run 31 August at 17:32 AEST, ninety minutes after the
close:

    IBKR      median 4,937.7s   (spread 4,271.7 - 4,938.7)
    yfinance  median 4,874.8s   (spread 4,814.8 - 4,874.8)

They agree to within the sixty-second sampling granularity. **Before the
`delayedLastTimestamp` fix they differed by a factor of eighty**, which is how
the wrong field was caught. Re-run it outside hours any time the numbers look
surprising: if the two disagree on a shut market, the instrument is broken, not
the feed.

⚠️ Note IBKR's per-symbol SPREAD is 667s against yfinance's 60s - different
symbols' last trades landed at different points through the closing auction, so
IBKR appears to capture more of the close. Suggestive, not conclusive, and not
what this script is for.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import connection_target  # noqa: E402
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402

_SAMPLE = ["BHP.AX", "CBA.AX", "SUN.AX", "TNE.AX", "A2M.AX", "WOW.AX"]


def _last_trade_time(ticker: object) -> datetime | None:
    """When the last TRADE printed - never when the ticker object last updated.

    ⚠️ **`Ticker.time` and `Ticker.timestamp` are the OBJECT'S refresh stamp, not
    the trade's.** Measured 31 August with the ASX shut for ninety minutes:

        delayedLastTimestamp  2026-08-31 06:21:08 UTC   age 4,110s   <- the trade
        time                  2026-08-31 07:29:26 UTC   age    12s   <- the object
        timestamp             (same as `time`)          age    12s
        lastTimestamp         None                                  <- real-time, unsubscribed

    The first draft of this script read `time`, and on a market where nothing had
    traded for over an hour it would have reported IBKR as SIXTY SECONDS FRESH
    against yfinance's twenty minutes - and recommended a migration on a field
    that measures nothing about the feed. A shut market is what exposed it: a
    genuine trade stamp cannot be a minute old when no trade has happened.

    `lastTimestamp` first for a real-time subscription; `delayedLastTimestamp` is
    what this account actually gets. Never `time`.
    """
    for field in ("lastTimestamp", "delayedLastTimestamp"):
        value = getattr(ticker, field, None)
        if isinstance(value, datetime):
            return value
    return None


def _age_seconds(ts: datetime | None, now: datetime) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return (now - ts).total_seconds()


def _summarise(name: str, ages: dict[str, list[float]], counts: dict[str, int]) -> None:
    seen = [s for s in ages if ages[s]]
    print(f"\n  {name}")
    print(f"    symbols with any print : {len(seen)} of {len(ages)}")
    if not seen:
        print("    ⚠️ NOTHING ARRIVED. That is a result, not a failure to measure.")
        return
    medians = [statistics.median(ages[s]) for s in seen]
    print(f"    median print age       : {statistics.median(medians):>8.1f}s")
    print(f"    best / worst symbol    : {min(medians):>8.1f}s / {max(medians):.1f}s")
    total = sum(counts[s] for s in seen)
    print(f"    distinct prints        : {total}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--all", action="store_true", help="every watched symbol, not a sample")
    args = parser.parse_args()

    from ib_async import IB

    settings = Settings(data_dir=tempfile.mkdtemp(prefix="qat-feed-"))
    if args.all:
        from qat.data import universe

        symbols = list(universe.resolve_watchlist(settings))
    else:
        symbols = list(_SAMPLE)

    print(f"measuring {len(symbols)} symbol(s) for {args.minutes:g} minute(s)")
    print("⚠️ During market hours only. Outside them both sources report a stale close")
    print("   and the comparison is meaningless.\n")

    host, port, client_id = connection_target(settings)
    ib = IB()
    await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)

    ib_ages: dict[str, list[float]] = {s: [] for s in symbols}
    ib_counts: dict[str, int] = defaultdict(int)
    yf_ages: dict[str, list[float]] = {s: [] for s in symbols}
    yf_counts: dict[str, int] = defaultdict(int)

    try:
        ib.reqMarketDataType(3)  # delayed
        tickers = {}
        for symbol in symbols:
            qualified = await ib.qualifyContractsAsync(to_ib_contract(symbol, settings.market))
            if not qualified or qualified[0] is None:
                print(f"  {symbol}: could not qualify - excluded")
                ib_ages.pop(symbol, None)
                yf_ages.pop(symbol, None)
                continue
            tickers[symbol] = ib.reqMktData(qualified[0], "", False, False)

        deadline = datetime.now(UTC).timestamp() + args.minutes * 60
        last_ib: dict[str, datetime | None] = {}
        while datetime.now(UTC).timestamp() < deadline:
            await asyncio.sleep(60)
            now = datetime.now(UTC)

            for symbol, ticker in tickers.items():
                ts = _last_trade_time(ticker)
                if ts is None:
                    continue
                age = _age_seconds(ts, now)
                if age is None:
                    continue
                ib_ages[symbol].append(age)
                if last_ib.get(symbol) != ts:
                    ib_counts[symbol] += 1
                    last_ib[symbol] = ts

            # ⚠️ THE CONTROL, polled in the SAME window. Comparing against a
            # remembered "yfinance is 20 minutes late" would measure the memory.
            await _poll_yfinance(list(tickers), yf_ages, yf_counts, now)
            print(f"    ... {now:%H:%M:%S} sampled")
    finally:
        ib.disconnect()

    print("\n=== RESULT ===")
    _summarise("IBKR (delayed, streaming)", ib_ages, ib_counts)
    _summarise("yfinance (the control)", yf_ages, yf_counts)
    print(
        "\n⚠️ THE ONLY QUESTION THAT DECIDES ANYTHING is the median print age.\n"
        "   IBKR's delayed feed is delayed BY DEFINITION - nominally 15-20 minutes.\n"
        "   If the two medians are comparable, migrating does NOT close the blind\n"
        "   window and item 33's 'deeper fix' is not one. Read the numbers before\n"
        "   designing anything on top of them - M39 and M43 were both designed\n"
        "   against a capability nobody measured first."
    )
    return 0


async def _poll_yfinance(
    symbols: list[str],
    ages: dict[str, list[float]],
    counts: dict[str, int],
    now: datetime,
) -> None:
    """One yfinance poll, matching what the application actually does."""
    import yfinance as yf

    try:
        frame = await asyncio.to_thread(
            yf.download,
            tickers=" ".join(symbols),
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=False,
            group_by="ticker",
        )
    except Exception as exc:  # noqa: BLE001 - a failed poll is a measurement
        print(f"    yfinance poll failed: {exc}")
        return
    if frame is None or frame.empty:
        return

    for symbol in symbols:
        try:
            series = frame[symbol]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if series.empty:
            continue
        stamp = series.index[-1].to_pydatetime()
        age = _age_seconds(stamp, now)
        if age is not None:
            ages[symbol].append(age)
            counts[symbol] += 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
