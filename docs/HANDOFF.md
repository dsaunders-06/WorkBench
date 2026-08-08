# Handoff — 8 August 2026

Paste the block at the bottom into a new context window. Everything above it is
the detail that block points at.

---

## ⚠️ The one thing with a clock

**MNST splits 2-for-1 with an ex-date of Tuesday 11 August, and a buy order for
8 shares is queued at Alpaca waiting for Monday's open.**

This is the first deliberate machinery test this project has run. Its purpose is
one measurement that cannot be reasoned about: **what Alpaca does to a held
quantity, and to a resting protective order, when a stock splits.** M39's
adjustment cannot be designed without it, and this paper account has processed
**zero** corporate actions in its life.

**The procedure is written, printed and standalone: `docs/MNST_SPLIT_TEST.md`.**
It assumes no memory of the conversation that produced it. Read that, not this.

Three things from it that must not be lost:

* **The app must NOT be running when the order fills.** It does not track MNST,
  so it will not absorb the fill, and the first reconciliation poll reads it as
  an unexplained divergence and halts the session. Start the app ~15 minutes
  *after* the open instead.
* **The stop is placed on Monday, not attached to the buy.** Alpaca's ticket
  refuses a stop below the market on a *buy* order — that field is a
  stop-*entry*. Step 4a of the sheet.
* **Expect the position to be liquidated on Tuesday, and that is the result.**
  Post-split MNST trades near $45.43 while the stop rests at $72.68 — above the
  market, so an unadjusted stop triggers at the open. That is the M39 hazard,
  watched rather than reasoned about.

Tuesday's session **will halt** when the split lands, until the anomaly is
declared in the Risk Console. That is M60 working, and it is the first live
exercise of it.

## ⚠️ Found 8 August, not yet fixed — M66

**The aggregate risk-at-stop that gates every new entry is measured against
ENTRY prices, not current ones.** The app reports 5.02%; measured against
current prices it is **5.87%**, against a 5.00% cap.

`PortfolioGovernor.snapshot` does `prices.get(symbol) or pos.avg_price`, and
`avg_price` is the broker's `avg_entry_price`. The `prices` argument is plumbed
through `snapshot`, `evaluate` and `delever_fraction` — and **nothing in the
trading path ever passes it.** `RiskEngine` and `DeleverSweep` both omit it;
only `adopted.py`, a display path, supplies it. So this is not a stood-down
artefact: every entry decision this system has ever made used entry prices.

**A winning book understates its risk**, because a position that has gained has
further to fall to its stop. The bias grows with profit and is backwards from
prudent.

It changes which trades happen and how large they are, so it is **inside the
freeze** and needs a recorded lift. **Do not deploy before Tuesday.**

**Designed, not built** —
`docs/superpowers/specs/2026-08-08-risk-at-stop-current-prices-design.md`. It is
smaller than it looks: **Alpaca's `Position.current_price` is the consolidated
tape** (10 of 10 matched SIP, 0 matched IEX), so the price is already in every
`positions()` response, free on this tier, and free of the IEX bias. One extra
fallback tier in `snapshot` plus an optional field on `Position`; no caller
changes.

An earlier version of this section said the fix was coupled to the market-data
decision. It is not.

Checked rather than assumed: `QAT_DELEVER_SWEEP_ENABLED=false`, so the stricter
figure cannot force a sale. With the sweep enabled it would have trimmed all ten
positions on deploy.

Verify with `scripts/analysis/verify_gating_figures.py`.

## M65 — found and FIXED 8 August, not yet deployed

The entry record held the price we asked for, not the price we paid: 8 of 10
positions differed, AMD by 141 bps, and `restore_open_lots` used it as the lot's
cost basis — so P&L and every R-multiple denominator were wrong by that drift.

**Fixed** by `SignalToOrderBridge.reconcile_entry_prices()`, which asks the
broker at startup, *before* the ledger is rebuilt. It heals the eight records
already on disk. A quarantined position is never corrected, because a split
changes `avg_entry_price` legitimately.

**⚠️ The first launch of a build containing this rewrites
`open_position_entries.json` for eight positions. Back that file up first**, as
`closed_trades.csv` was before the CVS correction.

Not deployed. See ROADMAP M65 for what it does *not* fix — `_announce_fill`
still publishes the reference price at `transmitted`, so a lot created live
inside a session carries it until the next startup.

## Where things stand

