# Handoff — 6 August 2026

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

---

## Where things stand

- **Deployed:** M41+M42 (`ec0f5bf`), verified by hash and confirmed to start,
  8 August. Everything below is in it.
- **Repo:** clean, pushed, one branch (`master`).
- **App:** running. The stamp should read `M41+M42 (ec0f5bf)` or later.
  **Never `M56+M51` — that build cannot start.**
- **Next session:** Monday night. US markets are shut for the weekend, which is
  what the 8 August development window was for.

### What landed on 7–8 August, in order

| | |
|---|---|
| **M56b** | Report bounded to the day it claims to cover. The blocked section was lifetime totals under a daily heading — the 6 August daily reported a kill-switch that fired on the 4th |
| **M56c** | The regime gate no longer suppresses EXITS. It gated `on_features` entirely, and that is the only route to an exit signal, so an ineligible strategy was never asked to sell. 29 entries, zero signal exits, 1.19 years |
| **M57** | Earnings event risk — entries halved within 5 trading days of a print |
| **M57a** | The Advanced settings tab was unreachable: the selector sat inside the scroll area |
| **M57b** | `_with_narrative` deleted the report it annotated. Unmasked by M56b — the narrator had been failing for six reports, so the field-dropping path never ran |
| **M57c** | Three observability fixes: the regime line that described a mechanism replaced in M27b, shutdown logging, and the earnings lookup taken off the async signal path |
| **M58** | The M37 diagnostics finally read |
| **M58a** | Detail-level chooser, first run only |
| **M58b** | Correlation measured over 60 bars, not the whole 300-bar buffer |
| **M42** | Partial fills counted at what the broker filled. **Same failure that halted 5 August**, on the path M53 never touched |
| **M41** | Whether a trade was held through its earnings print, recorded on the trade |

1,423 tests; ruff, black, mypy, bandit clean.
- **Holding period:** see ROADMAP.md, *"Where the 30-day hold came from"*. The
  30 was set by a churn milestone with no reference to swing's own cycle, and
  measurement says it is roughly right regardless — shortening it toward the
  originally intended 10 days would roughly halve net return per slot-year.
- **Account:** equity $101,363. Ten positions — AMAT 7, AMD 7, CRWD 16, CSCO 44,
  GS 7, JNJ 19, MS 41, UNP 17, VRTX 19, WFC 58. All protected.
- **Closed trades: one.** CVS, −$482.18, −1.68R. The first this system has ever
  recorded, and it survives restarts.

## The strategic fact that reframes everything

**The long-term intent is to trade the ASX only.** US equities on Alpaca are the
validation vehicle, not the destination — and Alpaca cannot reach the ASX at all.

What the trial genuinely validates is the **machinery**: protection rests, fills
are absorbed, trades are recorded, rails bind. That is market-agnostic. The
**edge numbers are not** — different market, hours, spreads and commissions — and
should not be carried across without being re-earned. See ROADMAP.md, *"Where
this is ultimately going"*.

## What happened on 6 August

Nine milestones. The first four are one chain: any one missing and the first
stop-out still records nothing.

| | |
|---|---|
| **M47** | `status=open` hid a live protective leg once its parent entry filled. Bounded by symbol instead — dates age, symbols do not |
| **M48** | `after=` filters `submitted_at`, so a long-resting order's fill was unqueryable. 0 of 10 reachable → 10 of 10 |
| **M49** | No entry lot for adopted positions, and closed trades never reloaded. The counter could not move off zero |
| **M50** | Fills while the app was down were never asked for |
| **M53** | **A partial fill halted a live session.** M50's dedupe keyed on order id; a partially filling order reports the same id with a growing `filled_qty`. CVS filled 47 in pieces, 30 were absorbed, 17 vanished, kill-switch |
| **M53a** | The same hazard reintroduced through the save path — `quantity_known` was read but never written |
| **M52/M54** | A broker 500 threw a signal away instead of refusing it; a forced start claimed the market was open |
| **M40** | Fundamentals into the AI advisory context |
| **M55/M56** | Axis labels, expertise level made real, Restore Defaults, unsaved-changes prompt, Basic/Advanced split, Exit button, time on the equity axis |
| **M56a** | **M56 could not start.** The chart seed drew onto `self.equity_curve` forty lines before the constructor created it. Found by launching the deployed build nine hours early rather than at the bell |

