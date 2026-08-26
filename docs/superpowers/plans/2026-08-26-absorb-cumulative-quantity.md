# Absorb Path: Cumulative Quantity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `absorb_broker_fills` record every share of a multi-execution broker exit, while still producing ONE closed-trade row per order per pass.

**Architecture:** `BrokerFill.quantity` becomes unambiguously *cumulative filled quantity for the order* on both adapters. IBKR's `from_ib_fill` carries `execution.cumQty` instead of `execution.shares`; the absorb pass then collapses the many executions IBKR returns for one order down to the single highest cumulative before the existing M53 delta arithmetic runs. Alpaca is unaffected — it already returns one order object per order carrying a cumulative `filled_qty`, so the collapse is a no-op there.

**Tech Stack:** Python 3.12, `ib_async` 2.1.0, pytest.

## Why this exists — the measured finding

On 26 August LOV.AX's take-profit leg filled **3,217 shares in 183 executions**. The app absorbed **374** and tripped the kill switch on `tracked=2843 broker=0`. Root cause, proven by replaying the real executions through the real translation function:

- `oms.py:1394` — `return fill.quantity > prior.quantity + 1e-9`, whose comment states the contract as *"an order still filling reports the SAME id with a larger `filled_qty`"*. `filled_qty` is **Alpaca's** field and is **cumulative**.
- `ib_translate.py:363` — `quantity=float(execution.shares)`, which is **per-execution**.

So only an execution setting a new running maximum is ever absorbed, and the absorbed total equals **the largest single execution**. Replay output:

```
executions for LOV.AX order 1216552509 : 183
sum of BrokerFill.quantity             : 3,217
largest single BrokerFill.quantity     :   374
absorbed: 10, 15, 26, 323  ->  TOTAL 374,  LOST 2,843
```

Those are the four deltas the live app logged. **Not a hypothesis.**

⚠️ **Why no test caught it:** every fill fixture in the suite fills an order in ONE execution, where per-execution and cumulative are the same number. The two readings are indistinguishable until an order fills in pieces.

## Global Constraints

- **PowerShell, never the Bash tool**, for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` or constructing `Settings()`.
- **Format with `black`, not `ruff format`.** All four clean: `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- ⚠️ **CI is BLOCKED at the GitHub billing wall.** The local suite is the ONLY verification.
- **Never deploy mid-session.** This touches the only exit path the system has.
- ⚠️ **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store persists there.
- Baseline: **2,758 passed, 25 skipped** (2,783 collected).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/data/broker/ib_translate.py` | **Modify.** `from_ib_fill` carries `execution.cumQty`, and says why in the docstring. |
| `src/qat/domain/oms/oms.py` | **Modify.** `absorb_broker_fills` collapses many executions per order to the highest cumulative before the delta arithmetic. |
| `src/qat/data/broker/adapter.py` | **Modify.** `BrokerFill.quantity`'s docstring states the contract that was never written down. |
| `tests/data/broker/test_ib_fill_cumulative.py` | **Create.** The translation contract, on a multi-execution order. |
| `tests/domain/oms/test_absorb_multi_execution.py` | **Create.** The LOV shape end to end: 183 executions in, one ledger row and 3,217 shares out. |

---

## Task 1: State the contract where it was missing

**Files:**
- Modify: `src/qat/data/broker/adapter.py` — `BrokerFill`

**Interfaces:**
- Produces: no code change to behaviour. A docstring that makes the next boundary crossing checkable.

**Why this is Task 1 and not an afterthought.** Both sides of this defect were individually correct. What was absent was any statement of what the number MEANS, so neither author could have been caught by review. Writing it down first means Tasks 2 and 3 are implementing against a stated contract.

- [ ] **Step 1: Add the contract to `BrokerFill`**

Find the `quantity` field on `BrokerFill` in `src/qat/data/broker/adapter.py` and put this immediately above the class's field block (adapt the surrounding wording to the existing docstring style, but keep every fact):

```python
    """...existing description...

    ⚠️ `quantity` is the order's CUMULATIVE filled quantity, not the size of one
    execution. Every consumer subtracts what it has already absorbed from it,
    so a per-execution figure here silently discards fills.

    This is not a stylistic preference. On 26 August 2026 an IBKR take-profit
    filled 3,217 shares in 183 executions; `from_ib_fill` supplied
    `execution.shares` while `OMS._is_foreign_unrecorded` compared it against a
    stored cumulative, so only executions setting a new running maximum were
    absorbed. 374 shares reached the ledger and 2,843 did not, and the kill
    switch tripped on the difference. Alpaca returns one order object per order
    carrying a cumulative `filled_qty`, which is where the assumption came from
    and why it was invisible after the broker changed.
    """
