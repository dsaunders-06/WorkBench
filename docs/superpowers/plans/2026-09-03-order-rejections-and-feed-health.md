# Order Rejections and Feed Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the application hear what its libraries are already telling it — an IBKR order rejection, and a market-data feed that has stopped answering — so it stops booking positions the exchange never took and stops trading blind without saying so.

**Architecture:** Two independent halves. Part One teaches the order path to book what *executed* rather than what was *ordered*, and to consume `ib_async`'s `errorEvent` with a fail-closed classification. Part Two teaches the feed to validate what came back rather than only catching exceptions, and to count health per symbol rather than all-or-nothing.

**Tech Stack:** Python 3.12, ib_async 2.1.0, yfinance 1.5.2, pydantic-settings, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-order-rejections-and-feed-health-design.md`

## Global Constraints

- **Absent is never a number.** `filled_quantity is None` means "this adapter does not report executed quantity" — it must never fall back to the order's size (that is the defect) and never be read as `0` (that under-books a real fill).
- **Fail closed by construction, not by enumeration.** The error classification enumerates the **benign** codes only; anything unrecognised falls to the serious branch. Never enumerate the serious set.
- ⚠️ **`errorEvent` is not only about orders.** Code 2104 (*"market data farm connection is OK"*) arrives as an error. The handler must establish that a `reqId` maps to one of this app's orders **before** classifying; unmatched errors are logged and ignored, never halted on.
- **DOWN stays report-only.** M119 made "MARKET DATA DOWN is not a kill-switch trigger" an explicit decision after halting cost a whole session. Nothing in Part Two may halt, refuse an order, or change what is traded.
- ⚠️ **A task that adds a `Settings` field MUST document it in `scripts/manual_body.py` in the same task.** `tests/test_manual_documents_every_setting.py` is a repo-wide guard and targeted test runs do not catch it — that is exactly how it was missed on 2 September.
- **Do NOT touch `src/qat/data/broker/alpaca_adapter.py`.** Alpaca is dead for this system; item 13 keeps it as the US era's evidence trail. Counting it as adapter work has already inflated one cost estimate in this project.
- ⚠️ `qat.domain.*` and `qat.data.*` are under **strict mypy** (`pyproject.toml:76-82`). `config.py`, `adapter.py`, `ib_translate.py`, `ib_adapter.py`, `oms.py` and `yfinance_source.py` are all in that scope.
- Run the four checks **separately**, never chained: `ruff check .`, `black --check .`, `mypy src`, `bandit -q -r src`. ⚠️ `black --check` can exit 0 while printing "1 file would be reformatted" — read the printed output, not the exit code.
- Use `.venv\Scripts\python.exe -m <tool>`, never a bare tool name — the venv's Scripts directory is not on PATH.
- Line length 100. Test files are named for the BEHAVIOUR, not the module, and open with a docstring saying why the test exists.
- Work on `master`. Do not push. Every commit message ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Nothing here is visible until a build, deploy and read-back after a market close. That is **not** part of this plan.

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/data/broker/adapter.py` | **Modify.** `Order` gains `filled_quantity`. |
| `src/qat/data/broker/ib_translate.py` | **Modify.** `from_ib_trade` populates it from `trade.orderStatus.filled` (line 321-327). |
| `src/qat/data/broker/mock_broker.py` | **Modify.** Populate on the synchronous fill path. |
| `src/qat/data/broker/simulated_broker.py` | **Modify.** Same. |
| `src/qat/domain/oms/oms.py` | **Modify.** `:861` books executed quantity; `:472-496` gains the broker-ceiling trim. |
| `src/qat/data/broker/ib_errors.py` | **Create.** The benign-code set and the classification. Its own file so the rule is readable without the adapter around it. |
| `src/qat/data/broker/ib_adapter.py` | **Modify.** Subscribe `errorEvent`, resolve `reqId` to an order, act on the classification. |
| `src/qat/config.py` | **Modify.** `broker_max_order_shares` only (Task 6). |
| `scripts/manual_body.py` | **Modify.** Document `broker_max_order_shares` (Task 6). |
| `src/qat/data/yfinance_source.py` | **Modify.** Validate the poll result; per-symbol health; instrumentation. |
| `pyproject.toml` | **Modify.** Pin yfinance. |

### ⚠️ Test conventions — verified, read before writing any test

- Test files are named for the BEHAVIOUR (`test_risk_console_anomalies.py`), not the module. There is no `test_oms.py`. Create new behaviour-named files.
- The Qt binding is PySide6; `asyncio_mode = "auto"` but existing async tests still carry `@pytest.mark.asyncio` — match the surrounding file.
- ⚠️ Construct settings as `Settings(_env_file=None)`. Without it the test loads the operator's live `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env`.
- Broker tests live under `tests/data/broker/`; OMS tests under `tests/domain/oms/`.

---

# PART ONE — THE ORDER PATH

Independently deployable. Stop after Task 6 and Part One ships on its own.

---

### Task 1: `Order.filled_quantity`

**Files:**
- Modify: `src/qat/data/broker/adapter.py` (the `Order` dataclass)
- Modify: `src/qat/data/broker/ib_translate.py:321-327`
- Create: `tests/data/broker/test_executed_quantity_is_carried.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Order.filled_quantity: float | None = None`, populated by `from_ib_trade` from `trade.orderStatus.filled`.

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_executed_quantity_is_carried.py`:

```python
"""An order's SIZE is not the amount that executed, and the app booked the size.

On 3 September TWS staged a 790-share BHP.AX order on a precautionary size limit
- it never reached the exchange - and the app booked all 790 because `oms.py:861`
read `order.quantity`. Reconciliation caught it four minutes later
(`tracked=790 broker=0`) and the kill switch halted flow.

`ib_async`'s `OrderStatus.filled` is the executed quantity and has always been
available; the handoff's claim that this needed a new broker-contract field
populated from scratch overstated the cost.
"""

from __future__ import annotations

from types import SimpleNamespace

from qat.data.broker.adapter import Order
from qat.data.broker.ib_translate import from_ib_trade


def _trade(status: str, filled: float, avg_price: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        order=SimpleNamespace(permId=0),
        orderStatus=SimpleNamespace(
            status=status, filled=filled, avgFillPrice=avg_price, permId=0
        ),
    )


def _order() -> Order:
    return Order(symbol="BHP.AX", side="buy", quantity=790.0, order_id="app-1")


def test_an_accepted_but_unfilled_order_carries_zero_executed():
    """⚠️ THE 3 SEPTEMBER CASE. Accepted by the broker, nothing executed."""
    result = from_ib_trade(_trade("PreSubmitted", filled=0.0), _order())

    assert result.filled_quantity == 0.0
    assert result.quantity == 790.0, "the ORDER's size is unchanged - they differ"


def test_a_partial_fill_carries_what_executed():
    result = from_ib_trade(_trade("Submitted", filled=400.0, avg_price=64.0), _order())

    assert result.filled_quantity == 400.0


