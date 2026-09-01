# Manual Position Close Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator close one app-managed position in full from the dashboard, cancelling its OCA protective legs first and restoring them if the sell fails.

**Architecture:** A domain service `PositionCloser` owns the whole sequence — read legs from the broker, cancel, verify, sell through the OMS, recover on failure. The dashboard contributes only a button and a confirmation dialog. A prerequisite fix stops `IBAdapter.cancel_order` reporting cancels it did not perform.

**Tech Stack:** Python 3.12, `ib_async` 2.1.0, PySide6, pytest, `MockBroker` for tests.

Spec: `docs/superpowers/specs/2026-09-01-manual-position-close-design.md`

## Global Constraints

- **PowerShell for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal`**, including Python that only reads it — `Settings()` loads that directory's `.env`. The Bash sandbox serves a frozen snapshot and does not error.
- **Run the four checks SEPARATELY, never chained with `&&`.** `black --check` can exit 0 while printing "1 file would be reformatted".
  - `.\.venv\Scripts\python.exe -m ruff check src scripts tests`
  - `.\.venv\Scripts\python.exe -m black --check src scripts tests`
  - `.\.venv\Scripts\python.exe -m mypy src`
  - `.\.venv\Scripts\python.exe -m bandit -q -r src -c pyproject.toml`
- **Do not reference Alpaca.** The broker is IBKR, the market ASX, the price source yfinance.
- Full suite baseline: **2,993 passed, 26 skipped**. It must not drop.
- v1 is **full close only** and **market orders only**. `quantity` is reserved and must be refused when not `None`.
- Never send an order while another is working (M139). One order, no retry loop.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/domain/oms/position_closer.py` (create) | `CloseOutcome`, `CloseResult`, `PositionCloser`. The entire sequence. No Qt. |
| `src/qat/data/broker/ib_adapter.py` (modify, ~747-789) | `cancel_order` resolves previous-session orders from the live client, or raises. Never a silent local cancel. |
| `src/qat/presentation/dashboard.py` (modify, ~282-290) | "Close Position" button, selection gating, confirmation dialog, result rendering. |
| `tests/data/broker/test_ib_cancel_resolves.py` (create) | The adapter fix, including its raise path. |
| `tests/domain/oms/test_position_closer.py` (create) | Preconditions, sequence, recovery, and the sabotage checks. |
| `tests/presentation/test_close_position_button.py` (create) | Button gating and that the dialog gates the call. |

---

### Task 1: `IBAdapter.cancel_order` must never claim a cancel it did not perform

**Files:**
- Modify: `src/qat/data/broker/ib_adapter.py:747-789`
- Test: `tests/data/broker/test_ib_cancel_resolves.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `IBAdapter.cancel_order(order_id: str) -> Order` raises `CancelNotResolvedError` when the order cannot be resolved. `class CancelNotResolvedError(Exception)` exported from `qat.data.broker.ib_adapter`.

Today, when `_ib_orders` and `_ib_groups` have no entry — true for **every order placed in a previous session**, because order identity does not survive a restart — the method sets `order.status = "cancelled"` and returns success **without touching the broker**.

⚠️ **CORRECTION TO THE SPEC.** The spec names `OMS.cancel_order()` as the method with the silent-cancel branch. **It is not** — `OMS.cancel_order` does `self._orders[order_id]` and raises `KeyError` on an unknown order, which is already fail-closed. The silent branch is in **`IBAdapter.cancel_order`**, one layer down, and that is what this task fixes. Update the spec's "prerequisite fix" section to name the adapter when this task is done.

- [ ] **Step 1: Write the failing test**

```python
# tests/data/broker/test_ib_cancel_resolves.py
import pytest

from qat.data.broker.ib_adapter import CancelNotResolvedError


@pytest.mark.asyncio
async def test_cancel_raises_when_the_order_cannot_be_resolved(adapter_with_empty_maps):
    """A cancel that reaches no broker must NOT report success.

    Before this, a leg from a previous session took the `if not group:` branch,
    was marked cancelled locally, and returned an Order with status
    "cancelled" - so a caller would go on to sell while both OCA legs were
    still resting, and be put short.
    """
    adapter = adapter_with_empty_maps
    with pytest.raises(CancelNotResolvedError) as excinfo:
        await adapter.cancel_order("1216552518")
    assert "1216552518" in str(excinfo.value)


