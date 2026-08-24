# Reconciling resting orders — design

**Outstanding item 23**, and the highest-value item on the list. On 24 August an
interrupted session left **sixteen orphaned GTC bracket legs** at the broker
with the application holding no record of any of them. A flat TNE.AX carried up
to 12,304 shares of automatic short risk, buying power would not have refused
it, and **nothing in the application was watching**.

The item asks a question before it asks for work: *establish whether anything
adopts or reconciles open ORDERS.* This document answers that first, because the
answer changes what needs building.

---

## What exists today, and why it was blind

The answer is **no** — but not for the reason the item assumes. The hard part is
already built. It is pointed the wrong way.

`IBAdapter.resting_stop_orders` (`ib_adapter.py:389`) already performs a
broker-wide scan using `reqAllOpenOrdersAsync`, and its docstring already sets
out why `openTrades()` is the wrong call — it returns only the connected
client's orders, so *"invisible protection reads as NO protection"*. That
lesson was learned and written down before 24 August. The scan is correct.

Three narrowings downstream of it made the sixteen legs invisible.

**1. The translate boundary discards half of every bracket.**
`from_ib_resting_stop` (`ib_translate.py:392`) returns `None` for any order
whose type is not in `_IB_STOP_TYPES`. A bracket's take-profit leg is a LIMIT
order, so **it is dropped before anything can count it**. Eight of the sixteen
legs could not have been seen by any consumer at any point.

**2. The result is keyed by symbol, one record per name.**
`resting_stop_orders` returns `dict[str, RestingStopOrder]`. Sixteen legs across
two symbols collapse to at most two records; the surplus is discarded after a
single warning line. The data structure cannot represent the defect.

**3. The only consumer skips flat symbols explicitly.**
`OMS.verify_position_stops` (`oms.py:1038`) iterates the app's own belief
`_position_stops` and then does:

```python
if symbol not in held:
    continue
```

That line is the one that let TNE carry 12,304 shares of resting sells. A flat
symbol is not merely uncovered by accident — it is passed over deliberately,
because the function's question is "is my protection still there", and a
position that no longer exists needs no protection.

### The shape of it

Every order-side check in this codebase asks **"is what I believe still
there?"**. Nothing asks **"what is there that I do not believe in?"**

`check_reconciliation` (`oms.py:1802`) gets this right for POSITIONS. It builds
a union — `set(self._filled_quantities) | set(broker_positions)` — so a holding
the app knows nothing about is still compared. Orders have no equivalent, and
`BrokerAdapter` (`adapter.py:262`) exposes no all-open-orders method at all.

This is the same family as M104: the fourth boundary, the one that was missed
while three others translated correctly.

---

## The constraint that shapes everything below

**Order identity does not survive a restart.** `_broker_order_ids` and `_orders`
are in-memory and empty after a restart (`version.py:501`, recorded as the
deeper fact behind M140).

So a reconciler **cannot** classify an order as orphaned by asking "did I place
this?" — after a restart the honest answer is always no, and the 24 August
orphans were themselves inherited across exactly such a restart. Classification
must be **arithmetic against the position**, the way M140's guard was.

---

## The problem that makes this harder than it looks

TNE.AX right now holds **3,051 shares**, bracketed at 30.69 and 36.86. That is a
stop for 3,051 **and** a target for 3,051 — **6,102 shares of resting sell
against a 3,051 long.**

A reconciler that sums closing-side resting quantity and compares it to the
position would flag **the one position this system has ever placed correctly**
as carrying 3,051 shares of naked short risk, on its first run.

The legs are one-cancels-all; only one can ever fire. **Any rule that does not
collapse OCA groups is wrong**, and it would be wrong in the most damaging
direction — a false positive on the first live outing, on the position that
proves M139 works.

Measured against the installed **ib_async 2.1.0**, not read from documentation:
`Order` exposes `ocaGroup`, `ocaType`, `parentId`, `parentPermId`,
`totalQuantity` and `filledQuantity`. The grouping is buildable.

---

## Design

### 1. One scan, not two

`BrokerAdapter` gains `open_orders() -> list[RestingOrder]`. `RestingOrder` is a
new frozen dataclass in `adapter.py`:

| Field | Source | Why |
|---|---|---|
| `symbol` | `from_ibkr(contract.symbol)` | M104 — every IBKR boundary translates |
| `order_id` | `permId or orderId` | the id the rest of the app knows an order by |
| `side` | `order.action` | grouping and netting happen per side |
| `order_type` | `order.orderType` | **not** filtered on — see below |
| `quantity` | `orderStatus.remaining` | a half-filled stop carries half the risk |
| `oca_group` | `order.ocaGroup` | primary group key |
| `parent_perm_id` | `order.parentPermId` | fallback group key |
| `owner_client_id` | `order.clientId` | the visible-but-not-cancellable trap |
| `status` | `orderStatus.status` | working-status filter |
| `why_held` | `orderStatus.whyHeld` | item 26's locate condition is visible here |
| `stop_price` / `limit_price` | `auxPrice` / `lmtPrice` | so the log can name the level |

`IBAdapter.open_orders()` makes the single `reqAllOpenOrdersAsync()` call and
translates via a new `from_ib_open_order`, which — unlike `from_ib_resting_stop`
— **discards nothing by order type**.

**`open_orders()` applies NO status filter and NO type filter.** It returns what
the broker returned, translated, with `status` carried as a field. Filtering is
each consumer's own business.

That is not tidiness — it is what makes the operator's separability decision
hold structurally. `resting_stop_orders()` is rewritten to derive from
`open_orders()` rather than issuing its own call, and if `open_orders()` did the
status filtering, `from_ib_resting_stop` would silently inherit the **wide** set
and the sizing change we just agreed to defer would ship anyway, unannounced,
inside a change that claims to move no sizing input. Exactly the M31a /
`from_ib_trade` combination this design already cites twice.

So: `open_orders()` filters nothing; `from_ib_resting_stop` keeps applying
`_IB_WORKING_STATUSES` unchanged; the orphan scan applies its own wide set. A
test asserts that `resting_stop_orders()` returns the same result before and
after the derivation, which is what proves the inheritance did not happen.

The consolidation itself is not a new idea: `resting_stop_orders`' own docstring
already argues for it — *"One scan rather than two, because two could disagree
about what counts as protection."* Leaving both calls in place would create
precisely the second scan it warns about.

### 2. The rule, as a pure function

New module `src/qat/domain/oms/resting_orders.py`. No I/O, no broker, no clock,
no logging — so every case below is a table-driven unit test.

```
unjustified_resting_risk(orders, positions) -> list[SymbolOrderDivergence]
```

Per symbol, per side, over working statuses only:

1. group key = `oca_group`, else `f"parent:{parent_perm_id}"`, else `f"solo:{order_id}"`
2. take the **max** quantity within each group — only one leg of an OCA group can fire
3. **sum** across groups
4. justified SELL = `max(held, 0)`; justified BUY = `max(-held, 0)`
5. excess = resting − justified, beyond a `1e-6` tolerance

Grouping happens **within a side**, so a still-working BUY parent never nets
against its SELL children.

#### The working-status set is M139 sitting in the code again

Step 1 filters on "working statuses", and the app's answer to that is
hand-maintained: `_IB_WORKING_STATUSES` (`ib_translate.py:380`) is
`{PreSubmitted, Submitted, PendingSubmit}`.

Measured against the installed ib_async 2.1.0, `OrderStatus.ActiveStates` is
`{PreSubmitted, Submitted, PendingSubmit, ApiPending, ApiUpdate,
ValidationError}`. **`ApiPending` and `ApiUpdate` are missing from the app's
set.**

This is precisely M139's defect — *"`_IB_STATUS_MAP` had four entries and none
of IBKR's working states"* — surviving in a second hand-maintained status set
that M139 did not touch. Here it fails in the **unsafe direction**: an orphan
sitting in `ApiPending` is invisible, so resting risk is **under**-counted and
the rail reports an all-clear it has not earned.

**The orphan scan derives its set from `OrderStatus.ActiveStates` rather than
restating it**, so an ib_async upgrade cannot silently narrow it again — with
one documented subtraction, `ValidationError`, which ib_async counts active but
which is not an order that can fill. The subtraction is written at the
definition with its reason, and a test asserts the derived set against
`ActiveStates` so a future divergence fails the suite instead of passing
quietly.

> **The same bug also affects existing behaviour, and is deliberately NOT fixed
> here.** `from_ib_resting_stop` uses the narrow set, so a protective stop in
> `ApiPending` currently reads as no protection: `verify_position_stops` drops
> it from `_position_stops` and logs `POSITION UNPROTECTED` for a position that
> is in fact protected. That direction is conservative for sizing and merely a
> false alarm — the opposite of the orphan scan's failure — but it is the same
> defect.
>
> Fixing it moves a sizing input, so per the operator's decision below it is
> **split out into its own item** and `_IB_WORKING_STATUSES` is left untouched
> by this change. See *What this changes, and what it does not*.

Verified against the three states that matter:

| State | Resting | Held | Result |
|---|---|---|---|
| TNE tonight | one group, max 3,051 | 3,051 | **clean** — no false positive |
| 24 Aug, mid-incident | four groups × 3,076 = 12,304 | 3,076 | excess **9,228**, flagged |
| 24 Aug, after unwind | eight legs, flat | 0 | **every leg unjustified** |

Both directions are measured, so an orphaned BUY on a flat symbol is caught as
well as an orphaned SELL. That is deliberate: the item's language is about short
risk because that is what happened, but unaccounted long risk is the same
defect.

> **Residual, recorded rather than lost.** This rule is arithmetic, never
> identity, because identity does not survive a restart. It holds only while the
> application's entries are MARKET orders (outstanding item 44 — *"Every order
> is a market order"*), so nothing of its own ever rests unfilled. **If this
> application is ever given resting entry orders, this rule must be revisited**,
> or a legitimate working limit buy on a flat symbol will read as an orphan.

### 3. What it does about it

`OMS.check_resting_orders()`, mirroring `check_reconciliation`'s shape, called
from `ReconciliationMonitor.poll()` and once from `start()` immediately after
`adopt_broker_positions()`.

**Startup is the run that must not skip it.** The 24 August orphans were
inherited across a restart; a poll-only rail would have found them five minutes
late, and `session_check`'s third check has been reporting *"NO ADOPTION LINE IN
THIS RUN — protection is unverified"* ever since.

An adapter without `open_orders` returns `[]` and **nothing is judged**. This is
the defensive pattern `verify_position_stops` already uses, and the reason is
its docstring's: a missing capability must never be read as "no orders rest
anywhere", which would be a fabricated all-clear.

On a divergence, the log names **every leg individually** — id, side, type,
remaining quantity, price, owner client id — at ERROR. "Sixteen orphaned legs"
was established by hand on 24 August and should have been one log line.

### 4. A store that structurally cannot lie

New `RestingOrderAnomalyStore`, same persistence conventions as
`PositionAnomalyStore`, **with no `explains()` method at all.**

This is not fastidiousness. `PositionAnomalyStore.declare()` binds an anomaly to
`broker_quantity`, and `explains()` (`anomaly.py:130`) then returns `True` for
any position divergence at that quantity — which `check_reconciliation`
(`oms.py:1810`) uses to **suppress the kill-switch trip**.

Quarantining a flat symbol through `declare(..., broker_quantity=0.0)` would
therefore grant that symbol immunity from the position-reconciliation halt at
broker=0 — **the exact rail that caught the real mismatch on 24 August.** Item
23's fix would have partially disabled item 27's.

That is the `M31a` / `from_ib_trade` shape exactly: two individually correct
decisions combining into a defect. It is recorded here because it was found by
reading `explains()` before writing code, and the next person deserves to know
the trap was deliberate to avoid rather than absent by luck.

A test asserts the attribute's absence, so re-adding `explains()` fails the
suite rather than quietly restoring the interference.

Consulted alongside `anomalies.is_quarantined` at the entry gate
(`signal_bridge.py:863`) and the exit and re-arm paths (`:542`, `:667`), plus a
refusal reason in `refusals.py` so it renders on the Blotter. That row is not
optional decoration: `refusals.py:131` records that M60's `"position anomaly"`
was never added and every quarantine refusal therefore rendered as *"not
recognised - see the note below"* from 8 August onward — *"precisely the failure
this module exists to prevent, committed against this module."* Adding a
quarantine reason without its refusal row would commit it a third time.

### 5. Cancelling

`resting_order_cancel_enabled: bool = False`.

When enabled, cancels **only on symbols the book is flat in.** No protection
exists to strip, so there is no choice about which group survives. A held symbol
carrying excess is reported and quarantined but **never trimmed**: choosing
which OCA group dies is a judgement this application should not make unattended,
and getting it wrong strips the stop from a real long — the failure
`verify_position_stops` exists to shout about.

Off by default follows the house precedent set at `delever_sweep_enabled`
(`config.py:358`): *"a rail that sells without being asked is a bigger
delegation than one that merely blocks buying."* Cancelling is a smaller
delegation than selling, but it is still the app acting on the account
unattended, on a detector with no field history.

Each cancel is attempted independently. A failure — notably **error 10147**, the
measured trap where an order visible to `reqAllOpenOrders` is not cancellable
from this connection — is logged with its `owner_client_id` and stepped over. One
refusal must not abort the remaining legs.

### 6. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `resting_order_reconcile_enabled` | `True` | detection and quarantine |
| `resting_order_cancel_enabled` | `False` | permission to cancel on flat symbols |