def test_a_full_fill_carries_the_whole_quantity():
    result = from_ib_trade(_trade("Filled", filled=790.0, avg_price=64.0), _order())

    assert result.filled_quantity == 790.0


def test_the_field_defaults_to_none_meaning_unreported():
    """`None` is "this adapter does not report it" - a different claim from zero."""
    assert Order(symbol="BHP.AX", side="buy", quantity=1.0, order_id="x").filled_quantity is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_executed_quantity_is_carried.py -v
```

Expected: FAIL with `AttributeError: 'Order' object has no attribute 'filled_quantity'`.

- [ ] **Step 3: Add the field**

In `src/qat/data/broker/adapter.py`, in the `Order` dataclass immediately after `filled_price`:

```python
    # The amount that actually EXECUTED, as distinct from `quantity`, which is
    # what was ORDERED (3 September 2026).
    #
    # ⚠️ `None` means "this adapter does not report executed quantity", which is
    # a DIFFERENT CLAIM from zero. Read as the order's size it re-creates the
    # defect this field exists to fix - on 3 September TWS staged a 790-share
    # order on a precautionary limit and the app booked all 790 against a broker
    # holding none. Read as 0 it under-books a real fill.
    filled_quantity: float | None = None
```

- [ ] **Step 4: Populate it in `from_ib_trade`**

In `src/qat/data/broker/ib_translate.py`, after the `avgFillPrice` assignment (line 322-323):

```python
    # Unconditional, unlike `filled_price` above: 0.0 is a MEANINGFUL executed
    # quantity - it is the staged-order case - so an `if` here would leave it
    # None and lose the very reading that matters.
    our_order.filled_quantity = float(trade.orderStatus.filled)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_executed_quantity_is_carried.py -v
```

Expected: PASS, 4 tests.

- [ ] **Step 6: Run the four checks separately**

```bash
.venv/Scripts/python.exe -m ruff check .
```
```bash
.venv/Scripts/python.exe -m black --check .
```
```bash
.venv/Scripts/python.exe -m mypy src
```
```bash
.venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 7: Commit**

```bash
git add src/qat/data/broker/adapter.py src/qat/data/broker/ib_translate.py tests/data/broker/test_executed_quantity_is_carried.py
git commit -m "Order carries what executed, not only what was ordered"
```

---

### Task 2: The fakes report executed quantity too

**Files:**
- Modify: `src/qat/data/broker/mock_broker.py` (the `place_order` fill path)
- Modify: `src/qat/data/broker/simulated_broker.py` (same)
- Create: `tests/data/broker/test_fakes_report_executed_quantity.py`

**Interfaces:**
- Consumes: `Order.filled_quantity` (Task 1).
- Produces: both fakes set `filled_quantity` on every order they fill, so `None` never reaches the OMS from a test.

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_fakes_report_executed_quantity.py`:

```python
"""A fake that does not report executed quantity hides the defect being fixed.

The manual-close branch was rejected three times, each with 3,000+ tests passing,
because a fake did not model the real broker. If these two keep returning
`filled_quantity is None`, every OMS test exercises the absent path and none
exercises the real one.
"""

from __future__ import annotations

import pytest

from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.data.broker.simulated_broker import SimulatedBroker


def _order() -> Order:
    return Order(symbol="BHP.AX", side="buy", quantity=10.0, order_id="app-1")


@pytest.mark.asyncio
async def test_mock_broker_reports_what_it_filled():
    filled = await MockBroker().place_order(_order())

    assert filled.status == "filled"
    assert filled.filled_quantity == 10.0


@pytest.mark.asyncio
async def test_simulated_broker_reports_what_it_filled():
    filled = await SimulatedBroker().place_order(_order())

    assert filled.status == "filled"
    assert filled.filled_quantity == 10.0
```

⚠️ If either class needs constructor arguments, read the class and supply them —
do not change the class to suit the test.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_fakes_report_executed_quantity.py -v
```

Expected: FAIL with `assert None == 10.0`.

- [ ] **Step 3: Populate in both fakes**

In `src/qat/data/broker/mock_broker.py`, beside the existing `order.filled_price = fill_price`:

```python
        # These fakes fill synchronously and completely, so what executed IS the
        # order's size. Stated rather than left None, so OMS tests exercise the
        # populated path the real adapter takes.
        order.filled_quantity = order.quantity
```

Make the identical change in `src/qat/data/broker/simulated_broker.py` at its own
fill site. ⚠️ Do **not** set it on the protective-stop early return in either
file: a resting stop does not fill and does not change the position (M31d).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/ -v
```

Expected: PASS, with no existing broker test regressing.

- [ ] **Step 5: Commit**

```bash
git add src/qat/data/broker/mock_broker.py src/qat/data/broker/simulated_broker.py tests/data/broker/test_fakes_report_executed_quantity.py
git commit -m "The fakes report executed quantity, so tests exercise the real path"
```

---

### Task 3: ⛔ VOID — implemented, reviewed, reverted

**Do not implement this task.** It was written, reviewed and reverted on
3 September (`5cf7168`, reverted by `f84b55c`). Making sign-off book
`filled_quantity` is a live-path regression, reproduced by the review:

    AFTER  tracked=0.0   broker=790  ->  mismatch  ->  KILL SWITCH TRIPPED
    BEFORE tracked=790.0 broker=790  ->  clean

`place_order` returns before anything has executed — `_await_perm_id` waits for
the permId only — so `filled_quantity` is legitimately `0.0` at sign-off. And
nothing books it later, because `_is_foreign_unrecorded` excludes the app's own
orders. **Sign-off is the only quantity-booking site for an own order**, so
booking nothing there books nothing ever, and the protective stop later fires as
a foreign fill and is subtracted — a phantom SHORT against a flat broker.

⚠️ `oms.py:861` stays exactly as it is. The optimistic-book-plus-reconcile design
is not replaced; **Task 5b reverses the booking when a rejection proves the order
will never fill**, which is the actual gap.

Tasks 1 and 2 remain in: `Order.filled_quantity` is correct and is what Task 5b
uses to leave behind whatever really executed before the order died.

---

### Task 4: Classify IBKR errors, fail-closed

**Files:**
- Create: `src/qat/data/broker/ib_errors.py`
- Create: `tests/data/broker/test_ib_error_classification.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ErrorAction(Enum): IGNORE, REJECT, HALT`
  - `BENIGN_ORDER_ERROR_CODES: frozenset[int]`
  - `classify(code: int, *, is_order_scoped: bool) -> ErrorAction`

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_ib_error_classification.py`:

```python
"""IBKR told us the order was rejected and the app was not listening.

3 September, `logger=ib_async.wrapper`:

    Error 383, reqId 476: The following order "ID:476" size exceeds the Size
    Limit of 500. Restriction is specified in Precautionary Settings of Global
    Configuration/Presets.

Nothing consumed it. The app went on believing the order was live at the
exchange for over two hours.

⚠️ THE ENUMERATION IS OF THE BENIGN CODES ONLY. An unfamiliar rejection falls to
HALT. Enumerating the SERIOUS set is what made the manual-close branch green over
the exact defect it was named for, three times.
"""

from __future__ import annotations

from qat.data.broker.ib_errors import BENIGN_ORDER_ERROR_CODES, ErrorAction, classify


def test_a_known_benign_order_rejection_rejects_without_halting():
    assert classify(383, is_order_scoped=True) is ErrorAction.REJECT


def test_an_unknown_order_scoped_code_halts():
    """⚠️ FAIL CLOSED. 9999 is in nobody's list, which is the point."""
    assert classify(9999, is_order_scoped=True) is ErrorAction.HALT


def test_an_informational_code_with_no_order_is_ignored():
    """⚠️ 2104 is "market data farm connection is OK" and arrives as an ERROR.
    Fail-closed on unmatched errors would halt the system on a health notice."""
    assert classify(2104, is_order_scoped=False) is ErrorAction.IGNORE


def test_even_an_unknown_code_is_ignored_when_it_matches_no_order():
    assert classify(9999, is_order_scoped=False) is ErrorAction.IGNORE


def test_the_benign_set_is_the_enumerated_one():
    """A guard against someone 'simplifying' this into a serious-code list."""
    assert 383 in BENIGN_ORDER_ERROR_CODES
    assert 9999 not in BENIGN_ORDER_ERROR_CODES
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_ib_error_classification.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'qat.data.broker.ib_errors'`.

- [ ] **Step 3: Write the module**

Create `src/qat/data/broker/ib_errors.py`:

```python
"""What to do about an error IBKR reports, decided by failing closed.

⚠️ WHY THIS IS ITS OWN FILE. The rule is one sentence and it is the whole safety
of consuming `errorEvent`: enumerate the BENIGN codes, and let everything else
halt. Kept beside the adapter's connection and order plumbing it would be read as
plumbing.

On 3 September IBKR reported Error 383 - an order whose size exceeded a TWS
precautionary limit - and nothing in the application consumed it. The order was
never transmitted to the exchange, the app believed it was live, and only broker
reconciliation four minutes later disagreed.

⚠️ THE ENUMERATION DIRECTION IS THE POINT. Listing the SERIOUS codes would mean
every rejection nobody anticipated is waved through as routine. That is the shape
the manual-close branch was rejected for three times, each time with 3,000+ tests
passing. Here an unrecognised order-scoped code HALTS.
"""

from __future__ import annotations

from enum import Enum


class ErrorAction(Enum):
    """What the adapter should do about one error from IBKR."""

    IGNORE = "ignore"
    REJECT = "reject"
    HALT = "halt"


# Order-scoped codes known to mean "this order will not be accepted, and that is
# a configuration disagreement rather than a risk event".
#
# ⚠️ ADD TO THIS SET ONLY WITH EVIDENCE FROM A REAL REJECTION. Every code added
# here is one that will no longer halt, and the cost of being wrong is a genuine
# problem treated as routine.
#
# 383 - order size exceeds the TWS Precautionary Settings size limit. Observed
#       3 September 2026 on a 790-share order against a limit of 500.
BENIGN_ORDER_ERROR_CODES: frozenset[int] = frozenset({383})


def classify(code: int, *, is_order_scoped: bool) -> ErrorAction:
    """Decide what one IBKR error means for this application.

    ⚠️ `is_order_scoped` FIRST, and it is not a formality. `errorEvent` carries
    connection and market-data notices as well as order errors - code 2104 is
    "market data farm connection is OK" and arrives at ERROR level. Classifying
    those would halt the system on a health message, so an error that matches no
    order this app placed is ignored no matter what its code is.
    """
    if not is_order_scoped:
        return ErrorAction.IGNORE
    if code in BENIGN_ORDER_ERROR_CODES:
        return ErrorAction.REJECT
    return ErrorAction.HALT
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_ib_error_classification.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/qat/data/broker/ib_errors.py tests/data/broker/test_ib_error_classification.py
git commit -m "ib_errors: enumerate the benign codes, halt on everything else"
```

---

### Task 5: The adapter consumes `errorEvent`

**Files:**
- Modify: `src/qat/data/broker/ib_adapter.py` (`connect`, plus a new handler)
- Create: `tests/data/broker/test_ib_adapter_hears_rejections.py`

**Interfaces:**
- Consumes: `classify`, `ErrorAction` (Task 4); `Order.status` literal already includes `"rejected"` (`adapter.py:11`).
- Produces: `IBAdapter._on_ib_error(reqId, errorCode, errorString, contract) -> None`, and `IBAdapter._order_for_req_id(req_id: int) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_ib_adapter_hears_rejections.py`:

```python
"""Error 383 arrived, was logged by ib_async, and reached nothing.

The adapter subscribes to no ib_async events by design - its docstring says
connection health is an active heartbeat instead, "simpler to reason about and
test". That decision is right and unaffected: it concerns connection health,
where polling gives the same answer. It does not extend to order rejections,
because there is no polling equivalent - Error 383 is delivered by `errorEvent`
or not at all.
"""

from __future__ import annotations

import logging

import pytest

from qat.data.broker.ib_errors import ErrorAction


def test_a_benign_order_rejection_marks_the_order_rejected(adapter, order_on_the_wire):
    adapter._on_ib_error(order_on_the_wire.req_id, 383, "size exceeds the Size Limit of 500", None)

    assert adapter._orders[order_on_the_wire.app_id].status == "rejected"


def test_a_benign_rejection_does_not_halt(adapter, order_on_the_wire, published):
    adapter._on_ib_error(order_on_the_wire.req_id, 383, "size exceeds the Size Limit", None)

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_an_unknown_order_scoped_code_halts(adapter, order_on_the_wire, published):
    """⚠️ FAIL CLOSED."""
    adapter._on_ib_error(order_on_the_wire.req_id, 9999, "something nobody listed", None)

    assert adapter._orders[order_on_the_wire.app_id].status == "rejected"
    assert any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_an_error_matching_no_order_is_ignored(adapter, published, caplog):
    """⚠️ 2104 is a health notice. Halting on it would stop the system daily."""
    with caplog.at_level(logging.DEBUG):
        adapter._on_ib_error(999999, 2104, "Market data farm connection is OK", None)

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_the_handler_never_raises_into_the_callback(adapter, published):
    """ib_async calls this from its own event loop; an exception escaping here
    would surface inside the library, not in our stack.

    ⚠️ Asserts the CONSEQUENCES, not merely that nothing was raised. A test
    whose only content is "it did not throw" passes against a handler that
    silently swallows a real rejection, which is the failure mode this whole
    task exists to remove."""
    adapter._orders.clear()
    adapter._ib_orders.clear()

    adapter._on_ib_error(None, None, None, None)  # deliberately malformed

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published), (
        "a malformed error must not halt trading"
    )
    assert adapter._orders == {}, "no order should have been invented"
```