@pytest.mark.asyncio
async def test_cancel_resolves_a_previous_session_order_from_the_live_client(
    adapter_with_live_trade,
):
    """reqAllOpenOrders populates the client's open trades, so a permId this
    session never placed is still resolvable - and must be cancelled for real."""
    adapter, client = adapter_with_live_trade
    result = await adapter.cancel_order("1216552518")
    assert result.status == "cancelled"
    assert client.cancelled_perm_ids == [1216552518]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_cancel_resolves.py -v`
Expected: FAIL — `ImportError: cannot import name 'CancelNotResolvedError'`.

- [ ] **Step 3: Add the exception and the resolution fallback**

```python
# src/qat/data/broker/ib_adapter.py - near the other adapter exceptions
class CancelNotResolvedError(Exception):
    """A cancel could not be resolved to a live broker order.

    ⚠️ RAISED RATHER THAN REPORTED AS SUCCESS. This method used to set
    `order.status = "cancelled"` and return when `_ib_groups` had no entry -
    which is EVERY order placed in a previous session, because order identity
    does not survive a restart. A caller that then sold would leave both OCA
    protective legs resting against a position no longer held, and be put
    short. A cancel that reached no broker is a failure, not a cancel.
    """
```

Then, inside `cancel_order`, replace the `if not group:` branch:

```python
        group = self._ib_groups.get(order_id) or ([ib_order] if ib_order is not None else [])
        if not group:
            # ⚠️ FALL BACK TO THE LIVE CLIENT before giving up. `open_orders()`
            # calls reqAllOpenOrdersAsync, which populates the client's open
            # trades with orders this session never placed - exactly the
            # previous-session legs this path exists for.
            group = self._resolve_from_open_trades(order_id)
        if not group:
            raise CancelNotResolvedError(
                f"cancel_order({order_id!r}) resolved no live broker order. This "
                f"session did not place it and the client does not report it, so "
                f"nothing was cancelled - reporting success here is what would put "
                f"the account short."
            )
```

And the resolver:

```python
    def _resolve_from_open_trades(self, order_id: str) -> list[object]:
        """Live orders matching `order_id`, matched on permId.

        `RestingOrder.order_id` carries the broker's permId, which is what
        survives a restart - `orderId` is per-session and does not.
        """
        open_trades = getattr(self.ib_client, "openTrades", None)
        if not callable(open_trades):
            return []
        found: list[object] = []
        for trade in open_trades():
            order = getattr(trade, "order", None)
            if order is None:
                continue
            if str(getattr(order, "permId", "")) == str(order_id):
                found.append(order)
        return found
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_cancel_resolves.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the existing adapter tests — this changes a shared method**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker -q`
Expected: all pass. If a test relied on the silent-cancel branch, that test was asserting the defect — fix the test and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/ib_adapter.py tests/data/broker/test_ib_cancel_resolves.py
git commit -m "IBAdapter.cancel_order: resolve from the live client, or raise"
```

---

### Task 2: `CloseResult` and the preconditions that refuse

**Files:**
- Create: `src/qat/domain/oms/position_closer.py`
- Test: `tests/domain/oms/test_position_closer.py`

**Interfaces:**
- Consumes: `CancelNotResolvedError` from Task 1.
- Produces:
  - `class CloseOutcome(Enum)` with members `CLOSED`, `REFUSED`, `RECOVERED`, `UNPROTECTED`
  - `@dataclass(frozen=True, slots=True) class CloseResult` with `outcome: CloseOutcome`, `symbol: str`, `quantity: float`, `cancelled_legs: tuple[str, ...]`, `detail: str`
  - `class PositionCloser` with `__init__(self, oms, broker, kill_switch, entries)` and `async def close_position(self, symbol: str, *, operator: str, acknowledge_halt: bool = False, quantity: float | None = None) -> CloseResult`

This task delivers **only the refusals**. Nothing is cancelled and nothing is sold yet — every path returns `REFUSED`.

- [ ] **Step 0: Write the test fixtures — every later task uses these**

