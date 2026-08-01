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

## M31b - What the first trading session found  **[COMPLETE]**

The session of 31 July filled **six positions** - CSCO 44, UNP 17, WFC 58,
CRWD 16, JNJ 19, CVS 47 - all whole shares, no broker refusals, through every
rail. The first real trades this system has ever made. It also exposed six
defects, listed here in the order they must be fixed.

**1. Bracket legs expired at the close. [DONE]** Orders were submitted
`TimeInForce.DAY`, so at 20:00 the take-profit legs EXPIRED and Alpaca
cancelled the paired stops with them, as OCO does. Six positions worth about
$36,000 sat through a three-day weekend with no protection at the broker at
all. A stop whose purpose is to outlive the application must outlive the
session: bracketed entries are now GTC. Plain orders stay DAY, so an unfilled
market order does not linger into the next session at a price nobody chose.

**2. Nothing reconciles stops against the broker. [DONE]** `OMS._position_stops` still
holds stops the app believes are resting at Alpaca, and the governor computes
risk-at-stop from them - so after the expiry above it thinks the book is safer
than it is. Reconciliation compares FILLED QUANTITIES only, which is why it
caught nothing. This is the same failure as the phantom `transmitted` status on
30 July: app-side belief and broker reality diverged with nothing watching.

**3. A transiently-blocked order is never re-examined. [DONE]** The autonomous
executor evaluates each order once, on `OrderPendingSignoffEvent`. An order
refused for `Opening Volatility` or `Midday Lull` - reasons that expire in
minutes - is treated exactly like one refused for a permanent reason, and the
symbol stays suppressed because the bridge skips anything in
`pending_signoff_symbols()`. It cost three manual reject cycles on 30 July and
one position (PANW, 10 shares, blocked 15:39 in the Midday Lull) on the 31st.

**4. Entry times are not persisted. [DONE]** `SignalToOrderBridge._entries` is built
only from live fill events, so a restart leaves open positions with no known
entry date - and the minimum hold and time stop both treat an unknown entry as
"never applies". A restart silently disarms the churn rails on everything
already held.

**5. The blotter shows no prices. [DONE]** Columns are Order ID, Symbol, Side,
Quantity, Status, Created At. No reference price, stop, target or strategy - on
the screen whose entire purpose is informed human sign-off. Deciding whether to
approve a stale order on 30 July required reconstructing all of it from the
decision journal plus a live quote.

**6. Repeated identical refusals flood the journal. [DONE]** SPY was refused by the
cost rail 249 times in one session, once a minute, every minute - 249 of 262
journal rows. The refusal is correct; logging it 249 times buries every real
event. Suppressed per symbol: an identical outcome-and-reason pair is written once,
and any change either way is always written, so the journal still shows when a
refusal started and when it stopped.

**All six landed 1 August.** `OMS.verify_position_stops` now asks the broker
which stops are actually working and drops any it cannot find, so an
unprotected position falls back to counting its full value at risk rather than
looking safe. Entry dates are written to `open_position_entries.json` on every
fill, so a restart no longer disarms the churn rails.

A broker that cannot answer `resting_stops` changes nothing: an adapter without
the capability must not be read as "no stops rest anywhere", which would drop
every stop the app holds.

## M31d - A restart forgot what was protecting the book

`OMS._position_stops` is in-memory and starts empty, so every launch
re-adopted its own positions as unprotected. The governor counts a position
with no known stop at its full value, which is the conservative rule and the
right one - but applied to six holdings worth $27.9k on $100.8k equity it
reads as 27.7% risk-at-stop against a 5% cap, and rejects every new buy before
sizing runs.

It also blinded `verify_position_stops`, the M31b rail that catches a stop
that has quietly stopped existing: it iterates `_position_stops`, so after a
restart it had nothing to check - precisely when an overnight bracket expiry
is most likely to have happened.

Adoption now asks the broker. `resting_stops()` already existed and was used
only to verify; it is the account, and the account is the only thing that
actually knows. A position with no resting stop is still absent from the
record, so the conservative rule is unchanged - it is now reached by evidence
rather than by assumption, and the naked ones get named at ERROR instead of
being averaged into one warning about all of them.

