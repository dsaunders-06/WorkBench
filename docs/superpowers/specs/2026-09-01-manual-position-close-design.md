# Design — manual position close from the Positions table

**1 September 2026. DESIGN ONLY. No code has been written.**

Manual SELL of an app-managed position, from the dashboard, while the app runs
in `execution_mode=auto`. Manual BUY is explicitly not in this design.

---

## Why this, and why sells only

The operator has no manual trading path anywhere in the application. The
screener and risk console place no orders; the only order-placing paths are the
autonomous executor and two sell-side remediation scripts. TWS, added
1 September, supplies manual trading at the broker — but nothing the operator
does there is visible to the app's records.

**A manual SELL of an app-managed position is the safe half.** The app holds the
entry record, so the exit produces a proper closed trade with entry basis,
R-multiple and MAE/MFE intact.

⚠️ **A manual BUY is the dangerous half and is excluded.** It creates a position
with no entry basis, so the minimum hold and time stop cannot be computed and no
stop can be re-armed — the 24 August state `flatten_positions.py` exists to
remediate. It also has no row on a Positions table to live on.

---

## ⚠️ THE CENTRAL RISK: THE LEGS MUST BE CANCELLED FIRST, AND THE CANCEL MUST BE VERIFIED

Every position carries **two OCA-linked resting SELL orders** (LMT + STP) for
its full quantity. Sell manually without cancelling them and the legs remain
resting against a position no longer held — **they execute and put the account
short.**

Three prior incidents bear directly on this and are designed against, not
merely cited:

| Date | What happened | What it forces here |
|---|---|---|
| 24 Aug | `openTrades()` reported no protective stops while **sixteen were resting** — they belonged to clientId 1, the probe was 99 | Read legs with `open_orders()` (`reqAllOpenOrders`), never `openTrades()` |
| 19 Aug | A cancel reported `PendingCancel` **while being rejected outright** (error 10147: an order belongs to the clientId that placed it) | Re-read after cancelling. The cancel's own response is not evidence |
| 24 Aug | M139 re-transmitted a working order every 60s; the account held **4× the intended position** | One order, no retry loop. Never send while another works |

⚠️ **This recurred on 1 September**, hours before this design: a read-only probe
of TWS reported **"0 open orders"** against a book carrying twenty, for exactly
the 24 August reason. The trap is live, not historical.

### A prerequisite fix, in the same change

⚠️ **CORRECTED, Task 1:** the silent-cancel branch below lives in
`IBAdapter.cancel_order`, one layer under `OMS.cancel_order()` — not in
`OMS.cancel_order()` itself, which does `self._orders[order_id]` and raises
`KeyError` on an unknown order, already fail-closed. `IBAdapter.cancel_order`
resolves through `self._ib_orders` / `self._ib_groups`, which are
**session-scoped** — and order identity does not survive a restart. For any leg
placed in an earlier session it reached `if not group:`, set
`status = "cancelled"` **locally**, and returned success **without cancelling
anything at the broker**.

`PositionCloser` does not call it — it cancels via broker identity. But a method
that reports a cancel it did not perform, sitting beside a feature whose entire
safety rests on cancels being real, must not be left as it is. **Fixed in Task
1** (`src/qat/data/broker/ib_adapter.py`, commit `99a3650`): before giving up,
it now falls back to the live client's `openTrades()`, matched on permId (the
id that survives a restart); if that still resolves nothing, it raises
`CancelNotResolvedError` rather than claiming success.

---

## Component

`src/qat/domain/oms/position_closer.py` — a domain service. No Qt.

```python
class CloseOutcome(Enum):
    CLOSED        # sold, legs gone, ledger has the exit
    REFUSED       # a precondition failed; NOTHING was sent
    RECOVERED     # sell failed, original bracket re-placed
    UNPROTECTED   # sell failed AND re-place failed - the loud one

@dataclass(frozen=True, slots=True)
class CloseResult:
    outcome: CloseOutcome
    symbol: str
    quantity: float                  # sold, or 0
    cancelled_legs: tuple[str, ...]
    detail: str                      # operator-facing, always populated

async def close_position(
    symbol: str,
    *,
    operator: str,
    acknowledge_halt: bool = False,
    quantity: float | None = None,   # None = all. Reserved; v1 accepts only None
) -> CloseResult
```