```python
# tests/domain/oms/test_position_closer.py  (top of file)
from dataclasses import dataclass

import pytest

from qat.data.broker.adapter import Order, Position, RestingOrder


def _leg(symbol, order_id, order_type, *, stop=None, limit=None, status="Submitted"):
    return RestingOrder(
        symbol=symbol, order_id=order_id, side="sell", order_type=order_type,
        quantity=100.0, status=status, oca_group="oca-1",
        stop_price=stop, limit_price=limit,
    )


@dataclass
class _Entry:
    price: float = 100.0


class _FakeBroker:
    def __init__(self, positions, legs, legs_after_cancel, positions_after_cancel, cancel_raises):
        self._positions = positions
        self._positions_after = positions_after_cancel
        self._legs = legs
        self._legs_after = legs_after_cancel
        self._cancel_raises = cancel_raises
        self.open_orders_calls = 0
        self._cancelled = False

    async def positions(self):
        source = self._positions_after if (self._cancelled and self._positions_after) else self._positions
        return [Position(symbol=s, quantity=q, avg_price=100.0) for s, q in source.items()]

    async def open_orders(self):
        self.open_orders_calls += 1
        return list(self._legs_after) if self._cancelled else list(self._legs)

    async def cancel_order(self, order_id):
        if self._cancel_raises is not None:
            raise self._cancel_raises
        self._cancelled = True
        return Order(symbol="X", side="sell", quantity=0.0, order_id=order_id, status="cancelled")


class _FakeOms:
    def __init__(self, exit_rejected, reprotect_raises):
        self.exit_orders = []
        self.signed_off = []
        self.protective_orders = []
        self._exit_rejected = exit_rejected
        self._reprotect_raises = reprotect_raises

    async def submit_exit_order(self, symbol, quantity, price, reason="signal"):
        self.exit_orders.append((symbol, quantity, reason))
        status = "rejected" if self._exit_rejected else "pending_signoff"
        return Order(symbol=symbol, side="sell", quantity=quantity,
                     order_id=f"order-{len(self.exit_orders)}", status=status)

    async def submit_protective_stop(self, symbol, quantity, stop_price, take_profit_price=None):
        if self._reprotect_raises is not None:
            raise self._reprotect_raises
        self.protective_orders.append((symbol, quantity, stop_price, take_profit_price))
        return Order(symbol=symbol, side="sell", quantity=quantity,
                     order_id="protect-1", status="pending_signoff")

    async def sign_off(self, order_id, operator):
        self.signed_off.append((order_id, operator))
        status = "transmitted" if order_id.startswith("protect") else "filled"
        return Order(symbol="X", side="sell", quantity=0.0, order_id=order_id, status=status)


class _FakeKillSwitch:
    def __init__(self, reason):
        self.reason = reason
        self.tripped = reason is not None


@pytest.fixture
def closer_factory():
    from qat.domain.oms.position_closer import PositionCloser

    def make(positions=None, entries=None, legs=None, legs_after_cancel=None,
             positions_after_cancel=None, halt=None, cancel_raises=None,
             exit_rejected=False, reprotect_raises=None):
        positions = positions or {}
        entries = {s: _Entry() for s in positions} if entries is None else entries
        broker = _FakeBroker(positions, legs or [], legs_after_cancel or [],
                             positions_after_cancel, cancel_raises)
        oms = _FakeOms(exit_rejected, reprotect_raises)
        closer = PositionCloser(oms, broker, _FakeKillSwitch(halt), entries)
        closer.oms, closer.broker = oms, broker
        return closer

    return make
```

⚠️ **Check `Position`'s real field names before running** — `grep -n "class Position" -A 8 src/qat/data/broker/adapter.py`. If `avg_price` is named differently there, fix the fixture rather than the source.

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/oms/test_position_closer.py
import pytest

from qat.domain.oms.position_closer import CloseOutcome, PositionCloser


@pytest.mark.asyncio
async def test_refuses_a_symbol_the_broker_does_not_hold(closer_factory):
    closer = closer_factory(positions={})
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "not held" in result.detail


@pytest.mark.asyncio
async def test_refuses_when_there_is_no_entry_record(closer_factory):
    """Without an entry basis the exit records no closed trade and no
    R-multiple. v1 names the script rather than half-recording."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, entries={})
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "flatten_positions.py" in result.detail


@pytest.mark.asyncio
async def test_refuses_a_partial_quantity_in_v1(closer_factory):
    closer = closer_factory(positions={"CBA.AX": 100.0})
    result = await closer.close_position("CBA.AX", operator="tester", quantity=50.0)
    assert result.outcome is CloseOutcome.REFUSED
    assert "full close" in result.detail


@pytest.mark.asyncio
async def test_refuses_while_the_kill_switch_is_tripped(closer_factory):
    closer = closer_factory(positions={"CBA.AX": 100.0}, halt="broker gone")
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "broker gone" in result.detail, "the halt REASON must reach the operator"


@pytest.mark.asyncio
async def test_proceeds_past_the_halt_when_acknowledged(closer_factory):
    closer = closer_factory(positions={"CBA.AX": 100.0}, halt="broker gone")
    result = await closer.close_position(
        "CBA.AX", operator="tester", acknowledge_halt=True
    )
    assert result.outcome is not CloseOutcome.REFUSED or "tripped" not in result.detail
```

- [ ] **Step 2: Run and watch it fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qat.domain.oms.position_closer'`.

- [ ] **Step 3: Write the module with preconditions only**

```python
"""Close one app-managed position in full, from the operator's hand.