**What it found on 1 August.** All six. Every entry from 31 July shows the
same three rows at Alpaca: market buy filled, limit sell expired, stop sell
canceled. The brackets were submitted DAY, and the take-profit leg expiring at
the close took the paired stop with it - the exact failure M31b diagnosed,
now caught in the act. The GTC fix shipped in M31a protects new entries and
cannot resurrect these.

**Re-arming. [DONE]** Every stop this system ever placed rode in as a bracket
leg on an entry, so a position whose legs died had no way to get another one.
`OMS.submit_protective_stop` places a standalone GTC stop on a position
already held, and `SignalToOrderBridge.rearm_protective_stops` proposes one at
startup for each held position the broker is not protecting.

The level comes from the recorded entry stop, not from an ATR recomputed now:
the risk budget was spent on the distance the position was SIZED against, so
protecting it at any other distance protects an amount nobody approved. A
position with no recorded entry stop gets nothing and is logged - an invented
level would look identical to a real one on every screen in the app.

Two ways this order could have made things worse than the exposure it repairs,
both guarded: submitted as a market sell it liquidates the position, and
counted as a fill it halves the tracked quantity against a broker still
holding all of it - which reconciliation reads as a discrepancy and answers by
tripping the kill-switch, on the very order sent to make the book safer.

They are proposed, not transmitted. Reducing risk is an argument for letting
an order through unattended and not an argument for bypassing the gate: a stop
still sells shares when it is reached.

## M31c - The Performance tab showed the launch, not the present

Three observations on 1 August - the Closed Trades table empty, no daily report
for Friday, the weekly report apparently never run - turned out to be one
display bug and two correct behaviours.

`PerformanceScreen.refresh()` was called at construction and by the Refresh
button, and nowhere else. A session started at 00:18 still displayed 00:18's
figures at 06:04: Friday's daily report was on disk and absent from the screen,
and the promotion table, metrics and closed-trades list were all equally stale.
During a live session that means watching a promotion table frozen at launch.

It now re-reads on `showEvent` and polls once a minute while it is the visible
tab, stopping in `hideEvent`.

**The other two were not bugs.** Closed Trades is empty because nothing has
closed - six positions opened 31 July against a ten-trading-day minimum hold.
And the weekly report *did* run: `last_weekly` records the week's MONDAY, so
`2026-07-27` is Friday 31 July's week, and `weekly_reports.md` contains "Week
of 27 Jul 2026 to 31 Jul 2026". Reading that field as a week-end date is what
made a working scheduler look broken.

**Open-position activity in reports. [DONE]** A daily report on a day with six
entries and no exits read identically to a day when nothing happened, because
every metric is built from closed trades. Reports now carry `opened` and `held`
from the ledger's open lots, so Friday reads "Opened 6 position(s), $27,783.86
committed" with each entry listed, and "Still held 6 position(s)". A genuinely
quiet day still reads as quiet.

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

### M27b - Gate on probability mass, not the argmax label  **[DONE, 31 July]**

The gate read the single winning label. On 30 July that label was `high_vol` at
0.31 against `bull` at 0.29, so a **0.02 difference decided whether the only
promoted strategy traded at all**, while 0.49 of the distribution sat in
regimes where it was eligible. Collapsing a distribution to its argmax and then
testing set membership throws away the confidence the model already computed.

A strategy now trades when at least `regime_eligibility_mass` (default 0.5) of
the distribution lies inside its suitable regimes.

**Measured over the same 300 sessions, this changes very little in aggregate,
and that is the honest headline:**

| | argmax | mass >= 50% | net |
|---|---|---|---|
| swing | 57.3% | 58.1% | +2 days |
| trend-following | 42.7% | 41.9% | -2 days |

The top-two margin is under 5 points on only **6.2%** of sessions - the
hysteresis-smoothed label is usually a confident call. So this is a correctness
fix for the coin-flip case, not a way to trade more, and it moves in both
directions: swing gains days, trend-following loses them. 30 July happened to
land in that 6%.

