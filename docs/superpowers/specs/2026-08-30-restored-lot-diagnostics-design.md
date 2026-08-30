# Restored-lot diagnostics — design

**30 August 2026.** Two fields that a restart destroys, fixed together because
they are lost at the same line for the same reason.

M44's "other half" was recorded as one open piece: `worst_price` and
`best_price` evolve over a trade's life, so persisting them at open would
restore a stale excursion. Measuring the problem before designing for it found a
second defect sitting on the same line — and the second one is worse, because it
was believed fixed.

## 1. What was measured, and how

Both findings below are from a runnable test with a control, not from reading
call sites. The control is the point: the live path passes, so a test that
passed on both paths would have proved nothing.

    LIVE     reference_price=49.9   entry_slippage=0.099…  mae_r=-0.8  mfe_r=1.6
    RESTORED reference_price=None   entry_slippage=None

Same lot, same prices, same exit. The only difference is whether the app
restarted while the position was held.

### Defect A — M156's `reference_price` is inert on the restart path

**This is the defect that matters, and it is new.** M156 (28 August, commit
`382c92c`) carried `reference_price` onto `_Entry` and `PositionEntry`,
populated it from the fill event, persisted it in
`open_position_entries.json`, and read it back with `.get`. All of that works.

The value then dies one step further on. `TradeLedger.restore_open_lot`
(`trades.py:617`) has no `reference_price` parameter, so
`SignalToOrderBridge.restore_open_lots` (`signal_bridge.py:695`) cannot pass
one. The rebuilt lot carries `None`, and `ClosedTrade.entry_slippage` — which is
`entry_price - reference_price` — returns `None`.

**With a ten-day minimum hold and a session most nights, every trade this system
closes goes through that path.** M44's instrument is still unfed.

Its commit shipped five tests. They assert the dataclass shape, the write and
the read — the record and the file. **None follows the value into the rebuilt
lot, which is what a `ClosedTrade` is actually made from.** That is the shape
the same commit message names in items 59, 67 and Milestone C Task 1: a field on
a record that is never consumed is inert, and a test that stops at the record
cannot tell.

### Defect B — the excursion resets to the entry price

`restore_open_lot` seeds `worst_price=price, best_price=price` and says so
plainly in its docstring: *"MAE and MFE on a restored lot measure from the
restart forward. That understates both, and understating a diagnostic is
acceptable where fabricating one is not."*

The reasoning is sound and the outcome is still that `mae_r` and `mfe_r` are
unmeasurable in practice, for the same reason as Defect A — the restart happens
before nearly every close.

### The structural fact underneath both

    _Entry fields          : opened_at, price, reference_price, stop_price,
                             strategy, target_price
    OpenLot fields         : …, opened_at, price, reference_price, stop_price,
                             strategy, worst_price, best_price, …
    common                 : opened_at, price, reference_price, stop_price, strategy
    restore_open_lot params: opened_at, price, quantity, stop_price, strategy, symbol
    COMMON NOT PASSED      : ['reference_price']

A field can be added to the persisted record and to the lot and still not travel
between them, because a third thing — a function signature — has to change too
and nothing checks that it did.

The count, stated exactly, because the commit that shipped Defect A got it right
and the number has moved:

| # | Field | Lost | Status |
|---|---|---|---|
| 1 | `target_price` | M33 | fixed |
| 2 | `strategy` | M49 | fixed |
| 3 | `reference_price` | M44 | fixed **at the record** on 28 August, still lost one call further down — Defect A |
| 4 | `worst_price` | M44 | Defect B |
| 5 | `best_price` | M44 | Defect B |

Three of the five are the same commit's work, and the third was believed
finished. That is what the structural guard in §4 exists to stop.

## 2. Approach: backfill from daily bars

The excursion is **not persisted**. At restore, it is recomputed from the daily
OHLC bars the bridge already holds.

The bridge owns a `MultiSymbolAggregator` of real OHLC bars, seeded by warm
start with 300 daily bars per symbol. Its own comment calls it *"the most
load-bearing of the three aggregators in the app: the ATR computed from these
bars sets the stop distance, and the stop distance sets the position size."* The
data needed is already in the component that already calls `restore_open_lot`.

**Why this rather than persisting it:**

* Nothing to keep in sync, go stale, be written atomically, be keyed against a
  re-entered symbol, or be pruned on close. Restart-proof by construction rather
  than by maintenance.
* It recovers the excursion for the ten positions held **right now**, back to
  24–27 August. A persisted field recovers nothing already lost.
* It is **more accurate than the live path**. The feed is polled every 60
  seconds, so across a six-hour ASX session it takes on the order of 360
  samples — and it cannot see any extreme that occurred between two of them. A
  bar's high and low are the extremes of every trade, not of a sample.

  ⚠️ The delay is a separate matter and is *not* part of this claim: a
  twenty-minute-old print is still a real traded price. Sampling is what loses
  the extreme, not lateness.

**What it costs, stated plainly:** daily granularity, and one lot's life is then
measured on two bases — bars before the restart, ticks after. The bars are the
wider and more correct half, so the seam understates rather than inflates.

