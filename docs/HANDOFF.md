# Handoff — 21 August 2026, after the first widened ASX session

The previous version is `docs/archive/HANDOFF-2026-08-20-superseded.md`. It was
1,455 lines, most of it dated debriefs whose history had become actively
misleading. Nothing was deleted; it was archived and this was written fresh.
**Keep this file short.** It went stale by growing.

---

## ⚙️ Before quoting any figure in here, run this

```powershell
& "C:\Claude Programming\scripts\session_check.ps1"     # NO ARGUMENTS, EVER
.\.venv\Scripts\python.exe scripts\handoff_state.py
```

Everything below was true at the close on 21 August. Assume nothing still is.

---

## ⚠️ THE ONE RULE THAT HAS COST THE MOST TIME

**Anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` runs through
PowerShell, never Bash.** The Bash sandbox serves a frozen snapshot and does NOT
error — including venv python launched from Bash.

It covers scripts that never NAME that directory, because **`Settings()`
silently loads `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env`** (see
`config.env_path`). On 20 August a harness that looked like it only called a
vendor API built `Settings()` under Bash, got the July config — US market,
broker alpaca — resolved an ALPACA history source, asked it for ASX symbols, and
produced four hours of imaginary rate limit. M118 made that message name its
source.

**Any script that builds `Settings()` runs under PowerShell**, or passes
`_env_file=None` and sets what it needs explicitly.

---

## Where this stands

| | |
|---|---|
| Deployed build | **M120 (`14dc257`)**, running since 12:10:52 |
| Repository HEAD | **M128 (`ae364a3`)** |
| Deploy gap | **M122–M128 are NOT deployed** |
| Pushed | **Nothing since `14dc257`** — Actions minutes exhausted until September |
| Suite | 2,505 passed, 25 skipped |
| Watchlist | **94 ASX megacaps + STW.AX**, widened 12:09 |
| Entry allow list | **CLEARED** — all 94 enterable |
| Account | FLAT, equity 1,003,953.07. No entry has ever been placed by the app on IBKR |

### The session, as it finished

Stood down cleanly at 16:00:19; daily and weekly reports written at 16:02. **No
trades, no signals, no sizing decisions.** Equity +$109.93 (+0.01%) with cash
unchanged — mark/FX drift, not trading.

31 of 94 symbols were armed all afternoon and **none crossed**. At the close the
nearest were A2M +0.29%, NHF +0.48%, ANZ +0.59%. The market declined to
cooperate; nothing was wrong.

The only ERRORs were an IBKR 1100/1102 blip at 14:17 that self-healed in 29
seconds, with equity sampling running straight through it. **The 1102 is the
RECOVERY, logged at ERROR** — judge by content, never by count.

---

## ⚠️ WHAT MONDAY'S OPEN ACTUALLY TESTS

**M119 has never been exercised.** Zero empty polls in 3h48m. Its entire purpose
is surviving the open, and today's session started at 12:10 — *after* the delay
window that killed the 10:00 one. **Monday 10:00 is its first real test.**

What happened at the 10:00 open: Yahoo publishes ASX intraday ~20 minutes late,
so all five 60s polls from the bell returned empty, the source hit
`max_consecutive_failures` and **ended the stream permanently**. Nothing
restarts an ended stream. Nothing halted either — MARKET DATA DOWN is
deliberately not a kill-switch trigger, and per-symbol staleness skips symbols
that have never ticked. The account sat flat and blind on an open market until
it was restarted by hand at 12:10.

---

## OUTSTANDING, IN ORDER

1. **Run the era migration, then deploy M122–M128, before Monday's open.**
   `scripts\migrate_ledger_eras.py` — dry run first, `--apply` second, **with the
   app closed** (it refuses while the process is up). Dry run as at 21 August:
   `equity_curve.csv` 14,473→US / 876→ASX; `risk_decisions.csv` 4,876→US / 0→ASX;
   `closed_trades.csv` 2→US/USD. Then **decide the MNST row by hand**: entry
   91.1838, exit 45.9975, no strategy, no stop — an unadjusted split recorded as
   a stop-out, not a −375 loss. The script reports it and deliberately will not
   rewrite it.
2. **Blocked on a first fill, all of it:** Task 2 (`recent_fills` on IBKR), M71
   (built, never exercised — an app-transmitted sell has never happened), and Q4
   (how far back IBKR executions go). M123 removed one reason it could not
   happen; nothing proves it was the only one.
3. **Stage 3 ASX trading rules — the rest of them.** M123 did tick sizes. Still
   unimplemented: the $500 minimum marketable parcel (unlikely to bind at $1M
   equity, but absent), T+2, and the auctions against session logic written for
   a 13:30 UTC open.
4. **The $2,087.83 that is not cash.** Equity minus cash is a steady 2,087.83
   that the app reports as 0.2% exposure while the OMS holds no positions. Small,
   unexplained, and somebody will eventually mistake it for a position.
5. **`invoke build` does not build.** It is `@task(pre=[lint, test])` with a
   `pass` body — lint and tests only, no packaging. It returns 0 with a green
   suite while `dist/` keeps yesterday's exe. Packaging is `invoke package`, then
   `invoke sign`. Same family as the `invoke build | tail` trap.
6. **How much news actually clears the two-source rule at 94 symbols?** M126
   turned Yahoo on, but the only measurement is six ASX names yielding two
   corroborated stories. If 94 names yield four, the feature is honest and nearly
   empty — worth knowing before it informs anything.
7. **Stage 4 regime re-sourcing** — do not start until the ablation question is
   settled. If the regime gate does not earn its keep, this stage disappears.

**Closed 21 August:** the ASX breadth feature (M112, verified live at 94 breadth
symbols); the Stage 2 data decision (news → Yahoo by operator decision, bars →
yfinance, measured at 95/95 symbols with zero empty polls across a full
session); the Force-Start confirmation (M124); the broker connect retry and the
port pre-flight (M125); the AI advisor's news and results date (M126); the
Alpaca-era records, now covering all three ledgers (M122, M127).

---

## What shipped today, and what each one changes

* **M119** — the yfinance feed retries with capped backoff instead of ending the
  stream. *Deployed. Never exercised.*
* **M120** — the trading day is keyed on the exchange, not UTC, in the three
  rails M111 missed. One of them, the earnings blackout, is a **position-size**
  input. Measured: no change before 5 October, when AEDT puts the first hour of
  every session on the previous UTC date. *Deployed.*
* **M122** — the trade ledger carries a market and a currency, and
  `EdgeEstimator` is pinned to `settings.market`. An Alpaca US loss can no
  longer become a twentieth of the win rate that sets position size.
* **M123** — order prices are rounded onto exchange increments. **Buys round
  down, sells round up** — conservative on cost and on protection at once. IBKR
  rejects off-tick prices (error 110), and an ATR stop on a $1.91 stock lands
  off the ASX half-cent grid.
* **M124 / M125** — Force-Start asks first and **defaults to no**; `connect()`
  retries a refused port for about a minute; the pre-flight probes the **port**,
  not the process, and names which of the four it found.
* **M126** — Yahoo news is on by default, the Workbench gets the same inputs as
  the Advisor, and **the stories handed to the model are shown on screen**.
* **M127** — the equity curve and the refusal log have eras. `points()` returns
  the current account only. This is what stops a 9.9x broker migration reading
  as an 896% return, which is what the weekly report published on 21 August.
* **M128** — ticks carry the **bar's** timestamp, and staleness is measured
  **beyond** the feed's 1,200s structural delay. ⚠️ **Risk-rail change:** a print
  is stale at 900s of age *past* the vendor's lag. Stamping bar time alone would
  have excluded every symbol and traded nothing, silently.

---

## Standing constraints

* **PowerShell for `%LOCALAPPDATA%`** — see the top of this file.
* **Do not push until September.** Actions minutes are spent, so **the local
  suite is the only gate**: run it in full and read the actual summary line,
  never a piped tail.
* **Formats with `black`, not `ruff format`.** They agree on nearly everything
  and diverged on exactly one file on 21 August. `black --check .` before
  committing. `invoke lint` shells out to a `ruff` that is not on PATH — run the
  four through the venv python: `ruff check .`, `black --check .`, `mypy src`,
  `bandit -r src`.
* **`scripts\session_check.ps1` takes NO ARGUMENTS.** Permissions are stored as
  exact command strings, so a varying command can never be allowlisted. Widen
  what the script REPORTS, never what the caller passes.
* **It checks the PROCESS first, and that matters.** On 20 August the log went
  silent because the app had EXITED, which reads identically to an idle feed.
  **A quiet log is not a healthy app.**
* Operator's terminal is PowerShell 5.1 — `;` not `&&`, `@'...'@` here-strings
  with the closing `'@` at column 0.
