# Design — order rejections the app can hear, and a feed that can report its own failure

**3 September 2026.** Two defect clusters found by running the application, not by
a test. Both cost something today. Both have the same shape.

**Nothing here is built or deployed.** Every file is under `src/`, so it needs a
build, deploy and read-back after a close.

---

## ⚠️ THE UNIFYING FINDING: THE LIBRARY TOLD US AND THE APP WAS NOT LISTENING

Two independent failures on 3 September, and in each the library reported the
problem plainly while the application carried on believing all was well.

    logger=ib_async.wrapper  ERROR  Error 383, reqId 476: The following order
      "ID:476" size exceeds the Size Limit of 500. Restriction is specified in
      Precautionary Settings of Global Configuration/Presets.

    logger=yfinance          ERROR  HTTP Error 401: {"finance":{"result":null,
      "error":{"code":"Unauthorized","description":"Invalid Crumb"}}}

**Neither library raises. Both log.** Our code reacts to exceptions and return
values, so neither reached it. The app booked a position for an order the
exchange never saw, and traded on a feed that had stopped answering for 99 of 100
symbols — and reported neither.

⚠️ **This is not a plea to catch more exceptions.** It is that a library's own
error stream is an input we were not reading. Both halves below are the same
correction applied to two different libraries.

---

## What happened, in one paragraph each

**The order.** TNE.AX stopped out overnight, taking the book to nine and
unblocking the first entry since 31 August. At 14:52:24 the app transmitted
`buy 790 BHP.AX`. TWS **staged** it — held it untransmitted on a precautionary
Size Limit of 500 — so it never reached the exchange. The app booked all 790
anyway. At 14:56:18 reconciliation caught it (`BHP.AX tracked=790 broker=0`) and
the kill switch halted flow, correctly. ⚠️ **The phantom then counted toward the
position cap**: at 14:54:33 NST.AX was refused `already at the 10-position limit`
— nine real positions plus one that never existed.

**The feed.** From 14:52 to at least 15:16 the app logged `No usable quote for
BHP.AX` every sixty seconds while a fresh Python process on the same machine
pulled all 100 watchlist symbols in 3.7 seconds. The app produced **no**
`MARKET DATA DOWN`, **no** `poll produced no ticks`, and **zero** of its own
`yfinance quote poll failed` warnings.

---

# PART ONE — THE ORDER PATH

## A. Executed quantity (Defect B)

`oms.py:861` is unchanged from the line the 31 August section names as Defect B's
root cause, under a heading that says **"FIXED, M160"**:

    signed_qty = filled.quantity if filled.side == "buy" else -filled.quantity

`filled` is the ORDER the broker returned and `.quantity` is the **order's size**,
not the amount executed. An order merely *accepted* books a full position.

⚠️ **That reading is incomplete, and the next section corrects it.** M42 already
established a contract under which this line is CORRECT, and the real defect is
both that IBKR never implemented it and that the contract cannot express the case
that bit us.

### ⚠️ M42 ALREADY OWNS THIS PROBLEM, AND CANNOT EXPRESS THE 3 SEPTEMBER CASE

**Found during implementation, 3 September, when Task 3 turned 25 existing tests
red.** This section is the corrected diagnosis; the paragraph above it was
written without knowing M42 existed.

**There is already a contract for "book what executed".** M42 established that
the ADAPTER rewrites `Order.quantity` to the filled amount, and
`tests/safety/test_partial_fill_at_signoff.py` states it plainly: *"the OMS must
count what the adapter reports rather than the size it asked for."*
`alpaca_adapter.py:646` implements it:

    filled_qty = _as_float(getattr(placed, "filled_qty", None))
    if filled_qty > 0:
        order.quantity = filled_qty

So `oms.py:861` reading `filled.quantity` was **correct for any adapter that
honours M42**. That is why it survived review for months.

**`from_ib_trade` never rewrites `quantity`.** IBKR never implemented M42's half.
That alone looks like the whole answer, and it is not.

### ⚠️ AND THE GUARD IS THE POINT. M42 EXCLUDES ZERO ON PURPOSE.

`alpaca_adapter.py:641-643`, in M42's own words:

> *"Guarded on being positive: an accepted-but-unfilled order reports filled_qty
> of 0, and writing that back would read as 'this position was closed' rather
> than 'it has not started'."*

**That exclusion is exactly 3 September.** A staged order reports `filled=0`, so
under M42 `quantity` stays at 790 and the OMS books 790 — the phantom — on an
adapter that fully honours the contract.

