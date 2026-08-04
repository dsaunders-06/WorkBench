# Handoff — 5 August 2026

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

---

## Where things stand

- **Deployed:** M46 (`53390a1`). Repo is at `d5fd1f9`, clean, pushed, one
  branch (`master`).
- **Account:** Alpaca paper, ten positions — CRWD 16, CSCO 44, CVS 47, JNJ 19,
  UNP 17, WFC 58 (standalone OCOs) and AMAT 7, AMD 7, GS 7, MS 82 (brackets
  from tonight's entries). **All ten are protected.**
- **MS is deliberately noted:** 82 shares against an intended 41, from the
  duplicate-entry defect fixed in M46. The position is protected by two
  brackets. Whether to trim it back is the operator's call, not a defect to fix.
- **Closed trades: still zero.** That is the number that matters.

## The open task

`resting_stops()` cannot see a protective leg whose parent entry has filled.
Tonight that made four protected positions read as unprotected, and the app
proposed four duplicate OCOs which Alpaca refused for insufficient shares.

The measured behaviour is in ROADMAP.md under *"How Alpaca actually represents
orders"* — read that first, it was proven against the live account and should
not be re-derived.

**The fix is `status=all` with `nested=true`, filtering legs on their own
status.** The part needing care is the cost: that query returned 220 rows
against 11, and grows without bound, so it cannot be fetched on every
five-minute reconciliation poll. It needs a date bound — and choosing that
bound badly reintroduces the same bug in a new form, because a leg belonging to
an older entry would go invisible again.

That bounding question is the whole of the remaining work. It was deliberately
not started at the end of a context window.

## Standing constraints

- **Read anything under `%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell,
  never Bash.** The Bash tool sees a stale view of that path and has produced
  confidently wrong readings four times in this project.
- The operator's terminal is **Windows PowerShell 5.1** — no `&&`, use `;`.
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
| `docs/UI_UX_APPROACH.md` | UI/UX plan. Steps 1–2 (design system, expertise levels) are done and committed as M45 but **not built or deployed**. Screen work waits for closed trades |
| `docs/PRODUCT_DESCRIPTION.md` | Current capability, written for evaluation, limitations given equal weight |
| `scripts/watch_session.py` | Live session watcher. `--from-start --no-follow` for morning review |

## What not to re-derive

- How Alpaca returns bracket legs — measured, in ROADMAP.md.
- Why swing rarely exits — 29 entries, zero signal exits over 1.19 years.
- Why the walk-forward numbers are weak — the windows manufacture an entry at
  each slice boundary.
- That the AI advisory context carries no fundamentals — that is M40.

---

## Prompt to paste

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
Read docs/HANDOFF.md first, then the section of ROADMAP.md titled "How Alpaca
actually represents orders" and the standing rule at the top of that file.

Deployed build is M46; repo is clean at d5fd1f9 on master.

The task: resting_stops() cannot see a protective leg whose parent entry has
filled, so bracketed positions read as unprotected once their entry fills. The
behaviour is already measured — do not re-derive it. The fix is status=all with
nested=true filtering legs on their own status; the real work is bounding that
query by date, because it returns 220 rows against 11 and grows without bound,
and a bound that is too tight reintroduces the same invisibility for older
entries.

Constraints: read %LOCALAPPDATA%\QuantAdvisoryTerminal via PowerShell only,
never Bash. The operator's terminal is PowerShell 5.1, so use ; not &&. Plan
and get approval before implementing; build and sign freely but always ask
before deploying over C:\QuantAdvisoryTerminal. The validation-phase freeze
permits defect fixes, not changes to which trades happen.

Start by proposing the approach to bounding the query.
```
