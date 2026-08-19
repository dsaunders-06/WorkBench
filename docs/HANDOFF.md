# Handoff — 19 August 2026, the day the US trial closed

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

**Sections dated before 19 August are history and are kept for their reasoning,
not as current state.** Where the two disagree the paste block and
`handoff_state.py` win. This file has been wrong about its own next steps twice:
on 14 August three of four were already done, void, or misstated, and on
19 August an alarm it would have had you chase turned out to be the watch script
rather than the app. Check the code.

## ⚙️ Before quoting any figure in here, run this

    .\.venv\Scripts\python.exe scripts/handoff_state.py

It derives the deploy gap, the milestone list and the test count from the
repository. Every current-state number here is a hand-maintained copy, and this
project lost that argument four times in three days. **Counting is not the fix —
deriving is.**

---

# Where this stands, in one paragraph

**The IBKR paper account is LIVE (`DUQ200898`) and Stage 1 Task 1 is DONE.**
Three of its four questions are answered against a real Gateway, not inferred.
Work is NO LONGER PAUSED - the blocker that paused it is gone.

**Run `handoff_state.py` before quoting any number below.** This file has gone
stale within a day of being written, twice.

## What Task 1 measured, 19 August

* **ASX trading permission IS granted.** Confirmed by a `whatIfOrder` preview
  that creates no order. Commission came back **AUD 6.60**, exactly the ASX
  Fixed floor. Account equity ~**1,003,733** - the 10x figure that changes
  which rails bind.
* **All four IBKR calls exist and answer.** `fills`, `reqExecutions`,
  `openTrades`, `reqAllOpenOrders` - no permission error, no pacing violation.
* **`announcements` has NO equivalent.** Confirmed, not inferred. Task 5 is a
  decision to record, not code to write.
* **Q3 ANSWERED: a resting stop IS visible** to both `openTrades()` and
  `reqAllOpenOrders()`, agreeing on type, price, status and permId.
* **Q1 ANSWERED: permId SURVIVES a Gateway restart.** Task 3's identity choice
  holds, measured. (`orderId` survived too - that is NOT a reason to prefer it;
  its hazard was reuse, never mutation.)
* **Q2 advanced, not closed.** The order came back `whyHeld='trigger'` - IBKR's
  marker for held-at-IBKR rather than working at the exchange. Cannot settle
  native-vs-simulated for LIVE ASX because IBKR simulates all paper stops. But
  **the API EXPOSES the distinction**, so the app can read what it currently
  assumes. Task 4 should carry `whyHeld` through.
* **Q4 STILL OPEN** - execution retention needs a real fill, the only remaining
  question that does.

Full report: `docs/superpowers/specs/2026-08-19-ibkr-capability-measurement.md`.
The account now holds **no orders and no positions** - the test order was
cancelled and the cancellation verified externally.

## THE DEFECTS TASK 1 FOUND, WHICH MATTER MORE THAN WHAT IT WENT LOOKING FOR

**M95 - IBKR sent a protective stop as a MARKET order. FIXED, Stages A and B.**
`to_ib_order` branched on `limit_price` alone, so the protective stop
`OMS._propose_protective_order` builds - `order_type="stop"`,
`limit_price=None` - fell through to `MarketOrder("SELL", qty)`. **A protective
stop for an unprotected position became an immediate market sell OF THAT
POSITION.** Never reached production; `QAT_BROKER=alpaca` throughout the US
trial. **Nothing caught it because the capability audit asks "is the method
there", and `place_order` was there - the TRANSLATION was wrong.**

Stage A: STP at GTC, `modify_order` propagating `stop_price`, and a boundary
guard that RAISES rather than approximating. Stage B: bracketed entries as
parent plus two legs, standalone stop-plus-target as one OCA group, `cancel`
that cancels every leg AND RE-READS to confirm, `modify` that reprices the STOP
LEG rather than the entry.

