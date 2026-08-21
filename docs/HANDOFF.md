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
| Deployed build | **M130 (`f5b9bd2`)**, running since 17:59:58 |
| Deploy gap | **M133 only.** Everything else committed after `f5b9bd2` is docs and data. M133 changes the exposure metric and needs a build to take effect |
| Pushed | **Nothing since `14dc257`** — Actions minutes exhausted until September |
| Suite | 2,517 passed, 25 skipped. ruff and black both clean |
| Watchlist | **94 ASX megacaps + STW.AX** |
| Entry allow list | **CLEARED** — all 94 enterable |
| Account | FLAT, equity 1,003,953.07. No entry has ever been placed by the app on IBKR |
| Ledgers | **EMPTY.** The Alpaca era was retired to `docs/archive/alpaca-era/` on 21 August: 0 closed trades, 0 risk decisions, 920 equity samples (ASX only), 6 journal rows |

### The session, as it finished

Stood down cleanly at 16:00:19; daily and weekly reports written at 16:02. **No
trades, no signals, no sizing decisions.** Equity +$109.93 (+0.01%) with cash
unchanged — **accrued interest**, queried from the account rather than guessed
at. An earlier note here called it FX drift; the account is single-currency AUD,
so there is no FX to drift.

31 of 94 symbols were armed all afternoon and **none crossed**. At the close the
nearest were A2M +0.29%, NHF +0.48%, ANZ +0.59%. The market declined to
cooperate; nothing was wrong.

The only ERRORs were an IBKR 1100/1102 blip at 14:17 that self-healed in 29
seconds, with equity sampling running straight through it. **The 1102 is the
RECOVERY, logged at ERROR** — judge by content, never by count.

---

## ⚠️ WHAT MONDAY'S OPEN ACTUALLY TESTS

**M119 has never been exercised.** It is deployed — it has been since 12:10 and
is in the M130 build — but zero empty polls in 3h48m means nothing has tested
it. Its entire purpose is surviving the open, and Friday's session started at
12:10, *after* the delay window that killed the 10:00 one. **Monday 10:00 is its
first real test.**

What happened at the 10:00 open: Yahoo publishes ASX intraday ~20 minutes late,
so all five 60s polls from the bell returned empty, the source hit
`max_consecutive_failures` and **ended the stream permanently**. Nothing
restarts an ended stream. Nothing halted either — MARKET DATA DOWN is
deliberately not a kill-switch trigger, and per-symbol staleness skips symbols
that have never ticked. The account sat flat and blind on an open market until
it was restarted by hand at 12:10.

### An entry can only happen in 57% of the session

Computed from the calendar, not assumed. The autonomy gate permits Morning
Trend, Afternoon and Closing Session, and excludes the other two:

| | | |
|---|---|---|
| 10:00–10:28 | Opening Volatility | **blocked** |
| **10:29–11:58** | Morning Trend | **entries** |
| 11:59–14:04 | Midday Lull | **blocked** |
| **14:05–15:16** | Afternoon | **entries** |
| **15:17–16:00** | Closing Session | **entries** |

206 of 361 minutes. Subtract the feed's ~20-minute delay and **the last usable
moment is about 15:40**, because a move after that never reaches the strategy
before the stand-down. So a fill needs a trigger inside roughly **10:29–11:58 or
14:05–15:40**. A quiet morning does not mean a quiet day, and a crossing at
12:30 does nothing at all.

---

## OUTSTANDING, IN ORDER

