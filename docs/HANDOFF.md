# Handoff — 13 August 2026, end of day

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

## ⚙️ Before quoting any figure in here, run this

    .\.venv\Scripts\python.exe scripts/handoff_state.py

It derives the deploy gap, the milestone list and the test count from the
repository, and **names any test count in this file that has gone stale**. Every
current-state number here is a hand-maintained copy, and this project lost that
argument four times in three days: the deploy gap was quoted as five, eight,
nine and twelve; "the brief has been wrong in detail" as third, fifth, sixth and
FIVE; the test count sat at 1,690 in three paragraphs while the suite moved on.
**Counting is not the fix — deriving is.**

---

# Where this stands, in one paragraph

**M88 is deployed and running, the deploy gap is zero, and the overnight
session ran clean end to end.** The ASX moved from eventual destination to
near-term one on 12 August, which reframed the trial rather than pausing it:
throughput was never going to prove an edge — 2 closed trades in 12 days
against 30 per strategy, cap breached so the number is zero — and under the new
framing it does not have to. **The binding constraint stopped being evidence
and became instrumentation.** The research harness is five steps of six built,
and **G1 has now run and did not pass** — for a reason that is a fidelity limit
rather than a defect, accepted deliberately with its costs named. The 20 August
review still matters and now has its first concrete data point.

---

# 🌙 SESSION DEBRIEF — overnight 12–13 August

**Ran clean end to end.** Started 23:30:17, stood down 06:00:18. No
intervention, no code change, nothing that threatened the test.

| | |
|---|---|
| Build during the session | `M39+M87 (67677bc)` — M88 was still undeployed |
| ERROR / CRITICAL | 0 |
| MARKET DATA DOWN | 0 |
| Kill-switch / reconciliation mismatch | 0 |
| POSITION UNPROTECTED | 0 |
| Broker-side fills | 0 — so M88's open absorb window cost nothing |
| Closed trades | 0, `closed_trades.csv` unchanged |

**The regime classified at the bell**, four seconds after open: `low_vol`,
exposure scalar 1.00, on VIX 15.46 and curve 0.81. Mass was
`low_vol 0.39 · sideways 0.22 · bear 0.20` — 0.61 inside swing's suitable set,
so swing was eligible at full size all night. The sideways-default warning did
not recur after the open.

## The one event, and it matters for 20 August

**AXP fired swing's entry condition and was refused 108 times by the position
limit**, 04:09 to 05:59, first refusal at $341.90.

The machinery working exactly as designed: a real setup, correctly identified,
correctly refused because the book is at 10 of 10. The decision journal deduped
108 evaluations to a single `rejected` row (M31b behaving properly).

**It is also the first concrete evidence of what the 10-position cap costs** — a
valid swing setup arrived and could not be taken. One night, one symbol, not
enough to argue from, but exactly the observation the 20 August review needs.

## Minor, noted not escalated

41 staleness exclusions and 41 recoveries, every one cleared. The 23:30:22 burst
was symbols that had not printed since the previous close; the rest were thin
symbols crossing the 15-minute threshold mid-session (`DE`, `REGN` twice, `NOC`)
and returning within seconds. Macro polled hourly with all five FRED series live
throughout.

---

# 🚀 M88 DEPLOYED — 13 August 19:58

    Build: M88 (45980a5, built 2026-08-12 20:41 UTC, packaged)
    10 of 10 positions carry a stop - 2 closed trades and 10 lots restored
    CRWD announcement restored and correctly inert - 0 ERROR since launch
    Deploy gap: 0

**The absorb window is closed in the running build for the first time.**
Tonight is the first session M88 has ever run — the previous night was
completely inert, zero broker-side fills, so the changed fill-absorption path is
still unexercised in production. **If a stop or target fires tonight, that is
its first real test**, and it is the thing to have eyes on rather than the quiet.

**The deploy nearly proceeded on a backup that did not exist.** See the sandbox
finding below — it is the most important operational lesson of the last two days.

---

# 🔬 G1 RAN, AND DID NOT PASS

    symbol-days: exact 6 - partial 2 - disjoint 12 - live-only 38 - harness-only 8

    rail                            agreed  live only  harness only   rate
    Position limit                       0         37             0     0%
    Aggregate risk-at-stop cap           2          2            19     9%
    Approved                             6         14             1    29%
    Cost-to-risk (trade too small)       0          1             0     0%

**The dominant failure is structural, not a bug.** Live evaluates every 60
seconds against a FORMING bar and filled its book on day one — 32 approvals on
31 July. The replay evaluates once per CLOSED bar, approved 7 across the whole
window, and never reached ten positions, so the rail that dominates the live
record never bound.

**Operator's decision, 13 August: accept the limit and narrow the claim.** The
harness measures **daily-cadence decisions**. Rails needing a full book are
tested by construction. Full reasoning and the three revisit triggers are in
`docs/superpowers/specs/2026-08-12-research-harness-design.md` — the one most
likely to bite is that **step 6 cannot ablate the position limit or the
aggregate cap naturally**, and those are the two that dominate the live record.

**Found on the way — the fourth wall-clock dependency, and the worst.**
`RiskDecision.ts` defaulted to `datetime.now(UTC)`, so every replayed decision
was stamped with the day the REPLAY RAN. The first run scored 0% on everything
for that reason alone: the rows existed, the rails were right, and only the date
was a lie. `RiskEngine` now takes an injectable clock.