- **Deployed:** `M63+M62 (49482c2)`, hash-verified, **launched and confirmed
  running** on 8 August, and alive through a full reconciliation poll cycle with
  no false positives.
- **Repo:** clean, pushed. `git log --oneline -1` gives the tip; the handoff commit is always at or near it.
- **HEAD IS WELL AHEAD OF THE DEPLOYED BUILD IN `src/`, and that is real.**
  `git diff 49482c2..HEAD -- src/` covers M64, M65, M67, M68 and M69 — the
  Regime Monitor, the entry-price reconciliation, both halves of the Risk
  Console, and the walk-forward caveat.
  All presentation or record-correction; **none of it changes a trading
  decision, and Monday needs none of it.** Do not deploy before the split test.
- **Account:** equity ~$101,245. Ten positions — AMAT 7, AMD 7, CRWD 16, CSCO 44,
  GS 7, JNJ 19, MS 41, UNP 17, VRTX 19, WFC 58 — all protected, all carrying a
  stop resting at the broker. Risk-at-stop 5.02% against a 5.00% cap, so the book
  is refusing new entries. That is the rails working.
- **Closed trades: one.** CVS, −$482.18, −1.68R.
- **1,561 tests**; ruff, black, mypy, bandit clean.

## What landed on 8 August

| | |
|---|---|
| **M59** | A protective stop whose **level** moved was invisible. `verify_position_stops` compared presence, so a stop still resting at a different price passed. `_position_stops` is the denominator of every risk-at-stop figure, and the book sits at 5.02% against a 5.00% cap — a wrong denominator on one symbol refuses entries in every other |
| **M60** | The position-anomaly seam. Reconciliation can be told a difference is explained; a position can be quarantined from the write path. Serves M39 and M43 both |
| **M61** | Deliberate machinery testing, as a posture. M54 exercised against a real broker failure for the first time since it shipped; `entry_allow_list` added |
| **M62** | A broker JSON payload fragmented one cause into 113 report rows. Guard plus a row cap |
| **M63** | Dashboard balances: two groups, level-aware |
| **M64** | Regime Monitor: says which strategies the regime permits, and found a concurrency race doing it |
| **M65** | The entry record held the price we asked, not the price we paid. **Found and fixed** |
| **M66** | The risk cap that gates every entry uses ENTRY prices. **Found, designed, not built** |
| **M67** | The Risk Console now answers "why was I refused", closing a forward reference M64 created hours earlier |
| **M68** | Its correlation table was measuring intraday ticks where the rail measures 60 daily bars |
| **M69** | Walk-forward stated no caveat, on the screen that holds the deploy gate |

## The reframing that changed how we work

**Recorded because it reverses a previously implicit priority.** The trial has
been trying to do two jobs that conflict:

* **Collect edge evidence** — wants a frozen configuration and natural trades.
* **Validate the machinery** — wants edge cases *provoked*, because they do not
  occur naturally in a book of ten megacaps.

ROADMAP's *"Where this is ultimately going"* already settles which matters: the
edge numbers will not transfer to the ASX and must be re-earned; **the machinery
is what transfers.** On a paper account with no money at risk, protecting the
edge baseline at the cost of not testing the machinery optimises the output that
gets discarded.

So rules may be varied to make a test possible, and the variation is then judged
on its merits. **What still constrains us is the record, not money** — a later
reader must be able to tell a real defect from a test artifact.

M39, M43, M44 and M54 were all blocked on "wait for an event that may never
come". M54 is now done. MNST is M39's.

## What the measurements found

**Alpaca's split representation, measured 8 August** (`scripts/analysis/probe_alpaca_splits.py`):
forward split is `old_rate=1.0, new_rate=4.0`, ratio `new/old`; reverse inverts.
Records carry `ex_date`, `record_date`, `payable_date`, `target_symbol`. The
request takes a **server-side `symbol` filter**. Two traps: `target_symbol` is
absent on ~10% of records, and `payable_date` can precede `ex_date` — key on
`ex_date`.

**CRWD is why automatic detection was deferred.** It split 4-for-1 on 2 July; we
bought on 31 July, post-split, and the position is correct. But a detector
matching symbol and ratio over a recent window would call our 16 shares
split-explained **today**, and be wrong. The false positive is in the book. Any
detector must gate on `ex_date` falling after the position was opened.

**`TradingClient` wraps no account-activities method** in alpaca-py 0.43.5. The
REST endpoint answers directly.

