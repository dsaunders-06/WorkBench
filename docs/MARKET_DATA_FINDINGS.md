# Market data — what this account actually has, measured 8 August 2026

> **⚠️ EVERYTHING BELOW IS THE US / ALPACA ACCOUNT.** The system moved to ASX and
> IBKR on 19-20 August. Alpaca is no longer the data source and IBKR is
> execution-only in this codebase. The ASX findings are the section immediately
> below; the original 8 August measurements are kept unchanged beneath them
> because they are still the record of what the US account had.

## ASX / yfinance — measured 20 August 2026, the first live session

**yfinance cannot sustain a 100-symbol, 60-second poll.** After roughly twenty
minutes it hard-blocked and answered "possibly delisted" for ALL 101 symbols at
once - megacaps included, minutes after pricing them - and the feed produced no
ticks. The 499-session replay never exposed this because replay reads history in
BULK, ONCE; live polling is a different access pattern against the same vendor.

> ### ⚠️ RE-READ 1 SEPTEMBER 2026: "101" IS OUR COUNT, NOT YAHOO'S THRESHOLD
>
> The heading above has been read as though 101 were a vendor limit. It is not.
> On 20 August the watchlist was the **unpruned megacap 100 plus the STW.AX
> benchmark** = 101 polled, so the number records **how many we asked for** and
> says nothing about where the limit sits. It could be 96 or 250. **Nobody has
> measured it**, and there is no documented yfinance free-tier symbol threshold
> anywhere in this repo - the only other `101`s in the codebase are Alpaca-era
> equity figures.
>
> ⚠️ **AND THE FAILURE IS NOT REPRODUCING.** On 1 September the live session
> polled **95 symbols on a 60-second cadence for three and a half hours**
> (10:20:40 onward, ~210 polls) with **zero feed failures**. Whatever caused the
> 20 August block - request rate, vendor behaviour, or the un-cached re-fetching
> this file warns about two paragraphs down - it is not biting at 95 today.
>
> **M161 widens the list to 99 + STW.AX = 100 polled**, using headroom
> `watchlist_max_symbols` already allowed while staying under the one count ever
> observed to fail. That is a deliberate step below an unmeasured boundary, not
> a measurement of it. ⚠️ **Going materially beyond 100 needs the boundary
> measured first, out of hours** - a harness that finds where the block actually
> starts, rather than another count inherited as a rule.

**It is not a per-symbol fact and must not be read as one.** M106 rewrote the
pre-flight's feed check for exactly this: a source that prices NONE of the
symbols asked for has failed as a SOURCE, and listing a hundred tickers sends an
operator to check the symbols instead of the one thing that is wrong.

**The block is easy to re-trigger with diagnostics.** On the evening of
20 August five separate probe fetches while investigating an unrelated defect
blocked it again for over an hour, which delayed a measurement that needed it.
Cache the panel; re-fetching per attempt is the same hazard at a smaller scale.

**Six ASX tickers in the megacap list were dead** - AWC, BKW, DHG, IPL, NSR, SVW
- returning no real bars at all. `fetch_daily_panel` correctly discarded them and
named them rather than seeding synthetic data. Pruned in M110.

**Daily bars are stamped exchange-local midnight**, e.g. `2026-08-20 00:00:00+10:00`
for the 20 August session. Flooring those to a UTC boundary dated every bar a day
early and admitted today's partial session as a completed bar - see M111.

**The open question this leaves is Stage 2:** which source supplies ASX bars.
yfinance is free and proven across 499 sessions but unofficial, rate-limited, and
fabricates bars on a 404. IBKR would need an `IBHistorySource` written with
pacing. A third vendor is the only option that would let the survivorship caveat
come off the research manifests.

## ❌ IBKR's DELAYED FEED IS NOT FRESHER THAN yfinance — measured 1 September 2026

Both sources polled in the SAME window by `scripts/measure_ibkr_feed.py`, sample
of six ASX megacaps, during continuous trading 10:17:53–10:48:15 AEST:

| | symbols | median print age | per-symbol spread | distinct prints |
|---|---|---|---|---|
| IBKR (delayed, streaming) | 6 of 6 | **1206.9s** (20.1 min) | 1205.3–1208.3s | 173 |
| yfinance (the control) | 6 of 6 | **1237.3s** (20.6 min) | 1213.0–1260.8s | 168 |

**Thirty seconds apart on a twenty-minute window.** Migrating the price source to
IBKR's delayed feed would recover 2.5% of the blind window. It is not the "deeper
fix" item 33 proposed it as.

**Both are blind at the bell**, which is the window the fix was for. A separate
run across 10:07–10:17, deliberately not averaged in, returned `0 of 6` on BOTH
sides — not one last-trade stamp in ten minutes. The application's own feed
agrees: 95/95 failed downloads from 10:00:00, recovery at **10:20:40**, a 20m40s
blind window against 31 August's ~20m37s.

⚠️ **The one thing IBKR is measurably better at is CONSISTENCY, not freshness** —
3.0s of spread across symbols against yfinance's 47.8s. That decides nothing
here.

⚠️ **Read the harness's own validation before trusting a re-run.** Its first
draft read `Ticker.time` — the object's refresh stamp — and reported IBKR as 60
seconds fresh on a market shut for ninety minutes. The field is
`delayedLastTimestamp`. A SHUT market is the free control: with nothing trading,
both sources must report the same last trade, and when they disagreed eightyfold
the instrument was broken, not the feed.

⚠️ **Known limit:** a "print" is scored only when a last-trade timestamp is a
datetime, so `0 of 6` means no *stamp*, not proven no *price*. It does not affect
the steady-state medians, which are measured from real stamps on both sides.

**What would actually close the window is a paid real-time ASX subscription** — a
cost decision, not an engineering one.

---


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