⚠️ `adapter`, `order_on_the_wire` and `published` are fixtures you must build.
Read `tests/data/broker/` for how an `IBAdapter` is constructed in this repo with
a fake `ib_client` and a fake bus — do not invent a construction path.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_ib_adapter_hears_rejections.py -v
```

Expected: FAIL with `AttributeError: 'IBAdapter' object has no attribute '_on_ib_error'`.

- [ ] **Step 3: Add the resolver and the handler**

In `src/qat/data/broker/ib_adapter.py`, add these methods to `IBAdapter`:

```python
    def _order_for_req_id(self, req_id: int) -> str | None:
        """The app's order id for an IBKR reqId, or None if it is not ours.

        ⚠️ THIS IS THE GATE THAT MAKES FAIL-CLOSED SAFE. `errorEvent` carries
        connection and market-data notices as well as order errors, so an error
        that matches no order of ours must never be classified - see
        `ib_errors.classify`.

        Bracket legs are searched too: a rejection can name a child's orderId,
        and the group is the same order as far as this app is concerned.
        """
        for app_id, ib_order in self._ib_orders.items():
            if getattr(ib_order, "orderId", None) == req_id:
                return app_id
        for app_id, group in self._ib_groups.items():
            if any(getattr(leg, "orderId", None) == req_id for leg in group):
                return app_id
        return None

    def _on_ib_error(
        self,
        req_id: object,
        error_code: object,
        error_string: object,
        contract: object = None,
    ) -> None:
        """React to an error IBKR reported. Never raises - ib_async calls this
        from its own event loop, where an escaping exception surfaces inside the
        library rather than in our stack."""
        try:
            code = int(error_code)  # type: ignore[arg-type]
            rid = int(req_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            logger.debug("IBKR error with unusable ids: %r %r", req_id, error_code)
            return

        try:
            app_id = self._order_for_req_id(rid)
            action = classify(code, is_order_scoped=app_id is not None)
            if action is ErrorAction.IGNORE:
                logger.debug("IBKR error %s (reqId %s) matches no order: %s", code, rid, error_string)
                return

            order = self._orders.get(app_id or "")
            if order is not None:
                order.status = "rejected"
            logger.error(
                "IBKR REJECTED order %s (reqId %s), code %s: %s. The order is marked "
                "rejected and will not be retried.",
                app_id,
                rid,
                code,
                error_string,
            )
            if action is ErrorAction.HALT:
                # ⚠️ Unrecognised, so it halts. Adding a code to
                # BENIGN_ORDER_ERROR_CODES is the deliberate way to stop this.
                asyncio.ensure_future(
                    self.bus.publish(
                        KillSwitchEvent(
                            reason=f"IBKR rejected an order with unrecognised code {code}: {error_string}",
                            triggered_by="ib-adapter",
                        )
                    )
                )
        except Exception:  # noqa: BLE001 - must not raise into ib_async's loop
            logger.exception("Failed to handle IBKR error %r", error_code)
```

Add the import beside the existing broker imports:

```python
from qat.data.broker.ib_errors import ErrorAction, classify
```

And subscribe in `connect`, after the `connectAsync` call succeeds:

```python
        # ⚠️ The module docstring's "no ib_async Events" decision is about
        # CONNECTION HEALTH, where an active heartbeat answers the same
        # question. It does not extend here: there is no polling equivalent for
        # an order rejection. Error 383 arrives on this event or nowhere.
        self.ib_client.errorEvent += self._on_ib_error
```

⚠️ Read `connect` first — it has two `connectAsync` call sites (around lines 187
and 253). Subscribe once, on the path that both reach, and make sure a reconnect
does not subscribe a second time.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/ -v
```

Expected: PASS.

- [ ] **Step 5: Run the four checks and the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```
```bash
.venv/Scripts/python.exe -m ruff check .
```
```bash
.venv/Scripts/python.exe -m black --check .
```
```bash
.venv/Scripts/python.exe -m mypy src
```
```bash
.venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/ib_adapter.py tests/data/broker/test_ib_adapter_hears_rejections.py
git commit -m "IBAdapter hears IBKR's rejections instead of only its return values"
```

---

### Task 5b: The OMS reverses a booking when an order is rejected

**This is the task that actually fixes 3 September.** Sign-off books the ORDERED
size optimistically; when a rejection proves the order will never fill, that
booking must come back out — otherwise the phantom persists and the
reconciliation rail trips every five minutes until a human intervenes, which is
precisely what happened.

**Files:**
- Modify: `src/qat/domain/events.py` (a new event)
- Modify: `src/qat/data/broker/ib_adapter.py` (publish it from `_on_ib_error`)
- Modify: `src/qat/domain/oms/oms.py` (subscribe and reverse)
- Create: `tests/domain/oms/test_a_rejected_order_gives_its_booking_back.py`

**Interfaces:**
- Consumes: `_on_ib_error` and the classification (Tasks 4, 5); `Order.filled_quantity` (Task 1).
- Produces: `OrderRejectedEvent(symbol: str, order_id: str, booked_quantity: float, executed_quantity: float | None, reason: str)`.

⚠️ **The adapter must NOT import the OMS.** It publishes over the bus exactly as
it already does for `KillSwitchEvent` (`ib_adapter.py:268`); the OMS subscribes.
That precedent is stated in the adapter's own module docstring.

⚠️ **Reverse the BOOKED amount minus what actually EXECUTED.** A partially filled
order that is then rejected or cancelled leaves a real position behind. Reversing
the full booked size would create a phantom short — the same defect in the other
direction, and the one the reverted Task 3 produced.

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/oms/test_a_rejected_order_gives_its_booking_back.py`:

```python
"""A rejected order kept its optimistic booking, and reconciliation paid for it.

3 September: TWS staged a 790-share BHP.AX order on a precautionary size limit.
Sign-off booked 790 - correctly, under a design that books optimistically and
lets reconciliation catch divergence. IBKR then said Error 383, nothing read it,
and the booking stood. `tracked=790 broker=0` tripped the kill switch every five
minutes for two hours, and the phantom counted toward the position cap, refusing
NST.AX with "already at the 10-position limit" against a book of nine.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_rejection_takes_the_whole_booking_back(oms):
    """Nothing executed, so nothing should remain booked."""
    await _sign_off_a_buy(oms, symbol="BHP.AX", quantity=790.0)
    assert oms._filled_quantities["BHP.AX"] == 790.0

    await _reject(oms, symbol="BHP.AX", booked=790.0, executed=0.0)

    assert oms._filled_quantities.get("BHP.AX", 0.0) == 0.0


@pytest.mark.asyncio
async def test_a_partially_filled_rejection_leaves_what_executed(oms):
    """⚠️ Reversing the FULL booking here would create a phantom short - the
    reverted Task 3's defect in the other direction."""
    await _sign_off_a_buy(oms, symbol="BHP.AX", quantity=790.0)

    await _reject(oms, symbol="BHP.AX", booked=790.0, executed=400.0)

    assert oms._filled_quantities["BHP.AX"] == 400.0


@pytest.mark.asyncio
async def test_an_unknown_executed_quantity_reverses_nothing(oms):
    """`executed_quantity is None` means the adapter did not say. Reversing on a
    guess could invent a short; leaving it lets reconciliation settle it, which
    is the path that caught 3 September in four minutes."""
    await _sign_off_a_buy(oms, symbol="BHP.AX", quantity=790.0)

    await _reject(oms, symbol="BHP.AX", booked=790.0, executed=None)

    assert oms._filled_quantities["BHP.AX"] == 790.0


@pytest.mark.asyncio
async def test_a_rejection_for_an_unknown_symbol_changes_nothing(oms):
    await _reject(oms, symbol="NEVER.AX", booked=100.0, executed=0.0)

    assert "NEVER.AX" not in oms._filled_quantities
```

⚠️ `oms`, `_sign_off_a_buy` and `_reject` are yours to write. **Read
`tests/domain/oms/` for how an `OMS` is constructed in this repo and drive the
real sign-off path** — a helper that writes `_filled_quantities` directly would
test the assertion and not the code.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_a_rejected_order_gives_its_booking_back.py -v
```

- [ ] **Step 3: Add the event, publish it, subscribe to it**

Add `OrderRejectedEvent` to `src/qat/domain/events.py` following the shape of the
events already there. Publish it from `_on_ib_error` in both the REJECT and HALT
branches — a halting rejection still needs its booking reversed. Subscribe in the
OMS beside its other bus subscriptions and reverse:

```python
        remaining = event.booked_quantity - event.executed_quantity
        self._filled_quantities[event.symbol] = (
            self._filled_quantities.get(event.symbol, 0.0) - remaining
        )
```

with `executed_quantity is None` returning early and logging, per the third test.

- [ ] **Step 4: Run the tests, then the FULL suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

⚠️ Live order path. A targeted run is not sufficient evidence. The baseline is
**3,147 passed / 26 skipped**.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/events.py src/qat/data/broker/ib_adapter.py src/qat/domain/oms/oms.py tests/domain/oms/test_a_rejected_order_gives_its_booking_back.py
git commit -m "A rejected order gives its optimistic booking back"
```

---

### Task 6: The sizer respects the broker's ceiling

**Files:**
- Modify: `src/qat/config.py` (beside `max_order_pct_of_cash`)
- Modify: `src/qat/domain/oms/oms.py` (after the per-order cash cap, around `:496`)
- Modify: `src/qat/data/broker/ib_adapter.py` (`_on_ib_error`, the 383 audit)
- Modify: `scripts/manual_body.py`
- Create: `tests/domain/oms/test_broker_share_ceiling.py`

**Interfaces:**
- Consumes: `_on_ib_error` (Task 5).
- Produces: `Settings.broker_max_order_shares: int | None = None`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/oms/test_broker_share_ceiling.py`:

```python
"""The sizer proposed 790 shares against a broker that refuses above 500.

TWS enforces a Precautionary Settings size limit that is NOT exposed through the
API - verified 3 September: no method on `IB` and no name in `ib_async` mentions
preset, precaution, limit, config or setting. So the app must be told it, and the
broker's own rejection audits what it was told.

Defaults to None - no ceiling - because a fresh install must not silently enforce
a limit belonging to one particular TWS instance.
"""

from __future__ import annotations

from qat.config import Settings


def test_the_ceiling_defaults_to_unset():
    assert Settings(_env_file=None).broker_max_order_shares is None


def test_an_order_above_the_ceiling_is_trimmed_to_it(oms_with_ceiling):
    """790 requested against a ceiling of 500 books an order of 500."""
    order = oms_with_ceiling(ceiling=500, requested_shares=790.0)

    assert order.quantity == 500.0


def test_an_order_below_the_ceiling_is_untouched(oms_with_ceiling):
    order = oms_with_ceiling(ceiling=500, requested_shares=400.0)

    assert order.quantity == 400.0


def test_no_ceiling_means_no_trim(oms_with_ceiling):
    order = oms_with_ceiling(ceiling=None, requested_shares=790.0)

    assert order.quantity == 790.0
```

⚠️ `oms_with_ceiling` is a fixture you must write, driving the real sizing path
around `oms.py:472-496`. Read that method and the existing OMS tests first.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_broker_share_ceiling.py -v
```

Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'broker_max_order_shares'`.

- [ ] **Step 3: Add the setting**

In `src/qat/config.py`, beside the other order-sizing settings:

```python
    # The largest share count this broker will accept without holding the order
    # for manual confirmation. NOT queryable through the IBKR API - it is a
    # TWS-local Precautionary Settings value - so the app has to be told.
    #
    # ⚠️ Defaults to None, meaning no ceiling is known and nothing is trimmed.
    # A default of 500 would silently enforce one particular TWS instance's
    # configuration on every install.
    #
    # On 3 September a 790-share order was STAGED rather than transmitted
    # against a limit of 500, and the app booked a position the broker never
    # held. Error 383 audits this value whenever IBKR rejects on size.
    broker_max_order_shares: int | None = Field(default=None, gt=0)
```

- [ ] **Step 4: Trim in the sizer**

In `src/qat/domain/oms/oms.py`, immediately after the per-order cash-cap block
(after `shares = trimmed`, around line 496):

```python
        ceiling = self.settings.broker_max_order_shares if self.settings is not None else None
        if ceiling is not None and shares > ceiling:
            logger.info(
                "%s trimmed from %g to %g shares by the broker's order-size ceiling "
                "(broker_max_order_shares). Above it the broker STAGES the order for "
                "manual confirmation rather than transmitting it, which on 3 September "
                "booked a position the exchange never took.",
                candidate.symbol,
                shares,
                float(ceiling),
            )
            shares = float(ceiling)
```

- [ ] **Step 5: Audit the setting from Error 383**

In `_on_ib_error` in `src/qat/data/broker/ib_adapter.py`, before the `HALT` branch:

```python
            if code == 383:
                self._audit_size_limit(str(error_string))
```

And add the method:

```python
    _SIZE_LIMIT_PATTERN = re.compile(r"Size Limit of (\d+)")

    def _audit_size_limit(self, message: str) -> None:
        """Compare the broker's stated size limit with what we were configured.

        ⚠️ AUDITS, NEVER DECIDES. The parsed number is not applied: a rail that
        depended on IBKR's error wording staying stable would be one string
        change away from silently doing nothing. The configured value is the
        belief; this is what catches it drifting.
        """
        match = self._SIZE_LIMIT_PATTERN.search(message)
        if match is None:
            return
        broker_limit = int(match.group(1))
        configured = self.settings.broker_max_order_shares
        if configured is None:
            logger.warning(
                "The broker enforces an order-size limit of %d shares and "
                "broker_max_order_shares is UNSET, so the sizer will keep proposing "
                "above it. Set it to %d.",
                broker_limit,
                broker_limit,
            )
        elif configured != broker_limit:
            logger.warning(
                "broker_max_order_shares is %d but the broker says its limit is %d. "
                "One of them is wrong and the sizer is trusting the configured value.",
                configured,
                broker_limit,
            )
```

Add `import re` to the module's imports if absent.

- [ ] **Step 6: Document the setting in the manual**

⚠️ **Not optional.** `tests/test_manual_documents_every_setting.py` fails
otherwise, and a targeted test run will not show it. Read `scripts/manual_body.py`
and add `QAT_BROKER_MAX_ORDER_SHARES` to Appendix B in the surrounding style:
what it is, that it defaults to unset, that the broker's limit is not queryable
so it must be set by hand, and that Error 383 warns when the two disagree.

- [ ] **Step 7: Run the tests, then the FULL suite**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_broker_share_ceiling.py tests/test_manual_documents_every_setting.py -v
```
```bash
.venv/Scripts/python.exe -m pytest -q
```

- [ ] **Step 8: Commit**

```bash
git add src/qat/config.py src/qat/domain/oms/oms.py src/qat/data/broker/ib_adapter.py scripts/manual_body.py tests/domain/oms/test_broker_share_ceiling.py
git commit -m "The sizer respects the broker's ceiling, and the broker audits it"
```

---

# PART TWO — THE FEED

Nothing here may halt, refuse an order, or change what is traded.

---

### Task 7: The poll validates what came back

**Files:**
- Modify: `src/qat/data/yfinance_source.py:306-345` (`_poll_once`)
- Create: `tests/data/test_the_feed_notices_a_partial_response.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_poll_once` returns `tuple[list[RawTick], set[str]]` — the ticks, and the app-spelled symbols that were requested but returned nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_the_feed_notices_a_partial_response.py`:

```python
"""`download()` does not raise, so our own failure warning never fired.

3 September: yfinance logged `HTTP Error 401 ... Invalid Crumb` under its OWN
logger and returned a frame. `_poll_once` wraps the call in try/except, so
nothing was caught - and `yfinance quote poll failed` appeared ZERO times while
the app had no usable quote for 25 minutes.

A partial response has to be a measured fact, not an absence.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.data.yfinance_source import YFinanceMarketDataSource


class _Client:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def download(self, tickers, **kwargs):
        return self._frame


@pytest.mark.asyncio
async def test_symbols_absent_from_the_response_are_reported():
    """⚠️ The 3 September shape: one symbol answers, the rest do not."""
    source = YFinanceMarketDataSource(client=_Client(_one_symbol_frame()))

    ticks, missing = await source._poll_once(["BHP.AX", "CBA.AX", "WOW.AX"])

    assert {t.symbol for t in ticks} == {"BHP.AX"}
    assert missing == {"CBA.AX", "WOW.AX"}


@pytest.mark.asyncio
async def test_a_complete_response_reports_nothing_missing():
    source = YFinanceMarketDataSource(client=_Client(_all_symbols_frame()))

    ticks, missing = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert missing == set()


@pytest.mark.asyncio
async def test_an_exception_reports_every_symbol_missing():
    class _Boom:
        def download(self, tickers, **kwargs):
            raise RuntimeError("network gone")

    source = YFinanceMarketDataSource(client=_Boom())

    ticks, missing = await source._poll_once(["BHP.AX", "CBA.AX"])

    assert ticks == []
    assert missing == {"BHP.AX", "CBA.AX"}
```

⚠️ `_one_symbol_frame()` and `_all_symbols_frame()` are helpers you must write,
returning the multi-index frame shape `normalise_frame` expects. Read
`normalise_frame` and the existing yfinance tests for the real shape — a frame of
the wrong shape would make these tests pass for the wrong reason.

The class is `YFinanceMarketDataSource` (`yfinance_source.py:201`). Its
constructor already takes `client`, `poll_seconds`, `max_consecutive_failures`
and `max_backoff_seconds`, so a fake client is injected directly.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_the_feed_notices_a_partial_response.py -v
```

Expected: FAIL — `_poll_once` returns a list, not a tuple.

- [ ] **Step 3: Return what is missing as well as what arrived**

In `src/qat/data/yfinance_source.py`, change `_poll_once`'s signature and both
return paths:

```python
    async def _poll_once(self, symbols: list[str]) -> tuple[list[RawTick], set[str]]:
        """The ticks that arrived, and the symbols that did not.

        ⚠️ MISSING SYMBOLS ARE RETURNED, NOT INFERRED. `yfinance.download` does
        NOT raise on an authentication or rate-limit failure - it logs its own
        ERROR and hands back a frame - so the `except` below never fired on
        3 September and this method returned an empty list that the caller read
        as "the feed answered". A partial response is now a measured fact.
        """
        vendor = {to_yfinance(symbol): symbol for symbol in symbols}
        try:
            raw = await asyncio.to_thread(...)   # unchanged call
        except Exception:  # noqa: BLE001 - an unofficial feed fails in many ways
            logger.warning("yfinance quote poll failed", exc_info=True)
            return [], set(symbols)
```

and at the end, alongside the existing `ticks` accumulation, track which vendor
symbols produced no usable row and return
`ticks, {vendor[v] for v in missing_vendor_symbols}`.

⚠️ Report in the APP's spelling, not Yahoo's — the method already translates both
ways for exactly this reason.

- [ ] **Step 4: Update the caller**

`stream_ticks` currently does `ticks = await self._poll_once(symbol_list)`. Change
it to unpack the tuple; leave its behaviour otherwise identical in this task —
per-symbol health is Task 8.

```python
            ticks, missing = await self._poll_once(symbol_list)
```

- [ ] **Step 5: Run the tests, then the feed suite**

```bash
.venv/Scripts/python.exe -m pytest tests/data/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/yfinance_source.py tests/data/test_the_feed_notices_a_partial_response.py
git commit -m "The feed poll reports which symbols did not answer"
```

---

### Task 8: Per-symbol health

**Files:**
- Modify: `src/qat/data/yfinance_source.py` (`__init__`, `stream_ticks`, `_delay_after`)
- Create: `tests/data/test_one_symbol_cannot_mask_an_outage.py`

**Interfaces:**
- Consumes: `_poll_once -> tuple[list[RawTick], set[str]]` (Task 7).
- Produces: `YFinanceMarketDataSource.__init__` gains
  `down_symbol_fraction: float = 0.5`.

⚠️ **A CONSTRUCTOR ARGUMENT, NOT A `Settings` FIELD — and this corrects an
earlier draft of this plan.** `max_consecutive_failures` is already a constructor
argument with a default of 5 (`yfinance_source.py:210-217`), not a setting. The
source is built at `runtime.py:217` as
`YFinanceMarketDataSource(poll_seconds=settings.yfinance_poll_seconds)`. Adding a
`Settings` field for the sibling of an existing constructor argument would put two
knobs of the same kind in two different places.

**Consequence: this task touches neither `config.py` nor `scripts/manual_body.py`**,
and the Settings/manual constraint in the Global Constraints does not apply to it.
It still applies to Task 6.

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_one_symbol_cannot_mask_an_outage.py`:

```python
"""One symbol answering hid a ninety-nine symbol outage.

`stream_ticks` held ONE counter and reset it whenever a poll produced any tick:

    if ticks:
        consecutive_failures = 0

On 3 September exactly one of 100 symbols answered, for 25 minutes. There was no
`poll produced no ticks` line, no `MARKET DATA DOWN`, and the app placed an order
whose price-drift check was skipped for want of a quote.

⚠️ AND THE OPEN MUST NOT TRIP IT. Yahoo publishes ASX intraday ~20 minutes late,
so at every open EVERY symbol is legitimately absent. On 21 August that shape
ended the stream at 10:04 waiting for data that arrived at 10:22, and the account
sat flat and blind on an open market. That is the M119 regression this test set
exists to prevent as much as the outage itself.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from qat.data.yfinance_source import YFinanceMarketDataSource

SYMBOLS = [f"S{i}.AX" for i in range(100)]


class _PartialClient:
    """Answers for `answering` and returns nothing for the rest, every poll."""

    def __init__(self, answering: list[str]) -> None:
        self.answering = answering

    def download(self, tickers, **kwargs):
        # ⚠️ Build the frame the way normalise_frame expects. Read
        # `normalise_frame` before changing this - a frame of the wrong shape
        # makes these tests pass for the wrong reason.
        raise NotImplementedError("build the multi-index frame - see normalise_frame")


async def _drain(source: YFinanceMarketDataSource, polls: int) -> None:
    """Drive `stream_ticks` for a fixed number of polls without real sleeps."""
    raise NotImplementedError("patch asyncio.sleep and step the generator")


@pytest.mark.asyncio
async def test_one_answering_symbol_does_not_mask_the_other_ninety_nine(caplog):
    """⚠️ THE 3 SEPTEMBER CASE, and the test this task exists for."""
    source = YFinanceMarketDataSource(
        client=_PartialClient(answering=[SYMBOLS[0]]), max_consecutive_failures=5
    )

    with caplog.at_level(logging.ERROR):
        await _drain(source, polls=6)

    assert "market data is down" in caplog.text.lower()
    assert "S1.AX" in caplog.text, "the DOWN line must NAME the failing symbols"


@pytest.mark.asyncio
async def test_a_single_absent_symbol_never_reports_down(caplog):
    """One delisted or thinly-traded name is not an outage."""
    source = YFinanceMarketDataSource(
        client=_PartialClient(answering=SYMBOLS[1:]), max_consecutive_failures=5
    )

    with caplog.at_level(logging.ERROR):
        await _drain(source, polls=6)

    assert "market data is down" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_the_open_does_not_report_down(caplog):
    """⚠️ THE M119 REGRESSION, ASSERTED DIRECTLY. At the open Yahoo has published
    nothing yet, so ALL symbols are absent - legitimately, for ~20 minutes. On
    21 August that shape ended the stream and the account sat blind on an open
    market for two hours."""
    source = YFinanceMarketDataSource(
        client=_PartialClient(answering=[]), max_consecutive_failures=5
    )

    with caplog.at_level(logging.ERROR):
        await _drain(source, polls=6)

    assert "market data is down" not in caplog.text.lower()


@pytest.mark.asyncio
async def test_coverage_returning_resets_the_counters(caplog):
    """After the delay window clears, a full response must clear the state -
    otherwise every session reports DOWN for the rest of the day."""
    raise NotImplementedError("drive partial polls, then full ones, assert recovery")
```

⚠️ **The three `NotImplementedError` bodies above are yours to write**, and they
are marked rather than guessed because none of them can be written correctly
without reading the code first:

* `_PartialClient.download` must return the multi-index frame shape
  `normalise_frame` expects. Read `normalise_frame` (`yfinance_source.py:78`) and
  copy the shape an existing test in `tests/data/test_yfinance_source.py` builds.
* `_drain` must step `stream_ticks` without waiting on real 60-second sleeps.
  Read `tests/data/test_feed_health.py` for how this repo drives an async
  generator in a test.
* The recovery test needs a client whose answers change between polls.

⚠️ A frame of the wrong shape would make every one of these pass for the wrong
reason, which is precisely the failure this project has hit three times.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_one_symbol_cannot_mask_an_outage.py -v
```

- [ ] **Step 3: Add the constructor argument**

In `src/qat/data/yfinance_source.py`, in `YFinanceMarketDataSource.__init__`
beside `max_consecutive_failures`:

```python
        down_symbol_fraction: float = 0.5,
```

```python
        # The share of watched symbols that must be failing before the feed is
        # reported DOWN. A symbol counts as failing once it has missed
        # `max_consecutive_failures` polls in a row.
        #
        # ⚠️ Half, not "any". One delisted or thinly-traded symbol must never
        # report the feed down; 99 of 100 silent for twenty-five minutes
        # (3 September) must, and did not.
        self.down_symbol_fraction = down_symbol_fraction
```

⚠️ A constructor argument, matching `max_consecutive_failures` beside it — not a
`Settings` field. See this task's Interfaces block for why.

- [ ] **Step 4: Replace the counter**

In `stream_ticks`, replace the single `consecutive_failures` int with a
`dict[str, int]` keyed by symbol. On each poll, increment every symbol in
`missing` and reset every symbol that produced a tick. The feed is DOWN when

    failing = {s for s, n in counters.items() if n >= self.max_consecutive_failures}
    len(failing) >= self.feed_down_symbol_fraction * len(symbol_list)

⚠️ **Guard the open.** While `BLIND_WINDOW_FILTER.blind` is set, counters
accumulate but DOWN is not reported. That filter is already set from the first
empty poll (item 54) and cleared on recovery, so it is the existing notion of the
same window — do not invent a second one.

The DOWN log line must **name the failing symbols** (truncated), which is the
entire reason for counting per symbol.

⚠️ `_delay_after` takes a single int today. Give it the failing count, or the
backoff will no longer match the state it is backing off from.

- [ ] **Step 5: Run the tests, then the FULL suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/yfinance_source.py tests/data/test_one_symbol_cannot_mask_an_outage.py
git commit -m "Feed health is measured per symbol, so one answer cannot mask an outage"
```

---

### Task 9: Instrument the poisoning — do not fix it

**Files:**
- Modify: `src/qat/data/yfinance_source.py` (`_poll_once`)
- Create: `tests/data/test_a_failed_poll_records_what_came_back.py`

**Interfaces:**
- Consumes: `_poll_once` (Task 7).
- Produces: nothing new.

⚠️ **NO SESSION RESET SHIPS.** Three hypotheses for the process-local poisoning
were tested on 3 September and all three failed: it is not the batch size (100,
75, 50, 30, 20 and 10 all returned complete data in a fresh process), not the
crumb on the price path (a deliberately poisoned `_crumb` still returned 295
rows — `download()` does not use it), and not an ongoing 401 storm (13 errors
between 14:51:28 and 14:52:15, then nothing, while the outage ran 25 more
minutes). **The mechanism is unknown.** This task gathers evidence; the fix waits
for it.

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_a_failed_poll_records_what_came_back.py`:

```python
"""Three hypotheses were tested on 3 September and all three failed.

NOT the batch size: in a fresh process 100, 75, 50, 30, 20 and 10 symbols all
returned complete data, 100/100 in 3.7s. NOT the crumb on the price path: a
deliberately poisoned `_crumb` still returned 295 rows, because `download()` does
not use it. NOT an ongoing 401 storm: the burst was 13 errors between 14:51:28 and
14:52:15, then nothing, while the outage ran twenty-five minutes longer.

So the mechanism is UNKNOWN, and this records what a failing poll actually saw
rather than shipping a remedy for a guess.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from qat.data.yfinance_source import YFinanceMarketDataSource


class _EmptyClient:
    def download(self, tickers, **kwargs):
        return pd.DataFrame()


@pytest.mark.asyncio
async def test_a_partial_poll_records_requested_against_returned(caplog):
    source = YFinanceMarketDataSource(client=_EmptyClient())

    with caplog.at_level(logging.WARNING):
        await source._poll_once(["BHP.AX", "CBA.AX", "WOW.AX"])

    assert "3" in caplog.text, "the number REQUESTED must be recorded"
    assert "0" in caplog.text, "the number RETURNED must be recorded"


@pytest.mark.asyncio
async def test_the_probe_records_whether_a_session_was_cached(caplog):
    """The one fact that separates a poisoned process from a poisoned account."""
    source = YFinanceMarketDataSource(client=_EmptyClient())

    with caplog.at_level(logging.WARNING):
        await source._poll_once(["BHP.AX"])

    lowered = caplog.text.lower()
    assert "crumb" in lowered and "cookie" in lowered


@pytest.mark.asyncio
async def test_a_complete_poll_records_nothing(caplog):
    """The probe must not add a line to every healthy poll - 60 a minute of
    them would bury the one that matters."""
    raise NotImplementedError("supply a client returning all requested symbols")


@pytest.mark.asyncio
async def test_the_probe_never_breaks_the_poll(caplog):
    """⚠️ A diagnostic must never break the feed it is diagnosing. If reading
    YfData's cached state raises, the poll still returns its ticks."""
    raise NotImplementedError("monkeypatch the introspection to raise, assert the poll survives")
```

⚠️ **The two `NotImplementedError` bodies are yours**, and they are the two that
cannot be written without reading the code: one needs a client returning the full
multi-index frame `normalise_frame` expects, and one needs to know how the probe
reaches `YfData`.

⚠️ Read `yfinance.data.YfData` before writing the probe — it is a singleton via
`SingletonMeta`, so reading its cached state must not construct a second one or
mutate anything.

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_a_failed_poll_records_what_came_back.py -v
```

- [ ] **Step 3: Add the instrumentation**

In `_poll_once`, when `missing` is non-empty, log once at WARNING with: how many
symbols were requested and how many returned, and whether a cookie and crumb were
cached. Wrap the introspection in its own `try/except` — **a diagnostic must
never break the feed it is diagnosing.**

- [ ] **Step 4: Run the tests**

```bash
.venv/Scripts/python.exe -m pytest tests/data/ -v
```

- [ ] **Step 5: Commit**

```bash
git add src/qat/data/yfinance_source.py tests/data/test_a_failed_poll_records_what_came_back.py
git commit -m "Record what a failed poll actually returned, so the next one names the cause"
```

---

### Task 10: Pin yfinance

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Change the pin**

`yfinance>=0.2.40` is unbounded and **1.5.2** is installed — a major-version drift
on an unofficial API that no test would have caught. Change to:

```toml
    "yfinance>=1.5.2,<2",
```

Floor at what is actually running and tested; ceiling below the next major.

- [ ] **Step 2: Verify the installed version still satisfies it**

```bash
.venv/Scripts/python.exe -c "import yfinance; print(yfinance.__version__)"
```

Expected: `1.5.2`.

- [ ] **Step 3: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Pin yfinance below the next major - 0.2 to 1.5 drifted in unnoticed"
```

---

### Task 11: Full verification

- [ ] **Step 1: Full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Read the final line. Do not infer from the exit code.

- [ ] **Step 2-5: The four checks, separately**

```bash
.venv/Scripts/python.exe -m ruff check .
```
```bash
.venv/Scripts/python.exe -m black --check .
```
```bash
.venv/Scripts/python.exe -m mypy src
```
```bash
.venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 6: Sabotage — prove the two central rails bite**

⚠️ **Commit everything first.** `git checkout` on an uncommitted file discards the
real edit along with the sabotage; that happened on 2 September.

```bash
git status --porcelain
```

Expected: empty.

**Rail one — fail-closed classification.** In `src/qat/data/broker/ib_errors.py`,
change `return ErrorAction.HALT` to `return ErrorAction.REJECT`, then:

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_ib_error_classification.py -k unknown -v
```

Expected: **FAIL.** Restore with `git checkout src/qat/data/broker/ib_errors.py`.

**Rail two — the booking reversal.** In `src/qat/domain/oms/oms.py`, change
the reversal to subtract `event.booked_quantity` instead of
`booked_quantity - executed_quantity`, then:

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_a_rejected_order_gives_its_booking_back.py -v
```

Expected: **FAIL** on `test_a_partially_filled_rejection_leaves_what_executed`,
showing a phantom SHORT where 400 shares really executed — the reverted Task 3
defect in the other direction. Restore, then confirm:

```bash
git status --porcelain
```

Expected: empty.

- [ ] **Step 7: Bump the milestone**

Bump `MILESTONE` in `src/qat/version.py` with a comment block covering: that both
failures were libraries reporting a problem the app was not reading; that
`OrderStatus.filled` always existed so the recorded cost of Defect B was
overstated; that the classification enumerates the benign set so an unfamiliar
rejection halts; that `errorEvent` also carries health notices, which is why
order-scoping comes first; and that no yfinance session reset ships because three
hypotheses were tested and all three failed.

```bash
git add src/qat/version.py
git commit -m "M165: hear the rejection, and say when the feed is blind"
```

- [ ] **Step 8: Report, do not deploy**

Deploying is separate and operator-gated: build, confirm the dist hash MOVED,
sign, dry run, **ask**, `-Apply`, then read the build stamp back off the app's own
log. Do not begin it as part of executing this plan.

---

## Self-review notes

- **Spec coverage:** A → Tasks 1-3; B → Tasks 4-5; C → Task 6; D → Task 7; E → Task 8; F → no task, correctly (report-only means nothing changes); G → Task 9; H → Task 10. Error handling and Testing → each task's own steps plus Task 11.
- **Deliberately unresolved, and flagged rather than guessed:** several tasks name a fixture or a class the plan could not verify without reading further (`oms`, `_record_fill`, `adapter`, `order_on_the_wire`, `YFinanceMarketDataSource`). Each such step says to read the real file and use the real name. That is honest ignorance, not a placeholder — inventing a plausible name would be worse, because it would look correct.
- **Type consistency:** `filled_quantity: float | None` is used identically in Tasks 1, 2, 3. `ErrorAction`/`classify` signatures match between Tasks 4 and 5. `_poll_once`'s tuple return is introduced in Task 7 and consumed in Tasks 8 and 9.
- **The riskiest task is 3**, because it changes the live order path and every OMS test runs through it. It is the only Part One task whose steps mandate a full-suite run before commit.
