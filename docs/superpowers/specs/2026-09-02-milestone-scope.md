# Scope — next milestone, gathered 2 September 2026

**SCOPE ONLY. No code written. Nothing built or deployed** — the ASX session was
open while this was gathered, and `sectors.py` and the UI files are all in
`src/`, compiled into the exe, so every item here needs a build and deploy after
a close.

Six items: one found by me, four raised by the operator, and a sixth (item 6,
the absent risk metrics) measured on 2 September after the M163 deploy.

---

## 1. ⚠️ M161's five new symbols bypass the 30% sector cap

**Already recorded in `HANDOFF.md` (commit `b55f868`) — repeated here because it
is item one of this milestone.**

`ALX.AX`, `CWY.AX`, `SDF.AX`, `SOL.AX`, `ANN.AX` are absent from
`qat.data.sectors.SECTOR_BY_SYMBOL` (102 ASX entries; none of the five). The
screener showed the symptom — ticker with no Sector — before any log line could.

⚠️ **Not cosmetic.** `signal_bridge.py:1422` uses `.get`, deliberately, so an
unmapped symbol has **no sector cap applied at all** rather than being lumped
into a shared "Unknown" bucket. That design is right; the defect is that M161
widened the tradable universe without mapping the new names.

⚠️ The app's own warning for this (*"…the 30% sector concentration cap cannot
apply to it (item 44)"*) **has never fired** — it triggers only when a signal for
that symbol reaches the bridge.

**Fix:** ALX Industrials, CWY Industrials, SDF Financials, SOL Financials, ANN
Health Care.

### ✅ SWEEP RUN 2 September — the gap is EXACTLY the five, and nothing else

Operator agreed to a full sweep. Run read-only against the live settings:

    watchlist resolved : 99      polled (incl benchmark): 100
    sector map entries : 204     UNMAPPED: 5
        ALX.AX  ANN.AX  CWY.AX  SDF.AX  SOL.AX
    mapped but NOT watched: 7 -> AWC, BKW, DHG, IOZ, IPL, NSR, SVW

**Coverage of the other 95 is complete.** The earlier caution — that 102 mapped
entries against 99 watched did not prove coverage — was worth raising and turned
out negative. Scope of the fix is settled and small: five entries.

⚠️ **AND THE MIRROR IMAGE, found by the same sweep.** Six of the seven mapped-but-
unwatched symbols are **AWC, BKW, DHG, IPL, NSR, SVW** — precisely the tickers
**M110 pruned as dead**. Their sector entries were never removed. Harmless in
itself (a lookup nobody queries), but it shows the watchlist and the sector map
are edited independently **in both directions**, which is the actual defect
behind item 1.

**So the milestone should carry a guard, not just five rows.** A startup
assertion — or a test — that every resolved watchlist symbol has a sector
mapping would have caught M161 on the day it was built, and costs one
comparison. `IOZ.AX` is a legitimate exception: it is in the `etf` watchlist
category, not `megacap`, so any guard must scope to the RESOLVED watchlist
rather than to every symbol the app knows.

---

## 2. The Positions "Status" column is blank for positions that ARE still held

**Operator observation:** information missing from Status, and *which* symbols
are missing **shifts across the day**.

### What the column actually reports

`position_view.py:144` appends `held until <date>` only when
`minimum_hold_status(...).blocked` is True. That is the same rule the order path
enforces, deliberately shared so the two cannot drift
(`signal_bridge.py:267`). It returns `blocked=False` when:

* the minimum hold has elapsed (`held_days >= min_holding_trading_days`, 10), or
* the **loss escape** fires: `loss_r = (entry - price) / (entry - stop)` and
  `loss_r >= min_holding_loss_escape_r` (**0.5**).

### Measured against the 2 September screenshot

Computed from `open_position_entries.json` and the displayed marks:

| | loss_r | shown | correct? |
|---|---|---|---|
| SEK | 0.510 | blank | ✅ escaped |
| JHX | 0.821 | blank | ✅ escaped |
| TNE | 0.506 | blank | ✅ escaped |
| **ANZ** | **0.079** | **blank** | ❌ **not escaped — unexplained** |
| **IAG** | **−0.175** | **blank** | ❌ **not escaped — unexplained** |
| BOQ | −0.394 | held until 08/09 | ✅ |
| A2M | 0.450 | held until 08/09 | ✅ |
| SUN | −0.162 | held until 08/09 | ✅ |
| WOW | 0.347 | held until 09/09 | ✅ |
| ASX | 0.263 | held until 08/09 | ✅ |

**Two findings, and they are different problems:**

**2a — the shifting is REAL BEHAVIOUR, and it is a UX defect.** SEK, JHX and TNE
sit at 0.51, 0.82 and 0.51 against a 0.5 threshold. As the price moves, a
position crosses back and forth and the note appears and disappears. Nothing is
broken — but a status that flickers with the tick teaches an operator to
distrust the column. It should say something stable, e.g. *"hold escaped (loss
0.51R)"* rather than falling silent, so the difference between "still held" and
"escapable now" is visible instead of inferred from an empty cell.