* **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets
  `QAT_DATA_DIR` session-wide and the anomaly store persists there, so one
  declared anomaly leaks a quarantine into every later test.
* **Never deploy mid-session** without a reason, and **always ask before
  unzipping over `C:\QuantAdvisoryTerminal`.** 21 August was a deliberate
  exception: the book was FLAT with nothing in flight, which is the cheapest
  possible moment to restart.
* A defect that corrupts the record is still fix-immediately.

---

## The habits that found everything

**Derive, do not remember.** Four counts were asserted and wrong in three days;
the derived ones stopped being wrong. On 21 August the guard test added in M120
caught its own author, and the manual-coverage guard caught an undocumented
setting an hour later.

**Test the claim, not the arithmetic.** Every defect found on 11 August was in a
sentence that predicted or explained, never in a number.

**Ask what reads it.** M126 found news being fetched, corroborated, and handed to
a model with nowhere for the operator to see it.

**Verify the artefact, not the exit code.** `invoke build` returns 0 having built
nothing. A green suite is not a build, and a build is not a deploy.

**Check whether the fix has a sibling.** M119, M120 and M122 were each one
implementation being right and its twin being wrong — the Alpaca source retried
and yfinance did not; `trading_date` had one caller out of four; `closed_trades`
was scoped by strategy but not by market. When something is fixed, ask what else
shares its shape.

