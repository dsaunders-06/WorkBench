# Development stack after M27

## Standing rule during the data-collection phase

**Nothing lands that changes a trading decision.** The phase exists to find out
whether the machinery runs end to end and produces a reviewable record. A change
that alters which trades are taken contaminates the only measurement being made.

**Amended 29 July:** M27a is an authorised exception - the operator has decided
the live path moves to daily bars, which necessarily changes trading decisions.
Nothing else changes until it lands.

The install stays on **M26** until M27a is ready. M27 is committed but not deployed:
it adds a rail that refuses trades, which works against a phase whose purpose is
accumulating them - and it would refuse them on cost assumptions that cannot yet
be audited, because the metrics are still gross.

### Blocking - fix immediately

Anything that stops data existing:

* the feed dying, or symbols silently dropped
* the app crashing, hanging, or failing to survive a session
* `decision_journal.csv` or `risk_decisions.csv` not being written (still
  unproven - no signal has ever reached them)
* reconciliation false-tripping the kill-switch and halting a session
* orders rejected by a bug rather than by a rule
* the daily report failing at the close

### Deferred - however tempting

Anything that changes decisions: cost-rail calibration, concentration limits,
exit rules, holding periods, promotion settings, strategy parameters.

The test: *would this change which trades happen?* If yes, it waits.

### Morning check

1. `Trading session started - US is open` at 13:30 UTC, then ticks
2. Any `MARKET DATA DOWN`
3. Whether the journal and audit CSVs exist yet
4. Counts: signals generated, orders proposed, orders filled
5. The daily report's Metrics block

Looking for *does the pipeline move*, not *did it make money*. At these sample
sizes P&L is noise.

## The stack

Ordered on one principle: **make the measurement honest before making the
strategy better.** Everything downstream inherits a measurement error.

### M27a - Run the live path on daily bars  **[DECIDED]**

The largest finding so far, and it outranks the cost work: **no strategy in this
system has yet been evaluated on the data it was designed for.** Every session to
date has tested plumbing, not strategy.

**Evidence, 28 July.** The infrastructure ran perfectly - 13:37:59 to 20:03:09,
one process, no restarts, no kill-switch trips, no feed failures - and produced
zero signals. The regime engine crashed twice while trying to fit:

```
ValueError: startprob_ must sum to 1 (got nan)
ValueError: transmat_ rows must sum to 1 (got row sums of [1. 1. 1. 0.])
```

with 84 warnings that states were never visited. No `RegimeEvent` was ever
published all session.

**Mechanical cause.** `RegimeFeatureBuilder` has six columns: log returns,
realised vol, VIX, yield-curve slope, credit spread. The last three come from
FRED and update *daily*. Fitting on 60 one-minute bars leaves them **constant
across every row**, which makes the covariance matrix singular - hence the NaN.

**Real cause, and the fourth instance of one pattern.** `min_fit_bars = 60` is a
sensible window in *daily* bars (~3 months, over which VIX and credit spreads
genuinely move). It is being fed 60 one-minute bars - **one hour of market**. A
correct mechanism wired to the wrong input, exactly as with `BRK-B`, the
staleness rail, and the trade-timestamp clock.

The same mismatch applies to the strategies themselves. `bar_interval_seconds =
60`, so swing's EMA20/EMA50 are **20 and 50 minutes**, not days. A strategy
intended to hold for two weeks is deciding on a one-hour lookback. Its silence
may be the correct response to a timeframe it was never designed for.

**Two sessions, two different causes, same outcome - corrected 30 July.** My
first reading of 29 July was wrong and is worth recording so the next session
does not inherit it. The regime engine did **not** fail silently that night; it
fitted cleanly and published `low_vol`.

| | 28 July | 29 July |
|---|---|---|
| Regime engine | crashed (NaN), published nothing | fitted, published `low_vol (scalar=1.00)` |
| StrategyEngine regime | fell back to the `SIDEWAYS` default | took `LOW_VOL` |
| Swing | **eligible**, found no setup | **gated off entirely** |

`SwingStrategy.suitable_regimes()` returns `{Regime.SIDEWAYS}`, and
`strategies/engine.py:174` skips any strategy whose set excludes the current
regime. So on the 29th swing could not have produced a signal whatever prices
did. The zero-trade result was the gate, not the timeframe.

**Which makes the macro finding the urgent half, not the secondary one.** The
regime gate works, and works with real teeth - which is good design and exactly
why feeding it noise matters. On 29 July a random number generator switched the
only promoted strategy off for a full session, and the system reported that as
normal operation. `scalar=1.00`, so it did not even reduce exposure; it just
made swing quietly ineligible. This is the scenario recorded below as the
dangerous one, now observed. The 28th's crash was the lucky version.

