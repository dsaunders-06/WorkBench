# W2 step 6 — the ablation switch and the run manifest — 13 August 2026

The last step of the research harness described in
`2026-08-12-research-harness-design.md`. It adds the switch that turns a rail
off, the outcome the switch is measured against, and the manifest that records
what a run may and may not be quoted as saying.

**Freeze-compatible by construction.** No file in the trading path is edited.
Every rail is disabled by setting its existing configuration value beyond
reach, so the shipped `RiskEngine` and `PortfolioGovernor` run exactly as they
trade. See *Rejected: a RailSet threaded through the decision path*.

---

## The finding this design is built around

**No rail in the G1 window has a validated agreement rate.** The 13 August
decision narrowed G1's claim to *"the rails it can exercise agree"*. Checked
against the recorded table rather than restated:

    rail                            agreed  live only  harness only   rate
    Position limit                       0         37             0     0%
    Aggregate risk-at-stop cap           2          2            19     9%
    Approved                             6         14             1    29%
    Cost-to-risk (trade too small)       0          1             0     0%

The narrowing removes the position limit from the scoreboard. **It does not
rescue the result:** the two rails the harness genuinely exercised score 9% and
29%.

The one uncontaminated rail — cost-to-risk — was exercised once, by live only.

### Corrected 13 August, after re-scoring: there are at least two mechanisms

An earlier version of this section explained the aggregate cap's 19
harness-only bindings as the position-limit failure one rail down — live
refusing on capacity while the harness, its book never full, accumulated risk
until the cap caught it. **That explanation was asserted, not measured, and
re-scoring found a second and larger mechanism underneath it.**

**The regime rail is dead in the harness.** Across all 28 harness decisions in
the G1 window, `regime_scalar` is **1.0 on every one**. Live varied it —
0.4 · 0.5 · 0.7 · 1.0 — as a real measurement moving with the market. Cause:
`ReplaySession.run()` starts the regime engine, strategy engine, bridge and
executor, but **never starts the `RiskEngine`**, and `RiskEngine.start()` is
what subscribes to `RegimeEvent`. The scalar stays at its constructor default
forever.

Measured consequence on SPY, 31 July — the two sides agree on everything except
the scalar:

| | live | harness |
|---|---|---|
| price | 745.07 | 746.79 |
| stop distance | 19.53 | 20.91 |
| stop source | strategy | strategy |
| equity | 100,660 | 100,000 |
| **regime scalar** | **0.4** | **1.0** |
| cost-to-risk | 13.8% → **refused** | 7.3% → **approved** |

A harness sizing up to 2.5× larger than live consumes a 5% aggregate
risk-at-stop budget in four positions rather than ten, which is a direct and
sufficient account of harness-only cap bindings without invoking the position
limit at all.

**Settled by fixing it: cadence dominates, and the scalar was not the cause.**
Starting the risk engine and re-running left the verdict bit-for-bit identical.
Both mechanisms were real; only one was load-bearing.

The cadence difference is visible on 31 July as four single-row live approvals —
AMD, C, CVS, MU — where live approved seconds after the bell on the prior day's
frame and the harness, evaluating that day's closed bar, produced no decision
at all. It was already the better-supported reading: live ran at scalar 1.0 for
whole sessions (594 rows on 5 August, 299 on 11 August) and those days still
scored zero exact, so the scalar could never have been the whole story.

**What changes for this design:** the regime gate is the rail M51's oldest
question is about, and the original harness spec says *"Regime is a rail here,
not a fixture — that is what makes M51's oldest question answerable."* **It is
currently a fixture, pinned at 1.0.** Ablating it today would compare 1.0
against 1.0 and report no difference. The manifest's `exercised` field is what
would have caught that, which is the argument for the field — but the
subscription has to be fixed before any regime ablation means anything.

**What follows for step 6.** An ablation measures the difference between two
*harness* runs. That difference is real and measurable. Reading it as *what
this rail costs the live system* requires the harness to bind rails as live
does, and no rail has yet shown that it does. So the claim is scoped in the
instrument rather than in a reader's memory: **every result this step produces
says what a rail costs inside the harness, and the manifest says so in the
file.**

Decided by the operator on 13 August, with the alternatives costed: closing the
fidelity gap first (intraday evaluation, minute bars, a materially heavier
harness) was declined for now, and re-scoring G1 on 31 July alone — the one day
live also started from an empty book — remains available and cheap.