---

# 👁️ SESSION WATCH — the protocol, and the one thing that went wrong

Run when the operator starts the app and `scripts/watch_session.py` before the
23:30 AEST open. **Report only what threatens the test's continuation. Fix a
blocker once and no more — no fix loops. Note minor issues without escalating.
Brief after the 06:00 close: events, not a transcript.**

## Reading the data — not optional

**Use PowerShell for anything under `%LOCALAPPDATA%`. NEVER Bash**, and never
PowerShell launched from Bash. The log is
`%LOCALAPPDATA%\QuantAdvisoryTerminal\data\logs\qat.log`, one JSON object per
line. `([datetime]$o.ts)` is a DateTime, not a string — format it, do not
`.Substring` it.

**`-match` is case-insensitive in PowerShell.** "excluded from signals" matches
a `SIGNAL` pattern, which inflated a signal count to 42 when the true figure was
0. Use `-cmatch` where case carries meaning.

## ⚠️ qat.log is NOT a complete view of decision activity

**The single correction from the first night.** Hourly checks reported "0
signals, 0 refusals" all night. That was accurate about `qat.log` and blind to
what mattered: `risk_decisions.csv` held **108 decisions**, every one a
position-limit refusal on AXP. It surfaced only because the file had grown 37 KB.

**Read the audit trail alongside the log, at every check:**

    Import-Csv "$env:LOCALAPPDATA\QuantAdvisoryTerminal\data\risk_decisions.csv" |
      Where-Object { $_.timestamp -ge '<session start ISO>' }

## Cadence that worked

Pre-open verify, the four-minute checklist at the bell, **hourly** through the
night, tightening before the close for the brief.

**The four minutes at 23:30:**

1. `Trading session started - US is open`
2. `REGIME ... -> <label> (exposure scalar ...)` within seconds. **Its absence is
   the most consequential thing that can silently go wrong** — every strategy
   then gates on the sideways DEFAULT rather than on a measurement
3. Any `MARKET DATA DOWN` or repeated macro fetch failures
4. `N carries a stop resting at the broker` — N must equal the position count

## What healthy looks like, so the configuration is not reported as a fault

* **Zero new entries is EXPECTED.** The aggregate cap is breached at 5.01%
  against 5.00% and the book is 10 of 10, so entries are refused by design.
* **A burst of staleness warnings at the bell** is symbols that have not printed
  since the previous close. They clear as each trades.
* **`CORPORATE ACTION first seen: CRWD`** is M39 in shadow mode. It touches no
  order; the ex-date gate rejects it.

## Scope of a fix

The standing rule's own fix-immediately list only: app crashing or hanging, feed
dead or symbols dropped, orders rejected by a bug rather than by a rule, the
kill-switch tripping on a non-discrepancy, protection not resting or not
repaired, the ledgers not being written, the daily report failing. **Nothing
that changes which trades happen or how large** — a test rescued by changing the
thing under test is not a test. And a fix cannot reach the running session
anyway: deploying needs the app closed and the operator's own hands.

---

# ⚠️ THE ASX MOVED FORWARD — 12 August

**Read `docs/superpowers/specs/2026-08-12-asx-transferable-validation-design.md`
before planning anything.** The operator's position: if the ASX move becomes a
strong proposition it will be called early, because six to twelve months of
validation are better spent in the destination market than the staging one.

**The rule that follows:** between now and the call, everything built is either
market-agnostic or cheap to abandon. Transferable — the machinery, the research
harness, the data ports, the evidence framework, M39/M43/M60. **Not
transferable — US expectancy figures**, which stop being a deliverable and
become validation of the instrument.

**W1.0 is DONE and pushed** (`bed0b79`, `15b705b`, `1162142`). Three findings,
each from checking a claim rather than repeating it:

* **`IBAdapter` implements 8 of `BrokerAdapter`'s 12 methods.** Absent:
  `recent_fills`, `resting_stops`, `resting_stop_orders`, `announcements` —
  fill absorption, protective-order integrity, corporate-action detection.
  **They are optional BY DESIGN**, every caller guards with `getattr`, so an
  adapter lacking them neither crashes nor corrupts — it silently stops
  verifying, absorbing and detecting. **Run
  `scripts/broker_capabilities.py`**, do not quote a count from here.
* **`resolve_broker` returned `MockBroker(seed=1)` for `broker=ibkr`** after
  attempting nothing, in a function whose docstring says quietly trading against
  a simulator while believing you are connected to a real account *"would be
  worse than either"*. It refuses now.
* **ROADMAP was wrong that `ibkr` is "unimplemented beyond the seam."**
  `ib_adapter.py` is 223 lines with a client protocol, translate module,
  heartbeat and backoff, and `costs.py` already carries ASX cost profiles with a
  docstring saying *live trading starts on ASX*. **The move is not starting from
  zero.**

**NEXT, and it has a clock: W1.4.** The operator is opening a live IBKR account
to reach the paper API — the TWS API via **IB Gateway**, which is what
`ib_async` speaks. `ib_adapter.py:74` RAISES when `trading_mode` is live and
unconfirmed but only WARNS when `trading_mode` is paper and `ibkr_port` is a
live port (4001/7496), then connects. Inert today. **On the morning that account
exists, a log line is the only thing between a port typo and real orders.** The
warning becomes a refusal before any IBKR credential enters configuration.