**M96 - IBKR could not resolve an ASX symbol at all. FIXED.** `to_ib_contract`
never stripped the `.AX` suffix and hardcoded `currency="USD"`. Measured:
`BHP.AX` returned error 200 in either currency, and an unsuffixed `BHP` in USD
resolved to the NYSE ADR (conId 4986) rather than ASX (4036812). Fixed at the
vendor boundary in `symbols.to_ibkr`, M26's pattern. Also sets the bracketed
parent's TIF explicitly - IBKR warned 10349 that a Gateway-side PRESET had
chosen it.

**M97 - `recent_fills`. BUILT.** Stage 1 Task 2. `reqExecutions` rather than
the session-scoped `IB.fills()`, `permId` as the identity so Task 3's bridge
actually matches, strict `BOT`/`SLD` with an unknown side DROPPED rather than
defaulted, and the window applied on FILL time here rather than delegated to a
broker-side filter whose semantics have not been measured. `symbols.from_ibkr`
is the inbound half of M96 - the app tracks `BHP.AX` and IBKR answers `BHP`,
and an untranslated fill matches no tracked position.

**ORDERS BELONG TO A clientId.** Cancelling from a different `clientId` than
placed fails with error 10147 - while `reqAllOpenOrders()` still SHOWS the
order, and while our own object reports `PendingCancel`. **Visible is not
cancellable.** `QAT_IBKR_CLIENT_ID` must be treated as IMMUTABLE while any
order rests, or protective stops become unmodifiable while still appearing in
the app's view of what protects the book.

## OUTSTANDING, IN ORDER

1. **Stage 1 Task 4** - `resting_stops`/`resting_stop_orders`. Carry `whyHeld`
   (it distinguishes a stop held at IBKR from one working at the exchange) and
   the owning `clientId` (so "can I actually cancel this" is answerable).
2. **Stage 1 Task 5** - the announcements decision. Measured; needs an
   operator choice, not code.
3. **Q4** - execution retention, needs a real fill. Decide if it is worth one.
   `recent_fills` is now the natural place to settle it.
4. **The rest of Stage 3's ASX rules** - the $500 minimum marketable parcel
   reaches position sizing directly and is implemented nowhere. ASX minTick is
   0.001 (measured); tick sizes, T+2 and the auctions are unbuilt.

Unchanged: the DATA decision (yfinance for ASX bars, IBKR for execution - do
NOT buy ASX Total during testing), M71 still unobserved in production, the cash
floor question, and M43 waiting on the announcements decision.

**Two documents supersede everything below.** `docs/2026-08-19-us-trial-close.md`
is the full account of the US phase. `docs/superpowers/plans/2026-08-19-ibkr-move.md`
is the four-stage plan.

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

## Run `scripts\session_check.ps1` — one command, at every cadence

    & "C:\Claude Programming\scripts\session_check.ps1"

**Invoke it exactly like that, with no arguments.** It reports the current or
most recent session — derived from the log rather than passed in — so the same
command serves the pre-open verify, the bell, the hourly checks, the pre-close
tighten and the morning brief. It covers the four checks, errors either side of
the bell, staleness in and out, the audit trail grouped by symbol, the ledgers
with a `closed_trades` hash, and session equity bounded at stand-down.

**Why one fixed string, and why it may not grow a parameter.** Claude Code
stores PowerShell permissions as EXACT COMMAND STRINGS. A command whose text
varies between runs — an hourly check with the hour in its filter — can never be
allowlisted, and the operator is offered *"approve once"*, every time, because a
durable rule would never match the next command. That is what made the 13 August
scheduled-task attempt unworkable, and it was invisible until the operator asked
why approving once was the only option. It is allowlisted in
`.claude/settings.local.json` and confirmed to run without prompting. **If a
future check needs a different window, widen what the script REPORTS rather than
what the caller passes.**

Pure PowerShell, deliberately not Python: a script that cannot import `qat`
cannot instantiate a `RiskEngine` without a `data_dir`, which is how a probe
wrote a row for symbol `AAA` into the live record on 12 August. It reads and
never writes.