### ✅ 2a DONE — an escaped hold now says so

`position_view.py` gains an `elif status.loss_r is not None:` branch:
`hold escaped (0.60R down)`. Blocked still reads `held until <date>`; an
ELAPSED hold stays quiet, because it is no longer a constraint and would be
noise on every row for the rest of the position's life. `loss_r` is the exact
discriminator - `minimum_hold_status` populates it only when the escape was
reached and computed. Seen to bite: disabling the branch turns
`test_an_escaped_hold_SAYS_SO_rather_than_falling_silent` red.

### ❌ 2b WITHDRAWN — it does not reproduce

**Original claim, kept because it was acted on:**

**2b — ANZ and IAG are blank without escaping, and the rule does not explain
it.** Both opened 25 August 14:04:53, the same day as BOQ, A2M, SUN and ASX,
which DO show the note — so `held_days` is not the difference. ⚠️ **This is
unexplained and must be instrumented rather than guessed at.** Candidates worth
checking, in order: whether `entries` is missing these symbols at render time
(the `entry is None` early return produces exactly this blank), and whether the
view's `entry.stop_price` differs from the record I computed against.

⚠️ ANZ and IAG share an identical `opened_at` to the second. Probably
coincidence — two orders in one cycle — but worth a glance while instrumenting.

⚠️ **INSTRUMENTED 2 September, and the finding is WITHDRAWN.** A read-only probe
ran the REAL `minimum_hold_status` against live broker marks for all ten
positions:

    ANZ   mark 37.51   loss_r -0.163   blocked True   -> held until <date>
    IAG   mark  8.30   loss_r -0.577   blocked True   -> held until <date>
    JHX/SEK/TNE  loss_r 0.793/0.571/0.663  blocked False -> BLANK (escaped)

**All ten are correct.** ANZ and IAG render the note. The original claim came
from computing `loss_r` against the prices in a screenshot and reading those two
Status cells as empty; the rule does not reproduce it.

Two possibilities remain and cannot be distinguished from outside the app:
their Status text did not survive into the transcription of the image, or they
were genuinely blank at that moment for a reason this probe cannot see.
**Operator to watch for it next session.** 2a's fix makes that observation
decisive: with the escaped state now labelled, a blank cell inside a hold window
is unambiguous evidence of a bug rather than something to reason about from
prices.

---

## 3. Equity curve Y axis is unreadable

Renders as `1.004e+06`, `1.0042e+06`, `1.0044e+06`. Scientific notation on a
money axis, and five near-identical labels differing in the fourth decimal.

**Cause:** the range is tiny relative to the value — roughly $600 of movement on
a $1.004M base, so a full-precision axis has nowhere to put the difference.

**Options, for the design conversation rather than decided here:**
thousands-separated dollars (`$1,004,200`); an axis in **$k** or **$M** with the
unit in the label; or plotting **change from day-start** so the axis is centred
near zero and the shape is what carries the information. The last is the biggest
change and probably the most readable, but it drops the absolute NAV from view,
which some operators want. **Operator's call.**

---

## 4. The corporate-action banner is permanent furniture

*"CORPORATE-ACTION DETECTION UNAVAILABLE on this broker…"* occupies a full-width
orange band on the dashboard at all times.

⚠️ **The message is correct and must not be deleted.** It is a real, permanent
limitation — IBKR publishes no corporate-action feed, so a split cannot be seen
before its ex-date, entries are not gated on pending actions and resting stops
are not adjusted through one. The app already states it once at startup and the
monitor logs it once, calling it *"a property of the broker, not a failure to
retry"*.

**The problem is that a STANDING condition is rendered as an ALERT.** A banner
that is always present is one an operator stops seeing — and the day something
genuinely alarming appears in the same place, it will be read as furniture too.

**Options:** move it to a persistent status indicator (a capability row or a
footer chip with a tooltip carrying the full text); keep the banner but make it
dismissible with the state remembered; or show it only on the screen where it
changes a decision. **Requirement either way: the full wording must remain
reachable, not summarised away** — it explains a real gap in protection.

---

## 5. Daily and Weekly report history, newest first

Show report history ordered most-recent to oldest.

Needs a look at how reports are currently listed and whether "history" means the
files on disk or a rendered list in the app. Smallest item here; no findings yet.

---

## 6. ✅ MEASURED 2 September — why the AI advisory has no portfolio risk

Raised as *"portfolio_check appears in only 63 of 3,596 audit rows (1.8%), and
`risk_metrics()` reads ONLY the last entry"*, with two questions. Both are now
answered from the audit file itself rather than from the code.

### Q1 — why so rarely? BECAUSE THE BOOK IS FULL. It is not a logging defect.

All **3,533** rows without a `portfolio_check` carry **one** reason, and it is
the same one:

    3533  "already at the 10-position limit (10 held or pending)"
    3533  side = buy
    3533  furthest input key reached: `governor`

`inputs["portfolio_check"]` is assigned at `engine.py:311`. The governor's
position-count rejection returns at `engine.py:283` — one rail earlier. **A
candidate that was already refused never reaches the portfolio checker**, so
there is no number to record. The 1.8% is a measurement of how long the book has
been at 10 of 10, not of anything broken.

