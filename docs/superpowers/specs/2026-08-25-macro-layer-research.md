# Macro for an ASX book — what professionals watch, what is free, and a plan

**Asked on 25 August 2026:** research what other macro information a professional
share trader relies on, where it can be sourced at no cost, and plan how to build
it into the Advisory screen.

**Everything below marked MEASURED was fetched from this machine on 25 August
2026.** Nothing here is taken from a vendor's marketing page or from memory —
this project has spent two days finding rails that were configured, plausible,
and receiving no data.

---

## 1. What this application has today

Five FRED series, all United States, feeding both the macro read and the regime
engine's feature matrix (`config.py:17`):

```
DGS3MO   US 3-month treasury
DGS10    US 10-year treasury
T10Y3M   US 10y-3m spread          -> regime feature
VIXCLS   CBOE VIX                  -> regime feature
BAA10Y   Moody's Baa credit spread -> regime feature
```

**The gap is not subtle.** This is a book of 94 ASX megacaps and STW.AX, and
the regime that sets its position size is classified entirely on American
data. Nothing here knows the RBA cash rate, the AUD, the iron ore price, or
whether Australian financials — currently **60% of the book** — are under
stress. The ASX move (M104) changed the market and did not change the macro.

---

## 2. What professionals actually watch

From the research, four families recur, and they are worth naming because they
map onto what is obtainable:

**Yield curve.** 10y-2y and 10y-3m spreads. An inversion is the most-watched
recession signal in markets. The app has the US 10y-3m; it has no Australian
curve at all.

**Credit spreads.** Widening high-yield spreads lead equity stress — described
in the research as the most reliable single credit signal. The app has Baa
(investment grade); **high-yield OAS is the one practitioners actually quote**
and is free.

**Volatility.** Implied vol as a risk-appetite gauge. The app has the US VIX
and **not the ASX one**, which exists.

**Breadth.** How many names participate in a move; narrow leadership precedes
corrections. The app has none, and this is the one family with no free
off-the-shelf series — it must be computed from the watchlist the app already
holds bars for.

To that, an Australian book adds three the US literature does not stress:
**the AUD** (a commodity currency that moves the earnings of half the index),
**bulk commodity prices** (iron ore and coal drive BHP, RIO, FMG), and **China
demand**, since it is the destination for those bulks.

---

## 3. What is free — MEASURED, not assumed

### Tier A — daily, live, no key, via `yfinance` (already a dependency)

| Ticker | What | Measured 25 Aug | History |
|---|---|---|---|
| `^AXVI` | **S&P/ASX 200 VIX** | 10.54 | 759 bars |
| `^AXJO` | ASX 200 | 9,164.60 | 760 bars |
| `^AXFJ` | **ASX 200 Financials** | 9,231.10 | 760 bars |
| `AUDUSD=X` | AUD/USD | 0.72 | 778 bars |
| `TIO=F` | **Iron ore 62% Fe** | 95.34 | 752 bars |
| `HG=F` | Copper | 6.65 | 755 bars |
| `GC=F` | Gold | 4,696.50 | — |
| `CL=F` | WTI crude | 82.03 | — |
| `^VIX` | CBOE VIX | 15.77 | — |
| `DX-Y.NYB` | US dollar index | 99.02 | — |
| `^HSI` | Hang Seng (China proxy) | 25,511.10 | — |

**Every one returned data.** All six checked for depth carry 750+ daily bars
against the 301 the regime engine fits on, so these are viable as regime
FEATURES and not merely as narrative colour.

`^AXVI` and `^AXFJ` are the two that matter most and are the least obvious:
an Australian volatility gauge for an Australian book, and a sector index that
speaks directly to a book that is presently 60% financials.

### Tier B — free, no key, direct from the RBA (CSV)

Measured: all returned **HTTP 200** with real content, with an ordinary
User-Agent header.

| Table | What | Size |
|---|---|---|
| `f1.1-data.csv` | Interest rates and yields — money market, **cash rate** | 43 KB |
| `f2-data.csv` | **Capital market yields — government bonds** (the AU curve) | 200 KB |
| `f11.1-data.csv` | Exchange rates | 136 KB |
| `i1-data.csv` | International trade and balance of payments | 40 KB |

`https://www.rba.gov.au/statistics/tables/csv/<table>-data.csv`

Note the RBA site itself **403s an automated page fetch** while these CSV
endpoints serve fine — so a scraper would have concluded the data was
unavailable. The CSVs are the supported path.

### Tier C — free, existing FRED key, already integrated

Measured through the app's own `FredMacroSource`:

| Series | What | Last observation |
|---|---|---|
| `BAMLH0A0HYM2` | **US high-yield OAS** | 2.7 on **21 Aug 2026** (daily) |
| `T10Y2Y` | US 10y-2y spread | 0.46 on **24 Aug 2026** (daily) |
| `IRLTLT01AUM156N` | AU 10y govt bond yield | 4.831 — **June 2026** (monthly) |
| `LRHUTTTTAUM156S` | AU unemployment | 4.43% — **June 2026** (monthly) |
| `AUSRECDM` | AU recession indicator | **last observation 2022** |

**Frequency is the finding here, and it decides the design.** FRED's Australian
series are MONTHLY and lag by roughly two months — June data in late August.
That is fine as narrative context and **useless as a daily regime feature**.
`AUSRECDM` has not updated since 2022 and should not be used at all.

