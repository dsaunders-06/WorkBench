# Handoff — 5 August 2026 (evening)

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

---

## Where things stand

- **Deployed:** M48 (`ce568f1`). Repo is at `ce568f1`, clean, **4 commits ahead
  of `origin/master` — not yet pushed**. One branch (`master`).
- **Account:** Alpaca paper, ten positions — AMAT 7, AMD 7, CRWD 16, CSCO 44,
  CVS 47, GS 7, JNJ 19, MS 82, UNP 17, WFC 58. **All ten are protected, and the
  app can now see all ten** (it could see six).
- **MS is deliberately noted:** 82 shares against an intended 41, from the
  duplicate-entry defect fixed in M46. Protected by two brackets. Whether to
  trim it back is the operator's call, not a defect to fix.
- **Closed trades: still zero.** That is the number that matters.
- Backups of the two previous installs are at `C:\QuantAdvisoryTerminal-M46-backup`
  and `-M47-backup`. Delete when M48 has survived a session.

## What M47 and M48 changed

Both were defects in **what the app asked the broker**, not in what it did with
the answer. Neither touches a trading decision.

- **M47** — `resting_stops` asked `status=open`, which excludes a filled parent
  and takes its still-`held` stop legs with it. Four bracketed positions read as
  unprotected on 4 August, 412 duplicate OCOs were refused, and the aggregate
  risk-at-stop cap sat at 33.66% against a 5% limit all session, so no new entry
  could have been approved. Now bounded **by symbol** — dates age, symbols do
  not — and each leg is filtered on its own status.
- **M48** — `recent_fills` asked for `after=since` with a five-minute cursor.
  `after=` filters on `submitted_at`, and no protective order is ever five
  minutes old. Measured structurally: **0 of 10** resting legs were reachable by
  the old query shape, 10 of 10 by the new. On the first stop-out that loses the
  closed trade *and* trips the kill-switch.

## The open task — nothing is mid-flight

Nothing is half-done. The next session starts clean. Candidates, in the order I
would take them:

1. **Watch the first session on M48.** The whole point is the first stop-out.
   Look for `BROKER-SIDE FILL absorbed` followed by a closed trade appearing,
   and for `N carries a stop resting at the broker` reading **10**, not 6.
2. **M49 (unwritten): the absorb watermark does not survive a restart.**
   `OMS._last_fill_scan` starts at construction, so a protective fill that
   happens while the app is down is never absorbed. Reconciliation will not trip
   (adoption re-baselines), but the closed trade is lost — the same
   evidence-destroying shape as M48 in a narrower window. Needs the watermark
   persisted.
3. **Test flakiness worth fixing properly.** Windows' clock granularity lets
   `datetime.now(UTC)` return the same value twice, and the absorb watermark is
   exclusive. The two new M48 tests rewind it explicitly; the older
   broker-side-fill tests pass on timing luck. The product behaviour is correct.
4. **M40 — fundamentals absent from the AI advisory context.** Cheapest item in
   ROADMAP.md and not behind the freeze.

## Standing constraints

- **Read anything under `%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell,
  never Bash.** The Bash tool sees a stale view of that path and has produced
  confidently wrong readings four times in this project.
- The operator's terminal is **Windows PowerShell 5.1** — no `&&`, use `;`.
  (PowerShell has no heredoc either; use a `@'...'@` here-string for commit
  messages, with the closing `'@` at column 0.)
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
| `scripts/watch_session.py` | Live session watcher. `--from-start --no-follow` for morning review |

## What not to re-derive

- How Alpaca returns bracket legs, what `limit` counts, and what `after=`
  filters on — all measured, all in ROADMAP.md under *"How Alpaca actually
  represents orders"*.
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

Deployed build is M48; repo is clean at ce568f1 on master, 4 commits ahead of
origin.

Nothing is mid-flight. M47 and M48 fixed the two query-shape defects that made
protection invisible and would have swallowed the first stop-out. The next
thing that matters is watching a session run on M48 — the first closed trade is
the evidence the whole trial exists to collect.

Constraints: read %LOCALAPPDATA%\QuantAdvisoryTerminal via PowerShell only,
never Bash. The operator's terminal is PowerShell 5.1, so use ; not && and a
@'...'@ here-string rather than a heredoc. Plan and get approval before
implementing; build and sign freely but always ask before deploying over
C:\QuantAdvisoryTerminal. The validation-phase freeze permits defect fixes, not
changes to which trades happen.

Start by reviewing last night's log for whether the M48 path actually fired.
```
