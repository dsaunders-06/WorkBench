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
| Deployed build | **M141 (`09ab51b`)**, installed 25 August 09:01. Exe SHA256-identical to the signed artefact, signature Valid. **Read back off its own log 09:09 25 August** — `Build: M141 (09ab51b, built 24/08/2026 22:58 UTC, packaged)`. The startup scan ran in the same launch: `RESTING ORDER SCAN: 2 working leg(s) across 1 symbol(s), nothing unjustified` — both legs of TNE's live bracket seen and correctly not flagged |
| Repository HEAD | **WELL ahead of the deployed build** — ten fixes landed after the close on 25 August (items 32, 34, 35, 36, 37, 38, 39, 40, 43, 44, 45). `handoff_state.py` derives the gap; do not read a number from here |
| Deploy gap | **⚠️ LARGE, and NONE OF IT HAS RUN LIVE.** M141 (`09ab51b`) is what is installed; every fix below it is committed and pushed but NOT deployed. Several touch the risk and order paths — the sector rail, position marks, IBKR call timeouts, the drift guard, kill-switch persistence. **Build, deploy and run a WATCHED session before trusting any of it.** Rollback from M141 is still a rename: `C:\QuantAdvisoryTerminal.bak-M140-20260825-0901` |
| Pushed | **Up to date.** M141 pushed 24 August evening. The "Actions minutes exhausted until September" rule was TESTED and is false — see the standing constraints |
| Suite | **2,715 passed, 25 skipped.** ruff, black, mypy and bandit clean |
| Watchlist | **94 ASX megacaps + STW.AX** |
| Entry allow list | **CLEARED** — all 94 enterable |
| Account | **HOLDING TNE.AX 3,051 @ 32.9783**, bracketed 30.69 / 36.86, carried overnight deliberately. NetLiquidation ~1,001,264 AUD. **The app HAS now placed entries on IBKR — 24 August was the first day** |
| Kill switch | **NOT tripped.** It does not persist — see item 32. Yesterday's trip was cleared by the restart, not by a decision |
| Ledgers | **0 closed trades** (seven fabricated rows removed 24 August — see the incident above), **49 risk decisions**, journal carries the day's real order flow |

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

## ⚠️ 24 AUGUST: THE FIRST ORDERS THIS SYSTEM EVER PLACED, AND WHAT WENT WRONG

Read this before touching the order path. It is the most instructive thing the
project has produced and it was found by running the application, not by a test.

### What happened

**10:00** — M119 got its first real test and PASSED. Five empty polls at
10:04:26, `"Retrying with backoff"` instead of ending the stream, and recovery
on its own at 10:21. The defect that killed Friday did not recur.

**10:06:27 — the log died** and stayed dead across a full restart while the app
traded normally. `watch_session.py` held `qat.log` open; on Windows a plain
`open()` grants no delete-sharing, so `doRollover`'s rename failed with
WinError 32, and the handler left `stream=None` and swallowed it. **It cost a
wrong diagnosis:** a feed that had recovered looked hung, and the app was
restarted for nothing. Fixed in M137.

**13:05** — the first real ASX entry signal. The sizer asked for 3,468 shares;
M138's new cap trimmed it to 3,076; the gate refused it because Midday Lull is
not eligible. Every rail correct.

**14:04:51** — Afternoon opened, the gate auto-signed, and TNE.AX and DXS.AX
were transmitted. **Then re-transmitted every sixty seconds, four times each.**

### Why

`_IB_STATUS_MAP` had four entries and none of IBKR's working states, and
`from_ib_trade` only assigned a status when the lookup succeeded — so a
transmitted order came back still reading `pending_signoff`, which is exactly
what `OMS.pending_orders` filters on, so `retry_pending` found it again a minute
later and the gate correctly allowed it again.

**Two individually correct decisions combined.** M31a removed
`order.status = "transmitted"` from before `place_order`, because a raised call
left a false "transmitted". `from_ib_trade` left the working states unmapped on
the stated grounds that they *"leave our own already-set transmitted status
alone"* — true when written, false the moment M31a landed. Fixed in M139, with
a second guard in the OMS that refuses a repeat transmission independently of
any status field.

### The damage, and the cost

68,268 DXS against an intended 17,067 — exactly 4× — and 12,304 TNE against
3,076. About $800k of exposure on a $1M account, and **sixteen orphaned GTC
bracket legs**. Unwound the same afternoon: **NetLiquidation $1,001,287 against
$1,004,063, so −$2,776, or −0.28%.** Never a P&L event; a position-integrity one.

### 15:19 — M139 CONFIRMED, and a third defect found

M139 was deployed at 15:17 and a signal fired at 15:19:36. **TNE.AX 3,051
transmitted EXACTLY ONCE**, filled in full, bracketed at 30.69 / 36.86. Under
yesterday's code it would have gone again at 15:20:36 and every minute after.
The fix is verified in production, which is the only place today's defects were
ever going to be found.

**Then the kill switch tripped, correctly**, on
`Broker reconciliation mismatch: TNE.AX tracked=4382 broker=3051` — the app
believed it held MORE than it had ever ordered.

**⚠️ THE ABSORB PATH REPLAYS ACROSS A CRASH BOUNDARY. Found, NOT fixed.**
`absorbed_fills.json` carried a watermark of `2026-08-24T00:38:09Z`, set before
the 14:08 kill and never advanced past the session that followed. On restart
everything after 10:38 looked unabsorbed, so `recent_fills` returned the whole
afternoon — the duplicate buys, **the operator's manual remediation sells**, and
the app's own current fills. The manual sells were absorbed as *"a resting
protective order executed, and this is now a closed trade"* and matched against
the lot opened at 15:19:36, producing **seven closed trades whose `closed_at`
precedes their `opened_at` by an hour**, worth −$167.90 that nobody lost, in the
file the promotion gate reads.

Repaired by `scripts/repair_impossible_closed_trades.py` (backup kept). The one
test it applies is arithmetic, not judgement: an exit stamped before its entry is
impossible. **Nothing in the application rejects one**, and it should.

**A property worth knowing before the next manual repair:** to the absorb path, a
manual sell through TWS is indistinguishable from a resting stop firing. My own
remediation is what produced the fabricated trades.

### Four things this taught that outlive the bug

1. **A PER-ORDER CAP IS NOT A PER-POSITION CAP.** The $100k cap worked
   perfectly, four times over. Nothing bounds total exposure per name at
   transmission time — the concentration cap lives in the sizer, upstream, so it
   never saw the duplicates.
