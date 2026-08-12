# An ASX-transferable validation programme — 12 August 2026

Design for the work between the M39 deploy and the operator's decision on
whether to move to the ASX sooner rather than later.

**The premise, stated by the operator on 12 August:** the destination is the
ASX, and if the move becomes a strong proposition it will be called early — the
preference is to spend six to twelve months validating in the destination market
rather than in the staging one.

Everything below follows from that single sentence, because it changes what the
current work is *for*. ROADMAP has recorded since 6 August that the trial's edge
numbers do not transfer and that what genuinely validates is the MACHINERY. That
was written as a caveat. **This design treats it as the design constraint.**

## The rule this design applies

> Between now and the call, everything built is either market-agnostic, or cheap
> enough to abandon.

Transferable, and therefore worth building now: the machinery, the research
harness, the data ports, the evidence framework, the safety infrastructure
(M39, M43, M60). Not transferable, and therefore no longer a deliverable: US
expectancy figures. They become validation of the instrument rather than
evidence about the strategy, and this design says so everywhere they appear so
that nobody later defends a number this document already discounted.

## Two findings from scoping, which move the estimate

Taken by reading the tree on 12 August, before any of the work below was
proposed. Both were checked rather than assumed, and both contradict a
one-line status in ROADMAP.

### The IBKR path is further along than ROADMAP admits

ROADMAP says *"`ibkr` exists in the broker list and is unimplemented beyond the
seam."* Measured:

| | |
|---|---|
| `src/qat/data/broker/ib_adapter.py` | **223 lines** — connection, heartbeat, reconnect-with-backoff, a live-port guard, a read-only mode |
| `ib_client_protocol.py` / `ib_translate.py` | present, 60 and 71 lines |
| `MARKET_COST_PROFILES` in `costs.py` | already carries `("ASX", "fixed")` and `("ASX", "tiered")` |

The cost model's own docstring says *"Market-aware, because IBKR prices each
market differently and **live trading starts on ASX**."* The cost model was
built for the destination from the beginning. **The move is not starting from
zero.**

### And the gap is concentrated exactly where it hurts

`IBAdapter` implements eight of `BrokerAdapter`'s methods. The four it does not
implement are:

    recent_fills   resting_stops   resting_stop_orders   announcements

Which is to say: **fill absorption, protective-order integrity, and
corporate-action detection.** Every lesson from M31d, M33d, M47, M48, M60 and
M39 lives behind those four names, and every one of them was learned by
measuring what Alpaca actually returns rather than by reasoning about what its
parameter names suggest — the mistake ROADMAP records as having disrupted three
consecutive sessions.

**So the ASX cost is not spread thinly. It is concentrated in the subsystems
that were most expensive to get right, and it is measurement work before it is
coding work.** That is the scope of W1, and it is why W1 is measurement rather
than building.

### The absence is silent, which is what makes it expensive

Checked rather than assumed, after the claim above was challenged. **Those four
methods are optional by design, not missing by omission.** The protocol
documents a fallback for each — *"Adapters that cannot answer return an empty
tuple, which reads as 'unknown' rather than 'none'"* — and the callers honour it:
`getattr(self.broker, "resting_stops", None)`, with `verify_position_stops`
returning early because *"an adapter without the capability must not be read as
'no stops rest anywhere', which would drop every stop the app holds."*

Nothing crashes. Nothing corrupts. **Which is worse, not better:** on IBKR as it
stands, M31b's protection verification, M34/M48's fill absorption and M39's
corporate-action detection all become no-ops, silently, as a *supported*
configuration. The app would report perfect health while verifying nothing.

That is the shape of the defect fixed on 12 August — blindness indistinguishable
from a quiet book — and it means the cost is not "write four methods". It is
that the whole protective layer degrades quietly when they are absent, and
nothing currently says so.

### Two hazards found by the same check

* **`broker=ibkr` never reaches `IBAdapter`.** `runtime.py` logs a warning and
  returns `MockBroker(seed=1)`. Configuring the destination broker today yields
  **seeded fabricated data and one log line.** Harmless while nobody sets it;
  lethal on the morning of the cutover. It sits in the same resolver whose
  neighbouring docstring records `MockMacroSource` feeding `random.uniform(-1, 5)`
  to the regime engine for twenty-five milestones with nothing saying so.
