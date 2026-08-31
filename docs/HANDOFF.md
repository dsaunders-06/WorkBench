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
| Deployed build | **M158 (`16ce8e6`)**, installed 31 August 09:28, SHA256 `6FEBA4B6…300C`, signature Valid on the installed copy. Rollback: `C:\QuantAdvisoryTerminal.bak-0167399-20260831-0928` (contains M157). ✅ **READ BACK 09:29**, thirty minutes before the bell — `Build: M158`, 95 symbols warm-started, ten positions adopted 10/10 with stops, 20 legs clean, ten lots restored, `Excursion backfilled ... 10 of 10`, **zero ERROR/CRITICAL**. ⚠️ **No absence line, correctly** — nothing had printed, and the design stays silent rather than reporting "94 of 94 absent". Carries item 33 (M158) and item 44's both halves (M157). Previous: M157, M156, M155, M154, M153, M152, M151, M150 |
| Repository HEAD | **Level with the deployed build.** `handoff_state.py` derives the gap; do not read a number from here |
| Deploy gap | **ZERO.** `DEPLOYED` reads `16ce8e6` and so does HEAD, recorded by the script only after the installed copy verified |
| Pushed | ✅ **LEVEL with `origin` at `0167399`.** The 27 August hold was lifted on 30 August and 74 commits went up in ONE push. ⚠️ **CI is STILL at the billing wall** — that push's run died in 2s with zero steps, *"the job was not started because recent account payments have failed or your spending limit needs to be increased"*. **The allowance resets ~1 September.** Until then a push backs work up, costs no Actions minutes (a job that never starts bills nothing) and emails a failure while verifying nothing. After the reset, batch pushes: one push is one run, ~8.6 minutes of 2,000 at `windows-latest`'s 2× multiplier |
| Suite | **2,977 passed, 26 skipped** (3,003 collected). ruff, black, mypy src, bandit clean |
| Watchlist | **94 ASX megacaps + STW.AX** |
| Entry allow list | **CLEARED** — all 94 enterable |
| Account | **TEN POSITIONS, all bracketed, 20 resting legs** — A2M ANZ ASX BOQ IAG PNI SEK SUN TNE WOW (read from `open_position_entries.json`, 28 August 21:40). **RHC.AX exited 27 August at TARGET, +5,736.57 net, 2.47R.** ⚠️ **AN ENTRY CANNOT HAPPEN AT TEN** — `governor.py:304` refuses at `>=`, so ten of ten is AT the cap and the book needs NINE. On 28 August that cost 1,036 refusals and zero approvals across six symbols, and it is why items 56 and 58 remain unexercised |
| Kill switch | ✅ **CLEAR** — `{"tripped": false, "reason": null}`, and `resting_order_anomalies.json` is `{"anomalies": []}` with no quarantines outstanding. **The next session opens with order flow LIVE and autonomous execution enabled.** The Risk Console button is trustworthy (item 57, confirmed on the click that fixed it) and the switch persists across restarts (item 32) |
| Ledgers | **6 closed trades** — five LOV.AX and one RHC.AX. ⚠️ **One LOV row is a REPAIR row with EMPTY costs**, so net P&L across LOV is **NOT summable from that file**; IBKR's commission on the unabsorbed portion was not knowable after the fact and its `exit_reason` says so. ⚠️ **All six carry an EMPTY `entry_slippage`** — see item 44: the field was never persisted, and M156 fixes that only for trades opened FROM NOW |

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

## ⚠️ MEASURED 30 AUGUST 22:35, SO MONDAY IS A COMPARISON NOT A GUESS

Read only, against the live Gateway, computed with the app's **own**
`PortfolioGovernor.snapshot` and with LIVE prices (the M66 tier) — not a
reimplementation. Measuring a rail with a different instrument than the rail
uses is how 8 August read 5.02% against a true 5.87%.

    equity            1,013,822.81
    gross exposure      600,514.62
    risk at stop         42,226.45     4.165%   cap 5.000%
    headroom              8,464.69     -> WITHIN CAP
    positions                    10    stops found 10

    TNE 0.617%  SEK 0.590%  A2M 0.589%  ASX 0.537%  BOQ 0.482%
    SUN 0.390%  IAG 0.377%  PNI 0.296%  WOW 0.193%  ANZ 0.093%

⚠️ **THE AGGREGATE CAP IS NOT BREACHED, and the standing note said it was.**
That claim was true on 20 August at 5.01% and has been repeated since. Tonight it
is 4.165%. **The only gate actually shut is the POSITION COUNT** —
`governor.py:304` refuses at `>=`, so ten of ten is AT the cap and the book needs
NINE. `session_check.ps1`'s "expected, not a fault" note has been corrected: it
never measured the cap it was asserting.

**What that changes for Monday:** if an exit takes the book to nine, an entry is
possible *and* there is budget for it — 8,464 of headroom, roughly one position's
worth at the ~0.5% each these run at. Previously the note implied both gates were
shut.

⚠️ **AND THE COUNTERINTUITIVE PART, which is worth holding in mind at the bell.**
Risk-at-stop is `(price − stop) × qty`, so **a RALLY raises it** — a position that
has gained has further to fall. Headroom is 8,464 against 600,514 of gross, so a
move of roughly **+1.4% across the book breaches the 5% cap**, at which point the
aggregate rail starts refusing regardless of the position count. A fall does the
opposite. So "we have headroom" is a statement about today's prices only.

**Item 31's baseline, unchanged from 28 August:** 20 resting legs, **10
PreSubmitted and 10 Submitted, ZERO in either state item 31 added**. So it is
still a no-op against this book. If Monday shows orders in the added states,
item 31 has become live and its loosened rail is being exercised for the first
time — that is the moment to read it.

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

## ⚠️ 26 AUGUST: THE FIRST EXIT THIS SYSTEM EVER MADE, AND THE 88% THAT NEVER REACHED THE LEDGER

**Read this before touching the absorb path.** Live, on M145, market open.
Everything below is MEASURED — from the log, the ledger files, and a read-only
IBKR probe on clientId 99 taken at 10:20.

### What happened, to the second

| Time (AEST) | Event |
|---|---|
| 10:06:31 | First execution on LOV.AX order permId `1216552509` (orderId 147, clientId 1) — the **take-profit** leg |
| 10:06:31–10:08:30 | **183 separate executions**, summing to exactly **3,217 shares** at 28.45. Final `cumQty` 3,217 — the entire position |
| 10:08:30 | `Error 202, reqId 148: Order Canceled` ×2 — IBKR's OCA cancelling the sibling stop leg. **Not a fault** |
| 10:09:42 | Absorb pass ran. Booked **4 fills** (deltas 10, 15, 26, 323 = cumulative **374**) and stopped |
| 10:09:42 | `Broker reconciliation mismatch: LOV.AX tracked=2843 broker=0` |
| 10:09:42 | `KILL-SWITCH TRIPPED: Broker reconciliation mismatch. All new order flow is halted.` |
| 10:09:42 | `RESTING ORDER SCAN: 18 working leg(s) across 9 symbol(s)` — was 20 across 10, so LOV's two legs are correctly gone |
| 10:14:42 | Next poll: **absorbed nothing**, same mismatch, still 4 ledger rows |

**The kill switch was RIGHT.** `tracked=2843 broker=0` is a real disagreement,
and the halt is the only thing preventing the app managing a position it does
not hold. Leave it tripped.

### ✅ The good half — and it is genuinely good

**This is the first exit in this system's life**, and it was a winner.
`closed_trades.csv` went 0 rows → 4:

| qty | entry | exit | net P&L | r_multiple |
|---|---|---|---|---|
| 10 | 24.2214 | 28.45 | +35.21 | 1.53 |
| 15 | 24.2214 | 28.45 | +56.11 | 1.63 |
| 26 | 24.2214 | 28.45 | +102.10 | 1.71 |
| 323 | 24.2214 | 28.45 | +1,342.36 | 1.81 |

**+1,535.78 AUD net**, `exit_reason: target`, ~+17%. And the arithmetic is
sound: `closed_at` (10:06:31…) is AFTER `opened_at` (25 Aug 10:28:52),
`holding_days` 0.984. **No repeat of the 24 August impossible-trades bug.**

### ⚠️ The defect: 179 of 183 executions never reached the ledger

The app booked cumulative 374 and believes it still holds **2,843 phantom
shares**. At roughly $4.23/share that is about **$12,000 of realised gain
absent from `closed_trades.csv`**. NetLiquidation is unaffected — the broker is
the truth — but the RECORD is wrong, and the promotion gate reads the record.

`absorbed_fills.json` holds, for that order:

    "1216552509": {"filled_at": "2026-08-26T10:06:56+10:00",
                   "quantity": 374.0, "price": 28.45, "quantity_known": true}

with the watermark advanced to `10:09:42`.

**This is NOT a timing race, and that was checked rather than assumed.** The
last execution landed at 10:08:30; the absorb ran at 10:09:42, seventy-two
seconds later. Every one of the 183 executions existed and was queryable when
the app looked — the probe retrieved all of them afterwards from the same
Gateway.

**Ruled out by reading the code, not by guessing:**
* `IBAdapter.recent_fills` does not truncate or aggregate. It returns
  everything `reqExecutions(ExecutionFilter())` gives, filtered only by
  `fill.filled_at <= since` and by symbol.
* The query floor is not the cause. `_fill_query_floor` (M53) deliberately
  reaches back past every remembered fill, and the prior watermark was
  25 Aug 12:27:22 UTC — all 183 executions are well above it.
* Partial fills are a DESIGNED-FOR case, not an unhandled one. The deltas
  10/15/26/323 are exactly M53's cumulative-quantity arithmetic working. It
  simply stopped after four.

**⚠️ NOT ESTABLISHED at the time of writing: which layer dropped the other 179.
FOUND AND PROVEN at 13:10 the same day - see the section immediately below.**
It was recorded as unknown rather than guessed at — this project has spent a day on findings written from
call sites while the recorded data held the answer. The next step is to
instrument the absorb pass and count what `recent_fills` actually RETURNS for
LOV.AX versus what `_is_foreign_unrecorded` accepts. The evidence needed is a
count at each boundary, not another reading of the code.

### ✅ ROOT CAUSE FOUND AND PROVEN — 26 August, 13:10. A units mismatch at the Alpaca→IBKR boundary.

**`BrokerFill.quantity` means CUMULATIVE to the OMS and PER-EXECUTION from IBKR.**

`oms.py:1394`, deciding whether anything new has executed:

    return fill.quantity > prior.quantity + 1e-9

and its own comment states the contract: *"an order that is still filling
reports the SAME id with a larger **filled_qty**"*. `filled_qty` is **Alpaca's**
field, and Alpaca returns ONE order object per order carrying a **cumulative**
quantity. The design is correct for Alpaca.

`ib_translate.py:363` supplies the other side:

    quantity=float(execution.shares),

IBKR does not return one object per order. It returns **one `Fill` per
execution**, each carrying that execution's OWN `shares`. So the OMS compares a
per-execution count against a stored cumulative.

**The consequence, stated exactly:** only an execution whose own share count
sets a NEW RUNNING MAXIMUM is ever absorbed, and the total absorbed therefore
equals **the largest single execution**. Everything else is silently discarded
as "already seen".

**PROVEN by replaying the real executions through the real translation
function** (read-only, clientId 99, nothing written):

    executions returned for LOV.AX order 1216552509: 183
    sum of BrokerFill.quantity        : 3,217
    largest single BrokerFill.quantity:   374

    what the CURRENT code absorbs:
       delta      10   stored      10   00:06:31
       delta      15   stored      25   00:06:44
       delta      26   stored      51   00:06:45
       delta     323   stored     374   00:06:56

    TOTAL ABSORBED  :   374
    ACTUALLY FILLED : 3,217
    LOST            : 2,843

Those are the live deltas — 10, 15, 26, 323 — and the live tracked remainder of
2,843, reproduced offline from the broker's own records. Not a hypothesis.

**This is M104's shape again: the boundary that was missed when the broker
changed.** Every layer is individually correct. `from_ib_fill` faithfully
reports what one execution did; `_is_foreign_unrecorded` correctly implements
cumulative-delta arithmetic. They disagree about what the number MEANS, and
nothing typed or asserted the contract.

⚠️ **It is not LOV-specific and it is not rare.** It fires on any order that
fills in more than one execution where a later execution is smaller than an
earlier one — which is ordinary for a large ASX order. The four entries that
DID reach the ledger are the four ascending executions; the 179 that did not
are simply the ones that happened to be smaller.

**Why no test caught it:** every fixture in the suite fills an order in ONE
execution, so per-execution and cumulative are the same number and the two
readings of `quantity` are indistinguishable. The first order to fill in 183
pieces was the first to tell them apart.

### The fix is NOT a one-liner, and here is the trap

The obvious change is `quantity=float(execution.cumQty)` — IBKR supplies
`cumQty` and it is exactly the "filled_qty" the OMS comment means. Measured on
this order it runs 10, 35, 39 … 3,217 monotonically, so the delta arithmetic
would then be correct and would recover all 3,217.

⚠️ **But it would produce up to 183 rows in `closed_trades.csv` for one exit.**
Today's four rows are already four rows for one logical trade (see item 3's
note). One delta per execution makes that 183. The promotion gate counts closed
trades toward 20 and 30; at that rate a single exit clears the gate on its own,
which would make the gate meaningless.

So the fix wants BOTH halves, and shipping only the first would be worse than
the bug:
1. `from_ib_fill` carries the cumulative quantity, so no execution is lost; and
2. the absorb pass **groups by order id within a pass**, takes the max
   cumulative, and emits ONE fill event for the delta since the last pass — so
   one exit is one ledger row, whatever the broker's execution count.

That is a risk-path change to the only exit path this system has. It wants its
own plan, its own tests built on a MULTI-execution fixture, and a watched
session — not a quick patch while a position is open and the switch is tripped.

### The state this leaves, and why it is safe to leave

* **Kill switch TRIPPED** — no new order flow. ⚠️ And per item 32 it now
  PERSISTS across restarts, logging CRITICAL on restore. **A restart clears
  nothing** and would additionally replay a ~10-hour watermark window, which
  `_load_fill_state` itself warns is *"correct after a clean shutdown and
  SUSPECT after a crash"*.
* **Nine positions, eighteen legs, every one protected.** `4 unprot ... x0`.
* The phantom LOV long cannot be acted on while the halt stands.
* The mismatch will re-log every 300s. That is the rail working, not a
  deterioration.

**Do not reset the switch until the 2,843 is either absorbed or the ledger is
repaired deliberately.** Resetting it hands the app a position that does not
exist.

### What this answers on the outstanding list

Item 1 — *"the first fill, and everything behind it"* — is **partly answered**.
A broker-side protective exit did reach `closed_trades.csv` through
`absorb_broker_fills`, and the ledger arithmetic held. What it also shows is
that the path is correct for the first few executions of an order and loses the
rest, which no test covered because no test has ever had a 183-execution fill.

**And note the shape for the promotion gate (item 3):** one logical exit
produced FOUR ledger rows. The gate counts closed trades toward 20 and 30, so
partial fills inflate that count several-fold per exit. Twenty rows may be five
trades. That needs deciding before the gate is read.

## Minor, found while diagnosing the above

`scripts/ibkr_probe.py` **overwrites a dated spec file** — it wrote its output
into `docs/superpowers/specs/2026-08-19-ibkr-capability-measurement-raw.md`,
replacing the 19 August measurement with today's. Restored with
`git checkout --`. A dated measurement artefact should not be the default
output path of a tool that gets re-run; the probe should write to a new dated
file, or to the scratchpad.

## ⚠️ 31 AUGUST: THE PNI STOP-OUT — three findings from one row

**The first closed trade under M157**, and the first in this system's life to
carry `mae_r` and `mfe_r`. It immediately proved one thing and broke another.

    symbol PNI.AX  qty 2,973   entry 17.9258  stop 16.46  exit 15.56
    exit_reason stop   net_pnl -7,170.79   r_multiple -1.6455
    mae_r -0.633   mfe_r -0.087   worst_price 16.9979   best_price 17.7985

### ✅ M147's absorb fix CONFIRMED on a real multi-execution order

`verify_exit_on_the_wire.py`, same day:

    executions 9   shares summed 2,973   IBKR final cumQty 2,973
    ledger row qty 2973.0 exit_price 15.56   recorded - VWAP  -0.000000

**Nine executions, ONE ledger row, full quantity.** That is exactly the shape
that lost 179 of 183 executions on LOV. ⚠️ The tool says honestly that with ONE
price across all nine, a blended average and a single price are the same number,
so this cannot distinguish M147's cumulative-price half — that stays unproven.

### ⚠️ NEW DEFECT: `mae_r` UNDERSTATES, and it does so on the case M44 exists for

`worst_price` is **16.9979 — HIGHER than the exit price of 15.56.** MAE reports
the trade went 0.63R against; it realised **−1.6455R**.

**On a stop-out MAE cannot be less severe than the realised R.** That invariant
is violated, and nothing checks it.

**Root cause, read not guessed:** `_close_against_lots` never touches
`worst_price`/`best_price`. The excursion is updated only by `_on_price` from a
MarketDataEvent — so a broker-side stop filling at a price the app never sees as
a tick is invisible to it. Here the exit landed at 10:00:13, inside the blind
window, with the feed delivering nothing.