**Then W1.1** — measure what IBKR actually returns for those four methods,
against a paper account, read-only. The capability matrix is the checklist.

---

# 🔬 W2 — THE RESEARCH HARNESS IS FIVE STEPS IN

**Spec:** `docs/superpowers/specs/2026-08-12-research-harness-design.md`.
Plans for each step are in `docs/superpowers/plans/2026-08-12-*.md`.

**What it is.** `ReplaySession` drives historical bars through the REAL
`StrategyEngine`, `SignalToOrderBridge`, `OMS`, regime engine and autonomy path
into a `SimulatedBroker`. **Nothing re-implements a strategy, a rail or a fill.**
It exists because no instrument in this repository measures the deployed
system: the vectorized engine has no stop, target or time stop and exits only
on signal flips; the replay scripts hand-copy the rules from `swing.py`; and no
portfolio simulation existed at all, so the governor was exercised by nothing
but live trading. And it answers the one question live trading NEVER can — *do
the rails help* — because the same October cannot be held twice with a cap on
and off.

## The fill-model decisions every future number depends on

| | |
|---|---|
| **The stop wins any bar touching both levels** | A daily bar cannot say which came first, so expectancy is a FLOOR, not an estimate |
| **A gap through the stop fills at the OPEN** | The MNST lesson in the simulator. A fake that filled politely at the trigger would hide the loss shape this account paid $375.23 to learn |
| **A gap through the target fills at the TARGET** | The same rule pointed the other way. Deliberately conservative; recorded as revisitable |
| **Entries fill at the NEXT bar's open** | Acting on the close that generated the signal is look-ahead in its most ordinary form |
| **A stop can fire on the bar its entry filled** | The entry was at the open, so the rest of that bar follows it |

## Two production seams were added, and why each was unavoidable

* **`BarAggregator.prime_bar`** — the live path builds bars FROM TICKS, and one
  tick a day gives `high == low == close`, so ATR collapses to zero and every
  stop distance with it. Priming installs the true OHLC as the forming bar; the
  ordinary `MarketDataEvent` that follows folds in harmlessly.
* **`SignalToOrderBridge(clock=...)`** — the minimum hold and the weekly churn
  cap compared against `datetime.now(UTC)` and went **silently inert** in a
  replay. Both default to the wall clock, so live behaviour is unchanged.

**The lesson generalises and is the thing to carry into step 6:** every
wall-clock read in the trading path is a place a replay silently produces
nothing. Two found so far; the autonomy gate was a third, fixed by injecting
the simulated clock it already accepted.

## Where it got to

Steps 1–4 are **built, green and pushed**: the broker, the session loop, the
portfolio with the governor live, and the regime engine classifying rather than
defaulting. The harness has been watched refusing a trade by name —
`already at the 1-position limit` in `risk_decisions.csv` — which is the
precondition for any ablation meaning anything, and the question M51 has been
unable to ask since 5 August.

**Step 5 (G1) is complete and has RUN — see the G1 section above for the
verdict.** The window and its bars are frozen and cached in
`scripts/analysis/g1/`, the comparator is tested on synthetic rows, and
`run_g1.py` executes the whole gate. It did not pass, the reason is a fidelity
limit rather than a defect, and the limit was accepted deliberately on
13 August with its costs named.

**Two corrections that run_g1.py records in its own docstrings**, because both
were wrong in the plan and right only after measuring: the window opens with an
**empty book** (the first row is CSCO approved at 2026-07-31T13:30:10, and the
book is built inside the window), and the gate uses **IEX rather than SIP**,
because the live book computed these decisions from IEX and replaying SIP would
score feed differences as logic differences. SIP remains right for research runs.

Step 6 — the ablation switch and the run manifest — comes next, shaped by the
accepted limit.

## ⚠️ THE SANDBOX FINDING — read this before touching the live data directory

**The Bash sandbox is PER-FILE, and it covers WRITES as well as reads.** This is
the most important operational lesson of the last two days and it nearly cost
the trial's entire evidence base.

**Reads.** Same directory, same minute: Bash sees `equity_curve.csv` at 301 rows
dated 27 July while PowerShell sees 9,971 — but **both see `risk_decisions.csv`
identically.** So a spot-check on the wrong file CONFIRMS Bash is fine, and the
next read is nine thousand rows short with nothing to say so. I made exactly
that spot-check and was about to build the G1 extractor on it.

**Writes, and this is the near-miss.** The pre-deploy backup script, run from
Bash on 13 August, copied 20 files, **printed success, and wrote nothing to the
real filesystem.** The whole operation landed in an overlay only Bash can see.
The M88 deploy came within one step of overwriting the install with the closed
trades, entry records, decision journal and risk decisions unprotected.

**A script cannot detect this from the inside** — within the overlay the copy
genuinely appears to be there. So the guard has to be external:

* run anything that touches `%LOCALAPPDATA%` **through the PowerShell tool**;
* **verify from PowerShell afterwards** — file count, and a hash of
  `closed_trades.csv` against the live one. That check is the only thing that
  distinguishes a backup from a convincing report of one.

`scripts/backup_data_dir.py` carries this warning in its own docstring, is dry
run by default, and refuses while the app is running.

## Two findings about the live record itself