**Depends on:** the `BrokerAdapter` protocol (`open_orders`, `cancel_order`,
`place_order`, `positions`), the OMS for recording the exit, and `KillSwitch` to
read state. It imports no Qt and decides no policy — `acknowledge_halt` is
passed in, so the dialog owns the human question and the service owns the
mechanism.

**Why not a method on `OMS`:** `oms.py` already carries the reconciliation rail,
the resting-order scan and fill absorption. This choreographs one irreversible
operation with its own recovery branch, which is a different job, and the file
is large enough that adding it would make both harder to hold in context.

---

## Preconditions — every one REFUSES before anything is sent

| Check | Why |
|---|---|
| Symbol held **per the broker** | The broker is the authority on what is held; app records are a claim |
| An entry record exists in `_entries` | Without it there is no entry basis, so no closed trade and no R-multiple. v1 names `flatten_positions.py` instead of half-recording |
| No working order for the symbol beyond its protective legs | M139. Never send while another is working |
| Kill switch clear **or** `acknowledge_halt=True` | Operator decision, below |
| `quantity is None` | v1 is full-close only; a value returns REFUSED rather than silently closing everything |

### ❌ The kill-switch decision — REVERSED 1 September, and the original was dangerous

**A manual close REFUSES while the switch is tripped. There is no acknowledged
override.** `acknowledge_halt` is removed from `close_position` and from the UI.

⚠️ **WHY THE ORIGINAL WAS WORSE THAN NO FEATURE.** The first version permitted a
close during a halt behind a second confirmation. The whole-branch review found
that this could not work, and the mechanism was confirmed against source:

* **Cancelling bypasses the kill switch.** `_cancel_legs` calls
  `broker.cancel_order()` DIRECTLY. It never passes sign-off.
* **Selling does not.** It goes `submit_exit_order` → `sign_off`, and
  `OMS._sign_off_locked` (`oms.py:723`) sets `status = "rejected"`
  unconditionally while the switch is tripped.
* **So does re-protecting.** The recovery path's `submit_protective_stop` needs
  sign-off too, and is rejected for the same reason.

**The sequence during a halt was therefore: legs cancelled, nothing sold,
bracket cannot be restored.** The operator ends up holding the full position
with **the stop-loss deleted** — strictly worse than before pressing the button,
at the exact moment the system has already decided something is wrong. Every
other failure path in this design leaves the operator no worse off; this one
actively stripped protection.

⚠️ **The tests passed anyway**, which is the part worth remembering:
`_FakeOms.sign_off` ignored the kill switch and always returned `filled`, so
`test_proceeds_past_the_halt_when_acknowledged` was satisfied by an
`UNPROTECTED` outcome. **A green test described a disaster.**

**The chosen answer is the honest one:** the button refuses while halted and
says so. Resetting the kill switch first is a deliberate act that takes seconds
and is already routine — it was done twice on 1 September. The escape hatch was
worth less than it appeared.

**The rejected alternative, recorded so it is not re-proposed blindly:** carve a
narrow exemption into sign-off so an operator-approved EXIT may pass while
tripped, while entries may not. Coherent, and it means deliberately putting a
hole in the one rail that halts everything. Not taken.

---

## Sequence

1. **Read legs** — `open_orders()`, filtered to this symbol and the working
   statuses. Capture each leg's type, quantity, price and OCA group; those
   levels are what recovery re-places.
2. **Cancel each leg.**
3. ⚠️ **Re-read `open_orders()` and confirm they are gone.**
4. ⚠️ **If any leg survives, STOP. Do not sell.** Return `REFUSED`. This is the
   branch that prevents the short-position trap, and it is the one to sabotage
   in testing.
5. **Re-read the broker's position quantity** — a leg may have filled during the
   cancel — and place **ONE market SELL** for it. No retry loop.
