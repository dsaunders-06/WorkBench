# Position anomaly seam, and the protection-level fix — 8 August 2026

Design for the first piece of ROADMAP Group 1: **something outside this
application changes a held position, and reconciliation and protection misread
the result.** M39 (corporate actions) and M43 (halts) are the same problem
twice; this builds the part they share, plus one independent defect found while
measuring.

Three items, in the order they should land:

1. **`verify_position_stops` compares presence, not level.** Standalone,
   independent of everything else here, and it bites today.
2. **One measurement is still outstanding**, and it has a deadline of
   Tuesday 11 August. Not implementation work — a decision, recorded here so it
   is not lost.
3. **The position-anomaly seam**: reconciliation being able to be told a
   difference is explained, and a position being in a state the ordinary path
   must not treat as ordinary.

## What was measured on 8 August, so it is not re-derived

Three read-only probes against the paper account. No orders placed. The
ROADMAP's own instruction for this work was to *"start by measuring what the
broker reports through a split rather than by reasoning about it"*, and this is
that measurement, as far as it can currently go.

**Alpaca announces splits precisely.** A forward split is
`old_rate=1.0, new_rate=4.0` — the ratio is `new/old`. A reverse split inverts
it (`old_rate=1000.0, new_rate=1.0`). Each record carries `ex_date`,
`record_date`, `payable_date`, `target_symbol`, `target_original_cusip` and a
stable `corporate_action_id`. `GetCorporateAnnouncementsRequest` accepts a
`symbol` filter server-side, so a detector queries one symbol rather than
sifting the ~1,600 records a year the market produces.

Two traps in that data:

* **`target_symbol` is absent on roughly 10% of records** — 32 of 291 reverse
  and 8 of 63 forward splits in an 88-day sample. A market-wide scan is
  therefore unreliable, and the per-symbol query is the right shape.
* **`payable_date` can precede `ex_date`.** CRWD's are 1 July and 2 July.
  `ex_date` is the one to key on.

**`TradingClient` wraps no account-activities method** in alpaca-py 0.43.5;
activities are Broker-API-only there. The REST endpoint
`/v2/account/activities/{type}` answers directly and returns HTTP 200.

**This account has processed zero corporate actions, ever.** `SPLIT`, `MA`,
`NC`, `SPIN`, `REORG` and `DIV` all return 200 with no rows; `FILL` returns
100. Nothing held is currently exposed.

### The near-miss that shaped the design

**CRWD split 4-for-1 with ex_date 2 July 2026.** We hold 16 CRWD. We bought on
31 July — *after* the split — at 187.40, and the OCO resting against it
(stop 163.32, limit 235.20) is correctly sized for 16 post-split shares.
Nothing is wrong with the position.

That is exactly why it matters. **A detector matching on symbol and ratio over
a recent window would flag our CRWD holding as split-explained today, and be
wrong.** The false-positive case is not hypothetical; it is in the book. Any
future detector must gate on `ex_date` falling after `_entries[symbol].opened_at`.

It is also the reason the automatic detector is *not* in this spec. The piece
that can be wrong in the dangerous direction — declining to halt on a
divergence that is not a split — is the piece being deferred until there is
evidence to build it against.

## Item 1 — `verify_position_stops` compares presence, not level

`OMS.verify_position_stops` (`src/qat/domain/oms/oms.py`) drops a stop from
`_position_stops` only when the symbol is **absent** from what the broker
reports resting:

```python
lost = [
    symbol
    for symbol in list(self._position_stops)
    if symbol in held and symbol not in resting
]
```

So a stop whose **level** changes at the broker — for any reason, not only a
split — is never noticed. The app's belief stays at the level it recorded, the
symbol is still present in `resting`, and the check passes.

This matters beyond bookkeeping. `_position_stops` is what
`PortfolioGovernor` measures risk-at-stop against: a position with a known stop
risks the distance to that stop, one without risks its whole value. A belief
that is wrong by a factor makes the aggregate wrong, and the aggregate is at
**5.02% against a 5.00% cap**, which is what currently gates entries in every
*other* symbol. A wrong denominator does not stay in one symbol.

**The fix.** Compare levels as well as presence. A symbol whose resting level
differs from the recorded belief is reported, and the recorded belief is
replaced by what the broker actually says — the broker is the authority on what
is resting, which is the rule this codebase already applies everywhere else.

The comparison is **relative, not absolute**: `abs(resting - believed) >
1e-4 * believed`. An absolute epsilon cannot serve a book holding both WFC at
87 and GS at 1,040 — a tolerance loose enough to absorb rounding on the latter
is blind to a real move on the former. A relative test is scale-free, and at
1e-4 it absorbs cent-level rounding on every price in the book while catching
any move that could matter. It is logged at ERROR and named, in the same shape as
the existing `POSITION UNPROTECTED` line, because a protective level moving
without this app moving it is exactly as significant as one disappearing.

