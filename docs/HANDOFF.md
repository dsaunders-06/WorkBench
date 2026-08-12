# Handoff — 12 August 2026, end of day

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

**M39 is built and deployed, and it changes nothing until promoted.** The split
that motivated it cost $375.23 on 11 August; the machinery that would have
prevented it now runs in shadow mode, has been watched rejecting the one false
positive in the live book, and will not touch an order until
`QAT_CORPORATE_ACTION_MODE=act`. The deploy gap is zero. **Then the ground
moved:** the operator brought the ASX forward from eventual destination to
near-term one, which reframes the trial rather than pausing it. Throughput was
never going to prove an edge — 2 closed trades in 12 days against 30 per
strategy, with the cap breached so the number is zero — and now it does not have
to. **The binding constraint stopped being evidence and became
instrumentation.** The 20 August review still matters, but it is deciding a
different question.

---

# 📌 TOMORROW, 13 AUGUST — DEPLOY M88

**The deploy gap is no longer zero, and this is the first undeployed change all
day that is not tests, documents or an unreachable branch.** Deferred
deliberately on the evening of 12 August, not forgotten.

    Deploy gap
      milestones      1 across 4 commits
      which           M88

**What is undeployed:** `absorb_broker_fills` took its watermark *after* the
pass, so a protective fill executing while the pass ran fell below the next
query's floor and was never read again — a stop firing, and no closed trade for
it. The installed build still has that window open. Every sweep of tonight's
session runs with it.

**Before deploying, run the derivation rather than trusting this block:**

    .\.venv\Scripts\python.exe scripts/handoff_state.py

**The deploy checklist that already exists is in "For the next deploy" below** —
back up `open_position_entries.json` and the data directory, close the app,
`Expand-Archive -Force`, verify by hash, launch, and **update `DEPLOYED` in
`scripts/handoff_state.py`**. The permission classifier refuses the expand step,
so the operator runs it. **Always ask before deploying.**

**Do it in the morning, after the overnight session has ended** — the app must
be closed, and ten positions are held.

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
against a paper account, read-only. The capability matrix is the checklist. And
**W2**, the portfolio-level replay harness, which is the asset that survives the
move and can start now because it needs no broker.

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

Read docs/HANDOFF.md first, then the standing rule at the top of ROADMAP.md,
then the sections "MNST split test - THE RESULT" and "How Alpaca actually
represents orders".

BEFORE QUOTING ANY CURRENT-STATE FIGURE, RUN:
  .\.venv\Scripts\python.exe scripts/handoff_state.py
It derives the deploy gap, the milestone list and the test count, and names any
stale test count in the handoff. FOUR hand-maintained counts were wrong in
three days. Counting is not the fix - deriving is.

THE SPLIT TEST IS DONE. IT COST REAL MONEY.
8 MNST bought Monday at 91.1838 with a hand-placed sell stop at 72.68. Alpaca
halved the PRICE to ~46 and NEVER delivered the shares. The stop was not
adjusted, not re-priced, not re-quantified - it fired at the open and
liquidated the position in three partials (1@46.34, 3@46.16, 4@45.79).

  THE -375.23 IS A REAL LOSS, NOT AN ARTEFACT. An earlier handoff and a
  morning brief both called it an artefact; both were wrong, and wrong because
  they assumed instead of checking. Verified against /v2/account/activities:
  729.47 out, 367.98 in, NO SPLIT / CSD / share delivery of any kind, equity
  moved 101,754.81 -> 101,387.14 consistently.

  THE RECORD IS NOW CORRECTED AND VERIFIED. exit_reason target -> stop, and
  strategy swing -> blank. Checked through the app's own loader: 2 trades
  parse, MNST has strategy=None, and strategies() returns ['swing'] only, so
  MNST is correctly out of the promotion gate. The money was NOT touched.
  Backups: closed_trades.csv.bak-20260806-084823 (the CVS correction) and
  closed_trades.csv.bak-20260812-084430-POST-correction.

  Quantity went 8 -> 0, never 8 -> 16. So NO divergence, NO kill-switch trip,
  and M60's declare-then-quarantine was NEVER EXERCISED. Accepted knowingly.

  THE FINDING: an unadjusted stop through a split does not merely misreport -
  IT LOSES ABOUT HALF THE POSITION, FOR REAL. -51.4% on a position that should
  have been roughly flat. CAVEAT: paper account, and Alpaca paper's corporate
  action handling may be incomplete in ways a live one is not. DESIGN M39 FOR
  THE BEHAVIOUR MEASURED, NOT THE ONE PREFERRED.

  ALSO SETTLED: a split can arrive IN HALVES, price first and shares later or
  never, so a detector keyed on quantity alone is blind to exactly the window
  where the stop is lethal. ACCOUNT ACTIVITIES ARE USELESS FOR DETECTION -
  zero SPLIT rows through a real split. Announcements duplicate and the count
  changes, so dedupe on (symbol, ex_date). Order ids survive across days.

  STILL UNMEASURED: what happens when the position SURVIVES to the share
  adjustment. Never reached. SFBS 2-for-1 on 21 August is the next chance -
  WIDEN THE STOP BEFOREHAND or the same thing happens again.

