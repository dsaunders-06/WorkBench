# Handoff — 6 August 2026

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

---

## Where things stand

- **Deployed:** M56 (`1d4e862`). **Repo is four commits ahead of the deployed
  build** — M51's evaluation work is committed and pushed but not built.
- **Repo:** clean, pushed, one branch (`master`), HEAD `247ce21`.
- **App:** not running. Launch before the next session; the stamp should read
  `M56 (1d4e862)`.
- **Account:** equity $101,347. Ten positions — AMAT 7, AMD 7, CRWD 16, CSCO 44,
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

**Ledger corrected by hand:** CVS rebuilt at its true 47 shares and 95.597 exit;
the MS 41-share row removed as an operator trim rather than a strategy exit.
Backup at `closed_trades.csv.bak-20260806-084823`.

## M51 — evaluation, built and NOT deployed

Three pieces, all read-only over records the app already writes, so none of it
changes a decision.

| File | What it does |
|---|---|
| `docs/EVALUATION_BASELINE.md` | What is measured, what that changes, what is captured and never read |
| `domain/evaluation/refusals.py` | Why orders did not happen, split by what the refusal MEANS |
| `domain/evaluation/approvals.py` | How close an approval came to being a refusal |

**Both sections are wired into the daily report and will appear on the next
build.** They have never run in the app.

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

1. **Build and deploy M51** so the evaluation sections appear in the daily
   report. Nothing else is waiting on it.
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
- **Validation freeze:** nothing lands that changes which trades happen or how
  large they are.

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

## A note on how the defects were found

Three of the four defects introduced on 6 August passed their tests and were
caught by reading live data — `absorbed_fills.json` on disk, the actual reason
strings in `risk_decisions.csv`, the real fill quantities at the broker. The
tests verified the logic that was being thought about; the failures were in the
layer that was not. **Read the files, not just the log lines you expect.**

---

## Prompt to paste

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
Read docs/HANDOFF.md first, then the standing rule at the top of ROADMAP.md,
the section "Where this is ultimately going", and "How Alpaca actually
represents orders".

Deployed build is M56 (1d4e862). The repo is clean and pushed at 247ce21, four
commits AHEAD of what is deployed - M51's evaluation work is committed but has
never run in the app.

Nothing is mid-flight. The next task is to build and deploy M51 so the two
evaluation sections appear in the daily report, then watch the two-week baseline
to a review around 20 August.

Long-term intent is to trade the ASX only; Alpaca is US-only and is the
validation vehicle, not the destination. What the trial validates is the
machinery, not the edge numbers.

Constraints: read %LOCALAPPDATA%\QuantAdvisoryTerminal via PowerShell only,
never Bash. PowerShell 5.1, so ; not && and @'...'@ here-strings. The project
formats with black, not ruff format. A deploy needs the app closed and must use
Expand-Archive -Force, since renaming the install directory is blocked. Plan and
get approval before implementing; build and sign freely but always ask before
deploying. The validation freeze permits defect fixes and additional recording,
not changes to which trades happen.
```