Independent of items 2 and 3. Lands first. Fix-immediately under the freeze —
*"protective orders not resting, or not being repaired"*.

## Item 2 — the measurement still outstanding

**What Alpaca does to a held quantity, and to a resting OCO, when a split
occurs, has zero observations.** The announcements endpoint says nothing about
it and this account has never processed one.

That is the single premise on which any "leave the protection alone, Alpaca
adjusts it" design would rest, and it cannot be settled by reasoning.

**MNST splits 2-for-1 with ex_date Tuesday 11 August.** Holding a small
position with a stop attached through Tuesday would answer it directly. Nine
other forward splits follow through August (SFBS and IESC 2-for-1 on 21 and
24 August, APH 2-for-1 on 3 September).

**This is a decision for the operator and is deliberately not implementation
work.** It is recorded here because it has a deadline — before Monday's close —
and because the answer determines the shape of M39 step 2. The contamination
cost needs weighing first: it would add an eleventh position to a book with a
ten-position limit, already at the risk cap. Noted in mitigation, and to be
confirmed rather than assumed: a position opened outside the app has no entry
record, so `restore_open_lots` skips and names it, meaning it would not enter
the closed-trade evidence the trial exists to collect.

If the measurement is not taken, M39 step 2 waits for a real event, and the
behaviour meanwhile is what item 3 provides.

## Item 3 — the position-anomaly seam

### The concept, and where it lives

A new module, `src/qat/domain/oms/anomaly.py`:

```python
@dataclass(frozen=True)
class PositionAnomaly:
    symbol: str
    reason: str              # the operator's own words
    declared_by: str         # who said so
    declared_at: datetime    # UTC
    tracked_quantity: float  # what the app thought, at declaration
    broker_quantity: float   # what the broker said, at declaration
```

and a `PositionAnomalyStore` persisting to `position_anomalies.json` in the
data directory — the same shape as `open_position_entries.json` and the
absorbed-fill state, so it survives a restart by construction rather than by
luck.

Its own module rather than a dict on the OMS, because two components read it —
the OMS for reconciliation and order admission, the signal bridge for re-arm
and lot restore — and it has a persistence lifecycle of its own.
`signal_bridge` already imports from `oms`, so reaching it through
`self.oms.anomalies` adds no new import direction.

### The binding rule, which is the whole idea

```python
def explains(self, symbol: str, tracked: float, broker: float) -> bool
```

True only if there is an active anomaly for that symbol **and the broker still
reports the quantity recorded when it was declared.**

Without that binding, declaring a symbol explained once grants it permanent
immunity, and the next genuine divergence passes silently. That is precisely
the failure `adopt_broker_positions` already warns about — it *"trains an
operator to ignore the one signal that means my view of the account cannot be
trusted"*. A divergence declared explained at 16→64 does **not** explain a
later 64→128.

### The reconciliation seam

`OMS.check_reconciliation` builds `divergent` and trips. It gains one filter:
divergences the store explains are partitioned out before the decision.

* **Unexplained** — ERROR, kill-switch, `return True`. Identical to today.
* **Explained** — logged once per symbol per session, and excluded from the
  return value. Once per session rather than once per poll, following the
  repeat-trip guard already on `KillSwitch.trip`, which exists so a recurring
  condition does not flood the log or overwrite the original cause.

`ReconciliationMonitor.poll` publishes `KillSwitchEvent` on `True`, so keeping
the return value meaning "a *halting* mismatch was found" needs no change
there. A separate accessor exposes the explained set to the Risk Console.

### The quarantine — five call sites

Every active anomaly quarantines its symbol. The rule is **block writes, allow
exits**, enforced where the decisions actually are. Exits, trims and entries
are already separate call sites, so nothing new is needed to tell them apart.

| Site | Behaviour |
|---|---|
| `OMS.submit_order` | **Refused.** After the allow-list check and before the kill-switch check, so the rejection names the anomaly rather than a generic halt. Produces an ordinary rejected order, so it reaches `risk_decisions.csv` and the refusal analysis. |
| `OMS.submit_exit_order`, `reason="delever"` | **Refused.** A trim sized against a known-wrong quantity is the trim doing damage. |
| `OMS.submit_exit_order`, any other reason | **Allowed**, and re-reads `broker.positions()` to size the exit, because the tracked quantity is known-wrong. If that read fails it refuses and records why — a transient broker failure recorded as a rejected order per M54, not a silent pass-through of a bad quantity. |
| `SignalToOrderBridge.rearm_protective_stops` | **Skipped**, at ERROR. This is the liquidation guard: `_entries[symbol].stop_price` is the pre-event level, and re-arming from it is what liquidates the position at the next open. |
| `SignalToOrderBridge.restore_open_lots` | **Skipped**, at WARNING. |

