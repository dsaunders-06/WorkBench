# W2 — the research harness — 12 August 2026

Design for the portfolio-level replay harness named in
`2026-08-12-asx-transferable-validation-design.md`. **It is the asset that
survives the ASX move**, it needs no broker, and it is the only instrument that
can answer the questions the live book cannot reach.

**Freeze-compatible by construction.** Nothing here changes which trades happen
or how large they are. The harness reads the trading path; it does not alter it.

## Why the existing tooling cannot do this job

Three instruments exist and **none of them measures the deployed system.**

1. **`VectorizedBacktester` has no ATR stop, no 2R target, no time stop and no
   minimum hold.** Exits happen only when the signal flips. M33 measured the
   consequence: exposure changes 7 times in 300 bars, roughly one trade per
   symbol in 14 months. It measures a different strategy from the one trading.
2. **The replay scripts hand-copy the rules.** `swing_exit_behaviour.py` and
   `swing_rail_sweep.py` re-implement the entry rule, the ATR stop, the target
   and the churn rails inside the script, over yfinance bars, on the ten
   currently-held symbols, over two years. Every figure in "Booked for the
   September review" rests on that base, and a second copy of the rules can
   drift from `swing.py` silently.
3. **No portfolio-level simulation exists at all.** The governor, the
   10-position limit, the 5% aggregate cap, correlation clusters, sector caps,
   VaR/ES, the regime scalar, Kelly bounds and the cost rail are exercised by
   **nothing but live trading.**

And there is a question no amount of live trading can ever answer: **do the
rails help?** The same October cannot be held twice with the correlation cap on
and off. Only simulation produces the counterfactual, which is why M51 has been
open since 5 August waiting for an instrument that does not exist.

## Architecture

**A `SimulatedBroker` implementing `BrokerAdapter`, plus a historical clock.**
Bars flow through the real strategy objects, the real `RiskEngine`, the real
`PortfolioGovernor`, the real `CostModel`, the real regime engine and the real
exit rails. **There is no second copy of the rules, so nothing can drift.**

Rejected alternatives, both recorded because they will be proposed again:

* **Extend the vectorized engine** with stops and targets. Fixes the
  signal-only-exit defect and still cannot run a portfolio, so the rail
  questions stay unanswerable — and it becomes a second implementation to keep
  in step by hand.
* **Formalise the replay scripts.** Cheapest, and it is what already exists. Its
  weakness is demonstrated rather than hypothetical.

### The harness becomes the fourth adapter, and W1.0 already covers it

`SimulatedBroker` joins `AlpacaAdapter`, `IBAdapter` and `MockBroker` in
`KNOWN_ADAPTERS()`, so `test_no_known_adapter_is_missing_a_core_capability`
covers it the day it exists. **If it ever lacks a capability the live path
depends on, a test fails** rather than the harness quietly measuring a book
whose protection was never verified. Add it to the registry in the same commit
that creates it.

### The clock is what makes the regime replay honest

The clock advances one trading day at a time, and the engine only ever sees bars
and macro observations up to the simulated date. **The periodic HMM refit is
therefore fitted on the past rather than on the answer, by the shape of the
harness rather than by a guard that could be forgotten.** No separate
look-ahead check is needed, and none should be added — a guard implies the
default is unsafe.

## The fill model

**Decided: pessimistic. The stop wins any bar that touches both levels.**

A daily bar's low can touch the 2.5×ATR stop while the same bar's high touches
the 2R target, and the bar cannot say which came first. Assuming the stop makes
every expectancy figure a **floor rather than an estimate** — if the edge
survives this treatment it survives reality. The cost is a downward bias of
unmeasured size, accepted deliberately.

**Gaps fill at the open, not at the stop level.** A bar opening below the stop
fills at the open, which is worse. This is the MNST lesson written into the
simulator: an unadjusted stop through a gap does not fill politely at its
trigger, and a fake that pretended otherwise would hide exactly the loss shape
this system has already paid for once.

**Entries fill at the next bar's open plus `CostModel` slippage**, never at the
signal bar's close. The signal is computed from a closed bar; acting on that
same bar's price is look-ahead in its most ordinary form.

`recent_fills` returns protective executions, so **the harness exercises the
M88 absorb path** as a side effect rather than bypassing it.

## Ablation and the run manifest

A run config names which rails are active: position limit, aggregate risk cap,
single-name cap, sector cap, correlation cluster, gap risk, VaR/ES, cost rail,
and the regime gate. **Regime is a rail here, not a fixture** — that is what
makes M51's oldest question answerable.

**Every run emits a manifest**: rails on and off, price series and which
adjustment, universe, period, starting equity, fill model, and the code commit.
A result whose provenance is not recorded is a result nobody can reproduce, and
this project's whole argument is that figures must be derived rather than
remembered.

## Outputs

**Per-trade rows in the `closed_trades.csv` schema.** Harness output and live
output are then read by one set of tools and compared like for like. A separate
backtest schema would guarantee the two could never be checked against each
other, which is the entire point of building this rather than borrowing one.

## G1 — the acceptance gate

**Replay a dated window and compare against `decision_journal.csv`: for each
candidate, the same accept or refuse, and the SAME BINDING RAIL.**