**This is measurement, not fabrication.** The backfilled figure comes from the
same instrument the stop distance already rests on. The docstring's rule is
preserved, not waived.

### Ordering is structural, not incidental

The backfill is worthless if the buffers are empty when it runs. Verified:

* `orchestrator.start_all` awaits each engine's `start()` in registration order.
* `runtime.py:777` passes `signal_bridge.bars` as one of warm start's three
  aggregators.
* Warm start's `start()` awaits `seed()` before returning, and the bridge is
  registered after it.

Observed on both launches tonight: seeding completed at 21:14:37, lots restored
at 21:14:41.

⚠️ **Warm start catches its own exceptions and continues** — *"a cold start
beats no application"*. So empty buffers are a live possibility and must be
reported, never silently absorbed.

## 3. The design

### 3.1 `TradeLedger.restore_open_lot` gains three optional parameters

    reference_price: float | None = None
    worst_price: float | None = None
    best_price: float | None = None

`reference_price` flows straight onto the lot. `None` means UNKNOWN — never the
entry price, which would report zero slippage on a trade nobody measured.

`worst_price` and `best_price` fall back to `price` when not supplied, which is
exactly today's behaviour. Existing call sites and the backtester are unchanged.

`_LotStore`, the Protocol the bridge declares for this call, is updated to
match — otherwise the bridge's own type contract states something false.

### 3.2 The bridge computes the backfill

A private helper on `SignalToOrderBridge`:

    _excursion_since(symbol, opened_at) -> tuple[float | None, float | None, int]

reads `self.bars.frame(symbol)`, keeps bars strictly after the entry day's
boundary, and returns `(min(low), max(high), bar_count)`, or `(None, None, 0)`
when there are none.

`restore_open_lots` then passes `entry.reference_price` together with whatever
the helper returned.

### 3.3 Excluding the entry day's own bar is the load-bearing rule

TNE's 24 August daily bar contains prices from before 15:19:36, when the
position did not exist. Folding it in would attribute to the trade a low it
never experienced — the exact fabrication the docstring forbids.

So the entry day's bar is excluded and the lot starts from the entry price,
picking up bars from the following day onward. Genuine same-day excursion is
missed. On a ten-to-thirty-day hold at daily granularity that is small, and it
is always in the safe direction.

Bars from the restore day onward need no special handling: every price in them
occurred while the position was held.

### 3.4 One new line, carrying counts

    Excursion backfilled from daily bars on N of M restored lot(s); K had no
    bars after their entry day and start at the entry price, which understates
    both.

A count, not an adjective — M154's shape. When warm start has failed, `K == M`
and the line says so, which is what makes an empty buffer visible instead of
silent.

## 4. Testing

**At the consumer, and with a planted violation.** Both halves are needed: a
consumer test says the value arrives, a planted violation says the guard can
see.

1. **The structural guard.** Every field name common to `_Entry` and `OpenLot`
   must appear in `restore_open_lot`'s signature. Verified to fail today, naming
   exactly `reference_price` and nothing else; `target_price` is correctly
   excluded because it is not an `OpenLot` field. Anchored on shape rather than
   on a list of names, so the *sixth* field to be lost across a restart fails the
   build instead of shipping — this change closes numbers three, four and five.

2. **`entry_slippage` after a restore.** Restore a lot, sell it, assert the
   closed trade carries a slippage figure. **With the live path alongside as a
   control** — the live path already passes, so a test green on both proves
   nothing about the one that was broken.

3. **`mae_r` and `mfe_r` after a restore**, equal to the bar-derived figures.

4. **A planted violation of the entry-day rule.** Seed the entry day's bar with
   a low far below anything after it and assert it does *not* reach
   `worst_price`. Asserting the absence alone would report the same clean result
   whether the rule works or the scan is blind.

5. **The empty-buffer guard.** No bars → `worst == best == entry price`, and the
   line reports `K == M`. Exercised at the layer that logs it, not only at the
   store: item 59's six store tests all stayed green when the caller was deleted.

## 5. Blast radius, and how it is verified

`restore_open_lot` is on the exit path. It is the reason a stop firing on a
position opened in an earlier session records a closed trade at all — the
counter the whole validation phase exists to move. Getting it wrong loses trades
from the record silently.

Every new parameter is optional and defaults to today's value, so behaviour is
unchanged wherever nothing is passed.

**Verification is the full suite plus ruff, black, mypy and bandit — not the
targeted tests.** Item 22's three green tests hid a broken order path that the
full suite then found in 134 failures, with mypy already naming the cause.

## 6. Explicitly out of scope

* **The six existing closed trades cannot be repaired.** Their reference prices
  were never written down and their bar history predates the records. They stay
  empty, and the first trade opened and closed after this ships is the check.
* **Intraday excursion granularity.** Daily bars are the instrument. Finer
  measurement is a separate question and nothing currently reads it.
* **Persisting the live tick-derived excursion.** Considered and rejected above.