A property worth naming: with seven regimes and a *flat* distribution, a
four-regime strategy sits at 0.57 and trades while a one-regime strategy sits
at 0.14 and does not. When the model knows nothing, breadth of mandate decides
rather than an arbitrary argmax. That is the intended direction.

**Still open from the original M27b:** the label remains unstable across
refits - three replays of the same 300 days produced three different current
labels, differing only in refit timing. Mass gating reduces the blast radius
(a near-tie no longer flips a gate) but does not address the cause. Candidates
remain: fix the HMM's random state across refits, refit on a calendar schedule
rather than a bar count, or hold the fitted model and re-estimate only the
posterior. With daily bars a refit now happens roughly monthly, so this is a
slow-burning problem rather than an intraday one.

### M28a - The staleness rail  **[DONE, 31 July]**

Not a tuning problem. The rail had never once fired correctly - every trip it
produced was a false positive, and it was only ever masked by the feed being
broken in other ways:

| Trip | Symbol | Reported age | Reality |
|---|---|---|---|
| 27 Jul | (feed dead) | - | never fired; per-symbol staleness skips symbols that have not ticked |
| 28 Jul 13:30 | BRK.B | 63,017s | thin on IEX, last print was the previous close |
| 28 Jul 13:35 | HON | 97s | liquid; the poll interval itself |

It read `_last_seen`, the TRADE's timestamp, so it measured how old the last
print was rather than whether the feed was delivering. With a 60s poll against
a 60s threshold the measured age lands between 60 and 120 seconds through
entirely normal operation, on any symbol. A trip was arithmetic, not risk.

The two ideas it conflated are now separate:

* **Feed liveness** - measured on *receive* time, reported by
  `MarketDataFeedEvent`, shown as MARKET DATA DOWN. Still deliberately not a
  kill-switch trip: no ticks means no signals, so the danger is that nobody
  notices, not that it trades wrongly.
* **Quote freshness** - measured on the *trade's own* timestamp, reported by
  `DataStaleEvent`, and it now excludes that ONE symbol from signal generation.
  It cannot halt the account. `KillSwitch.check_staleness` is gone and
  `KillSwitchEngine` no longer subscribes to the event.

`DataStaleEvent` gained a `stale` flag so a symbol that prints again is let back
in rather than lost for the session, and it publishes on the *transitions* only.
A stale symbol still has its bars recorded, so its buffer is continuous when it
returns.

Default 60s -> **900s**, which is what the measurement now means: a megacap
prints continuously, a thin or halted one legitimately does not, and sizing
against an hour-old print is the hazard worth naming.

**Operator action:** `QAT_DATA_STALENESS_SECONDS=250000` can come out of the
`.env`. It suppressed a rail that halted sessions; the rail no longer halts
anything, and leaving the override disables the per-symbol exclusion that
replaced it.

### M28 - Cost-truthful measurement  **[DONE, 31 July]**

Fees on `ClosedTrade`, gross and net both retained; cost drag in the Metrics tab
and reports. Expectancy, average R, profit factor and the promotion gate are all
net.

`pnl` was removed rather than redefined, so every call site had to say which it
meant. Costs are apportioned from the *fill*, because the commission floor is
charged once per order - a position closed in three pieces pays one entry
commission, not three.

Two things the plan did not anticipate. A trade stopped at exactly its stop
loses **more than 1R**, since the 1R of price movement is joined by the cost of
having been in the trade; anything sized on "a stop costs 1R" understates every
loss. And the backtester had the same defect in reverse - costs deducted from
equity but gross P&L recorded per trade, so one backtest reported a net CAGR
beside a gross profit factor. Both sides now agree.

Measured at the shipped defaults on a 2% gain: a $20,000 position keeps 0.36R
of a 0.40R gross move, a $2,000 position keeps 0.25R. Against a 0.2R promotion
floor that gap decides whether a strategy qualifies.

**This unblocks M29**, which reads exactly these numbers.

### M29 - Governance consistency  **[DONE, 31 July]**

The policy said "earn autonomy" and the code granted it anyway. Resolved by
binding enforcement to what is actually at stake instead of to a flag someone
has to remember: `promotion_evidence_enforced` is true on **any live account**,
whatever `enforce_promotion_evidence` says.