6. **Verify** the position is flat and the exit reaches the ledger.

⚠️ **THE SELL GOES THROUGH THE OMS's NORMAL ORDER PATH, NOT A RAW ADAPTER CALL.**
This was ambiguous in the first draft and is the difference between a close that
records a trade and one that does not. Placing directly on the adapter would
fill at the broker while the app's fill-absorption, the trade ledger and
`closed_trades.csv` never saw it — the position would vanish from the book with
no closed trade, no R-multiple and no MAE/MFE, which is the exact half-recorded
state the entry-record precondition exists to prevent.

⚠️ **It is signed off as the OPERATOR, bypassing the `AutonomyGate`.** The gate
decides whether the *system* may act unattended; here a human has already
approved this specific order in the dialog. The sign-off records that operator,
so the audit trail says who closed the position and that it was manual — and it
behaves identically whether `execution_mode` is `auto` or `recommend`, since the
approval has already happened. **A manual close must never queue in the blotter
waiting for a second sign-off.**

### Order type

**Market, in v1.** Not a preference: the legs are cancelled first, so a sell
that does not fill leaves the position completely unprotected. A market order is
the one that cannot sit unfilled. ⚠️ The cost is real and already measured —
M44 recorded a gap costing **1.68R, not the 1R sizing assumes**.

A limit option arrives later, and only together with the fill-timeout and
re-protect machinery it requires.

### Failure handling

| Failure | Response |
|---|---|
| Cancel not verified (step 4) | `REFUSED`. Nothing sold. Legs untouched or partially cancelled — reported exactly |
| Sell rejected or unfilled | Re-place the original bracket at the captured levels, newly OCA-linked → `RECOVERED`, ERROR logged, shown on screen |
| Re-place also fails | `UNPROTECTED`, CRITICAL logged, blocking dialog. A real position with no stop; nothing about this is quiet |

---

## UI surface

A **Close Position** button beneath the Positions table on the dashboard,
enabled only when exactly one row is selected. The confirmation dialog itemises
symbol, quantity, last price, unrealised P&L, **and the two legs about to be
cancelled**.

Follows the blotter's pattern: `_confirm()` and `_show_error()` stay separate
methods so tests can monkeypatch them and assert whether the order path was
reached, without driving Qt widgets. The widget calls `close_position()` and
renders `CloseResult.detail`. **No sequencing in Qt.**

---

## Testing

Against `mock_broker`, headless. The branches that matter are the ones that will
almost never run:

- cancel verification fails → **no sell is sent**
- sell rejected → bracket re-placed at original levels → `RECOVERED`
- re-place also fails → `UNPROTECTED`, CRITICAL
- switch tripped without `acknowledge_halt` → `REFUSED`, nothing sent
- switch tripped **with** it → proceeds
- a leg fills mid-cancel → the sell uses the **re-read** quantity
- no entry record → `REFUSED`, names the script
- `quantity` not None → `REFUSED`

⚠️ **Each gets a sabotage check.** M160, eleven days ago: its tolerance was
sabotaged into a blanket skip and **eight of nine tests stayed green** — only
the larger-gap test caught it. A suite that passes with the rail removed is not
testing the rail. The step-4 abort is the first to sabotage.

---

## Out of scope for v1

- **Partial closes** — the `quantity` parameter exists so adding them later does
  not rework the signature; v1 refuses any value but `None`. Partial requires
  re-placing a bracket for the remainder, and a partial close that leaves the
  remainder unprotected is worse than no feature
- **Limit orders** — arrive with the timeout and re-protect machinery
- **Manual BUY** — different problem, no row to live on, TWS covers it
- **Converging `flatten_positions.py` / `unwind_in_tranches.py` onto this
  service** — worth doing, not now

## Known interaction, not a defect

This works only while the app is connected as the clientId that placed the legs.
If a position is closed by hand in TWS while the app runs, reconciliation will
see the change and adapt, but this button's preconditions will **refuse** on
that symbol — the legs it expected are gone. That is correct behaviour, recorded
here so it does not read as a bug.
