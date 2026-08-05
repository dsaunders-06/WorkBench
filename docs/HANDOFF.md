# Handoff — 5 August 2026 (late)

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

---

## Where things stand

- **Deployed:** M50 (`914b9af`). Repo clean and pushed, one branch (`master`).
- **Account:** Alpaca paper, ten positions — AMAT 7, AMD 7, CRWD 16, CSCO 44,
  CVS 47, GS 7, JNJ 19, MS 82, UNP 17, WFC 58. All ten protected, and verified
  against the live account: **the app now sees all ten** (it saw six).
- **MS is deliberately noted:** 82 shares against an intended 41, from the
  duplicate-entry defect fixed in M46. Protected by two brackets. Whether to
  trim is the operator's call, not a defect.
- **Closed trades: still zero** — but for the first time the counter *can*
  move. Until today it could not, under any circumstances.

## What changed today, and why it is one thing

Four defects, all in what the app asked the broker or what it did with the
answer. None changes a trading decision. They only make sense as a chain: any
one left unfixed and the first stop-out still produces nothing.

| | What was broken | State now |
|---|---|---|
| **M47** | `status=open` hid a live protective leg once its parent entry filled | 10 of 10 positions read as protected |
| **M48** | `after=` filters `submitted_at`, so a long-resting order's fill was unqueryable | 0 → 10 of 10 reachable |
| **M49** | No entry lot for adopted positions; closed trades never reloaded | Trade recorded, and it survives a restart |
| **M50** | Fills while the app was down were never asked for | Replayed and recorded at next start |

The measured cost of M47 alone, from the 4 August session: 412 duplicate orders
refused, and the aggregate risk-at-stop cap pinned at 33.66% against a 5% limit
for eight and a half hours, so no new entry could have been approved.

## What to look for in the next session

New lines, whose **absence** is the signal something did not wire up:

- `Broker-fill watermark restored to …` at startup (M50)
- `Restored N open lot(s) to the trade ledger` at startup (M49)
- `Restored N closed trade(s) from closed_trades.csv` once any trade has closed
- `N carries a stop resting at the broker` must read **10**, not 6
- Aggregate risk-at-stop should come off the 33.66% ceiling
- If a stop fires: `BROKER-SIDE FILL absorbed`, then a row on the Performance
  tab that is still there after the next restart

## The open task — nothing is mid-flight

1. **Watch a session on M50.** The first closed trade is the evidence the whole
   trial exists to collect, and four separate defects stood between the system
   and recording one.
2. **Clock-granularity fragility in tests.** Windows' clock is coarse enough
   that two `datetime.now(UTC)` calls return the same value, and three separate
   test failures today traced to it. The M48/M50 tests nudge a watermark back a
   second to work around it; the older broker-side-fill tests pass on timing
   luck. Worth making the time source explicit and injectable instead.
3. **M40 — fundamentals absent from the AI advisory context.** Cheapest item in
   ROADMAP.md, and not behind the freeze.
4. **Ten install backups** now sit in `C:\`, four from today, roughly 4 GB. The
   pre-M46 ones are almost certainly dead weight. Deleting installs is the
   operator's call; ask which go.

## Files the app now reads as well as writes

Three things under `%LOCALAPPDATA%\QuantAdvisoryTerminal\data` are load-bearing
where some were previously write-only:

| File | Note |
|---|---|
| `closed_trades.csv` | Read at every launch (M49). Gained `reference_price`, `worst_price`, `best_price` so a reloaded trade keeps its M37 excursion diagnostics |
| `open_position_entries.json` | Now carries `strategy` (M49). The ten current entries predate it and resolve to the sole deployed strategy, `swing` |
| `absorbed_fills.json` | New (M50). Watermark plus ids of fills already recorded, pruned to 30 days |

## Standing constraints

- **Read anything under `%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell,
  never Bash.** The Bash tool sees a stale view of that path and has produced
  confidently wrong readings four times in this project.