⚠️ **It self-corrects on the first exit.** The moment the book drops to nine,
candidates get past the governor and every one of them records a
`portfolio_check` again. This is the same event items elsewhere are waiting on.

### Q2 — should the read search back? NO, and staleness is the smaller reason.

⚠️ **`AuditLog._entries` is IN-MEMORY and is never rehydrated from the CSV.**
`audit.py:70` initialises it empty; `entries()` at `:116` returns
`list(self._entries)`. It holds **this run only**.

That breaks the proposal at the root:

* At **startup** `entries()` is empty, so `risk_metrics()` returns `{}` — the
  model gets nothing, every single run, before any decision happens.
* **Within** a 10-of-10 run the list contains nothing but governor rejections, so
  a search back over it finds nothing either.
* Searching back **across days** would mean reading `risk_decisions.csv`, which
  nothing does today. That is a materially bigger change than "search back".

And then the staleness trap M73's own comment names. The most recent stored
`portfolio_check` is:

    1,161 rows back   2026-08-31T00:30:06+00:00   JHX.AX (approved)
    var_95 0.01078  var_99 0.01482  es_975 0.01663
    single_name_pct 0.125  sector_pct 0.125

Two days old, and computed on an **8-position** book that no longer exists. Feed
that to the model as today's portfolio risk and it is exactly the failure the
docstring was written to prevent. **Any honest staleness bound rejects it** — so
a bounded search-back would be code that changes nothing while looking like a
fix. That is worse than leaving it alone.

### Q3 — the dropped fields. Two-thirds true, and cheap.

`risk_metrics()` filters to the hardcoded tuple `("var_95", "es_975")`. Across
all 63 rows that DO carry a check:

    var_95           present 63   non-null 63
    var_99           present 63   non-null 63     <- dropped, always available
    es_975           present 63   non-null 63
    single_name_pct  present 63   non-null 63     <- dropped, always available
    sector_pct       present 63   non-null  3     <- correctly omitted 60/63

`var_99` and `single_name_pct` are discarded despite being populated in every
case. Adding all three names to the tuple is safe: the existing `is not None`
comprehension already omits `sector_pct` on the 60 occasions it is null, which is
the "absent is omitted rather than zeroed" discipline the docstring states.

### Q4 — the operator's own tiles read the same source

Not raised, found while checking. `risk_console.py:574` and `dashboard.py:479`
both read `entries[-1].inputs["portfolio_check"]` and both `return` silently when
it is absent.

✅ `KpiTile` defaults to `"-"` (`widgets.py:13`), so a fresh run shows **dashes,
not a measured zero**. That is honest and needs no fix.

⚠️ **Latent, within-run:** once a tile HAS been set, a later absence leaves the
old number on screen with nothing marking it stale. Bounded to one run and to the
same book, so low severity — but it is the same shape as the Status-column defect
in item 2: a display that cannot distinguish "no value" from "last value".

### What would actually put a number in front of the model

The advisory wants **current portfolio risk** and is reading a **decision
artefact**. `PortfolioRiskChecker.check()` needs a candidate — it prices the book
*plus a proposed trade* — so nothing today computes risk over the held book
alone.

✅ The pieces exist and are already candidate-free:
`_combined_portfolio_returns` is a `@staticmethod` taking only
`(weights, returns, total_equity)` (`portfolio_risk.py:133`), and
`compute_historical_var` / `compute_expected_shortfall` are module-level
functions.

**Three options, operator's call:**

* **(a) Leave it.** The number returns by itself on the first exit. Costs
  nothing; the model still sees no portfolio risk on any 10-of-10 day or in any
  run before its first non-rejected decision.
* **(b) Widen the tuple** to `var_99` and `single_name_pct` (and `sector_pct`,
  which self-omits). Real, one line, tested — but it only helps on the occasions
  a check fires at all, so on today's data it changes nothing.
* **(c) Compute portfolio risk over the CURRENT book**, on the equity-sample
  cadence, independent of any decision — and feed THAT to the advisory and the
  tiles. The only option that gives the model a number today, and the only one
  that makes the tiles mean "the book right now". It is a new path, so it needs
  its own rails: what it does with fewer than N return observations, and what it
  shows when the book is empty.

(b) and (c) are independent and (b) is strictly smaller; doing (c) does not make
(b) unnecessary, because the audit rows should carry the full set either way.

---

## Sequencing

⚠️ **Everything above needs a build and deploy, so it lands after a close.**

Item 1 is the only one with live consequence: five tradable symbols are outside a
risk rail right now. Exposure is limited while the book is 10 of 10 — no entry
can happen — but the first exit unblocks one.

Item 2b is a genuine unexplained defect and should be instrumented before it is
"fixed"; 2a, 3, 4 and 5 are UX decisions where the operator's preference
decides.

Item 6 is ANSWERED, not open: the 1.8% is the position cap working, and the
proposed search-back is refused on evidence. What remains of it is a choice
between (a) nothing, (b) a one-line widening, and (c) a live book-risk path -
also the operator's.