2. **Stopping the process does not stop the damage.** Orders already at the
   broker kept filling after the app was killed; TNE went from 8,587 to 12,304
   afterwards.
3. **`ib.openTrades()` is CLIENT-SCOPED.** It showed no protective stops while
   sixteen were resting, because they belonged to client id 1 and the probe was
   client 99. Anything auditing broker state must use `reqAllOpenOrders`
   — **and its async form**, because the sync one is a `util.run` wrapper that
   raises "event loop is already running" inside the app (the M102 trap, hit
   three times in one afternoon).
4. **A flat position can still carry short risk.** TNE was flat with eight legs
   resting on it — up to 12,304 shares of automatic short, and buying power
   would not have refused it.

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

22. **The per-order cap keys off CASH; it should key off SPENDABLE cash.**
    Operator finding, 24 August, agreed and deferred to after the session.
    M138's cap uses `account.cash`, which ignores `min_cash_reserve` — money the
    system has already declared unspendable. Fix to
    `balances.spendable_cash(min_cash_reserve)`, the method the Balances panel
    already calls, so there is one definition with three readers rather than
    three definitions.

    **Live numbers:** reserve is **$1,000** (not the $1 default), so 10% of cash
    is $100,186.52 against 10% of spendable at $100,086.52 — **$100** on a $100k
    order. Immaterial today, which is not the argument.

    The argument is that the no-leverage rail already computes
    `spendable = available_cash - min_cash_reserve` (`engine.py:242`) and the
    panel already shows `spendable_cash(...)`. A cap on raw cash is a THIRD
    basis for one question — the shape that hurt `trading_date` (one caller of
    four) and `minimum_hold_status` before it was extracted. And the failure
    that actually bites is not the $100: as cash approaches the reserve, a cap
    on raw cash can authorise an order the no-leverage rail then refuses, so one
    rail permits what another forbids. The reserve exists to be raised; at
    $50,000 the two diverge properly.

23. ~~**Nothing reconciles RESTING ORDERS.**~~ **DONE — M141.**
    `OMS.check_resting_orders()` scans `broker.open_orders()`, nets each
    one-cancels-all group against the position, and logs every leg the book
    cannot justify at ERROR with the prefix `RESTING ORDER ORPHAN:`. Arithmetic,
    not identity — order identity does not survive a restart (item 27's
    finding), so the only durable question is whether the book justifies what
    is resting, not who placed it. Netting is MAX within a group, SUM across
    groups: TNE's own 3,051-share stop and 3,051-share target are one
    justified position, not 6,102 of unexplained risk — a summing rule would
    have flagged the only position this system has ever placed correctly.
    Quarantined through a new `RestingOrderAnomalyStore`, deliberately not
    `PositionAnomalyStore` — that store's `explains()` suppresses the
    kill-switch trip inside `check_reconciliation`, so routing a flat symbol
    through it would grant that symbol immunity from the exact rail that
    caught 24 August's real mismatch. Cancellation sits behind
    `resting_order_cancel_enabled`, default **False**, and acts only on
    symbols the book is FLAT in even when enabled — a held symbol's excess is
    reported and quarantined, never cancelled automatically. **The
    working-status widening this needed is split out as its own item (31,
    below)** by decision, because widening the shared set moves
    `_position_stops`, a sizing input.
    ⚠️ **Cancelling stays OFF until the TOCTOU fix has been WATCHED, not just
    landed.** `resting_order_cancel_enabled` re-reads positions immediately
    before the cancel loop and abandons a symbol that is no longer flat,
    checked against both the broker's fresh answer and this app's own tracked
    fills (Task 7b, final review) — that fix IS in as of this pass, closing the
    gap where a leg filling mid-loop could leave a real short while the loop
    cancelled its OCA sibling. What is not yet true is that anyone has watched
    it fire against a live broker. The first live exercise of this rail —
    turning `resting_order_cancel_enabled` on for real — should be a session
    the operator is watching, the same rule item 28 applies to resetting the
    kill switch.
    Original: M139 stops duplicates being
    created; it does nothing about the sixteen orphaned GTC bracket legs an
    interrupted session left at the broker on 24 August, with the application
    holding no record of any of them. `adopt_broker_positions` adopts
    POSITIONS — establish whether anything adopts or reconciles open ORDERS,
    because a flat TNE carrying 12,304 shares of resting sells is short risk
    nothing was watching. Highest-value item on this list.

24. **Bound total exposure per name at TRANSMISSION time.** See lesson 1 above.
    The concentration cap is upstream in the sizer and cannot see what has
    already gone out.

25. **`preflight`'s book check derives `unprotected` from held positions only.**
    Corrected premise: it already routes through `reqAllOpenOrdersAsync`, via
    `broker.resting_stops()` (`preflight.py:445`) — the client-scoped view was
    never its defect. The defect is at `preflight.py:450`: `unprotected` is
    built by walking `held` positions and asking which lack a stop, so a
    resting stop on a symbol the book does NOT hold — exactly M141's orphan
    shape — is invisible to this check. It answers "is every position
    protected" and cannot answer "what is resting that the book does not
    explain"; that second question is now `check_resting_orders`'s, not
    preflight's, and preflight should say so rather than imply coverage it
    does not have.

26. **The IBKR order preset.** Every API sell on DXS.AX threw
    `Error 10349: Order TIF was set to DAY based on order preset` and
    `Warning 404: Order held while securities are located` — a short-sale locate
    on the sale of a LONG position, which never resolves in paper, parking the
    order at `PreSubmitted`. 68,268 and 12,000 both failed identically, so it is
    not size. A manual sell through TWS filled. Find the preset; every order
    this application places goes through the API.

27. ~~**⚠️ THE ABSORB WATERMARK DOES NOT SURVIVE A CRASH.**~~ **FIXED — M140.**
    The guard sits at the MATCH, not the watermark: `_close_against_lots` refuses
    an exit that precedes a lot **this app opened itself** (`strategy is not
    None`), and a restored watermark over two hours old now warns. The wide
    replay is left alone deliberately — it is what M50 exists for.
    **Narrowed by an existing test:** the first version compared timestamps
    alone and broke three tests in `test_live_exit_price_correction`, which
    absorbs an exit against an ADOPTED lot whose `opened_at` is a placeholder.
    That fixture also ran two clocks and was corrected; the guard was not
    weakened. **What is still true and unfixed: order identity does not survive
    a restart** — `_broker_order_ids` and `_orders` are in-memory, so after a
    restart the app's own fills read as foreign. The guard makes that harmless
    to the ledger rather than making it untrue.
    Original: highest priority of
    everything on this list, because it corrupts the record rather than costing
    money. `absorbed_fills.json`'s watermark advances during a run; if the
    process dies, it stays where it was and the next run absorbs everything that
    happened in between — including fills from orders the app never sent, and
    manual operator activity — attributing them to whatever lot is open now.
    Produced seven impossible trades on 24 August. Options: advance the
    watermark on every absorb rather than periodically; or refuse to absorb a
    fill older than the current run's start; or both. **And reject an
    `opened_at`/`closed_at` inversion outright** — it is arithmetic, and nothing
    checks it today.