**Ledger corrected by hand:** CVS rebuilt at its true 47 shares and 95.597 exit;
the MS 41-share row removed as an operator trim rather than a strategy exit.
Backup at `closed_trades.csv.bak-20260806-084823`.

## The pre-flight, and why it is now the habit

The deployed build had been verified by hash and never once **started**. The
executable was written at 12:40; the last run in the log was 11:14 and stamped
`M55`. Hash equality proves the right bytes were installed. It proves nothing
about whether they run.

Launched at 13:50 instead of 23:15, it crashed before the window opened. See
ROADMAP.md, *M56a*. The cost of finding it nine hours early was ten minutes; the
cost of finding it at the bell would have been the session, and probably not
until someone looked at the screen, because the crash wrote nothing to the log.

**So: launch the build in daylight, on the day it is deployed.** Everything that
does not need a moving market can be checked then — the startup lines, the
commit stamp, adoption reading 10, the chart seeded on a real axis. The market
is shut, the session controller stands down, no signals are emitted and nothing
is ordered. What remains for the bell is only what genuinely requires one.

Verified this way on 6 August, against the installed binary rather than a
proxy: full startup, `Adopted 10 … 10 carries a stop resting at the broker`
reading 10, and the equity chart open on a time axis showing history.

## M51 — evaluation, deployed but never yet run in a session

Three pieces, all read-only over records the app already writes, so none of it
changes a decision.

| File | What it does |
|---|---|
| `docs/EVALUATION_BASELINE.md` | What is measured, what that changes, what is captured and never read |
| `docs/LIVE_TRADING_READINESS.md` | What must be true before REAL money. Not near — 1 closed trade of 30, and sizing still on placeholder constants. Written early on purpose |
| `docs/PRODUCT_BLUEPRINT.html` | Printable explanation of the system for a non-expert. Self-contained; open from the filesystem |
| `domain/evaluation/refusals.py` | Why orders did not happen, split by what the refusal MEANS |
| `domain/evaluation/approvals.py` | How close an approval came to being a refusal |

**Both sections are wired into the daily report and were verified through the
real reporter path before the build.** They have never been generated by a live
session — the first will be at tonight's close.

**Pre-verified offline on 6 August**, against copies of the live records so the
originals were untouched. Both sections render, and the reporter's numbers match
an independent pass over `risk_decisions.csv` exactly: 635 candidates,
5 approved, 630 refused, splitting 524 position-limit and 106 risk-cap. What
tonight adds is only that the reporter runs inside a live session.

Two things that pre-verification settled, and which would otherwise look like
defects at the close:

* **`load_risk_decisions` takes `since` with no upper bound**, so a report covers
  that date *onward*, not that date alone. Harmless while the period being
  reported ends today — nothing is dated in the future — but it means the
  6 August figures are a subset of what a 5 August report shows, and two reports
  will legitimately disagree about the same day.
* **"No entry approvals recorded" alongside approvals is correct.** All four
  approvals on 6 August were exits — `exit - closing existing position (entry
  sizing bypassed)`. The approvals section counts entries only.

### What the analysis already says

```
1,418 candidates considered, 42 approved (3.0%)
  capacity   1,107   Position limit 1,001 · Aggregate risk cap 106
  candidate    269   Cost-to-risk (trade too small)

38 entry approvals, 1 trimmed rather than refused (VRTX, cut to 20)
  Cost-to-risk               median 47% of limit, tightest in 24 of 38
  Correlated cluster         median  0%, never tightest
```

Three findings worth carrying forward:

1. **The cost rail is the real constraint on trade quality** — simultaneously
   the largest non-capacity refusal and the tightest rail on trades that pass.
   Every approved entry sits about halfway to uneconomic.
2. **The correlated-cluster cap has never been near binding.** Either the book
   has genuinely never held correlated names, or the measure is not capturing
   what it was built for. An M51 question by definition.
3. **The entire M37 diagnostic set is written and read by nothing** — MAE, MFE,
   entry slippage, regime at entry, exit reason, holding days, costs. Capturing
   first was right; "captured" has been reported as "done" ever since.