---

## Second finding: the harness has no outcome to measure

**`ReplaySession` records no closed trades.** Two gaps, both found by reading
the code against the spec:

* **`TradeLedger` is not wired in.** `replay_session.py` builds the OMS,
  strategy engine, bridge, regime engine, journal and executor. No ledger.
* **`absorb_broker_fills` is never called.** `oms.py:1359` is the only place an
  `OrderFilledEvent` is published for a protective execution, and across the
  repository that method is invoked by the live runtime and by tests — never by
  the replay.

So when `SimulatedBroker._execute_protective` fires a stop, the position leaves
the book, the governor's position count correctly falls, and **nothing records
the trade.** No P&L, no expectancy, no R-multiple.

The harness design document asserts both as done — §Outputs says *"Per-trade
rows in the `closed_trades.csv` schema"*, and the fill model says `recent_fills`
means the harness *"exercises the M88 absorb path as a side effect rather than
bypassing it"*. Neither was true.

**Counted separately from the §4.x register in `ROADMAP.md`**, which stands at
eight across seven milestones and is about the brief. This is the same failure
in a different document — a spec describing what was intended as though it were
what was built — and it was found the same way: by reading the code against the
prose instead of trusting the prose.

**It is decisive for this step.** An ablation switch with no outcome can only
compare which rails bound, never whether the rails helped — and *do the rails
help* is M51's question and the reason the harness exists.

---

## What gets built

### 0. Start the `RiskEngine`

One line, and it is the prerequisite for everything else here.
`ReplaySession.run()` starts four engines and omits the fifth, so the risk
engine never subscribes to `RegimeEvent` and the regime rail is inert. Add
`await self.oms.risk_engine.start()` beside the others, and its `stop()` in the
`finally` block.

**Done, and re-run, 13 August.** The scalar now moves: 0.7 across the window,
1.0 for the first few decisions of day one.

**The verdict did not change.** exact 6 · partial 2 · disjoint 12 · live-only 38
· harness-only 8 — identical, and 31 July identical too, SPY still disjoint.

That is worth more than a passing note, because **this section predicted the
opposite**: *"every figure in the window was produced by a harness sizing
against a scalar the live book never used, so the current verdict is not a
measurement of cadence alone."* Measured, it was. The dead subscription was a
real defect and not the explanation for the disagreement, and the 13 August
cadence account survives a test it could have failed.

Two things the re-run surfaced instead, both bearing on the regime ablation:

* **The harness classifies 0.7 for the entire window; live moved 0.4 · 0.7 ·
  1.0 · 1.0 · 1.0.** Daily-bar classification through `HysteresisGate` and a
  20-bar refit interval is far stickier than live reclassifying intraday on a
  forming bar. The rail is alive but nearly constant, so an ablation against it
  measures one regime label rather than a varying one — a fidelity limit of the
  same family as the accepted cadence limit, and it must appear in the
  manifest beside `exercised`.
* **The regime updates only when the benchmark's bar is published.** `_one_day`
  iterates `self.bars`, and the regime engine reclassifies on SPY's
  `MarketDataEvent`, so every symbol iterated before SPY that day is evaluated
  against the PREVIOUS day's regime. It is why SPY itself was still at 1.0 on
  31 July and still disjoint. Live has no such split - the regime is current
  before any symbol is evaluated. Publishing the benchmark first would close
  it; recorded here rather than fixed, because it changes which trades the
  harness takes and belongs in a plan rather than in a footnote.

**The general lesson, and it is a new one.** The harness's three known seams
were all about a *clock* — `prime_bar`, `SignalToOrderBridge(clock=)`,
`RiskEngine(clock=)`. This is a different family: a production object correctly
constructed, correctly wired, and **never started**, so a subscription the live
app has is one the harness silently lacks. Nothing errors. The rail simply
holds its default forever, and the default is the permissive value.

Worth a test of its own shape: *every Engine the live runtime starts is started
by the harness too*, derived from the runtime's own registration list rather
than from a hand-written one.

### 1. The outcome: `TradeLedger` and a daily absorb sweep

`ReplaySession` gains a `TradeLedger` on its own bus and data directory, and
calls `await self.oms.absorb_broker_fills()` once per simulated day, **after
`broker.advance()`** — the advance is what fires stops and targets, so absorbing
before it would sweep a book nothing had happened to yet.