28. **The kill switch is TRIPPED.** It caught the mismatch correctly. Item 27
    is now fixed, so it is safe to reset — but reset it on a launch you are
    WATCHING, because the mismatch it caught came from a replay whose first
    pass now warns rather than being silent.

29. **Make deploying update `DEPLOYED` itself.** `handoff_state.py`'s hand-
    maintained constant has now been wrong three times: for a day after M104,
    across the whole M130 deploy, and for two hours after M139 on 24 August —
    that last one in the rush to get a session running before the close. Its own
    comment says the figure must change in the same minute as the copy, and
    exhortation has now failed three times. An `invoke deploy` that expands the
    zip AND rewrites the line would remove the only step a human has to
    remember.

30. **Stage 4 regime re-sourcing** — do not start until the ablation question is
    settled. If the regime gate does not earn its keep, this stage disappears.

31. **The working-status set is narrow in `ib_translate`.** `_IB_WORKING_STATUSES`
    holds three of ib_async's five real working states; `ApiPending` and
    `ApiUpdate` are missing, so `from_ib_resting_stop` reads a stop in either as
    no protection and `verify_position_stops` logs `POSITION UNPROTECTED` on a
    protected position. M141 fixed this for the orphan scan only, in its own
    set, because widening the shared one moves `_position_stops` — the
    denominator of every risk-at-stop figure the governor gates entries on.
    Ship it separately and measure the aggregate before and after on a watched
    session. `tests/data/broker/test_working_statuses.py` asserts the
    divergence, so closing it is a deliberate act.

32. **⚠️ THE KILL SWITCH DOES NOT SURVIVE A RESTART.** `KillSwitch` holds
    `_tripped` in memory and persists NOTHING (`kill_switch.py` has no path, no
    file, no load). `runtime.py:523` constructs a bare one on every launch. So a
    halt that is meant to hold until a human decides holds only until the next
    time the app starts — and it is then cleared **silently**, with no line in
    the log saying a halt was discarded.

    Found on 25 August, and found the embarrassing way: this handoff said "THE
    KILL SWITCH IS TRIPPED … it is SAFE to reset", advice was given on that
    basis, and the operator pointed at the app reporting it INACTIVE. It had
    been cleared by the two restarts that morning, not by anyone. The evidence
    was already on screen — `session_check`'s `kill-switch mentions: 0` — and
    was read as "nothing happened to it" rather than "it is not tripped".

    This is the M50/M140 family: *this state did not survive a restart*. The
    codebase already knows the fix, twice — `PositionAnomalyStore` and
    `RestingOrderAnomalyStore` both persist deliberately, and the latter's
    docstring says why: the thing it guards against is inherited across a
    restart. The switch, which is the most consequential state in the
    application, is the one that does not.

    Two things are needed, and the second matters as much as the first: persist
    the tripped state with its reason and timestamp, AND log loudly at startup
    when a persisted halt is restored — or, if a deliberate decision is made
    that a halt should NOT outlive the process, say so in the log at every
    launch that discards one. Silence is the defect either way.

    Until then: **a tripped kill switch is not a durable halt.** If the account
    must not trade, do not rely on the switch alone across a restart.

33. **The feed's blind window and the entry gate line up by COINCIDENCE, and
    nothing checks that they do.** yfinance publishes ASX intraday roughly 20
    minutes late, so the application is structurally blind from the bell until
    about 10:21. The autonomy gate happens to block entries until 10:29. The
    seven-minute margin is the only thing standing between "no entry can be
    sized on absent data" and "one can", and it is not enforced, asserted or
    even mentioned anywhere in the code.

    Measured on two consecutive sessions, and the timing is deterministic from
    activation rather than lucky: activation 10:00:12, five empty polls, backoff
    at **10:04:26 on both 24 and 25 August to the second**, recovery on its own
    at 10:21.

    Two ways this stops being safe, neither of them exotic. Widen the entry
    window — move Morning Trend earlier, or let Opening Volatility trade — and
    entries become possible while the feed still has nothing for today. Or let
    the delay run longer than usual on one morning, and the same thing happens
    with no configuration change at all. In both cases the failure is silent:
    the strategy sees stale bars, not missing ones, because the last data it has
    is yesterday's close.

    The same delay is already documented biting at the OTHER end — the last
    usable moment is about 15:40, because a move after that never reaches the
    strategy before stand-down. That end is written down; this end is not.

    What is wanted is not a bigger margin but an ASSERTION: the entry gate
    should refuse to open on a symbol whose most recent tick predates the
    session, and say so. That turns an accident of the calendar into a rail,
    and it holds however the windows or the delay move.

    The deeper fix is a feed that is not 20 minutes late at all. IBKR is
    already connected, already authenticated, and already serving positions and
    orders to this application — it is the obvious candidate, and the reason
    yfinance is still the price source is history rather than a decision.

    **NARROWED 25 Aug, after checking what already exists** — the lesson of
    three wrong findings earlier the same day. A staleness rail IS in place:
    `MarketDataFeed` publishes `DataStaleEvent` once a symbol stops updating
    for `data_staleness_seconds` (900s) BEYOND the feed's own known delay, and
    `refusals.py` carries a "Stale market data" reason, so the entry path can
    already refuse on staleness.

    The gap is narrower and more specific: **a symbol that has never ticked
    this session is not stale, it is ABSENT** — and absence is not refused. At
    the bell nothing has ticked today, so nothing can read as stale; the
    strategy works from warm-start history, which is yesterday's close. That is
    the case the 10:29 entry gate happens to cover by coincidence, and nothing
    asserts it.

    So the work is *"treat never-ticked-this-session as its own refusal,
    distinct from stale"*, not *"add a staleness rail"*. It adds a refusal to
    the entry path, so it wants a plan and a watched session rather than being
    appended to a long day of other changes. **Deliberately NOT done on 25
    August for that reason** — it is the natural next piece of work.