```

- [ ] **Step 2: Confirm nothing broke**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: `2,758 passed, 25 skipped` — a docstring cannot change behaviour, and confirming that is the point of running it before the behavioural tasks.

- [ ] **Step 3: Commit**

```bash
git add src/qat/data/broker/adapter.py
git commit -m "Absorb fix: state what BrokerFill.quantity means"
```

---

## Task 2: `from_ib_fill` carries the cumulative quantity

**Files:**
- Modify: `src/qat/data/broker/ib_translate.py` — `from_ib_fill`
- Test: `tests/data/broker/test_ib_fill_cumulative.py`

**Interfaces:**
- Consumes: the contract from Task 1.
- Produces: `from_ib_fill(fill, market) -> BrokerFill | None` where `quantity` is `execution.cumQty`.

**Measured:** on the real LOV order, `cumQty` runs `10, 35, 39, … 3,217` monotonically across the 183 executions, so the highest cumulative is the order's full filled size.

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_ib_fill_cumulative.py`:

```python
"""A BrokerFill from IBKR carries the order's CUMULATIVE filled quantity.

IBKR returns one Fill per EXECUTION, each with its own `shares`. Every consumer
of BrokerFill.quantity subtracts what it has already absorbed, so a
per-execution figure discards fills silently.

Measured 26 August 2026: LOV.AX order 1216552509 filled 3,217 shares in 183
executions. With `shares`, only executions setting a new running maximum were
absorbed - 374 reached the ledger and 2,843 did not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from qat.data.broker.ib_translate import from_ib_fill


def _fill(shares: float, cum_qty: float, price: float = 28.45):
    """The shape ib_async returns: Fill(contract=..., execution=...)."""
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="LOV"),
        execution=SimpleNamespace(
            execId="x",
            permId=1216552509,
            side="SLD",
            shares=shares,
            cumQty=cum_qty,
            price=price,
            time=datetime(2026, 8, 26, 0, 6, 31, tzinfo=UTC),
        ),
    )


def test_quantity_is_the_cumulative_not_the_execution():
    """The execution moved 25 shares; the ORDER has now filled 35."""
    out = from_ib_fill(_fill(shares=25.0, cum_qty=35.0), "ASX")

    assert out is not None
    assert out.quantity == 35.0, (
        f"got {out.quantity} - that is this execution's own size, and every "
        "consumer will treat it as the order's running total"
    )


def test_the_last_execution_carries_the_whole_order():
    """The real LOV order's final execution: 3 shares, cumulative 3,217."""
    out = from_ib_fill(_fill(shares=3.0, cum_qty=3217.0), "ASX")

    assert out is not None
    assert out.quantity == 3217.0


def test_the_symbol_is_still_translated_back():
    """Unchanged behaviour, pinned because this task edits the same return."""
    out = from_ib_fill(_fill(shares=10.0, cum_qty=10.0), "ASX")

    assert out is not None
    assert out.symbol == "LOV.AX"
    assert out.order_id == "1216552509"
    assert out.side == "sell"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_fill_cumulative.py -q`

Expected: the first two FAIL with `got 25.0` and `got 3.0`. The third passes already.

- [ ] **Step 3: Write minimal implementation**

In `src/qat/data/broker/ib_translate.py`, change the `quantity` line of `from_ib_fill` and add the reason to its docstring:

```python
        quantity=float(execution.cumQty),
```

Add to `from_ib_fill`'s docstring, after the existing paragraphs:

```
    **`cumQty`, NOT `shares`.** `BrokerFill.quantity` is the order's cumulative
    filled quantity; `shares` is what THIS execution moved. IBKR returns one
    Fill per execution, so supplying `shares` gave the OMS a per-execution
    number where it subtracts a stored cumulative - and only executions setting
    a new running maximum were ever absorbed. Measured 26 August 2026 on LOV.AX
    order 1216552509: 183 executions, 3,217 shares, of which 374 reached the
    ledger. `cumQty` runs 10, 35, 39 ... 3,217 monotonically across those same
    executions.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/data/broker/ -q`

⚠️ **Expect other fill tests to fail here, and READ them before changing them.** Any fixture that set `shares` and `cumQty` to the same value still passes; one that set only `shares` will now see `cumQty` missing or wrong. A fixture that never distinguished the two is the fixture this defect hid behind — fix the fixture to carry both fields honestly. **If a test asserts a per-execution quantity as a deliberate contract, STOP and report it** rather than editing the assertion.

- [ ] **Step 5: Commit**

```bash
git add src/qat/data/broker/ib_translate.py tests/data/broker/test_ib_fill_cumulative.py
git commit -m "Absorb fix: from_ib_fill carries cumQty, not this execution's shares"
```

---

## Task 3: One order, one ledger row, whatever the execution count

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — `absorb_broker_fills`
- Test: `tests/domain/oms/test_absorb_multi_execution.py`

**Interfaces:**
- Consumes: `from_ib_fill` now supplying cumulative quantities (Task 2).
- Produces: `absorb_broker_fills` unchanged in signature. Internally it collapses the fills it received to at most one per `order_id` — the one with the highest `quantity` — before the existing `_is_foreign_unrecorded` / `_unabsorbed_part` arithmetic runs.

⚠️ **THIS HALF IS NOT OPTIONAL, and shipping Task 2 without it is worse than the bug.** With cumulative quantities and no collapse, 183 executions produce up to 183 deltas and therefore up to 183 rows in `closed_trades.csv` for one exit. The promotion gate counts closed trades toward 20 and 30; one exit would clear the gate by itself. Today's four rows for one exit are already the small version of that problem.