## The open queue

1. **Watch tonight's session** — see the paste block below. Three things in this
   build have never met a moving market; the fourth, the M56 chart, was checked
   in daylight and the M51 sections were pre-verified offline.
2. **Watch the two-week baseline.** Configuration is frozen as it stands,
   reviewed around **20 August**. See ROADMAP.md, *"The conservative baseline"* —
   it records the arithmetic behind declining to widen the limits, and why now
   was the cheapest moment to widen if it is ever going to happen.
3. **First-run-only level prompt.** Agreed, not built. Show the detail-level
   chooser when no level has ever been saved — not on every launch.
4. **UI/UX steps 3 onward.** Settings is done; Dashboard and Performance
   deliberately wait until the first batch of closed trades has been read, so
   the interface being read does not change underneath the reading.
5. **Delete the five pre-M46 install backups.** Authorised after a successful
   session, and there has been one — but a protection policy blocks me from
   removing `C:\QuantAdvisoryTerminal*`, so this is manual.
6. **Two cosmetic recurring warnings**, never chased: the report narrative
   failing, and the HMM convergence notice.

## Standing constraints

- **Read `%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell, never Bash.**
- Operator's terminal is **PowerShell 5.1** — `;` not `&&`, and a `@'...'@`
  here-string rather than a heredoc, closing `'@` at column 0.
