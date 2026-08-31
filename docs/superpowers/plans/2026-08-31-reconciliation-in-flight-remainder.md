# Reconciliation In-Flight Remainder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the kill switch tripping on a partial fill, by treating a divergence as expected only up to the unfilled remainder the broker itself reports for a working BUY order — and still tripping on anything beyond it.

**Architecture:** `check_reconciliation` asks `open_orders()` for each symbol's working-buy remainder and subtracts it before judging. No contract change: `RestingOrder.quantity` **is** `orderStatus.remaining`, and `check_resting_orders` already fetches it in the same monitor cycle.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-31-reconciliation-in-flight-remainder-design.md` (commit `82bad0f`).

## Global Constraints

- **This is the HALT RAIL.** `check_reconciliation` returns "a halting mismatch was found" and `ReconciliationMonitor` publishes `KillSwitchEvent` on `True`. Getting it wrong in the lax direction blinds the one signal that means "my view of the account cannot be trusted".
- ⚠️ **BUYS ONLY.** Protective sells return early at sign-off and never touch `_filled_quantities` — the `return filled` sits two lines above `signed_qty`. Subtracting sell remainders invents a 13,586-share tolerance on BOQ and turns a clean book red.
- **No `open_orders()`, no tolerance.** A rail that loses its evidence gets stricter, never laxer.
- **Run the four checks SEPARATELY** — `black --check` exits 0 while printing "1 file would be reformatted", so `&&` hides a failure.
- **The FULL suite, not the targeted one.**
- **PowerShell** for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal`.
- **Use the edit tool, which errors on a failed match.**
- ⚠️ **Do NOT reference Alpaca** in reasoning or cost estimates. It has no function in this app; the broker is IBKR, the market ASX.
- Next milestone number: **M160**.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/qat/domain/oms/oms.py` | `check_reconciliation`, the halt rail | Add `_in_flight_buy_remainders()`; subtract it in the `divergent` computation (~line 1993) |
| `tests/domain/oms/test_reconciliation_in_flight.py` | The tolerance, its limits, and both planted traps | Create |

---

### Task 1: The remainder helper

A pure read of the broker's working orders. Reviewable alone: it either reports buys-only correctly or it does not.

**Files:**
- Create: `tests/domain/oms/test_reconciliation_in_flight.py`
- Modify: `src/qat/domain/oms/oms.py` — add `_in_flight_buy_remainders` immediately above `check_reconciliation` (currently line 1965)

