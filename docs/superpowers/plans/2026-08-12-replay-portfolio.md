# W2 Step 3 — the portfolio, the governor and the caps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay N symbols through the real `PortfolioGovernor` and its caps, with every rail actually binding, so the harness can begin to answer whether the rails help.

**Architecture:** A clock seam on `SignalToOrderBridge` (the pattern `AutonomyGate` already carries) makes the two wall-clock rails bind on simulated time. Warm-up via the existing `seed()` fills the buffers before day one. The day loop widens from one symbol to the whole universe, and the governor is live throughout.

**Tech Stack:** Python 3.12, pandas, pytest, pytest-asyncio.

## Global Constraints

- **The validation freeze applies.** The clock seam defaults to `datetime.now(UTC)`, so live behaviour is byte-for-byte unchanged. No strategy parameter, cap, threshold or sizing rule changes.
- **No regime engine yet.** That is step 4. The engine gates on the sideways default and logs that it is doing so, which is correct and must not be papered over.
- **Every test that builds an OMS must pass its own `data_dir`.**
- **Do not tune a fixture until a rail binds.** Step 2's lesson: count the stages and find the cause. A rail made to bind by shaping the data is a rail that has not been tested.
- **Formats with `black`, not `ruff format`.** The venv python is `.\.venv\Scripts\python.exe`.

## What step 2 found, which this step must not repeat

Two rails read the wall clock and therefore **go silently inert in a replay**:

| | |
|---|---|
| `signal_bridge.py:1017` | `_trading_days_between(entry.opened_at, datetime.now(UTC))` — the **minimum hold**. A simulated `opened_at` against a real `now` gives an enormous held_days, so it never blocks |
| `signal_bridge.py:1073` | `self._entries_this_week(datetime.now(UTC))` — the **weekly churn cap**. Its window never contains the simulated entries, so it never binds |

Neither errors and neither logs. **Step 3 exists to measure whether the rails help, so a harness that quietly disables two of them would answer that question wrongly and confidently.**

**The stamping side is already correct** — `opened_at=event.ts` at line 818 and `_entry_times.append(event.ts)` at line 825 both use the event timestamp, which in a replay is the simulated bar. Only the two comparisons are wall-clock, so one seam fixes both.

---

### Task 1: The clock seam

**Files:**
- Modify: `src/qat/domain/oms/signal_bridge.py` — constructor, and lines 1017 and 1073
- Test: `tests/domain/oms/test_signal_bridge_clock.py` (create)