**The fix is small — fold the exit price into worst/best when closing a lot —
and the invariant is worth asserting in the same change:** for a losing trade,
`mae_r <= r_multiple`. Not done mid-session; this is the trade ledger.

⚠️ **This makes every `mae_r` M157 produces suspect in the same direction**, and
the direction is the dangerous one: it makes trades look like they went less
against than they did.

### ⚠️ A SECOND DATA POINT FOR M44's CENTRAL WORRY, and it agrees with the first

The stop was 16.46 and it filled at **15.56 — 0.90 through, −1.6455R on an
intended −1R.** M44's only previous observation was CVS at 1.68R. **Two
stop-outs, both about 1.6R.** If that is typical, every position is sized against
an understated downside, which is precisely what item 7 warns about. Two is not a
distribution, but two agreeing is worth more than one.

`entry_slippage` is empty and always will be on this row: PNI opened 25 August,
before M156 persisted `reference_price`.

### The book is now NINE

Entries become possible for the first time since 24 August. That unblocks
M158's gate (which a 10-of-10 book never reaches), item 56's numeric permId and
item 58's two-entries-in-one-cycle.

## ⚠️ 31 AUGUST: THE FIRST APP-TRANSMITTED ENTRY, AND THE FOUR THINGS IT BROKE

**The first entry this system has placed since 24 August**, and the first ever to
exercise item 56's identity bridge. The entry itself SUCCEEDED. Four defects
surfaced behind it, three of them new.

### ✅ What worked, measured from the broker

    10:30:07  Autonomy signed off order 9a8d... : buy 1097 JHX.AX
    10:30:06 - 10:30:51   17 executions, cumQty 1,097, ~41.91-41.93
    JHX 1,097 @ avgCost 41.9554
    JHX SELL LMT 1,097 @46.01  Submitted     oca=1031062661
    JHX SELL STP 1,097 @39.39  PreSubmitted  oca=1031062661

Signal → gate → sign-off → transmit → 17 executions → full fill → **bracket
placed and OCA-linked**. Ten positions, twenty legs, all protected.