* **No conformance test exists.** `tests/data/broker/test_ib_adapter.py` tests
  what `IBAdapter` does; **nothing in `tests/` asserts that any adapter satisfies
  `BrokerAdapter`.** The capability gap is invisible to all 1,964 tests — the
  same sentence as the two M39 defects that only deploying found.

## W1.0 — the static capability audit, before any IBKR contact

**Because "four methods" is a reading, and this project's rule is derive, do not
remember.** The spike answers what each method costs; it cannot answer whether
four is the right number. This does.

* a **capability matrix**, derived on demand rather than recorded —
  `scripts/broker_capabilities.py` prints every adapter against every
  `BrokerAdapter` method, and prints what each gap costs. **Run it rather than
  quoting the figure below**, which is true on 12 August and has no way of
  staying true;
* a **test that fails when an adapter lacks a capability the live path depends
  on** — M80's *ask what reads it*, pointed at the broker port;
* the **resolver fixed** so `broker=ibkr` cannot silently resolve to a mock.

An hour or two, no trading behaviour touched, and its output becomes the
checklist W1.1 measures against — so it makes the spike cheaper as well as
sounder. **It de-risks the ASX call more than the broker probing does**, because
it replaces an estimate with a derived list.

## W1 — the ASX feasibility spike

**Purpose: produce the costed inventory the operator's call gets made against.**
ROADMAP records the ASX blocker as a status — *"no ASX data source and Alpaca
cannot transact on the ASX"* — and it has never been costed. Nothing currently
distinguishes a week of work from a quarter.

Probe scripts in `scripts/analysis/`, the same pattern as
`probe_feed_entitlement.py`, `probe_live_announcements.py` and
`probe_alpaca_splits.py`. **Read-only. Nothing here changes application state or
trading behaviour, so none of it touches the freeze.**

### W1.1 — what IBKR actually returns

For each of the four unimplemented methods, and against a paper account:

* **`resting_stop_orders` / `resting_stops`** — does IBKR return a protective
  leg when its parent has filled? This is the exact question that cost M31d,
  M33d and a session of duplicate OCOs on Alpaca. The answer must be measured
  against a real account with a real resting stop, not inferred from
  documentation.
* **`recent_fills`** — what does it bound on? Alpaca's `after=` filters on
  `submitted_at` rather than fill time, which is what M48 exists to work around.
* **`announcements`** — does IBKR expose corporate actions through the API at
  all? If not, M39's detector needs an entirely new producer, and that is the
  single largest ASX-specific item in the inventory.
* **Order shapes** — does the ASX support the OCO and bracket forms the OMS
  depends on, and will IBKR hold a GTC stop on an ASX symbol? A market where
  protective orders cannot rest at the broker is a different system, not a port.

### W1.2 — ASX market data

Which vendor supplies ASX daily bars, corporate-action adjusted, and at what
cost. Point-in-time universe membership including delisted securities is the
discriminator, because it is the difference between research that is clean and
research that is decorated survivorship bias.

**Worth recording for the decision:** point-in-time ASX data with delisted names
is commercially available in a way that historical US index membership is not.
**ASX research may therefore be cleaner than US research**, which is an argument
for the move that has nothing to do with the strategy.

### W1.3 — what the app assumes that the ASX breaks

An inventory, not a fix list:

* session hours and the opening/closing auctions, against session logic written
  for a 13:30 UTC open;
* T+2 settlement and its effect on cash reconciliation;
* tick sizes, and the **$500 minimum marketable parcel** — this one reaches
  position sizing directly and is not a display concern;
* ASX corporate actions arrive as company announcements, not through an
  Alpaca-shaped API;
* halts are announcement-driven, which changes the shape of M43 rather than the
  need for it.

### W1.4 — live-account safety review

**Triggered by the operator opening an IBKR account, and required before any
IBKR credentials exist in configuration.**

Until now every configuration mistake in this system has cost paper money. A
live account ends that permanently, and one guard is already asymmetric —
`ib_adapter.py:74`:

    trading_mode=live, not confirmed  ->  raises LiveTradingNotConfirmedError
    trading_mode=paper, live port     ->  logger.warning, then CONNECTS

`_LIVE_PORTS = {4001, 7496}`. A config claiming paper while pointed at a live
Gateway connects, and every downstream decision keyed on `is_live` reads False
while real orders are reachable. **Inert today** — `broker=ibkr` resolves to
`MockBroker` and no account exists behind it. The moment both change, a log line
is the only thing between a port typo and live orders, in a system whose own
history says a warning nobody reads is indistinguishable from silence.