⚠️ THE ORDER OF OPERATIONS IS THE WHOLE SAFETY OF THIS. Every position carries
two OCA-linked resting SELL orders for its full quantity. Selling without
cancelling them first leaves them resting against a position no longer held -
they execute and put the account SHORT.

Separate from `oms.py` deliberately: that file carries the reconciliation rail,
the resting-order scan and fill absorption. This choreographs one irreversible
operation with its own recovery branch, which is a different job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

_SCRIPT_HINT = "scripts/flatten_positions.py"


class CloseOutcome(Enum):
    CLOSED = "closed"
    REFUSED = "refused"
    RECOVERED = "recovered"
    UNPROTECTED = "unprotected"


@dataclass(frozen=True, slots=True)
class CloseResult:
    outcome: CloseOutcome
    symbol: str
    quantity: float
    cancelled_legs: tuple[str, ...]
    detail: str


class PositionCloser:
    def __init__(self, oms, broker, kill_switch, entries) -> None:
        self.oms = oms
        self.broker = broker
        self.kill_switch = kill_switch
        self.entries = entries

    def _refuse(self, symbol: str, detail: str) -> CloseResult:
        logger.warning("Manual close of %s REFUSED: %s", symbol, detail)
        return CloseResult(CloseOutcome.REFUSED, symbol, 0.0, (), detail)

    async def _held_quantity(self, symbol: str) -> float:
        """The BROKER's quantity. App records are a claim; this is the fact."""
        for position in await self.broker.positions():
            if position.symbol == symbol:
                return abs(position.quantity)
        return 0.0

    async def close_position(
        self,
        symbol: str,
        *,
        operator: str,
        acknowledge_halt: bool = False,
        quantity: float | None = None,
    ) -> CloseResult:
        if quantity is not None:
            return self._refuse(
                symbol,
                "v1 supports full close only - pass quantity=None. A partial close "
                "would leave the remainder needing a re-placed bracket.",
            )

        held = await self._held_quantity(symbol)
        if held <= 0:
            return self._refuse(symbol, f"{symbol} is not held at the broker")

        if self.entries.get(symbol) is None:
            return self._refuse(
                symbol,
                f"no entry record for {symbol}, so the exit would record no closed "
                f"trade and no R-multiple. Use {_SCRIPT_HINT} instead.",
            )

        if self.kill_switch.tripped and not acknowledge_halt:
            return self._refuse(
                symbol,
                f"the kill switch is tripped ({self.kill_switch.reason}) and the "
                f"halt was not acknowledged",
            )

        return self._refuse(symbol, "not implemented past preconditions")
```

- [ ] **Step 4: Run and watch them pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/position_closer.py tests/domain/oms/test_position_closer.py
git commit -m "PositionCloser: the preconditions, every one of which refuses"
```

---

### Task 3: Cancel the legs, verify, and STOP if any survives

**Files:**
- Modify: `src/qat/domain/oms/position_closer.py`
- Test: `tests/domain/oms/test_position_closer.py`

**Interfaces:**
- Consumes: `CloseResult`, `PositionCloser` from Task 2; `CancelNotResolvedError` from Task 1.
- Produces: private `async def _cancel_legs(self, symbol: str) -> tuple[list, str | None]` returning `(captured_legs, failure_detail)`. `captured_legs` are the `RestingOrder`s as read **before** cancelling, so Task 5 can re-place them.

This is the branch that prevents the short-position trap.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_stops_dead_when_a_leg_survives_the_cancel(closer_factory):
    """⚠️ THE MOST IMPORTANT TEST IN THIS FILE.

    On 19 August a cancel reported PendingCancel while being rejected outright
    (error 10147). If a leg is still resting, selling puts the account short.
    """
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT"), _leg("CBA.AX", "2", "STP")],
        legs_after_cancel=[_leg("CBA.AX", "2", "STP")],   # one survives
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert "still resting" in result.detail
    assert closer.oms.exit_orders == [], "NOTHING may be sold while a leg rests"