SETTLED 12 AUGUST - the strategy: null alarm was WRONG (M86)
It was NINE, not ten - VRTX carried swing. And nothing was unattributed:
restore_open_lots passes `entry.strategy or _sole_deployed_strategy()`, so with
swing the only deployed strategy all ten restored as swing, attributed, with an
R-multiple. Measured through the app's own path, not read off the file. CVS is
the proof - no strategy field at all in the pre-m33b backup, closed as swing.
The nulls were pre-M49 legacy: M49 added the field 5 Aug 00:11 UTC, those nine
records were written 31 Jul and 4 Aug.

  THE REAL DEFECT, WHICH HAD A CLOCK: attribution was INFERRED from a config
  value at every launch, not stored. _sole_deployed_strategy returns None the
  moment a SECOND strategy is deployed - so ACTIVATING M84 OR M85 WOULD HAVE
  RETROACTIVELY UNATTRIBUTED NINE HELD POSITIONS. Measured: strategies() -> [].
  It had NO TEST AT ALL. Both halves now fixed - M86 heals the record at
  startup, and the LIVE RECORD WAS CORRECTED for the deployed build. Backup
  open_position_entries.json.bak-20260812-090344-PRE-M86-strategy-backfill.
  Now 0 null, 10 named, two-strategy case returns ['swing'] not [].
  Swing was a FACT not a guess - decision_journal.csv records strategy=swing
  for all nine with transmit timestamps matching opened_at to the second.

  SO THE M84/M85 ACTIVATION HAZARD IS CLEARED. It was never in the strategies
  themselves - it was in the record they would have silently emptied.

M39 IS BUILT AND DEPLOYED - and it ships in SHADOW, so it changes nothing
Splits only. Detection is ANNOUNCEMENT-DRIVEN because a quantity-triggered
detector would never have fired on MNST: Alpaca halved the PRICE and never
delivered the shares, so quantity went 8 -> 0. Phase 1 re-prices the resting
stop before the ex-date open and touches NOTHING else - halving the basis would
have shown MNST as roughly flat when the loss was real. Phase 2 acts only on an
OBSERVED quantity change and deliberately does NOT rewrite the ledger, because
that path has ZERO OBSERVATIONS and still does.

  NO FREEZE LIFT WAS NEEDED. Phase 1 is the standing rule's own fix-immediately
  category - "protective orders not resting, or not being repaired" - and a
  sell-stop at 72.68 against a 46 market is a liquidation order, not protection.
  Refusing entries on a pending action refuses strictly MORE, which is M60's
  precedent. Shadow default makes it a no-op until deliberately promoted.

  TO PROMOTE IT: QAT_CORPORATE_ACTION_MODE=act. Read the shadow log first.

  THE GATE HELD IN PRODUCTION, which is the result that matters. The log says
  "CORPORATE ACTION first seen: CRWD ex-date 2026-07-02 ratio 4" and then does
  NOTHING - no SHADOW line, no ADJUSTED line. CRWD is held, 16 shares, correctly
  sized post-split with a correct OCO at 163.32. Without the ex_date gate the
  monitor would divide that stop by four to ~40.83 and, in act mode, liquidate
  the position at the next open. The gate is now the ONLY defence - the lookback
  used to exclude CRWD before the gate was consulted - and it has been WATCHED
  doing the job. Re-run scripts/analysis/probe_live_announcements.py to recheck.

  TWO DEFECTS FOUND BY DEPLOYING, both invisible to a fully passing suite.
  Widening the lookback to 90 made the range 135 and Alpaca caps it at 90, so
  every query failed - and a probe for exactly that path had not been re-run
  after the constant changed. WORSE: the Risk Console kept saying "none pending
  on held positions" while blind. The cap is now enforced in the ADAPTER, and
  blindness is a REPORTED STATE rather than a silence.

