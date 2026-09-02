# Scope — next milestone, gathered 2 September 2026

**SCOPE ONLY. No code written. Nothing built or deployed** — the ASX session was
open while this was gathered, and `sectors.py` and the UI files are all in
`src/`, compiled into the exe, so every item here needs a build and deploy after
a close.

Five items: one found by me, four raised by the operator.

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

**2b — ANZ and IAG are blank without escaping, and the rule does not explain
it.** Both opened 25 August 14:04:53, the same day as BOQ, A2M, SUN and ASX,
which DO show the note — so `held_days` is not the difference. ⚠️ **This is
unexplained and must be instrumented rather than guessed at.** Candidates worth
checking, in order: whether `entries` is missing these symbols at render time
(the `entry is None` early return produces exactly this blank), and whether the
view's `entry.stop_price` differs from the record I computed against.

⚠️ ANZ and IAG share an identical `opened_at` to the second. Probably
coincidence — two orders in one cycle — but worth a glance while instrumenting.

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

## Sequencing

⚠️ **Everything above needs a build and deploy, so it lands after a close.**

Item 1 is the only one with live consequence: five tradable symbols are outside a
risk rail right now. Exposure is limited while the book is 10 of 10 — no entry
can happen — but the first exit unblocks one.

Item 2b is a genuine unexplained defect and should be instrumented before it is
"fixed"; 2a, 3, 4 and 5 are UX decisions where the operator's preference
decides.