**Running it against a real session found three faults reading it would not
have** — the same argument as screenshotting the UI. Scoping the four checks to
the session made *"N carries a stop"* unable to pass at all, because adoption
happens at LAUNCH, two hours before the bell; errors between launch and the bell
were dropped entirely, hiding a macro failure at 23:05 against a 23:30 open; and
session equity was unbounded at the end, so the night's P&L quietly rewrote
itself on every re-run as post-market marks arrived.

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

**W1.4 IS DONE — landed 12 August. This section said otherwise until 14 August.**
`ib_adapter.py` now raises `LivePortInPaperModeError` when `trading_mode` is
paper and `ibkr_port` reaches a live session (4001/7496), and the exception's
own docstring dates the change: *"This was a warning until 12 August, and a
warning is not enough."* The guard is deliberately one-directional — live mode
against a paper port is the SAFE mismatch and is allowed.

**Nothing now stands between the IBKR account and a safe first connection.** It
was described here as the next thing needing to be built, and a session acting
on that would have rebuilt something already in the code. Read
`ib_adapter.py` rather than this paragraph.

**W1.1 is the real critical path, and it is genuinely blocked** — measure what
IBKR returns for `recent_fills`, `resting_stops`, `resting_stop_orders` and
`announcements`, against a paper account, read-only. Needs the TWS API via **IB
Gateway**, which is what `ib_async` speaks. `scripts/broker_capabilities.py` is
the checklist and is ready the day the account exists. No local work shortens
this.

---

# 🌏 ASX MACRO — DONE 14 August, and it changed the answer

**Plan:** `docs/superpowers/plans/2026-08-14-asx-macro.md`. Nine commits,
`c8efb94` → `bee937c`. Suite 2,092 → 2,121 passed. **Zero milestones — nothing
here needs deploying.**

`run_asx_replay.py` never passed `macro=`, so `vix_level`, `yield_curve_slope`
and `credit_spread` were constant, the covariance was singular, the HMM could
not fit, and every ASX figure ever quoted was produced at a permanent exposure
scalar of 1.00. The frozen FRED loader that `run_ablation.py` owned privately
now lives in `qat.domain.backtester.macro_cache` and both runners share it.

**The result is the reason to care.** `regime_gate` went from unable to be
exercised at all to `bound_count: 2`, and expectancy over the same 499 sessions
went **+0.03R mean / +2.76R total / 48% win → −0.06R / −5.02R / 44%**. The
positive number was never an edge measurement.

## Three things found by RUNNING it, not by reading it

* **A rail bound 15 times with no row in the manifest.** `Cash floor` refused 15
  candidates. `build_manifest` iterated the twelve knobs in `ablation.RAILS`,
  while `refusals._PATTERNS` recognises many more labels — so a rail the ledger
  *watched bind* was absent entirely, which reads as "nothing else refused".
  Now derived and reported as `unmodelled_refusals`, from the run's own
  `risk_decisions.csv` through the existing `rail_of` — never a second list.
* **A convergence signal that could never fire, shipped by the fix meant to
  report one.** `hmmlearn`'s `monitor_.converged` returns True when
  `iter == n_iter`, so *"reached the iteration cap without converging"* is
  unrepresentable through it. **The instruction was wrong and the
  implementation was faithful.** Worse, the symptom actually observed —
  `Model is not converging` — comes from a *decreasing log-likelihood*, which
  never touches `converged`. Same class as `refusals.py`'s `"es limit"` pattern
  that never matched anything. Now counts hmmlearn's own warning: the real run
  reports **4 refits**, and the manifest says so.
* **`{}` meant two different things.** An empty `unmodelled_refusals` read
  identically for "checked, nothing unmodelled" and "this manifest predates the
  field". Now `dict | None`, matching `bound_count`'s own `int | None` idiom
  twelve lines above it in the same file.

## What is deliberately NOT done

Australian macro series. The regime engine reads `settings.fred_series`, so
swapping them is a change to what the deployed engine consumes — trading logic
dressed as a research fix. It needs its own spec, and it is now the second
question, after the ablation.

Also open: `unmodelled_refusals` cannot separate "known rail the table does not
model" from "reason we could not classify"; `run_comparison.py` never surfaces
the field; and no test drives a real hmmlearn fit into emitting the warning —
the seam is covered at the logger, not end to end.