**Revised order of work inside M27a.** Daily bars govern how well swing sees the
market; real macro data governs whether swing is allowed to look at all. Items 1
and 2 are small and can land before the rest - swing may start trading without
the whole milestone:

1. ~~`resolve_macro_source()` - real FRED when the key is present, mock otherwise
   **with a loud warning**, matching `resolve_broker`.~~ **Done, 30 July.**
   Two things had to come with it: `MacroFeed` published one `MacroEvent` per
   *observation*, which the mock's single-observation response hid and which
   against real FRED would have put 57,878 events on the bus every hour; and
   its poll loop had no error handling, so one network failure would have
   killed the task silently and frozen every macro feature for the session.
2. ~~**Give `regime_engine/engine.py` a logger.**~~ **Done, 30 July.**
   Classifications, transitions, warm-up progress, refits, and fit failures
   with the per-feature numbers that explain them.
3. ~~Daily-bar warm-start seeding (below).~~ **Done, 30 July**, together with
   the daily cadence, which could not be split from it: seeded daily bars with
   a 60s interval would be replaced by minute bars through the session, warm at
   the open and wrong by lunch. Three things the plan below did not anticipate:
   per-symbol fetching would have blocked startup for over two minutes (one
   bulk request does it in 3.2s); the regime engine appended a feature row per
   *tick*, which would have swamped 300 seeded rows within one session; and
   gap filling would have invented flat bars for weekends.
4. ~~Persistence and dead-classifier visibility.~~ **Done, 30 July.**
   `RegimeHealthEvent` and a REGIME ENGINE DOWN banner, ranked below the halt
   and the feed outage; `StrategyEngine` names every strategy and its
   eligibility the first time it gates on the default instead of a classified
   regime. **Persistence was deliberately not built** - the warm start already
   re-seeds every symbol from the authoritative source in seconds, and a local
   copy that can disagree with the vendor is maintenance cost for no benefit.
   The one real gap it would have closed, a mid-session restart losing the
   day's open/high/low, is fixed by loading the vendor's partial bar for today
   as the *forming* bar rather than discarding it.

**M27a is complete.** Verified against the live account: 101 symbols and 300
daily bars seeded in 7-17s, every macro column varying across the matrix, the
HMM classifying on the first live bar, and swing eligible.

**Swing's regime gate, widened 30 July by operator decision.** Measured over
the 300 real sessions to 29 July: bull 32.0%, bear 26.6%, high-vol 24.9%,
low-vol 10.4%, **sideways 6.2%**. The paper names Sideways alone for Swing, so
the only promoted strategy was eligible about one session in sixteen and the
zero-signal sessions were the ordinary case, not an anomaly. Now Sideways,
Bull, Low-Vol and Recovery; Bear, High-Vol and Recession stay excluded.

### Session of 30 July - M27a ran perfectly and still did not trade

The machinery did everything it was built to do. 101 symbols and 300 daily
bars seeded in **3 seconds**; the regime classified at **23:30:04**, four
seconds after the open, against three months cold; session control opened and
closed on the minute; **zero errors** all night; REGIME ENGINE DOWN never
fired. The M27b flapping fear did not materialise - one classification, stable
all session. Note that with daily bars `refit_interval_bars = 20` now means
every 20 *days*, so the model refits roughly monthly.

And the account did not trade, for the third session running and a third
distinct reason. Two candidates, which **the record could not distinguish** -
which is itself the defect:

1. The regime came out `high_vol`, one of the three deliberately excluded from
   Swing. At the measured frequencies that is ~25% of days; with bear, Swing is
   gated off about half the time even after the widening.
2. **The deployed strategy set is not persisted and was never logged.** It
   starts empty at every launch (spec §K) and only a manual Workbench click
   fills it. If nothing was deployed, no strategy was evaluated at all and the
   regime is irrelevant.

**Fixed 31 July:** the engine names its deployed set at startup and warns when
it is empty, deployment and undeployment are logged through `deploy()` /
`undeploy()` rather than a bare `.append()`, and the banner reads **NO STRATEGY
DEPLOYED** instead of AUTO-TRADE ACTIVE - which is what it claimed all night
while nothing could trade.

**Still open: should the deployed set survive a restart?** It changes
behaviour, so it is a decision rather than a fix. Today an unattended session
inherits nothing from the last one.

### M27b - The regime label is not a stable function of the input  **[NEW]**