* **A test row reached the live record.** `Settings(_env_file=None).data_dir`
  resolves to the LIVE data directory. `conftest` sets `QAT_DATA_DIR` so tests
  are safe; **scratchpad scripts run outside pytest and are not.** Two W2 probes
  built a `RiskEngine` without an explicit `data_dir`, so `AuditLog` wrote one
  approval for symbol `AAA` at 12 August 08:53:32 UTC. One row in 2,931, for a
  symbol that does not exist, changing no conclusion — **left in place
  deliberately**, because the mechanism matters more than the row and a record
  with a documented blemish beats one somebody edited. **Any script run outside
  pytest must pass its own `data_dir`.**
* **`WES.AX` — one row, 6 August, an ASX ticker refused by the position limit in
  a US book.** Predates this work, provenance unknown. Excluded from G1 by name,
  left in the record.

---

# ⚠️ THE MNST split — DONE, and it cost real money

**Ex-date was Tuesday 11 August. The event landed at the 23:30 AEST open, the
stop fired, and the position is gone.** The next one with a clock on it is
**SFBS 2-for-1 on 21 August** — not held, and it **cannot be bought** while both
rails bind, so Phase 2 stays unmeasured unless a position closes first.

## What has already been measured

| | |
|---|---|
| Buy | 8 MNST filled Monday at **$91.1838** (total $729.47) against a $90.85 reference — **+36.7 bps of real entry slippage** |
| Stop | Placed by hand Monday, **sell stop 8 @ $72.68 GTC**, order `34ffd4cd…` |
| Pre-split baseline | `scripts/analysis/split-captures/MNST-pre-split-20260810-134022.json` — **the irreplaceable artefact** |
| Monday night | Session ran clean. No halt, no errors. Split **not** applied at Monday's close |
| **Tuesday 21:54** | **Alpaca has halved the PRICE to ~$46.30 but not the quantity or the basis** — the corporate action is half-applied |

## THE RESULT — it happened, and it cost real money

**The stop was never adjusted. It fired at the open and liquidated the
position.** Order `34ffd4cd` went `new` → `filled`, still qty 8, still $72.68 —
not cancelled, not re-priced, not re-quantified. It executed in three partials:
1 @ $46.34, 3 @ $46.16, 4 @ $45.79.

**The share side never arrived.** Quantity went **8 → 0**, never 8 → 16.
`avg_entry_price` stayed stale at $91.1838. So there was no divergence, no
kill-switch trip, and **M60's declare-then-quarantine was never exercised** —
the accepted cost of letting it run.

### The loss is REAL. An earlier version of this file said otherwise

This section predicted "a split artefact, not a loss" needing correction.
**That was wrong**, and it was wrong because it assumed rather than checked.

Verified against `/v2/account/activities`:

    buys   5 @ 91.20 + 2 @ 91.20 + 1 @ 91.07  =  $729.47 out
    sells  1 @ 46.34 + 3 @ 46.16 + 4 @ 45.79  =  $367.98 in
    gross  -$361.49    costs $13.74    net  -$375.23

**No SPLIT, no CSD, no share delivery of any kind.** Equity moved
101,754.81 → 101,387.14, consistently. The account genuinely paid for 8 shares
at pre-split prices and sold 8 at post-split prices. **The recorded P&L is
correct and must not be "corrected".**

Which makes the finding much more serious than a bookkeeping error:

> **An unadjusted stop through a split does not merely misreport. It loses
> about half the position's value, for real** — −51.4% on a position that
> should have been roughly flat.

**Caveat, load-bearing:** this is a PAPER account. Alpaca paper's
corporate-action handling may be incomplete in ways a live account is not. The
loss is real *in this account*; whether live Alpaca would have delivered the
shares is unknown. **Design M39 for the behaviour measured, not the preferred
one.**

### What IS wrong in the record — two fields, not the money

| Field | Recorded | Correct | Why |
|---|---|---|---|
| `exit_reason` | `target` | **`stop`** | Order 34ffd4cd was a stop; there was no target leg |
| `strategy` | `swing` | **blank** | Hand-placed at the broker. Leaving it credits swing's promotion evidence with a trade it did not make |

`exit_price 45.9975` is the volume-weighted average of the three partials and is
right. `stop_price` and `r_multiple` are blank because the lot carried no stop.

**File:** `%LOCALAPPDATA%\QuantAdvisoryTerminal\data\closed_trades.csv`
**Close the app first** — the ledger holds it open in append mode. Back up as
`closed_trades.csv.bak-<yyyyMMdd-HHmmss>`, the convention the CVS correction
used.

## What the captures must answer

Compare `pre-split` against `post-split`, in order of how much each matters:

1. **What happened to the resting stop `34ffd4cd`** — cancelled, left at $72.68,
   re-priced to ~$36.34, re-quantified to 16, or executed. **This decides M39's
   design and is the whole reason for the exercise.**
2. Did quantity double 8 → 16, and is `avg_entry_price` halved to ~$45.59 or
   left stale at $91.18?
3. Did a `SPLIT` account activity appear? That endpoint has returned zero rows
   for this account's entire life.
4. What the application did — divergence, halt, declare-then-quarantine.

## Already learned, before the event

* **Alpaca returns the same announcement more than once and the count changes** —
  one record Saturday, two byte-identical ones Monday, which was the
  `payable_date`. **M39's detector must dedupe on (symbol, ex_date)** and must
  not read a changing count as a changing action.
* **An order id survives across days** — the buy queued Saturday is the id that
  filled Monday. Whether it survives the split itself is what tonight answers.