@pytest.mark.asyncio
async def test_reads_legs_with_open_orders_not_open_trades(closer_factory):
    """open_orders() uses reqAllOpenOrders. openTrades() is clientId-scoped and
    reported zero legs against sixteen resting on 24 August."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[_leg("CBA.AX", "1", "LMT")])
    await closer.close_position("CBA.AX", operator="tester")
    assert closer.broker.open_orders_calls >= 2, "read once to capture, again to verify"


@pytest.mark.asyncio
async def test_a_cancel_that_cannot_be_resolved_refuses(closer_factory):
    from qat.data.broker.ib_adapter import CancelNotResolvedError

    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT")],
        cancel_raises=CancelNotResolvedError("no live order"),
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.REFUSED
    assert closer.oms.exit_orders == []
```

- [ ] **Step 2: Run and watch them fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -k cancel -v`
Expected: FAIL — the closer still returns "not implemented past preconditions".

- [ ] **Step 3: Implement the cancel-and-verify**

```python
    _WORKING = frozenset({"Submitted", "PreSubmitted", "PendingSubmit", "ApiPending", "ApiUpdate"})

    async def _legs_for(self, symbol: str) -> list:
        orders = await self.broker.open_orders()
        return [o for o in orders if o.symbol == symbol and o.status in self._WORKING]

    async def _cancel_legs(self, symbol: str) -> tuple[list, str | None]:
        """Cancel every working leg, then RE-READ to prove they are gone.

        ⚠️ The cancel's own response is not evidence. On 19 August one reported
        PendingCancel while being rejected outright.
        """
        captured = await self._legs_for(symbol)
        for leg in captured:
            try:
                await self.broker.cancel_order(leg.order_id)
            except Exception as exc:  # noqa: BLE001 - report it, never proceed
                return captured, f"cancel of leg {leg.order_id} failed: {exc}"

        survivors = await self._legs_for(symbol)
        if survivors:
            ids = ", ".join(o.order_id for o in survivors)
            return captured, (
                f"{len(survivors)} leg(s) still resting after the cancel ({ids}). "
                f"NOTHING was sold - selling now would leave them resting against a "
                f"position no longer held and put the account short."
            )
        return captured, None
```

And in `close_position`, replacing the placeholder return:

```python
        captured, failure = await self._cancel_legs(symbol)
        if failure is not None:
            return self._refuse(symbol, failure)
        cancelled = tuple(leg.order_id for leg in captured)
        return CloseResult(
            CloseOutcome.REFUSED, symbol, 0.0, cancelled, "sell not implemented yet"
        )
```

- [ ] **Step 4: Run and watch them pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/position_closer.py tests/domain/oms/test_position_closer.py
git commit -m "PositionCloser: cancel the legs, verify, and stop dead if one survives"
```

---

### Task 4: Sell through the OMS and confirm flat

**Files:**
- Modify: `src/qat/domain/oms/position_closer.py`
- Test: `tests/domain/oms/test_position_closer.py`

**Interfaces:**
- Consumes: `_cancel_legs` from Task 3.
- Produces: `CloseOutcome.CLOSED` results. Calls `oms.submit_exit_order(symbol, quantity, price, reason="manual_close")` then `oms.sign_off(order.order_id, operator)`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_sells_the_reread_broker_quantity_not_the_stale_one(closer_factory):
    """A leg may fill during the cancel. The broker is the authority."""
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT")],
        positions_after_cancel={"CBA.AX": 60.0},
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.CLOSED
    assert result.quantity == 60.0


@pytest.mark.asyncio
async def test_the_sell_goes_through_the_oms_and_is_signed_off_as_the_operator(
    closer_factory,
):
    """Placing on the adapter directly would fill at the broker while the
    ledger never saw it - the position would vanish with no closed trade."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[_leg("CBA.AX", "1", "LMT")])
    await closer.close_position("CBA.AX", operator="darren")
    assert closer.oms.exit_orders == [("CBA.AX", 100.0, "manual_close")]
    assert closer.oms.signed_off == [("order-1", "darren")]


@pytest.mark.asyncio
async def test_sends_exactly_one_order_and_never_retries(closer_factory):
    """M139 re-transmitted a working order every 60s into 4x the position."""
    closer = closer_factory(positions={"CBA.AX": 100.0}, legs=[_leg("CBA.AX", "1", "LMT")])
    await closer.close_position("CBA.AX", operator="tester")
    assert len(closer.oms.exit_orders) == 1
```

- [ ] **Step 2: Run and watch them fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -k sell -v`
Expected: FAIL — "sell not implemented yet".

- [ ] **Step 3: Implement the sell**