---

# 🔬 W2 — THE RESEARCH HARNESS IS COMPLETE

**Spec:** `docs/superpowers/specs/2026-08-12-research-harness-design.md` and
`2026-08-13-ablation-switch-and-run-manifest-design.md`. Plans are in
`docs/superpowers/plans/2026-08-12-*.md` and `2026-08-13-*.md`.

**All six steps shipped, 14 August.** Step 6 added the ablation switch, the run
manifest and the comparison — and its first result is that **no rail can be
exercised on the US window**: ten risk decisions in a whole run over 38 symbols,
ten approvals, zero refusals, so every ablation correctly reports NOT EXERCISED.
Run it with `scripts\research\run_ablation.py --rail <name>`, or `--list`.

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
stop fired, and the position is gone.**

**SFBS ON 21 AUGUST IS VOID, and the plan built on it with it.** ROADMAP
committed to freeing a position slot deliberately so the 2-for-1 could be
observed. **SFBS is not in the tradable universe** — it appears in docs and
tests and nowhere in `src/`, so the app cannot buy it with a free slot or
without one. Checked 14 August; the plan had been recorded for two days.

Two things follow. The book sitting at 10 of 10 has cost nothing, because the
slot could not have been used. And **M66's sequencing is released** — it was
placed after the SFBS event so it would not take back the freed slot, and there
is no event.

**Adding SFBS to the universe is not recommended.** It is a freeze lift that
changes which trades happen, spent on a US corporate action, to instrument what
CRWD already demonstrated in production on 12 August: the ex-date gate refusing
a live announcement, observed rather than tested.

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

**Inside the freeze. Do not build without a recorded lift — but nothing else
blocks it now, and it is the highest-value unblocked work.** Its "land after the
SFBS event" sequencing was released on 14 August when SFBS turned out not to be
tradable. It is a MACHINERY defect, so unlike the edge numbers it transfers to
the ASX.

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

**Those 18 were deployed on 12 August as `M86 (7812c22)`. M39, M87 and M88 have
landed since and are ALL installed** — the running build is `M88 (45980a5)` and
the deploy gap is zero. Run `handoff_state.py` rather than trusting this
paragraph: its `DEPLOYED` constant is the one figure it cannot derive, and the
milestone label beside it reads out of `version.py` at that commit rather than
being typed. **This sentence has already been stale once** — it still said M39
and M87 were staged and uninstalled a day after M88 shipped them.

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
  indistinguishable from healthy. The Bash tool IS correct for the venv python
  and for Alpaca API calls — the sandbox is filesystem-only.
* **Overnight watching is `scripts\session_check.ps1`, not a scheduled prompt.**
  This bullet used to prescribe a scheduled prompt that wakes and uses the
  PowerShell tool. **Measured on 13–14 August: that does not work**, for two
  independent reasons. Scheduled tasks compose a different command each run, so
  no permission rule can match and the operator is prompted every time with
  *"approve once"* as the only option. And a scheduled task's OUTPUT never
  reaches the session that created it — the 06:13 brief ran (`lastRunAt`
  confirms it) and its report was never seen. **A scheduler that fires into
  silence looks exactly like a quiet night**, which is the failure this whole
  protocol exists to prevent.
* Operator's terminal is PowerShell 5.1 — `;` not `&&`, `@'...'@` here-strings
  with the closing `'@` at column 0.
* **Formats with `black`, not `ruff format`.** `invoke lint` shells out to a ruff
  that is not on PATH — run the four via the venv python: `ruff check .`,
  `black --check .`, `mypy src`, `bandit -r src`.
* **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets
  `QAT_DATA_DIR` session-wide and the anomaly store persists there, so one
  declared anomaly leaks a quarantine into every later test.
* **The validation freeze ENDED on 14 August** — see the top of `ROADMAP.md`. It
  existed to keep a result interpretable, and there is no result to protect:
  the gate needs 30 closed trades and swing's sees ONE. M66 was the last item
  behind it. **The operative rule now is the ASX one: everything built is either
  market-agnostic or cheap to abandon.** The question stopped being *would this
  change a trading decision* and became *would this survive the move*.
