# Market data — what this account actually has, measured 8 August 2026

Written because the question gates two things — M43 (halts) and M32 (ASX) — and
because the assumptions in circulation turned out to be wrong in both
directions.

Every figure here came from the live paper account. Scripts:
`scripts/analysis/probe_market_data.py`.

## What was assumed, and what is true

| Assumed | Measured |
|---|---|
| The app runs on yfinance, delayed ~15 minutes | **It runs on Alpaca.** `QAT_MARKET_DATA_SOURCE=alpaca`, `QAT_ALPACA_DATA_FEED=iex` |
| SIP needs a paid subscription we do not have | **Half right.** Real-time SIP is refused; **SIP *historical* works free** |

The earlier handoff statement that this system runs on delayed, unofficial
yfinance data was **wrong**. yfinance is a configured option and a fallback; the
live setting is Alpaca IEX.

## The entitlement, exactly

```
SIP latest trade (real time)        REFUSED  "subscription does not permit
                                              querying recent SIP data"
IEX latest trade                    OK       AAPL 313.29
SIP 1-minute bars, last 10 minutes  REFUSED  (same message)
SIP daily bars, last week           OK       7 bars
```

**Free tier.** Real-time is IEX only. Anything older than ~15 minutes is
available on the full consolidated tape at no cost.

## What IEX costs us

IEX is one exchange. Measured across the ten held symbols, last completed
session:

* **IEX sees a median 4.3% of consolidated volume** — 2.7% on AMD, 5.1% on JNJ.
* Closing prices differ by a median **1.6 bps**, worst 8.5 bps. Small.

Closes being close is the reassuring number, and it is the wrong one to look at.

### ATR is the number that matters

Daily bars are requested on the **same feed as live ticks** —
`feed=_feed_enum(self.feed)` in `AlpacaMarketDataSource._request`. So with
`iex` configured, every EMA, every regime feature, all 100 breadth symbols and
**every ATR** are computed from one exchange's view.

ATR does not use closes. It uses **high and low**, and a single venue sees a
narrower range than the consolidated tape by construction — it was not there for
the prints that made the extremes.

Measured over 67 sessions, identical dates on both feeds:

```
Median per-session high-low range, IEX / consolidated:  0.965
All ten symbols below 1.000 - systematic, not noise
```

That propagates straight into sizing, because ATR sets the stop distance and the
stop distance sets the share count:

| | median | worst |
|---|---|---|
| ATR, IEX / consolidated | **0.961** | 0.861 (CSCO) |
| Resulting position **oversize** | **+4.0%** | **+16.1%** (CSCO) |

### What that actually means

Not "we are risking more per trade than configured". The arithmetic is
internally consistent — `budget / (ATR x mult)` shares each risking
`ATR x mult` is the budget, whatever ATR is.

**The stops are simply too tight for the real volatility.** Positions are sized
as though these stocks were ~4% calmer than they are, so stops get hit more often
than the design assumes. Per-trade loss is as budgeted; the *frequency* is
higher.

For a trial whose entire purpose is measuring whether swing has an edge, that is
a systematic bias against the strategy, produced by the data feed rather than by
the strategy. **The September evidence burst would carry it.**

## The fix, and why it is not free of consequence

Request **daily bars on `sip`** while leaving live ticks on `iex`. Historical SIP
costs nothing on this account. It is roughly a one-line separation of the two
feed choices, which are currently one setting.

Three things it is not:

* **It is inside the validation freeze.** It changes ATR, therefore stop
  distance, therefore position size — the freeze's own test is *"would this
  change which trades happen, or how large they are?"* and the answer is yes.
  It needs a deliberate lift, recorded, like M56c, M57 and M58b.
* **It resets the two-week baseline** that began 6 August and is reviewed
  around 20 August. Sizes measured before and after would not be comparable.
* **One operational unknown.** The bars request has no `end`, so during market
  hours it spans data less than 15 minutes old — which is exactly what free-tier
  SIP refuses. Whether Alpaca truncates or rejects the whole request is
  untested; the market was shut. Setting `end = now - 16 minutes` on SIP
  requests removes the question. **Test this before relying on it.**

## What this means for M43 and M32

**M43 (halts) is gated here, and the gate is now specific.** Halts are not in the
REST API — `get_asset()` reports `status=active, tradable=True` for a halted
symbol, because that is *listing* status. The feed is
`subscribe_trading_statuses` on `StockDataStream`, a websocket this application
does not consume. `AlpacaMarketDataSource` documents why it polls: the app is
built around a polled `AsyncIterator` at a daily cadence, and streaming would be
a larger change for prices this system does not act on tick-by-tick.

That reasoning holds for *prices* and does not hold for *halts* — a halt is an
event, not a price, and polling cannot see it at all. So M43 needs a websocket
consumer regardless of what is decided about price feeds.

**M32 (ASX) is not gated here at all.** Alpaca cannot reach the ASX under any
subscription, so no Alpaca decision advances it. That is an IBKR question, and
it is separate.

Those two were bundled together in the 8 August handoff. They should not have
been.

## Recommendation

Three items, and only the first is urgent:

1. **Nothing before Tuesday.** The MNST split test runs on the deployed build.
   No sizing change should land between now and a measurement.
2. **Then decide on SIP daily bars**, as a recorded freeze lift. The argument for
   is that a 4% systematic stop-tightening contaminates the very evidence the
   trial exists to produce, and September is close. The argument against is that
   it resets a baseline two weeks from its review. **My view: take it, and
   restart the baseline** — a baseline measured through a known bias is not worth
   protecting.
3. **M43 needs a websocket consumer**, decided on its own merits. It is not
   blocked on the price-feed choice; it needs a new capability either way.
