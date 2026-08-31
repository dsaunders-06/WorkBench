# Reconciliation must not read an order in flight as a divergence — design

**31 August 2026.** Defect B, found when the first app-transmitted entry since
item 56 tripped the kill switch nine seconds into a forty-five-second fill.

## 1. What happened, measured

    10:30:06 - 10:30:51   JHX.AX buy, 17 executions, cumQty 1,097
    10:30:15              Broker reconciliation mismatch: JHX.AX tracked=1097 broker=378
    10:30:15              KILL-SWITCH TRIPPED: Broker reconciliation mismatch

The poll landed nine seconds into the fill. The app counted the whole order as
held; the broker had executed 378 of it. **The switch was not wrong — that is a
real instantaneous disagreement — but it is not a durable one**, and any market
order that outlives the poll gap will do this every time.

### Root cause, `oms.py:861`

    signed_qty = filled.quantity if filled.side == "buy" else -filled.quantity
    self._filled_quantities[filled.symbol] += signed_qty

`filled` is the order the broker RETURNED, and `.quantity` is the **order's
size**, not the amount executed. So the full quantity is booked the instant the
broker accepts.

That matters because `filled_quantities()` documents itself as *"what this app
believes is **held**"* — a settled-holdings view, and *"the number a
reconciliation difference is one half of."* Booking an unsettled commitment into
a holdings view is the defect.

⚠️ **The obvious fix is not available.** Removing the sign-off write would leave
own fills uncounted entirely: they never come back through absorb, because
`_is_foreign_unrecorded` excludes them via `_broker_order_ids`. Sign-off is the
only place the app's own fills are counted.

## 2. The design: subtract what is still in flight

`check_reconciliation` asks the broker how much of each working BUY order is
still unfilled, and treats a divergence as expected **only up to that amount**.

    expected  = sum(remaining of working BUY orders for the symbol)
    divergent = abs(tracked - broker - expected) > 1e-6

Applied to the live case: `1097 - 378 - 719 == 0`. No mismatch, no trip.

**No contract change is needed.** `open_orders()` is already on the adapter
protocol and implemented in `IBAdapter`; `RestingOrder.quantity` **is**
`orderStatus.remaining`; and `check_resting_orders` already fetches it in the
same monitor cycle as `check_reconciliation`.

**The number was already in hand at the moment it tripped:**

    10:30:15  RESTING ORDER ORPHAN: JHX.AX BUY resting=719 justified=0 excess=719
    10:30:15  Broker reconciliation mismatch: JHX.AX tracked=1097 broker=378

The gap was 719 and the working buy's remainder was 719, in the same second, in
the same scan cycle.

### 2.1 ⚠️ BUYS ONLY, and this is the load-bearing rule

The instinct is to handle both sides symmetrically. **That would be a serious
bug.**

The twenty resting protective legs are *working sell orders* whose `remaining`
is the full position — BOQ's is 13,586. But a protective stop **returns early at
sign-off and never touches `_filled_quantities`** (`oms.py`, the
`is_protective_stop` branch). Subtracting those remainders would invent a
tolerance of 13,586 shares on a symbol with no divergence at all, and turn a
clean book into a mismatch.

**Buys always inflate tracked at sign-off. Protective sells never do.** So only
buys are subtracted.

**The cost, stated:** a partially-filled app-transmitted SELL would still trip,
because tracked would under-count while the sell worked. That is the conservative
direction — it trips rather than blinds — and per item 1 an app-transmitted sell
has never completed in this system's life. Revisit it when one does.

### 2.2 Failure behaviour: no tolerance, which trips

If `open_orders()` raises, or the adapter does not implement it, the expected
remainder is **zero** and the rail behaves exactly as it does today. A rail that
loses its evidence must get stricter, not laxer. `check_resting_orders` already
guards for an adapter without `open_orders()` and logs it; the same guard applies.

### 2.3 What this does NOT change

* **The rail keeps its teeth.** With no working buy, the tolerance is zero and
  every divergence trips exactly as before.
* **A gap LARGER than the remainder still trips**, with the excess intact.
* Nothing about the kill switch, the quarantine store, or the position cap.

## 3. Testing

1. **The live case, with its real numbers.** tracked 1097, broker 378, working
   buy remaining 719 → **no mismatch**.
2. **A genuine divergence with nothing in flight.** tracked 1097, broker 378, no
   open orders → **mismatch**. The rail's teeth.
3. **⚠️ PLANTED: a gap larger than the remainder still trips.** tracked 1097,
   broker 300, remaining 719 → gap 797 exceeds the tolerance → **mismatch**.
   Without this, an implementation that simply skipped any symbol with a working
   order would pass tests 1 and 2.
4. **⚠️ PLANTED: resting protective sells must NOT create a tolerance.** A clean
   book — tracked == broker — carrying full-size resting sell legs must produce
   **no mismatch**. An implementation that subtracted sell remainders turns this
   green book red, and it is the trap this design exists to avoid.
5. **`open_orders()` raising** → falls back to today's behaviour and trips on the
   raw gap.

## 4. Blast radius

`check_reconciliation` returns "a halting mismatch was found", and
`ReconciliationMonitor` publishes `KillSwitchEvent` on `True`. **This is the halt
rail.** Getting it wrong in the lax direction blinds the one signal that means
"my view of the account cannot be trusted".

The change is additive and subtractive-only-when-evidenced: the tolerance is
zero unless the broker itself reports a working buy with an unfilled remainder.

Verification is the full suite plus ruff, black, mypy and bandit — **run
separately**, because `black --check` exits 0 while printing "1 file would be
reformatted".

⚠️ **One dependency worth naming.** This trusts the in-session `open_orders()`
view, and Defect C showed that view can be incomplete — the JHX legs' OCA group
was missing from it while a fresh read had it. The `remaining` figure was
correct on the day, but both come from the same call. M159's group-key
instrumentation will show how far that view can be trusted, and **reading
tomorrow's session before shipping this is the cheaper order of operations.**

## 5. Out of scope

* **An executed quantity on `Order`.** It fixes the root but alone makes things
  worse: at sign-off the executed quantity is zero or partial, so tracked would
  UNDER-count and the rail would trip the other way once the order completed. It
  needs a stream updating tracked per execution — a far larger machine, into the
  halt rail.
* **Partial app-transmitted sells.** See §2.1.
* **Defect C.** Narrowed, not proven; instrumented in M159.