Cadence reuses `reconciliation_poll_seconds` (300s). No new poll loop: the check
belongs on the rail that already asks the broker what it holds.

### 7. Operator surface

A fifth check in `session_check.ps1`, alongside the existing four, reporting
unjustified resting quantity by symbol. The four checks are how every defect on
24 August was actually confirmed, and a rail with no line in that output is a
rail nobody reads.

---

## Testing

The pure function carries the weight, because it is where the false positive
would live:

* **TNE's current 3,051 / 6,102 bracket does NOT flag** — an explicit named
  regression test. This is the single most important assertion in the change.
* 24 August mid-incident: 12,304 against 3,076 held → excess 9,228.
* 24 August after unwind: eight legs, flat → all unjustified.
* Partial fills — remaining, not `totalQuantity`.
* An ungrouped solo stop, grouped under `solo:`.
* A SHORT position protected by BUY stops — justified, not flagged.
* Mixed sides on one symbol, netting independently.
* Non-working statuses ignored — and an order in `ApiPending` **counted**, the
  case the current set misses.
* The derived working-status set asserted against `OrderStatus.ActiveStates`,
  so an ib_async upgrade that adds a state fails the suite rather than
  narrowing the scan in silence.

Then: adapter missing the capability judges nothing; store persistence
round-trips; **`RestingOrderAnomalyStore` has no `explains` attribute**; cancel
is off by default; cancel when on touches flat symbols only and never a held
one; a cancel failure does not abort the remaining legs.

`from_ib_open_order` gets translate-level tests including the take-profit LIMIT
leg that `from_ib_resting_stop` drops, and `resting_stop_orders` keeps its
existing tests unchanged — if deriving it from `open_orders` breaks them, the
derivation is wrong.

> **When a new guard breaks an old test, check the fixture before the guard**
> (M140's lesson). The existing `resting_stop_orders` tests are the contract
> here, not an obstacle.

---

## Out of scope

* **Cancelling excess on HELD symbols.** Deliberate, per §5.
* **Persisting order identity across restarts.** The real fix for the deeper
  fact at `version.py:501`, and a larger change than this. This design is
  built to be correct without it.
* **Item 25 (`preflight`).** Adjacent and touched by §1, but its own item.
  Noted while investigating: **item 25's premise is partly stale** — `preflight`
  calls `broker.resting_stops()` (`preflight.py:445`), which already routes
  through `reqAllOpenOrdersAsync`. Its real defect is the same inverted
  direction, deriving `unprotected` from held positions only
  (`preflight.py:450`). Worth correcting on the item before working it.
* **Item 26 (the order preset).** `why_held` is carried on `RestingOrder` so the
  locate condition becomes visible, but nothing here acts on it.

---

## What this changes, and what it does not

**One sizing input does change**, and it must be called out rather than buried:
widening the working-status set means `from_ib_resting_stop` now recognises
stops in `ApiPending` and `ApiUpdate`, so `verify_position_stops` stops dropping
them from `_position_stops` — and `_position_stops` is the denominator of every
risk-at-stop figure the portfolio governor gates new entries on.

The direction is **toward accuracy and toward more risk being permitted**: a
position previously counted at its full value because its stop was in an
unrecognised state will now be counted at its true risk-to-stop, so the
aggregate falls and the governor may allow an entry it would previously have
refused. That is correct — the position genuinely was protected — but it is a
loosening, and a loosening reached by fixing a measurement is still a loosening.

**DECIDED by the operator, 24 August: keep them separable.** The status widening
is split out and does NOT ship with the orphan scan.

What that means concretely:

* The orphan scan carries its **own** working-status set, derived from
  `OrderStatus.ActiveStates` minus `ValidationError`, living in the new
  `resting_orders` module. It is complete from the start, because for the scan
  an incomplete set fails unsafe.
* `_IB_WORKING_STATUSES` and `from_ib_resting_stop` are **left exactly as they
  are**. `verify_position_stops` keeps its current behaviour, `_position_stops`
  keeps its current contents, and the governor's aggregate does not move.
* The two sets will therefore **disagree** for the duration, and that is
  deliberate rather than an oversight. A comment at each definition points at
  the other and at this decision, so the next reader finds the divergence
  explained instead of discovering it.
* The widening becomes its own outstanding item, with its own before-and-after
  measurement of the governor's aggregate on a watched session.

This keeps the change's headline claim literally true: **no sizing input moves.**

Nothing else moves. No strategy, signal, sizer or gate decides anything
differently, except that a symbol carrying unjustified resting risk stops
accepting new entries — which is the point.

The kill switch is untouched, and stays tripped until reset on a watched launch
(item 28).
