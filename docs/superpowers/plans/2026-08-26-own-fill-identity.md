# Own-Fill Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the app absorbing its own entries as foreign broker-side fills, which doubles the book and halts the session ~300s after every new position.

**Architecture:** The OMS decides "did this process send this fill?" by comparing `fill.order_id` against `_broker_order_ids`, which is populated from what `place_order` returns. IBKR returns `permId = 0` at `placeOrder` — TWS has not acknowledged yet — so the set receives the app's own UUID and never the permId the execution will arrive under. The fix closes that in two places: `place_order` waits, briefly and boundedly, for the permId TWS is about to send; and if it never comes, the app says so loudly instead of silently mis-identifying its own order.

**Tech Stack:** Python 3.12, `ib_async` 2.1.0, pytest.

## Why this exists — measured, 26 August

Two entries at 15:15:24-25, WOW.AX 1098 and SEK.AX 2978. Each transmitted **exactly once** and correctly bracketed. 107 seconds later:

```
BROKER-SIDE FILL absorbed: buy 1098 WOW.AX at 40.04 (order 550634674)
  - a position was OPENED at the broker that this application did not send
Broker reconciliation mismatch: SEK.AX tracked=5956 broker=2978,
                                WOW.AX tracked=2196 broker=1098
```

Exactly 2× on both. `from_ib_trade` documents the cause at the line that causes it:

> permId can be legitimately absent (0) here: `IB.placeOrder` returns a `Trade` before TWS has acknowledged the order… an absent/zero permId leaves `our_order.order_id` exactly as it was (the app's own id)

**It is not a race.** Every `Order signed off and transmitted` line in the entire log history — back to 1 August, both brokers, every session — carries a UUID and never a permId. The bridge has not once succeeded.

**It fired on 25 August too and nothing saw it**: fourteen absorbs of that day's own nine entries at 17:56:43, with **zero** reconciliation mismatches logged, because the poll was wedged — 3 scans that day against 78 on 26 August. Item 34's fix did not cause this; it made a months-old defect visible.

⚠️ **The broker quantity is always correct.** No over-buying. The damage is the app's book, plus a halted session.

## Global Constraints

- **PowerShell, never the Bash tool**, for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` or constructing `Settings()`.
- **Format with `black`, not `ruff format`.** All four clean: `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- ⚠️ **CI is BLOCKED at the GitHub billing wall.** The local suite is the ONLY verification.
- ⚠️ **Every test that builds an OMS must pass its own `data_dir`.**
- **Deploy AFTER the close.** This is the order path.
- Baseline: **2,768 passed, 25 skipped**.

---

## Milestone A — the identity bridge (Tasks 1-4)
## Milestone B — the console button (Task 5), item 57, independent and much smaller

---

## Task 1: A test that reproduces the double-count

**Files:**
- Test: `tests/domain/oms/test_own_fill_identity.py`

**Interfaces:** consumes `OMS.absorb_broker_fills`, `OMS._is_foreign_unrecorded`, `BrokerFill`.

**This task ships no fix.** It pins the defect first, so the fix is measured against a failing test rather than against a story.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/oms/test_own_fill_identity.py`:

```python
"""An order this app sent must never be absorbed as a foreign fill.

Measured 26 August 2026. Two entries transmitted at 15:15:24-25, each exactly
once and correctly bracketed. 107 seconds later the app absorbed both as "a
position was OPENED at the broker that this application did not send" and the
book doubled: WOW.AX tracked=2196 broker=1098, SEK.AX tracked=5956 broker=2978.

The cause is an identity mismatch, not a race. `IB.placeOrder` returns before
TWS acknowledges, so `permId` is 0 and `from_ib_trade` correctly leaves the
app's own UUID on the order. `_broker_order_ids` therefore holds a UUID while
the execution arrives keyed on the permId.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_a_fill_for_an_order_this_app_sent_is_not_foreign(oms_that_sent_an_order):
    """The whole defect, in one assertion.

    The OMS transmitted an order and the broker reported the resulting
    execution under its OWN identifier. That fill is not foreign, however the
    two ids are spelled.
    """
    oms, fill_for_our_order = oms_that_sent_an_order

    assert not oms._is_foreign_unrecorded(fill_for_our_order), (
        "the app absorbed its own order as a foreign broker-side fill - this is "
        "the 26 August double-count, and it doubles the book"
    )


@pytest.mark.asyncio
async def test_absorbing_after_our_own_entry_does_not_double_the_book(
    oms_that_sent_an_order,
):
    """The consequence, asserted where an operator would see it."""
    oms, _ = oms_that_sent_an_order
    before = dict(oms._filled_quantities)

    await oms.absorb_broker_fills()

    assert oms._filled_quantities == before, (
        f"tracked quantities moved on an absorb of our own fill: "
        f"{before} -> {dict(oms._filled_quantities)}"
    )
```

⚠️ **The fixture `oms_that_sent_an_order` does not exist — build it in this file.** It must reproduce the real shape, not a convenient one:
- an OMS with its **own `data_dir`**;
- a broker stub whose `place_order` returns the order **with `order_id` UNCHANGED** (the app's UUID), exactly as IBKR does when `permId` is 0;
- the order put through the real `submit_order`/sign-off path so `_broker_order_ids` is populated the way production populates it;
- a `BrokerFill` carrying a **different** `order_id` — a permId-shaped numeric string — for the same symbol, side and quantity.

Model it on `tests/domain/oms/test_oms.py` and `tests/domain/oms/test_adopted_positions.py`.

- [ ] **Step 2: Run it and CONFIRM IT FAILS**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/oms/test_own_fill_identity.py -q`

Expected: **both FAIL.** Record the exact output — it is the evidence the fix is what repairs it. A test that has never been seen to fail is not evidence.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/domain/oms/test_own_fill_identity.py
git commit -m "Item 56: pin the own-fill double-count with a failing test"
```

⚠️ Committing red deliberately, and only here: this test is the specification for Tasks 2-3, and the suite is green again by Task 2. Note it in the commit body.

---

## Task 2: Wait, briefly, for the permId TWS is about to send

**Files:**
- Modify: `src/qat/data/broker/ib_adapter.py` — `place_order`
- Modify: `src/qat/config.py` — a new setting
- Test: `tests/data/broker/test_ib_permid_wait.py`

**Interfaces:**
- Produces: `Settings.ibkr_permid_wait_seconds: float = 5.0`, and a `place_order` that returns an order carrying the permId whenever TWS supplies one within that window.

**Why this and not something cleverer.** `_adopt_from_broker`'s docstring already records that the permId arrives "moments later". The app does not need a new identity scheme; it needs to not give up on the one it has after zero milliseconds. Waiting inside `place_order` costs nothing at the broker — **the order is already live** — and every downstream consumer (`_broker_order_ids`, the dual registration, `_correct_announced_price`) then works unchanged.

⚠️ **Bounded, and it must degrade to today's behaviour rather than to a hang.** If the permId never arrives, keep the app's own id exactly as now — but say so at WARNING, because that is the state in which the next fill will be mis-identified, and it has been silent since 1 August.

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_ib_permid_wait.py`:

```python
"""place_order must learn the permId TWS sends moments after acknowledgement.

`IB.placeOrder` returns a live Trade before TWS has acknowledged, so permId is
0 at that instant. Returning then leaves the app's own UUID as the order's id,
and the execution later arrives keyed on the permId - which is the 26 August
double-count.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_the_permid_is_picked_up_when_it_arrives_late(adapter_with_late_permid):
    """permId is 0 at placeOrder and set shortly after, as TWS really behaves."""
    adapter, order = adapter_with_late_permid

    result = await adapter.place_order(order)

    assert result.order_id == "550634674", (
        f"order_id is {result.order_id!r} - the app kept its own id and will not "
        "recognise its own fill"
    )


@pytest.mark.asyncio
async def test_a_permid_that_never_arrives_keeps_our_id_and_says_so(
    adapter_whose_permid_never_arrives, caplog
):
    """Degrade to today's behaviour, but LOUDLY.

    Writing 0 as an id would collide every unacknowledged order with every
    other, so keeping our own id is right. Doing it silently is what let this
    run since 1 August.
    """
    import logging

    adapter, order, app_id = adapter_whose_permid_never_arrives

    with caplog.at_level(logging.WARNING):
        result = await adapter.place_order(order)

    assert result.order_id == app_id
    assert "permId" in caplog.text, caplog.text


@pytest.mark.asyncio
async def test_the_wait_is_bounded(adapter_whose_permid_never_arrives):
    """A broker that never answers must not hold the order path open."""
    adapter, order, _ = adapter_whose_permid_never_arrives
    adapter.settings.ibkr_permid_wait_seconds = 0.2

    started = asyncio.get_running_loop().time()
    await adapter.place_order(order)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 2.0, f"place_order took {elapsed:.1f}s - the wait is not bounded"
```

⚠️ **Build the two fixtures in this file.** The late-permId one must set `permId` on the Trade **after** `placeOrder` returns, from a task the event loop can run — a fake that sets it synchronously proves nothing, because the whole defect is that the value is absent at that instant.

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_permid_wait.py -q`

Expected: `test_the_permid_is_picked_up_when_it_arrives_late` FAILS with the app's UUID.

- [ ] **Step 3: Add the setting**

In `src/qat/config.py`, beside `ibkr_call_timeout_seconds`:

```python
    ibkr_permid_wait_seconds: float = Field(default=5.0, ge=0)
```

⚠️ `ge=0`, not `gt=0`: zero must be a legal way to switch the wait off entirely without editing code, and this setting has to appear in the manual — `test_manual_documents_every_setting` will fail otherwise. Document it there in the same commit.

- [ ] **Step 4: Write the implementation**

In `ib_adapter.place_order`, between `trade = self.ib_client.placeOrder(contract, ib_order)` and `result = from_ib_trade(trade, order)`, insert:

```python
        await self._await_perm_id(trade, order.order_id)
```

and add the helper beside `_call`:

```python
    async def _await_perm_id(self, trade: object, app_order_id: str) -> None:
        """Give TWS its moment to acknowledge, so we learn our own order's id.

        `IB.placeOrder` returns a LIVE `Trade` before TWS has acknowledged it,
        so `permId` is 0 at that instant and `from_ib_trade` correctly declines
        to write a junk id. Nothing then ever revisited it: `_broker_order_ids`
        held the app's UUID, the execution arrived keyed on the permId, and
        `_is_foreign_unrecorded` absorbed the app's own entry as foreign. On
        26 August that doubled the book on two symbols and halted the session.

        The order is ALREADY LIVE at the broker when this runs - this waits to
        learn its name, not to send it. `_adopt_from_broker`'s docstring
        records that the permId arrives "moments later", which is what makes a
        short wait the whole fix rather than a new identity scheme.
        """
        deadline = self.settings.ibkr_permid_wait_seconds
        if deadline <= 0:
            return
        loop = asyncio.get_running_loop()
        started = loop.time()
        while loop.time() - started < deadline:
            order_obj = getattr(trade, "order", None)
            status = getattr(trade, "orderStatus", None)
            if getattr(order_obj, "permId", 0) or getattr(status, "permId", 0):
                return
            # Yields to the event loop so ib_async can process the ack.
            await asyncio.sleep(0.05)
        logger.warning(
            "IBKR did not report a permId for order %s within %.1fs, so it keeps the "
            "app's own id. Its fill will arrive under a permId this process does not "
            "recognise and WILL be absorbed as foreign, doubling the book (item 56).",
            app_order_id,
            deadline,
        )
```

⚠️ **Also apply it to the bracket and OCA paths.** `place_order` returns early for `order.is_bracket` and for a stop with a take-profit, into `_place_bracket` and `_place_oca`. Those transmit real entries too — the 26 August orders were brackets — so the wait belongs on the parent order in each. **A fix applied to one of three placement paths is the sibling failure this project keeps finding.**

- [ ] **Step 5: Run both test files, then the suite**

Run: `.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_permid_wait.py -q`

Then: `.venv\Scripts\python.exe -m pytest -q`

Expected: this task's three new tests PASS.

⚠️ **CORRECTED DURING EXECUTION — Task 1's two tests STAY RED after this task, and that is correct.** An earlier version of this step claimed they would go green here. They cannot: Task 1's fixture builds its OMS over `MockBroker`, whose `place_order` never touches `order_id`, so no path from those tests reaches `IBAdapter.place_order` at all. They are closed by **Task 3**'s `register_broker_order_id`, and they are Task 3's acceptance criteria, not this task's.

The two fixes are at different layers and both are needed: this task stops the adapter losing the permId against a real IBKR, and Task 3 makes the OMS able to learn one after transmit. Do not treat the remaining red as a regression, and do not weaken Task 1's fixture to make it green here.

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/ib_adapter.py src/qat/config.py tests/data/broker/test_ib_permid_wait.py docs/
git commit -m "Item 56: wait briefly for the permId, and say so when it never comes"
```

---

## Task 3: Late binding, so a slow acknowledgement is survivable

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — a public way to register a broker id learned after transmit
- Modify: `src/qat/data/broker/ib_adapter.py` — `_adopt_from_broker` tells the OMS what it learned
- Test: append to `tests/domain/oms/test_own_fill_identity.py`

**Why a second layer.** Task 2 removes the cause in the normal case. It cannot remove it in the case where TWS is slower than the wait, and that case is exactly when the system is under stress. `_adopt_from_broker` **already learns the permId** moments later for the adapter's own registry; it simply never tells the OMS. Closing that is small and makes the fix survive a slow broker.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/oms/test_own_fill_identity.py`:

```python
@pytest.mark.asyncio
async def test_a_permid_learned_after_transmit_is_registered(oms_that_sent_an_order):
    """The belt-and-braces path, for when the wait in place_order times out.

    The adapter learns the permId moments later either way - it needs it for
    modify and cancel to resolve. The OMS's own foreign-fill check must learn it
    at the same moment, or a slow acknowledgement still doubles the book.
    """
    oms, fill_for_our_order = oms_that_sent_an_order
    assert oms._is_foreign_unrecorded(fill_for_our_order), "fixture should start unregistered"

    oms.register_broker_order_id(fill_for_our_order.order_id)

    assert not oms._is_foreign_unrecorded(fill_for_our_order)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/domain/oms/test_own_fill_identity.py -q`

Expected: FAIL — `OMS` has no `register_broker_order_id`.

- [ ] **Step 3: Implement**

On `OMS`, beside the other public bookkeeping methods:

```python
    def register_broker_order_id(self, order_id: str) -> None:
        """Record a broker identifier learned AFTER transmit (item 56).

        `place_order` waits briefly for the permId, and a slow acknowledgement
        can outlast that wait. The adapter learns it either way - it needs it
        for modify and cancel to resolve - so this is how that knowledge
        reaches the one check that decides whether a fill is our own.
        """
        if order_id:
            self._broker_order_ids.add(str(order_id))
```

Then call it from `_adopt_from_broker` at the point the permId is resolved. ⚠️ **The adapter must not import the OMS.** Pass a callback in, or have the OMS subscribe — follow whichever direction the existing dependency already runs, and do not invert it for convenience.

- [ ] **Step 4: Run the suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/oms.py src/qat/data/broker/ib_adapter.py tests/domain/oms/test_own_fill_identity.py
git commit -m "Item 56: register a permId learned after transmit"
```

---

## Task 4: Verify, deploy after the close, watch the next entry

**Files:** none — this is the gate.

- [ ] **Step 1: Suite and four checks** — all clean, at or above 2,768.

- [ ] **Step 2: Confirm the log line changes shape**

The proof this worked is that `Order signed off and transmitted` finally carries a **numeric permId** instead of a UUID. Every such line since 1 August carries a UUID; **that is the before-and-after**, and it is visible in the first entry after deploy without waiting for an absorb pass.

- [ ] **Step 3: Deploy after the close**, SHA256-verify, update `DEPLOYED` in the same minute, read the stamp back off the log.

- [ ] **Step 4: Clear the doubled book**

⚠️ The restart does this by itself: adoption re-baselines from the broker. Confirm `tracked` matches `broker` for WOW.AX and SEK.AX before resetting anything.

- [ ] **Step 5: Reset the kill switch DELIBERATELY, and watch the next entry**

Watch, in order: the order id in the transmit line is numeric; the order transmits **once**; no `BROKER-SIDE FILL absorbed` line names it; no mismatch appears at the next poll; `4 unprot x0` holds.

⚠️ **If a `BROKER-SIDE FILL absorbed` line names an order this app just sent, stop and halt.** That is this defect surviving the fix.

---

## Milestone B — Task 5: the console button (item 57)

**Files:**
- Modify: `src/qat/presentation/risk_console.py`
- Test: `tests/presentation/` — alongside the existing risk-console tests

**The defect:** `_refresh_kill_switch_button()` is called from exactly two places — construction (`:133`) and the end of its own click handler (`:631`). The 2-second `QTimer` never calls it. So a switch tripped by reconciliation, the equity rails or the startup restore leaves the label stale, and because the handler reads the TRUE state rather than the label, **clicking a button that says "click to halt trading" resets the switch and resumes order flow with no confirmation.** Observed 26 August; the operator saw the disagreement and declined to click, which is the only reason order flow stayed halted.

- [ ] **Step 1** — Write a failing test: trip the switch by a route OTHER than the button, then assert the button's text reports TRIPPED. It must fail today.
- [ ] **Step 2** — Confirm it fails.
- [ ] **Step 3** — Call `_refresh_kill_switch_button()` from `_on_timer_tick`, so the label is derived rather than remembered. ⚠️ Prefer this to adding another listener: the timer already exists and a derived label cannot go stale, whereas a listener can be missed exactly as the outbound one was.
- [ ] **Step 4** — Confirm it passes; run the full suite. ⚠️ `conftest` refuses every `QMessageBox`/`QInputDialog` (added 25 August after a modal appeared on the operator's screen mid-session) — do not add a dialog to this path.
- [ ] **Step 5** — Commit.

⚠️ **Milestone B is worth shipping even if Milestone A slips.** It is small, it touches no rail, and it removes a control that currently invites the opposite of the operator's intent during an incident.

---

## Self-Review

**Coverage.** Item 56's cause is Task 2; its survivability under a slow broker is Task 3; the regression guard is Task 1; live confirmation is Task 4. Item 57 is Task 5.

**Placeholders.** Three fixtures are specified by shape and modelled on named existing tests rather than written out, because each needs the surrounding conventions of files the implementer will read. Each has explicit ⚠️ notes on what would make it a fixture that proves nothing — a synchronously-set permId, or an OMS without its own `data_dir`.

**Type consistency.** `register_broker_order_id(order_id: str) -> None` is defined in Task 3 and used in Tasks 3 and 4. `Settings.ibkr_permid_wait_seconds` is defined in Task 2 Step 3 and used in Step 4 and in Task 2's bounded-wait test.

**Known gap, stated rather than hidden:** none of this addresses the fact that `_broker_order_ids` does not survive a restart. A fill arriving for an order sent before a restart still reads as foreign — which is CORRECT for a genuine broker-side exit, and wrong for an entry that filled across the boundary. That case is rarer, is not what 26 August was, and is deliberately out of scope.