**Halts are not detectable through the REST API.** `get_asset()` reports
`status=active, tradable=True` even for a halted symbol — that is *listing*
status. The real feed is `subscribe_trading_statuses` on `StockDataStream`, **a
websocket this application does not consume.** So **M43 is now gated on the
market-data decision**, which until now was only M32's problem.

## The next block of work

### Immediate — the MNST test

Monday and Tuesday. See `docs/MNST_SPLIT_TEST.md`. Nothing else should be
started that requires deploying a build before Tuesday.

### Group 1 — external changes to a held position

**M60 built the shared half and it is deployed.** What remains:

* **M39 detection and adjustment**, which waits on Tuesday's captures. The
  adjustment is where the four-way atomicity risk lives — tracked quantity,
  entry record, resting protection, ledger basis. **A partial adjustment is
  worse than none**; M60's quarantine is what gives it somewhere safe to fail.
* **M43 halts** — needs its own producer, and that producer needs a websocket.
  See above. Sequence it with the market-data decision.

### The market-data question — measured 8 August, see `docs/MARKET_DATA_FINDINGS.md`

**Two things stated earlier in this document's life were wrong, and are
corrected there.** This system does *not* run on yfinance — it runs on Alpaca
IEX. And M43 and M32 are *not* both gated on one market-data decision; only M43
touches it, and M32 is an IBKR question because Alpaca cannot reach the ASX
under any subscription.

The finding that matters: **IEX sees a median 4.3% of consolidated volume and a
3.5% narrower daily range, and daily bars are requested on the same feed as live
ticks.** ATR is therefore ~3.9% understated, and since ATR sets the stop distance
which sets the share count, **every position is a median 4% larger than intended
— 16% on CSCO.** Per-trade risk is internally consistent; the stops are simply
too tight for the real volatility, so they are hit more often than the design
assumes. For a trial measuring whether swing has an edge, that is a systematic
bias produced by the feed rather than the strategy.

SIP *historical* data is free on this account. The fix is to request daily bars
on `sip` while leaving live ticks on `iex`. **It is inside the freeze** — it
changes position size — and it resets the two-week baseline. **Decide it after
Tuesday, not before**; nothing should change sizing between now and the split
measurement.

### Group 4 — the interface