34. ~~**⚠️ THE RECONCILIATION POLL WEDGED SILENTLY AND NEVER RECOVERED.**~~
    **BACKSTOP FIXED 25 Aug (`e9a180b`) — ROOT CAUSE STILL OPEN.** `poll()` now
    runs under `asyncio.wait_for` (120s default) and logs what is at stake;
    CRITICAL after three in a row; it does NOT trip the kill switch, which
    stays the operator's open decision. **The real cause is that the IBKR
    adapter has no timeout on ANY of its eight awaits on the client** —
    `reqExecutionsAsync`, reached first via `absorb_broker_fills`, resolves
    only on `execDetailsEnd` and hangs forever if that is lost. THAT is not
    fixed and should be the next thing done. Observed
    live on 25 August. `ReconciliationMonitor` started at 09:09:52, adopted
    positions, ran the startup orphan scan — and then completed **not one** of
    the ~20 polls due in the following 110 minutes. The app was otherwise
    healthy throughout: macro fetched, feed recovered, regime refit twice, and
    five bracketed entries placed correctly.

    **Nothing said so.** No `Reconciliation poll failed` line — `_run`'s handler
    never fired, so nothing raised. The signature is a hung `await` inside
    `poll()`: no exception, no log, the loop simply never comes back round.
    `check_reconciliation` calls `absorb_broker_fills()` first, which talks to
    IBKR, and that is the most likely place to be stuck.

    **It was only visible because M141's scan logs a heartbeat on every poll.**
    `check_reconciliation` is silent on a clean pass, so for as long as this
    project has existed a dead reconciliation loop and a healthy one have
    produced identical logs. This may well have happened before and gone
    unnoticed. The heartbeat existed because the final code review insisted on
    it (finding I2) over a version that logged only on divergence.

    **What it costs while wedged:** nothing compares book against broker,
    nothing verifies a stop still rests, the orphan scan does not run, and —
    worst — `absorb_broker_fills` does not run, so a stop or target firing is
    never recorded. The app would go on believing it holds a position it has
    already exited. That is M140's shape with a different cause.

    Not diagnosed as of this writing. What IS established: a read-only probe on
    clientId 99 got `reqAllOpenOrders`, `positions`, `fills` and `executions`
    back in **1.07 seconds**, so IBKR was fully responsive and the wedge is
    inside the application.

    Wanted: a watchdog on the poll itself. A loop whose failure mode is silence
    needs a deadline — if a poll has not COMPLETED within some multiple of its
    interval, that is an ERROR and a kill-switch candidate, because the rails
    are off. `asyncio.wait_for` around `poll()` would do it.

    **AND check 5 of `session_check.ps1` reported a reassuring green all day**,
    which is a defect in M141's own operator surface. It reads
    `5 orphans  RESTING ORDER SCAN ran, clean - 0 divergences` — true, and
    misleading: the scan ran ONCE, at 09:09:52, and the rail was dead for the
    remaining 6h50m. The check distinguishes "did not run" from "ran clean",
    which was the point of I2, but NOT "running every poll" from "ran once at
    startup seven hours ago".

    Fix it with the same change: report the LAST scan time and the COUNT, and
    flag when the newest heartbeat is older than a small multiple of
    `reconciliation_poll_seconds`. A freshness check is the only kind that can
    catch a rail that stopped rather than one that never started.

    Closing the loop on the day: no bracket fired on 25 August, so the worst
    case never materialised — nothing closed unrecorded and the ledger is not
    short. That was luck, not design.

35. **`ib_async` logs each `orderStatus` at INFO with the entire `Trade` repr**,
    including the full `TradeLogEntry` history — kilobytes per line, growing as
    each order accumulates status changes. On 25 August this rotated the 5 MiB
    log **three times in under three minutes** (10:30:27, 10:32:20, 10:32:55)
    during ordinary order activity. With five backups, an entire session's
    app-level diagnostics can be evicted within the hour: the lines recording
    the day's five entries were one rotation from deletion when they were read.

    Same consequence as M137 — no log to diagnose from — by the opposite
    mechanism. M137 was rotation FAILING; this is rotation THRASHING, and it
    hides exactly the app-level lines a live incident needs. Quiet the
    `ib_async.wrapper` logger to WARNING, or raise the cap and the backup count.

36. **`poll()`'s docstring promises a control that does not exist, and the
    kill-switch button is what sits where it would be.**
    `ReconciliationMonitor.poll` says it is *"Public so a test or the Risk
    Console can force a check without waiting on the interval."* **The Risk
    Console cannot.** That screen has exactly three buttons — the kill switch
    (`risk_console.py:126`), "Declare a difference explained…", and "Clear a
    quarantine…". Nothing anywhere calls `poll()` outside tests.

    On 25 August that sentence was read as fact and the operator was told to
    force a reconciliation from the Risk Console while diagnosing item 34.
    There was no such control. The kill switch was tripped at 12:09:27 with
    `Manual trigger by operator (risk console)` — the only code path that can
    produce that message — and the operator reports not pressing it.
    `_on_kill_switch_clicked` is a TOGGLE bound to Qt's `clicked`, which fires
    on **Space or Enter when the button has focus**, and it is the first
    widget constructed on that screen. Halting the account was one stray
    keystroke away from an instruction to do something else entirely.

    Two fixes, and the second is the real one. **Build the force-check button**
    — it is genuinely wanted, item 34 is precisely the case for it, and the
    docstring has been promising it for long enough that someone believed it.
    And **make the kill-switch button hard to hit by accident**: a confirm step
    on TRIP (not on reset — de-risking must stay one click), or at minimum
    remove it from the default focus chain. A control whose whole purpose is to
    stop the account should not be the thing a stray Enter finds first.

    The general form is the M110 family again: a docstring asserting a
    capability nothing implements. It was believed here by the same session
    that was auditing other docstrings for exactly this.