* **A defect that corrupts the record is still fix-immediately**, and the whole
  fix-immediately list is unchanged. The freeze ending removed a constraint, not
  the discipline.
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

## Prompt to paste - SUPERSEDED, kept as the record of what was believed

> **DO NOT PASTE THIS ONE.** It is the brief as it stood on the morning of
> 19 August, before the account went live. It says WORK IS PAUSED PENDING THE
> IBKR ACCOUNT and W1.1 is GENUINELY BLOCKED; both were true when written and
> neither is true now. Task 1 is done, M95 and M96 are built.
>
> **The current prompt is the block at the very end of this file.** This one is
> kept because the file's own argument is that a brief goes stale within a day
> - and here is one that did, in hours.

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
Paper account throughout - no real money is involved.

THE US TRIAL CLOSED ON 19 AUGUST. Read docs/2026-08-19-us-trial-close.md first,
then docs/superpowers/plans/2026-08-19-ibkr-move.md. The ASX/IBKR move is
CALLED, not proposed.

BEFORE QUOTING ANY CURRENT-STATE FIGURE, RUN:
  .\.venv\Scripts\python.exe scripts/handoff_state.py
It derives the deploy gap, the milestone and the test count. FOUR
hand-maintained counts were wrong in three days. Deriving is the fix.

AND CHECK THE BRIEF AGAINST THE CODE BEFORE ACTING ON IT. On 14 August three
of four "next steps" were already done, void, or misstated. On 19 August a
"failure" alarm turned out to be the watch script, not the app.

READ THE LIVE DATA THROUGH POWERSHELL, NEVER BASH
The Bash sandbox is PER-FILE and covers WRITES as well as reads. A backup run
from Bash on 13 August copied 20 files, PRINTED SUCCESS, and wrote nothing.
Run it through PowerShell, then VERIFY EXTERNALLY - file count and a hash of
closed_trades.csv against the live one.
  Settings(_env_file=None).data_dir is the LIVE data directory. conftest
  protects tests; scripts run outside pytest do not. ANY SCRIPT RUN OUTSIDE
  PYTEST MUST PASS ITS OWN data_dir.

WHERE THIS STANDS - 19 August
M94 (f537a9e) deployed and verified, deploy gap ZERO, 2,194 passed / 25 skipped.
Everything is pushed. The app runs; the US trial is over.

WHAT THE TRIAL LANDED - the full account is in the close document
  4,876 risk decisions over 10 sessions. 45 approved (0.92%). TWO closed
  trades, of which the promotion gate can count ONE: CVS at r=-1.68 against a
  gate needing THIRTY. Equity +0.74%.
  4,456 of 4,831 refusals were the 10-position limit. The book filled on day
  one and never emptied - the rails were sized for capital preservation and
  the trial needed throughput. That conflict was never stated, and it is the
  reason there is no edge evidence.
  THREE rails ever bound in production: position limit, cost-to-risk,
  aggregate cap. Five never bound at all.
  The MACHINERY held: 10 of 10 carrying a resting stop at every check across
  19 days, zero kill-switch trips, zero lost sessions, ledgers always written.

THE NEXT WORK IS THE IBKR MOVE, IN FOUR STAGES
Only stage 1 is planned in detail, deliberately - the rest is guessing until
stage 1 measures something.
  STAGE 1  the adapter can be trusted. BLOCKED ONLY ON THE ACCOUNT EXISTING.
  STAGE 2  ASX market data (a commercial decision)
  STAGE 3  ASX trading rules - the $500 MINIMUM MARKETABLE PARCEL reaches
           position sizing directly and IS IMPLEMENTED NOWHERE
  STAGE 4  regime re-sourcing - DO NOT START until the ablation question is
           settled, because it may delete this stage entirely