**Interfaces:**
- Produces: `SignalToOrderBridge(..., clock: Callable[[], datetime] | None = None)` and `self._now() -> datetime`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/oms/test_signal_bridge_clock.py`:

```python
"""Two rails read a clock, and a replay must be able to supply it (W2 step 3).

The minimum hold and the weekly churn cap compare against `now`. Against the
WALL clock in a replay, a simulated opened_at gives an enormous held_days and a
seven-day window that never contains the simulated entries - so both rails stop
binding, silently, in the harness built to measure whether rails help.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.data.broker.mock_broker import MockBroker
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

SIMULATED = datetime(2016, 3, 15, 15, 0, tzinfo=UTC)


def _bridge(tmp_path, clock=None) -> SignalToOrderBridge:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(MockBroker(seed=1), RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    return SignalToOrderBridge(bus, oms, settings=settings, clock=clock)


def test_the_default_clock_is_the_wall_clock(tmp_path):
    """Live behaviour must be unchanged: no caller passes a clock today."""
    bridge = _bridge(tmp_path)
    before = datetime.now(UTC)

    now = bridge._now()

    assert before <= now <= datetime.now(UTC)


def test_an_injected_clock_is_what_the_rails_read(tmp_path):
    bridge = _bridge(tmp_path, clock=lambda: SIMULATED)
    assert bridge._now() == SIMULATED


def test_the_weekly_churn_window_is_measured_on_the_injected_clock(tmp_path):
    """The rail counts entries in the last seven days. On the wall clock, a
    2016 entry is nine years old and the window is always empty."""
    bridge = _bridge(tmp_path, clock=lambda: SIMULATED)
    bridge._entry_times = [SIMULATED - timedelta(days=1), SIMULATED - timedelta(days=3)]

    assert bridge._entries_this_week(bridge._now()) == 2


def test_entries_outside_the_injected_window_still_fall_out(tmp_path):
    bridge = _bridge(tmp_path, clock=lambda: SIMULATED)
    bridge._entry_times = [SIMULATED - timedelta(days=8)]

    assert bridge._entries_this_week(bridge._now()) == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_signal_bridge_clock.py -v
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'clock'`.

- [ ] **Step 3: Add the seam**

In `SignalToOrderBridge.__init__`, add the parameter after `corporate_actions`:

```python
        clock: Callable[[], datetime] | None = None,
```

and in the body, beside the other assignments:

```python
        # Injectable for the same reason AutonomyGate's is (W2): a rail that
        # compares against the wall clock cannot bind in a replay, and both
        # rails below stop binding SILENTLY - no error, no log. Defaults to the
        # wall clock, so live behaviour is unchanged and no caller needs to
        # know this exists.
        self._clock = clock
```

Add the method, near `_entries_this_week`:

```python
    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else datetime.now(UTC)
```

Ensure `Callable` is imported from `collections.abc` at the top of the file.

- [ ] **Step 4: Use it at both sites**

`signal_bridge.py` line ~1017, in `_blocked_by_minimum_hold`:

```python
        held_days = _trading_days_between(entry.opened_at, self._now())
```

`signal_bridge.py` line ~1073, in `_submit_entry`:

```python
        taken = self._entries_this_week(self._now())
```

- [ ] **Step 5: Run the new tests, then the whole suite**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_signal_bridge_clock.py -v
```

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q
```

Expected: no new failures. This file is the live entry path — **a failure here is a real regression, not a test to adjust.**

- [ ] **Step 6: Gates and commit**

```bash
.venv/Scripts/python.exe -m black src/qat/domain/oms/signal_bridge.py tests/domain/oms/test_signal_bridge_clock.py ; .venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m mypy src
```

```bash
git add src/qat/domain/oms/signal_bridge.py tests/domain/oms/test_signal_bridge_clock.py
```

```bash
git commit -m "W2: let the churn and minimum-hold rails read an injected clock"
```

---

### Task 2: Warm-up, so day one is not blind

**Files:**
- Modify: `src/qat/domain/backtester/replay_session.py`
- Test: `tests/domain/backtester/test_replay_session.py` (append)

**Why.** Step 2 let the replay warm its own buffers, so the first ~50 days produced nothing. Over one symbol and 160 bars that is tolerable; over a universe and a decade it wastes the front of every window and, worse, makes the first weeks of any measured period systematically quiet. `seed()` exists for exactly this — it is the M27a warm start — and it must run **before** any prime, which is the rule it already enforces.

**Interfaces:**
- Produces: `ReplaySession(..., warm_bars: int = 60)` and a `start` boundary — the replay loop begins after the warmed prefix rather than at bar zero.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_the_buffers_are_warm_before_the_first_replayed_day(tmp_path):
    """Without a warm start the first ~50 days are blind, so the front of every
    measured window is systematically quiet."""
    session = ReplaySession(
        bars={"AAA": _trending_bars()},
        strategies=[SwingStrategy()],
        settings=_settings(tmp_path),
        warm_bars=60,
    )

    assert len(session.engine.bars.frame("AAA")) >= 60, "seeded before day one"
    assert len(session.bridge.bars.frame("AAA")) >= 60
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_session.py -v -k warm
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'warm_bars'`.

- [ ] **Step 3: Implement**

Add `warm_bars: int = 60` to `__init__`, and after the aggregators exist:

```python
        self.warm_bars = warm_bars
        self._warm_start()
```

```python
    def _warm_start(self) -> None:
        """Seed both buffers with the prefix, and start the clock after it.

        `seed` refuses once any bar exists, so this runs before the first
        prime - the rule the aggregator already enforces, and the reason the
        warm prefix cannot simply be primed like any other day.
        """
        if self.warm_bars <= 0:
            return
        for symbol, frame in self.bars.items():
            prefix = frame.iloc[: self.warm_bars]
            if prefix.empty:
                continue
            seeded = prefix.reset_index().rename(columns={prefix.index.name or "index": "ts"})
            self.engine.bars.seed(symbol, seeded, now=self._seed_now())
            self.bridge.bars.seed(symbol, seeded, now=self._seed_now())
        # The replayed period starts where the warm prefix ends: a day that has
        # already been seeded must not also be primed, or it is counted twice.
        self.broker._index = min(self.warm_bars, len(self.broker.session_dates) - 1)

    def _seed_now(self) -> datetime:
        """The instant the warm prefix is 'as of' - the first replayed day, so
        `seed` treats the whole prefix as closed history rather than admitting
        its last row as a forming bar."""
        index = min(self.warm_bars, len(self.broker.session_dates) - 1)
        return self.broker.session_dates[index].to_pydatetime()
```

**Note on `seed`'s frame shape:** it reads `BAR_COLUMNS` (`ts, open, high, low, close, volume`), so the index must become a `ts` column. If the rename does not produce `ts`, read `BAR_COLUMNS` and match it exactly rather than guessing.

- [ ] **Step 4: Run the file, then the whole suite**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_session.py -v
```

**The existing step-2 tests must still pass.** If `test_a_signal_becomes_an_order_at_the_broker` now fails, the warm prefix has swallowed the day the thesis fires — check where the pullback sits relative to `warm_bars` before touching anything else.

- [ ] **Step 5: Gates and commit**

```bash
git commit -m "W2: warm the buffers before the first replayed day"
```

---

### Task 3: The whole universe, with the governor live

**Files:**
- Modify: `src/qat/domain/backtester/replay_session.py`
- Test: `tests/domain/backtester/test_replay_portfolio.py` (create)

**Interfaces:**
- Produces: nothing new on the surface — `ReplaySession` already takes a dict of symbols. This task proves it behaves with several, and wires the bridge's clock.

- [ ] **Step 1: Pass the simulated clock to the bridge**

In `ReplaySession.__init__`:

```python
        self.bridge = SignalToOrderBridge(
            self.bus,
            self.oms,
            settings=settings,
            bar_interval_seconds=_DAILY_SECONDS,
            clock=self._simulated_now,
        )
```

The same callable the autonomy gate already uses. **Both rails now bind on simulated time**, which is the whole point of Task 1.

- [ ] **Step 2: Write the test**

Create `tests/domain/backtester/test_replay_portfolio.py`:

```python
"""Several symbols, one book, and the governor live (W2 step 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _bars_with_pullback_at(dip_index: int, days: int = 200) -> pd.DataFrame:
    """The dip depth is computed, not tuned - an EMA20 lags a +0.5/day trend by
    about 4.75, so 10 clears it. See the step-2 fixture for the derivation."""
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[dip_index] -= 10.0
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.5 for c in closes],
            "low": [c - 1.5 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        },
        index=index,
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )


@pytest.mark.asyncio
async def test_several_symbols_share_one_book(tmp_path):
    """Each symbol pulls back on a different day, so entries arrive spread out
    rather than all at once - which is what a portfolio actually looks like."""
    bars = {
        "AAA": _bars_with_pullback_at(120),
        "BBB": _bars_with_pullback_at(140),
        "CCC": _bars_with_pullback_at(160),
    }
    session = ReplaySession(
        bars=bars, strategies=[SwingStrategy()], settings=_settings(tmp_path)
    )

    await session.run()

    held = {p.symbol for p in await session.broker.positions()}
    orders = {o.symbol for o in session.broker._orders.values()}
    assert orders, "the production path produced no order across three symbols"
    assert held <= {"AAA", "BBB", "CCC"}
```

- [ ] **Step 3: Run it**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_portfolio.py -v
```

**If no order appears, count the stages** as step 2 did — signals, pending, at-broker, and the decision journal's `outcome`/`reason` columns. Do not reshape the bars.

- [ ] **Step 4: Gates, full suite, commit**

```bash
git commit -m "W2: replay a book of several symbols with the governor live"
```

---

### Task 4: A cap that actually binds

**Files:**
- Test: `tests/domain/backtester/test_replay_portfolio.py` (append)

**Why its own task, and why it is the point of step 3.** Everything before this proves the machinery turns. This proves the harness can observe a **rail refusing a trade** — which is the first thing it must be able to do before any ablation means anything, and the question M51 has been unable to ask since 5 August.

- [ ] **Step 1: Write the test**

```python
@pytest.mark.asyncio
async def test_the_position_limit_refuses_an_entry_and_says_so(tmp_path):
    """The first rail observation the harness can make. With the limit set to
    one, a second symbol's valid setup must be refused BY THE GOVERNOR, and the
    refusal must be visible in the journal rather than inferred from silence."""
    bars = {
        "AAA": _bars_with_pullback_at(120),
        "BBB": _bars_with_pullback_at(140),
    }
    settings = _settings(tmp_path).model_copy(update={"max_concurrent_positions": 1})
    session = ReplaySession(bars=bars, strategies=[SwingStrategy()], settings=settings)

    await session.run()

    held = [p.symbol for p in await session.broker.positions()]
    assert len(held) <= 1, "the position limit did not bind"

    journal = (tmp_path / "decision_journal.csv").read_text(encoding="utf-8")
    assert "refused" in journal or "blocked" in journal, "a refusal must be recorded, not silent"
```

The setting is `max_concurrent_positions` (`config.py:303`, default 10), verified rather than guessed — an earlier draft of this plan said `max_positions`, which does not exist. The governor reads it at `governor.py:264`.

- [ ] **Step 2: Run it**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_portfolio.py -v
```

**If the limit does not bind, that is a finding, not a test to soften.** Report it: either the governor is not reached in the replay, or the second setup never fires, and the journal will say which.

- [ ] **Step 3: Gates, full suite, commit, push**

```bash
git commit -m "W2: observe a portfolio rail refusing a trade"
```

---

## Verification, end to end

- [ ] Full suite under CI conditions: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q`
- [ ] All four gates clean
- [ ] CI green on the pushed commit

## Deliberately not in this plan

- **The regime engine on the simulated clock.** Step 4. The engine will keep logging that it gates on the sideways default, and that warning is correct.
- **Loading real vendor bars.** The universe and its normalisation arrive with the first real research run; every test here builds its bars explicitly, which is what makes the ambiguous cases stateable.
- **G1 against `decision_journal.csv`.** Step 5, and no research runs before it passes.
- **The ablation switch and the manifest.** Step 6.