**M65's entry-price correction fired:** `ENTRY PRICE CORRECTED: JHX.AX filled at
41.9185, announced at 41.9100 (+2.0 bps)`.

**M158's gate was EXERCISED and ALLOWED it.** Zero `no price at all this session`
refusals today — JHX had printed, so the gate let a legitimate entry through. ⚠️
**It has been seen to ALLOW, never yet to REFUSE.** Half a confirmation: it does
not false-positive; whether it actually blocks is still unproven live.

### ⚠️ DEFECT A — `_orders` key and the order's own id diverge (item 56)

    executor.py:127 retry_pending -> :147 _consider -> oms.py:964 get_order
    KeyError: '1031062661'

`oms.py:816-820`:

    self._orders[order_id] = filled            # the app's ORIGINAL id
    if filled.order_id:
        self._broker_order_ids.add(str(filled.order_id))   # the permId, into a SET

`place_order` returns an Order **re-identified with the broker's permId**
(`ib_adapter.py:342-344`). The OMS stores that object under its ORIGINAL key and
puts the permId only into `_broker_order_ids`. **`_orders` is never re-keyed**, so
`_orders["<uuid>"] = Order(order_id="1031062661")`.

`pending_orders()` iterates `.values()` and hands back that object; `_consider`
then calls `get_order(order.order_id)`, a KEY lookup, which raises.

⚠️ **The `try` wraps the WHOLE `for` loop**, so the sweep dies on the first such
order and **every remaining pending order is skipped**. Autonomous execution is
stalled, repeating every 60s. It does not touch resting protection.

**Fix wants both halves:** alias `_orders` under the new id as well as the old
(nothing holding the old id then breaks), AND move the `try` INSIDE the loop so
one bad order cannot starve the rest.

### ⚠️ DEFECT B — DIAGNOSED, DELIBERATELY NOT FIXED

**Root cause found, `oms.py:861`:**

    signed_qty = filled.quantity if filled.side == "buy" else -filled.quantity

`filled` is the ORDER the broker returned, and `.quantity` is the **order's
size**, not the amount executed. So the app records the full 1,097 the instant
the broker accepts, whatever has actually filled.

⚠️ **`Order` has NO executed-quantity field** — only `quantity` and
`filled_price`. Fixing this properly means adding one to the broker contract and
populating it in all three adapters, feeding the kill-switch rail.

**NOT DONE, and the reason is M147's:** *"the fix wants BOTH halves, and shipping
only the first would be worse than the bug."* A contract change across three
adapters, into the rail that halts trading, taken mid-session under time
pressure, is the combination this project keeps paying for.

**The shape it wants:** a divergence should be expected up to the unfilled
remainder of a working order for that symbol, and still trip beyond it. At
10:30:15 the gap was 719 and the working remainder was 719 — expected. With no
working order, a 719 gap must still halt. That keeps the rail's teeth.



    10:30:15  Broker reconciliation mismatch: JHX.AX tracked=1097 broker=378
    10:30:15  KILL-SWITCH TRIPPED

The fill ran **10:30:06 → 10:30:51**. The poll landed **9 seconds into a
45-second market order**: the app counted the whole order as committed while the
broker had filled 378 of 1,097.

**The switch was not wrong** — that is a real instantaneous disagreement — but it
is not a durable one, and **any market order that outlives the poll gap will do
this every time.** Reconciliation needs to know an order is still working before
calling the difference a mismatch.

### ⚠️ DEFECT C — the orphan scan double-counts OCA legs on a NEW position

    10:35:15  RESTING ORDER ORPHAN: JHX.AX SELL resting=2194 justified=1097 excess=1097
    10:35:15  RESTING ORDER QUARANTINE on JHX.AX: 1097 shares of resting sell the
              book does not justify (holds 1097)

**The message contradicts itself**: the book does not justify 1,097 of resting
sell, while holding 1,097. It is summing both OCA legs (1,097 + 1,097 = 2,194)
against one position.

⚠️ **ROOT CAUSE NOT ESTABLISHED, and it is recorded as unknown rather than
guessed.** The other nine positions have identical LMT+STP OCA-linked shapes and
reported `nothing unjustified` all morning, so the scan normally dedupes OCA
siblings. What is different about a position entered THIS session has not been
determined. Do not fix this from a call site — instrument it.

### ⚠️ DEFECT D — item 56's stated check FAILED: the transmit line still carries a UUID

    Order signed off and transmitted: order=9a8d057d6c9e44f399120bdecbf94bf2

Item 56's check is *"the transmit line carries a NUMERIC permId, not a UUID"*.
**It does not.** The permId is resolved LATER and reaches `_broker_order_ids` and
the Order object, never the transmit line. So item 56 is **not** confirmed — and
the same late resolution is what causes Defect A.

**Item 58 remains unexercised**: only one entry fired, so no two entries have
seen each other in one cycle.

## ✅ 31 AUGUST: M43 ANSWERED, AND A BIGGER FINDING BEHIND IT

**Measured at 10:59 AEST with the ASX in CONTINUOUS TRADING**, holding a
STREAMING delayed subscription (`marketDataType=3`) for twenty seconds, not a
snapshot:

    BHP.AX  last=66.515  bid=66.51  ask=66.52  high=66.74  low=66.18  open=66.68
            volume=495,809      halted=nan      delayedHalted=nan
    CBA.AX  last=159.31  bid=159.29   |   SUN.AX  last=18.705  bid=18.7

### ❌ M43 HAS NO FEED. Do not design detection against the flag.

**A full live quote arrives, and the halt fields are the ONLY ones that never
populate.** That removes the confound the 28 August measurement could not:
"nothing is arriving" is now excluded, because everything except `halted` is.

By item 5's own rule - *"if it stays `nan`, it does not, and M43 is M39's shape"*
- this is the answer. What remains is BEHAVIOURAL detection: a symbol that stops
ticking while its peers keep ticking. That is a heuristic, not a report, and it
collides with the staleness rail, which already treats a silent symbol as
excluded rather than halted.

### ⚠️ THE INSTRUMENT WAS LYING, and it nearly hid the result

`probe_halts.py` ended with an unconditional `print` reading *"The market is
SHUT"*. **It was never a session check.** Written on 28 August when the market
genuinely was shut, it printed unchanged at 10:57 on 31 August with the ASX
trading - and it is what made the first re-run look inconclusive.

Same shape as `session_check.ps1`'s "the aggregate cap is breached", corrected
the night before: **a statement true when written, surviving into a context where
it is false.** Both were caught by checking the claim against the world rather
than reading it. The line is now replaced by the measurement, and
`scripts/probe_halts_streaming.py` holds the streaming test so a snapshot is
never mistaken for the feed again.

### ✅ THE BIGGER FINDING: IBKR's DELAYED FEED STREAMS A FULL ASX QUOTE

`last`, `bid`, `ask`, `high`, `low`, `open`, `volume` - live, streaming, on the
paper account, with **no market-data subscription**.

⚠️ **This changes what item 33's "deeper fix" is worth.** That item says: *"The
deeper fix is a feed that is not 20 minutes late at all. IBKR is already
connected, already authenticated, and already serving positions and orders - it
is the obvious candidate, and the reason yfinance is still the price source is
history rather than a decision."*

**That is now MEASURED rather than assumed.** The app runs on yfinance: ~20
minutes late, polled every 60s, structurally blind from the bell to ~10:21 - a
blind window observed again this morning, with M119 backing off at 10:04:28 and
recovering at 10:20:37. IBKR was streaming a live quote the whole time.

⚠️ **NOT a decision, and deliberately not made here.** What is established is
that the candidate feed exists and delivers. What is NOT established: its true
delay, its coverage across all 94 symbols, its rate limits, and what it does at
the auction. Those want their own measurement before any migration - M39 and M43
are both cases of a design built on a feed nobody measured first.

## OUTSTANDING, IN ORDER

**One list.** It used to be two: this file's, and section 4 of
`docs/LIVE_TRADING_READINESS.md` ("what is not built, and only matters with real
money"). Two lists is how M39, M41, M43 and M44 went unmentioned in a review of
outstanding work on 21 August. The readiness document still holds the REASONING
for each gap and is worth reading; the list lives here.

### ⚠️ AUDITED 30 AUGUST — what was checked, and against what

Every open item below was checked against **the code, the logs or the live
Gateway**, never against its own prose. That distinction is the entire point:
15 stale headings were closed on 27-28 August, three of them found only by
starting to RE-IMPLEMENT work that already existed.

**Closed by this audit:**

* **Item 2 (M119)** said "deployed but unexercised". The logs say
  `yfinance market data has recovered` on **25, 26, 27 AND 28 August**, every one
  at ~10:20. It survived four consecutive confirmations, two of them in sessions
  that were read back at the time.
* **Item 7 (M44)** — both halves done in M157, deployed and read back tonight.
* **Five "not yet deployed" markers** — HEAD is the deployed build, so all are
  deployed. Weakened to "as of 30 August" rather than naming a build, because
  which of M155/M156/M157 first carried each was not checked and should not be
  asserted.
* **Item 17's regime half** — its text still claimed the Workbench "does not know
  the prevailing regime". `workbench.py:226` subscribes to `RegimeEvent`; M136
  fixed it. Caught because a live note read "regime unknown" and looked like the
  defect — it was not, the market was shut.

**Item 26 — CLOSED on investigation, and the sharpening I did first was WRONG.**
The audit's first pass reported "the locate half fired 63 times" and promoted the
item to the top of the queue on that basis. There is **ONE** such event, echoed
63 times by `ib_async`'s Trade-repr logging. Investigated properly the same
night: `Error 10349` appears zero times ever, `whyHeld` never says `locate`, the
one warning was on LOV not DXS and did not stop that order filling, and the
"parked" DXS sells were bracket legs resting normally. See item 26.

⚠️ **A grep over these logs counts repr ECHOES, not events**, because ib_async
writes each Trade's entire `log=[...]` history into every `orderStatus` line.
That is the second measurement artefact this week to survive into a conclusion —
the first was Milestone C's identical arms. **Extract distinct `TradeLogEntry`
tuples, then count.**

**Confirmed genuinely open, by looking:** item 9 (nothing in `src/` implements
auction rules — only `costs.py` mentions the word), item 24 (no transmission-time
exposure bound exists).

**Items 41 and 42 are CORRECTIONS, not work.** Both record that an earlier claim
was wrong. They read as open items and are not.

⚠️ **The pattern this audit found is the same one as last week:** a heading is
written once and then survives every piece of evidence that contradicts it,
because reading a list is not auditing it. Item 2 needed four.

### Blocking the experiment

1. **The first fill, and everything behind it:** `recent_fills` on IBKR, M71
   (built, never exercised — an app-transmitted sell has never happened), and how
   far back IBKR executions go. M123 removed one reason it could not happen;
   nothing proves it was the only one. ~~The ledger is now EMPTY, so the first
   fill will be row one.~~

   ✅ **PARTLY ANSWERED 26 August.** A broker-side exit DID reach
   `closed_trades.csv` through `absorb_broker_fills` - four rows, arithmetic
   sound - so the path works end to end. It also lost 179 of 183 executions;
   see the 26 August incident above.

   ✅ **AND "how far back IBKR executions go" is now MEASURED: SAME DAY ONLY.**
   At 13:14 on 26 August `reqExecutions(ExecutionFilter())` returned **183
   executions, every one from 26 August**, and none of the 25 August orders
   that `absorbed_fills.json` still lists. That is not a small operational
   detail: **a broker-side fill not absorbed on the day it happens can never be
   absorbed**, because the executions are gone. Any repair that depends on
   re-reading them has until the end of the trading day, and the automatic
   re-absorb path in the absorb-fix plan inherits that deadline.
2. ~~**M119 is deployed but unexercised.**~~ **CLOSED 30 August — it has been
   exercised FOUR times.** Audited against the logs rather than the list:
   `yfinance market data has recovered` appears on **25, 26, 27 and 28 August,
   every one at ~10:20**, each after the feed went down at the open and came
   back unaided. The 28 August line also carries M151's suppression count.
   ⚠️ **This heading survived four consecutive confirmations**, including two
   sessions that were read back at the time. Reading the list is not auditing
   it — which is the whole of what this audit found.
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

   ### ⚠️ MEASURED 28 August BEFORE DESIGNING, and the feed is NOT ESTABLISHED

   `scripts/probe_halts.py`, read-only against the live Gateway:

       Ticker fields matching 'halt': ['delayedHalted', 'halted']

       Error 354: Requested market data is not subscribed ...
                  Delayed market data is available.

       DELAYED feed:
         BHP.AX  halted=nan  delayedHalted=nan  close=66.40
         CBA.AX  halted=nan  delayedHalted=nan  close=154.96
         SUN.AX  halted=nan  delayedHalted=nan  close=18.85

   **`ib_async` models a halt; this account cannot see one.** There is no live
   IBKR market-data subscription — the app runs on yfinance, which reports no
   halt at all — and on the DELAYED feed, which does work (the closes above are
   real), the halt tick was never delivered.

   ⚠️ **NOT YET CONCLUSIVE, and the distinction matters.** `nan` on a symbol we
   just got a close for looks like *the tick was never sent* rather than *not
   halted*, which should be `0`. But the market was SHUT, so "nothing is halted"
   and "halts are not reported" are indistinguishable from here.

   **Monday finishes it in one run**: `scripts/probe_halts.py` during market
   hours. If `halted` reads `0` on a trading symbol, the flag is live and M43 has
   a feed. If it stays `nan`, it does not, and M43 is M39's shape — a designed
   feature with nothing behind it.

   ⚠️ **DO NOT DESIGN DETECTION UNTIL THAT RUN.** M39 was specified against a
   feed that turned out not to exist, and the cost was the design, not the code.

   If the flag proves absent, the only remaining approach is BEHAVIOURAL — a
   symbol that stops ticking while its peers keep ticking — and that is a
   heuristic, not a report. It would also collide with the staleness rail, which
   already treats a silent symbol as excluded rather than halted.
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

   ### ⚠️ THE PREMISE IS WRONG: THE BLOCKER IS NOT TRADE COUNT

   Measured 28 August. All six closed trades carry an EMPTY `entry_slippage`,
   and they would still be empty at twenty:

       entry_slippage   (empty on all 6)
       reference_price  (empty on all 6)
       mae_r -0.0   mfe_r 0.0   worst_price = best_price = entry_price

   `ClosedTrade.entry_slippage` is `entry_price - reference_price` and returns
   `None` without it. `open_position_entries.json` stored only
   `opened_at, price, stop_price, target_price, strategy` — **so every restart
   discarded it, and this app restarts most days.** The instrument existed and
   had never once been fed.

   ⚠️ **THIRD TIME THIS RECORD HAS LOST A FIELD ACROSS A RESTART**, and the
   other two are in its own comments: M33's `target_price` ("six positions came
   back with downside protection and no way to bank a gain") and M49's
   `strategy` ("would rebuild the trade and still not count towards anything").

   ✅ **FIXED 28 August (not deployed):** `reference_price` is carried on
   `_Entry` and `PositionEntry`, populated from the fill event — which has
   carried it since M37, the bridge simply dropped it — persisted by
   `_save_entries`, and read back with `.get` so pre-existing files load as
   UNKNOWN rather than as the entry price.

   ✅ **BOTH HALVES DONE — M157, 30 August.** And measuring before designing
   found a second defect inside the first, which is the worse of the two because
   it had shipped as done.

   ⚠️ **M156's `reference_price` NEVER REACHED THE LOT.** It was carried onto
   `_Entry`, persisted, and read back — all of which worked — and then died one
   call further on: `TradeLedger.restore_open_lot` had no such parameter, so the
   bridge could not pass one and every rebuilt lot got `None`. With a ten-day
   minimum hold and a session most nights, the restart path is the one EVERY
   trade this system closes takes, so `entry_slippage` was still empty. Proven
   with a control, before anything was changed:

       LIVE     reference_price=49.9  entry_slippage=0.099…
       RESTORED reference_price=None  entry_slippage=None

   M156 shipped five tests. They pin the dataclass shape, the write and the read
   — the record and the file. **None follows the value into the rebuilt lot,
   which is what a `ClosedTrade` is made from.** Items 59, 67 and Milestone C
   Task 1 are the same shape, and that commit's own message names them.

   **`worst_price` and `best_price` are NOT persisted.** They are recomputed at
   restore from the daily bars warm start already seeds, so they cannot go stale
   and there is nothing to key, prune or write atomically. The entry day's own
   bar is excluded — it holds prices from before the position existed.

   **Fields this record has now lost across a restart: five.** `target_price`
   (M33), `strategy` (M49), `reference_price` (M44, fixed at the record on 28
   August and lost again one call down), `worst_price` and `best_price`. The
   guard added is anchored on SHAPE — every field common to `_Entry` and
   `OpenLot` must be a parameter of `restore_open_lot` — because a list of names
   is what failed three times. Confirmed to fail when the defect is reintroduced.

   ⚠️ **UNPROVEN UNTIL A TRADE CLOSES.** Everything above is from the suite. The
   check is the first trade opened and closed under M157, and **it must survive a
   RESTART before it counts** — losing it at restart is the entire defect. The
   six existing rows stay empty and always will; their reference prices were
   never written down.

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
13. ~~**Retire the Alpaca CODE paths?**~~ **ANSWERED 28 August — KEEP, and
    here is what it actually costs.** Measured rather than argued:

    | Question | Measured |
    |---|---|
    | Modules implementing it | 3 — `alpaca_source.py`, `alpaca_adapter.py`, `alpaca_client_protocol.py` |
    | Places that reach them | 5, all LAZY — `capabilities:144`, `history:220`, `runtime:180/289`, `settings:188` |
    | Module-level `import alpaca` in `src` | **ZERO** — all 20 are function-local |
    | Hard dependency | **YES** — `alpaca-py>=0.43`, and the spec has `excludes=[]` |
    | Ships in the exe | ~1.3 MB of SDK, for a path this book cannot select |
    | Dedicated tests | 2 files, 66 references; ~10 more incidental |

    **The safety half of the question is already answered by a rail, not by
    deletion.** `preflight.py:172` refuses `broker=alpaca` with `market != US`
    and `:195` refuses `market_data_source=alpaca` the same way. Retiring the
    code to prevent a US broker being pointed at an ASX book would be removing
    code to solve a problem that is already refused at startup.

    **And it is not abandoned code, which is the distinction that decides
    this.** `AlpacaAdapter` is in `KNOWN_ADAPTERS()`, and every entry there is
    capability-audited by `test_capabilities.py` — so it cannot quietly rot
    behind the ASX path while looking like a live fallback. Dead code that
    still passes an audit is a different thing from dead code.

    ⚠️ **What would change the answer:** IBKR proven over a full quarter, or
    the exe size or an `alpaca-py` CVE starting to matter. Not before.

    ⚠️ **What retiring would also delete, and this is the real reason to wait:**
    nine `scripts/analysis/*` probes import the SDK at module level. They are
    the US era's evidence trail — how the feed entitlement, the mark source and
    the split behaviour were actually established. Deleting the SDK deletes the
    ability to re-run any of them, and this project has twice been saved by
    re-reading how a finding was obtained.

    ORIGINAL: Open question. The adapter and market-data
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
    candidate signal — and passed `regime_label="unknown"`, so it did not know
    the prevailing regime. ⚠️ **THAT HALF WAS FIXED IN M136** and this text
    outlived it: `workbench.py:226` subscribes to `RegimeEvent` and updates, and
    the `"unknown"` at :219 is only the value before the first event arrives.
    Checked 30 August, after a live Workbench note read "regime unknown" and
    looked like this defect — it was not, the market was simply shut and nothing
    had classified. Neither sees everything. The ask is one answer over
    both, against the prevailing regime and following the current strategy's
    rules. Needs a design pass first, and **M73's framing has to survive it**:
    this screen is "an analyst, never a trader" and its output reaches no part of
    the trading system. A recommendation that follows the live strategy's rules
    sits closer to that line, not further from it.

18. ~~**The Dashboard's "Review & Apply" button applies nothing.**~~
    **DONE 28 August (not deployed).** BOTH branches of the original ask, not
    the cheaper one: it is renamed to **"Acknowledge note"**, and the click now
    writes an INFO line naming the regime it was acknowledged AGAINST -
    `Regime note ACKNOWLEDGED by the operator: regime bull, at ...` - so it can
    finally serve as evidence a human saw a regime change before a trade.

    ⚠️ **The log line is the deliverable; the caption is the weaker half.** The
    button still resets on the next `RegimeEvent`, and that is correct - a tick
    left standing under a new regime would claim an acknowledgement nobody
    made. What must survive is the record, and a caption is not one.

    The caption confirms with a zoned, market-local time (items 21/40's rule
    applied to a surface added after them), and a test pins that it follows the
    MARKET rather than the machine - easy to pass by accident on a box in
    Sydney, so it is asserted under `market="US"` too.

    Spec §K is unchanged and now pinned: a source-level test asserts the
    handler still reaches no trading path. The fix for a dishonest label was
    never to make the label true by acting.

    ORIGINAL: Its handler is
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

19. ~~**Is the CI-goes-red-before-2200-AEST rule real?**~~ **ANSWERED — NO.**
    Tested 24 August: 43 held-back commits pushed at 13:07 and CI completed
    green in 3m57s. Already recorded in the standing constraints; the item
    outlived its own answer. Audit, 27 Aug.
    ORIGINAL: Recorded as fact in this
    file and in a saved memory. On 24 August CI ran at **13:07 AEST and passed**
    — one clean counter-example. Either a time-dependent test was fixed
    somewhere in the 43 pushed commits, or the rule was never as deterministic
    as recorded. Worth one deliberate daytime push to settle rather than
    carrying forward.

20. ~~**Sweep the other guards for the same blindness.**~~ **DONE 28 August
    (not deployed).** Four guards scan a globbed corpus of `*.py`:

    | Guard | Corpus check | Positive control |
    |---|---|---|
    | `test_design_system_is_the_only_source_of_colour` | had one | had one |
    | `test_computed_values_have_readers` | had one | n/a — asserts a PRESENCE |
    | `test_theme` | **none** | **none** |
    | `test_m111_trading_day` | **none** | **none** |

    ⚠️ **NO HIDDEN LIVE VIOLATION WAS FOUND** — the honest result, and unlike
    M135, which was hiding one. What two of the four could not do was tell you
    their green meant anything.

    **Three narrownesses closed anyway, and the positive control found the
    worst of them on its first run.** `test_theme`'s hex scan required the
    colour to be the WHOLE quoted literal, so `"color: #b71c1c;"` — the only
    way a screen actually writes one — was invisible to the guard whose entire
    job is to catch it. Its font-size scan required exactly one space after the
    colon, so `font-size:14px` was invisible. Both were latent only because the
    tokenising colour guard covers the same ground, and **a guard that is
    correct only because another one overlaps it is not a guard.**

    **Two halves, neither substituting for the other.** `tests/support/
    source_corpus.py:source_files` refuses a missing root or a collapsed corpus
    AT THE POINT THE FILE LIST IS BUILT, so a guard written next month inherits
    it — that answers *did we look*. A planted violation answers *can we still
    see*, and every absence-asserting scan now has one.

    ⚠️ **And a meta-guard, because a helper nobody must use is a convention —
    which is exactly what M135 had.** `test_no_guard_globs_the_source_tree_
    without_the_corpus_check` fails on any test that globs `*.py` itself. It
    flagged its own planted samples on the first run, which is how its two
    exemptions were earned rather than assumed.

    ORIGINAL: M135 found the colour
    guard reading every f-string as empty since the 3.12 upgrade, hiding a live
    violation while reporting none. Any pattern- or `tokenize`-based guard in
    this codebase written before that upgrade could have narrowed the same way,
    and a narrowed guard is worse than none because its green result is read as
    evidence. Not urgent; genuinely worth doing.

21. ~~**Screens render stored UTC as if it were local time.**~~ **STALE —
    ALREADY FIXED, found by audit 28 August.** `display_dates.format_session_
    time(value, market)` exists, renders `HH:MM:SS ZONE` in the EXCHANGE's
    timezone, treats a naive timestamp as UTC, and always names the zone. Every
    site this item and item 40 name now routes through it: `blotter.py:333`,
    `performance.py:435`, `regime_monitor.py:301`, `risk_console.py:415/421`,
    `account_poller.py:72` (the Balances panel's "as of") and
    `watch_session.py:181/275` — including the tally line that printed a bare
    UTC clock with no zone label at all into the console an operator watches
    during an incident. `tests/domain/test_session_time_display.py` pins it.

    ⚠️ **Thirteenth stale heading this week.** Same shape as the other twelve:
    the work shipped and the item outlived it. Nothing here was re-done.

    ORIGINAL: Spotted by the
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

22. ~~**The per-order cap keys off CASH; it should key off SPENDABLE cash.**~~
    **FIXED 28 August, DEPLOYED as of 30 August.** The rule is extracted to
    `adapter.spendable_from(cash, min_cash_reserve)` with THREE readers -
    `AccountBalances.spendable_cash` delegates to it, and the OMS cap calls it
    directly. The broker returns an `AccountSummary`, which does not carry the
    method, so extracting the free function was the only way both could read one
    definition.

    ⚠️ **The suite caught a change that broke 134 tests**, and mypy caught the
    cause first: `account.spendable_cash(...)` does not exist on
    `AccountSummary`. My own test fixture returned `AccountBalances` and hid it.
    A fixture that returns a friendlier type than production is a test that
    proves the wrong thing.

    ⚠️ Also handled: `OMS.settings` can be `None` (tests only - `min_cash_reserve`
    is `gt=0` in production), which falls back to raw cash. That is the OLD
    behaviour rather than a new hazard, and it is stated at the call site.

    ORIGINAL:
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

25. ~~**`preflight`'s book check derives `unprotected` from held positions only.**~~
    **CLOSED 28 August, DEPLOYED as of 30 August** - and closed by STATING the limit
    rather than widening the check, which is what the item asked for.

    Every `book` outcome now carries: *"⚠️ This does NOT look for stops resting
    on symbols the book does not hold (the orphan shape); that is
    check_resting_orders' question, in the session."* Confirmed against the live
    Gateway.

    ⚠️ **Deliberately NOT widened.** That question belongs to
    `check_resting_orders`, which owns the reconciler and can act on it;
    duplicating it here would be a second derivation of one question — the shape
    that produced items 22 and 31 this same evening.

    ⚠️ **The empty-book line was the worst of the three** and the item did not
    name it: it read *"no positions, no resting stops"*, which asserts the
    second half outright. With nothing held the loop runs zero times, so a stop
    resting on ANY symbol would go unreported while the line said none existed.
    It now says nothing was checked about what may be resting.

    ORIGINAL:
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

26. ~~**The IBKR order preset.**~~ **PREMISE NOT SUPPORTED — investigated
    30 August, and the item was wrong on every specific it named.** Measured
    against logs retained back to **27 July**:

    | The item said | The record says |
    |---|---|
    | `Error 10349` on every API sell | **ZERO occurrences**, any symbol, ever |
    | `Warning 404` locate on DXS.AX | **ONE** occurrence, and on **LOV**, not DXS |
    | a locate parked the orders | `whyHeld` **never** contains `locate`, anywhere |
    | DXS sells parked at PreSubmitted | TRUE — with `whyHeld='child'`, `'trigger'`, `'child,trigger'` |
    | "68,268 and 12,000 both failed" | 68,268 is the DXS **POSITION SIZE**: `Position(…symbol='DXS'…, position=68268.0, avgCost=5.86)` |

    The DXS sells were LimitOrder/StopOrder pairs at ids 98/99, 108/109,
    118/119, 128/129 — **bracket legs resting in their designed state**, which is
    exactly what the ten positions held today look like: 10 Submitted, 10
    PreSubmitted. The single locate warning was on LOV order 147, a bracket
    CHILD, and that is the same `permId 1216552509` that executed 3,217 shares on
    26 August. It blocked nothing.

    ⚠️ **The TIF half was real and is fixed (M96)** — `ib_translate.py:152/188/189`
    pass `tif="GTC"` explicitly, and the comment at :184 records the measurement.
    That is presumably why 10349 never appears in this window.

    ⚠️ **THE COUNT THAT MADE THIS LOOK URGENT WAS AN ARTEFACT.** A grep found "63
    occurrences" of the locate warning; there is **one**, echoed 63 times because
    `ib_async` logs the entire `Trade` repr — including its whole `log=[...]`
    history — into every subsequent `orderStatus` line. Any grep over these logs
    counts repr echoes, not events. Extract distinct `TradeLogEntry` tuples.

    **What remains genuinely open is item 1, not this:** no app-transmitted sell
    has ever completed, so the path is UNTESTED rather than broken. The item's
    one unexplained observation — "a manual sell through TWS filled" — is not
    contradicted here, but nothing in the log supports the mechanism it was
    attributed to. **An open market and one app-transmitted sell settles it.**

    Loose end, recorded rather than chased: positions report
    `exchange='ASX', conId=49281421` while orders go out on `exchange='SMART'`.
    Nothing observed suggests this causes anything — the sells reached
    PreSubmitted/Submitted rather than being rejected — and it is noted only so
    the next person does not re-derive it.

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

28. ~~**The kill switch is TRIPPED.**~~ **STALE — it is CLEAR.** Reset by the
    operator 26 August 22:02:22 and clear all through the 27 August session
    (`kill_switch.json` reads `tripped: false`). Kept only for the advice that
    outlives it: reset on a launch you are WATCHING.
    ORIGINAL: It caught the mismatch correctly. Item 27
    is now fixed, so it is safe to reset — but reset it on a launch you are
    WATCHING, because the mismatch it caught came from a replay whose first
    pass now warns rather than being silent.

29. ~~**Make deploying update `DEPLOYED` itself.**~~ **DONE 28 August.**
    `scripts/deploy.ps1` installs and then calls `scripts/record_deploy.py`,
    which rewrites the constant. Everything is DERIVED - milestone, commit,
    hash, rollback name - so nothing is typed per deploy.

    ⚠️ **THE COUNT WAS UNDERSTATED: it has been wrong TEN times, not three.**
    Found while fixing it - `DEPLOYED` still read `0b1ecd6` (M148) with M155
    installed, having sat stale through every deploy of 28 August. The last
    seven failures belong to the person writing this. That is the argument for
    a mechanism in its strongest form.

    **The record is rewritten only AFTER the installed copy verifies**, so it
    can never claim a build that is not there. A missing constant RAISES rather
    than passing quietly: a deploy that installs the build and leaves the record
    stale is exactly how this happened.

    ⚠️ **Two guards added beyond the item**, and one fired on its first run:
    the script REFUSES a dirty working tree - a deploy whose provenance cannot
    be stated is not a deploy - and it refuses while the app is running, naming
    the clean-shutdown reason.

    ORIGINAL: `handoff_state.py`'s hand-
    maintained constant has now been wrong three times: for a day after M104,
    across the whole M130 deploy, and for two hours after M139 on 24 August —
    that last one in the rush to get a session running before the close. Its own
    comment says the figure must change in the same minute as the copy, and
    exhortation has now failed three times. An `invoke deploy` that expands the
    zip AND rewrites the line would remove the only step a human has to
    remember.

30. **Stage 4 regime re-sourcing** — ⚠️ **NO LONGER BLOCKED as of 28 August:**
    Milestone C exists and has answered its first question. **Stage 4 regime re-sourcing** — do not start until the ablation question is
    settled. If the regime gate does not earn its keep, this stage disappears.

31. ~~**The working-status set is narrow in `ib_translate`.**~~ **CLOSED
    28 August, DEPLOYED as of 30 August.** `_IB_WORKING_STATUSES` is now
    `WORKING_STATUSES` itself - ONE definition rather than two that agree, which
    is what stops them drifting apart again.

    ⚠️ **MEASURED BEFORE SHIPPING, as this item required.** Against the live
    book: **20 open orders, 10 `Submitted` and 10 `PreSubmitted`, ZERO in either
    added state.** The widening is a no-op on that book and the aggregate cannot
    move on it. The defect it removes is real and future, not present.

    ⚠️ It LOOSENS a rail and that is why it shipped alone: a position whose stop
    was ignored counted its FULL value against the aggregate cap and now counts
    only to the stop, so the aggregate falls and entries previously refused may
    be permitted. **Read the aggregate on the next watched session anyway** -
    a no-op today is not a no-op forever.

    ✅ **ITEM 64'S PIN FIRED, FOR THE FIRST TIME.**
    `test_item_31_the_working_status_set_is_still_narrow` went red the moment
    the set widened, forcing this heading to be updated rather than left stale.
    That is exactly what it was built for, and it worked within a day.

    ORIGINAL: `_IB_WORKING_STATUSES`
    holds three of ib_async's five real working states; `ApiPending` and
    `ApiUpdate` are missing, so `from_ib_resting_stop` reads a stop in either as
    no protection and `verify_position_stops` logs `POSITION UNPROTECTED` on a
    protected position. M141 fixed this for the orphan scan only, in its own
    set, because widening the shared one moves `_position_stops` — the
    denominator of every risk-at-stop figure the governor gates entries on.
    Ship it separately and measure the aggregate before and after on a watched
    session. `tests/data/broker/test_working_statuses.py` asserts the
    divergence, so closing it is a deliberate act.

32. ~~**⚠️ THE KILL SWITCH DOES NOT SURVIVE A RESTART.**~~ **FIXED IN M144, AND
    THIS HEADING HAS BEEN DANGEROUSLY WRONG SINCE.** It persists: the 27 August
    launch logged `KILL-SWITCH RESTORED FROM THE PREVIOUS SESSION` on 26 August
    and `kill_switch.json` is the store. A reader trusting the heading would
    believe a restart clears a halt, which is the opposite of the truth and
    would invite exactly the restart-to-clear that item 32 existed to prevent.
    ORIGINAL: `KillSwitch` holds
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
    distinct from stale"*, not *"add a staleness rail"*.

    ✅ **BUILT — M158, 31 August. NOT YET DEPLOYED**, deliberately: M157 is
    running today's open, and this deploys after the close so its read-back
    lands at a real bell.

    **The gate enforces, the rail reports**, and they are deliberately not the
    same mechanism. `AutonomyGate` takes a `last_print_source` and refuses a BUY
    whose latest print is absent or from a previous session, compared on
    `mc.trading_date` — both sides of the Sydney midnight boundary are pinned.
    `MarketDataFeed` exposes `last_print_at` and reports absent symbols with a
    count. Wired by an assignment in `runtime.py`, pinned by a test that was
    SEEN to fail.

    ⚠️⚠️ **WHAT A 10-OF-10 BOOK DOES TO THE READ-BACK, and it caught an
    over-claim of mine before the deploy.** `executor.py:161` evaluates the gate
    only on an order that is already `pending_signoff` — one the risk engine
    approved. `governor.py:304` refuses at the position limit UPSTREAM of that,
    so **while the book is 10 of 10 no order is created and the GATE IS NEVER
    REACHED.**

    So the two halves read back separately:

    * **The rail half is readable any session** — the absence count comes from
      the staleness pass and needs no order at all. It requires a moment where
      some symbols have printed and others have not, which is the partial
      delivery pattern the 28 August "possibly delisted" errors show.
    * **The gate half needs the book at NINE.** Until then, "no absence refusal
      appeared" means *nothing reached the gate*, **NOT** that the refusal is
      inert. Reading it as inert would be the absence-proves-nothing trap this
      project keeps recording.

    ⚠️ **TWO CORRECTIONS TO THIS ITEM, both from reading the code rather than
    the item.**

    **It OVERSTATED one part.** Signals are generated inside
    `StrategyEngine._on_market_data`, which is TICK-DRIVEN — a symbol with no
    tick never reaches the handler and cannot signal. "No data at the bell" is
    therefore not by itself an entry hazard, and the 10:29 gate was not the only
    thing standing in the way.

    **It UNDERSTATED the real one, and this is the finding.** A pre-session
    print IS caught by the staleness arithmetic. But exclusion is computed by a
    PERIODIC PASS while the signal is computed ON TICK ARRIVAL — so between a
    pre-session-stamped tick landing and the next pass, an entry can be sized
    against data that is not today's. **That is a RACE, not a coincidence**, and
    no margin closes a race. An assertion at the point of decision does.

    ⚠️ **AND A REAL DEFECT FOUND WHILE BUILDING IT.**
    `refusals._match` is FIRST-MATCH-WINS over substrings. The new refusal's own
    text reads *"ABSENT, not stale"*, and `("stale", …)` was listed first — so
    it was being filed under **"Stale market data"**, the exact conflation this
    item exists to prevent. The specific patterns now precede the general one,
    and nothing but list order enforces that.

    **Recorded, deliberately out of scope:** `MarketDataFeedEvent` — which
    exists precisely because *"a feed that never delivered anything raised
    nothing at all"* — has ONE subscriber, `main_window.py:83`, a display.
    **No entry decision gates on feed health.** That is a different rail from
    per-symbol absence and mixing them would repeat M28a's mistake of halting an
    account for one symbol's silence.

34. ~~**⚠️ THE RECONCILIATION POLL WEDGED SILENTLY AND NEVER RECOVERED.**~~
    **ROOT CAUSE FOUND, FIXED, AND CONFIRMED LIVE 26 Aug.**

    ✅ **CONFIRMED IN PRODUCTION, 26 August, on M145.** Eight consecutive
    heartbeats, **300 seconds apart to the second**, every one reporting the
    full book:

        08:54:41  (startup)  RESTING ORDER SCAN: 20 working leg(s) across 10 symbol(s)
        08:59:41  (+300s)    ... and six more, through 09:29:42

    `ERROR/CRITICAL since the bell: 0` — no `reqAllOpenOrders` timeout, in the
    same after-hours/pre-open condition that produced two of them at 22:28:22
    the night before. Set against 25 August, when the scan ran **once**, at
    09:09:52, and the rail was dead for the following 6h50m.

    Note it was `session_check`'s new freshness line that made this legible:
    `RESTING ORDER SCAN x8, last 09:29:42`. The old line read
    `RESTING ORDER SCAN ran, clean` whether it had run once or eight times, so
    the confirmation and the failure would have looked identical.

    **ROOT CAUSE FOUND AND FIXED 26 Aug.** Backstop fixed 25 Aug (`e9a180b`):
    `poll()` runs under `asyncio.wait_for` (120s default) and logs what is at
    stake; CRITICAL after three in a row; it does NOT trip the kill switch,
    which stays the operator's open decision.

    **⚠️ THE RECORDED CAUSE WAS WRONG, and wrong the familiar way.** This item
    said the culprit was `reqExecutionsAsync` losing an `execDetailsEnd`. That
    was written from reading a call site — the fourth time on this project that
    a finding came from code structure rather than from the recorded evidence,
    after items 41, 42 and 43. It is falsifiable in one line of the library:
    `reqExecutionsAsync` keys its future on `client.getReqId()`, which is
    **unique per request**, so two of them cannot interfere at all.

    **The real cause is a SHARED FUTURE KEY, and two callers on identical
    timers.** Measured against the installed ib_async 2.1.0:

        def reqAllOpenOrdersAsync(self):
            future = self.wrapper.startReq("openOrders")   # a LITERAL key
            self.client.reqAllOpenOrders()
            return future

        def startReq(self, key, ...):
            future = asyncio.Future()
            self._futures[key] = future                    # OVERWRITES, silently

    `openOrderEnd` resolves whichever future is in the dict at that moment. A
    second call while the first is in flight **replaces the first future
    without resolving or cancelling it**, so of N concurrent readers exactly
    one is answered and the rest await a future nobody will ever complete.
    Proven offline, deterministically, with no Gateway: the orphaned future
    never completes.

    Two independent asyncio tasks in this application reach it, and
    `reconciliation_poll_seconds` and `protection_sweep_seconds` are **both
    300.0**, with both engines started in the same second:

    * `ReconciliationMonitor.poll` → `check_resting_orders` → `open_orders()`
    * `CorporateActionMonitor.refresh` → `resting_stop_orders()`

    So the two timers are **phase-locked and collide on every tick for the life
    of the process** — not occasionally. That is the whole shape of the bug,
    and it explains the one thing the old hypothesis never could: **why the
    startup scan ALWAYS succeeded.** The orchestrator awaits each engine's
    `start()` in turn, so nothing overlaps at launch; every poll after it does.

    **The production evidence was already on disk and says so.** At 18:02:43 on
    25 August the poll's own log line reads *"the broker reconciliation result
    above is unaffected and already published"* — `check_reconciliation`
    COMPLETED, positions and executions both came back, and only
    `reqAllOpenOrders` hung. A dead connection cannot produce that. At 22:27:22
    both readers fired within 15ms of each other and both timed out at exactly
    60s, five minutes after a startup scan on the same connection had returned
    20 legs across 10 symbols.

    **Fixed:** an `asyncio.Lock` in `IBAdapter` serialising every
    `reqAllOpenOrders` through one helper, `_all_open_orders`. ⚠️ The lock is
    taken **before** `request()` is called, and that ordering IS the fix —
    `reqAllOpenOrdersAsync` is a plain `def` that registers its future the
    moment it is CALLED, not when awaited, so a lock inside `_call` would let
    both callers clobber the key first and serialise nothing. Four tests,
    including a structural sweep that fails if a fourth call site ever reaches
    the client directly, and a tripwire on the two intervals still being equal.

    ⚠️ **The existing timeout tests could not have caught this**, and the
    reason generalises: their fakes are `async def`, and calling a coroutine
    function runs none of its body, so no `startReq` happens until the await.
    The real method is a plain `def`. **A fake with the wrong call semantics
    tests the fake.**

    **Also fixed: check 5 of `session_check.ps1` now reports FRESHNESS.** It
    read a reassuring `RESTING ORDER SCAN ran, clean - 0 divergences` all day
    on 25 August while the rail was dead — the scan ran ONCE, at 09:09:52, and
    nothing distinguished that from running every poll. It now prints the COUNT
    and the LAST scan time, and flags `*** THE SCAN HAS STOPPED ***` when the
    newest heartbeat is more than 900s (three poll intervals) old. Verified to
    FIRE, not merely to pass: against the 25 August morning shape it prints
    `x1, last 09:09:52, 410 min ago`. The window ends at the app's last log
    line rather than at stand-down, deliberately — the poll keeps running after
    the session stands down, which is exactly where the 22:27 collision was
    seen. Observed
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

    ~~Wanted: a watchdog on the poll itself.~~ **DONE 25 Aug** — `poll()` runs
    under `asyncio.wait_for`. Worth keeping the reasoning: a loop whose failure
    mode is silence needs a deadline. Note the backstop is what made the root
    cause findable at all — before it, the collision produced no log line of
    any kind, and the two ERROR pairs it emitted on 25 August are the entire
    evidence trail this diagnosis rests on.

    **AND check 5 of `session_check.ps1` reported a reassuring green all day**,
    which is a defect in M141's own operator surface. It reads
    `5 orphans  RESTING ORDER SCAN ran, clean - 0 divergences` — true, and
    misleading: the scan ran ONCE, at 09:09:52, and the rail was dead for the
    remaining 6h50m. The check distinguishes "did not run" from "ran clean",
    which was the point of I2, but NOT "running every poll" from "ran once at
    startup seven hours ago".

    ~~Fix it with the same change~~ — **DONE 26 Aug**, as described above: the
    COUNT and the LAST scan time, and an alarm past three poll intervals. A
    freshness check is the only kind that can catch a rail that stopped rather
    than one that never started.

    Closing the loop on the day: no bracket fired on 25 August, so the worst
    case never materialised — nothing closed unrecorded and the ledger is not
    short. That was luck, not design.

35. ~~**`ib_async` logs each `orderStatus` at INFO with the entire `Trade` repr**~~
    **FIXED.** `NOISY_LIBRARY_LOGGERS` carries `ib_async.wrapper` and
    `logging.py:33` describes this exact defect as its reason. Audit, 27 Aug.
    ORIGINAL:,
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

36. ~~**`poll()`'s docstring promises a control that does not exist**~~
    **APPEARS FIXED — judged from the docstring, not from a live run.**
    `delever.poll()` now says what it does: *"Reports the breach whether or not
    trimming is enabled, so 'we are over cap and doing nothing about it' is a
    visible state rather than silence."* ⚠️ Weaker evidence than 35 or 51,
    which name their milestone. Audit, 27 Aug.
    ORIGINAL:
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

37. ~~**⚠️ THE DRIFT GUARD ON PARKED ORDERS MAY NEVER RUN.**~~ **FIXED — all
    three wants, and EXERCISED live on 27 August.** `ib_adapter.py:287` uses
    `reqTickersAsync`, which waits for the ticker rather than hoping, bounded by
    `_call`'s deadline. `executor.py:235` logs the skip and distinguishes it
    from a pass — seen today on WOW.AX: *"No usable quote for WOW.AX, so the
    price-drift check is SKIPPED for this order - it is not passing that check,
    it is not taking it."* Found stale on 27 August by audit.
    ORIGINAL: An order the autonomy
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

38. ~~**⚠️ THE RISK CONSOLE CALLS A PARKED ORDER "approved".**~~ **ALREADY
    FIXED in `de8b8d1`, and this heading outlived it.** `risk_console.py:384`
    renders `risk-approved`/`risk-refused`, and `:180` adds a caption saying
    what the verdict is NOT - *"NOT whether the order reached the broker"* -
    rather than trusting a hyphenated label to carry it alone.

    ⚠️ Found on 27 August by starting to re-implement it. **Fourth stale
    heading in two days** (28, 32, 61, and this). The pattern is now frequent
    enough to be its own item: see 64.

    ORIGINAL: **The Risk Console calls a parked order "approved".** Observed 25 August:
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

39. ~~**The Equity vs Benchmark chart's x-axis renders bar indices, not dates.**~~
    **FIXED in `62660ae`, with a second half in `fc296f8`.** `equity_axis_mode`
    returns the axis and its label as a PAIR so the two cannot disagree — which
    is exactly how they came to disagree. Found stale on 27 August by audit.
    ORIGINAL:
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

40. ~~**UTC is still rendered where AEST is meant — more instances found.**~~
    **STALE — closed with item 21 on 28 August.** Every instance this entry
    names was verified fixed: the Balances "as of", the Regime Monitor's
    transition history, the Blotter column, and `watch_session.py`'s tally
    line. See item 21 for the measured site list.

    ORIGINAL:
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

* ⚠️⚠️ **DO NOT PUSH TO GITHUB.** Standing hold placed by the operator on
  **27 August 2026**: *"no pushing to GitHub until I advise otherwise."* Commit
  locally as normal — the hold is on `git push` alone. **Only the operator can
  lift it**; do not infer it has been lifted from silence, from a new session,
  or from a change looking safe. When reporting state, say plainly that commits
  are local and unpushed, so nothing downstream assumes `origin` is level.
* **PowerShell for `%LOCALAPPDATA%`** — see the top of this file.
* ~~**Do not push until September.**~~ **TESTED AND FALSE, 24 August.** 43
  held-back commits were pushed at 13:07 and CI completed **green in 3m57s** on
  `windows-latest`. Run the local suite in full anyway and read the actual
  summary line, never a piped tail.

  ⚠️⚠️ **AND NOW IT IS EXHAUSTED — 26 August. CI IS BLOCKED.** The allowance ran
  out during the 25 August session. Runs fail in **3–4 seconds with zero steps
  executed**, annotated *"The job was not started because recent account
  payments have failed or your spending limit needs to be increased."* Operator's
  read: blocked until **September**.

  From `gh run list`: everything up to **25 Aug 12:23 UTC** succeeded at ~4m19s;
  both runs after it (25 Aug 22:43 and 23:01 UTC) hit the wall. The 25 August
  session pushed **eight times** — at the 2× multiplier that is roughly 8
  minutes each.

  **Pushing still works and still costs nothing** — a push consumes no minutes,
  only the workflow does. So `git push` succeeds and the workflow simply never
  starts. **Batching no longer saves anything**, because there is nothing left
  to spend.

  **The consequence is the part that matters: the local suite is now the ONLY
  verification.** There is no second instrument left to disagree with it — which
  is precisely the safety net that caught seven consecutive red pushes against a
  green local suite on 19 August. Run all four checks and the suite before every
  commit and treat them as final. After pushing, still run `gh run list
  --limit 3`, but expect `failure` in ~4s and read it as the wall, not a
  regression — confirm by checking the run has zero steps, and do not spend time
  debugging it.

  **Note the shape, which outlives the outage.** This rule has now been wrong in
  BOTH directions inside three days: recorded as "exhausted, do not push",
  tested on 24 August and found false, rewritten as "CI works" — and true again
  today because the conditions moved underneath it. A rule about a FINITE
  RESOURCE was written as though it described a permanent property. Check the
  state; do not recall it.

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

50. ~~**The build stamp renders its date in UTC.**~~ **FIXED in M145
    (`08e4dc5`).** Confirmed on today's own builds: `M151 (7f3efe3, built
    27/08/2026 17:24 AEST)`. Found stale on 27 August by audit.
    ORIGINAL: Seen on M144: `built
    25/08/2026 12:01 UTC` on the Settings screen, where 12:01 UTC is 22:01
    AEST. Reported by the operator on 25 August and deferred to the next
    session.

    **This is the LABELLED kind, not the dangerous kind.** It says "UTC" out
    loud, so unlike `watch_session.py`'s bare clock (item 40) nobody can
    misread it by ten hours without noticing. But it is rendered to a human on
    a screen whose other fields are session-local, which is the boundary item
    40 drew: convert it, or at minimum keep saying which zone it is.

    `format_session_time` already exists and does exactly this. The stamp is
    written by `_write_build_stamp` in `tasks.py` at package time, so the fix
    is at the point of WRITING it rather than of displaying it - which means
    the stamp is baked into the artefact and a rebuilt build is needed to see
    the change, not merely a redeploy.

    Note the deliberate exception recorded under item 40: the LOG's `ts` field
    stays UTC-with-offset. Machine records want one zone. Do not "finish the
    job" by converting those.

51. ~~**A refused Gateway connection kills the app with a raw PyInstaller**~~
    **FIXED in M125.** `ib_adapter.py:153` — *"Connect, retrying a refused port
    for a bounded time (M125)"* — and `preflight` probes the port rather than
    the process. Audit, 27 Aug.
    ORIGINAL:
    dialog, and the log's last line says the shutdown was NORMAL.** Seen on the
    first M145 launch, 26 August 08:44:28, with IB Gateway not logged in.

    The adapter's own handling is good and the message is exactly right:

        IBKR refused the connection 6 times - giving up. Check that the Gateway
        is logged in and that its API port (4002) is open.

    Then the exception propagates out of the entrypoint uncaught, and what the
    operator actually SEES is a `#32770` message box titled *"Unhandled
    exception in script"* reading `Failed to execute script 'app' due to
    unhandled exception: [WinError 1225] The remote computer refused the
    network connection` — strictly less useful than the line the app had
    already written, and it never reaches the log at all.

    Worse, the log's final line is `Quant Advisory Terminal stopped - shutdown
    reached normally`, written at the same second. **The record says clean exit
    while a crash dialog is on screen.** That is this project's recurring shape
    pointed at the operator surface: the record and the reality disagree, and
    the record is the reassuring one. Anything reading the log to decide
    whether the last run ended cleanly — `session_check` included — is told yes.

    The GUI stayed up behind the dialog, fully rendered and entirely dead, with
    every Balances field on `—`, which is how it was mistaken for a live window.

    Wanted: catch the connect failure at the entrypoint and exit deliberately —
    the operator-facing text should be the adapter's sentence, not PyInstaller's
    — and do not log "shutdown reached normally" on a path that is ending
    because of an unhandled exception.

52. ~~**`SessionController.active` is constructed True, so a controller that**~~
    **ADDRESSED in M108.** Still constructed `True`, deliberately — the
    orchestrator starts the feed before this engine runs — and `:98` now
    explains it. The real defect was the SILENCE that followed, which M108
    fixed. Audit, 27 Aug.
    ORIGINAL:
    never runs its first check asserts the market is OPEN.** Same launch:
    the Dashboard read `Session: ACTIVE - ASX is open` at 08:45, three
    columns away from its own `ASX closed` / `opens in 01:14:28 (Wed 10:00)`.

    **The default is deliberate and its reasoning is sound** —
    `session_controller.py:81`, because the orchestrator starts the feed before
    this engine, so the session begins active and the first `apply_once` stands
    it down. That is correct on every launch that reaches the engine. This one
    died in broker-connect, several engines earlier, so `apply_once` never ran
    and nothing ever corrected the assumption.

    **Bounded honestly: in THIS instance the cost was a wrong label on a dead
    app, not a trading action.** The only consumers of `.active` outside the
    controller are `status_line()` and `session_panel.py:339`; the trading gate
    works by the controller starting and stopping the feed and strategy engine,
    and neither was running. So this is a display defect today.

    It is recorded because of its SHAPE, which is the one this list keeps
    finding: a flag that asserts the permissive state before anything has
    checked, corrected only by a step that may never execute. Item 45 praised
    `(escape unknown)` for saying "we could not check" instead of asserting;
    this is the same question answered the other way.

    Wanted: a third state. Until `apply_once` has run once, the line should say
    so rather than pick a side — and it should be UNKNOWN, not ACTIVE, that it
    falls back to.

53. ~~**The watcher would not start, and its own usage line is what failed.**~~
    **FIXED 26 Aug.** Reported by the operator mid-session. `watch_session.py`
    documents `python scripts/watch_session.py`, and that command answered
    `ModuleNotFoundError: No module named 'qat'` — `qat` lives under `src/` and
    is importable only from an interpreter it has been installed into, so a
    bare `python` (which is what the docstring tells you to type) could never
    work. The venv python did.

    **Nine sibling scripts already carry the fix** — `preflight`, `ibkr_probe`,
    `flatten_positions`, `unwind_in_tranches` and the rest all do
    `sys.path.insert(0, .../"src")`. The one tool an operator reaches for
    *while a session is running* was the one without it. Nothing in it needs a
    third-party package, so with `src` on the path any interpreter runs it.

    ⚠️ **AND item 40 was only half fixed, in the file its own test calls the
    WORST offender.** With the watcher finally running, every event line read
    ten hours out: an app launch at **08:53:34 AEST printed as `22:53:34`**,
    bare, with no zone label. `stamp = str(event.get("ts",""))[11:19]` — a raw
    slice of the log's UTC-with-offset field, throwing the offset away.

    M144 converted the TALLY line in this same file, twenty lines below, and
    left the PER-EVENT line alone. Two printers, one file, one fixed. That is
    exactly what *"check whether the fix has a sibling"* exists to catch, and
    it was missed on the file the habit was written about.

    It is also the worst place for it to survive: the event line is the one
    that repeats hundreds of times during an incident, which is the only time
    anyone reads this tool — the precise scenario item 40's test file
    describes. Now rendered through `format_session_time`, zone named, with a
    fallback that cannot raise, because a monitor that dies on one malformed
    line is worse than one showing an awkward stamp.

54. ~~**The known blind window logs 570 ERRORs a session, from a library logger**~~
    **FIXED — M151, and the volume was UNDERSTATED.** Measured on the 27 August
    log: **685 of the 710 lines** in the blind window (10:00:05–10:20:32) were
    the per-symbol delisting storm — 96% — and they buried the RHC.AX
    `BROKER-SIDE FILL absorbed` under about three hundred of them. With the
    filter the fill would sit among ~25 lines.

    `BlindWindowFilter` drops ONLY the `possibly delisted; no price data found`
    message, and ONLY while the feed says it is blind. Matched on the TEXT, not
    the logger — suppressing yfinance wholesale would have hidden the real
    `HTTP Error 401: Invalid Crumb` that landed at 10:26:52. Outside the window
    the same message passes through, because COL.AX and GQG.AX logged it
    genuinely on 26 August. What is dropped is counted, and the count is printed
    beside the recovery line that explains it.

    ⚠️ Blind is set from the FIRST empty poll rather than at the failure
    threshold: the storm starts at poll one, and four polls of 95 is most of it
    already spent by the time the threshold is crossed.

    ORIGINAL: **The known blind window logs 570 ERRORs a session, from a library logger
    nobody tamed.** Observed live 26 August at the open. From 10:00:02,
    yfinance logged `<SYM>: possibly delisted; no price data found` once per
    symbol per poll — 95 symbols × 6 polls = **570 ERROR lines**, plus six
    multi-line `95 Failed downloads` blocks. **582 of the 591 log lines written
    since the bell came from the `yfinance` logger.**

    **None of it is a fault.** It is the documented 20-minute ASX delay: there
    is no data for today until about 10:21, and M119 handled it exactly right,
    logging `yfinance has returned no data 5 times consecutively - market data
    is down. Retrying with backoff.` once, and `MARKET DATA DOWN` once. Our own
    code said the right thing, once. The library said it 570 times.

    The `$` prefix on those symbols (`$CIA.AX`) is yfinance's own error
    formatting, not our symbol construction — the lines come from the
    `yfinance` logger, not from `qat.data.yfinance_source`.

    **Two costs, and the second is the one that bites.** `session_check` now
    reports `ERROR/CRITICAL since the bell: 584` on a completely healthy
    session, which trains the operator to ignore that number — and it is the
    number that would carry a real fault. And this is item 35's family: log
    volume evicts diagnostics, and 570 lines a session is a rotation budget
    spent on a non-event.

    `NOISY_LIBRARY_LOGGERS` already exists for exactly this (`logging.py:47`)
    and carries only `ib_async.wrapper`, `ib_async.client` and `ib_async.ib`.
    yfinance is not in it — **and adding it there would not work**, because
    that mechanism raises a logger to WARNING and yfinance is logging at ERROR.

    ⚠️ Wanted, but NOT a blanket silence: a genuinely delisted symbol is a real
    event and must stay visible. What is redundant is the per-symbol repetition
    during a window the app already knows it is blind in, and which its own
    summary line already reports once. Suppress it while the feed is inside its
    known delay, or collapse it to a single line naming the count — not by
    turning the logger off.

56. ~~**⚠️⚠️ THE APP COUNTS ITS OWN ENTRIES TWICE. The identity bridge has NEVER
    worked.**~~ **FIXED IN M148 (`0b1ecd6`), DEPLOYED 26 August 19:05 — AND NOT
    YET EXERCISED.** No entry has happened since it landed, so the first entry
    of the next session is its first real test. ⚠️ **The finding below is
    retained in full**, because what to watch for is only legible against it.
    Found live 26 August at 15:17:11, twenty seconds of trading after
    the kill switch was reset.

    Two entries went out at 15:15:24-25 — WOW.AX 1098 and SEK.AX 2978, each
    **transmitted exactly once** (M139 held) and correctly bracketed. 107
    seconds later:

        BROKER-SIDE FILL absorbed: buy 1098 WOW.AX at 40.04 (order 550634674)
          - a position was OPENED at the broker that this application did not send
        Broker reconciliation mismatch: SEK.AX tracked=5956 broker=2978,
                                        WOW.AX tracked=2196 broker=1098

    Exactly 2x on both. The app sent those orders and then absorbed them as
    foreign.

    **THE CAUSE, and it is documented at the very line that causes it.**
    `from_ib_trade`'s own docstring:

    > permId can be legitimately absent (0) here: `IB.placeOrder` returns a
    > `Trade` before TWS has acknowledged the order... an absent/zero permId
    > leaves `our_order.order_id` exactly as it was (the app's own id)

    So `oms.py:730` registers the order under the app's **UUID**, the execution
    arrives keyed on IBKR's **permId**, `_is_foreign_unrecorded` compares the
    two, and they can never match.

    **It is not a race and it does not sometimes win.** Every
    `Order signed off and transmitted` line in the entire log history — back to
    1 August, across Alpaca and IBKR, every session — carries a UUID and never a
    permId. The bridge has not once succeeded.

    ### ⚠️ It fired on 25 August too, and NOTHING could see it

        17:56:43  BROKER-SIDE FILL absorbed: buy 99 LOV.AX ... 11674 BOQ.AX
                  ... 9227 A2M.AX ... 2802 IAG.AX ... 237 ANZ.AX   [14 of them]

    Those are that day's own nine entries, absorbed as foreign — and **zero
    reconciliation mismatches were logged on 25 August**. The reason is item 34:
    the poll was wedged, and only **3 scans** ran that day against **78** on 26
    August. The book was silently doubled and every subsequent restart
    re-adopted from the broker and quietly corrected it.

    **So item 34's fix did not cause this — it made a months-old defect visible
    for the first time.** That is precisely what the fix was for, and it is the
    strongest argument yet that a rail whose failure mode is silence is worse
    than no rail.

    ### What it costs, and what it does NOT

    **The broker quantity is always correct.** WOW held 1098 and SEK held 2978 —
    exactly what was ordered. **No over-buying: this is NOT 24 August.** The
    damage is confined to the app's book, and a restart re-adopts from the
    broker and clears it.

    While the book IS doubled it is not harmless: tracked quantities feed the
    aggregate-risk and sizing calculations, the resting-order scan reads the
    brackets as unjustified and quarantines them, and the kill switch trips —
    halting trading for the rest of the session.

    **Every rail behaved correctly.** Transmission once, brackets placed,
    mismatch detected, switch tripped, `resting_order_cancel_enabled: False`
    so the quarantine could not cancel real protection, `4 unprot x0`
    throughout. The detection worked; the arithmetic underneath it did not.

    ~~Wanted: the app must learn its own order's permId when TWS acknowledges it,
    rather than only at `placeOrder` when it is still 0 — and `_broker_order_ids`
    must be updated at that moment. Until then EVERY new entry double-counts and
    halts the session ~300s later.~~ **DONE in M148.** `place_order` now waits
    briefly for the permId (`_await_perm_id`, `ib_adapter.py:796`) and says so
    when it never comes, and `oms.py:265` binds it late if the wait loses — so
    the bridge works whether the acknowledgement is fast or slow.

    ### ⚠️ HOW TO TELL, ON THE FIRST ENTRY, WHETHER IT WORKED

    **The `Order signed off and transmitted` line carries a NUMERIC permId
    rather than a UUID.** Every such line in the whole log history — back to
    1 August, across Alpaca and IBKR — carried a UUID, so that one field IS the
    before/after, and it is visible immediately without waiting for an absorb
    pass. Then: **no `BROKER-SIDE FILL absorbed` line may name an order the app
    has just sent.** If one appears, HALT — that is this defect surviving its
    fix.

    ### ✅ AND A DORMANT RAIL CAME BACK, UNPROMPTED

    On the M148 restart, without being asked:

        Corrected the recorded entry price for SEK.AX -> 14.8836,
        WOW.AX -> 40.0752 to what the broker charged

    That is `_correct_announced_price` (M70/M71), which this handoff had
    recorded as having gone dormant without erroring — *the app kept recording
    entry and exit prices it never paid*. It resolves an incoming fill by
    comparing `order.order_id` against the fill's, which is **the very identity
    that never matched**. Fixing item 56 revived it as a side effect, and those
    two entry prices in the record are now what was actually paid rather than
    what the order was sized against.

    ⚠️ **Worth generalising:** this defect was silently disabling a rail nobody
    had connected to it. A second rail may still be dark for the same reason,
    and the way to find it is to look for anything else keyed on
    `order.order_id`.

    ### ⚠️ THAT LEAD WAS FOLLOWED, AND IT FOUND A SECOND DARK CONSUMER

    **`_own_partial_fill_stamps` has been empty for the entire life of the IBKR
    integration**, and M148 is about to fill it for the first time.

    It is written in exactly one place — `_correct_announced_price`
    (`oms.py:1761`), *after* `_order_the_broker_calls` resolves. That call never
    resolved, so the dict never gained an entry. It is read in exactly one
    place, `_fill_query_floor` (`oms.py:1451`), whose own docstring says why it
    exists:

    > **The app's OWN partials need the same reach, and were not getting it
    > (M70).** `_absorbed_fills` holds foreign executions only … an entry still
    > filling was covered by neither term.

    M70 added that reach deliberately. **On IBKR it has never once applied**, because
    the term that feeds it was always empty — the same single broken identity,
    two rails downstream, and neither of them erroring.

    ⚠️ **So the first entry changes the absorb query floor for the first time.**
    Once a partially-filled own entry stamps that dict, `_fill_query_floor`
    starts reaching back further than it ever has on this broker. The reasoning
    says that is safe — a re-read of a completed fill has a zero delta and is
    skipped, `_absorbed_fills` is pruned to 30 days and the query is bounded by
    symbol — but **safe by argument is not the same as observed**, and this is
    the absorb path, on the day its other half is also unproven.

    ### ✅ AND IT GIVES THE WATCH A SECOND, INDEPENDENT SIGNAL

    `Corrected the recorded entry price for <SYM> -> <price> to what the broker
    charged` is now expected on an entry that fills away from its sized price.
    That line **cannot appear unless the identity bridge resolved**, so it
    confirms the item 56 fix from a completely different direction than the
    numeric permId does. Two independent confirmations beat one, and this one
    also says the price in the record is what was actually paid.

    ⚠️ Absence is NOT failure here: the line is suppressed when the fill lands
    within `_ANNOUNCED_PRICE_TOLERANCE` of the announced price, which is the
    ordinary case. **The permId remains the signal that must be there.**

57. ~~**The Risk Console's kill-switch button reports a state it has not
    checked, and clicking it does the OPPOSITE of what it says.**~~
    **FIXED AND CONFIRMED LIVE 26 August.** Shipped in M148. The label is now
    recomputed from the panel's existing 2s timer rather than remembered, so it
    is DERIVED and cannot go stale — deliberately preferred to another
    listener, because the outbound half of this same bug was fixed once and the
    inbound half was missed.

    ✅ **Confirmed by the operator at 22:02:22**, on the first click after the
    fix: *"Reset pressed, both messages agree."* The banner and the button said
    the same thing, and the reset did what its label promised. Seven hours
    earlier the same click would have reset the switch while reading *"click to
    halt trading"*. Logged as `Kill-switch reset by operator (risk console) -
    order flow resumes (was: Broker reconciliation mismatch)`.

    ORIGINAL FINDING. Found by the
    operator on 26 August, who saw the main banner reading `Execution halted`
    while the Risk Console button read `KILL-SWITCH: inactive - click to halt
    trading`, and **stopped rather than clicking**. That caution is the only
    reason order flow stayed halted.

    `_refresh_kill_switch_button()` is called from exactly TWO places:
    construction (`risk_console.py:133`) and the end of the click handler
    (`:631`). The panel's 2-second `QTimer` never calls it. So the label
    reflects the state at build time or at the operator's last click, and **a
    switch tripped by anything else — reconciliation, the equity rails, the
    restore-on-startup path — never updates it.**

    ⚠️ **The dangerous part is the handler.** `_on_kill_switch_clicked` reads
    `self.runtime.kill_switch.tripped` — the TRUE state, not the label — and:

        if self.runtime.kill_switch.tripped:
            # No confirmation: de-risking stays one click, deliberately.
            self.runtime.kill_switch.reset(operator)

    So clicking a button labelled *"click to halt trading"* **resets the switch
    and resumes order flow, with no confirmation prompt** — because the
    no-confirm path is deliberately reserved for de-risking, and item 36's
    `_confirm_trip` guards only the other direction. The one screen an operator
    reaches for in an incident invites the opposite of the intended action.

    **This is the sibling of a fix that was already made here.** The handler's
    own docstring records it: *"halting from here left the main window's banner
    reading AUTO-TRADE ACTIVE and resetting left it reading HALTED. The state
    was right and every other view of it was wrong."* That fix made this screen
    ANNOUNCE outward. Nobody made it LISTEN. Same shape as `BrokerFill.price`
    and item 40's watcher clock, both found the same day.

    ~~Wanted: refresh the button from the same listener every other view already
    uses.~~ **DONE in M148, and better than that.** It is refreshed from the
    panel's existing 2s timer, so the label is DERIVED rather than announced —
    deliberately preferred to another listener, because a derived label cannot
    go stale where a listener can be missed, which is precisely how the
    outbound half was fixed and the inbound half was not.

    ~~Until then, trust the banner or `session_check`, never that button.~~
    **No longer true — the button is trustworthy as of M148**, confirmed by the
    operator at 22:02:22 with both surfaces agreeing.

58. ~~**⚠️ TWO ENTRIES SIZED IN ONE CYCLE EACH SEE A BOOK WITHOUT THE OTHER**~~
    **FIXED in M150, deployed 27 Aug.** `pending_orders` now counts `transmitted`
    as committed exposure. ⚠️ NOT YET EXERCISED - needs two entries in one cycle,
    and the book has been at 10 of 10 since.
    ORIGINAL: **Two entries sized in one cycle each see a book without the other, and
    THE 10-POSITION LIMIT WENT TO 11.** Found 27 August from the audit trail,
    not from a failure — the book has been over its cap since 26 August 15:15
    and nothing has said so.

    | | risk decision | signed off | `position_count` |
    |---|---|---|---|
    | WOW.AX | 05:15:24Z | 15:15:24.870 | **9.0** |
    | SEK.AX | 05:15:25Z | 15:15:25.043 | **9.0** |

    Nine held, both approved, book eleven — in 173 milliseconds.

    **The check is not missing and it is not wrong.** `ExposureSnapshot` counts
    pending buys into `position_count` deliberately (`governor.py:136-148`, and
    its comment says why a pending SELL is excluded), and `governor.py:304`
    refuses at `>= max_concurrent_positions`. The rail is built exactly as it
    should be.

    **What it reads is stale.** Both orders were sized in one evaluation cycle
    and signed off afterwards — the log's own phrase for them is *"an order
    parked since it was sized"* — so when the second was sized the first was
    neither held nor yet pending. The pending term had nothing to see.

    ⚠️ **CONFIRMED: the count, the two audit rows and the resulting book of 11
    against a cap of 10.** NOT YET PINNED: that a shared snapshot is the
    mechanism. It is strongly indicated and it should be nailed by a test that
    sizes two candidates in one cycle and watches the second get approved —
    which is also the test that would have caught this.

    ### It is the week's shape for the third time

    Item 56: the identity is checked, and the thing checked was never populated.
    Item 34: the poll is scheduled, and the schedule was wedged. This: the limit
    counts pending orders, and nothing was pending yet. **A rail reading a stale
    input is indistinguishable from a rail that agrees with you** — and all
    three were found by reading the record rather than the call site.

    ### ⚠️ WHAT IT COSTS TODAY, AND IT IS NOT NOTHING

    Eleven positions against a cap of ten is also **why no entry can happen at
    all**, and it costs MORE than it looks: `governor.py:304` refuses at `>=`,
    so returning to ten is back AT the limit rather than under it. **From
    eleven, TWO exits are needed before a new name can be entered.** Confirmed
    live on 27 August - RHC.AX exited at 10:02:41, the book went 11 -> 10, and
    nothing became enterable. That cost 27 August its planned test of item 56's
    entry path:

        max_concurrent_positions      : 10      book holds 11
        max_aggregate_risk_at_stop_pct: 0.05    last read 5.03%

    and the governor has been saying the second half every 300s since 26 August:

        Aggregate risk-at-stop 5.03% is over the 5.00% cap - sweep is disabled,
        so nothing will be sold to correct it. It falls as positions close or as
        equity rises, and rises as equity falls

    Two independent blocks, either one sufficient. **The first live event of the
    next session will be an EXIT, not an entry**, and the entry watch only comes
    alive after a position closes.

    ⚠️ **Do NOT "fix" this by raising either cap.** Both are doing their job;
    the book got over the line through the sizing race above, and widening the
    rail to accommodate a race would hide the race.

    Wanted: entries sized within one cycle must see each other. Either the cycle
    sizes candidates against a snapshot it updates as it goes, or a candidate is
    re-checked against the book at sign-off — which is where the order becomes
    real anyway, and where the price-drift check (item 37) already sits.

59. ~~**⚠️ A RESTING-ORDER QUARANTINE CAN ONLY EVER BE DECLARED, NEVER LIFTED**~~
    **FIXED — the reconciler now lifts its own quarantine after
    `CLEAN_SCANS_BEFORE_CLEAR = 3` consecutive clean scans** (15 minutes at the
    300s poll). The operator button stays, so a release need not wait.

    **Why auto-clearing is defensible here and would not be in general:** this
    is not "the symptom went away". It is the SAME rail, over the SAME input,
    running the SAME derivation and reporting the negation - a stronger warrant
    than a human clicking without re-deriving anything, which until now was the
    only way.

    ⚠️ **Hysteresis because a divergence can flap.** Clearing on the first clean
    scan would let the store track noise. `declare()` resets the run, so the
    counter is of CONSECUTIVE clean scans and not a tally.

    ⚠️ **Scoped to what the scan could SEE.** A symbol the broker did not report
    says nothing about that symbol, and counting it clean would lift on absence
    of evidence - items 34 and 37's shape.

    ### ⚠️ THE STORE TESTS DID NOT TEST THE WIRING, AND THE FALSIFICATION FOUND IT

    Six tests covered the store and all six stayed GREEN when
    `saw_clean_scan` was deleted from `_reconcile_resting_orders` - because
    nothing drove the reconciler. **That is item 56's first regression guard
    exactly**: a guard built at a layer no path from the defect reaches.
    `test_a_clean_scan_lifts_a_quarantine_the_reconciler_declared` now runs the
    real reconciler over a broker whose book justifies everything, and it DOES
    go red when the call is removed.

    ORIGINAL: **A resting-order quarantine can only ever be declared, never lifted —
    AND TWO ARE LIVE RIGHT NOW ON A CONDITION THAT NO LONGER EXISTS.** Found
    27 August at launch, from the app's own startup line.

        09:16:31 WARNING Restored 2 resting-order quarantine(s) from
                 resting_order_anomalies.json: SEK.AX, WOW.AX
        09:17:41 INFO    RESTING ORDER SCAN: 22 working leg(s) across
                 11 symbol(s), nothing unjustified

    **The scan and the store disagree, and nothing reconciles them.** The stored
    reason is dated `2026-08-26T05:17:11` — the doubled book of item 56, fixed
    in M148 that evening.

    ### The mechanism, and it is not subtle

    `_reconcile_resting_orders` (`oms.py:1991-2009`) iterates
    **`for divergence in divergences:`** and calls `declare()` inside that loop.
    A CLEAN scan has no divergences, so the loop body never runs — **there is no
    symmetric clear.** The store's own comment says *"`declare()` below still
    runs every scan regardless, because the anomaly store must stay current even
    when the log stays quiet"* — but "current" only ever means *more*.

    `clear()` has exactly ONE caller in the whole codebase:
    `risk_console.py:477`, an operator button. **So a quarantine outlives its
    cause until a human notices and clicks.**

    ### What it costs

    `submit_order` refuses a quarantined symbol at `oms.py:325`, naming it
    `resting order anomaly - ...`. **SEK.AX and WOW.AX cannot be entered**,
    today or in any later session, until someone clears them by hand.

    ✅ **Entries only, and that is verified rather than assumed.** The check sits
    in `submit_order(candidate: OrderCandidate, ...)`, the entry sizing path.
    Protective exits are the brackets already resting AT THE BROKER — all 22
    legs, `4 unprot x0` — so nothing about this can stop the account
    de-risking. The rail fails in the SAFE direction.

    ⚠️ **But safe is not the same as right.** It refuses two symbols for a
    reason that stopped being true, says so only in a startup line nobody reads
    twice, and would be invisible the moment entries resume. It is the silent
    narrowing this project has now been bitten by three times.

    ### ⚠️ A CORRECTION: `5a34fa5` claimed these cleared. They did not.

    That commit recorded *"both quarantines cleared on their own."* **Wrong, and
    worth stating plainly because a future reader would trust it.** What cleared
    was the resting-order SCAN, which stopped reporting divergences. The
    QUARANTINE is a different store with no automatic clear, and it survived the
    restart into the next session. Two stores, one checked, the other assumed to
    have followed.

    ### Minor, in the same place

    The stored text reads *"2978 shares of resting sell the book does not
    justify (holds 2978)"* — an excess of 2978 while holding 2978, which is
    self-contradictory as an English sentence. It comes of summing BOTH OCA
    bracket legs against a single position. Whatever the arithmetic intends, an
    operator reading that line in an incident cannot act on it.

    Wanted: a clean scan should clear a quarantine whose divergence has gone —
    or, if automatic clearing is judged too permissive for a risk store, the
    startup line must say **how old** the quarantine is and that the current
    scan disagrees with it, so the staleness is impossible to miss.

61. ~~**⚠️ THE WORKBENCH'S AI NOTE BELIEVES THE ACCOUNT IS FLAT.**~~ **FIXED IN M149, ✅ CONFIRMED
    28 August 08:56:28** — by an audit line that had to be built first (M153):

        Advisory context for SUN.AX: 10 position(s), IS held,
        risk metrics ABSENT, verdict built, 0 corporate-action note(s)

    All ten positions reached the model, SUN.AX flagged held, the verdict built,
    no WARNING. ⚠️ **The note still did not MENTION the holding** — that is the
    model's choice, not missing data, and the two were indistinguishable until
    the line existed. `risk metrics ABSENT` is correct pre-open.

    ⚠️ **A SEPARATE, SMALLER ITEM FALLS OUT.** `build_regime_narrative_prompt`
    says *"Summarise the current market regime and what it implies for
    positioning, citing the supplied context only"* and never directs the model
    to WEIGH existing exposure. It has the position and no instruction to use
    it. That is a PROMPT question, not a data one — see item 65.
    ORIGINAL: **The Workbench's AI note believes the account is flat. It is the
    SIBLING of the regime gap that was fixed three lines above it.** Found by
    the operator on 27 August, who ran a backtest and a walk-forward on SUN.AX
    and read the note saying *"Given no current positions and lacking portfolio
    risk metrics..."* while the account held **3,192 SUN.AX**.

    **The commentary is wrong, and the note is formed on a false premise.**

    ### The asymmetry, in one table

    Both screens call `build_advisory_context`. What each actually passes:

    | argument | Advisor | Workbench |
    |---|---|---|
    | `regime_label` / `regime_probs` | ✅ | ✅ *(fixed earlier)* |
    | `fundamentals` | ✅ | ✅ |
    | **`positions`** | ✅ | ❌ |
    | **`risk_metrics`** | ✅ | ❌ |
    | **`verdict`** (M136 rule checks) | ✅ | ❌ |
    | **`position`** (the held lot's own facts) | ✅ | ❌ |
    | `fetched_notes` | ✅ | ❌ |

    Every missing argument defaults to `None` and becomes an empty dict. Nothing
    errors. The model is simply told the account holds nothing.

    ### ⚠️ It is the sibling, and the comment that closed the first half is
    three lines above the gap

    `workbench.py:566` carries this, on the regime arguments:

    > The defect this closes: it passed "unknown" and formed a recommendation
    > against no regime at all, while the Advisor formed one against the live
    > regime for the same company.

    **Exactly the same sentence is true of positions today.** M126's whole
    purpose was that the two screens cannot reach different views of one
    company. The regime half was found and fixed; the account half was never
    checked. This is the fourth instance of *check whether the fix has a
    SIBLING* in three days.

    ### Why the tests did not catch it

    `build_advisory_context`'s own docstring asserts the invariant:

    > Both screens call this. They differ ONLY in what they can legitimately
    > supply ... and never in what they fetch

    **That sentence is false as written**, and the test built to defend it only
    covers the second clause. `test_both_screens_get_the_same_fetched_material`
    compares `_FETCHED = ("symbol", "next_earnings", "news")` - the material the
    BUILDER fetches for itself. Its sibling test's docstring states the trap
    outright: *"`fundamentals` and `position` are SUPPLIED by the caller, not
    fetched, so asserting the two calls agree on them proves nothing when both
    default to empty."*

    So the suite knows supplied fields default to empty, and **nothing checks
    that the Workbench supplies them.** The guard covers the builder; the defect
    is at the call site.

    ### What it costs

    Advisory only - no rail, no sizing, no order path. But the one real action
    on that screen is **Deploy to Paper**, and the note is the commentary an
    operator weighs before pressing it. Forming that advice believing the
    account is flat removes exactly the considerations that should temper it:
    existing exposure in the same name, concentration, and correlation. On
    SUN.AX it is sharper still - the book is five financials of ten and SUN is
    one of them.

    Wanted: the Workbench passes the same account facts the Advisor does. ⚠️
    **And a test at the CALL SITES, not the builder** - one that constructs both
    screens' calls and asserts neither drops an argument the other supplies.
    A guard on the builder alone is what let this through.

62. ~~**⚠️ THE MACRO AI PROPOSES AN EXPOSURE SCALAR ON NO STATED SCALE, AND HAS
    NEVER SEEN THE ONE THE DETERMINISTIC READ JUSTIFIES.**~~ **FIXED in M149, ✅ CONFIRMED LIVE 28 August.**
    The model now names the hint and reasons about it:

    > *"The deterministic read already proposes an exposure hint of 0.85, which
    > aligns with a neutral stance. No additional macro factors justify
    > deviating from this figure, so we keep it unchanged."*

    Proposed 0.85 — which IS `neutral` in `MACRO_REGIME_EXPOSURE_HINT` — and
    named no HMM regime. Yesterday it returned 0.40, a value in neither position
    of this table, with no reference to the hint beside it.

    ⚠️ **0.40 → 0.85 is NOT the proof and must not be quoted as it.** The
    deterministic read moved Risk-On (1.00) → Neutral (0.85) overnight, so the
    two days are not like-for-like. The proof is that it NAMED and REASONED
    about the hint — which is the criterion set in advance, precisely so a
    changed number could not be mistaken for a fix.

    ORIGINAL: Found by the operator, who read the Regime Monitor
    showing, one line above the other:

        Deterministic read (STW.AX): Risk-On ... Exposure hint 1.00.
        Proposed exposure scalar: 0.40   (proposal only - not applied)

    and asked why a majority-bullish, Risk-On market would draw a 0.40.

    ### ✅ First, the reassuring half: NOTHING APPLIES IT

    `suggested_exposure_scalar` has exactly ONE consumer in the codebase -
    `regime_monitor.py:221`, which prints it. The schema says so too: *"a
    proposal only. Nothing applies it… letting a model move risk settings on
    its own was a materially larger trust delegation than letting it comment on
    them."* The operator's instinct that this needs human intervention is
    correct, and the boundary held.

    ### ⚠️ TWO EXPOSURE VOCABULARIES, AND 0.40 IS NOT IN THIS ONE

    | table | values |
    |---|---|
    | `MACRO_REGIME_EXPOSURE_HINT` (this screen) | risk_on **1.0**, neutral **0.85**, caution **0.6**, risk_off **0.3** |
    | `_EXPOSURE_SCALARS` (the HMM regime engine) | bull 1.0, recovery 0.9, low_vol 1.0, sideways 0.7, bear 0.5, **high_vol 0.4**, recession 0.3 |

    **0.40 exists only in the second**, where it means `high_vol` - a table
    belonging to the component that OWNS `RiskEngine.regime_scalar` and is
    deliberately its only writer. The macro read cannot produce 0.40 in any
    state.

    ### The cause: the model was never given the anchor

    `MacroSignal.exposure_hint` is a property. The screen renders it. But
    `to_dict()` - **the only part of the signal that reaches the prompt** -
    did not carry it. And `build_macro_analysis_prompt` named no scale at all,
    while the schema constrains the field to nothing tighter than
    `Field(ge=0.0, le=1.0)`.

    So the screen invited a comparison between two numbers where **only one
    side had the relevant input**. The model was not disagreeing with 1.00; it
    had never seen 1.00.

    ### ✅ NOT item 61, and worth saying so rather than crying wolf

    `get_macro_assessment` passes `positions={}` and `risk_metrics={}` **on
    purpose**, and the code says why: *"this is a market-wide question, and
    keeping positions out is what lets `LLMRouter` send it to the general slot
    rather than forcing the sensitive one."* A considered routing decision, not
    an omission. Two empty dicts in two screens, one a defect and one correct -
    which is exactly why "the context looks thin" is not by itself a finding.

    ### The fix

    1. `to_dict()` carries `exposure_hint`, with its docstring stating the rule
       that was broken: **a field left out here is a field the model does not
       have**.
    2. The prompt names the macro scale, anchored, and says the figure is a
       REVISION of `exposure_hint` on the SAME SCALE - so naming the table is
       not just four more numbers to ignore.

    ⚠️ **The HMM's table is deliberately NOT named in that prompt.** Showing
    the model a second scale invites precisely the crossover that produced 0.40,
    and `MACRO_REGIME_EXPOSURE_HINT`'s own comment already warns that two
    independent things writing one scalar "would make the applied exposure
    impossible to attribute to either". A test asserts the HMM regime names stay
    out.

    The anchor is literal text rather than rendered from the table, because
    importing it would point `ai_advisory` at `macro_analysis` and that package
    states it "imports nothing from the rest of" the domain. A test pins the
    text against the real table instead - **falsified by changing 0.30 to 0.35
    and watching it go red**, so the drift it exists to catch is a demonstrated
    catch rather than a hope.

    ### ⚠️ What this does NOT establish

    It does not show the 0.40 was wrong. A model can argue for defensiveness at
    `bull=0.47` with recovery and low_vol splitting most of the remainder. What
    is established is that the proposal was **uninformed and unconstrained**.
    Whether an anchored prompt produces a different number is the read-back
    check for this change, and it has not been run.

63. ~~**⚠️⚠️ THE CLOSED-TRADE LEDGER'S HEADER IS STALE**~~ **FIXED in M150 and
    CONFIRMED live 27 Aug** - both files repaired on load, second launch silent.
    ORIGINAL: **The closed-trade ledger's header is stale, and three fields are
    UNREADABLE ON EVERY ROW — INCLUDING THE ONE `EdgeEstimator` FILTERS ON.**
    Found 27 August after the close, from the ledger file itself.

        HEADER  30 fields   ...,best_price,market,currency,
        ROW     32 fields   ...,44.4523,,,ASX,AUD,1216558924

    ### Measured, by reading the file exactly as the app does

        rows read back: 6
          symbol       = 'RHC.AX'
          r_multiple   = '2.4737'      ← fine
          exit_reason  = 'target'      ← fine
          market       = ''            ← should be 'ASX'
          currency     = ''            ← should be 'AUD'
          order_id     = None          ← the key does not exist
          restkey(None) = ['AUD', '1216558924']

        market values across every row: ['', '', '', '', '', '']

    **The data is not lost.** `ASX`, `AUD` and the order id are all present in
    the rows, at the right positions. They are simply past where the header
    stops naming columns, so `csv.DictReader` hands them back under the wrong
    names or strands them in the restkey.

    ### The cause: a header written once and never migrated

    `_record` (`trades.py:1128`) writes the header only when the file is NEW:

        is_new = not self.path.exists() or self.path.stat().st_size == 0
        writer = csv.DictWriter(handle, fieldnames=_FIELDS, ...)
        if is_new:
            writer.writeheader()

    Rows are then appended under the CURRENT `_FIELDS` forever after. So every
    field added since the file was created - `earnings_at_entry`,
    `held_through_earnings` (both landing under the names `market` and
    `currency`), then `market`, `currency`, `order_id` themselves - is written
    into rows and never named in the header.

    ⚠️ **And the amendment path preserves the staleness by design.**
    `_read_closed_rows`' docstring: *"keyed by whatever header the file actually
    has - not `_FIELDS` - so a row is read and, if untouched, written straight
    back under the schema it already had."* That is right for not clobbering
    data and it also guarantees the bad header survives every amendment.

    ⚠️ **`order_id`'s own comment shows the half that was thought about:**
    *"Added while the file already has rows without it - `from_row` reads it
    with `.get()` for exactly that reason."* A ROW missing a field was handled.
    A HEADER missing the NAME was not. The same one-direction shape as items 56,
    58, 59 and 61.

    ### What it costs

    1. ⚠️⚠️ **`EdgeEstimator` can never measure an edge.** It calls
       `closed_trades(strategy, market=self.settings.market)` and the filter is
       a strict `trade.market == market`. Every restored row has `market=None`,
       so **the filter matches nothing and will match nothing at 20 trades or at
       200** - the sizer stays on its invented 0.55 / 1.5 constants forever,
       reporting `source="default"` for a reason that has nothing to do with
       sample size. **This is M122's rail, silently never binding.**
    2. **M71/M147's exit-price amendment cannot target its row after a
       restart** - it matches on `order_id`, which reads back as absent.
    3. `earnings_at_entry` and `held_through_earnings` are unreadable too.

    ✅ **No live harm has occurred YET**, and that is worth stating precisely:
    at 6 closed trades the estimator is below its 20-trade threshold and would
    have used defaults anyway. The cost is entirely in the future, which is
    exactly why it would not have announced itself.

    ### The fix, in two separable parts

    * **Code:** on append, compare the on-disk header against `_FIELDS` and
      REWRITE the file's header when they differ. The rows already match
      `_FIELDS` order, so nothing else has to move.
    * **Data:** the existing file needs its header line replaced.
      ⚠️ **This is the only record of realised P&L this system has.** It gets a
      dry-run script and a backup first, per the standing rule about live data
      writes - never an inline edit.

    ⚠️ **Check `equity_curve.csv` for the same shape before assuming it is
    clean.** It has its own `_FIELDS` (`trades.py:1207`) and the identical
    write-header-only-if-new logic at `:1276-1278`.

64. ~~**⚠️ ITEM HEADINGS OUTLIVE THEIR FINDINGS**~~ **PIN BUILT** -
    `tests/test_open_items_are_still_open.py`. ⚠️ **AND IT HAPPENED AGAIN THE
    SAME DAY**: items 58, 63, 64 and 66 all had their BODIES updated and their
    HEADINGS left stale, found on 28 August by listing unstruck items. The pin
    catches an open item that gets FIXED; it cannot catch a heading whose body
    already says so. Four more, hours after writing this.
    ORIGINAL: **Item headings outlive their findings, and one of them was dangerous.**
    **TWELVE found in two days.** The first four by tripping over them; the last
    three by finally LOOKING, in a ten-minute audit that closed three items for
    the cost of five greps. That ratio is the argument for doing the audit
    before the work, not after.

    | item | heading said | truth |
    |---|---|---|
    | 28 | the kill switch is TRIPPED | clear since 26 Aug 22:02:22 |
    | 32 | **the kill switch DOES NOT survive a restart** | it has since M144 |
    | 38 | the console calls a parked order "approved" | fixed in `de8b8d1` |
    | 61 | the Workbench believes the account is flat | fixed in M149 |
    | 37 | the drift guard may never run | fixed, and exercised today |
    | 39 | the chart's x-axis renders bar indices | fixed in `62660ae` |
    | 50 | the build stamp renders its date in UTC | fixed in M145 |
    | 35 | `ib_async` orderStatus noise | in `NOISY_LIBRARY_LOGGERS` |
    | 51 | a refused Gateway kills the app | fixed in M125 |
    | 52 | `SessionController.active` is True | addressed in M108 |
    | 36 | `poll()` promises a control | appears fixed |
    | 19 | is the CI rule real? | answered NO on 24 Aug |

    **Item 32 is the one that mattered.** A reader trusting it would believe a
    restart clears a halt - the opposite of the truth, and an invitation to the
    restart-to-clear that item 32 was written to prevent.

    Item 38 was found by beginning to RE-IMPLEMENT a fix that already existed.
    That is the cost in its plainest form: the list is the work queue, and a
    stale entry spends real time.

    ⚠️ **The bodies are right; the headings rot.** Every one of these had
    correct detail underneath a first line that had stopped being true, which is
    why reading further would have caught it and skimming did not.

    ### ✅ BUILT — `tests/test_open_items_are_still_open.py`

    ⚠️ **It asserts each open item's defect is STILL PRESENT**, so the day
    someone fixes one without updating this file, it goes red and names the
    item. That inverts the usual direction deliberately: **these tests are
    EXPECTED to fail when the code improves.** A red there is not a regression,
    it is this list falling behind, and the fix is to update the heading and
    delete the entry.

    Pinned open: 25, 29, 31. Pinned closed (so a fix cannot quietly regress):
    35, 51, 54, 58, 59, 63.

    ⚠️ Only genuinely grep-able claims are in it. Most items cannot be pinned
    this way and are not pretended to be — a guard that covered everything by
    weakening what it asserts is the failure it exists to prevent. And a missing
    file FAILS rather than skipping, which is `test_corporate_action_has_every_reader`'s
    own recorded lesson.

    ORIGINAL WANT: a check that can fail. Several items name a commit, a milestone or a
    file that would let a test assert the claim still holds - `grep`-able facts
    like "`_EXPOSURE_SCALARS` contains 0.4" or "risk_console renders
    'risk-approved'". Not every item can be pinned, and the ones that can should
    be, the way `test_corporate_action_has_every_reader` pins its own claim
    rather than trusting a sentence.

65. ~~**The Workbench's note receives the account and is never told to use it.**~~
    **DONE 28 August, DEPLOYED as of 30 August.** `build_regime_narrative_prompt` now
    asks the model to say what the regime implies GIVEN what is already held,
    naming concentration in one name or one sector.

    ⚠️ **CONDITIONAL on something being held.** A standing instruction to weigh
    holdings, handed a flat account, invites a discussion of a position that
    does not exist. Pinned in both directions - removing it turns five tests
    red, making it unconditional turns the empty-book guard red.

    ⚠️ **And it says the note is NOT a risk control.** Telling a model to weigh
    exposure invites it to sound like one; the rails decide and the note
    comments, so the prompt states that rather than leaving it to tone.

    ⚠️ **VERIFY IT WITH THE AUDIT LINE, NOT THE NOTE.** A note that mentions a
    holding proves the model chose to; one that does not proves nothing without
    `Advisory context for ...`. That distinction is what made item 61
    answerable, and it applies here unchanged.

    ORIGINAL:
    Falls out of item 61's confirmation on 28 August: the context provably
    carried all ten positions and `SUN.AX ... IS held`, and the note still made
    no reference to the holding.

    `build_regime_narrative_prompt` asks for a summary of the regime and what it
    implies for positioning, "citing the supplied context only". Nothing asks
    the model to weigh EXISTING exposure — concentration, correlation, or the
    fact that the symbol under test is already held.

    ⚠️ **Not urgent and not a rail.** The one real action on that screen is
    Deploy to Paper, and the operator can see their own book. Recorded because
    the fix for item 61 was justified partly on the model being able to temper a
    recommendation with exposure — and it demonstrably has the facts and no
    instruction to.

    Wanted: name the holding in the prompt when the symbol is held, the way the
    macro prompt now names `exposure_hint`. ⚠️ **Verify with the audit line, not
    by reading the note** — a note that mentions a holding proves the model
    chose to, and one that does not proves nothing without the line.

66. ~~**⚠️ HALF THE REGIME FEATURES ARE US DATA ON AN AUSTRALIAN BOOK**~~
    **MEASURED 28 Aug: `credit_spread` moves the label on ZERO of 249 bars.**
    Two US columns still unmeasured - `vix_level` and `yield_curve_slope`.
    ORIGINAL: **Half the regime features are US data on an Australian book, and one of
    THEM MEASURES +0.004.** Raised by the operator on 28 August. Recorded here
    because it was previously buried in Milestone B's "what this plan does NOT
    do" section, where nothing would surface it.

    | column | source | market |
    |---|---|---|
    | `log_return` | STW.AX | 🇦🇺 |
    | `realized_vol` | STW.AX | 🇦🇺 |
    | `breadth` | the 94 ASX symbols | 🇦🇺 |
    | `vix_level` | `VIXCLS` | 🇺🇸 |
    | `yield_curve_slope` | `T10Y3M` | 🇺🇸 |
    | **`credit_spread`** | **`BAA10Y`** | 🇺🇸 |

    **The label that sets position size on a 94-stock ASX book is half
    classified on American data.** That is Milestone B's stated goal in one
    line, and it is still true.

    ⚠️ **`BAA10Y` is the weakest thing measured here: +0.004 against forward ASX
    volatility** (25 August), where `BAMLH0A0HYM2` carries +0.160. +0.004 is
    indistinguishable from nothing — in a column feeding a sizing input.

    **This is NOT Milestone C.** C builds the instrument; this is the first
    question to put to it. Scheduled: `--feature credit_spread` is now Milestone
    C's Task 6 Step 3, ahead of `asx_vix_z`, on the operator's call —
    removing a column that measures +0.004 is a cheaper and cleaner question
    than adding one that moves the label on 23% of bars.

    ### ⚠️⚠️ THE FIRST FOUR MEASUREMENTS WERE WORTHLESS. RETRACTED.

    On 28 August this file briefly recorded *"`credit_spread` moves the label on
    ZERO of 249 bars"*. **That was wrong, and so were the three runs beside it.**
    The harness was not ablating anything: `replay_session.py` built its
    `RegimeEngine` without `features`, so both arms used the default six columns
    and were byte-identical. `NOT EXERCISED` was a truthful statement about the
    arms and a meaningless one about the feature.

    ⚠️ **A CONTROL IS WHAT CAUGHT IT.** `breadth` is ASX-derived and central to
    the matrix; ablating it returned the identical result to `credit_spread`.
    Two columns of wholly different importance cannot both be inert, and that
    was the only reason to look. **The three runs before the control were
    believed.**

    ⚠️ **AND THE STILL ENABLED GUARD DID NOT FIRE**, because it read the
    manifest — which was written from the INTENDED feature list. It checked
    intent, not effect. It now reads the list off the engine that actually ran.

    ### ✅ MEASURED PROPERLY, 28 August — ALL FOUR, WITH A CONTROL

    | column | source | label differs | equity |
    |---|---|---|---|
    | `vix_level` | VIXCLS 🇺🇸 | **213 of 249 (86%)** | −661.99 |
    | `credit_spread` | BAA10Y 🇺🇸 | 104 of 249 (42%) | +233.81 |
    | `yield_curve_slope` | T10Y3M 🇺🇸 | 75 of 249 (30%) | −698.27 |
    | `breadth` | ASX-derived 🇦🇺 | 67 of 249 (27%) | −375.12 |

    ⚠️⚠️ **THE QUESTION WAS ASKED THE WRONG WAY ROUND, AND THE ANSWER IS
    WORSE THAN THE WORRY.** The concern was that the US columns might be
    carrying nothing on an Australian book. **All three are MORE influential
    than the ASX-derived control**, and `vix_level` alone moves the label on
    86% of bars. The regime label on a 94-stock ASX book is not merely informed
    by American data - it is *dominated* by it.

    ⚠️ **AND M146 DID NOT FIX THAT.** Milestone A found *"raw feature spread is
    led by `vix_level` at 85.0% of the total"* and made the matrix
    scale-neutral so no column could dominate by SCALE. It still dominates by
    INFORMATION, at 86% of labels. Standardisation addressed the units and left
    the influence untouched — those were always different questions, and only
    the ablation could tell them apart.

    ⚠️ `credit_spread` is NOT inert either, at 42% - the opposite of what its
    +0.004 forward-vol correlation suggested in isolation.

    ⚠️ **DO NOT read the equity deltas as results.** Ten trades per arm on a
    baseline of -7.25R and a 10% win rate. At n=10 those figures are noise; the
    LABEL movement is the measurement, and even that is one window.

    ⚠️ **THE LESSON, and it is the day's most expensive:** a marginal
    correlation of +0.004 said the column was worthless and the joint model says
    it moves 42% of labels. Milestone B's plan warned of exactly this — *"a
    feature can contribute through interaction while looking weak alone"* — and
    it took an ablation to see it. That is what the instrument is FOR.

    ### What this does and does not license

    ⚠️ **It does NOT say the US columns are wrong.** American volatility
    genuinely leads Australian equities, so a dominant `vix_level` may be the
    model working. What it says is that the influence is now MEASURED rather
    than assumed, and that it is far larger than anyone had reason to think.

    ⚠️ **One window, and ten trades per arm on a -7.25R baseline.** The equity
    column is noise at that count and must not be quoted; the label movement is
    the measurement.

    ### ✅ REPLICATED ON TWO DISJOINT WINDOWS, 28 August

    `--until 375` replays bars 250-375; `--from 125` replays 375-499. **No bar
    is in both.**

    | | earlier<br>2025-08-21→2026-02-18 | later<br>2026-02-19→2026-08-14 | full |
    |---|---|---|---|
    | `vix_level` 🇺🇸 | **85%** | **83%** | **86%** |
    | `credit_spread` 🇺🇸 | 16% | 56% | 42% |
    | `yield_curve_slope` 🇺🇸 | 21% | 73% | 30% |
    | `breadth` 🇦🇺 | 18% | 65% | 27% |

    **Baseline regime diversity, which is what makes the rest readable:**

    | | earlier | later |
    |---|---|---|
    | dominant label | **bear 78%** | bear 35% |
    | distinct labels | 4 | 6 |
    | transitions | **3** | **8** |

    ⚠️⚠️ **THREE OF THE FOUR FEATURES TRACK THE WINDOW, NOT THEMSELVES.**
    `credit_spread`, `yield_curve_slope` and `breadth` all score 16-21% on the
    monotone window and 56-73% on the diverse one. **A label that barely moves
    cannot be moved by removing a column**, so a bare ablation percentage
    measures how CONTESTABLE the window was as much as how influential the
    feature is. The comparator now prints the baseline's label spread and
    transition count beside the percentage, and a test pins it.

    ⚠️ **`vix_level` IS THE EXCEPTION, AND THAT MAKES ITS RESULT STRONGER.** It
    flips 85% of labels in a window that is 78% bear with THREE transitions -
    it is not moving the label at boundaries, it is DETERMINING it.

    ### ✅ THE MAGNITUDES DO NOT REPLICATE. THE RANK ORDER DOES.

        earlier  vix_level > yield_curve_slope > breadth > credit_spread
        later    vix_level > yield_curve_slope > breadth > credit_spread

    **Identical on both disjoint windows**, while every magnitude except
    `vix_level`'s moved by three to four times. That is the comparison the
    window effect leaves intact: WITHIN a window all four features face the same
    contestability, so their order is informative even when their percentages
    are not.

    ⚠️ **SO ITEM 66 DOES HAVE AN ANSWER, and it is not the one it started
    with.** `credit_spread` (BAA10Y) is the LEAST influential of the four
    columns, last in both windows. But least is not nothing: it still moved 56%
    of labels in the contestable window, so **"BAA10Y is dead weight" is not
    supported** — it is simply the weakest of four columns that all matter less
    than `vix_level`.

    ⚠️ **And the three US columns do NOT cluster.** `vix_level` is first and
    `credit_spread` last, with the ASX-derived `breadth` between them. Whatever
    is driving the label, it is not "US data" as a bloc - it is the VIX
    specifically. Item 66's framing, that half the features are US and therefore
    suspect, is the wrong cut.

    ⚠️ Rank stability over TWO windows is still two. It should be checked on a
    third before the ordering is treated as settled.

    Wanted next, in this order:
    1. ~~**Repeat on a second window.**~~ **DONE for `vix_level` and `breadth`.**
       Still needed for `credit_spread` and `yield_curve_slope`.
    2. Then Milestone B's `^AXVI` question, which is now much sharper: adding an
       Australian volatility column to a matrix whose label is 86% driven by an
       American one.
    3. ⚠️ **Always with a control.** A control is the only reason today's first
       four numbers were caught, and it cost one extra run.

67. ~~**⚠️⚠️ M151's FILTER WAS ON THE WRONG HANDLER, AND REPORTED WORK IT DID
    NOT DO.**~~ **FIXED — DEPLOYED as of 30 August.** Found live at the 28 August open.

        10:20:36  yfinance market data has recovered - 678 per-symbol
                  'possibly delisted' error(s) were suppressed ...

        lines in the blind window : 797
        delisting errors IN THE LOG: 774

    `configure_logging` attached `BLIND_WINDOW_FILTER` to the **stdout** handler
    and never to the **file** handler. The packaged build is `--windowed` and
    has no console — `configure_logging`'s own docstring says a stdout-only
    configuration "discarded every line the moment the application was run the
    way it is actually shipped".

    ⚠️ **Worse than not working.** It suppressed on a stream nobody reads and
    then ASSERTED the suppression on the line an operator would use to conclude
    the log was clean. A missing fix is a gap; a fix that reports work it did not
    do is a false assurance, and this one was quotable.

    ⚠️ **ITEM 59'S MISTAKE, REPEATED — and the lesson had already been written
    into Milestone C's constraints the day before.** M151's tests proved
    `BlindWindowFilter.filter()` suppresses and counts. Nothing proved it was
    ATTACHED. A guard at a layer no path from the defect reaches.

    ### ⚠️ AND THE OBVIOUS FIX WOULD HAVE INTRODUCED A SECOND DEFECT

    `filter()` runs once per HANDLER. Attaching it to both without more would
    have counted every suppressed record TWICE, and the recovery line would have
    reported double what it dropped — replacing a false assurance with a wrong
    number. Records are now tagged so one record counts once, pinned by a test,
    and by its opposite so the tag cannot become a latch that only counts one.

    The new tests drive `configure_logging` and inspect the handlers it
    installs. They are scoped to handlers carrying `JsonFormatter` — what the
    APP owns — because pytest injects its own, and because "at least one
    handler has it" is precisely the assertion that would have passed all along.

68. **⚠️ I FIXED ITEM 29 AND THEN DID IT AGAIN, WITHIN THE HOUR.**
    `scripts/deploy.ps1` and `scripts/record_deploy.py` exist to keep
    `handoff_state.DEPLOYED` true. I built them, deployed M155 by the OLD
    hand-run script, and left `DEPLOYED` reading `0b1ecd6` (M148) - stale
    through the very deploy that shipped the fix for it being stale.

    Found at handover by MEASURING the state instead of writing it from memory,
    and corrected to `9bd111a` with the new tool.

    ⚠️ **The mechanism was never the problem; not using it is.** A tool built
    and then bypassed is worth less than the exhortation it replaced, because it
    reads as solved. **Use `scripts/deploy.ps1` for every deploy from now on** -
    the ad-hoc scratchpad scripts used all week are gone with their session, and
    that is deliberate.

    ⚠️ Same session, same shape: a `str.replace` in a heredoc silently no-opped
    SIX times, each one a Windows path where `` or `
` is a valid escape.
    Every one was caught by grepping for the string just written. The habit that
    works is the edit tool, which ERRORS on a failed match.

## 📋 PROMPT TO PASTE — next session

Continuing QAT (Quant Advisory Terminal) at C:\Claude Programming.
Paper account throughout - no real money.

READ THE STATE FIRST, and trust it over anything in this prompt:

    & "C:\Claude Programming\scripts\session_check.ps1"   (NO ARGUMENTS, EVER)
    .\.venv\Scripts\python.exe scripts\handoff_state.py

Then read docs\HANDOFF.md. Read the 26 AUGUST incident section before touching
the order or absorb path.

⚠️ POWERSHELL for anything touching %LOCALAPPDATA%\QuantAdvisoryTerminal -
including Python that only READS it, and anything that builds Settings(), which
loads that directory's .env whether or not the script mentions it. The Bash
sandbox serves a frozen snapshot and does NOT error. It cost a worthless dry run
on 28 August: it reported a 301-row, 3-column equity curve for a file that is
2,894 rows and 5 columns.

⚠️ DO NOT PUSH. Standing operator hold since 27 August, still in force. Commit
locally as normal. This is NOT mere caution: CI is at the GitHub billing wall,
so every push fires a run that dies in ~4s with zero steps and emails a failure -
20 such emails in one week. A NAS copy covers the backup risk. Only the operator
lifts this. THE LOCAL SUITE IS THE ONLY VERIFICATION; run all four checks and
treat them as final.

⚠️ DEPLOY WITH scripts\deploy.ps1 (dry run first, then -Apply). M156 was the
first deploy to actually use it, which is what item 68 was about - the tool had
been built and then bypassed within the hour.

THE STATE

  Deployed M156 (17f5ca9), installed 28 August 21:35. Exe SHA256 B1B9E99D...8566,
  signature Valid on the INSTALLED copy.
  ⚠️ NEVER LAUNCHED - the first launch is the read-back.
  Rollback: C:\QuantAdvisoryTerminal.bak-9bd111a-20260828-2135

  Tree clean at HEAD. DEPLOY GAP ZERO - the build and the tree are level, and
  the script recorded it after verifying the installed copy. 68 commits unpushed.
  Suite 2,951 passed / 26 skipped. ruff, black, mypy src, bandit clean.
  App STOPPED. Nothing is running. Gateway was up on 4002 on 28 August.

  TEN POSITIONS, all bracketed, 20 resting legs:
  A2M ANZ ASX BOQ IAG PNI SEK SUN TNE WOW.
  RHC.AX exited 27 Aug at TARGET, +5,736.57 net, 2.47R.

  KILL SWITCH CLEAR. No quarantines (resting_order_anomalies.json is empty).
  Order flow LIVE and autonomous execution enabled on the next launch.

  SIX CLOSED TRADES: five LOV.AX and one RHC.AX. ⚠️ One LOV row is a REPAIR row
  with EMPTY costs, so net P&L across LOV is NOT summable from that file.

⚠️ FIRST WORK: LAUNCH AND READ M156 BACK. It has never run.

  Expect `Build: M156 (17f5ca9, ...)`, 10 positions adopted, and NO
  header-repair or quarantine lines - their absence is M150 and the 27 August
  clearance confirming themselves.

  ⚠️ THE ONE NUMBER TO READ AT THE OPEN: aggregate risk-at-stop. M155 carries
  item 31, which LOOSENS a rail, and M155 has now run but was never read at an
  OPEN market. It was measured as a no-op against the book on 28 August (20
  orders: 10 Submitted, 10 PreSubmitted, ZERO in either added state), but a
  no-op then is not a no-op now. Read it before trusting any entry decision.

  ⚠️ AN ENTRY CANNOT HAPPEN AT TEN POSITIONS. governor.py:304 refuses at >=, so
  ten of ten is AT the cap and the book needs NINE. Items 56 and 58 are
  unexercised for that reason, not because they are unproven. On 28 August this
  cost 1,036 refusals and zero approvals across six symbols.

  WATCH, IN ORDER:

  1. M154's blind-window filter, at the bell. The recovery line should read
     "... has recovered - N per-symbol 'possibly delisted' error(s) were
     suppressed". ⚠️ M151 shipped this on the STDOUT handler only and asserted a
     suppression that never reached the log - 678 claimed against 774 still
     present. M154 put it on the file handler.
     A recovery line with NO count means it is still not working.
     NO delisting errors all session means it is over-reaching - a genuinely
     delisted symbol must stay visible.

  2. M155's four sizing-adjacent changes at an OPEN market: Milestone C's
     regime_features (default byte-identical), item 22's cap on SPENDABLE cash,
     item 31 above, item 59's quarantine auto-clear (needs a quarantine to
     exercise, and there are none).

  3. ON AN ENTRY, and this is NEW in M156: the entry record now carries
     reference_price, so `entry_slippage` on the resulting trade must NOT be
     empty. All six existing closed trades have it empty and always will - those
     reference prices were never written down. The first trade opened under M156
     is the check, and it must survive a RESTART before it counts, because
     losing it at restart is the entire defect.

  4. ON AN EXIT: ONE ledger row, full quantity, and RUN THE WIRE CHECK THE SAME
     DAY - IBKR execution retention is same-day only, measured twice:

         & ".\.venv\Scripts\python.exe" scripts\verify_exit_on_the_wire.py --symbol <SYM>

     A second exit takes the book to NINE, which is what unblocks entries.

  5. ON AN ENTRY: the transmit line carries a NUMERIC permId, not a UUID (item
     56, still unexercised - every such line back to 1 August carried a UUID).
     Two entries in one cycle should now see each other (item 58).

  6. FREE, NO MARKET NEEDED: the Dashboard's regime note now has an "Acknowledge
     note" button (item 18). Clicking it must write
     `Regime note ACKNOWLEDGED by the operator: regime <label>, at <ts>` to the
     log. It applies nothing - that is the point, and it is pinned by a test.

  7. FREE, NO MARKET NEEDED: Workbench -> backtest a held symbol. The log line
     "Advisory context for <SYM>: N position(s), IS held, ..." is the check.
     ⚠️ A note that MENTIONS the holding proves the model chose to; one that does
     not proves NOTHING without that line.

THEN, IN ORDER

  1. M43 - TRADING HALTS. Stopped BEFORE design on 28 August, deliberately.
     scripts\probe_halts.py is written and read-only; it needs ONE MARKET-HOURS
     RUN to conclude. What is known: there is no IBKR market-data subscription,
     and `halted` came back nan even on the working delayed feed. M39 is the
     precedent - corporate-action detection was designed, then found to have no
     feed behind it at all. Do not design this until the probe answers.
  2. MILESTONE B - the ^AXVI question. Milestone C exists and works, so this is
     now a sharper question than the one it was planned to answer: adding an
     AUSTRALIAN volatility column to a matrix whose label is 83-86% driven by an
     AMERICAN one. Plan: docs/superpowers/plans/2026-08-26-macro-milestone-b.md
  3. M44's OTHER HALF. reference_price is done. worst_price and best_price
     EVOLVE over a trade's life, so persisting them at open would restore a
     stale excursion - mae_r and mfe_r stay unmeasurable until that is built.
     It needs periodic persistence, not a field.
  4. Item 33 - never-ticked-this-session as its own refusal, distinct from
     stale. Adds a refusal to the entry path; wants a plan and a watched session.
  5. Reach 20 closed trades (item 3). At six. Below 20 the sizer uses invented
     constants; below 30 the promotion gate cannot be read. Needs market.
  6. The long-standing FEATURES: M39 corporate actions, M41 earnings event risk,
     Stage 3 ASX auction rules.

  ⚠️ HOUSEKEEPING, NEEDS AN OPERATOR DECISION: C:\ holds EIGHTEEN rollback
  directories totalling 7.06 GB, one per deploy back to 21 August. Ask before
  deleting any - they are the only rollback path for their build.

WHAT 27-28 AUGUST ESTABLISHED

  Nine builds M148-M156, every one read back except M156. Confirmed live:
  M119's feed retry (recovered unaided twice, 20 minutes blind each time),
  M147's absorb fix BOTH halves on a real multi-price wire, item 63's ledger
  repair, and items 61 and 62.

  FIFTEEN STALE HEADINGS were closed. Three were found by starting to
  RE-IMPLEMENT work that already existed; the rest by finally auditing rather
  than trusting the list. Item 37 sat on a work queue as tier-2 while its fix
  ran live in a session already read twice. Items 21 and 40 were fully fixed and
  still reading as open.

  MILESTONE C's FIRST FOUR MEASUREMENTS WERE WORTHLESS, and an ASX-derived
  CONTROL caught it - replay_session built its RegimeEngine without `features`,
  so both arms were identical and NOT EXERCISED was truthful about the arms and
  meaningless about the feature. The STILL ENABLED guard stayed silent because
  it read the manifest, written from the INTENDED list: it checked intent, not
  effect.

  MEASURED PROPERLY, on two disjoint windows: vix_level moves the label on
  83-86% of bars and REPLICATES. credit_spread, yield_curve_slope and breadth
  swing three- to fourfold with the window - so a bare ablation percentage
  measures how CONTESTABLE the window was as much as the feature. The RANK ORDER
  is identical on both windows. The US columns do NOT cluster: vix_level first,
  credit_spread last, ASX-derived breadth between them.

  ITEM 44's PREMISE WAS FALSE. It records the blocker as trade COUNT; in fact
  entry_slippage was empty on all six trades and would still be empty at twenty,
  because reference_price was never persisted. THIRD field this same record has
  lost across a restart, the other two documented in its own comments.

  ITEM 20's SWEEP FOUND NO HIDDEN VIOLATION - the honest result, and unlike
  M135, which was hiding one. Two of four guards could not tell you their green
  meant anything. A positive control found the worst narrowness on its first
  run: test_theme's hex scan required the colour to be the WHOLE literal, so
  "color: #b71c1c;" was invisible to the guard whose job is catching it.

HABITS THAT PAID FOR THEMSELVES

  RUN A CONTROL. One extra ablation caught four wrong answers that were about to
  be written down as findings.

  PLANT THE VIOLATION. An absence-asserting test reports the same empty list
  whether the codebase is clean or the scan has gone blind. Two halves are
  needed: a non-empty corpus says "we looked", a planted violation says "we can
  see". Neither substitutes for the other.

  A TEST NEVER SEEN TO FAIL IS NOT EVIDENCE - and it must fail AT THE LAYER THE
  DEFECT LIVES. Item 59's six store tests all stayed green when the caller was
  deleted; a source-level runtime guard caught a TypeError that would have
  stopped the app launching.

  THE FULL SUITE, NOT THE TARGETED ONE. Item 22's three green tests hid a broken
  order path; the suite found 134 failures and mypy had already named the cause.
  A fixture that returns a friendlier type than production proves the wrong
  thing.

  CHECK WHETHER THE FIX HAS A SIBLING. Task 2 fixed positional column reads in
  hmm_core and missed the identical shape in engine.py; the ablated arm then
  published zero regime bars.

  VERIFY THE ARTEFACT, NOT THE INTENTION. A str.replace in a heredoc silently
  no-opped SIX times this week, always a Windows path where \v or \r is a valid
  escape. Every one was caught by grepping for the string just written. Use the
  edit tool, which ERRORS on a failed match.

  MEASURE BEFORE SHIPPING A RAIL CHANGE. Item 31 loosens a rail; counting the
  live order statuses first showed it was a no-op on that book, which is what
  made it shippable without a session to read.

  A GUARD THAT CRIES WOLF GETS IGNORED. handoff_state's stale-figure check
  matched any "N tests" and its entire output was one false positive - a
  historical count of tests that FAILED. It now matches only a COLLECTED total,
  and deliberately does not check the "N passed" figure, because it never runs
  the suite and would be wrong by the skip count every time.