The external review recommended turning the flag on immediately. That would
have been circular: the bar is 30 closed trades, paper is where those trades
come from, and enforcing it there means nothing trades, so no evidence is
produced, so the bar is never met. Paper collects the evidence; live requires
it. An operator can opt in early on paper; nobody can opt out on live.

This depended on M28 - before it the gate would have enforced a bar computed on
gross figures already known to be optimistic.

**Sequencing note.** An external review recommended enabling this immediately.
Doing so during the paper phase would halt data collection - swing has zero
closed trades against a 30-trade bar, so nothing would trade unattended. Correct
before live money, self-defeating during a paper test. And it must follow M28:
the gate reads expectancy and average R, which are gross today, so enforcing it
first would gate on numbers already known to be wrong.

### M30 - Gap risk as its own concept  **[DONE, 31 July]**

Every risk figure meant *"if the stop fills"*. Measured across 28,987
overnight holds on this universe, **45 (0.16%) gapped through a 2.5x ATR
stop** - the worst costing 2.0R instead of 1R on a -22.1% gap. Real, but
milder than the 6R this section originally assumed.

**Gap risk has its own budget in the governor.** A modelled 6% overnight shock
(just above the 99th percentile of measured moves) applied to *notional*, must
cost no more than 5% of equity across everything held. That implies a
gross-exposure ceiling of about 83%, and it is a different hazard from the
risk-at-stop cap rather than a variant of it.

**Single-name concentration 25% -> 15%, and it now TRIMS rather than refuses.**
That order matters. `PortfolioRiskChecker` returns pass/fail, and 1% risk over
a ~5% stop already sizes swing at about 20% of equity - so lowering the cap
under reject semantics would have refused every swing trade outright rather
than making it smaller. The mechanism had to change before the number could.
Trimming is the established pattern here; the aggregate risk cap has always
worked that way.

**Two defects this exposed:**

* The governor ran only when a caller supplied `positions`, so with an empty
  book the concentration cap fell through to the reject-style checker - the
  first trade of the day was refused instead of sized down. It now runs for
  every buy.
* `PortfolioRiskChecker` could **block a sell**. Lowering the cap to 15% meant
  a 20% position could no longer be exited, because the check ran on the
  resulting concentration and refused it. A rail whose effect is "the account
  may not de-risk" is a broken rail, and this one had been able to do that
  since it was written.

**Sector 40% -> 30%. [DONE]** Held back at first, deliberately: sector was
enforced only in `PortfolioRiskChecker`, which holds the sector map and has no
way to trim, so lowering the number before it could trim would have
reintroduced exactly the refuse-everything failure single-name just had.

`PortfolioGovernor.evaluate` now takes `candidate_sector` and
`sector_by_symbol` and trims against the sector the same way it trims a single
name, counting held positions **and** pending buys - an unfilled order is
committed exposure, and a cap that only sees fills approves a third name while
the second sits in the blotter. It runs before the checker, so the checker
sees the already-trimmed exposure and remains a backstop with no cause to
fire. A candidate with no sector in the instrument map is not gated.

Only then does 30% mean anything: at a 15% single-name cap, 40% never bound
until the third position in a sector was already on. 30% bites at
two-and-a-bit, which is the point - sector is the correlation that survives
having picked different tickers, and it is the one that shows up precisely
when the names stop looking different.

### M31 - Churn control  **[DONE, 31 July]**

`enforce_min_holding_period` and `min_holding_trading_days` had been settings
since M27 and were **read by nothing at all** - the same dead-configuration
pattern as the M13 equity rails and M6 reconciliation before them.

Three rails, all in `SignalToOrderBridge`, which now tracks entry time and
entry stop from `OrderFilledEvent` because a broker `Position` carries neither:

* **Minimum hold** (10 trading days) on signal-driven exits.
* **Loss escape** (0.5R), which is what makes the minimum hold defensible. The
  open tension recorded here was real: a minimum hold blocks a
  signal-*deterioration* exit, which is not protective, so on its own it would
  sit through a broken thesis to save $12 of commission. Above 0.5R down, half
  the risk budgeted for the whole trade is already spent and the hold stops
  applying.