* **A split can be applied in halves.** Price first, quantity later. Any
  detector that keys on quantity alone will be blind to the window in between —
  which is exactly the window where an unadjusted stop is lethal.

---

# ⚠️ Found and NOT fixed

## M66 — the risk cap that gates every entry uses ENTRY prices

**Inside the freeze. Do not build without a recorded lift.**

`PortfolioGovernor.snapshot` does `prices.get(symbol) or pos.avg_price`, and
nothing in the trading path ever passes `prices` — `RiskEngine` and
`DeleverSweep` both omit it; only `adopted.py`, a display, supplies it. So
**every entry decision this system has ever made used entry prices.** A winning
book understates its risk, and the bias grows with profit.

Designed:
`docs/superpowers/specs/2026-08-08-risk-at-stop-current-prices-design.md`.
Smaller than it looks — `Position.current_price` is the consolidated tape and is
already in every `positions()` response. Verify with
`scripts/analysis/verify_gating_figures.py`.

## ~~Held over — every entry record has `strategy: null`~~ SETTLED, see M86

**Investigated 12 August. The alarm was wrong; a different and dated defect was
found underneath it, and both are now fixed.** Full detail in `ROADMAP.md` M86.

* **Nine, not ten.** VRTX carried `"strategy": "swing"`.
* **Nothing was unattributed.** `restore_open_lots` passes `entry.strategy or
  self._sole_deployed_strategy()`, and with swing the only deployed strategy all
  ten restored as `swing`. Measured through the app's own path, not read off the
  file. CVS is the end-to-end proof — no strategy field at all in
  `open_position_entries.json.bak-pre-m33b`, closed as `swing`.
* **Cause:** M49 added the field on 5 August; those nine records were written
  31 July and 4 August. Pre-M49 legacy, not ongoing corruption.
* **The real defect:** attribution was *inferred from a config value at every
  launch*, not stored. `_sole_deployed_strategy` returns None the moment a second
  strategy is deployed, so **activating M84 or M85 would have retroactively
  unattributed nine held positions** — measured, `strategies() -> []`. And it had
  **no test at all**.
* **Fixed both ways:** `reconcile_entry_strategies` heals the record at startup
  (M86, undeployed), and the live record was corrected on 12 August for the build
  that is running. Backup
  `open_position_entries.json.bak-20260812-090344-PRE-M86-strategy-backfill`.
  Now 0 null, 10 named, and the two-strategy case returns `['swing']`.

**Swing was a fact, not a guess** — `decision_journal.csv` records
`strategy=swing` for all nine with transmit timestamps matching `opened_at` to
the second.

## ~~The Balances broker row clips its fifth label~~ — FIXED (M87), verified on screen

**"Day trades (5d)" renders as "Da"** on the Dashboard, cut off at the right edge
of the Balances card — **and still clipped with the window maximised at 3086px**,
so it is not a small-window artefact. Its value shows the `—` that legitimately
means "the broker did not report it"; the defect is the label.

`balances_panel.py:271` puts five cells in one row where the primary grid wraps at
four, and the comment says why: five cells wrapped at four *orphan the last one
onto a row of its own*. That reasoning is sound and it fixed the orphan — it just
traded a wrapped row for a clipped one. The cells lay out at natural widths that
sum past the card.

**Pre-existing, not a regression from the deploy** — `c0938dc` (8 August) is an
ancestor of the deployed `49482c2`, so it shipped in the M63+M62 build too. It had
simply never been rendered and looked at. Every test passes through it, which is
the whole argument for screenshotting.

**Fixed in M87 and confirmed on screen in the M86 build**, which is the only
evidence that counts here: the overflow was not reproducible offscreen (the
display runs at 125% scaling, the test platform at 96 DPI) and an offscreen
render produces tofu, so no test could prove it. The label now reads in full.
Labels elide with an ellipsis and keep their text in a tooltip, and both grids
divide their width evenly. **A floor remains** — the panel cannot go below
1056px, and narrower than that it still overflows, because the bold money values
set that minimum and eliding a money figure would mislead where eliding a label
merely abbreviates.

## M71 — the same root cause as M70, on the way OUT

App-transmitted sells announce at the reference price too, so the ClosedTrade's
**exit** price is wrong. Separate from M70 because correcting it means rewriting
a record already on disk. **Read from the code, not yet verified against a live
transmitted sell** — do that before designing it.

---

# What has landed since 8 August

**Those 18 were deployed on 12 August as `M86 (7812c22)`. Since then M39 and M87
have landed and are NOT installed** — built, signed, zipped and staged. Run
`handoff_state.py` rather than trusting this paragraph: its `DEPLOYED` constant
is the one figure it cannot derive, and the milestone label beside it reads out
of `version.py` at that commit rather than being typed.

## Record correctness

| | |
|---|---|
| **M70** | The half of M65 that startup could not heal. A position opened and closed inside one session never reaches the next startup, and its ClosedTrade is already written against a basis never paid. Turned up that **`entry_slippage` was zero by construction** on every entry ever opened — the instrument M44 is booked to measure the cost model with in September |
| **M81** | The startup warning about MNST was the **opposite of the truth**. `restore_open_lots` said no lot could be restored; the replay opened one seconds later in the same startup |
| **M82** | Two more messages checkably false. **"this will only unwind as positions close"** — 112 times in one night — when the figure changed ten times with every position open, and moved the *wrong way* as equity fell |
| **M83** | Performance showed two trade counts that disagree and explained neither |