37. **⚠️ THE DRIFT GUARD ON PARKED ORDERS MAY NEVER RUN.** An order the autonomy
    gate blocks on phase is not rejected — it parks in `pending_signoff` and is
    retried every 60 seconds (M31b, and that retry is right: without it a
    blocked exit sat for a hundred sessions and a position was never closed).
    Observed live on 25 August: IAG.AX and RHC.AX parked at ~12:47 and were
    still being retried at 13:00, waiting for Midday Lull to end at 14:04.

    `AutonomousExecutor._retry_loop`'s docstring says parking is safe because
    *"the gate re-reads the current price and refuses anything that has drifted
    past `autonomous_price_drift_limit_pct`… An order that sat too long fails on
    drift rather than being signed at a price nobody chose."*

    **That guard is conditional and fails open.** `gate.py:200` reads
    `if current_price is not None and order.reference_price:` — a `None` price
    skips the check entirely, with no block and no log. And `current_price`
    comes from `AutonomousExecutor._current_price`, which asks
    `broker.get_market_data()`; `IBAdapter.get_market_data` issues `reqMktData`
    and then yields exactly ONCE (`await asyncio.sleep(0)`) before reading the
    ticker, whose fields default to `nan`. In `_current_price`,
    `float(quote.get("last") or …)` returns `nan` because **`nan` is truthy**,
    and `nan > 0` is False — so it returns `None`, and the guard is skipped.

    `_current_price`'s own docstring blesses this: *"None means the drift check
    is skipped rather than failed - an execution-only adapter never quoting is a
    known configuration."* True for Alpaca. IBKR is not execution-only, and the
    result is that the one guard protecting a stale parked order is off.

    **No `has drifted` line exists in ANY log**, including every rotated backup
    and pre-deploy archive back to 12 August. That is not proof — the phase
    check precedes the drift check and short-circuits it, and nothing may ever
    have drifted 3% — but combined with the code path it is not reassuring.

    Wanted: `get_market_data` must actually WAIT for a tick (or use
    `reqTickersAsync`), `_current_price` must treat `nan` as absent explicitly
    rather than by accident, and a skipped drift check must LOG that it was
    skipped. A guard that silently does nothing when its input is missing is the
    fabricated-all-clear shape this project keeps rediscovering — item 34, the
    `open_orders` docstrings, and now this.

    Also note the ordering: the phase block precedes the drift block, so a
    parked order's staleness is never even evaluated until the window reopens.