**Interfaces:**
- Produces: `OMS._in_flight_buy_remainders() -> dict[str, float]`, used by Task 2.

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/oms/test_reconciliation_in_flight.py`:

```python
"""An order still filling is not a divergence (Defect B).

⚠️ MEASURED LIVE, 31 August 2026. The reconciliation poll landed NINE SECONDS
into a forty-five-second fill:

    10:30:06-10:30:51  JHX.AX buy, 17 executions, cumQty 1,097
    10:30:15           Broker reconciliation mismatch: JHX.AX tracked=1097 broker=378
    10:30:15           KILL-SWITCH TRIPPED

`oms.py:861` books `filled.quantity` - the ORDER'S SIZE, not what executed - so
the app counts the whole order the instant the broker accepts it.

The number that explains the gap was already in hand, in the same scan cycle and
the same second:

    10:30:15  RESTING ORDER ORPHAN: JHX.AX BUY resting=719 justified=0 excess=719

1097 - 378 - 719 == 0.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.resting_orders import RestingOrder
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _resting(symbol: str, side: str, remaining: float, order_type: str = "market") -> RestingOrder:
    """`quantity` IS the unfilled remainder - `from_ib_open_order` builds it from
    `trade.orderStatus.remaining`."""
    return RestingOrder(
        symbol=symbol,
        side=side,
        quantity=remaining,
        total_quantity=remaining,
        order_id=f"{symbol}-{side}",
        order_type=order_type,
        status="Submitted",
        limit_price=None,
        stop_price=None,
        oca_group=None,
        parent_perm_id=None,
        owner_client_id=1,
        why_held=None,
    )


class _Broker(MockBroker):
    """A broker whose positions and open orders are set by the test."""

    def __init__(self, positions=None, open_orders=None, raises: bool = False) -> None:
        super().__init__(seed=1)
        for symbol, qty in (positions or {}).items():
            self._positions[symbol] = Position(symbol=symbol, quantity=qty, avg_price=10.0)
        self._open = list(open_orders or [])
        self._raises = raises

    async def open_orders(self) -> list[RestingOrder]:
        if self._raises:
            raise RuntimeError("broker refused open_orders")
        return self._open


def _oms(broker: _Broker) -> tuple[OMS, KillSwitch]:
    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    engine = RiskEngine(bus, switch, settings=settings)
    return OMS(broker, engine, switch, max_order_pct_of_cash=1.0, bus=bus), switch


@pytest.mark.asyncio
async def test_a_working_buy_reports_its_remainder() -> None:
    oms, _ = _oms(_Broker(open_orders=[_resting("JHX.AX", "buy", 719.0)]))

    assert await oms._in_flight_buy_remainders() == {"JHX.AX": 719.0}


@pytest.mark.asyncio
async def test_resting_protective_sells_report_NOTHING() -> None:
    """⚠️ PLANTED, and this is the trap the whole design exists to avoid.

    The twenty resting protective legs are WORKING SELL orders whose remaining
    is the full position - BOQ's is 13,586. But a protective stop RETURNS EARLY
    at sign-off and never touches `_filled_quantities`: the `return filled` sits
    two lines above `signed_qty`. Subtracting these would invent a 13,586-share
    tolerance on a symbol with no divergence at all.
    """
    oms, _ = _oms(
        _Broker(
            open_orders=[
                _resting("BOQ.AX", "sell", 13586.0, order_type="stop"),
                _resting("BOQ.AX", "sell", 13586.0, order_type="limit"),
            ]
        )
    )

    assert await oms._in_flight_buy_remainders() == {}


@pytest.mark.asyncio
async def test_buys_and_sells_together_report_only_the_buys() -> None:
    oms, _ = _oms(
        _Broker(
            open_orders=[
                _resting("JHX.AX", "buy", 719.0),
                _resting("JHX.AX", "sell", 1097.0, order_type="stop"),
            ]
        )
    )

    assert await oms._in_flight_buy_remainders() == {"JHX.AX": 719.0}


@pytest.mark.asyncio
async def test_a_broker_that_raises_reports_nothing_rather_than_guessing() -> None:
    """No evidence means NO TOLERANCE, which trips. A rail that loses its
    evidence must get stricter, never laxer."""
    oms, _ = _oms(_Broker(raises=True))

    assert await oms._in_flight_buy_remainders() == {}


@pytest.mark.asyncio
async def test_an_adapter_without_open_orders_reports_nothing() -> None:
    class _NoOpenOrders(MockBroker):
        open_orders = None  # type: ignore[assignment]

    bus = EventBus()
    switch = KillSwitch()
    settings = Settings(_env_file=None)
    oms = OMS(
        _NoOpenOrders(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        max_order_pct_of_cash=1.0,
        bus=bus,
    )

    assert await oms._in_flight_buy_remainders() == {}
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_reconciliation_in_flight.py -q
```

Expected: all five FAIL with `AttributeError: 'OMS' object has no attribute '_in_flight_buy_remainders'`.

⚠️ If `RestingOrder(...)` raises a `TypeError` instead, its field list has changed — read `src/qat/domain/oms/resting_orders.py` and fix `_resting`, do not guess.

- [ ] **Step 3: Add the helper**

In `src/qat/domain/oms/oms.py`, immediately above `async def check_reconciliation`:

```python
    async def _in_flight_buy_remainders(self) -> dict[str, float]:
        """How much of each working BUY order the broker has NOT yet filled.

        `sign_off` books `filled.quantity` - the ORDER'S SIZE, not what executed
        - so between acceptance and completion this app's holdings view runs
        ahead of the broker's by exactly this amount. Measured live on
        31 August: the poll landed nine seconds into a forty-five-second fill and
        halted trading on `tracked=1097 broker=378`, while the resting scan in
        the same second already held `JHX.AX BUY resting=719`.

        ⚠️ **BUYS ONLY, and this is load-bearing.** The resting protective legs
        are working SELL orders whose remaining is the full position, but a
        protective stop returns early at sign-off and never touches
        `_filled_quantities` - so subtracting their remainders would invent a
        tolerance of the whole position on a symbol with no divergence at all.
        Buys always inflate tracked; protective sells never do.

        ⚠️ **No evidence means NO tolerance.** An adapter without
        `open_orders()`, or one whose call fails, yields an empty map and the
        rail behaves exactly as it did before. A rail that loses its evidence
        must get stricter, not laxer.
        """
        source = getattr(self.broker, "open_orders", None)
        if source is None:
            return {}
        try:
            orders = await source()
        except Exception:
            logger.exception(
                "Could not read open orders for the reconciliation tolerance - "
                "judging on the raw difference, which is the strict direction"
            )
            return {}

        remainders: dict[str, float] = {}
        for order in orders:
            if order.side != "buy" or order.status not in WORKING_STATUSES:
                continue
            remainders[order.symbol] = remainders.get(order.symbol, 0.0) + float(order.quantity)
        return remainders
```

⚠️ `WORKING_STATUSES` is already imported in `oms.py` for `check_resting_orders`. If it is not, import it from `qat.domain.oms.resting_orders`.

- [ ] **Step 4: Run the tests and confirm all five pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_reconciliation_in_flight.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Run the FULL suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

- [ ] **Step 6: The four checks, SEPARATELY**

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
git add tests/domain/oms/test_reconciliation_in_flight.py src/qat/domain/oms/oms.py
```

```bash
git commit -m "M160: the broker can say how much of an order is still in flight"
```

---

### Task 2: Subtract it in the rail

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — the `divergent` computation in `check_reconciliation` (~line 1993)
- Modify: `tests/domain/oms/test_reconciliation_in_flight.py` — add the rail-level tests

**Interfaces:**
- Consumes: `OMS._in_flight_buy_remainders() -> dict[str, float]` from Task 1.

- [ ] **Step 1: Write the rail-level tests**

Append to `tests/domain/oms/test_reconciliation_in_flight.py`:

```python
def _flat_returns(n: int = 30) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n)
    return pd.Series([0.001] * n, index=dates)


def _candidate(symbol: str = "JHX.AX") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=_flat_returns(),
    )


@pytest.mark.asyncio
async def test_a_partial_fill_is_not_a_mismatch(tmp_path) -> None:
    """⚠️ THE LIVE CASE, with its real numbers. 1097 - 378 - 719 == 0."""
    broker = _Broker(
        positions={"JHX.AX": 378.0},
        open_orders=[_resting("JHX.AX", "buy", 719.0)],
    )
    oms, switch = _oms(broker)
    oms._filled_quantities["JHX.AX"] = 1097.0

    assert await oms.check_reconciliation() is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_the_same_gap_with_nothing_in_flight_still_trips() -> None:
    """⚠️ THE RAIL'S TEETH. Identical numbers, no working order - this MUST
    halt. Without this, the tolerance could be blinding rather than explaining."""
    broker = _Broker(positions={"JHX.AX": 378.0}, open_orders=[])
    oms, switch = _oms(broker)
    oms._filled_quantities["JHX.AX"] = 1097.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_gap_LARGER_than_the_remainder_still_trips() -> None:
    """⚠️ PLANTED. tracked 1097, broker 300, remaining 719 - the gap is 797 and
    the tolerance is 719, so 78 shares are unexplained and it must halt.

    Without this, an implementation that simply SKIPPED any symbol with a
    working order would pass both tests above.
    """
    broker = _Broker(
        positions={"JHX.AX": 300.0},
        open_orders=[_resting("JHX.AX", "buy", 719.0)],
    )
    oms, switch = _oms(broker)
    oms._filled_quantities["JHX.AX"] = 1097.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_clean_book_with_resting_protective_sells_stays_clean() -> None:
    """⚠️ PLANTED, the trap again but at the RAIL. tracked == broker, and the
    symbol carries full-size resting sell legs. An implementation that
    subtracted sell remainders turns this green book RED - inventing a
    13,586-share divergence on a position that agrees perfectly."""
    broker = _Broker(
        positions={"BOQ.AX": 13586.0},
        open_orders=[
            _resting("BOQ.AX", "sell", 13586.0, order_type="stop"),
            _resting("BOQ.AX", "sell", 13586.0, order_type="limit"),
        ],
    )
    oms, switch = _oms(broker)
    oms._filled_quantities["BOQ.AX"] = 13586.0

    assert await oms.check_reconciliation() is False
    assert switch.tripped is False
```

- [ ] **Step 2: Run them and confirm the right ones fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_reconciliation_in_flight.py -q
```

Expected: `test_a_partial_fill_is_not_a_mismatch` FAILS (it trips today — the defect). The other three PASS already: they assert behaviour that must not change, and **that is what makes the one failure meaningful.**

- [ ] **Step 3: Subtract the remainder in the rail**

In `check_reconciliation`, replace the `divergent` computation:

```python
        broker_positions = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
        # Defect B, 31 August. An order still filling is not a divergence: this
        # app books the whole order at sign-off while the broker reports only
        # what has executed, so the two legitimately differ by the unfilled
        # remainder until the order completes. Subtracting it explains that gap
        # WITHOUT blinding the rail - anything beyond the remainder still halts,
        # and with no working buy the tolerance is zero.
        in_flight = await self._in_flight_buy_remainders()
        symbols = set(self._filled_quantities) | set(broker_positions)
        divergent = {
            symbol: (self._filled_quantities.get(symbol, 0.0), broker_positions.get(symbol, 0.0))
            for symbol in symbols
            if abs(
                self._filled_quantities.get(symbol, 0.0)
                - broker_positions.get(symbol, 0.0)
                - in_flight.get(symbol, 0.0)
            )
            > 1e-6
        }
```

⚠️ The reported pair stays `(tracked, broker)` — the raw figures. The log line must keep showing what the two sides actually hold; the tolerance explains the difference, it does not rewrite it.

- [ ] **Step 4: Run the file and confirm all nine pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_reconciliation_in_flight.py -q
```

Expected: 9 passed.

- [ ] **Step 5: Run the FULL suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

⚠️ `tests/domain/oms/test_oms.py::test_reconciliation_mismatch_trips_kill_switch` sets `_filled_quantities["AAA"] = 999.0` against a `MockBroker` with no open orders — the tolerance is zero there, so it must still pass. If it fails, the tolerance is leaking where there is no working buy, and that is the lax direction. Read it before changing it.

- [ ] **Step 6: The four checks, SEPARATELY**

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

- [ ] **Step 7: Prove the teeth are still there**

⚠️ **A rail never seen to trip is not a rail.** Temporarily change the tolerance to skip any symbol with a working buy (`if symbol in in_flight: continue`), run the file, and confirm `test_a_gap_LARGER_than_the_remainder_still_trips` FAILS. Then restore, and confirm `git diff src/qat/domain/oms/oms.py` shows only the intended change.

- [ ] **Step 8: Commit**

```bash
git add src/qat/domain/oms/oms.py tests/domain/oms/test_reconciliation_in_flight.py
```

```bash
git commit -m "M160: an order still filling is not a divergence"
```

---

### Task 3: Record it and bump the milestone

**Files:**
- Modify: `docs/HANDOFF.md` — the Defect B entry
- Modify: `src/qat/version.py` — `MILESTONE` and a narrative entry

- [ ] **Step 1: Close Defect B in `docs/HANDOFF.md`**

Mark it fixed, keeping the measured numbers (`tracked=1097 broker=378`, remainder 719, same second) and both rules that shaped it: **buys only**, because protective sells never touch `_filled_quantities`; and **no evidence means no tolerance**. Record that the executed-quantity contract change was considered and rejected because alone it under-counts at sign-off.

- [ ] **Step 2: Bump the milestone**

```python
MILESTONE = "M160"
```

Add a narrative entry above it in the shape of the M159 block.

- [ ] **Step 3: Confirm it reports M160**

```bash
.venv/Scripts/python.exe -c "from qat.version import MILESTONE; print(MILESTONE)"
```

Expected: `M160`.

- [ ] **Step 4: Full suite and the four checks, separately**

```bash
.venv/Scripts/python.exe -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add docs/HANDOFF.md src/qat/version.py
```

```bash
git commit -m "M160: record Defect B, and the symmetric fix that would have broken the book"
```

## Deploy and the read-back

**Needs the operator.** Dry run `scripts\deploy.ps1`, ask, then `-Apply`.

⚠️ **THE READ-BACK NEEDS AN ENTRY THAT FILLS ACROSS MULTIPLE EXECUTIONS**, which needs the book below ten, which needs an exit. Expect:

1. **No `Broker reconciliation mismatch` during the fill.** That is the whole point.
2. **The kill switch stays clear** through an entry.
3. ⚠️ **If a mismatch still appears mid-fill**, read the numbers: if `tracked - broker` equals a remainder the resting scan reported in the same cycle, the tolerance is not being applied; if it exceeds it, the rail is working and something else is wrong.

⚠️ **AND WATCH THE OPPOSITE FAILURE.** A mismatch that never appears again *at all* — including on a genuine divergence — would mean the tolerance is blinding rather than explaining. The planted tests cover the constructed case; only a session shows the real one.

## What this does NOT prove

- **That the in-session `open_orders()` view is trustworthy.** Defect C showed it can be incomplete — the JHX legs' OCA group was missing from it while a fresh read had it. The `remaining` figure was correct on the day, but both come from the same call, and M159's group-key instrumentation is what will show how far it can be relied on.
- **Anything about partial app-transmitted SELLS.** Still trips, deliberately; that path has never run.