## The interface — Group 4 complete

M63 Dashboard · M64 Regime Monitor · M67/M68 Risk Console · M69 Workbench
caveats · M72 Screener · M73 AI Advisor · M74 Workbench levels · M75/M78 design
system · M76 dropdowns · M77 Blotter · M79 Performance.

## Process

**M80** — the pattern-counting was itself the pattern. A register replaces every
asserted count; `test_computed_values_have_readers` turns "ask what reads it"
into a check; `UI_UX_APPROACH.md` is dated and §4.x marked as intent.

## Designed, not built, NOT activated

**M84** price-action / candlestick · **M85** volume-profile. Both selectable via
`default_strategies()`, both absent from `QAT_DEPLOYED_STRATEGIES`, so neither
changes a trading decision. **Activating either is a separate act needing a
recorded lift.** Shared prerequisites: SIP daily bars, and one pattern module
(both specify Bullish Engulfing and Hammer — build once, not twice).

**One prerequisite is now cleared rather than outstanding.** Deploying a second
strategy used to retroactively unattribute every held position on a pre-M49
entry record — nine of ten, silently, because `_sole_deployed_strategy` stops
resolving as soon as there are two candidates. M86 stored the attribution, so
activation no longer costs the evidence. Had either been activated before
12 August, nine positions' worth of promotion evidence would have gone.

---

# The 12 August deploys — THREE of them, and what each one taught

Three builds shipped on 12 August. The second was broken and the third fixed it,
which is the part worth reading.

**1. `M86 (7812c22)`, 09:20.** The 18-milestone backlog. Confirmed in the log:
Adopted 10 not 11, 10 of 10 carrying a resting stop, M65 correcting exactly the
eight entry prices predicted, **the strategy fields surviving that rewrite**
(still 10 named, 0 null — the interaction worth checking, since M65 rewrites the
same file M86 had just corrected), and M86 itself correctly silent. M82's fix
visibly working: the aggregate-risk warning now says "nothing will be sold to
correct it" in place of the false "this will only unwind as positions close".

**2. `M39+M87 (5480452)`, 15:28. BROKEN, and the failure is the lesson.**
Widening the announcement lookback to 90 days made the total range 135, and
Alpaca refuses it outright:

    ValidationError: Value error, The date range is limited to 90 days.

Every query failed on all ten held symbols. **A probe existed for exactly this
path and was not re-run after the constant changed.**

**Worse than the broken query: the Risk Console went on saying "Corporate
actions: none pending on held positions."** That was false, and false in the
direction that reassures — the truth was UNKNOWN, not none. The monitor swallows
a query failure by design so one bad sweep cannot end the session, and with an
empty fallback store that makes blindness indistinguishable from a quiet book.

**3. `M39+M87 (67677bc)`, 15:43. The current build.** Hash-verified
`94C33499…6BF0528`. The 90-day cap is enforced in the ADAPTER now, where the
constraint lives, by splitting any range into windows and deduping across them —
so a caller widening a window cannot reintroduce it. And blindness is a reported
STATE rather than a silence: the monitor names the symbols it could not read,
both screens say so instead of claiming nothing is pending, and it clears on
recovery.

## What the third launch proved, which no test could

    CORPORATE ACTION first seen: CRWD ex-date 2026-07-02 ratio 4

**The announcement was fetched — and then nothing happened.** No `SHADOW:` line,
no `ADJUSTED:` line. That is the ex-date gate rejecting it, against real data, in
production.

It matters because CRWD is held, 16 shares, correctly sized post-split, with a
correct resting OCO at 163.32. Had the gate not held, the monitor would have
divided that stop by four to ~40.83 and — in `act` mode — placed an order that
liquidates the position at the next open. Until the lookback widened, the WINDOW
happened to exclude CRWD and the gate was never consulted; it is now the only
defence, and it has been observed doing the job. That is the M60 concern — *"the
piece that can be wrong in the dangerous direction"* — settled by observation.

**The aggregate cap is breached at 5.01% against the 5.00% cap, so new entries
are refused, and this predates every deploy today.** Measured in the pre-deploy
log at 07:54 through 08:09. M65 raised seven of eight entry prices, which widens
entry-to-stop and therefore raises risk-at-stop, so it was worth ruling out: it
did not tip the cap. **No deploy today changed any trading behaviour.**

## For the next deploy

* **Back up `open_position_entries.json`** and the data directory. Today's:
  `data-backup-20260812-133956-PRE-M39-DEPLOY`.
* **The level model gates real controls.** Workbench deploy is Professional-only
  (M74), Blotter bulk sign-off is Standard-and-above (M77). Live config is
  `QAT_UI_LEVEL=professional`, but the default is `standard` and a config reset
  takes the deploy button. Manual section 11.9 now documents this.
* App closed, `Expand-Archive -Force`, verify by hash, **then launch**. A hash
  proves the right bytes landed, never that they run — M56a passed its hash check
  and could not start. **The permission classifier refuses the expand step**, so
  the operator runs it.
* **Delete superseded zips.** A stale one staged beside the current one is a
  wrong build waiting to be installed.
* **Update `DEPLOYED` in `scripts/handoff_state.py`** — it is the one figure the
  tool cannot derive, and everything else derives from it.

---

# Standing constraints