- **The project formats with `black`, not `ruff format`.** `invoke lint` runs
  `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- **A deploy needs the app closed** — the executable is locked while it runs.
  `Rename-Item` on the install directory is now blocked by policy, so deploy by
  `Expand-Archive -Force` over the top and verify by hash afterwards.
- **Convention:** plan → approval → implement → verify → commit → build. Build
  and sign freely; **always ask before deploying**.
- **Pre-flight every deploy in daylight.** A hash proves the right bytes landed,
  not that they run — see *"The pre-flight"* above. Zips are made by hand;
  `invoke package` does not create one.
- **Validation freeze:** nothing lands that changes which trades happen or how
  large they are. **Lifted once, deliberately, on 7 August** for two changes
  shipped together — M56c, where the regime gate was suppressing exits as well
  as entries, and M57, the earnings event-risk rail. Those are the only
  decision-affecting changes since 3 August; everything else has been defect
  fixes and reporting. Everything else measured that day was **booked, not
  acted on** — see ROADMAP.md, *"Booked for the September review"*.
  **Lifted once more on 8 August**, for M58b alone: the correlated-cluster rail
  now measures over 60 bars rather than the whole 300-bar buffer. Verified
  against the live book to change no decision — the cap needs 5.5 correlated
  names to bind and the book holds one pair. The other two parameter changes on
  the table were declined with reasons recorded.

## What not to re-derive

- **How Alpaca answers queries** — legs return only with their parent, `limit`
  counts raw orders not nested parents, `after=` filters `submitted_at`. All
  measured, all in ROADMAP.md.
- **The bounding lesson, learned four times.** M47 bounded by held symbols, M48
  by tracked, M50 by remembered, M53 by how much of an order was already
  counted. Each time the wrong set looked natural from where the query lived.
- **Timestamp comparisons are not a mechanism.** M50's first design classified a
  fill by comparing two clocks microseconds apart and failed three tests before
  the design changed. The broker is the authority on what is held.
- **`risk_decisions.csv` `inputs` is a Python repr, not JSON** — single quotes,
  `True`, `None`. Parse with `ast.literal_eval` after trying JSON.
- Why swing rarely exits — 29 entries, zero signal exits over 1.19 years.

## The next block of work — M39 first, grouped

Reviewed 8 August. What remains splits into three groups, and the first is the
one to build.

### Group 1 — external changes to a held position (M39, then M43)

**They are the same problem twice.** Something outside this application changes
the state of a position it holds, and the reconciliation and protection
machinery misreads the result:

* **M39, a split.** Broker quantity doubles. Reconciliation compares tracked 16
  against broker 32 and trips the kill-switch. The resting OCO sits at roughly
  twice the new price. `open_position_entries.json` still holds the pre-split
  level, so the re-arm faithfully replaces protection at a price that
  liquidates. The ledger's entry price is unadjusted, so P&L and R on that trade
  are wrong by the split factor.
* **M43, a halt.** The position is held, the symbol is halted, the resting stop
  cannot fill, and it reopens materially lower. Nothing detects it and nothing
  flags that the position is currently unexitable.

Both need the same two seams: **reconciliation being able to be told a
difference is explained**, and **a position being in a state the ordinary path
must not treat as ordinary**. Build that concept once and it serves both.

**Suggested order, which is also the dependency order:**

1. The position-anomaly concept plus the reconciliation seam. Today
   reconciliation compares and trips; it needs a way to be told "this one is
   accounted for".
2. M39 detection and adjustment.
3. M43, reusing the anomaly concept.

**The design risk worth naming before anyone starts.** M39's adjustment has to
be atomic across four places — tracked quantity, the entry record, the resting
protection and the ledger basis. **A partial adjustment is worse than none**:
correcting the quantity but not the stop leaves protection at twice the price,
which liquidates the position at the next open. All four or none.

**On testability**, which was the operator's question. The roadmap's own warning
applies — *"should start by measuring what the broker reports through a split
rather than by reasoning about it"* — and no split has occurred. But the
detection does not have to guess: **yfinance is already a dependency and carries
split history**, so a quantity change whose ratio and date match a published
split is explainable without knowing Alpaca's exact representation. That half is
fully testable now against synthetic ratios. What waits for a real event is only
the confirmation of how Alpaca reports it.

**On the freeze.** M39 does not change which trades happen or how large they
are. It stops a corporate action destroying a position and halting a session,
which is *"the kill-switch tripping on something that is not a real
discrepancy"* and *"protective orders not resting, or not being repaired"* -
both in the fix-immediately list.

### Group 2 — does the captured data earn its place (M44, M51's open half)

Both wait for the September trades. M58 built the reading; M44 is specifically
whether the flat 5bps slippage assumption holds, and `entry_slippage` answers it
the moment there are enough trades to average. Nothing to do until then.

### Group 3 — M32, ASX readiness

The destination, and much the largest. Needs a market-data decision (yfinance
delayed and unofficial, versus IBKR's own), currency handling, and the IBKR live
path actually exercised. Separate piece of work, not adjacent to anything above.

## A note on how the defects were found

Four of the five defects introduced on 6 August passed their tests and were
caught by reading live data — `absorbed_fills.json` on disk, the actual reason
strings in `risk_decisions.csv`, the real fill quantities at the broker, and for
M56a the deployed executable actually being run. The tests verified the logic
that was being thought about; the failures were in the layer that was not.
**Read the files, not just the log lines you expect. Run the build, do not just
hash it.**

M56a sharpens this into something checkable. Its guard test passed because the
fixture could not reach the failure: an empty data directory meant the dangerous
branch was never entered, and the assertion compared two empty lists. **A test
whose fixture cannot reach the failure is not evidence.** Where a defect depends
on recorded state existing, the test has to write that state — which is what the
replacement does.

---

## Prompt to paste

For the next overnight paper-trading session. **"Live" here means a live market
session on the paper account, not real money** — for that, see
`LIVE_TRADING_READINESS.md`, and the answer is not yet.

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
This session covers the overnight paper-trading run: US market opens 13:30 UTC
(23:30 AEST). Paper account throughout — no real money is involved.

Read docs/HANDOFF.md first, then the standing rule at the top of ROADMAP.md and
the section "How Alpaca actually represents orders".

STATE
Deployed build M56a+M51 (ce15676), verified by hash and CONFIRMED TO START. Repo
clean and pushed at ce15676. App is CLOSED and needs launching before the open.
Equity $101,363, ten positions — AMAT, AMD, CRWD, CSCO, GS, JNJ, MS, UNP, VRTX,
WFC — all protected. One closed trade on record (CVS, −$482, −1.68R, stopped
out).

M56a exists because the build originally prepared for this session could not
start at all: the equity-chart seed drew onto a widget the constructor had not
created yet, and it died before the window opened without writing a traceback to
the log. It was found by launching the deployed build nine hours before the open
rather than at it. Keep that habit — a hash proves the right bytes landed, not
that they run. See ROADMAP.md, M56a.

WHAT HAS NEVER RUN IN A LIVE SESSION
Two of the four were checked on 6 August without a market and are noted here so
they are not re-verified from scratch:

  DONE  The equity chart on a real time axis, seeded from equity_curve.csv
        (M56). Confirmed opening with history on a time axis. An overnight gap
        rendering AS a gap is still worth a glance at the open.
  DONE  The two evaluation sections in the daily report (M51). Pre-verified
        offline against copies of the real records — both render, and the
        numbers match an independent pass exactly. What remains is only that
        they generate from inside a live session, at the close.

Still untested by anything short of a moving market:

  1. Partial-fill absorption (M53). Only exercised if a stop fills in pieces —
     which is exactly how the CVS stop behaved and how the last session was
     halted. If it happens, check tracked quantity ends equal to the broker's.
  2. Refusal-on-broker-failure (M54). Only visible if Alpaca errors. A 500
     should now produce a rejected order with a reason in the journal, not an
     "EventBus handler failed" line and a vanished signal.
  3. REGIME classifying at the bell. The market was shut for every check on
     6 August, so the session controller correctly stood down and the regime
     engine published nothing. Nothing has confirmed it classifies.

AT THE OPEN — the startup lines that must appear
  Build: M56a+M51 (ce15676, ...)      <- NOT M56+M51; that build cannot start
  Broker-fill watermark restored to ...
  Restored N closed trade(s) from closed_trades.csv
  Restored 10 open lot(s) to the trade ledger
  Adopted 10 ... 10 carries a stop resting at the broker    <- must read 10
  REGIME ... within seconds of the bell
Their ABSENCE is the signal, not their content. The watcher now prints the
Build: line itself — until 6 August it filtered out the one line carrying the
stamp the operator is told to check.

EXPECT A QUIET SESSION
Risk-at-stop sits at roughly 5.00% against a 5% cap and the ten-position limit
is full, so few or no new entries will be permitted — that is the rails working,
not a fault. Last check had nothing within 5% of its stop. A log that goes quiet
is indistinguishable from an app that has died, so check that risk_decisions.csv
and equity_curve.csv are still being written before concluding "nothing
happened". That is not hypothetical: the M56a crash produced exactly this
signature — the stamp, two restore lines, then silence — and would have read as
a quiet session all night.

The watcher, started BEFORE the app so the startup lines are captured:
  & "C:\Claude Programming\.venv\Scripts\python.exe" "C:\Claude Programming\scripts\watch_session.py"

QUEUE, if the session is uneventful
  1. First-run-only detail-level prompt — agreed, not built. Show the chooser
     when no level has ever been saved, not on every launch.
  2. UI/UX steps 3 onward. Settings is done; Dashboard and Performance wait
     until a batch of closed trades has been read.
  3. Delete the five pre-M46 install backups in C:\ — authorised, but a
     protection policy blocks it from the tool side, so it is manual.
  4. Two cosmetic recurring warnings never chased: the report narrative
     failing, and the HMM convergence notice.

Configuration is FROZEN for a two-week baseline, reviewed around 20 August. The
freeze permits defect fixes and additional recording, never changes to which
trades happen or how large they are.

Constraints: read %LOCALAPPDATA%\QuantAdvisoryTerminal via PowerShell only,
never Bash. PowerShell 5.1 — use ; not && and @'...'@ here-strings. The project
formats with black, not ruff format. A deploy needs the app closed and uses
Expand-Archive -Force, since renaming the install directory is blocked; the zip
is made by hand, invoke package does not create one. Plan and get approval
before implementing; build and sign freely but always ask before deploying, and
pre-flight the result in daylight.

One habit worth keeping: on 5–6 August, four of five defects introduced passed
their tests and were caught by reading live data — absorbed_fills.json on disk,
the real reason strings in risk_decisions.csv, actual fill quantities at the
broker, and the deployed executable actually being run. Read the files, not only
the log lines you expect; run the build, do not just hash it. M56a's guard test
passed because its fixture — an empty data directory — could not reach the
failure, so it compared two empty lists. A test whose fixture cannot reach the
failure is not evidence.

Start by confirming the deployed build, launching the app, and watching the open.
```