MEASURED 19 AUGUST AGAINST ib_async 2.1.0, NOT ASSUMED
  recent_fills            -> IB.fills(), IB.reqExecutions()          EXISTS
  resting_stops           -> IB.openTrades(), IB.reqAllOpenOrders()  EXISTS
  resting_stop_orders     -> same                                    EXISTS
  announcements           -> NO STRUCTURED EQUIVALENT. reqFundamentalData is
                             XML reports, reqHistoricalNews is unstructured.
                             M39's detection has no direct port - that is a
                             DECISION to record, not code to write.
  AND THE ONE THAT BITES: from_ib_trade NEVER records broker identity. Alpaca
  overwrites order.order_id at three sites; IBKR at none. So
  _correct_announced_price cannot resolve a fill and BOTH M70 AND M71 GO
  DORMANT ON IBKR WITHOUT ERRORING - the app would record prices it never
  paid, silently, exactly as before M70. Execution carries execId, permId and
  orderId, so the bridge is buildable. Prefer permId if it survives a restart;
  orderId is per-session.

THE ABLATION RAN, AND THE ANSWER IS "NOT WITH THIS INSTRUMENT"
  Three rails on ASX data, all EXERCISED - the first real ablation this
  system has produced. Every difference was INSIDE NOISE: 0.30 to 0.67
  standard errors on 80 trades with a 1.21R standard deviation. Resolving a
  0.09R effect needs ~2,800 trades PER ARM. No realistic window supplies it.
  So expectancy on one window cannot decide whether the regime gate earns its
  keep, and no amount of patience changes that. If that question still needs
  answering, the lever is VARIANCE or DRAWDOWN, which converge far faster.

  ASX replay, 95 symbols over 499 sessions, regime rail LIVE:
    265 candidates, 109 approved, 156 refusals
    80 closed trades - mean -0.06R, total -5.02R, 44% win
    FIVE rails exercised. With the rail inert the same window read +0.03R -
    the positive figure was never an edge measurement.

WORK IS PAUSED PENDING THE IBKR ACCOUNT. This is deliberate, not drift.
Task 3 shipped; Task 2 was stopped before it started because Task 1 measures
exactly what Task 2 would have had to assume. Do not resume Task 2 early.

OUTSTANDING, IN ORDER
  W1.1     Stage 1 Task 1. THERE IS A READY PROMPT FOR THIS AT THE END OF
           docs/HANDOFF.md - paste it the day the account is live.
           Run scripts/ibkr_probe.py READ-ONLY the day the paper account
           exists, and record the RAW responses. NOT broker_capabilities.py,
           which connects to nothing and would rubber-stamp the assumptions
           this task exists to test. Every later task is shaped by it.
           GENUINELY BLOCKED until a Gateway is actually listening on 4002 -
           the account being live is not the same thing.
           IT MUST ALSO SETTLE: does permId survive a Gateway restart (Task 3
           assumes so), are ASX stops native or IBKR-simulated, does a stop
           appear in openTrades(), and how far back do executions go.
  DATA     DECIDED 19 Aug: do NOT buy ASX Total ($25/mo) during testing.
           IBKR is EXECUTION-ONLY in this codebase - neither resolver has an
           IBKR branch, so no IBKR data of any kind can reach the app. Use
           yfinance for ASX data, IBKR for execution. Revisit at a real paper
           trial and price it as subscription PLUS two data sources PLUS a
           universe trim, not as $25.
  M71      FIXED from the code on 17 August but STILL UNOBSERVED in
           production - no app-transmitted sell has ever happened. Five
           sessions of watching produced none.
  Cash floor  bound 15 times on ASX and no rail in the manifest models it.
           Now reported under unmodelled_refusals; still not ablatable,
           because min_cash_reserve is gt=0 BY DESIGN (config.py:416).
           Whether to relax that for research is an OPERATOR decision.
  M43      trading halts. DO NOT build the Alpaca shape - ASX halts are
           announcement-driven, so it depends on the announcements decision.

  DONE: W2, W1.4, M66/M89/M90, ASX macro, M91 positions panel, M92 AU dates,
  M71, M93, M94 regime label.
  DROPPED: SFBS, intraday US harness, US expectancy as a deliverable.