```python
        quantity = await self._held_quantity(symbol)
        if quantity <= 0:
            # A leg filled the whole position during the cancel. Nothing to sell,
            # and that is a success rather than an error.
            return CloseResult(
                CloseOutcome.CLOSED, symbol, 0.0, cancelled,
                "the position was already flat after the legs were cancelled",
            )

        entry = self.entries.get(symbol)
        order = await self.oms.submit_exit_order(
            symbol, quantity, entry.price, reason="manual_close"
        )
        if order.status == "rejected":
            return await self._recover(symbol, captured, cancelled, "the exit order was rejected")

        # ⚠️ Signed off as the OPERATOR, bypassing the AutonomyGate. The gate
        # decides whether the SYSTEM may act unattended; a human has already
        # approved this specific order in the dialog. It must never queue in the
        # blotter for a second sign-off.
        signed = await self.oms.sign_off(order.order_id, operator)
        if signed.status != "filled":
            return await self._recover(
                symbol, captured, cancelled, f"the exit order ended {signed.status}"
            )

        logger.warning(
            "MANUAL CLOSE: %s %g sold by %s, %d protective leg(s) cancelled first",
            symbol, quantity, operator, len(cancelled),
        )
        return CloseResult(
            CloseOutcome.CLOSED, symbol, quantity, cancelled,
            f"closed {quantity:g} {symbol} at market; {len(cancelled)} leg(s) cancelled",
        )
```

Add a temporary `_recover` so this task runs green on its own; Task 5 replaces its body:

```python
    async def _recover(self, symbol, captured, cancelled, why: str) -> CloseResult:
        return CloseResult(CloseOutcome.UNPROTECTED, symbol, 0.0, cancelled, why)
```

- [ ] **Step 4: Run and watch them pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/position_closer.py tests/domain/oms/test_position_closer.py
git commit -m "PositionCloser: sell through the OMS, signed off as the operator"
```

---

### Task 5: Recover — re-place the bracket, or shout

**Files:**
- Modify: `src/qat/domain/oms/position_closer.py`
- Test: `tests/domain/oms/test_position_closer.py`

**Interfaces:**
- Consumes: `_recover` stub from Task 4.
- Produces: `CloseOutcome.RECOVERED` and `CloseOutcome.UNPROTECTED`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_a_rejected_sell_re_places_the_bracket(closer_factory):
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        exit_rejected=True,
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.RECOVERED
    assert closer.oms.protective_orders == [("CBA.AX", 100.0, 90.0, 110.0)]


@pytest.mark.asyncio
async def test_a_failed_re_place_reports_unprotected(closer_factory, caplog):
    closer = closer_factory(
        positions={"CBA.AX": 100.0},
        legs=[_leg("CBA.AX", "1", "LMT", limit=110.0), _leg("CBA.AX", "2", "STP", stop=90.0)],
        exit_rejected=True,
        reprotect_raises=RuntimeError("broker said no"),
    )
    result = await closer.close_position("CBA.AX", operator="tester")
    assert result.outcome is CloseOutcome.UNPROTECTED
    assert any(r.levelname == "CRITICAL" for r in caplog.records)
```

- [ ] **Step 2: Run and watch them fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -k "re_place or unprotected" -v`
Expected: FAIL — the stub always returns `UNPROTECTED`.

- [ ] **Step 3: Implement recovery**

```python
    async def _recover(self, symbol, captured, cancelled, why: str) -> CloseResult:
        """Put the protection back. The position is BARE until this succeeds."""
        stop = next((leg.stop_price for leg in captured if leg.stop_price), None)
        target = next((leg.limit_price for leg in captured if leg.limit_price), None)
        quantity = await self._held_quantity(symbol)
        try:
            if stop is None:
                # `submit_protective_stop` requires a float stop. Without one
                # captured there is nothing to restore, and pretending otherwise
                # would report RECOVERED over a bare position.
                raise ValueError("no stop price was captured from the original legs")
            # ⚠️ SIGN IT OFF. `submit_protective_stop` only ever creates a
            # pending_signoff order - "nothing reaches the broker without
            # sign-off". Without this the bracket is proposed and never placed,
            # and the position stays bare while the result claims RECOVERED.
            protective = await self.oms.submit_protective_stop(
                symbol, quantity, stop, take_profit_price=target
            )
            if protective.status == "rejected":
                raise RuntimeError(f"protective stop rejected for {symbol}")
            placed = await self.oms.sign_off(protective.order_id, operator="auto-reprotect")
            if placed.status not in ("transmitted", "filled"):
                raise RuntimeError(f"protective stop ended {placed.status}")
        except Exception:  # noqa: BLE001 - the loudest branch in the file
            logger.critical(
                "MANUAL CLOSE LEFT %s UNPROTECTED: %s, and re-placing the bracket "
                "FAILED. %g shares are held with no resting stop. Re-place by hand.",
                symbol, why, quantity,
            )
            return CloseResult(
                CloseOutcome.UNPROTECTED, symbol, 0.0, cancelled,
                f"{why}, AND the bracket could not be re-placed. {symbol} is held "
                f"with NO STOP. Re-place it by hand now.",
            )
        logger.error(
            "Manual close of %s failed (%s) - original bracket re-placed at "
            "stop=%s target=%s", symbol, why, stop, target,
        )
        return CloseResult(
            CloseOutcome.RECOVERED, symbol, 0.0, cancelled,
            f"{why}. The original bracket was re-placed (stop {stop}, target "
            f"{target}); the position is protected and still held.",
        )