THE ASX MOVED FORWARD - 12 August, and it reframes everything below
The operator will call the ASX move EARLY if it becomes a strong proposition:
six to twelve months of validation are better spent in the destination market
than the staging one. Spec:
docs/superpowers/specs/2026-08-12-asx-transferable-validation-design.md

  THE RULE: between now and the call, everything built is either
  market-agnostic or cheap to abandon. Transferable - the machinery, the
  research harness, the data ports, the evidence framework, M39/M43/M60. NOT
  transferable - US expectancy figures, which stop being a deliverable and
  become validation of the instrument.

  W1.0 IS DONE AND PUSHED. IBAdapter implements 8 of BrokerAdapter's 12
  methods; absent are recent_fills, resting_stops, resting_stop_orders and
  announcements - fill absorption, protective-order integrity, corporate-action
  detection. THEY ARE OPTIONAL BY DESIGN and every caller guards with getattr,
  so an adapter lacking them neither crashes nor corrupts - it silently stops
  verifying, absorbing and detecting, with a full suite passing. RUN
  scripts/broker_capabilities.py, do not quote a count. resolve_broker used to
  return MockBroker(seed=1) for broker=ibkr after attempting NOTHING; it
  refuses now. And ROADMAP was WRONG that ibkr is "unimplemented beyond the
  seam" - ib_adapter.py is 223 lines and costs.py already carries ASX cost
  profiles saying live trading starts on ASX.

  NEXT, WITH A CLOCK: W1.4. The operator is opening a LIVE IBKR account to
  reach the paper API - TWS API via IB GATEWAY, which is what ib_async speaks,
  ports 4002 paper / 4001 live. ib_adapter.py:74 RAISES when trading_mode is
  live and unconfirmed but only WARNS when trading_mode is paper and ibkr_port
  is a LIVE port, then connects. Inert today. On the morning that account
  exists, a log line is the only thing between a port typo and real orders.
  MAKE IT A REFUSAL BEFORE ANY IBKR CREDENTIAL ENTERS CONFIGURATION.

  THEN W1.1 - measure what IBKR actually returns for those four, paper account,
  read-only, capability matrix as the checklist. AND W2, the portfolio-level
  replay harness: no portfolio simulation exists anywhere, the vectorized
  engine has no stop/target/time-stop and exits only on signal flips, and the
  replay scripts hand-copy the rules from swing.py. It needs no broker, so it
  can start now.

OUTSTANDING, IN THE ORDER I WOULD TAKE THEM
  M66  the aggregate risk cap that gates every entry is measured against ENTRY
       prices, so a winning book UNDERSTATES its risk and the bias grows with
       profit. The one item genuinely behind the freeze, and fixing it makes the
       measured figure HIGHER - so it tightens an already-breached cap. Pair it
       with the 20 August cap review rather than doing it alone. Designed in
       docs/superpowers/specs/2026-08-08-risk-at-stop-current-prices-design.md.
  M71  app-transmitted SELLS announce at the reference price, so the recorded
       EXIT price is wrong too. Read from code, NEVER VERIFIED - it needs one
       live transmitted sell to confirm, and both closed trades so far were
       broker-side stops. Do not design it until one has been observed.
  M43  trading halts. M60 built the flagging half; this needs its own detector,
       and a halt has no ratio to match so it is a different question from M39.
  M44  execution quality. Waits on real closed-trade slippage data, and M70
       found entry_slippage was zero by construction, so the instrument itself
       only started working recently.
  UI   the Balances panel cannot go below 1056px and overflows in a narrower
       container. Eliding the labels did not lower it - the bold money values
       set the floor, and eliding a money figure misleads where eliding a label
       merely abbreviates. Not hit at any real window size today.