---

## 📋 PROMPT TO PASTE — next session

```
Continuing QAT (Quant Advisory Terminal) at C:\Claude Programming.
Paper account throughout - no real money.

Read the state first, and trust it over anything in this prompt:

    & "C:\Claude Programming\scripts\session_check.ps1"     (NO ARGUMENTS, EVER)
    .\.venv\Scripts\python.exe scripts\handoff_state.py

Then read docs\HANDOFF.md. It is short now, and current as at the 21 August
close.

⚠️ PowerShell for anything touching %LOCALAPPDATA%\QuantAdvisoryTerminal,
including Python that only reads it, and including anything that builds
Settings() - which loads that directory's .env whether or not the script
mentions it. The Bash sandbox serves a frozen July snapshot and does NOT error.

⚠️ DO NOT PUSH. GitHub Actions minutes are exhausted until September, so the
local suite is the only gate. Run it in full and read the summary line, never a
piped tail. Format with black, lint with ruff.

THE STATE, as at the 21 August close:

  Deployed M120 (14dc257). HEAD is M128 (ae364a3). SEVEN COMMITS UNDEPLOYED.
  Account FLAT. No entry has ever been placed by the app on IBKR.
  Watchlist widened to 94 ASX megacaps + STW.AX; entry allow list CLEARED.

THE FIRST TWO THINGS, IN ORDER, BEFORE MONDAY'S 10:00 OPEN:

  1. Run scripts\migrate_ledger_eras.py - dry run, then --apply, WITH THE APP
     CLOSED. Then decide the MNST row by hand: it is a split recorded as a
     stop-out, not a loss, and the script will not rewrite it for you.
  2. Deploy M122-M128. M119 - the fix that stops the feed dying at the open -
     IS deployed but has NEVER been exercised, because Friday's session started
     at 12:10, after the delay window that killed the 10:00 one. Monday's open
     is its first real test.

M128 CHANGED A RISK RAIL. Ticks now carry the bar's own timestamp, and
staleness is measured BEYOND the feed's 1,200s structural delay. If you touch
either number, understand both: stamping bar time without the delay allowance
excludes every symbol and trades nothing, silently, while reporting a healthy
feed.

Anything not deployed is not protecting anything. Check the stamp on the
RUNNING build, never the repository.
```