```

- [ ] **Step 4: Run and watch them pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/position_closer.py tests/domain/oms/test_position_closer.py
git commit -m "PositionCloser: re-place the bracket on failure, or report UNPROTECTED"
```

---

### Task 6: Sabotage the rails and prove the tests bite

**Files:**
- Modify: none permanently. Temporary edits, reverted.
- Test: `tests/domain/oms/test_position_closer.py`

M160 taught this eleven days ago: its tolerance was sabotaged into a blanket skip and **eight of nine tests stayed green** — only the larger-gap test caught it. A suite that passes with the rail removed is not testing the rail.

- [ ] **Step 1: Sabotage the step-4 abort**

In `_cancel_legs`, change `if survivors:` to `if False:`.

- [ ] **Step 2: Run the suite and confirm it goes RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_position_closer.py -v`
Expected: `test_stops_dead_when_a_leg_survives_the_cancel` FAILS.
If it passes, the test is not testing the rail — fix the test before continuing.

- [ ] **Step 3: Revert the sabotage and verify the revert**

```bash
git checkout -- src/qat/domain/oms/position_closer.py
grep -n "if survivors:" src/qat/domain/oms/position_closer.py
```

⚠️ **Grep afterwards.** `git checkout --` on an uncommitted file discards the real edit along with the sabotage; on a committed one it restores. Confirm the line is back.

- [ ] **Step 4: Repeat for the halt gate**

Change `if self.kill_switch.tripped and not acknowledge_halt:` to `if False:`.
Run the suite. Expected: `test_refuses_while_the_kill_switch_is_tripped` FAILS.
Revert and grep.

- [ ] **Step 5: Repeat for the quantity refusal**

Change `if quantity is not None:` to `if False:`.
Run the suite. Expected: `test_refuses_a_partial_quantity_in_v1` FAILS.
Revert and grep.

- [ ] **Step 6: Commit the record**

```bash
git commit --allow-empty -m "Sabotage check: three rails seen to bite"
```

---

### Task 7: The dashboard button

**Files:**
- Modify: `src/qat/presentation/dashboard.py` (near the positions table, ~282-290)
- Test: `tests/presentation/test_close_position_button.py`

**Interfaces:**
- Consumes: `PositionCloser.close_position` from Tasks 2-5.
- Produces: `DashboardScreen.close_position_button`, `DashboardScreen._on_close_clicked`, `DashboardScreen._confirm_close(symbol, quantity, legs, halt_reason) -> bool`.

`_confirm_close` is a separate method **specifically so tests can monkeypatch it** — the blotter's pattern, and the reason its docstring gives.

- [ ] **Step 0: Write the `dashboard` fixture**

```python
# tests/presentation/test_close_position_button.py (top of file)
import pytest

from qat.presentation.dashboard import DashboardScreen


def _cell(text):
    from PySide6.QtWidgets import QTableWidgetItem

    return QTableWidgetItem(text)


class _FakeCloser:
    def __init__(self):
        self.calls = []

    def legs_for(self, symbol):
        return ()

    async def close_position(self, symbol, *, operator, acknowledge_halt=False, quantity=None):
        self.calls.append((symbol, operator))


class _FakeKillSwitch:
    def __init__(self):
        self.tripped = False
        self.reason = None

    def trip(self, reason):
        self.tripped, self.reason = True, reason


@pytest.fixture
def dashboard(qtbot, fake_runtime):
    """`qtbot` and `fake_runtime` come from tests/presentation/conftest.py.

    ⚠️ Read that conftest before writing this - it already builds a runtime for
    the other dashboard tests, and a second, different one here is how two
    fixtures drift apart.
    """
    fake_runtime.closer = _FakeCloser()
    fake_runtime.kill_switch = _FakeKillSwitch()
    screen = DashboardScreen(fake_runtime)
    qtbot.addWidget(screen)
    screen.positions_table.setRowCount(1)
    screen.positions_table.setItem(0, 0, _cell("CBA.AX"))
    screen.positions_table.setItem(0, 1, _cell("100"))
    return screen
