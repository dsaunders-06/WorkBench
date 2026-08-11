# Handoff — 12 August 2026, morning

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

# ⚠️ THE MNST split — DONE, and it cost real money

**Ex-date was Tuesday 11 August. The event landed at the 23:30 AEST open, the
stop fired, and the position is gone.** The next one with a clock on it is
**SFBS 2-for-1 on 21 August** — not held, so running that test means buying it,
and the stop must be widened beforehand or the same thing happens again.

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

## M71 — the same root cause as M70, on the way OUT

App-transmitted sells announce at the reference price too, so the ClosedTrade's
**exit** price is wrong. Separate from M70 because correcting it means rewriting
a record already on disk. **Read from the code, not yet verified against a live
transmitted sell** — do that before designing it.

---

# What has landed since 8 August

**18 milestones across 19 commits, none deployed.** Run `handoff_state.py` for
the current list rather than trusting this paragraph.

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

# Deploying, when the test is done

**18 milestones ahead of the deployed `M63+M62 (49482c2)`.** Three commits do
not carry their number in the subject (M64, M67, M68), so counting with
`git log | grep M[0-9]` under-reports by three — use `handoff_state.py`.

**Before deploying:**

* **Back up `open_position_entries.json`.** The first launch of a build
  containing M65 rewrites it for eight positions.
* **Know that the level model now gates real controls.** The Workbench deploy
  button is Professional-only (M74) and Blotter bulk sign-off is Standard-and-
  above (M77). Live config is `QAT_UI_LEVEL=professional`, so nothing is lost —
  but the default is `standard`, and a config reset takes the deploy button.
* A deploy needs the app closed, uses `Expand-Archive -Force` over
  `C:\QuantAdvisoryTerminal`, is verified by hash and **then launched**. A hash
  proves the right bytes landed, never that they run — M56a passed its hash
  check and could not start.

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

ALSO FOUND, NOT FIXED
  M66  the aggregate risk cap that gates every entry is measured against ENTRY
       prices - nothing in the trading path passes current ones. INSIDE THE
       FREEZE, needs a recorded lift. Designed in docs/superpowers/specs/.
  M71  the same root cause as M70 on app-transmitted SELLS, so the exit price
       is wrong too. Needs a record rewrite. Read from code, NOT verified.

STATE
Deployed build M63+M62 (49482c2). HEAD is 18 MILESTONES AHEAD and none of it
is deployed. Repo clean and pushed. Ten positions held, all protected. TWO
closed trades (CVS -482.18 -1.68R; MNST -375.23, unattributed). Group 4 (the
interface) is COMPLETE. M84 and M85 are two new strategies - DESIGNED, NOT
BUILT, NOT ACTIVATED, selectable via default_strategies() but absent from
QAT_DEPLOYED_STRATEGIES.

BEFORE DEPLOYING
  Back up open_position_entries.json - the first launch of a build containing
  M65 rewrites it for eight positions.
  The level model now gates real controls: Workbench deploy is Professional
  only, Blotter bulk sign-off is Standard and above. Live config is
  professional so nothing is lost, but the DEFAULT is standard.
  App closed, Expand-Archive -Force, verify by hash, THEN LAUNCH. A hash
  proves the right bytes landed, never that they run.
  Expect Adopted 10 now, not 11 - MNST is gone.

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