- The operator's terminal is **Windows PowerShell 5.1** — no `&&`, use `;`.
  PowerShell has no heredoc; use a `@'...'@` here-string for commit messages,
  closing `'@` at column 0.
- **The project formats with `black`, not `ruff format`.** `invoke lint` runs
  `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`. Running
  `ruff format --check` reports files that are perfectly fine.
- **Convention:** plan → operator approval → implement → verify → commit →
  build. Build and sign freely; **always ask before unzipping over
  `C:\QuantAdvisoryTerminal`.**
- **Validation-phase freeze:** nothing lands that changes which trades happen or
  how large they are. Defect fixes and additional recording are permitted; see
  the standing rule at the top of ROADMAP.md.
- ASX is deferred. US equities on Alpaca paper only.

## Durable context, already written down

| Document | What it holds |
|---|---|
| `ROADMAP.md` | Standing rule, operating cadence, the Alpaca order model, M39–M44 unaddressed gaps, and every milestone with its reasoning |
| `docs/UI_UX_APPROACH.md` | UI/UX plan. Steps 1–2 committed as M45 but **not built or deployed**. Screen work waits for closed trades |
| `docs/PRODUCT_DESCRIPTION.md` | Current capability, written for evaluation, limitations given equal weight |
| `scripts/manual_body.py` | The user manual's source. Sections 10.3 and 10.5 were corrected for M49 — the manual is not bundled into the executable, so it needs no rebuild of the app |
| `scripts/watch_session.py` | Live session watcher. `--from-start --no-follow` for morning review |

## What not to re-derive

- **How Alpaca answers queries** — all measured, all in ROADMAP.md under *"How
  Alpaca actually represents orders"*: legs only return with their parent,
  `limit` counts raw orders rather than nested parents, and `after=` filters
  `submitted_at` rather than fill time.
- **The bounding lesson, learned three times.** M47 bounded its query by held
  symbols, M48 by tracked symbols, M50 by remembered ones. Each time the wrong
  set was the one that looked natural from where the query lived. Before adding
  a fourth broker query, ask which set is empty exactly when it matters.
- **Timestamp comparisons are not a mechanism.** M50's first design classified
  a fill by comparing two clocks microseconds apart; it failed three tests
  before the design changed rather than the boundary. The broker is the
  authority on what is held.
- Why swing rarely exits — 29 entries, zero signal exits over 1.19 years.
- Why the walk-forward numbers are weak — the windows manufacture an entry at
  each slice boundary.
- That the AI advisory context carries no fundamentals — that is M40.

---

## Prompt to paste

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
Read docs/HANDOFF.md first, then the standing rule at the top of ROADMAP.md and
the section titled "How Alpaca actually represents orders".

Deployed build is M50; repo is clean and pushed on master.

Nothing is mid-flight. M47 through M50 fixed the four defects that stood between
this system and recording a single closed trade - protection invisible after an
entry filled, the fill of a resting order unqueryable, no entry lot to match it
against, and no memory of fills that happened while the app was down. The trade
counter can now move off zero for the first time; it has never done so.

The next thing that matters is watching a session run and confirming the new
startup lines appear: "Broker-fill watermark restored", "Restored N open lot(s)
to the trade ledger", and "N carries a stop resting at the broker" reading 10
rather than 6.

Constraints: read %LOCALAPPDATA%\QuantAdvisoryTerminal via PowerShell only,
never Bash. The operator's terminal is PowerShell 5.1, so use ; not && and a
@'...'@ here-string rather than a heredoc. The project formats with black, not
ruff format. Plan and get approval before implementing; build and sign freely
but always ask before deploying over C:\QuantAdvisoryTerminal. The
validation-phase freeze permits defect fixes, not changes to which trades
happen.

Start by reviewing the most recent session log for whether the M49 and M50
startup paths actually fired.
```