Chosen over the alternatives deliberately:

* **Not "the same closed trades"** — there are two, one of them correctly
  unattributed. That is not a test.
* **Not "the same end-state book"** — one pass/fail that cannot say which rail
  diverged, and compensating errors still produce the right positions.
* **Not "matching refusal counts"** — the same totals can come from different
  decisions, so it is the easiest bar to pass while being wrong.

The binding rail is the diagnostic. Hundreds of decisions are available — 503
refusals in a single night on 5–6 August, each with its rail recorded — so this
is a real target rather than a gesture.

**Tolerated:** price differences inside a day, since daily-bar replay cannot
reproduce a decision taken at a specific second. **Not tolerated:** a different
rail binding, which is precisely what would reveal the harness is wired
differently from production.

**No research runs before G1 passes.** A harness that cannot reproduce what
actually happened is not measuring this system, and every number it produced
afterwards would be unfalsifiable.

## Stated on every run, not buried in a footnote

* **Survivorship.** The universe is a static 100-name megacap snapshot,
  documented in `universe.py` as *"static snapshots, not a live pull of official
  index membership"*. Backtesting a decade on the 2026 list is survivorship plus
  look-ahead of the kind that manufactures an edge. Stated rather than paid to
  fix, because the US numbers are provisional by construction.
* **The earnings rail is inert.** `EarningsCalendar` is forward-only —
  `next_earnings(symbol)` and `trading_days_until(symbol, as_of)` — and the
  yfinance implementation fetches only the next date, so a 2016 replay would
  compare a simulated date against 2026's earnings. `NullEarningsCalendar` is
  used, which the protocol explicitly supports. **Direction of the bias:
  M57's earnings trim never fires, so the harness sizes some entries LARGER than
  live would.** Buying a historical earnings calendar is a later spend decision.
* **The fill model is pessimistic**, so expectancy is a floor.
* **Daily bars only.**

## Out of scope for v1

* **The AI advisory layer.** It cannot place an order, so it changes no outcome
  in a replay. Its value is entirely in whether a human's decisions are better
  with it, which no simulation can measure.
* **Minute-bar resolution of ambiguous days.** Considered and declined with the
  pessimistic fill model.
* **Anything ASX.** The `HistoricalBarSource` port already exists, so an ASX
  source drops in behind the harness later without touching it.
* **Kelly re-estimation, parameter sweeps, and optimisation of any kind.** The
  harness must be trusted before it is used to change anything, and the freeze
  owns those decisions regardless.

## How bars reach the strategy — settled 12 August, and it needs a seam

**The live path builds bars from TICKS.** `MarketDataEvent` carries
`symbol, price, volume, ts`, and both `StrategyEngine` and
`SignalToOrderBridge` keep their own `MultiSymbolAggregator` fed from that
stream. The harness has daily OHLC bars and no ticks.

**One event per day at the close is silently fatal.** A single tick gives
`high == low == close`, `compute_atr` returns ~zero, and ATR sets the stop
distance which sets position size which the 1% and aggregate caps gate on.
Every figure would be wrong and nothing would error.

**`seed()` cannot be reused per-day.** It refuses once any bar exists —
*"seeded history cannot be interleaved with live bars"* — and that rule is
correct.

**Rejected: four synthetic ticks per day (open, high, low, close).** It
reconstructs the true bar with no production change, and buys nothing: the
mid-day evaluations it creates cannot produce mid-day fills, because
`SimulatedBroker` only fills on `advance()`. What it does buy is an arbitrary
choice of whether the high or the low tick comes first, which silently biases
which signals fire — non-determinism inside the instrument built to settle
arguments.

**Adopted: `prime_bar(symbol, bar)`.** Set the FORMING bar to the true daily
OHLC, closing the previous day's forming bar into `_completed` first. Then
publish an ordinary `MarketDataEvent` at that day's close. `add_tick` folds it
in **harmlessly** — `max(high, close)` and `min(low, close)` are no-ops because
the close sits inside the day's range, and `close = price` sets it to what it
already is. Evaluation then runs through the production path unmodified, on a
frame whose latest bar is the true daily bar.

**A first attempt at this was `append_completed`, and it was wrong.** It would
have populated both buffers and never caused the strategy to evaluate, because
evaluation is triggered by the event and not by the bar. Recorded because the
mistake is instructive: the seam had to match how the live path is DRIVEN, not
merely what it stores.

**The cost, stated plainly:** a production change made for the harness's
benefit. It is additive, and it carries the same ordering guard `seed()` has —
refuse a bar that is not strictly after the last, and refuse to prime over a
forming bar from the same boundary.

## Build order

1. `SimulatedBroker` against the `BrokerAdapter` protocol, registered in
   `KNOWN_ADAPTERS()`, with the fill model and its tests. Nothing else.
2. The clock and the session loop — one symbol, no rails, no regime, proving
   bars reach the strategy and orders reach the fake broker.
3. The portfolio: N symbols, the governor, the caps.
4. The regime engine on the simulated clock.
5. G1 against `decision_journal.csv`.
6. The ablation switch and the manifest.

**Steps 1 through 5 produce no research output and are not supposed to.** The
first number this harness produces should arrive after it has proved it can
reproduce a day that already happened.