* the port warning becomes a **refusal**;
* every consumer of `is_live` re-checked now that the flag guards real money
  rather than a paper account;
* `read_only=True` as the default posture for all spike probing.

### W1 deliverable

One document: per subsystem, **transfers / needs re-measuring / needs rebuild**,
each with an estimate and each citing the measurement it rests on. **Gate G0.**

## W2 — the research harness

**This is the main build, and it is the asset that survives the move.**

### Why the existing tooling cannot do this job

Three separate instruments exist and none of them measures the deployed system:

1. **`VectorizedBacktester` has no ATR stop, no 2R target, no time stop and no
   minimum hold.** Exits occur only when the signal flips. M33 measured the
   consequence — exposure changes 7 times in 300 bars, roughly one trade per
   symbol in 14 months. **It measures a different strategy from the one
   trading.**
2. **The replay scripts hand-copy the rules.** `swing_exit_behaviour.py` and
   `swing_rail_sweep.py` re-implement the entry rule, the ATR stop, the target
   and the churn rails inside the script, over yfinance bars, on the ten
   currently-held symbols, over two years. Every figure in "Booked for the
   September review" rests on that base. A second copy of the rules can drift
   from `swing.py` silently, and a selected ten-symbol set is by definition the
   sample ROADMAP already says is *"good enough to rank options against each
   other and not good enough to size a book on."*
3. **No portfolio-level simulation exists anywhere.** The governor, the
   10-position limit, the 5% aggregate cap, correlation clusters, sector caps,
   VaR/ES, the regime scalar, Kelly bounds and the cost rail are exercised by
   **nothing but live trading.** No amount of per-symbol backtesting can answer
   whether a rail that binds across a book improves outcomes.

### Approach — drive the production decision path

A `SimulatedBroker` implementing the existing `BrokerAdapter` protocol, plus a
historical clock, so bars flow through the **real** strategy objects, the real
`RiskEngine`, the real `PortfolioGovernor`, the real cost model and the real
exit rails. `mock_broker.py` (238 lines) is the starting point.

**Rejected: extending the vectorized engine.** It would fix the signal-only-exit
defect, but it still cannot run a portfolio, so the rail questions stay
unanswerable — and it becomes a second implementation of the rules to keep in
step by hand.

**Rejected: formalising the replay scripts.** Cheapest, and it is what already
exists. Its weakness is already demonstrated rather than hypothetical.

The recommended approach is the only one where **what is measured is the system
that gets promoted**, because there is no second copy of the rules to drift. It
also transfers to the ASX for nothing, since it sits behind the same port the
IBKR adapter does.

### What it must do

* **Portfolio-level.** N symbols, one equity curve, real position limit, real
  aggregate risk cap, real correlation and sector caps, real regime scalar.
* **Rails on/off ablation.** Any rail can be disabled for a run and the
  difference measured. This is what finally makes M51 and portfolio-risk
  validation answerable, and it is the reason the harness is worth building
  rather than borrowing.
* **Emit trades in the `closed_trades.csv` schema.** Backtest and live evidence
  then share one set of analysis tools and are comparable like for like. A
  separate backtest schema would guarantee the two can never be checked against
  each other, which is the whole point.
* **Record which price series it ran on, adjusted or unadjusted.** The
  adjusted-history / unadjusted-live seam is exactly what MNST exploited.

### Acceptance test, which is the whole design

**The harness must reproduce the live record.** The two closed trades. The
refusals in `decision_journal.csv`. The 5.01%-against-5.00% cap breach that is
currently refusing every entry.

A harness that cannot reproduce what actually happened is not measuring this
system, and every number it later produces would be unfalsifiable. This is
`G1`, and no research runs before it passes.

## W3 — the data foundation

`HistoricalBarSource` is already a port with Alpaca, yfinance and synthetic
implementations, so an ASX source drops in behind the harness without touching
it. Two honesty items rather than build items:

* **The US universe is a static 100-name megacap snapshot**, documented in
  `universe.py` as *"static snapshots, not a live pull of official index
  membership."* Backtesting a decade on the 2026 megacap list is survivorship
  plus look-ahead of exactly the kind that manufactures an edge. Under this
  design the bias is **stated on every US result** rather than paid to fix,
  because the US numbers are provisional by construction.