CONSTRAINTS
  PowerShell 5.1 - use ; not && and @'...'@ here-strings, closing '@ col 0.
  Formats with black, not ruff format. Run ruff check ., black --check .,
  mypy src, bandit -r src via the venv python.
  EVERY TEST THAT BUILDS AN OMS MUST PASS ITS OWN data_dir.
  Plan -> approval -> implement -> verify -> commit -> build. ALWAYS ask
  before deploying. Build zips are gitignored - one was committed by mistake
  and the history had to be stripped.
  SESSION WATCH: & "C:\Claude Programming\scripts\session_check.ps1"
  NO ARGUMENTS, EVER - permissions are stored as exact command strings.

THE HABITS THAT FOUND EVERYTHING
  CHECK THE BRIEF AGAINST THE CODE. Three of four next steps were void.
  VERIFY BY BEHAVIOUR, NOT BY BANNER. M90 was confirmed by 5.01% -> 6.34%.
  RENDER IT. The unsigned R-multiple passed a full suite and fell out of a
  screenshot in one look.
  PROVE A TEST FAILS FIRST. Several passed against unfixed code.
  DERIVE, DO NOT REMEMBER.
  AND THE ONE THIS WEEK ADDED: SUSPECT THE INSTRUMENT. Three session_check
  bugs in four days, all of them the script asserting something false about a
  healthy app - a dropped days component, a warm-up warning called a failure,
  and NO REGIME PUBLISHED for a clean session. An alarm you learn to ignore
  is worse than no alarm.
```

---

## 🔑 Prompt to paste THE DAY THE IBKR ACCOUNT IS ACTIVE

Separate from the block above on purpose. That one starts a new context window;
this one starts Stage 1. Paste it when the live account has ASX permissions and
IB Gateway is running.

### IB Gateway setup — do this BEFORE pasting the prompt above

Derived from this application's own config, so the port numbers are the ones the
code actually checks. Menu paths are version-specific; verify them in the UI
rather than trusting this list.

**1. Install IB Gateway, not TWS.** Gateway is the headless one and is what
`ib_async` speaks. TWS works too and its paper port is 7497, but Gateway is the
lighter thing to leave running overnight.

**2. Log in with the PAPER username.** It is a separate username from the live
one, not a toggle on the same credentials. Logging in with the live username and
assuming a paper session is the mistake this whole guard exists to catch.

**3. Enable the API.** Configure -> Settings -> API -> Settings:
  * tick "Enable ActiveX and Socket Clients";
  * set the socket port to **4002** (Gateway paper);
  * add **127.0.0.1** to Trusted IPs;
  * leave "Read-Only API" TICKED for the W1.1 measurement, and untick it only
    for the single stop order question 3 needs.

**PORTS THIS CODE TREATS AS LIVE: 4001 and 7496.** `ib_adapter.py` raises
`LivePortInPaperModeError` if `trading_mode` is paper and `ibkr_port` is either.
Paper ports are 4002 (Gateway) and 7497 (TWS).

**4. Point the app at it.** Defaults already match a paper Gateway, so usually
nothing to change:

    QAT_IBKR_HOST=127.0.0.1     (default)
    QAT_IBKR_PORT=4002          (default - paper Gateway)
    QAT_IBKR_CLIENT_ID=1        (default)
    QAT_TRADING_MODE=paper
    QAT_BROKER=ibkr

**5. Know about the daily restart, because it decides question 1.** IB Gateway
forces a restart every day unless auto-restart is configured, and the app is
meant to run overnight. Configure -> Settings -> Lock and Exit -> Auto Restart.
**ANSWERED 19 August** by exactly that method - a GTC stop left resting,
Gateway restarted, permId 828725903 unchanged. Auto Restart still matters for
overnight running; it is no longer an open question.

**6. Sanity-check the connection before running anything else:**

    & ".\.venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'src'); from ib_async import IB; ib=IB(); ib.connect('127.0.0.1',4002,clientId=99,readonly=True); print('connected:', ib.isConnected(), '| accounts:', ib.managedAccounts()); ib.disconnect()"

Use a clientId that is NOT 1 for this check, so it cannot collide with the app's
own connection. **If `managedAccounts()` shows a live account number rather than
the paper one (paper accounts are prefixed `DU`), stop** — you are connected to
the wrong session.

```
The IBKR paper account (DUQ200898) is LIVE, permissioned for ASX, and EMPTY -
no orders, no positions. Stage 1 Task 1 is done; M95, M96 and M97 are built.
Begin STAGE 1 TASK 4 of docs/superpowers/plans/2026-08-19-ibkr-move.md:
resting_stops and resting_stop_orders.