STATE - 12 August, end of day
Deployed build is M39+M87 (67677bc). THE DEPLOY GAP IS NO LONGER ZERO: M88 is
built, tested, pushed and NOT INSTALLED, and the operator deferred the deploy
to the MORNING OF 13 AUGUST deliberately. Until it lands, every sweep of
tonight's session can lose a protective fill that executes while the absorb
pass is running - a stop firing, and no closed trade for it. Ask before
deploying, back up the data dir first, and update DEPLOYED in handoff_state.py
after. Repo clean and pushed. Ten positions held, 10 of 10 protected, Adopted 10 not 11. TWO closed
trades (CVS -482.18 -1.68R; MNST -375.23, unattributed - and it STAYS
unattributed, that one is correct). Group 4 COMPLETE. M84 and M85 remain
DESIGNED, NOT BUILT, NOT ACTIVATED - and M86 cleared the hazard that made
activating them destroy nine positions' worth of attribution.

  THE AGGREGATE CAP IS BREACHED at 5.01% vs the 5.00% cap, so NEW ENTRIES ARE
  REFUSED. It predates every deploy today. With 2 closed trades in 12 days and
  30 needed PER STRATEGY, throughput was never going to prove an edge - and
  under the ASX reframing it no longer has to. Live paper answers the
  OPERATIONAL questions at the sample size it can reach; the edge question
  moves to the W2 harness.

  SO THE 20 AUGUST REVIEW DECIDES A DIFFERENT QUESTION. Widening the co-binding
  10-position / 5% pair buys throughput, and throughput buys US closed trades,
  which are now MACHINERY evidence rather than EDGE evidence. DECIDED: the
  rails HOLD, and ONE SLOT IS FREED DELIBERATELY for SFBS 2-for-1 on 21 August -
  the only dated chance to observe a split where the position SURVIVES to the
  share adjustment, which M39 Phase 2 has never seen. WIDEN THE STOP
  BEFOREHAND. M66 lands AFTER that event, not before: it raises the measured
  figure on an already-breached cap and would take back the slot.

  THE MANUAL IS CURRENT. It was last rebuilt 5 August for M49, and 53 of 91
  settings appeared nowhere while "quarantine" and "corporate action" appeared
  ZERO times. 29 settings added, three sections written (11.9 interface level,
  12.4 quarantine, 12.5 corporate actions). Two guards stop it rotting: every
  setting documented or excused with a reason, and every "Section N.M" must name
  a heading that exists - added after renumbering silently broke FOUR existing
  cross-references.

CONSTRAINTS
  READ %LOCALAPPDATA% VIA POWERSHELL, NEVER BASH. The Bash tool sees a
  sandboxed copy frozen at 27 July, and PowerShell launched FROM Bash inherits
  it, so the Monitor tool is blind too. A watcher armed there reads a file
  that never changes - it does not error, it goes quiet, and quiet looks
  exactly like healthy. Overnight watching must be a SCHEDULED PROMPT using
  the PowerShell tool. Bash IS correct for the venv python and Alpaca API
  calls - the sandbox is filesystem-only.
  PowerShell 5.1 - use ; not && and @'...'@ here-strings, closing '@ col 0.
  Formats with black, not ruff format. Run ruff check ., black --check .,
  mypy src, bandit -r src via the venv python.
  EVERY TEST THAT BUILDS AN OMS MUST PASS ITS OWN data_dir.
  Freeze: nothing lands that changes which trades happen or how large.
  Reporting and logging are explicitly permitted, and a defect that corrupts
  the record is FIX-IMMEDIATELY.
  Plan -> approval -> implement -> verify -> commit -> build. ALWAYS ask
  before deploying.

THE HABITS THAT FOUND EVERYTHING
  CHECK THE BRIEF AGAINST THE CODE. §4.x described something that was not
  there EIGHT TIMES across seven milestones - the register in ROADMAP.md lists
  each one. Count the rows there; do not restate the number.
  RENDER IT, do not trust the suite. Screenshotting found an orphaned grid
  row, an off-scale font, stranded labels, "Grew -0.0% a year", a notice
  floating in an empty screen and a truncated column. Every test passed.
  ASK WHAT READS IT. Six values were computed and displayed nowhere. That one
  now has a test.
  TEST THE CLAIM, NOT THE ARITHMETIC. Every defect found on 11 August was in a
  sentence that predicted or explained, never in a number.
  DERIVE, DO NOT REMEMBER. And CHECK BEFORE ASSERTING - the "artefact" claim
  above was reasoned rather than measured, and it was wrong.
```