* **Read `%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell, never Bash.**
  **Measured 10 August:** the Bash tool sees a sandboxed copy frozen at 27 July —
  `equity_curve.csv` at 13,811 bytes and 301 rows against the live 405,949 and
  8,757. PowerShell launched *from* Bash inherits the same blind view, so the
  sandbox covers the whole process tree, and **the Monitor tool cannot see the
  live account either.** Anything watching those files from a Bash shell reads a
  file that never changes: it does not error, it goes quiet, and quiet is
  indistinguishable from healthy. **Overnight watching must be a scheduled
  prompt that wakes and uses the PowerShell tool.** The Bash tool IS correct for
  the venv python and for Alpaca API calls — the sandbox is filesystem-only.
* Operator's terminal is PowerShell 5.1 — `;` not `&&`, `@'...'@` here-strings
  with the closing `'@` at column 0.
* **Formats with `black`, not `ruff format`.** `invoke lint` shells out to a ruff
  that is not on PATH — run the four via the venv python: `ruff check .`,
  `black --check .`, `mypy src`, `bandit -r src`.
* **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets
  `QAT_DATA_DIR` session-wide and the anomaly store persists there, so one
  declared anomaly leaks a quarantine into every later test.
* **Validation freeze:** nothing lands that changes which trades happen or how
  large they are. Reporting, logging and analysis are explicitly permitted, and
  **a defect that corrupts the record is fix-immediately.**
* Convention: plan → approval → implement → verify → commit → build. Build and
  sign freely; **always ask before deploying.**

---

# The habits that found everything

**Check the brief against the code before building.** §4.x described something
that was not there **eight times across seven milestones** — the register in
`ROADMAP.md` lists every one. It is also how M72 and M83 were found, which the
brief does not mention at all.

**Render it, do not trust the suite.** Screenshotting found M63's orphaned grid
row and off-scale font, M72's stranded filter labels, M74's "Grew -0.0% a year"
and a notice floating in an empty screen, M77's truncated Reason column. Every
test passed through all of them.

**Ask what reads it.** `shows_advanced()` had no consumers from M45 until M63,
`theme.callout` none until M72, `is_synthetic` reached the language model but
never the operator until M72, `refusals.rail_of` the reporter but never the
Blotter until M77, the M37 diagnostics nothing until M79. **This one now has a
test.**

**Test the claim, not the arithmetic.** Every defect found on 11 August was in a
sentence that predicted or explained — never in a number. Testing the numbers
would have missed all of them.

**Derive, do not remember.** Four separate counts were asserted and wrong in
three days. The ones that are now derived have stopped being wrong.

---

## Prompt to paste

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
Paper account throughout - no real money is involved.

Read docs/HANDOFF.md first, then the standing rule at the top of ROADMAP.md.

BEFORE QUOTING ANY CURRENT-STATE FIGURE, RUN:
  .\.venv\Scripts\python.exe scripts/handoff_state.py
It derives the deploy gap, the milestone list and the test count. FOUR
hand-maintained counts were wrong in three days. Counting is not the fix -
deriving is.

READ THE LIVE DATA THROUGH POWERSHELL, NEVER BASH - AND VERIFY WRITES
The Bash sandbox is PER-FILE and covers WRITES as well as reads. Bash sees
equity_curve.csv at 301 rows dated 27 July while PowerShell sees 9,971 - but
BOTH see risk_decisions.csv identically, so a spot-check on the wrong file
CONFIRMS Bash is fine and the next read is nine thousand rows short.

  THE NEAR-MISS: the pre-deploy backup script, run from Bash on 13 August,
  copied 20 files, PRINTED SUCCESS, and wrote NOTHING to the real filesystem.
  The M88 deploy came one step from overwriting the install with the closed
  trades, entry records, decision journal and risk decisions unprotected.
  A script CANNOT detect this from inside - within the overlay the copy is
  there. Run it through PowerShell, then VERIFY from PowerShell: file count
  and a hash of closed_trades.csv against the live one.

  Also: Settings(_env_file=None).data_dir resolves to the LIVE data directory.
  conftest protects tests; scratchpad scripts run outside pytest and do not.
  ANY SCRIPT RUN OUTSIDE PYTEST MUST PASS ITS OWN data_dir.

WHERE THIS STANDS
M88 is deployed and running (45980a5), deploy gap ZERO, and the absorb window
is closed in the live build for the first time. The ASX moved from eventual
destination to NEAR-TERM one on 12 August, which reframes the trial rather
than pausing it: US closed trades are MACHINERY evidence, not EDGE evidence,
because the edge numbers do not transfer. The binding constraint stopped being
evidence and became INSTRUMENTATION.

