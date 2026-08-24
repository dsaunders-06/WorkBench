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
| Deployed build | **M134 (`2d7777c`)**, installed 21 August 20:05 and read back off its own log |
| Repository HEAD | Past M134 — evening work of 21 August is **M135**, uncommitted to any build |
| Deploy gap | **M135.** UI, news and design-system only; **no trading-decision input changed**. Not urgent, and see the warning below about deploying before Monday |
| Pushed | **Up to date as of 24 August.** 43 commits pushed at 13:07 and CI went **green** in 3m57s. The "Actions minutes exhausted until September" rule was TESTED and is false — see the standing constraints |
| Suite | **2,528 passed, 25 skipped.** ruff, black and mypy clean |
| Watchlist | **94 ASX megacaps + STW.AX** |
| Entry allow list | **CLEARED** — all 94 enterable |
| Account | FLAT, equity 1,003,953.07 **AUD**. No entry has ever been placed by the app on IBKR |
| Ledgers | **EMPTY.** The Alpaca era was retired to `docs/archive/alpaca-era/`: 0 closed trades, 0 risk decisions, equity samples ASX-only, 6 journal rows |

> ✅ **The `-dirty` exe is gone.** It was replaced at 20:02 by a build from the
> clean tree, stamped `M134 (2d7777c, built 21/08/2026 10:00 UTC)` with no
> `-dirty` marker, signed and timestamp-verified, and installed at 20:05. The
> installed exe is **SHA256-identical** to the signed one in `dist\`
> (`9C63B69D…306C`). Rollback artefact `QuantAdvisoryTerminal-M130-f5b9bd2.zip`
> is still in `dist/`.
>
> ✅ **Read back off its own log at 20:10**, on a run that connected to the
> broker: `Build: M134 (2d7777c, built 21/08/2026 10:00 UTC, packaged)`. Launched
> 20:09:43, stood down 20:10:51 with the account FLAT and nothing to adopt, zero
> ERROR/CRITICAL, three equity samples written. The deployed build is an
> observation, not an intention.

### ⚠️ Do not deploy M135 before Monday's open

Nothing in M135 touches a trading-decision input — it is news scope, three
screens and the design system. But M119's first real test is Monday 10:00, and
it is more informative read against the build that is actually installed than
against one that changed five files the night before. Deploy after the open, or
once the feed has been watched through it.

The app currently installed is M134 and **tonight's work is not in it.** To look
at any of it, run from source with `invoke run`.

### The account is AUD-base. Verified, not assumed.

Every IBKR tag reports **AUD**, and `$LEDGER-TotalCashBalance` returns the
identical 1,001,865.24 for both `AUD` and `BASE` — if BASE were USD it would be
a converted figure. Single currency, no FX exposure anywhere. The equity-minus-
cash gap of **2,087.83 is `AccruedCash`**, accrued interest.

`docs/superpowers/plans/2026-08-19-ibkr-move.md` says *"Paper accounts start
with USD 1,000,000"* and now carries a correction at that sentence, because on
21 August it was taken as given and produced a confident, wrong finding that the
risk model divided USD by AUD and undersized every position by 28%. **The
account's own tags are the authority on its currency, not a plan document.**

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
is in the M134 build now installed — but zero empty polls in 3h48m means nothing
has tested it. Its entire purpose is surviving the open, and Friday's session started at
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
9. **Stage 3 ASX rules — DESIGNED AND PLANNED, execution parked to Sunday
   23 August by operator choice.** Spec
   `docs/superpowers/specs/2026-08-21-asx-auctions-design.md`, plan
   `docs/superpowers/plans/2026-08-21-asx-auctions.md` (5 tasks, bottom-up).
   **Scope was narrowed:** the minimum marketable parcel and T+2 were dropped
   as live-only concerns with no bite in a paper account. One residual is
   recorded rather than lost — if IBKR paper fills a sub-$500 order the live
   exchange would refuse, the paper record is optimistic by exactly the trades
   that could not have happened.
   The measurement behind it is committed and should not be re-derived:
   `scripts/asx_session_probe.py` asked the live Gateway and settled the design
   by evidence. **IBKR does not report a staggered ASX open** — fourteen
   contracts from A2M to XRO returned identical hours — so a per-symbol group
   model is not buildable. **The closing auction is derivable**: tradingHours
   1611 against liquidHours 1600. And the app already disagrees with the broker
   about the open, 10:00 against 0959.
   Original text: tick sizes are done (M123). Still absent:
   the $500 minimum marketable parcel (unlikely to bind at ~1M AUD equity), T+2,
   and the auctions against session logic written for a 13:30 UTC open.
10. ~~**The liquidity filter does not filter.**~~ **DONE — M134.** Renamed to
    `synthetic_average_daily_volume`, `resolve_watchlist` warns when it drops
    anything, and the Screener — which DISPLAYS it — now says at the call site
    that the number is derived from the ticker string. Left in place rather
    than removed: deleting it would silently widen the universe.
    Original: `average_daily_volume` is a
    deterministic RNG seeded on the ticker — a synthetic number between 10,000
    and 20,000,000, not real volume — so `QAT_WATCHLIST_MIN_AVG_VOLUME` screens
    on noise. Harmless across 94 megacaps that are liquid by construction;
    actively misleading if the universe widens beyond them.
11. ~~**News yield at 94 symbols.**~~ **DONE — M135.** News was never gated per symbol; `news_source` defaults to `yfinance` and the picker carries the whole watchlist. What suppressed it was the two-source rule, now `QAT_NEWS_MIN_SOURCES` defaulting to **1**. What that costs is written at the setting: a single planted story can reach the model. Original: Live in the deployed build, so measurable on
    Monday. The only measurement is six ASX names yielding two corroborated
    stories; if 94 yield four, the feature is honest and nearly empty.
12. ~~**`invoke build` does not build.**~~ **DONE — M134.** It is now
    `pre=[lint, test, package]`, verifies the exe exists afterwards, and
    prints its path, size and timestamp. `lint`, `test` and `format` now run
    every tool as `<this interpreter> -m <tool>` — they shelled out to bare
    names that are not on PATH, which is why it died on `'ruff' is not
    recognized`. Original: `@task(pre=[lint, test])` with a `pass`
    body — returns 0 with a green suite while `dist/` keeps yesterday's exe.
    Packaging is `invoke package`, then `invoke sign`.
13. **Retire the Alpaca CODE paths?** Open question. The adapter and market-data
    source are still in the tree and still tested, and `alpaca_source.py` is the
    reference implementation M119's retry came from. The 21 August decision was
    about DATA.
14. ~~**`migrate_ledger_eras.py` is superseded.**~~ **RESOLVED — kept, marked.**
    Its docstring now opens with SUPERSEDED and points at
    `retire_alpaca_era.py`. Kept rather than deleted because it records an
    approach that was correct for a day and its `--cutover` reasoning is what
    the retirement script inherited. Do not run it.
15. ~~**Design-system debt in the screens.**~~ **DONE — M135**, and the counts below were understated: 28 hand-written stylesheet arguments, not 20, and 11 longhand pixel sizes, not 8. `theme.text` now takes an optional colour — the reason they existed — and `theme.panel()` owns the bordered card. ⚠️ **The colour guard was passing while blind**: PEP 701 made f-string text arrive as `FSTRING_MIDDLE`, the scan filtered on `STRING`, and it was hiding a live `color: white` in `dashboard.py`. Original: `docs/UI_UX_APPROACH.md` records
    Group 4 (every screen restyled) as complete, and it is. What survives,
    RE-MEASURED 21 August: **20 `setStyleSheet` calls across seven files
    hand-write what a `theme` helper returns**, and 8 of those hardcode a pixel
    size, bypassing the type scale. `regime_monitor.py` 6, `balances_panel.py`
    5, `risk_console.py` 3. One colour constant lives outside `theme.py`.
    Raw hex IS solved — 18 sites, all inside `theme.py`, guarded by a passing
    test — so that document's "25 raw-hex sites" note is stale and now says so.
    The guard catches hex and cannot catch a primitive written longhand.
    Nothing is wrong on screen; this is debt, not a defect.
16. ~~**One symbol, one recommendation.**~~ **BUILT — M136**, spec
    `docs/superpowers/specs/2026-08-22-symbol-verdict-design.md`, plan
    `docs/superpowers/plans/2026-08-22-symbol-verdict.md`, five tasks all
    reviewed clean. **NO trading-decision input changed** — it reads the rails
    and alters none.
    ⚠️ **IT DOES NOT RENDER ON IBKR YET, and that is the remaining work.** The
    verdict declines rather than fabricating a day P&L of 0.0 — a fabricated
    0.0 can never trip the always-negative pause threshold, so it would report
    "permitted" on an invented fact (M73's shape). But **nothing populates
    `AccountBalances.last_equity` on IBKR**: it is an Alpaca field, and
    `_ACCOUNT_TAGS` requests no previous close. Operator chose on 22 August to
    SOURCE the day P&L rather than render a partial verdict.
    **Measured 24 August against the live Gateway, read-only:**
    `PreviousDayEquityWithLoanValue` is **NOT in the default accountSummary tag
    set** (nor is `SettledCash`), and `reqPnL` returned **nan** for dailyPnL,
    unrealizedPnL and realizedPnL after 3s on a flat account. A second probe
    using `accountValues` hung and was killed — possibly client contention. So
    the route is NOT yet established, and the next person should finish that
    measurement before mapping any tag. Do not map one from documentation.
    Two traps already hit while probing, both already documented in this
    codebase: `reqAccountUpdates` is a sync `util.run` wrapper and raises
    "event loop is already running" inside the app's loop (the M102 shape), and
    the default tag set is not the same thing as what IBKR can return.

17. **One symbol, one recommendation — the original entry, kept for its
    reasoning.** The AI Advisor
    forms buy/sell/hold from regime, positions, risk, fundamentals, results date
    and news. The Workbench forms one from backtest stats and the strategy's
    candidate signal — and passes `regime_label="unknown"`, so **it does not know
    the prevailing regime**. Neither sees everything. The ask is one answer over
    both, against the prevailing regime and following the current strategy's
    rules. Needs a design pass first, and **M73's framing has to survive it**:
    this screen is "an analyst, never a trader" and its output reaches no part of
    the trading system. A recommendation that follows the live strategy's rules
    sits closer to that line, not further from it.

18. **The Dashboard's "Review & Apply" button applies nothing.** Its handler is
    one line — `self.review_button.setText("Reviewed ✓")`. Nothing else in
    `src` or `tests` references it. The inertness toward TRADING is deliberate
    and right (spec §K, "Review & Apply, never auto-apply"), but the label
    promises an action, and the acknowledgement is not journalled, not logged
    and not persisted — so it cannot even serve as evidence a human saw a
    regime change before a trade, and it resets on the next `RegimeEvent`.
    Either rename it to what it is, or record the acknowledgement with the
    regime label and a timestamp. Same family as M73's framing that existed
    only in a docstring and M105's connection test that returned a tick
    regardless.

19. **Is the CI-goes-red-before-2200-AEST rule real?** Recorded as fact in this
    file and in a saved memory. On 24 August CI ran at **13:07 AEST and passed**
    — one clean counter-example. Either a time-dependent test was fixed
    somewhere in the 43 pushed commits, or the rule was never as deterministic
    as recorded. Worth one deliberate daytime push to settle rather than
    carrying forward.

20. **Sweep the other guards for the same blindness.** M135 found the colour
    guard reading every f-string as empty since the 3.12 upgrade, hiding a live
    violation while reporting none. Any pattern- or `tokenize`-based guard in
    this codebase written before that upgrade could have narrowed the same way,
    and a narrowed guard is worse than none because its green result is read as
    evidence. Not urgent; genuinely worth doing.

21. **Screens render stored UTC as if it were local time.** Spotted by the
    operator on 24 August: an order created at **13:05:01 AEST** shows on the
    Blotter as **03:05:01**. `Order.created_at` is `datetime.now(UTC)`, which is
    right for storage, and `blotter.py:332` formats it with no conversion —
    `f"{format_display_date(order.created_at)} {order.created_at:%H:%M:%S}"`.

    **Why it bites here specifically.** The Blotter is where a human decides
    whether to sign an order, and that decision turns on how stale it is. 03:05
    is a plausible-looking time rather than an obviously broken one, so it reads
    as a ten-hour-old order rather than a ten-minute-old one. Same family as
    M111/M120, where a UTC date silently stood in for an exchange date.

    It is also **inconsistent with the date beside it**: `format_display_date`
    renders that in Australian convention, so the row pairs a locally-formatted
    date with a UTC time, which implies the time is local too.

    **Swept 24 August — the layer is inconsistent, not uniformly wrong:**

    | Site | State |
    |---|---|
    | `blotter.py:332` (`created_at`) | **WRONG** — UTC, unlabelled |
    | `performance.py:434` (`trade.closed_at`) | **WRONG** — UTC, unlabelled; will misreport the first closed trade |
    | `regime_monitor.py:300` | honest — labelled `UTC` |
    | `risk_console.py:341` | honest — labelled `UTC` |
    | `session_panel.py:135` | correct — `session_for` already returns exchange-local |

    **Fix toward the EXCHANGE timezone** (`market_calendar.MARKET_TIMEZONES`),
    not the machine's local time: everything else in this application keys on
    the exchange, and the box happening to sit in Sydney is not a thing to rely
    on. Nothing currently forces the conversion at any call site, which is why
    two of five drifted — a helper that returns exchange-local formatted time
    would make the right thing the easy thing.

    **Not affected:** the log, journal and audit trail all store UTC with
    explicit offsets (`2026-08-24T03:05:01+00:00`), which is correct and
    unambiguous. This is display only.

22. **Stage 4 regime re-sourcing** — do not start until the ablation question is
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
* ~~**Do not push until September.**~~ **TESTED AND FALSE, 24 August.** 43
  held-back commits were pushed at 13:07 and CI completed **green in 3m57s** on
  `windows-latest`. Run the local suite in full anyway and read the actual
  summary line, never a piped tail.

  ⚠️ **NOT "push freely" — corrected the same afternoon.** The repo is
  **PRIVATE**, so minutes come from a finite monthly allowance, and that
  `windows-latest` runner bills at a **2× multiplier**: the 3m57s run cost about
  **8 minutes**. Every GitHub budget is **$0 with "Stop usage: Yes"**, which is
  a hard wall — **no spend is possible**, and the failure mode is runs being
  BLOCKED rather than a bill. That is almost certainly what "exhausted" meant.

  `ci.yml` fires on every push with no path filter, so a documentation-only
  commit buys a full Windows lint-and-test run — which is what the commit
  correcting this very paragraph did. **Batch commits and push once.** A
  `paths-ignore` for `docs/**` and `*.md` is worth adding, since most commits
  here are prose.

  **The rule was also the wrong SHAPE, which is the part worth keeping.** A
  push costs no Actions minutes — only the workflow it triggers does. So even
  had the minutes genuinely been spent, the push would have succeeded and CI
  would simply not have run. "Do not push" could never have been the right
  instruction; "expect CI not to run" would have been. One push of 43 commits
  is ONE workflow run, not 43.

  Two documented constraints and two saved memories were contradicted by
  running the thing rather than reading about it. They had been copied forward
  from document to document since 21 August without anyone testing them — the
  same failure the account-currency retraction and the UI colour counts were.
  Then the replacement rule was written from a single outcome without checking
  the conditions, and had to be corrected within the hour. Both halves are the
  same error.
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

READ THE STATE FIRST, and trust it over anything in this prompt:

    & "C:\Claude Programming\scripts\session_check.ps1"   (NO ARGUMENTS, EVER)
    .\.venv\Scripts\python.exe scripts\handoff_state.py

Then read docs\HANDOFF.md. It is short and current as at 21 August evening.

⚠️ POWERSHELL for anything touching %LOCALAPPDATA%\QuantAdvisoryTerminal -
including Python that only READS it, and including anything that builds
Settings(), which loads that directory's .env whether or not the script
mentions it. The Bash sandbox serves a frozen July snapshot and does NOT error.

PUSH NORMALLY. The "Actions minutes exhausted until September" rule was tested
on 24 August and is FALSE - 43 commits pushed, CI green in 3m57s. Run the local
suite in full anyway and read the summary line, never a piped tail. Lint with
ruff, format with BLACK (they diverged on one file on 21 August).

⚠️ THE FIRST LAUNCH MUST BE READ BACK. M134 was built clean, signed and
installed at 20:05 on 21 August, but the app has NOT been launched on it. The
first session_check must print `Build: M134 (2d7777c, ..., packaged)`. If it
still says M130, the copy did not take and nothing downstream is trustworthy.

THE STATE

  Deployed M134 (2d7777c), read back off its own log at 20:10 on 21 August.
  HEAD is past it: the evening's work is M135 and is NOT in the installed
  build, so run from source (`invoke run`) to see any of it.
  DO NOT DEPLOY M135 BEFORE THE OPEN - nothing in it touches a trading-decision
  input, and M119's first test is worth reading against the build that has been
  running rather than one changed the night before.
  Account FLAT, ~1,003,953 AUD. NO ENTRY HAS EVER BEEN PLACED BY THE APP ON
  IBKR. Ledgers are EMPTY: the Alpaca era was retired to
  docs/archive/alpaca-era/ on 21 August, so the first fill will be row one.
  Watchlist is 94 ASX megacaps + STW.AX and the entry allow list is CLEARED.
  Autonomous execution is ON with 10 free slots.

MONDAY'S OPEN IS THE THING THAT MATTERS

  M119 - the fix that stops the feed dying at the bell - is DEPLOYED and has
  NEVER been exercised. Friday's session started at 12:10, after the 20-minute
  delay window that killed the 10:00 one. Monday 10:00 is its first real test.
  Watch the first six minutes: five empty 60s polls used to end the stream
  permanently, with nothing halting, because MARKET DATA DOWN is deliberately
  not a kill-switch trigger.

  An entry can only happen in 57% of the session. Blocked during Opening
  Volatility (10:00-10:28) and Midday Lull (11:59-14:04). With the feed's
  ~20-minute delay the last usable moment is about 15:40, so a trigger must
  land inside 10:29-11:58 or 14:05-15:40. A quiet morning is not a quiet day.

  EXPECT THE FIRST ASX STALENESS EXCLUSION and do not read it as a fault. The
  rail fired 1,589 times on the US feed and has NEVER fired on ASX, because
  ts=now made price age unmeasurable until M128. The first one is it working.

FIRST WORK, IN ORDER

  1. Watch the open. Sweep with session_check every 20-30 minutes. Escalate on
     ERROR/CRITICAL by CONTENT (ib_async logs the 1102 RECOVERY at ERROR), on
     the process dying, a kill-switch trip, a reconciliation mismatch, or any
     order at the broker.
  2. If a fill happens, report it in detail. recent_fills, M71 and post-fill
     reconciliation have never run. The first-fill path was audited on
     21 August and found sound - see "Audited 21 August" in the handoff, and do
     not re-walk it without a reason.
  3. Otherwise the agreed order is item 16 (one symbol, one recommendation -
     needs a design pass, and M73's "analyst, never a trader" framing has to
     survive it), then item 9, whose spec and plan are already written and
     whose measurement is already committed. Items 8, 10, 11, 12, 14 and 15
     were cleared on 21 August.

TWO HABITS THAT EARNED THEIR KEEP ON 21 AUGUST

  Verify the artefact, not the exit code. `invoke build` returned 0 having
  built nothing; three PowerShell string-replacements silently did not match;
  the liquidity filter screens on a random number. None of them FAILED.

  Query the system, do not read the document. Two documents asserted things the
  running system contradicted - the UI/UX colour counts, and the account's
  currency. The second produced a confident wrong finding that had to be
  retracted the same evening.
```