READ FIRST
  docs/superpowers/specs/2026-08-19-ibkr-capability-measurement.md
  ROADMAP.md M95, M96, M97.

BEFORE QUOTING ANY CURRENT-STATE FIGURE
  .\.venv\Scripts\python.exe scripts/handoff_state.py

WHY THIS ONE NOW
  Without it the app stops verifying that what it believes protects the book
  is actually resting at the broker. "Ten of ten carrying a stop" becomes an
  ASSERTION rather than an OBSERVATION - and that was the US trial's single
  strongest safety claim. Read the protocol for the exact shapes; do not guess
  them. resting_stops is symbol -> stop price, resting_stop_orders is the
  richer record carrying the id and quantity needed to MODIFY one.

MEASURED, SO DO NOT RE-DERIVE
  Both come from openTrades() / reqAllOpenOrders(), and BOTH WERE CONFIRMED to
  show a resting stop on 19 August - orderType STP, auxPrice, status and
  permId all agreeing across the two calls.

  CARRY whyHeld THROUGH. A resting stop read whyHeld='trigger', and a bracket
  leg read 'child,trigger'. That is IBKR's own marker for an order HELD AT
  IBKR awaiting its trigger rather than working at the exchange - a SIMULATED
  stop. It does not settle native-vs-simulated for live ASX (IBKR simulates
  all paper stops), but it means the app can READ what it currently assumes.
  Surfacing it turns the strongest safety claim from an assertion into an
  observation, on exactly the axis the plan worried would be lost.

  CARRY THE OWNING clientId. An order belongs to the clientId that placed it:
  a cancel from another fails with error 10147 while reqAllOpenOrders() STILL
  SHOWS the order and our own object reports PendingCancel. VISIBLE IS NOT
  CANCELLABLE, so "is this position protected" and "can I actually move that
  stop" are different questions and resting_stop_orders should answer both.

  openTrades() is scoped to the CONNECTED client; reqAllOpenOrders() is not.
  They are not interchangeable and a test should say which is used and why.

  THE SYMBOL MUST COME BACK TRANSLATED. IBKR answers BHP, the app tracks
  BHP.AX. symbols.from_ibkr(symbol, settings.market) is the inbound half -
  M97 needed it too, and a stop keyed on the wrong form protects nothing the
  app can find.

HOW
  TDD, red proven first, against a fake IB - do not connect to a broker in a
  test. Then MUTATE to prove each test is load-bearing; this session found
  two tests that passed for the wrong reason exactly that way, and one gap
  where a shape slipped between two guards.
  Then ruff check ., black --check ., mypy src, bandit -r src, pytest tests -q,
  all via ./.venv/Scripts/python.exe. Then commit.
  A LIVE CHECK IS CHEAP AND WORTH IT: place one resting stop far from the
  market, read it back through resting_stop_orders, cancel it. ASK THE
  OPERATOR FIRST. Cancel from the SAME clientId that placed it.

STILL OPEN AFTER THIS
  Task 5, the announcements decision - measured, needs an operator choice.
  Question 4, execution retention - needs a real FILL, the only thing left
  that does.
  Stage 3's ASX rules - the $500 minimum marketable parcel reaches position
  sizing directly and is implemented nowhere. ASX minTick is 0.001, measured.

DO NOT
  Weaken M95's UnrepresentableOrderError guard to make anything pass.
  Trust an empty response from an empty account as evidence a method works -
  that is what made Task 1's first run one third of a measurement.
  Infer cancellability from visibility in reqAllOpenOrders().
```