THE RESEARCH HARNESS (W2) IS FIVE STEPS OF SIX
ReplaySession drives historical bars through the REAL StrategyEngine,
SignalToOrderBridge, OMS, regime engine and autonomy path into SimulatedBroker.
NOTHING re-implements a strategy, a rail or a fill. Spec:
docs/superpowers/specs/2026-08-12-research-harness-design.md

  FILL MODEL, and every future number rests on it: the STOP wins any bar
  touching both levels, so expectancy is a FLOOR not an estimate. A gap through
  the stop fills at the OPEN; a gap through the target fills at the TARGET.
  Entries fill at the NEXT bar's open. A stop can fire on the bar its entry
  filled.

  THREE PRODUCTION SEAMS, each defaulting to live behaviour: prime_bar (the
  live path builds bars FROM TICKS, and one tick a day collapses ATR and every
  stop distance with it), SignalToOrderBridge(clock=), and RiskEngine(clock=).
  THE LESSON GENERALISES: every wall-clock read in the trading path is a place
  a replay silently produces nothing - or worse, produces rows dated wrong.

  G1 RAN AND DID NOT PASS. exact 6, partial 2, disjoint 12, live-only 38,
  harness-only 8. The harness never hit the position limit once against 37 live
  symbol-days: live evaluates every 60s on a FORMING bar and filled its book on
  day one, the replay evaluates once per CLOSED bar. OPERATOR ACCEPTED THIS
  LIMIT on 13 August - the harness measures DAILY-CADENCE decisions, and rails
  needing a full book are tested by construction. THE REVISIT TRIGGER: step 6
  cannot ablate the position limit or the aggregate cap naturally, and those
  are the two that dominate the live record.

  NEXT: step 6, the ablation switch and the run manifest, shaped by that limit.

OVERNIGHT SESSION 12-13 AUGUST - CLEAN
23:30:17 to 06:00:18. Zero errors, zero data-down, zero kill-switch, zero
unprotected, zero broker-side fills, zero closed trades. Regime classified
low_vol at the bell with exposure 1.00.

  THE ONE EVENT: AXP fired swing's entry and was refused 108 TIMES by the
  position limit, 04:09-05:59, first refusal at $341.90. The machinery working
  as designed - and the FIRST CONCRETE EVIDENCE of what the 10-position cap
  costs, which is exactly what the 20 August review needs.

  THE MONITORING LESSON: qat.log is NOT a complete view of decision activity.
  Hourly checks reported "0 signals, 0 refusals" all night and were blind -
  risk_decisions.csv held 108 rows. READ THE AUDIT TRAIL ALONGSIDE THE LOG.

SESSION WATCH PROTOCOL (see the full section in HANDOFF.md)
Operator starts the app and scripts/watch_session.py before the 23:30 AEST
open. Report only what threatens the test's continuation. Fix a blocker ONCE
and no more - no fix loops. Note minor issues without escalating. Brief after
the 06:00 close: events, not a transcript.

  FOUR MINUTES AT THE BELL: session started; REGIME line within seconds (its
  ABSENCE is the most consequential silent failure - everything then gates on
  the sideways DEFAULT); no MARKET DATA DOWN; N carries a stop = position count.
  Then hourly, tightening before the close.

  EXPECTED, NOT A FAULT: zero new entries (cap breached at 5.01% vs 5.00%, book
  10 of 10); a staleness burst at the bell; CORPORATE ACTION first seen: CRWD
  (M39 shadow mode, touches no order).

  PowerShell gotchas: ([datetime]$o.ts) is a DateTime, format it rather than
  .Substring it. -match is CASE-INSENSITIVE, so "excluded from signals" matches
  a SIGNAL pattern - use -cmatch where case matters.

OUTSTANDING, IN THE ORDER I WOULD TAKE THEM
  W2 step 6  the ablation switch and the run manifest. Regime is a rail like
             any other now, which is what makes it ablatable.
  M66  the aggregate risk cap gates every entry against ENTRY prices, so a
       winning book UNDERSTATES its risk. Designed, inside the freeze, and it
       tightens an already-breached cap. Pair it with the 20 August review.
  W1.1 measure what IBKR returns for the four BrokerAdapter methods IBAdapter
       does not implement - recent_fills, resting_stops, resting_stop_orders,
       announcements. Blocked on the IBKR account. W1.4 (the port guard) MUST
       land before any IBKR credential enters configuration.
  M71  app-transmitted SELLS announce at the reference price, so the recorded
       EXIT price is wrong. NEVER VERIFIED against a live transmitted sell -
       do not design it until one has been observed.
  M43  trading halts. M60 built the flagging half; a halt has no ratio to
       match, so detection is a different question from M39's.

CONSTRAINTS
  PowerShell 5.1 - use ; not && and @'...'@ here-strings, closing '@ col 0.
  Formats with black, not ruff format. Run ruff check ., black --check .,
  mypy src, bandit -r src via the venv python.
  EVERY TEST THAT BUILDS AN OMS MUST PASS ITS OWN data_dir.
  Freeze: nothing lands that changes which trades happen or how large.
  Reporting and logging are permitted; a defect that corrupts the record is
  FIX-IMMEDIATELY.
  Plan -> approval -> implement -> verify -> commit -> build. ALWAYS ask
  before deploying. The permission classifier refuses the Expand-Archive step,
  so the operator runs it.

THE HABITS THAT FOUND EVERYTHING
  CHECK THE BRIEF AGAINST THE CODE. §4.x described something that was not
  there EIGHT TIMES across seven milestones. It is also how the "four missing
  IBAdapter methods" claim became a derivation instead of a reading.
  RENDER IT, do not trust the suite. Screenshotting found an orphaned grid
  row, an off-scale font, stranded labels and a truncated column - every test
  passed through all of them.
  ASK WHAT READS IT. Six values were computed and displayed nowhere.
  TEST THE CLAIM, NOT THE ARITHMETIC. Every defect found on 11 August was in a
  sentence that predicted or explained, never in a number.
  DERIVE, DO NOT REMEMBER. And CHECK BEFORE ASSERTING - the backup that
  "succeeded" on 13 August had written nothing at all.
```