That last one needs its reason stated. `restore_open_lots` takes **quantity
from the broker** and **price and stop from `_entries`**. After an external
quantity change it builds a lot at the post-event size on the pre-event basis —
*silently*, because the entry record exists so no `unknown` warning fires. P&L
is then wrong by the event's factor and the R-multiple is wrong in its
denominator too, feeding the 30-trade promotion gate and the September
evidence.

**`_Entry` carries no quantity** — only `opened_at`, `price`, `stop_price`,
`target_price`, `strategy` — so there is nothing to compare a broker quantity
against and no cheaper guard available. The quarantine is the mechanism.
Skipping produces a visibly missing lot rather than a quietly wrong one, which
is the rule that module already applies to an unknown stop.

### Defeating the restart laundering

`adopt_broker_positions` does `self._filled_quantities = dict(adopted)` —
wholesale from the broker. A restart therefore makes any divergence *vanish*:
tracked matches broker, reconciliation is content, and the entry record and
ledger stay wrong. With an overnight session and a restart between each one,
that is the normal path, not an edge case.

Three changes:

* The store loads from disk **before** adoption.
* After adoption, an active anomaly whose recorded `broker_quantity` no longer
  matches what was just adopted means a *further* change on an already-suspect
  position: ERROR, and it stays quarantined.
* The adoption banner gains a line naming quarantined positions. The operator
  is instructed to read the startup lines and treat their absence as the
  signal, so this belongs there and not only in the UI.

### Surfacing

Risk Console gets the active list, a **declare explained** action and a
**clear** action. Declaring needs the current tracked-versus-broker pair, which
the console obtains by forcing `poll()` — already public for exactly this.

Group 4 renders it on the Dashboard later. When it does, the M58c rule holds:
the quarantine indicator and its colour are identical at every expertise level
and only the explanatory prose is level-gated. **Safety is not a level.**

### Testing

Following the M56a rule — *a test whose fixture cannot reach the failure is not
evidence* — these write real state rather than asserting over empty
collections.

Item 1:

* A resting stop whose level has moved is reported and the belief is corrected.
* A resting stop at the recorded level is left alone.
* A broker that cannot answer changes nothing — an adapter without the
  capability must not read as "no stops rest anywhere".

Item 3:

* An explained divergence does not trip the kill-switch; an unexplained one does.
* **The immunity test:** an explanation recorded at broker=64 does not explain a
  later broker=128.
* Quarantine: buy refused, delever trim refused, re-arm skipped, lot restore
  skipped, ordinary exit allowed and sized from the broker.
* Exit allowed when the broker read succeeds; refused with a recorded reason
  when it fails.
* **The laundering test:** a data directory containing a persisted anomaly,
  adoption run against a broker reporting the post-event quantity, asserting the
  symbol is still quarantined and the ERROR was emitted. That fixture must
  contain the persisted file — an empty data directory is what let M56a's guard
  test pass while the defect shipped.

## Deliberately out of scope

* **Automatic split detection.** Deferred until item 2 reports. The CRWD
  near-miss above is why: the detector is the piece that can be wrong in the
  direction that declines to halt.
* **Any adjustment** of tracked quantity, entry record, resting protection or
  ledger basis. That is M39 step 2, and it is where the four-way atomicity risk
  lives.

**This does not repair damage; it contains it.** A declared anomaly stays
quarantined until the underlying records are corrected by hand — as was done
for CVS on 6 August. "Declared" must not read as "fixed" on any screen, and the
wording must say so.

## Position under the validation freeze

All three items are fix-immediately, and none changes which trades the strategy
chooses or how it sizes them.

* Item 1 is *"protective orders not resting, or not being repaired"*.
* Item 3 is *"the kill-switch tripping on something that is not a real
  discrepancy"*.

Item 3 adds no automatic judgement. The application halts less **only** where a
human has explicitly said why, and otherwise refuses strictly more than it does
today.

## Open decisions

* **MNST, before Monday's close.** Item 2. Operator's call.
* **Where declaration happens.** The design says Risk Console. A file-based
  declaration — a JSON the app reads and binds to the broker quantity at load —
  would be smaller and closer to how the CVS correction was actually worked,
  at the cost of nothing on screen prompting toward it. Risk Console is the
  default unless changed.