* **Time stop** (30 trading days), the counterweight - the reviewer's framing
  was right that markets do not know what "two weeks" means. One rail stops the
  system churning, the other stops it holding forever on a thesis that never
  resolved. Checked on the tick, so the broker is only asked for positions on
  the rare occasion it fires.
* **Turnover budget** (10 entries per rolling seven days), on entries only. A
  budget that blocked exits would be a rail against de-risking.

None of this can delay a protective exit: the resting broker stop, the delever
sweep and the kill-switch do not come through the signal path. A position whose
entry this application did not record - an adopted one - is never trapped.

### M32 - ASX readiness

**The blocker nobody flagged: there is no ASX market data source.** Alpaca is US
equities only, and the entire live data path hardened through M17/M25/M26 serves
US symbols. Needs a feed decision (yfinance, delayed and unofficial, vs IBKR's
own), currency handling, and the IBKR live path actually exercised.

Also: slippage is modelled at a flat 5bps, optimistic for ASX small and mid caps
where a $20,000 position can be a meaningful share of daily volume.

### M33 - Validation using what already exists  **[DONE, 1 August]**

`scripts/validate_strategy.py` runs Monte Carlo and walk-forward across the
watchlist with the cost model the live system uses. Three findings, all in the
measuring instrument rather than the strategy:

* **Every backtest was costed with no commission floor.** The Workbench built
  `CostModel()` bare at both call sites; that constructor defaults
  `min_commission` to 0.0 so pre-M27 backtests keep their numbers, against a
  configured 6.60. On swing over 40 symbols the drag is 1.5% of gross P&L at
  100k per symbol and 10.4% at 20k - a fixed fee is trivial on a large
  position and ruinous on a small one, and live positions are the small ones.
* **The backtester could hold shorts the live system cannot open.** The signal
  adapter mapped a sell to MINUS conviction. It means close the position -
  swing's carries `exit_reason=trend_broken` - and the live OMS submits buys
  and sells-to-close only. mean_reversion spent 48% of the AAPL series short,
  volatility 45%. A sell now goes flat.
* **Swing barely trades.** Exposure changes 7 times in 300 bars and never
  returns to zero after bar 52 - one trade per symbol in 14 months. So the
  Monte Carlo cone resamples near-buy-and-holds, and walk-forward manufactures
  exactly one entry per window at the slice boundary: 12 symbols, 1 full-run
  trade each, 3 walk-forward trades each. Neither tool says much about swing
  until it exits.

**Correlation is a limit now, not a table.** `PortfolioGovernor` trims against
a correlated cluster the same way it trims single-name and sector: holdings
whose returns track the candidate's at or above 0.70 are capped at 30%
combined. The cluster is defined per candidate rather than as a fixed
partition, which is what correlation actually is.

Sector was the proxy, and the proxy fails in the conditions the limit exists
for - correlations converge in a crisis, and a bank and a homebuilder in
different sectors stop being different at the moment that matters.

**The rail had to be fed before it could bite.** `existing_returns` was an
empty dict in `SignalToOrderBridge`, with a comment calling it a documented
simplification. It made two rails inert rather than lenient: nothing to
correlate against, and `PortfolioRiskChecker` computing portfolio VaR and ES
for a book it believed was empty. The warm start already seeds 300 daily bars
per symbol - the history existed and was never handed over. Series are indexed
by timestamp, not bar number, so correlating two symbols compares the same day;
pairs sharing fewer than 20 observations are skipped, because correlation on a
handful of points is noise. A symbol with no history is NOT assumed
correlated - the opposite of the unknown-stop rule, and deliberately so, since
that default would refuse every symbol the app has never held.

## Already built, despite appearing on review wishlists

Monte Carlo; walk-forward (on the Workbench since M19); regime probabilities and
an exposure scalar the risk engine applies; volatility-targeted sizing (the 1% is
a ceiling, not a constant); EMA rather than simple moving averages; a correlation
table.