**One list.** It used to be two: this file's, and section 4 of
`docs/LIVE_TRADING_READINESS.md` ("what is not built, and only matters with real
money"). Two lists is how M39, M41, M43 and M44 went unmentioned in a review of
outstanding work on 21 August. The readiness document still holds the REASONING
for each gap and is worth reading; the list lives here.

### Blocking the experiment

1. **The first fill, and everything behind it:** `recent_fills` on IBKR, M71
   (built, never exercised — an app-transmitted sell has never happened), and how
   far back IBKR executions go. M123 removed one reason it could not happen;
   nothing proves it was the only one. The ledger is now EMPTY, so the first fill
   will be row one.
2. **M119 is deployed but unexercised.** Friday's session started at 12:10, after
   the delay window that killed the 10:00 one. Monday's open is its first real
   test and the highest-value thing to watch.
3. **Reach 20 closed trades**, then 30. Below 20 the sizer uses invented
   constants; below 30 the promotion gate cannot be read at all. Every question
   below this line is partly speculative until then.

### Turns an ordinary market event into a loss

4. **M39 — corporate actions.** The readiness document calls this *the
   highest-severity gap*. The machinery exists (`domain/corporate_actions/`, plus
   M60's quarantine) but **IBKR serves no announcements**, so it has no input and
   a split cannot be seen before its ex-date. One ordinary 2-for-1 produces four
   failures from a non-event: the kill-switch trips on the doubled share count,
   the resting stop sits at roughly twice the new price, the re-arm restores
   protection at a level that liquidates the position, and the trade's P&L is
   wrong by the split factor. Ten positions held for a quarter makes it a
   question of when. **The MNST row retired on 21 August is what this looks like
   when it happens.**
5. **M43 — trading halts.** No detection anywhere. The staleness rail covers
   entry and says nothing about the case that hurts: position held, symbol
   halted, stop cannot fill, reopens materially lower.
6. **M41 — earnings event risk.** M120 fixed the DATE the blackout is computed
   against; the risk itself is untouched. With a 10-day minimum hold and a 30-day
   time stop, holding through an announcement is unavoidable — roughly quarterly
   per position. The 6% gap budget was measured across 28,987 ORDINARY nights;
   earnings gaps run 15–20% and a stop does not help, because the price never
   trades there. Widening to 94 symbols multiplies the exposure.
7. **M44 — execution quality.** Every order is a market order and slippage is
   modelled at a flat 5bps regardless of size, time of day or spread. The one
   real data point is not encouraging: the CVS stop gapped through and cost
   **1.68R, not the 1R the sizing assumes**. If that is typical, every position
   is sized against an understated downside. The instrument exists —
   `diagnostics.py` reads `entry_slippage` — and what is missing is trade count.
   ⚠️ Its analysis script now reads the ARCHIVE, because the 21 August retirement
   moved the journal rows out of the live directory; its other input was a live
   Alpaca API call that will not be made again.

### Correctness and hygiene

8. ~~**The exposure metric counts accrued interest as exposure.**~~ **DONE — M133.**
   `metrics.py:_exposure_ratios` computes `(equity - cash) / equity`. With no
   positions at all the daily report prints "Avg exposure 0.2%, Peak exposure
   0.2%", and every cent of that is `AccruedCash`. `GrossPositionValue` is the
   figure that means market exposure and reads 0.00. Minor, but it will overstate
   exposure by the accrued amount once positions exist.
   > **M132 IS RETRACTED — the risk model is NOT in the wrong currency.**
   > Queried the live account 21 August: **the base currency is AUD**, not USD.
   > Every account tag reports AUD, and `$LEDGER-TotalCashBalance` shows the
   > identical 1,001,865.24 for both `AUD` and `BASE` — if BASE were USD it
   > would be a converted, different number. So `risk_budget` (AUD) divided by
   > `stop_distance` (AUD) is dimensionally correct, there is no 28% undersize,
   > and `max_order_notional = 50_000` is AUD matching AUD prices.
   >
   > The claim was built on the IBKR-move plan's line *"Paper accounts start
   > with USD 1,000,000"* plus a round million, and never checked against the
   > broker. Reading a document instead of querying the account, inside an audit
   > whose purpose was checking claims against reality.
   >
   > What survives is smaller: `from_ib_account_values` still ignores
   > `value.currency` and lets the last matching row win. Harmless while the
   > account is single-currency AUD — which it is — and worth fixing before it
   > ever holds a second one.
9. **Stage 3 ASX rules — the rest.** Tick sizes are done (M123). Still absent:
   the $500 minimum marketable parcel (unlikely to bind at ~1M AUD equity), T+2,
   and the auctions against session logic written for a 13:30 UTC open.
10. **The liquidity filter does not filter.** `average_daily_volume` is a
    deterministic RNG seeded on the ticker — a synthetic number between 10,000
    and 20,000,000, not real volume — so `QAT_WATCHLIST_MIN_AVG_VOLUME` screens
    on noise. Harmless across 94 megacaps that are liquid by construction;
    actively misleading if the universe widens beyond them.
11. **News yield at 94 symbols.** Live in the deployed build, so measurable on
    Monday. The only measurement is six ASX names yielding two corroborated
    stories; if 94 yield four, the feature is honest and nearly empty.
12. **`invoke build` does not build.** `@task(pre=[lint, test])` with a `pass`
    body — returns 0 with a green suite while `dist/` keeps yesterday's exe.
    Packaging is `invoke package`, then `invoke sign`.
13. **Retire the Alpaca CODE paths?** Open question. The adapter and market-data
    source are still in the tree and still tested, and `alpaca_source.py` is the
    reference implementation M119's retry came from. The 21 August decision was
    about DATA.
14. **`migrate_ledger_eras.py` is superseded** by `retire_alpaca_era.py`. Dead
    script; keep or delete deliberately.
15. **Design-system debt in the screens.** `docs/UI_UX_APPROACH.md` records
    Group 4 (every screen restyled) as complete, and it is. What survives,
    RE-MEASURED 21 August: **20 `setStyleSheet` calls across seven files
    hand-write what a `theme` helper returns**, and 8 of those hardcode a pixel
    size, bypassing the type scale. `regime_monitor.py` 6, `balances_panel.py`
    5, `risk_console.py` 3. One colour constant lives outside `theme.py`.
    Raw hex IS solved — 18 sites, all inside `theme.py`, guarded by a passing
    test — so that document's "25 raw-hex sites" note is stale and now says so.
    The guard catches hex and cannot catch a primitive written longhand.
    Nothing is wrong on screen; this is debt, not a defect.
16. **Stage 4 regime re-sourcing** — do not start until the ablation question is
    settled. If the regime gate does not earn its keep, this stage disappears.

### Audited 21 August and found SOUND — do not re-audit without a reason

The first-fill path was walked end to end looking for another M123. Nothing
found that blocks a fill. Recorded so the next person does not repeat it:

* **whole-share quantities** — floored, refused below one (M31a);
* **the `.AX` contract** — M96, measured against the live Gateway;
* **bracket `parentId` linkage** — the adapter builds legs from `parent.orderId`
  straight after `placeOrder`; verified in the INSTALLED ib_async that line 790
  assigns a local and line 806 writes it back, so the linkage holds. Had it not,
  every leg would have carried `parentId=0` and the protection would have been
  standalone orders;
* **bracket structure** — `is_bracket` guarantees at least one leg, so a parent
  cannot be left untransmitted;
* **fill identity and symbol form** — `permId`, and `from_ibkr` on the way back;
* **execution timestamps** — timezone-aware on both parse branches. One residual:
  if IBKR sends an unqualified time AND `TimezoneTWS` is empty, Python assumes
  the LOCAL machine zone. Server 178 sends zone-qualified times, so unlikely,
  but it would shift fill times silently;
* **the absorb path** — M48/M53/M70 defended, and a `recent_fills` failure
  degrades to "nothing absorbed" while still logging at ERROR;
* **position symbol form (M104)** — the sharpest of them. A tracked `BHP.AX`
  against a broker `BHP` produces two divergences rather than a match, and a
  reconciliation mismatch TRIPS THE KILL SWITCH. All four IBKR boundaries now
  translate.

**Closed 21 August:** the $2,087.83 that was not cash — it is `AccruedCash`,
accrued interest, queried from the live account rather than guessed at; the ASX breadth feature (M112, verified live at 94 breadth
symbols); the Stage 2 data decision (news → Yahoo by operator decision, bars →
yfinance, measured at 95/95 with zero empty polls across a full session); tick
sizes (M123); the Force-Start confirmation (M124); the broker connect retry and
port pre-flight (M125); the AI advisor's news and results date (M126); the era
boundaries (M122, M127); the tick-timestamp and staleness pair (M128, M130); the
handoff rewrite (M129); the M130 deploy; and the Alpaca-era data, now retired
from the app entirely to `docs/archive/alpaca-era/` — which dissolved the MNST
question rather than answering it.

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
* **M130** — the feed watches its own lag and says so when the vendor stops
  matching the configured 1,200s. It **never** adjusts the threshold: a rail
  that widened its own tolerance as a feed degraded would hide the degradation.

### ⚠️ Expect the first ASX staleness exclusion, and do not read it as a fault

The staleness rail has **never fired on ASX** — 1,589 exclusions between 31 July
and 18 August on the US/Alpaca feed, then 9 on the 19th and **zero** across both
full ASX sessions. That was not calm; it was `ts=now` making price age
unmeasurable, so the rail could only ever see a feed that had gone silent.

Once M128 is deployed, ASX exclusions become possible for the first time. **The
first one is the rail working**, not a regression — and it will be the first
honest reading of ASX price age this system has produced.

Two things that make the old record readable: the US exclusions were genuine
(1,440 of 1,598 were on prints an hour or more old, averaging ~20 hours), so
nothing in the US trial is contaminated by this. And the 499-session ASX replay
harness has **no coverage of this rail at all** — `replay_session.py` publishes
`MarketDataEvent` straight onto the bus and never constructs a `MarketDataFeed`,
so it neither confirms nor contradicts any of it.

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