Additive and harness-side. No production file is edited: the ledger and the
absorb method both ship today and are simply not connected in the replay.

**The order within a day becomes:**

    1. prime the day's true OHLC into BOTH aggregators
    2. publish MarketDataEvent at the close, which triggers evaluation
    3. advance the broker, filling yesterday's entries at today's open
       and firing any stop or target the day's range touched
    4. absorb broker fills, turning those executions into ClosedTrade rows

Step 4 is new. Steps 1–3 are unchanged.

**The M88 absorb path is now genuinely exercised**, which the design document
already claimed and which nothing until now delivered.

### 2. The switch: `AblationConfig`

A rail is turned off by constructing `Settings` with its knob set beyond reach.
The mapping is data, held in one place, and every value is inside the field's
own validator:

| Rail | Knob | Default | Neutral | Genuinely off? |
|---|---|---|---|---|
| Position limit | `max_concurrent_positions` | 10 | `10_000` | yes |
| Aggregate risk-at-stop | `max_aggregate_risk_at_stop_pct` | 0.05 | `1.0` | **no — see below** |
| Single-name cap | `max_single_name_concentration_pct` | 0.15 | `1.0` | yes, under no-leverage |
| Sector cap | `max_sector_concentration_pct` | 0.30 | `1.0` | yes, under no-leverage |
| Correlated cluster | `correlation_cluster_threshold` **and** `max_correlated_cluster_pct` | 0.70 / 0.30 | `1.0` / `1.0` | yes |
| Gap-risk budget | `max_gap_risk_at_shock_pct` | 0.05 | `1.0` | yes — 16.7× equity at a 6% shock |
| Portfolio ES | `portfolio_es_limit_pct` | 0.03 | `1e6` | yes — no upper validator |
| Cost-to-risk | `max_cost_to_risk_pct` | 0.10 | `1.0` | **no — see below** |
| Minimum hold | `enforce_min_holding_period` | True | `False` | yes, a real boolean |
| Time stop | `enforce_time_stop` | True | `False` | yes, a real boolean |
| Weekly churn cap | `max_entries_per_week` | 10 | `10_000` | yes |
| Earnings trim | `enforce_earnings_event_risk` | True | `False` | yes — but inert already |
| Regime gate | *no knob* | — | do not start `RegimeEngine` | yes |

**Two rails cannot be made perfectly absent, and the manifest says so rather
than the table pretending otherwise:**

* **Aggregate risk-at-stop at 1.0** still refuses when risk-at-stop reaches 100%
  of equity. Reachable only through positions carrying no known stop, which the
  governor deliberately counts at full value.
* **Cost-to-risk at 1.0** still refuses a trade whose round trip exceeds its
  entire 1R. That is a trade the harness should arguably refuse anyway, but it
  is not nothing, and calling it nothing is how a floor becomes an estimate.

**The regime gate has no configuration knob** — it arrives as
`RegimeEvent.exposure_scalar`. Ablating it means not starting the regime engine,
leaving `RiskEngine.regime_scalar` at its 1.0 default. Harness-side, and it is
what makes M51's oldest question askable: *is the regime scalar earning its
place*.

#### The trap that would have ruined the first result

**The cost rail must be ablated with `max_cost_to_risk_pct=1.0`, never with
`apply_costs_in_paper=False`.**

That flag is read twice: by `RiskEngine._costs_apply()` for the rail, and by
`TradeLedger.__init__` (`trades.py:442`) for whether costs are charged into
recorded P&L. Switching it would disable the rail *and* make every trade free,
so the no-rail arm would win for a reason having nothing to do with the rail.
One flag, two consumers, and the confound is invisible in the output.

`AblationConfig` therefore refuses `apply_costs_in_paper` as an ablation knob by
name, with that reason in the error.

#### Refuse what cannot be neutralised

A rail named for ablation that has no entry in the table raises rather than
silently running a baseline twice and reporting no difference. **A run that
measured nothing must not be indistinguishable from a rail that costs nothing** —
that is the shape of the 12 August corporate-actions failure, where a swallowed
query made blindness look like a quiet book.

### 3. The manifest

Every run writes `manifest.json` beside its outputs. Fields, and why each is
there rather than in a reader's head:

```
run_id, created_at
code_commit          git rev-parse HEAD, plus a dirty flag
rails                per rail: enabled, knob, value, bound_count,
                     exercised, live_agreement
universe             symbols actually replayed, after bar fetch
period               first and last session, session count, warm_bars
bars                 source, feed (iex/sip), adjustment, interval
starting_equity
fill_model           the five decisions, as booleans and enums
stated_limitations   survivorship, earnings rail inert, daily bars only,
                     pessimistic fill
outputs              paths to closed_trades, risk_decisions, decision_journal
```

Three fields carry the scoping the operator approved:

* **`bound_count`** — how many times that rail actually bound in *this* run,
  derived from the run's own `risk_decisions.csv` through
  `refusals.rail_of`. The existing classifier, not a second one: a private
  copy would drift, and the Blotter and the manifest disagreeing about which
  rail bound would leave nobody able to say which was right.
* **`exercised`** — `bound_count > 0`. A rail that never bound reports **not
  exercised**, never *no difference*.
* **`live_agreement`** — read from the verdict `run_g1.py` writes, not typed.
  Today every rail reads `unvalidated` or carries G1's measured rate.

**`run_g1.py` gains one line: it dumps its `Verdict` to `g1_verdict.json`.**
Derived, not remembered — the alternative is a constant somebody updates by
hand, and four hand-maintained counts were wrong in three days.

### 4. The comparison

`compare_runs(baseline, ablated)` reads two manifests and two
`closed_trades.csv` files and reports: trade count, win rate, mean R, total R,
and the binding counts for every rail.

**It leads with a guard, not with a number.** If the ablated rail's
`bound_count` in the **baseline** run is zero, the comparison prints

    NOT EXERCISED - <rail> never bound in the baseline run.
    This comparison measures nothing about that rail.

and reports no difference figure at all. Suppressing the number rather than
printing a zero beside a caveat: a zero gets quoted and the caveat does not.

On today's evidence the position limit will trip this guard on the G1 window,
which is the correct behaviour and the reason the guard exists.

---

## Rejected alternatives

**A `RailSet` threaded through `RiskEngine` and `PortfolioGovernor`** with
`if enabled(...)` guards. "Off" would be genuinely off, and the two imperfect
rows in the table above would disappear. Declined: it puts new branches inside
the code that decides which trades happen, during a freeze whose test is
*would this change which trades happen*. A guard defaulting to on is still an
edit to the decision path, and it creates the second implementation of the
rules that this whole harness exists to avoid.

**Ablating by not calling the governor at all.** Cheaper than either, and it
disables six rails at once with no way to attribute a difference to any one of
them. The question is which rail earns its place, so the switch has to be
per-rail.

**Recording the ablation result without the outcome wiring** — comparing
approval counts instead of trades. It is what the harness can do today, and it
answers a different question: *how often did the rail bind*, which the audit
trail already records, rather than *did the rail help*.

---

## Testing

* **The mapping is exercised, not asserted.** For each rail: a run with it
  enabled that binds it, and a run with it neutralised that does not. A table
  entry whose neutral value fails to neutralise fails a test rather than
  producing a quiet zero.
* **`apply_costs_in_paper` is refused by name**, with the two-consumer reason.
* **A rail with no table entry raises.**
* **The absorb sweep produces a `ClosedTrade`** when a simulated stop fires —
  the wiring's whole purpose, and it is what nothing currently proves.
* **The comparison suppresses a difference** when the baseline `bound_count` is
  zero.
* **Every test that builds an OMS passes its own `data_dir`.** The standing
  constraint: `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store
  persists there, so one declared anomaly leaks a quarantine into every later
  test.
* **Any script run outside pytest passes its own `data_dir`.**
  `Settings(_env_file=None).data_dir` resolves to the LIVE data directory, which
  is how a probe wrote a row for symbol `AAA` into the live record on 12 August.

## Out of scope

* **Parameter sweeps and optimisation.** The harness must be trusted before it
  is used to change anything, and the freeze owns those decisions regardless.
* **Forcing a full book to make the position limit bind.** Available — the
  `OpeningPosition` seam exists — and deliberately not used here. A forced book
  is a synthetic setup rather than the observed one, and a difference measured
  against it is weaker evidence than the guard's honest silence.
* **Intraday evaluation.** The revisit trigger, declined on 13 August and still
  the thing that would make these numbers transferable to the live system.
