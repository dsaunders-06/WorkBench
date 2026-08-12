# M88 — The absorb watermark skips the pass it was taken during

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A broker fill that executes while an absorb pass is running must be absorbed by the next pass instead of falling permanently below the watermark.

**Architecture:** `absorb_broker_fills` takes its new watermark from `datetime.now(UTC)` *after* the pass completes. Take it *before* the query instead, and assign that. Re-reading is already free by design — `_absorbed_fills` dedupes and the delta arithmetic skips anything unchanged — so the cost of the fix is one extra comparison per already-absorbed fill, and the benefit is that the window closes.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio.

## Global Constraints

- **The validation freeze applies, and this qualifies under it.** The standing rule's fix-immediately list includes *"`trades.csv`, `decision_journal.csv` or `risk_decisions.csv` not being written"*. A protective fill that is never absorbed is a closed trade that is never recorded. **No strategy parameter, cap, threshold or sizing rule changes — which trades happen and how large they are is untouched.**
- **Formats with `black`, not `ruff format`.** Run the four through the venv python.
- **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store persists there. The existing helpers in `tests/safety/test_broker_side_fills.py` already handle this; follow them rather than inventing a new fixture.
- **Do not stamp a test fill with a bare `datetime.now(UTC)` and expect it to be later than something taken microseconds earlier.** This machine's clock granularity measures ~1ms, with 20,000 `now()` calls producing 10 distinct values. That is exactly the flake fixed in `7337a27`, and reintroducing it here would make this test fail for the tick reason rather than the reason it exists for. **Use an explicit offset.**
- The venv python is `.\.venv\Scripts\python.exe`.

## The defect, measured

`absorb_broker_fills` queries from `_fill_query_floor()` at `oms.py:1283`, then sets `self._last_fill_scan = datetime.now(UTC)` at `oms.py:1387` — after the loop, after the ledger writes, and after `_resync_tracked_quantities()` on the `record_only` branch, which is a second broker round trip.

A fill executing between those two moments is in neither answer: not in the query that already returned, and below the watermark the next query starts from.

Probed against `MockBroker`:

```
next pass absorbed    : NOTHING
floor it queried from : 2026-08-12T08:46:28.832744+00:00
=> the fill is BELOW the watermark and is never re-read. Permanently missed.
```

**Not always permanent.** `_fill_query_floor` reaches back past `_absorbed_fills` and `_own_partial_fill_stamps`, so an app with an outstanding partial drags the floor behind the missed fill and re-reads it by luck. With nothing outstanding — the normal case — floor equals watermark and it is gone.

**Why no test catches it.** Against `MockBroker` the pass duration measures 0.000 ms, so the window is empty unless a test deliberately opens one. Against Alpaca it is a network round trip plus processing, every sweep.

**The comment that argues for the current code is right about a different thing.** `oms.py:1385` says the advance happens after the pass *"so a crash mid-loop replays rather than skips"*. That reasoning is sound for crashes and is preserved exactly by this fix — an earlier watermark replays strictly more. It is stamping the watermark at the *end* that skips whatever happened during.

## File Structure

- **Modify `src/qat/domain/oms/oms.py`** — `absorb_broker_fills` only. Two lines: capture before the query, assign after the pass.
- **Modify `tests/safety/test_broker_side_fills.py`** — the M34/M50 absorb file, which already has the `_opened_position` helper and imports `replace`, `timedelta` and `BrokerFill`. Two tests are added here; no new file.

---

### Task 1: Pin the window closed

**Files:**
- Modify: `tests/safety/test_broker_side_fills.py` (append the fake and the test)
- Modify: `src/qat/domain/oms/oms.py:1279-1290` and `oms.py:1383-1390`

**Interfaces:**
- Consumes: `_opened_position(bus, ledger=None) -> tuple[MockBroker, OMS]`, already in the test file; `MockBroker.fill_resting_stop(symbol, price)`; `BrokerFill` (frozen dataclass, so `dataclasses.replace` applies).
- Produces: no new public names. `absorb_broker_fills` keeps its signature and return type.

- [ ] **Step 1: Write the failing test**

Append to `tests/safety/test_broker_side_fills.py`:

```python
class _FillsDuringTheQuery(MockBroker):
    """A protective order that executes WHILE the absorb pass is running.

    Real brokers do this constantly - the query is a network round trip and
    the market does not pause for it. The fake fires the stop as a side effect
    of answering, which places the execution after the query was taken and
    before the watermark advances: exactly the window M88 closes.
    """

    def __init__(self) -> None:
        super().__init__(seed=1)
        self.fired = False

    async def recent_fills(self, since, symbols=None):
        answer = await super().recent_fills(since, symbols)
        if not self.fired:
            self.fired = True
            self.fill_resting_stop("AAA", price=95.0)
            # Stamped a millisecond INTO the pass, by an explicit offset rather
            # than by now(). The clock here has ~1ms granularity, so a bare
            # now() inside this call can equal the timestamp taken microseconds
            # earlier at the top of the pass - which is the flake fixed in
            # 7337a27, and it would fail this test for the wrong reason.
            late = self._broker_fills[-1]
            self._broker_fills[-1] = replace(
                late, filled_at=late.filled_at + timedelta(milliseconds=1)
            )
        return answer


@pytest.mark.asyncio
async def test_a_fill_landing_during_the_pass_is_not_lost():
    """M88. The watermark used to be stamped after the pass, so an execution
    that happened during it fell below the next query's floor and was never
    read again - a protective order firing, and no closed trade for it."""
    bus = EventBus()
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    broker = _FillsDuringTheQuery()
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    await oms.sign_off(order.order_id, "operator")
    await oms.adopt_broker_positions()

    first = await oms.absorb_broker_fills()
    assert broker.fired, "the fake must have fired the stop during the first pass"
    assert [f.side for f in first] == [], "the stop fired AFTER this query was answered"

    second = await oms.absorb_broker_fills()

    assert [f.symbol for f in second] == ["AAA"]
    assert second[0].side == "sell"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest "tests/safety/test_broker_side_fills.py::test_a_fill_landing_during_the_pass_is_not_lost" -v
```

Expected: FAIL with `assert [] == ['AAA']` — the same assertion shape as the CI failure that started this, and for the same underlying reason.

- [ ] **Step 3: Capture the watermark before the query**

In `src/qat/domain/oms/oms.py`, inside `absorb_broker_fills`, replace:

```python
        source = getattr(self.broker, "recent_fills", None)
        if source is None:
            return []
        try:
            fills = await source(self._fill_query_floor(), self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read recent broker fills")
            return []
```

with:

```python
        source = getattr(self.broker, "recent_fills", None)
        if source is None:
            return []
        # Taken BEFORE the query, and it is the value the watermark becomes
        # (M88). A stamp taken after the pass excludes everything that executed
        # during it: the query has already been answered, and the next floor
        # starts above the execution. Protective fills are the only exits this
        # system has, so one lost that way is a closed trade that never exists.
        scan_started = datetime.now(UTC)
        try:
            fills = await source(self._fill_query_floor(), self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read recent broker fills")
            return []
```

- [ ] **Step 4: Assign it after the pass**

In the same function, replace:

```python
        # Advanced and persisted only after the pass, so a crash mid-loop
        # replays rather than skips - and `_absorbed_fills` is what makes a
        # replay safe to repeat.
        self._last_fill_scan = datetime.now(UTC)
```

with:

```python
        # Advanced and persisted only after the pass, so a crash mid-loop
        # replays rather than skips - and `_absorbed_fills` is what makes a
        # replay safe to repeat. The VALUE is the instant the pass began rather
        # than the instant it ended (M88): an end stamp replays nothing and
        # skips whatever executed while the pass ran. A begin stamp replays
        # strictly more, which is the same property the crash argument relies
        # on, so this strengthens that reasoning rather than weakening it.
        self._last_fill_scan = scan_started
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest "tests/safety/test_broker_side_fills.py::test_a_fill_landing_during_the_pass_is_not_lost" -v
```

Expected: PASS.

- [ ] **Step 6: Run the whole safety suite — this is the fill path**

```bash
.venv/Scripts/python.exe -m pytest tests/safety -q
```

Expected: all pass. If `test_replayed_buy_opens_a_lot.py` or `test_entry_price_reconciliation.py` fails, **stop and report** rather than adjusting them: they encode M50 and M70 behaviour, and a failure there means the earlier watermark changed something this plan did not anticipate.

- [ ] **Step 7: Commit**

```bash
git add src/qat/domain/oms/oms.py tests/safety/test_broker_side_fills.py
```

```bash
git commit -m "M88: take the absorb watermark before the pass, not after"
```

---

### Task 2: Prove the earlier watermark cannot double-absorb

**Files:**
- Modify: `tests/safety/test_broker_side_fills.py` (append one test)

**Interfaces:**
- Consumes: `_opened_position(bus, ledger=None)`; `MockBroker.fill_resting_stop`.
- Produces: nothing.

**Why this is its own task.** Task 1 makes every pass re-read fills the previous pass already absorbed. That is safe *by design* — `_absorbed_fills` is what makes replay repeatable — but "safe by design" is the claim this project has been burned by most often, and M46 was literally a fill counted twice tripping the kill-switch. A reviewer should be able to reject this half while accepting Task 1.

- [ ] **Step 1: Write the test**

Append to `tests/safety/test_broker_side_fills.py`:

```python
@pytest.mark.asyncio
async def test_the_earlier_watermark_does_not_absorb_the_same_fill_twice():
    """M88's risk, pinned. Starting the next query from the instant the last
    pass BEGAN means every fill that pass absorbed is read again. M46 was a
    fill counted twice tripping the kill-switch on arithmetic, so 'the dedupe
    handles it' is a claim that has to be shown rather than asserted."""
    bus = EventBus()
    broker, oms = await _opened_position(bus)
    tracked_before = oms._filled_quantities.get("AAA", 0.0)

    broker.fill_resting_stop("AAA", price=95.0)
    first = await oms.absorb_broker_fills()
    assert [f.symbol for f in first] == ["AAA"], "the fill must be absorbed once"
    tracked_after = oms._filled_quantities.get("AAA", 0.0)

    second = await oms.absorb_broker_fills()

    assert second == [], "the same execution must not be absorbed a second time"
    assert oms._filled_quantities.get("AAA", 0.0) == tracked_after
    assert tracked_after < tracked_before, "the stop did reduce the position"
    assert oms.kill_switch.tripped is False
```

- [ ] **Step 2: Run it to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest "tests/safety/test_broker_side_fills.py::test_the_earlier_watermark_does_not_absorb_the_same_fill_twice" -v
```

Expected: PASS. **If it fails, the fix in Task 1 is wrong and must be reverted, not patched** — a double absorption is worse than the window it closes, because it trips the kill-switch and halts a session rather than losing one record.

- [ ] **Step 3: Commit**

```bash
git add tests/safety/test_broker_side_fills.py
```

```bash
git commit -m "Pin M88's risk: an earlier watermark must not absorb twice"
```

---

### Task 3: Record M88 in ROADMAP

**Files:**
- Modify: `ROADMAP.md` (new entry above the ASX section, which is currently the newest)

**Interfaces:** none.

- [ ] **Step 1: Add the entry**

Insert immediately above `## The ASX became the near-term destination, not the eventual one`:

```markdown
## M88 - The absorb watermark skipped the pass it was taken during  **[FIXED 12 August]**

Found while diagnosing a CI failure that turned out to be unrelated - a tick
race in `test_a_genuinely_foreign_fill_is_still_absorbed`, fixed in `7337a27`.
The same reading of the watermark showed a real one underneath it.

`absorb_broker_fills` queried from `_fill_query_floor()` and then set
`_last_fill_scan = datetime.now(UTC)` **after** the pass - after the loop,
after the ledger writes, and after `_resync_tracked_quantities()` on the
`record_only` branch, which is a second broker round trip. **A fill executing
between the query and that stamp was in neither answer**: not in the query that
had already returned, and below the floor the next query started from.

Measured against `MockBroker`: the next pass absorbed **nothing**, and the fill
sat permanently below the watermark.

**Not always permanent, which is worse.** `_fill_query_floor` reaches back past
`_absorbed_fills` and `_own_partial_fill_stamps`, so an app with an outstanding
partial drags the floor behind the missed fill and re-reads it by luck. With
nothing outstanding - the normal case - it is gone.

**Why nothing caught it.** Against `MockBroker` the pass takes 0.000 ms, so the
window is empty unless a test opens one deliberately. Against Alpaca it is a
network round trip plus processing, every sweep. The consequence is the M34
class arriving by a different route: a protective order fires and never becomes
a closed trade, silently, in the evidence the trial exists to collect.

**The fix is to stamp the watermark at the instant the pass BEGAN.** The comment
arguing for the old code - *"advanced and persisted only after the pass, so a
crash mid-loop replays rather than skips"* - is right about crashes and is
strengthened rather than weakened: an earlier watermark replays strictly more.
Re-reading was already free by design, as `_fill_query_floor` says of itself.

**Two tests, because the fix carries its own risk.** One pins the window closed
using a broker that fires its stop as a side effect of answering the query. The
other pins the risk the fix introduces - every pass now re-reads what the last
one absorbed, and M46 was a fill counted twice tripping the kill-switch, so
"the dedupe handles it" had to be shown rather than asserted.

**Bearing on the ASX work:** `recent_fills` is one of the four `BrokerAdapter`
methods `IBAdapter` does not implement, so this is behaviour W1.1 must measure
IBKR against rather than assume.
```

- [ ] **Step 2: Commit**

```bash
git add ROADMAP.md
```

```bash
git commit -m "Record M88 - the window between the query and the watermark"
```

---

## Verification, end to end

- [ ] **Full suite, under CI's conditions**

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q
```

- [ ] **All four quality gates**

```bash
.venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m black --check . ; .venv/Scripts/python.exe -m mypy src ; .venv/Scripts/python.exe -m bandit -r src -q
```

- [ ] **CI is green on the pushed commit**

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" run list --limit 3
```

## Deliberately not in this plan

- **Changing `recent_fills`'s `>` to `>=`** in either `MockBroker` or the Alpaca adapter. The simulator must not answer more fully than the broker — `mock_broker.py` argues this itself — and a boundary-inclusive filter risks re-absorbing a fill sitting exactly on the watermark, which is the failure this plan's Task 2 exists to prevent.
- **Persisting `scan_started` differently.** `_save_fill_state` already writes `_last_fill_scan`; the value changes, the mechanism does not.
- **Anything about `IBAdapter`'s missing `recent_fills`.** That is W1.1, and it needs a live Gateway to measure.