So Australian daily macro must come from the RBA and yfinance. FRED's value
for this book is the two US daily series it is not yet using — high-yield OAS
and the 10y-2y — plus slow-moving Australian context.

### What could NOT be established

The **ABS Data API** returned 406 and 404 against the endpoints tried. Its
correct SDMX endpoints were not established, so Australian CPI and employment
at source remain **unproven**. FRED carries both monthly with a lag, which may
be sufficient. Recorded as unknown rather than guessed at.

---

## 4. Recommendation on what this is FOR

The operator deferred this deliberately until the research was done, which was
right — the frequencies decide it.

**Phase 1 — narrative only. Do this first.** Every Tier A and Tier C daily
series becomes context in the Advisory screen. The model reasons about the
AUD, iron ore, the ASX VIX, high-yield spreads and Australian financials when
forming its buy/sell/hold. **Nothing sizes or gates on it.** This is where the
existing macro read already sits, so it changes no rail and needs no watched
session.

**Phase 2 — regime features, behind its own deploy and a watched session.**
The daily series have the depth. Adding them to the feature matrix changes the
regime label, and the label sets position SIZE through the exposure scalar —
so this moves a sizing input and must ship alone, with a before-and-after on
the governor's aggregate. This is exactly the discipline item 31 is being held
to.

**Phase 3 — a macro risk rail. Not recommended yet, and possibly never.** A
rail that refuses entries on macro stress is a large delegation whose errors
are invisible: you discover them by not being in a market that then rose.
Revisit only once Phase 2 has run long enough to show the regime label
responding sensibly to Australian conditions.

**Breadth is deliberately excluded from Phase 1.** It is the one family with no
free series, must be computed from the watchlist's own bars, and would be a
new derived indicator rather than a sourced one. Worth doing; not worth
conflating with plumbing.

---

## 5. Plan

### Phase 1 — the Advisory screen (no rail changes)

**1.1 A second macro source alongside FRED.** `MacroDataSource` already exists
as a protocol with `fetch_series`. Add a `MarketSeriesSource` for the yfinance
tickers and an `RbaCsvSource` for the four tables, both behind the same
protocol so `AdvisoryContext` does not learn where a number came from.

Both must follow the rule this codebase already enforces everywhere: **a series
that cannot be fetched is absent, never zero.** M73's `var_95=0.0` and this
week's `held_in_sector_dollars: 0.0` are the same failure, and a macro layer
that silently reports a flat AUD is the same shape again.

**1.2 Cache with an honest staleness marker.** Reuse the TTL disk cache the
fundamentals already use. Every series carries its own `observed_at`, and the
context states it. A two-month-old Australian unemployment print is useful —
presented as current it is a lie.

**1.3 Render into `AdvisoryContext`.** Extend the macro block. Group by family
so the model sees structure rather than a bag of numbers: rates and curve,
credit, volatility, currency, commodities, China. State the observation date
per family.

**1.4 Show it on the Advisory screen**, in the same place the deterministic
macro read already appears, with the AI's own read beside it — the pattern the
screen already uses, where the two are allowed to disagree and the difference
is the interesting part.

**1.5 Tests that would have caught this week's failures.** For each source: a
fetch failure is absent and logged, never zero; a stale series is marked;
and — the one that matters — **an end-to-end test asserting the series reach
`AdvisoryContext`**, because a rail wired through four correct layers and never
called is precisely how item 44 stayed dark since the first trade.

### Phase 2 — regime features (separate milestone, watched session)

**2.1** Add the chosen daily series to `feature_matrix.py`. Candidates, on the
research: `^AXVI` (Australian volatility), the AU 10y-3m curve from RBA F2,
`BAMLH0A0HYM2` (high-yield credit), `AUDUSD=X`, `TIO=F`.

**2.2** Measure the regime label and the governor's aggregate before and after
on the same data. A changed label with no stated reason is not an improvement.

**2.3** Ship alone, watch a session, and record what the label did.

### Phase 3 — not scheduled

---

## 6. What to decide before Phase 1 starts

1. **Which Tier A tickers to include.** All eleven, or the six with the clearest
   ASX relevance (`^AXVI`, `^AXJO`, `^AXFJ`, `AUDUSD=X`, `TIO=F`, `HG=F`)?
   More series is more to keep honest about staleness.
2. **Whether to source the RBA CSVs in Phase 1** or defer them to Phase 2. The
   AU cash rate and bond curve are the strongest Australian additions, and they
   are also the only new integration in the phase.
3. **Whether ABS is worth establishing** for Australian CPI and employment at
   source, or whether FRED's monthly lagged versions suffice for narrative.

---

## Sources

- [Reserve Bank of Australia — Statistics](https://www.rba.gov.au/statistics)
- [Cash Rate Target — RBA](https://www.rba.gov.au/statistics/cash-rate/)
- [Credit Spreads: The Market's Early Warning Indicators — RIA](https://realinvestmentadvice.com/resources/blog/credit-spreads-the-markets-early-warning-indicators/)
- [Credit Spreads — LuxAlgo Library](https://www.luxalgo.com/library/concept/credit-spreads/)
- [Stock Market Crash Warning Signs: 8 Indicators Pros Watch](https://pro.stockalarm.io/blog/stock-market-crash-warning-signs)
- [HY Credit Spread (OAS) — Convex](https://convextrade.com/metrics/bamlh0a0hym2)
- [Macro Trading Glossary — Macro Staq](https://macrostaq.com/glossary)