⚠️ **So teaching `IBAdapter` to honour M42 does NOT fix this.** It fixes partial
fills, which were never the failure. The zero case is excluded by design, and
for a good reason: `quantity` is one number carrying two meanings, and it cannot
take a third.

### Which is the real argument for a separate field

The case needs **three** distinguishable states and `quantity` offers two:

| state | `filled_quantity` | what `quantity` alone can say |
|---|---|---|
| adapter does not report executions | `None` | nothing — indistinguishable |
| accepted, nothing executed (3 September) | `0.0` | collides with "closed" |
| partially executed | `400.0` | fine — this is M42's case |

A nullable field separates all three. `quantity` keeps its one honest meaning:
what was **ordered**. That is also what M42's rewrite destroys, and why a bracket
whose legs rest for 790 no longer matches an order object claiming 400.

⚠️ **The cost, measured rather than estimated.** Task 3 turned **25 tests red
across 6 files** — `test_live_entry_price_correction.py` (13),
`test_live_exit_price_correction.py` (4), `test_partial_fill_at_signoff.py` (3),
`test_replay_churn_rails.py` (2), `test_replay_outcomes.py` (2),
`test_autonomous_executor.py` (1). Every one is a fake following M42's convention
— rewriting `quantity`, never setting `filled_quantity`. They are fixture
updates, not a signal the approach is wrong, and the plan must budget for them
rather than discover them.