* **SIP historical is free on this account** and `Position.current_price` is the
  consolidated tape, both measured. The IEX 4.3%-of-volume problem blocks M85's
  volume profile and live-bar indicators; it does not block daily-bar research.
  **No new US price vendor is required.**

## W4 — the live session, continuing unchanged

The session runs on. **Its purpose is restated, not extended:** machinery,
execution quality, reconciliation and abnormal-event handling. Not expectancy.

The arithmetic that forces this is not in dispute — 2 closed trades in 12 days
against 30 per strategy, with the aggregate cap breached so current throughput
is zero. Forward paper trading in this configuration cannot produce a
statistically meaningful sample this decade, and asking it to is what made the
timeline look like an evidence problem when it is an instrument problem.

| Date | Item |
|---|---|
| Weekly | Read M39's shadow log. It accumulates judgement against real announcements at zero risk, and CRWD is already a recorded correct rejection |
| **20 Aug** | **Rails held.** Chasing 30 US closed trades stops being worth the disruption once the edge numbers are known not to transfer. **One slot freed deliberately** |
| **21 Aug** | **SFBS 2-for-1 — widen the stop beforehand.** The only dated chance to observe a split where the position survives to the share adjustment. M39 Phase 2 has zero observations and stays that way otherwise. Safety machinery, and it transfers to any market |
| **After 21 Aug** | **M66.** It is market-agnostic code and it is genuinely wrong. It also raises the measured figure on an already-breached cap, so deploying it first would take back the slot bought for SFBS |

## W5 — the evidence framework

One new item, and it is the one that resolves the throughput problem at its
root.

**Split the promotion gate in two.**

| Gate | Evidence source | Sample | Asks |
|---|---|---|---|
| **Machinery gate** | Live paper | Small — tens | Does protection rest and get repaired, are fills absorbed, does reconciliation hold, are abnormal events handled, is the journal complete, does realised slippage match the model |
| **Edge gate** | Harness + out-of-sample | Large — hundreds | Expectancy, R distribution, drawdown, regime behaviour, whether the rails help |

A single 30-closed-trade gate is currently asked to do both jobs and can do
neither: it is far too small for the second and needlessly slow for the first.
Splitting it lets live trading answer the questions it is actually good at, at
the sample size it can actually reach.

M51 then becomes a standing harness report — which rails bind, how often, how
much capital they withhold, and what the counterfactual outcome was — rather
than a one-off review that has been deferred since 5 August for want of an
instrument.

## Explicitly not doing

Under the freeze, and pointless before the harness can evaluate them:

* M84 / M85 activation;
* regime logic changes;
* Kelly changes, including the 0.55 / 1.5 placeholders;
* a portfolio optimiser or candidate ranker;
* any strategy parameter change.

Candidate ranking in particular is inherently portfolio-level and **cannot even
be specified** against a per-symbol engine. It waits for W2 by necessity, not by
preference.

## How this decomposes

**This is a programme, not one implementation plan, and it should not be built
as one.** W1 is measurement and produces a document; W2 is a substantial build
with its own acceptance test; W4 is already running and needs no plan at all.

Each gets its own plan → implementation cycle, in this order:

1. **W1 and W2 start together.** W1 is probe-heavy and mostly waiting on a
   broker; W2 is build-heavy and needs no broker. They do not contend.
2. **W3** folds into W2 as it is needed — the port already exists, so there is
   nothing to build until an ASX source is chosen at G0.
3. **W5** is written once the harness can produce the figures the gates cite.
   Writing thresholds before the instrument exists would be designing measures
   against imagined data, which is the mistake the walk-forward numbers already
   made and which M51 was deferred to avoid repeating.

## Gates

| | |
|---|---|
| **G0** | W1 inventory complete → **the operator's ASX call** |
| **G1** | Harness reproduces the live record → research may begin |
| **G2** | First rails ablation results → M51 has answers |
| **G3** | ASX go / no-go against measured numbers rather than estimates |

## What this design does not claim

It does not claim the swing strategy has an edge; nothing here assumes one.
It does not claim the US results will be worth defending; the design says
repeatedly that they will not be. And it does not claim the ASX move is cheap —
**it claims only that the cost is currently unknown, that it is knowable within
days, and that it is concentrated in four named methods.**