38. **⚠️ THE RISK CONSOLE CALLS A PARKED ORDER "approved".** Observed 25 August:
    RHC.AX, IAG.AX and PNI.AX all render as `approved  approved` in the Risk
    Console's audit panel while the Blotter shows them `pending_signoff -
    session phase 'Midday Lull' is not eligible`. The headline above reads
    *"7 candidate(s) considered, none refused."*

    The panel is not lying, it is answering a different question in a word that
    reads as this one. `risk_console.py:333` renders
    `runtime.risk_engine.audit_log.entries()`, where `approved` means **the risk
    engine approved the sizing** — not that the order was signed off, and
    certainly not that it reached the broker. An order can be risk-approved and
    then blocked by the autonomy gate, which is exactly what these three are.

    **This ambiguity is already documented elsewhere in the codebase**, which is
    what makes it a defect rather than a wording preference: `approvals.py:9`
    says of a different surface *"the trade ledger cannot tell them apart. Both
    read `approved`."* The same collision, reproduced on the screen an operator
    checks to find out what happened.

    The operator-facing consequence is direct: this screen is where you look to
    answer "did my orders go out", and today it said yes for three that had not.

    Wanted: say which approval it is. `risk-approved` versus `signed off`, or
    render the order's actual status beside it. The audit log is the right data;
    the label is the bug.

39. **The Equity vs Benchmark chart's x-axis renders bar indices, not dates.**
    Strategy Workbench, observed 25 August: the axis is labelled *"Date
    (synthetic daily bars)"* and its ticks read `00.550, 00.600 … 01.450`. Those
    are fractional positions along a one-element series, formatted as if they
    were numbers on a continuous scale. With a single closed trade the series
    has one point, so the axis has nothing to span and falls back to decimals
    around it.

    Reported before and still present. It is cosmetic only in the sense that no
    decision reads it — but it is on the screen used to judge a strategy, and an
    axis that says "Date" and shows `01.150` teaches the reader to distrust the
    chart.

40. **UTC is still rendered where AEST is meant — more instances found.**
    Extends item 21, which is NOT fully closed. Seen on 25 August:
    the Balances panel's *"as of 03:21:34"* (a 13:21 AEST event), the Regime
    Monitor's transition history *"25/08/2026 00:03:00 UTC -> sideways"*, and
    the Blotter's timestamp column showing `02:38:39` for a 12:38 AEST order.

    **`watch_session.py:179` is the worst of them** and is not a screen at all:
    `print(f"    -- {datetime.now(UTC):%H:%M:%S} tally: {parts}")` prints a UTC
    clock with **no zone label whatsoever**, into the live console an operator
    watches during a session. The others at least say "UTC" or sit in a field
    you might think to question; this one simply looks like the time. Read
    `03:21:34` off the watcher at 13:21 AEST and correlate it against the
    Blotter, the log, or your own watch, and the ten-hour error lands in the
    middle of an incident — which is the only time anyone is reading it.

    The Risk Console's anomaly rows are NOT affected — they label the zone
    explicitly (`… 14:22 UTC`), which is the pattern the rest should follow:
    either convert to session-local or say which zone it is. Silent UTC on a
    surface whose other fields are session-local is the failure, not UTC itself.

    Note the log files themselves are correctly UTC-with-offset in their `ts`
    field and should stay that way — machine records want one zone. This is
    about what is rendered to a human.

41. **CORRECTED 25 Aug — this item was OVERSTATED. Costs ARE applied to live
    closed trades; what is missing is only the ACTUAL per-fill commission.**

    > The original wording below claimed every live closed trade records 0.00
    > both sides, and quantified "$1,138.75 of invisible brokerage" and
    > "~$3,400 the promotion gate cannot see". **All of that is wrong.**
    >
    > `trades.py:487` sets `self._costs = CostModel.from_settings(...) if
    > apply_costs_in_paper or is_live else None`, and
    > `apply_costs_in_paper` defaults **True**. So `entry_cost` and
    > `exit_cost` ARE populated on live closed trades, from the model — which
    > is calibrated to IBKR's published ASX Fixed rates (8.8 bps, $6.60
    > floor). The promotion gate is NOT blind to costs.
    >
    > The comment immediately above that line already said so plainly: *"Real
    > per-fill commissions from a live broker are not read back yet."* The
    > finding was written from the absence of the word `commission` in
    > `ib_adapter.py` and `oms.py`, without checking whether the LEDGER
    > applied the model. Grepping for a word is not reading the path.
    >
    > **What remains true, and is all that remains:** the figures are
    > MODELLED, not actual. `ib_async` delivers the real charge on
    > `Fill.commissionReport` (`commission`, `currency`), and `BrokerFill`
    > carries no field for it. Reading it back would replace a good estimate
    > with the truth, and would surface any drift between IBKR's actual
    > billing and the published rates the profile encodes.
    >
    > **Priority accordingly: LOW.** Model-versus-actual on a well-calibrated
    > profile, not costs-versus-zero. Everything below is the original,
    > overstated finding, kept so the error is legible rather than tidied
    > away.

    ORIGINAL FINDING (overstated): **Brokerage is not captured on live trades.** IBKR charges roughly **$6.60**
    per ASX trade; the Performance tab reflects none of it.

    The seam already exists and is unwired, so this is plumbing rather than
    design: `ClosedTrade` carries `entry_cost` and `exit_cost`
    (`performance/trades.py:220`), and the backtester fills them from
    `backtester/costs.py`'s commission-with-a-floor model — whose own docstring
    warns that a flat fee is *"trivial on a large position and ruinous on a
    small one"*. **Nothing in `ib_adapter.py` or `oms.py` mentions commission at
    all**, so every live closed trade records 0.00 both sides.

    ib_async supplies it: `Fill.commissionReport` carries `commission` and
    `currency`, delivered on the `commissionReport` event. Absorbing it where
    fills are absorbed would populate the fields that already exist.

    Until then every live P&L figure, expectancy, profit factor and promotion
    decision is computed gross.

    **QUANTIFIED on the 25 August book, and the $6.60 figure is the FLOOR, not
    the fee.** The ASX profile is `IBKR Australia - Fixed (inc GST)`,
    `commission_bps=8.8` — 0.088% of trade value — with `min_commission=6.60`,
    which only binds below about $7,500 of notional. Every trade this system
    has placed is far above that. Round-tripping the ten open positions at the
    modelled rate:

        brokerage        1,138.75 AUD
        slippage           647.02 AUD  (modelled impact, not a charge)
        total friction   1,785.77 AUD   = 0.113% of equity in brokerage alone

    For scale, the quiet session of 21 August moved equity **+$109.93**. The
    brokerage on this book is ten times that, and none of it reaches a closed
    trade.

    The promotion gate is where this bites hardest: it needs **30 closed trades
    with net P&L positive** to decide whether a strategy keeps trading
    unattended. At ~$114 of brokerage per average round trip here, thirty trades
    is **~$3,400 of real cost the gate cannot see** — so it would judge an edge
    with the costs deleted, and keep an unprofitable strategy running on that
    basis.

    Note `risk_decisions.csv` ALREADY records `round_trip_cost` and
    `cost_to_risk_pct` per decision (ANZ: 65.80 and 5.15%) — reproduced exactly
    from the model, `2 × (commission 20.97 + slippage 11.92)`. So the system
    estimates the cost when deciding to trade and then never records what it
    actually paid. The estimate exists; the actual does not.

    Be fair to the model: it is market-aware, distinguishes IBKR Fixed from
    Tiered, implements the floor, and keeps third-party fees separate with a
    documented reason. This item is ONLY about the live path not recording
    actuals.

42. **CORRECTED 25 Aug — this item was WRONG on its main claim. The governor
    DOES evaluate the parked set. Only the per-order CASH cap repeats.**

    > The original below claimed each parked order "was sized independently"
    > and "none of the three has ever been evaluated against the other two",
    > with a table projecting the fourth release at 14.3% of remaining cash.
    > **The exposure half of that is wrong.**
    >
    > `oms.py:369` passes `pending_orders=self.pending_orders()` into the risk
    > engine, and `governor.py:136` folds them into its snapshot. Verified
    > against `risk_decisions.csv` for 25 August — `position_count` climbs
    > 1→9, one per order, while only FIVE positions were ever held before
    > 14:05:
    >
    > | Time | Sym | PosCount | GrossExp | AggRisk |
    > |---|---|---|---|---|
    > | 12:38 | RHC | 6 | 46.4% | 3.74% |
    > | 12:39 | IAG | 7 | 51.7% | 3.99% |
    > | 13:22 | PNI | 8 | 57.1% | 4.44% |
    > | 13:34 | ANZ | 9 | 62.4% | 4.87% |
    >
    > IAG's count of 7 is five held plus RHC parked plus itself. So aggregate
    > risk, gross exposure and concentration all accumulated ACROSS the parked
    > set, and ANZ was resized to 640 shares by exactly the headroom that
    > accounting produced. The set was bounded.
    >
    > **What survives, and it is narrower:** the per-order cash cap (M138, 10%
    > of cash) used the same 532,591 balance for RHC, IAG and PNI, because
    > cash does not move until a fill. Each was trimmed to 53,259. That is a
    > PER-ORDER cap behaving as specified rather than a defect, and the
    > portfolio-level question it raises is already outstanding item 24.
    >
    > **Priority: LOW, and arguably a duplicate of item 24.** The original is
    > kept below so the error is legible.

    ORIGINAL FINDING (wrong on exposure): **PARKED ORDERS ACCUMULATE AND
    RELEASE TOGETHER.** By 13:22 on 25 August three orders were parked in
    `pending_signoff` waiting for Midday Lull to end — RHC.AX (12:38), IAG.AX
    (12:39), PNI.AX (13:22). All three release in the same retry pass at 14:05.

    Each was sized independently, against the cash and exposure that existed at
    the moment it was created. RHC's own trim line records this:
    *"trimmed from 1971 to 1194 shares by the per-order cap of 10.0% of cash
    (53259 of 532591)"* — 10% of the cash **as it was at 12:38**. IAG and PNI
    each did the same arithmetic against a different balance, and none of the
    three has ever been evaluated against the other two.

    So the per-order cap is applied three times and the *combined* draw at the
    moment of release is applied never. This is outstanding item 24 —
    *"bound total exposure per NAME at transmission time"* — generalised from
    one symbol to the portfolio, and it is the same failure that item 24 was
    raised for: **the per-order cap works perfectly, several times over, and
    that is precisely the problem.**

    There IS a fail-closed cash re-check at sign-off (`_sign_off_locked`,
    documented against exactly this: *"ten orders each individually affordable
    when submitted can collectively overdraw"*), and sign-off is serialised. So
    cash is defended. **Exposure and concentration are not** — those are
    evaluated at sizing, not at release.

    Compounding it, item 37: the drift guard that should refuse a stale parked
    order appears not to run. Three orders sized 80+ minutes earlier, released
    at once, with the staleness check off, and only cash re-checked.

    Wanted: evaluate the parked queue as a SET at release, not one at a time.

43. ~~**A rejected order's reason reaches neither the log nor the Blotter.**~~
    **CORRECTED AND FIXED 25 Aug. The original claim was wrong; the real
    defect was one code path, and it is now closed.**

    > **Wrong:** refusals ARE journalled and DO reach the Blotter, which reads
    > reasons from the decision journal by order id. Seven rejections on 25
    > August carry full text - `kill-switch tripped`, `already at the
    > 10-position limit (10 held or pending)`. I wrote the finding from the
    > absence of a `reason` field on `Order` without checking the journal.
    >
    > **Right, and narrower:** there are two kill-switch refusals.
    > `submit_order` (`oms.py:334`) goes through `_new_rejected_order`, which
    > records. `_sign_off_locked` (`oms.py:633`) set the status, logged INFO
    > and RETURNED - while its two neighbours in the same method, "no price
    > available" and "broker refused", both call `_record`. Only that one did
    > not, so an order refused at sign-off showed on the Blotter with an empty
    > reason and no journal row at all.
    >
    > Observed: order `ab701dff`, RHC.AX, 12:37:35, refused inside the
    > kill-switch window and absent from the journal entirely, while three
    > other kill-switch refusals in the same window were recorded.
    >
    > Fixed: that path now journals `kill-switch tripped: <reason>`, carrying
    > the switch's own cause rather than a generic string.

    ORIGINAL FINDING (wrong):
    Blotter row 40 on 25 August: `RHC.AX buy 0 … rejected` with the reason
    column showing `-`. Quantity zero and status rejected are correct — that is
    `oms.py:335`'s `_new_rejected_order(candidate, 0.0, "kill-switch tripped")`,
    created at 12:37:35 while the switch was tripped, and the reason is true.

    It is simply not carried anywhere an operator can read it. **The log never
    names that order at all** — searched every rotated file, no line mentions
    its id — and `Order` is `slots=True` with neither a `rejection_reason` nor a
    `reason` field, so the refusal text only ever reaches the DecisionJournal.
    Parked orders DO show their reason on the Blotter because the autonomy
    gate's block text travels a different route entirely.

    The result is backwards: the Blotter explains why an order is *waiting* but
    not why one was *refused*, and refusal is the more consequential outcome.
    Note this is NOT the classifier's fault — `refusals.py:122` carries
    `("kill-switch", RefusalFamily.STATE, "Kill-switch active")`, so the reason
    would render correctly if it arrived. It never arrives.

    Wanted: carry the refusal reason on the order, and log a rejection at INFO
    naming the order and the reason. A refusal nobody can see is indistinguishable
    from a signal that never fired — and this project has already spent a day on
    that distinction.

44. ~~**⚠️⚠️ THE SECTOR CONCENTRATION RAIL HAS NEVER RUN.**~~ **FIXED 25 Aug
    (`7ba68ab`).** Both halves wired — `OrderCandidate.sector` and
    `sector_by_symbol` — because `governor.py` needs both and either alone is
    inert. Falsification observed: with either missing the candidate sizes in
    full. Five tests, including one proving a diversified book is NOT trimmed,
    so the trim provably comes from the sector branch. Original finding: Found 25 August because the operator looked at ten holdings and
    said "there seem to be a lot of banks".

    There were. **Six of the ten were Financials** — ANZ, ASX, BOQ, IAG, PNI,
    SUN — against a configured cap of **30%**.

    Everything needed is present and correct:
    * `max_sector_concentration_pct` = 0.30 (`config.py:189`), with a comment
      explaining the value was chosen deliberately: *"40% never bound before the
      third position in a sector was already on; 30% bites at two-and-a-bit,
      which is the point"*.
    * `governor.py:358` implements it, trimming rather than refusing (M31c).
    * `sectors.py` carries 102 ASX classifications, and all six of the symbols
      above are correctly mapped to `Financials`.
    * The parameter is threaded the whole way: `oms.submit_order(…,
      sector_by_symbol)` at `oms.py:293` → `:365` → `engine.py:306` →
      `governor.py:358`.

    And the live path does not pass it. `signal_bridge.py:1364`:

        await self.oms.submit_order(
            candidate, account.net_liquidation, existing_weights, existing_returns
        )

    Four positional arguments. `sector_by_symbol` defaults to `None`, so the
    rail receives no data on **every order this system has ever placed**, and
    silently does nothing. The parameter's presence in four signatures is what
    makes it invisible: every layer looks correctly wired, because every layer
    IS correctly wired except the one that starts the chain.

    This is the day's recurring shape at its most consequential — a guard that
    fails open on missing input and says nothing — but unlike the others the
    damage is already on the book: a 60% single-sector concentration that the
    system was explicitly configured to hold to 30%, accumulated over a single
    morning without one line of complaint.

    Note it would ALSO have bound today for the right reason. Six financials
    arrived across two windows; the cap "bites at two-and-a-bit", so it should
    have trimmed from roughly the third onward.

    Wanted: pass `SECTOR_BY_SYMBOL` at the call site. Then a test that asserts
    the rail BINDS on a constructed over-concentrated book — because a rail
    whose test only proves it can be called is what allowed this.

    Check the other optional risk arguments at the same call site for the same
    defect: `existing_weights` and `existing_returns` ARE passed, but anything
    else defaulting quietly deserves the same look.

    **CONFIRMED IN THE PRODUCTION AUDIT TRAIL, not just by reading code.**
    `risk_decisions.csv`'s `inputs` column records the governor's own view at
    each decision. Across all nine buys on 25 August:

    | Sym | AggRisk | Headroom | GrossExp | held_in_sector_dollars | sector_pct |
    |---|---|---|---|---|---|
    | LOV | 0.70% | 43,052 | 10.1% | **0.0** | null |
    | BOQ | 0.99% | 40,154 | 13.1% | **0.0** | null |
    | ASX | 1.87% | 31,351 | 26.5% | **0.0** | null |
    | A2M | 2.56% | 24,362 | 34.0% | **0.0** | null |
    | SUN | 3.28% | 17,227 | 40.6% | **0.0** | null |
    | RHC | 3.74% | 12,660 | 46.4% | **0.0** | null |
    | IAG | 3.99% | 10,158 | 51.7% | **0.0** | null |
    | PNI | 4.44% |  5,612 | 57.1% | **0.0** | null |
    | ANZ | 4.87% |  1,278 | 62.4% | **0.0** | null |

    Financials arrived 2nd, 3rd, 5th, 7th, 8th and 9th, and the governor
    recorded zero dollars held in sector every time. The evidence to catch this
    has existed since the first trade this system ever placed; nothing read it.

    **What DID limit the book was the aggregate risk cap alone** — headroom
    drained 43,052 → 1,278 and the last two were `resized_by_governor: true`.
    That rail worked correctly. But aggregate risk is indifferent to whether
    nine positions are nine sectors or one, which is exactly why the sector cap
    exists. The account finished at 62.4% gross exposure and 60% Financials.

    Answers a question asked on the day - why ANZ was only 640 shares. Not the
    sector rail: `headroom_dollars 1278.17 / per_share_risk 1.9964 = 640.2`,
    matching `final_shares` 640.2276 exactly. It was the aggregate risk cap,
    biting on the last order of the day.

45. ~~**THE POSITIONS PANEL HAS NO PRICES.**~~ **FIXED 25 Aug (`d494cb6`).**
    `positions()` is now enriched from `ib.portfolio()`; `positions()` stays
    authoritative for QUANTITY because reconciliation feeds the kill switch
    from it. Zero and nan marks are refused, both pinned by tests. Original
    finding: Every row on 25 August showed `Last ($) —`, `P&L —`, `To stop —` and
    `(escape unknown)`, for all ten holdings.

    **`(escape unknown)` is not the defect — it is the honesty marker working.**
    `signal_bridge.py:222` defines `escape_evaluated` as false *"only when there
    is a stop capable of an escape but no price was supplied to measure the loss
    against"*, and `position_view.py:143` appends the suffix so the panel says
    "we could not check" instead of asserting the minimum hold is definitely on.
    That is precisely the behaviour most of the rest of this list wishes it had.
    It appearing on ALL TEN rows is the signal, and the signal is: there is no
    price for any position.

    `_last_price` reads `Position.current_price` and deliberately refuses to
    fall back to `avg_price` — its docstring is right that a cost basis under a
    column headed "Last" is worse than a blank. **The IBKR adapter never
    populates `current_price`.** Grep it: `current_price` appears nowhere in
    `ib_adapter.py` or `ib_translate.py`. The field is M66's and its own comment
    discusses *Alpaca's* consolidated tape — it was built before the IBKR move
    and never carried across. M104's shape again: the boundary that was missed.

    **The fix is one call.** Measured against the installed ib_async 2.1.0:

        ib.positions()  -> Position(account, contract, position, avgCost)
        ib.portfolio()  -> PortfolioItem(contract, position, marketPrice,
                                         marketValue, averageCost,
                                         unrealizedPNL, realizedPNL, account)

    `ib_adapter.py:752` uses `positions()`, which carries no price.
    `portfolio()` carries the mark, the market value AND the unrealised P&L, is
    already populated by the `updatePortfolio` events filling the log, and costs
    no extra request.

    That one call would fill `Last`, `P&L`, `To stop`, `Long market value` in
    Balances — blank for the same reason — and retire `(escape unknown)` on
    every row. It would also give the minimum-hold loss escape a price to
    evaluate against, which is a RAIL, not a display: right now every position
    is conservatively held because nothing can check whether the escape should
    release it.

    NOTE this is a sibling of item 37 but NOT the same bug. That one is
    `broker.get_market_data()` / `reqMktData` returning `nan`. This one is
    `positions()` carrying no mark. Both are "no price reaches the app from
    IBKR", by two independent routes, and both fail silently. Fix them together
    and check whether any third consumer is quietly priceless too.

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

Then read docs\HANDOFF.md, and read the 24 AUGUST incident section BEFORE
touching the order path. It is the most instructive thing this project has
produced and none of it was caught by a test.

⚠️ POWERSHELL for anything touching %LOCALAPPDATA%\QuantAdvisoryTerminal -
including Python that only READS it, and anything that builds Settings(), which
loads that directory's .env whether or not the script mentions it. The Bash
sandbox serves a frozen snapshot and does NOT error.

PUSH NORMALLY - the "Actions minutes exhausted" rule was tested on 24 August and
is false. But the repo is PRIVATE and CI runs on windows-latest at a 2x
multiplier, so BATCH commits and push once. A docs-only commit still buys a full
Windows run.

THE STATE

  Deployed M140 (e432e1f), verified in production - read back off its own log
  24 August. HEAD is ahead of it by item 23's fix (M141) and the final-review
  fixes on top of that.
  THE ACCOUNT IS NOT FLAT: it holds TNE.AX 3,051 @ 32.9783, bracketed at 30.69
  and 36.86, carried overnight deliberately. That position is real and correct.
  THE KILL SWITCH IS TRIPPED, correctly. Item 27 (the absorb-watermark defect)
  is now FIXED (M140), so it is SAFE TO RESET - but only on a launch you are
  WATCHING (item 28), because the mismatch it caught came from a replay whose
  first pass now warns rather than being silent.
  closed_trades.csv is back to 0 rows after seven fabricated trades were
  removed. risk_decisions.csv holds 49 real decisions.

WHAT 24 AUGUST ESTABLISHED

  M119 passed - the feed hit five empty polls, retried with backoff, recovered
  on its own. M137 fixed a log that died silently at its rotation cap and stayed
  dead across a restart. M138 made the per-order cap a share of CASH that trims
  rather than refuses. M139 stopped an order being transmitted four times.

  Three defects, all in the order path, none caught by any test. All three are
  now fixed - M140 closed the last one, the absorb-watermark replay (item 27).

FIRST WORK, IN ORDER

  1. Item 23 is DONE (M141) - OMS.check_resting_orders() reconciles resting
     orders against the book and quarantines what it cannot justify. Read the
     final-review fixes before touching it further: cancelling
     (resting_order_cancel_enabled) stays OFF until its TOCTOU guard (Task 7b,
     already landed) has been WATCHED against a live broker, not just shipped -
     its first live exercise should be a session you are watching.
  2. Item 24 - bound total exposure per NAME at transmission time. The
     per-order cap worked perfectly four times over; that is the whole problem.
  3. Item 25 - preflight's broker view was never the defect (corrected premise;
     it already routes through reqAllOpenOrdersAsync). The defect is that
     `unprotected` is built by walking HELD positions only, so a resting stop
     on a symbol the book does NOT hold - item 23's own orphan shape - is
     invisible to preflight. That question is now check_resting_orders's, and
     preflight should say so rather than imply coverage it does not have.
  4. Then reset the kill switch on a session you are WATCHING (see THE STATE
     above) - nothing is blocking this except watching it happen.

TWO HABITS THAT PAID FOR THEMSELVES ON 24 AUGUST

  Run it, do not reason about it. Every defect found came from a live session.
  Two documented constraints and two saved memories were also disproved by
  simply executing them.

  A green result from an incomplete query is not evidence. ib.openTrades() is
  CLIENT-SCOPED - it reported no protective stops while sixteen were resting.
  Use reqAllOpenOrdersAsync, and prefer the async form of any ib_async call: the
  sync ones wrap util.run and raise "event loop is already running" inside the
  app. That trap was hit three times in one afternoon.
```