**Alpaca is unaffected.** Its `recent_fills` returns one order object per order, so a collapse keyed on `order_id` finds one entry per key and changes nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/oms/test_absorb_multi_execution.py`:

```python
"""One broker exit is one closed trade, however many executions it took.

LOV.AX filled 3,217 shares in 183 executions on 26 August 2026. Two things must
both hold: every share is absorbed, and the ledger gains ONE row rather than
183. The promotion gate counts closed trades toward 20 and 30, so an exit that
books itself 183 times clears the gate on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.data.broker.adapter import BrokerFill


def _lov_executions() -> list[BrokerFill]:
    """The real shape: many executions, one order, rising cumulative.

    Deliberately includes a LATER execution SMALLER than an earlier one - that
    is the exact condition the old code discarded, and a fixture of uniformly
    rising execution sizes would pass against the defect.
    """
    sizes = [10.0, 25.0, 4.0, 12.0, 51.0, 8.0, 374.0, 3.0, 2730.0]
    start = datetime(2026, 8, 26, 0, 6, 31, tzinfo=UTC)
    running = 0.0
    fills = []
    for i, size in enumerate(sizes):
        running += size
        fills.append(
            BrokerFill(
                order_id="1216552509",
                symbol="LOV.AX",
                side="sell",
                quantity=running,  # CUMULATIVE, per the BrokerFill contract
                price=28.45,
                filled_at=start + timedelta(seconds=i),
            )
        )
    return fills


@pytest.mark.asyncio
async def test_every_share_of_a_multi_execution_exit_is_absorbed(oms_with_lov_position):
    """3,217 filled, 3,217 absorbed. The defect absorbed 374."""
    oms = oms_with_lov_position
    absorbed = await oms.absorb_broker_fills()

    total = sum(f.quantity for f in absorbed)
    assert total == pytest.approx(3217.0), (
        f"absorbed {total} of 3,217 - the shortfall is silently discarded fills"
    )


@pytest.mark.asyncio
async def test_one_exit_produces_one_absorbed_fill(oms_with_lov_position):
    """Not 183. The gate counts rows."""
    oms = oms_with_lov_position
    absorbed = await oms.absorb_broker_fills()

    assert len(absorbed) == 1, (
        f"{len(absorbed)} fills for one order - the ledger will carry one row "
        "each and the promotion gate counts them"
    )
```

⚠️ **The fixture `oms_with_lov_position` does not exist yet.** Build it in this test file, following the pattern used by the existing OMS tests in `tests/domain/oms/` — and **it MUST pass its own `data_dir`** (`conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store persists there, so one declared anomaly leaks a quarantine into every later test). It needs: an OMS holding a 3,217-share LOV.AX position that the app did not transmit, and a broker stub whose `recent_fills` returns `_lov_executions()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/oms/test_absorb_multi_execution.py -q`

Expected: `test_one_exit_produces_one_absorbed_fill` FAILS reporting several fills. Record the number — it is the evidence the collapse is what fixes it.

- [ ] **Step 3: Write minimal implementation**

In `absorb_broker_fills`, immediately after the `fills = await source(...)` call succeeds and BEFORE the `for raw in fills:` loop, insert:

```python
        # IBKR returns one Fill per EXECUTION; Alpaca returns one order object
        # per order. Both now carry the order's CUMULATIVE quantity, so the
        # highest one per order is the whole story and the rest are earlier
        # snapshots of the same order.
        #
        # Collapsing here rather than in the adapter is deliberate: the delta
        # arithmetic below is per ORDER, and feeding it 183 snapshots of one
        # order emits 183 fill events - which the trade ledger turns into 183
        # closed trades for a single exit. The promotion gate counts closed
        # trades toward 20 and 30, so that is not a cosmetic problem.
        #
        # Alpaca is unaffected: one entry per order id means the max is that
        # entry.
        highest: dict[str, BrokerFill] = {}
        for raw in fills:
            seen = highest.get(raw.order_id)
            if seen is None or raw.quantity > seen.quantity:
                highest[raw.order_id] = raw
        fills = sorted(highest.values(), key=lambda f: f.filled_at)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/oms/ tests/data/broker/ -q`

Then the whole suite: `.venv\Scripts\python.exe -m pytest -q`

⚠️ **If an existing absorb test fails, read it before touching it.** M53's partial-fill tests (the CVS 47-share case) are the ones most likely to be sensitive, and they are testing real behaviour that must survive.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/oms.py tests/domain/oms/test_absorb_multi_execution.py
git commit -m "Absorb fix: one order is one fill event, whatever its execution count"
```

---

## Task 4: Verify, deploy after the close, watch a session

**Files:** none — this task is the gate.

- [ ] **Step 1: Run the suite and the four checks**

Run: `.venv\Scripts\python.exe -m pytest -q`, then `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.

Expected: all clean, count at or above the 2,758 baseline plus the new tests. **This is the whole of the verification — CI is walled.**

- [ ] **Step 2: Replay the real executions against the FIXED code**

Re-run the read-only proof harness (clientId 99, `readonly=True`, writes nothing) that produced the original evidence. Against the fixed code it must report **absorbed 3,217, lost 0, one fill event**. The same script produced `absorbed 374 / lost 2,843` against the defect, so it is a genuine before-and-after on real data rather than on a fixture.

- [ ] **Step 3: Deploy AFTER THE CLOSE**

⚠️ **Not before 16:00 AEST.** This changes the only exit path the system has, and the book is open. Build from a clean tree, verify the installed exe is SHA256-identical to the signed artefact, update `DEPLOYED` in `scripts/handoff_state.py` in the same minute, and read the build stamp back off its own log.

- [ ] **Step 4: Decide the kill switch and the ledger separately**

The switch is tripped on `LOV.AX tracked=2843 broker=0`. **This fix does not clear that** — it prevents the next occurrence. The existing 2,843 phantom and the missing ledger rows are a separate, deliberate repair. Do not reset the switch as a side effect of deploying.

- [ ] **Step 5: Watch the next exit**

The first multi-execution exit after this deploy is the real test. Confirm: the absorbed total equals the position size, `closed_trades.csv` gains ONE row, and no reconciliation mismatch follows. Record the execution count — if the next exit fills in one execution it has proved nothing, and the watch continues.