```

⚠️ **`fake_runtime` may not exist under that name.** Check `tests/presentation/conftest.py` first and use whatever it already provides; do not add a competing runtime fixture.

- [ ] **Step 1: Write the failing tests**

```python
# tests/presentation/test_close_position_button.py
def test_button_is_disabled_until_one_row_is_selected(dashboard):
    assert not dashboard.close_position_button.isEnabled()
    dashboard.positions_table.selectRow(0)
    assert dashboard.close_position_button.isEnabled()


def test_declining_the_dialog_sends_nothing(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: False)
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    assert dashboard.runtime.closer.calls == []


def test_confirming_calls_the_closer_with_the_operator(dashboard, monkeypatch):
    monkeypatch.setattr(dashboard, "_confirm_close", lambda *a, **k: True)
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    assert dashboard.runtime.closer.calls == [("CBA.AX", "operator")]


def test_the_dialog_is_told_the_halt_reason_verbatim(dashboard, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        dashboard, "_confirm_close",
        lambda symbol, qty, legs, halt_reason: seen.update(halt_reason=halt_reason) or False,
    )
    dashboard.runtime.kill_switch.trip("IBKR connection lost")
    dashboard.positions_table.selectRow(0)
    dashboard._on_close_clicked()
    assert seen["halt_reason"] == "IBKR connection lost"
```

- [ ] **Step 2: Run and watch them fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/presentation/test_close_position_button.py -v`
Expected: FAIL — `AttributeError: 'DashboardScreen' object has no attribute 'close_position_button'`.

- [ ] **Step 3: Add the button and handler**

```python
        self.close_position_button = QPushButton("Close Position")
        self.close_position_button.setEnabled(False)
        self.close_position_button.setToolTip(
            "Cancel this position's protective legs and sell the whole holding at "
            "market. The legs are cancelled FIRST and verified gone; if the sell "
            "fails the bracket is put back."
        )
        self.close_position_button.clicked.connect(self._on_close_clicked)
        self.positions_table.itemSelectionChanged.connect(
            lambda: self.close_position_button.setEnabled(
                len(self.positions_table.selectionModel().selectedRows()) == 1
            )
        )
```

```python
    def _on_close_clicked(self) -> None:
        rows = self.positions_table.selectionModel().selectedRows()
        if len(rows) != 1:
            return
        symbol = self.positions_table.item(rows[0].row(), 0).text()
        quantity = self.positions_table.item(rows[0].row(), 1).text()
        legs = self.runtime.closer.legs_for(symbol)
        halt_reason = (
            self.runtime.kill_switch.reason if self.runtime.kill_switch.tripped else None
        )
        if not self._confirm_close(symbol, quantity, legs, halt_reason):
            return
        asyncio.create_task(self._run_close(symbol, acknowledge_halt=halt_reason is not None))

    async def _run_close(self, symbol: str, *, acknowledge_halt: bool) -> None:
        """Await the closer and put its own words on screen.

        `CloseResult.detail` is always populated and is written for the
        operator, so it is rendered verbatim rather than re-summarised here -
        two descriptions of one outcome drift, and the operator would be
        reading an explanation of a decision taken on different words.
        """
        result = await self.runtime.closer.close_position(
            symbol, operator="operator", acknowledge_halt=acknowledge_halt
        )
        if result.outcome is CloseOutcome.UNPROTECTED:
            self._show_error(result.detail)   # blocking; the position has no stop
        else:
            self._show_result(result.detail)
```

⚠️ **`operator="operator"` is a placeholder for a real identity.** The risk console already passes an operator name to `kill_switch.trigger_manual(operator)` — use the same source rather than inventing a second one. Check how it obtains it before writing this line.

- [ ] **Step 4: Run and watch them pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/presentation/test_close_position_button.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the four checks SEPARATELY and then the full suite**

```
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m black --check src scripts tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m bandit -q -r src -c pyproject.toml
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: each clean; suite **at least 3,010 passed, 26 skipped** (2,993 baseline + 17 new).

- [ ] **Step 6: Commit**

```bash
git add src/qat/presentation/dashboard.py tests/presentation/test_close_position_button.py
git commit -m "Dashboard: Close Position button, with the dialog gating the call"
```

---

## Not in this plan

Partial closes, limit orders, manual buys, and converging `flatten_positions.py` / `unwind_in_tranches.py` onto this service. All recorded in the spec's out-of-scope section.

## ⚠️ Run this outside market hours

This touches the order path. The ASX session is 10:00-16:00 AEST and order flow is currently unhalted with the book at ten. Implement and test with the market shut.