Steps 1–3 done. **Step 4 (Dashboard), 4.5 (Workbench walk-forward caveat), 4.6
(Regime Monitor) and 4.7 (Risk Console, both halves) now done.** Remaining:
Screener (§4.8), the rest of the Workbench, AI Advisor (§4.9 calls that one "the
simplest screen, and fine"). **Order Blotter deliberately last** — most
safety-critical, and should be touched when the design system is proven.
**Performance (step 5) waits for September.**

**One known gap left open in M69:** the **Monte Carlo cone** has the same defect
as the walk-forward panel — ROADMAP says it "resamples near-buy-and-holds" for
the same reason — and it still states no caveat. Same screen, same fix, not
done.

**The brief has now been wrong in detail three times** — M63 on the Balances
premise ("most of them dashes"; ten of eleven report a figure), M64 on the macro
panel, M67 on the level. Read §4.x as a statement of intent and check its
particulars against the code and the account before implementing them.

Two things the last two screens established, worth carrying:

* **Three settings must produce three outcomes.** The Balances design reached
  review rendering Guided and Standard identically, because `explains()` is true
  for both. That is M58a in miniature. `prefers_density()` now exists, and
  `shows_advanced()` finally has consumers.
* **Render it, do not trust the suite.** Screenshotting found an orphaned grid
  row and an off-scale font that every test passed through.

### Group 2 — waits for September

M44 (is the flat 5bps slippage assumption right — `entry_slippage` answers it)
and M51's analysis half. Nothing to do until there are closed trades.

### Group 3 — M32 ASX

The destination, and much the largest. Behind the market-data decision.

## Standing constraints

- **Read `%LOCALAPPDATA%\QuantAdvisoryTerminal` via PowerShell, never Bash.**
- Operator's terminal is **PowerShell 5.1** — `;` not `&&`, `@'...'@`
  here-strings with the closing `'@` at column 0.
- **The project formats with `black`, not `ruff format`.** `invoke lint` shells
  out to a ruff that is not on PATH — run the four via the venv python:
  `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets
  `QAT_DATA_DIR` session-wide, and the anomaly store persists there — one
  declared anomaly would leak a quarantine into every later test.
- **A deploy needs the app closed** and uses `Expand-Archive -Force` over
  `C:\QuantAdvisoryTerminal`; renaming the install directory is blocked by
  policy. The zip is made by hand. Verify by hash, then **launch it** and confirm
  the startup lines.
- **Convention:** plan → approval → implement → verify → commit → build. Build
  and sign freely; **always ask before deploying**, then pre-flight in daylight.
- **Validation freeze:** nothing lands that changes which trades happen or how
  large they are. Lifted deliberately for M56c, M57 and M58b, each recorded with
  its reason. M59–M64 are all fix-immediately, reporting or presentation.

## The habits that found everything

**Check the brief against reality.** The Dashboard brief said the Balances panel
was "most of them dashes"; the live account reports ten of eleven. The
prescribed fix would have collapsed one cell and achieved nothing.

**A failing test is not automatically a bad fixture.** M64's race surfaced as one
failure in eighteen and looked exactly like a test that forgot to drive an
engine. It was `asyncio.gather` dispatching handlers concurrently.

**Verify a fix is needed before making it.** The report narrative had failed
every day for a week — and M56b had already fixed it. Today's code over 6 August's
rows gives 3 keys where the report written that day had 113.

**Ask what reads it.** `shows_advanced()` had zero consumers from M45 until
8 August. The minimum hold, the expertise level and the M37 diagnostics were all
the same pattern: configuration that persists, displays, and changes nothing.

---

## Prompt to paste

```
Continuing work on QAT (Quant Advisory Terminal) at C:\Claude Programming.
Paper account throughout — no real money is involved.

Read docs/HANDOFF.md first, then docs/MNST_SPLIT_TEST.md, then the standing
rule at the top of ROADMAP.md and the section "How Alpaca actually represents
orders".

STATE
Deployed build M63+M62 (49482c2), verified by hash and confirmed to start.
Repo clean and pushed - `git log --oneline -1` for the tip.

  HEAD IS WELL AHEAD OF THE DEPLOYED BUILD IN src/, and unlike earlier handoffs
  that is a real difference, not documentation. `git diff 49482c2..HEAD -- src/`
  covers M64, M65, M67 and M68 - the Regime Monitor, the entry-price
  reconciliation, and both halves of the Risk Console. All presentation or
  record-correction; NONE of it changes a trading decision, and MONDAY NEEDS
  NONE OF IT. Do not deploy before the split test.

Equity ~$101,245, ten positions — AMAT, AMD, CRWD, CSCO, GS, JNJ, MS, UNP,
VRTX, WFC — all protected. One closed trade (CVS, −$482, −1.68R). 1,556 tests
pass; ruff, black, mypy, bandit clean.

THE THING WITH A CLOCK
MNST splits 2-for-1, ex-date Tuesday 11 August, and a buy for 8 shares is
QUEUED at Alpaca for Monday's open. It is the first deliberate machinery test
this project has run, and it exists for one measurement that cannot be
reasoned about: what Alpaca does to a held quantity and to a resting stop
through a split. M39's adjustment cannot be designed without it.

  THE PROCEDURE IS docs/MNST_SPLIT_TEST.md. It is standalone and printed.
  Follow that, not a reconstruction of it.

  Three things from it that must not be lost:
   - The app must NOT be running when the order fills. It does not track MNST,
     will not absorb the fill, and the first reconciliation poll reads it as an
     unexplained divergence and HALTS THE SESSION. Start the app ~15 minutes
     after the open.
   - The stop is placed on Monday as a separate sell order, not attached to
     the buy. Alpaca refuses a stop below market on a BUY.
   - Expect the position to be liquidated on Tuesday. Post-split MNST is near
     $45.43 and the stop rests at $72.68, above the market. That is the M39
     hazard and it is the RESULT, not a failure.

  Tuesday's session will halt when the split lands until the anomaly is
  declared in the Risk Console. That is M60 working, and its first live run.

FOUND 8 AUGUST, NOT YET FIXED — M66, the more serious of the two
The aggregate risk-at-stop that GATES EVERY NEW ENTRY is measured against ENTRY
prices, not current ones. The app reports 5.02%; against current prices it is
5.87%, on a 5.00% cap.

  PortfolioGovernor.snapshot does `prices.get(symbol) or pos.avg_price`, and
  avg_price is the broker's avg_entry_price. The `prices` argument is plumbed
  through snapshot, evaluate and delever_fraction and NOTHING IN THE TRADING
  PATH EVER PASSES IT - RiskEngine and DeleverSweep both omit it, and only
  adopted.py (a display) supplies it. Not a stood-down artefact: every entry
  decision this system has made used entry prices.

  A WINNING BOOK UNDERSTATES ITS RISK, because a position that has gained has
  further to fall to its stop. The bias grows with profit, backwards from
  prudent. Same pattern as shows_advanced() before M63: a parameter plumbed
  everywhere and supplied by nothing.

  Inside the freeze - it changes which trades happen and how large. Interacts
  with the market-data finding: whichever prices get passed should come from
  the same feed decision or the fix bakes in the IEX bias. NOT BEFORE TUESDAY.
  Verify with scripts/analysis/verify_gating_figures.py.

M65 — FOUND AND FIXED 8 AUGUST, NOT DEPLOYED
Fixed by SignalToOrderBridge.reconcile_entry_prices(), which asks the broker at
startup BEFORE restore_open_lots rebuilds the ledger, and heals the eight
records already on disk. Quarantined positions are never corrected, because a
split changes avg_entry_price legitimately.

  THE FIRST LAUNCH OF A BUILD CONTAINING THIS REWRITES
  open_position_entries.json FOR EIGHT POSITIONS. Back that file up first, as
  closed_trades.csv was before the CVS correction.

  What it does NOT fix: _announce_fill still publishes the reference price at
  "transmitted", so a lot created live inside a session carries it until the
  next startup reconciles. See ROADMAP M65.

  What it was: _announce_fill publishes when status is "filled" OR
  "transmitted" and takes filled_price or reference_price. At transmit there is
  no fill price, so it published the REFERENCE, and _on_fill stored it with
  setdefault so the real fill could never replace it. 8 of 10 positions
  differed, AMD by 141 bps. restore_open_lots uses entry.price as the lot's
  cost basis, so P&L and the R-MULTIPLE DENOMINATOR were both wrong by that
  drift - AMD's true risk per share is 7.3% larger than recorded - and both
  feed the promotion gate and the September burst.

  Invisible because CVS, the only closed trade, drifted 1.4 bps and is right by
  luck. "A defect that corrupts the record is worse than one that stops the
  session."

WHAT LANDED 8 AUGUST
  M59  a protective stop whose LEVEL moved was invisible
  M60  the position-anomaly seam — reconciliation can be told a difference is
       explained, and a position quarantined from the write path
  M61  deliberate machinery testing as a posture; M54 exercised against a real
       broker failure at last; entry_allow_list added
  M62  a broker JSON payload fragmented one cause into 113 report rows
  M63  Dashboard balances, two groups, level-aware
  M64  Regime Monitor says which strategies the regime permits — and found an
       asyncio.gather race doing it
  M65  the entry record held the price we ASKED, not the price we PAID — found
       and FIXED, and it heals the eight wrong records already on disk
  M66  the risk cap gating every entry uses ENTRY prices — found and DESIGNED,
       not built, because it is inside the freeze
  M67  the Risk Console now answers "why was I refused", closing a forward
       reference M64 created hours earlier
  M68  its correlation table measured intraday ticks where the rail measures 60
       daily bars, so a binding pair could not appear on it at all
  M69  the walk-forward panel stated no caveat, on the screen that holds the
       DEPLOY GATE - slicing manufactures an entry per window, so for a
       continuously-held strategy the figures describe the slicing. The Monte
       Carlo cone has the same gap and is NOT yet done

THE REFRAMING THAT CHANGED HOW WE WORK
The trial does two conflicting jobs: collect edge evidence (wants a frozen
configuration) and validate machinery (wants edge cases provoked). ROADMAP
already settles which matters — the edge numbers will not transfer to the ASX
and must be re-earned; the machinery is what transfers. So on a paper account
rules MAY be varied to make a test possible, and the variation judged on its
merits afterwards. What still constrains us is THE RECORD, not money: a later
reader must be able to tell a real defect from a test artifact.

WHAT IS BLOCKED ON WHAT
  M39 detection/adjustment  — Tuesday's captures
  M43 halts                 — needs a WEBSOCKET consumer. get_asset() reports
                              status=active even for a halted symbol, because
                              that is LISTING status; halts live on
                              subscribe_trading_statuses on StockDataStream,
                              which this app does not consume. It polls, for a
                              documented reason that holds for prices and not
                              for events.
  M44, M51 analysis half    — September closed trades
  M32 ASX                   — an IBKR question. Alpaca cannot reach the ASX
                              under ANY subscription, so no Alpaca decision
                              advances it.

MARKET DATA — MEASURED, see docs/MARKET_DATA_FINDINGS.md
This app runs on ALPACA IEX, not yfinance (an earlier handoff said otherwise
and was wrong). Free tier: real-time is IEX only, but SIP HISTORICAL is free.

  IEX sees a median 4.3% of consolidated volume and a 3.5% narrower daily
  range. Daily bars are requested on the SAME feed as live ticks, so ATR is
  ~3.9% understated - and ATR sets the stop distance, which sets the share
  count. EVERY POSITION IS A MEDIAN 4% LARGER THAN INTENDED, 16% on CSCO.

  Not a per-trade risk breach - the arithmetic is internally consistent. The
  stops are too TIGHT for the real volatility, so they are hit more often than
  the design assumes. For a trial measuring edge, that is a bias produced by
  the feed rather than by the strategy, and September would carry it.

  The fix is free: request daily bars on `sip`, leave live ticks on `iex`. But
  it CHANGES POSITION SIZE, so it is inside the freeze and resets the two-week
  baseline. DECIDE IT AFTER TUESDAY - nothing should change sizing between now
  and the split measurement.

GROUP 4, THE INTERFACE — steps 1-3, 4 and 4.6 done
Remaining: Screener, Strategy Workbench, AI Advisor. Order Blotter
deliberately LAST (most safety-critical). Performance waits for September.
Two rules the last two screens established: three settings must produce three
outcomes (the Balances design reached review rendering Guided and Standard
identically — M58a in miniature), and RENDER IT rather than trusting the suite
(screenshotting found an orphaned grid row and an off-scale font that every
test passed through).

CONSTRAINTS
  Read %LOCALAPPDATA%\QuantAdvisoryTerminal via PowerShell ONLY, never Bash.
  PowerShell 5.1 — use ; not && and @'...'@ here-strings, closing '@ at col 0.
  Formats with black, not ruff format. Run ruff check ., black --check .,
  mypy src, bandit -r src via the venv python — `invoke lint` uses a ruff that
  is not on PATH.
  EVERY TEST THAT BUILDS AN OMS MUST PASS ITS OWN data_dir — conftest sets
  QAT_DATA_DIR session-wide and the anomaly store persists there, so one
  declared anomaly leaks a quarantine into every later test.
  A deploy needs the app closed, uses Expand-Archive -Force, is verified by
  hash and THEN LAUNCHED. A hash proves the right bytes landed, never that
  they run — M56a passed its hash check and could not start.
  Plan → approval → implement → verify → commit → build. Build and sign
  freely; ALWAYS ask before deploying, then pre-flight in daylight.

AT THE OPEN — the startup lines that must appear
  Build: M63+M62 (49482c2, ...)
  Broker-fill watermark restored to ...
  Restored 1 closed trade(s) from closed_trades.csv
  Restored N open lot(s) to the trade ledger
  Adopted N ... N carries a stop resting at the broker
  REGIME ... shortly after the engine starts
Their ABSENCE is the signal, not their content. On the MNST nights adoption
should read ELEVEN, not ten.

  & "C:\Claude Programming\.venv\Scripts\python.exe" "C:\Claude Programming\scripts\watch_session.py"

EXPECT A QUIET SESSION
Risk-at-stop is 5.02% against a 5.00% cap and the ten-position limit is full,
so few or no new entries will be permitted — that is the rails working. A log
that goes quiet is indistinguishable from an app that has died, so check that
equity_curve.csv is still growing before concluding "nothing happened". The
M56a crash produced exactly that signature.

THE HABITS THAT FOUND EVERYTHING
Check the brief against reality — the Dashboard brief said the Balances panel
was "most of them dashes"; the account reports ten of eleven, and the
prescribed fix would have achieved nothing. A failing test is not
automatically a bad fixture — M64's race surfaced as one failure in eighteen
and looked exactly like a test that forgot to drive an engine. Verify a fix is
NEEDED before making it — the report narrative had failed daily for a week and
M56b had already fixed it. And ask what reads it: shows_advanced() had zero
consumers from M45 until 8 August, which is the same pattern as the minimum
hold, the expertise level and the M37 diagnostics.
```