⚠️ **Alpaca's guarded rewrite becomes vestigial and is LEFT ALONE.** Alpaca is
dead for this system (item 13 keeps it as the US era's evidence trail), and
editing dead code to match a live contract adds risk for no benefit. Recorded so
the inconsistency is deliberate rather than missed.

### ✅ The data already exists. The recorded cost was overstated.

The handoff states that fixing this "means adding one to the broker contract and
populating it wherever `place_order` is implemented". Verified against the
installed library (`ib_async 2.1.0`):

    OrderStatus fields: orderId, status, filled, remaining, avgFillPrice,
                        permId, parentId, lastFillPrice, clientId, whyHeld, ...
    Trade helpers     : filled(), remaining(), isActive(), isDone()

`OrderStatus.filled` **is** the executed quantity. Nothing needs inventing.

### The change

`Order` gains `filled_quantity: float | None = None`. `from_ib_trade` populates it
from `trade.orderStatus.filled`. `oms.py:861` books that.

⚠️ **`None` means "this adapter does not report executed quantity" — a DIFFERENT
CLAIM from zero.** It must never fall back to the order size, which is the defect;
and it must never be read as 0, which would under-book a real fill. Three live
implementations populate it — `ib_adapter`, `mock_broker`, `simulated_broker`.
The two fakes fill synchronously, so for them it equals the order quantity and is
trivially correct.

**So what happens when it IS `None`?** Since all three live adapters populate it,
`None` reaching the OMS is a programming error, not a runtime condition. It is
logged at ERROR naming the adapter and the order, and **nothing is booked** —
reconciliation then settles the position from the broker within five minutes,
which is the same path that caught today's divergence. Booking nothing is the
fail-closed choice: an under-booked real fill is visible to reconciliation, while
an over-booked phantom is what this whole part exists to prevent.

`alpaca_adapter` is **not** updated. Alpaca is dead for this system — the app runs
ASX through IBKR and preflight refuses `broker=alpaca` off a US market. Item 13
keeps that code only as the US era's evidence trail, and counting it as adapter
work has already inflated one cost estimate in this file.

## B. Consuming `errorEvent`

`IBAdapter.connect` subscribes to `ib_client.errorEvent`. The halt path already
exists: the adapter publishes `KillSwitchEvent` over the bus at
`ib_adapter.py:268`, which is the precedent to follow (the adapter must not
import the kill switch directly — see the module docstring).

### ⚠️ Why this does not contradict the module's stated design

The adapter's docstring says connection health is checked by an active heartbeat
"rather than subscribing to ib_async's Event objects — simpler to reason about
and test". **That decision was right and is unaffected.** It concerns connection
health, where polling gives the same answer. It does not extend here: there is no
polling equivalent for an order rejection. Error 383 is delivered by
`errorEvent` or not at all.

### ⚠️ The scoping detail that makes fail-closed safe

`errorEvent` also carries informational messages — 2104 *"market data farm
connection is OK"* arrives as an error. A naive "unknown code → halt" would halt
the system on a health notice.

So the handler asks **first** whether the `reqId` maps to an order this app
placed. Only order-scoped errors are classified at all; everything else is logged
and ignored.

### Classification, fail-closed by construction

* An enumerated frozenset of **known-BENIGN** codes → the order moves to a
  terminal `rejected` status carrying the broker's reason, and the app carries on.
* **Everything else** → the same, PLUS a `KillSwitchEvent`.

⚠️ **The enumeration is of the benign set, never the serious set.** An unfamiliar
rejection falls to the serious branch. This is the shape that finally worked on
the manual-close branch after three whole-branch rejections — `status not in
TERMINAL_STATUSES` — where enumerating the bad cases had been green over the exact
defect it was named for.

### What a terminal `rejected` status buys

Today's order sat as `transmitted` indefinitely: `retry_pending` kept finding it,
autonomy kept blocking it, and it never resolved. A terminal status frees the slot
so a correctly-sized entry can take it.

## C. The sizer's ceiling

⚠️ **The precautionary limit is NOT queryable.** Verified: no method on `IB` and
no name in `ib_async` mentions preset, precaution, limit, config or setting. It is
a TWS-local UI value. The app can only be told it, or learn it from a rejection.

* A `broker_max_order_shares: int | None` setting, **defaulting to `None`**. The
  sizer trims to it exactly as the existing per-order cash cap does, logging the
  trim in the same shape. `None` means no ceiling is known and nothing is trimmed
  — today's behaviour, unchanged, until an operator sets it.
* On Error 383 the app parses the limit out of the message and **warns loudly**:
  if the setting disagrees with the broker's number, or if it is unset, the
  warning names the broker's value and says to configure it.

⚠️ **The app does not invent its broker's configuration.** Defaulting to `None`
rather than to 500 means a fresh install trims nothing rather than silently
enforcing a limit that belongs to one particular TWS instance. The current
machine's value is 500 and the operator sets it.

**The config is the belief; the rejection is the auditor.** The parsed number is
never applied automatically — string parsing audits, it does not decide. That
keeps the fix from depending on IBKR's error wording staying stable, while still
catching the drift that a second source of truth otherwise hides.

⚠️ **This is not a safety rail.** With B in place a size rejection is already
visible and safe. C exists to stop wasting an entry opportunity — today it cost
the first tradable signal in three days.

---

# PART TWO — THE FEED

## D. Validate the result, not just the exception

`_poll_once` wraps `yfinance.download` in `try/except` and returns `[]` on an
exception. **`download()` does not raise** on these failures — it logs its own
ERROR and returns a frame. Our `yfinance quote poll failed` warning fired **zero**
times today.

The poll compares what came back against what was requested, so a partial
response is a measured fact rather than an invisible one.

## E. Per-symbol health

`stream_ticks` currently holds one `consecutive_failures` counter and resets it
whenever a poll yields *any* tick:

    if ticks:
        consecutive_failures = 0

**One symbol answering masks a 99-symbol outage.** That is exactly what happened:
no `poll produced no ticks` line, no `MARKET DATA DOWN`, all day.

Replaced by a per-symbol consecutive-failure count. The report **names the failing
symbols** — which is the whole point of counting per symbol rather than in
aggregate.

**The two numbers, both explicit rather than implied:**

* A symbol is FAILING once it has missed `max_consecutive_failures` polls in a row
  — the existing setting, default **5**, reused rather than a second notion of the
  same idea.
* The feed is DOWN once **half or more** of the requested symbols are failing —
  a new `feed_down_symbol_fraction`, default **0.5**.

Today that fires: 1 of 100 answering means 99 failing, far past half, sustained
for twenty-five minutes. A single delisted or thinly-traded symbol never does.

### ⚠️ The open must not trip it — this is the M119 regression risk

At the ASX open every symbol is legitimately absent for ~20 minutes, because Yahoo
publishes ASX intraday about twenty minutes late. A naive per-symbol threshold
fires every single morning.

On 21 August that exact shape ended the stream at 10:04:20 waiting for data that
arrived at 10:22, and the account sat flat and blind on an open market for two
hours.

**Counters accumulate during the known blind window but cannot trigger DOWN until
it has elapsed.** `BLIND_WINDOW_FILTER` already models this state and is already
set from the first empty poll (item 54); this reads it rather than inventing a
second notion of the same window.

## F. DOWN stays report-only

⚠️ **Deliberately unchanged.** M119 made "MARKET DATA DOWN is not a kill-switch
trigger" an explicit decision after halting cost a session, and M158's per-symbol
entry gate does the blocking.

✅ **That gate worked today.** The log lists the 99 unprinted symbols as *"They
cannot be entered"*. BHP got through only because it was the one symbol that had
printed. The gate is not the defect and is not touched.

What changes is that the app can finally **say** the feed is broken, which today
it could not.

## G. Instrument the poisoning — do NOT fix it

The app's process had no usable quotes while a fresh process had all 100. That
points at process-local session state, and `YfData` is a singleton
(`SingletonMeta`) caching its cookie and crumb for the life of the process with
nothing in the 401 path clearing them.

⚠️ **BUT THE MECHANISM IS NOT ESTABLISHED, and a plausible story is not evidence.**
A deliberately poisoned `_crumb` still returned 295 rows from `download()` — the
chart endpoint does not use the crumb, so the `Invalid Crumb` 401s come from a
`quoteSummary`-style path (fundamentals, earnings), not the price poll. **The
crumb hypothesis is disproved for this endpoint.**

Two further hypotheses were tested and also failed:

* **NOT the batch size.** Measured in a fresh process: 100, 75, 50, 30, 20 and 10
  symbols ALL returned complete data — 100/100 in 3.7s.
* **NOT an ongoing 401 storm.** The burst was bounded: 13 errors between 14:51:28
  and 14:52:15, then nothing, while the quote outage continued for 25 more minutes.

**So no session reset ships.** Instead, a failed or partial poll logs what the
response actually was — status code, a truncated body, whether a crumb and cookie
were present — so the next occurrence identifies the mechanism instead of
confirming a guess.

This follows the rule that has already paid twice in this project: the IBKR feed
migration was REJECTED by a pre-written reading rule rather than adopted on
plausibility, and the M43 halt-feed question was answered by measuring that every
field except `halted` populated.

## H. The dependency pin

`pyproject.toml` has `yfinance>=0.2.40` with no ceiling, and **1.5.2** is
installed — a major-version drift on an unofficial API that nobody chose and no
test would have caught.

Proposed: `yfinance>=1.5.2,<2` — floor at what is actually running and tested,
ceiling below the next major.

---

## Error handling

* Absent is absent. `filled_quantity is None` is never coerced to a number.
* The `errorEvent` handler must never raise into ib_async's callback: it logs and
  swallows, matching the poll loops' discipline.
* An unclassifiable order-scoped error halts. An unrecognised non-order error is
  logged and ignored.
* Feed detection changes what is REPORTED, never what is traded.

## Testing

⚠️ **The fakes are the standard to beat.** The manual-close branch was rejected
three times, each time with 3,000+ tests passing, because a fake did not model the
real broker. The central gap here is the same: **no existing fake models an order
that is ACCEPTED but never filled** — today's case.

* A broker double that accepts an order and reports `filled=0`, and a test that
  the OMS books **nothing** for it.
* `filled_quantity is None` must not book the order size — assert the specific
  failure this whole part exists to prevent.
* A partial fill (`filled=400` of 790) books 400.
* `errorEvent` with an order-scoped benign code → order `rejected`, no halt.
* `errorEvent` with an order-scoped **unknown** code → halt. Mutate the benign set
  to include it and confirm the test fails.
* `errorEvent` with code 2104 and no matching order → **no halt**, no rejection.
  This is the test that stops fail-closed from halting on a health notice.
* Sizer trims to `broker_max_order_shares`; Error 383 whose parsed limit disagrees
  with config emits the warning and does **not** change the setting.
* Feed: a poll returning 1 of 100 symbols counts 99 failures, not zero.
* Feed: a full blind window at the open does **not** report DOWN — the M119
  regression, asserted directly.
* Feed: coverage recovering resets the counters.

## Sequencing

Part One and Part Two share no code and must land as separable commits. Part One
touches the live order path and should be reviewed and deployed on its own merits
even though both are specified here.

Within Part One: A is self-contained and fixes the phantom by itself. B needs no
part of A. C needs B only for its audit half.

⚠️ Everything is in `src/`, so nothing is visible until a build, deploy and
read-back after a close.

## Not in scope

* **Raising the TWS Size Limit.** The operator chose to teach the sizer the
  ceiling instead, so the preset stays as it is and the app respects it.
* **Any yfinance session reset**, per G — until the mechanism is established.
* **`whyHeld`.** `OrderStatus.whyHeld` exists and may flag a held order directly,
  which would detect staging without waiting for an error. Untested against a real
  staged order, so it is recorded as worth measuring, not designed against.