**Sharpened by the 30 July session.** The classification that gated Swing off
all night was `high_vol=0.31, bull=0.29, recovery=0.20`. Swing is eligible
under both `bull` and `recovery`, so **0.49 of the probability mass sat in
regimes where it could trade against 0.31 where it could not** - and a 0.02
difference between the top two decided the day. The gate takes the argmax of a
nearly flat distribution and treats it as certainty.

Gating on probability mass across a strategy's suitable regimes, rather than on
the argmax label, now looks more important than the refit instability below.

Three replays over the same 300 days of real data produced three different
current labels - `recovery`, `high_vol`, `low_vol` - differing only in when the
last HMM refit landed and what path the hysteresis took. One of the three had
breadth pinned at a constant 0.5, which the new zero-variance warning catches;
the other two differed on nothing but refit timing.

The label gates every strategy, so a classifier whose output depends on when it
was last refitted is gating on an artefact. Worth understanding before the
label is trusted to size or permit anything. Candidates: fix the HMM's random
state across refits, refit on a schedule tied to the calendar rather than a bar
count, or hold the fitted model and only re-estimate the posterior.

**The macro source has never been real, and this is the more dangerous half.**
`runtime.py:416` reads `macro = macro_source or MockMacroSource(seed=1)`, and
`FredMacroSource` is not even imported there - built in M2, never once wired into
the live app. So three of the six regime features (VIX, yield-curve slope, credit
spread) have been `round(self._rng.uniform(-1, 5), 3)`, polled hourly. Not stale,
not degraded: fabricated.

This is the fifth instance of the pattern and the worst form of it - not a
mechanism wired to the wrong input, but a **placeholder wired in place of the
real thing with no warning anywhere**. `resolve_broker` and the Alpaca data
source both log loudly when they fall back; the macro path had no resolver at
all, which is why it survived twenty-five milestones unnoticed.

It also means daily bars **alone would not have fixed the regime engine**. With
300 seeded bars the HMM would very likely have fitted without crashing, published
a regime, gated every strategy on it, and given no reason to look again. A regime
engine that classifies confidently on random numbers is far more dangerous than
one that crashes - the crash is the only reason this was found.

**FRED key now in the keyring** (`FRED_API_KEY` via `qat.security`, never `.env`).
Verified live, and the variation is what M27a needs:

| series | observations | first | distinct values, last 250 obs |
|---|---|---|---|
| VIXCLS | 9,238 | 1990-01-02 | **218** |
| T10Y3M | 11,144 | 1982-01-04 | 85 |
| DGS10 | 16,126 | 1962-01-02 | 69 |
| DGS3MO | 11,224 | 1981-09-01 | 60 |
| BAA10Y | 10,141 | 1986-01-02 | 36 |

On daily bars those columns genuinely move, which is exactly what makes the
covariance matrix non-singular. History is decades deep against the 300 bars the
seeding needs.

**Add `resolve_macro_source()`** alongside the existing broker and data-source
resolvers: real FRED when a key is present, mock otherwise **with a loud
warning**. The absence of that resolver is the root cause of this class of bug,
not the mock itself.

**Decision: the live path runs on daily bars.** This matches how the strategies
and the regime model were specified and how the intended two-week hold works. The
intraday feed keeps its role for execution pricing, staleness and account state -
it stops being the source of signal history.

**What that actually requires, and why it is a build rather than a flag.** There
is **no warm-start anywhere**: `StrategyEngine.bars` and `RegimeFeatureBuilder`
are populated purely from live ticks, from zero, at every process start. Setting
`bar_interval_seconds = 86400` alone would leave the system inert for ~10 weeks
(EMA50) to ~3 months (the regime HMM). So:

* seed `StrategyEngine.bars` from `HistoricalBarSource.get_daily_bars()` at
  startup - the source already exists and is already used by the Screener and
  Workbench;
* seed `RegimeFeatureBuilder` the same way, pairing each daily bar with the FRED
  values current on that date so the macro columns vary across rows;
* append one bar per day thereafter, and persist so a restart does not reset;
* accept that decisions become roughly one evaluation per symbol per day. That
  is correct for a two-week hold, and it changes what "collecting data" means -
  the signal is one decision point a day, not a continuous stream.

**A fail-open worth fixing alongside.** `StrategyEngine` takes
`default_regime = Regime.SIDEWAYS`, so when the regime engine died the system
carried on trading as though the market were sideways, and nothing on screen said
otherwise. Defensible for availability, but it means the regime gate was not
gating, and a crashed classifier should be visible rather than silently
permissive.

### M28a - The staleness rail (promoted ahead of the cost work)

Not a tuning problem. **The rail has never once fired correctly** - every trip it
has produced has been a false positive, and it was only ever masked by the feed
being broken in other ways:

| Trip | Symbol | Reported age | Reality |
|---|---|---|---|
| 27 Jul | (feed dead) | - | never fired; per-symbol staleness skips symbols that have not ticked |
| 28 Jul 13:30 | BRK.B | 63,017s | thin on IEX, last print was the previous close |
| 28 Jul 13:35 | HON | 97s | liquid; the poll interval itself |

The defect is one line:

```python
self._last_seen[tick.symbol] = tick.ts        # the TRADE's timestamp
self._last_tick_at = datetime.now(UTC)        # the RECEIVE time (M26, correct)
```

The rail reads `_last_seen`, so it measures **how old the last trade was**, not
**whether the feed is delivering**. With `market data poll = 60s` and
`data_staleness_seconds = 60`, a trade that occurred 40s before a poll arrives
already 40s old and the next poll is 60s later, so the measured age routinely
lands between 60 and 120 seconds through entirely normal operation. On any
symbol. A trip was not a risk, it was arithmetic.

**Currently suppressed** by `QAT_DATA_STALENESS_SECONDS=250000` in the operator
`.env` - ~69 hours, sized to clear a weekend gap (Monday's open is 65 hours
after Friday's close). This effectively disables the rail. Acceptable on paper
because M26's feed-health check covers genuine feed death using receive time;
**not acceptable before live money**, because it leaves a partial outage
undetected - the feed continuing to deliver some symbols while silently
stopping on others.

The redesign separates two ideas the current code conflates:

* **feed liveness** - measured on receive time - *may* halt trading
* **quote freshness** - measured on the trade timestamp - excludes that ONE
  symbol from signal generation, and never halts the account

A stale quote on one thin ticker should stop trading that ticker. Halting the
whole account because Berkshire had not printed on IEX by 09:30:15 is a rail
doing considerably more damage than the hazard it guards against.

### M28 - Cost-truthful measurement

Fees on `ClosedTrade`, gross and net both retained; cost drag in the Metrics tab
and reports. Expectancy, average R, profit factor and the promotion gate all
become net. Everything else waits on this, because every judgement about the
strategy reads these numbers.

### M29 - Governance consistency

Turn on `enforce_promotion_evidence`. Today the policy says "earn autonomy" and
the code grants it anyway.

**Sequencing note.** An external review recommended enabling this immediately.
Doing so during the paper phase would halt data collection - swing has zero
closed trades against a 30-trade bar, so nothing would trade unattended. Correct
before live money, self-defeating during a paper test. And it must follow M28:
the gate reads expectancy and average R, which are gross today, so enforcing it
first would gate on numbers already known to be wrong.

### M30 - Gap risk as its own concept

Every risk figure currently means *"if the stop fills."* The 5% aggregate cap is
really "5% if every stop fills as intended". A 1%-risk trade with a 5% stop is
**20% of equity in notional**; a 30% gap through the stop costs **6% of the
account**, six times the budgeted loss, from one name.

* separate stop risk from gap risk in the governor
* measure overnight gap exposure
* single-name concentration 25% -> 10-15%, sector 40% -> 30%

Matters more on ASX, where halts pending price-sensitive announcements are
routine for small and mid caps and a two-week hold spans them by design.

### M31 - Churn control

The pieces deferred from M27: minimum holding period for signal-driven exits
(10 trading days, configurable, never delaying a protective exit), a turnover
budget on `trades_per_week`, and a time stop.

Open tension to decide explicitly: a minimum hold blocks a *signal-deterioration*
exit, which is not protective. Sitting through a broken thesis to save $13 of
commission is the wrong trade above some loss threshold.

### M32 - ASX readiness

**The blocker nobody flagged: there is no ASX market data source.** Alpaca is US
equities only, and the entire live data path hardened through M17/M25/M26 serves
US symbols. Needs a feed decision (yfinance, delayed and unofficial, vs IBKR's
own), currency handling, and the IBKR live path actually exercised.

Also: slippage is modelled at a flat 5bps, optimistic for ASX small and mid caps
where a $20,000 position can be a meaningful share of daily volume.

### M33 - Validation using what already exists

`monte_carlo.py` and `walk_forward.py` have been built since M4 and never run in
anger. Run them on swing. Promote correlation from a Risk Console display to an
actual portfolio limit - sector is currently a proxy for correlation, and in a
crisis it is a poor one.

## Already built, despite appearing on review wishlists

Monte Carlo; walk-forward (on the Workbench since M19); regime probabilities and
an exposure scalar the risk engine applies; volatility-targeted sizing (the 1% is
a ceiling, not a constant); EMA rather than simple moving averages; a correlation
table.
