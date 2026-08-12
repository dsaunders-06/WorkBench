# W2 Step 2 — the clock and the session loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive one symbol's daily bars through the production strategy and OMS path into `SimulatedBroker`, proving bars reach the strategy and orders reach the broker.

**Architecture:** A `prime_bar` seam on the bar aggregators installs the true daily OHLC as the forming bar; an ordinary `MarketDataEvent` at that day's close then folds in harmlessly and triggers evaluation through the unmodified production path. A `ReplaySession` owns the wiring and the day loop.

**Tech Stack:** Python 3.12, pandas, pytest, pytest-asyncio.

## Global Constraints

- **The validation freeze applies.** `prime_bar` is additive and reachable only from the harness. No strategy parameter, cap, threshold or sizing rule changes.
- **No rails, no regime, no portfolio in this step.** One symbol. Step 3 adds the governor, step 4 the regime engine. A session loop that works for one symbol and lies about ten is worse than one that only claims one.
- **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store persists there.
- **Formats with `black`, not `ruff format`.**
- The venv python is `.\.venv\Scripts\python.exe`.

## Why `prime_bar` and not something simpler

`MarketDataEvent` carries a price, not a bar, and evaluation is triggered by that event. One event per day at the close gives `high == low == close`, so `compute_atr` returns ~zero — and ATR sets the stop distance, which sets position size, which the 1% and aggregate caps gate on. **Every figure would be wrong and nothing would error.**

`seed()` refuses once any bar exists, correctly, so it cannot be reused per-day.

`prime_bar` installs the true OHLC as the *forming* bar. The subsequent tick at the close folds in without damage: `max(high, close)` and `min(low, close)` are no-ops because the close sits inside the day's range.

## File Structure

- **Modify `src/qat/data/bars.py`** — `BarAggregator.prime_bar`, `MultiSymbolAggregator.prime_bar`.
- **Modify `tests/data/test_bars.py`** — the seam's guards. (Create it if absent.)
- **Create `src/qat/domain/backtester/replay_session.py`** — the wiring and the day loop.
- **Create `tests/domain/backtester/test_replay_session.py`** — bars reach the strategy, orders reach the broker.

---

### Task 1: `prime_bar`

**Files:**
- Modify: `src/qat/data/bars.py`
- Test: `tests/data/test_bars.py`

**Interfaces:**
- Consumes: `Bar`, `floor_to_interval`, `BarAggregator._completed/_forming/_trim`.
- Produces: `BarAggregator.prime_bar(bar: Bar) -> None` and `MultiSymbolAggregator.prime_bar(symbol: str, bar: Bar) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/data/test_bars.py` (create with the standard header if it does not exist):

```python
def _daily(ts: datetime, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(ts=ts, open=o, high=h, low=low, close=c, volume=1000.0)


def _day(n: int) -> datetime:
    """A daily boundary. Anchored to the epoch, as floor_to_interval is."""
    return floor_to_interval(datetime(2026, 1, 5 + n, 12, 0, tzinfo=UTC), 86_400.0)


def test_prime_bar_installs_the_true_ohlc_as_the_forming_bar():
    agg = BarAggregator(interval_seconds=86_400.0)

    agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))

    assert agg.forming is not None
    assert (agg.forming.high, agg.forming.low) == (110.0, 90.0)


def test_a_tick_at_the_close_folds_in_without_flattening_the_bar():
    """The whole reason this seam works. A daily close sits inside the day's
    range, so max(high, close) and min(low, close) are no-ops."""
    agg = BarAggregator(interval_seconds=86_400.0)
    agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))

    agg.add_tick(_day(0) + timedelta(hours=1), 105.0)

    assert (agg.forming.high, agg.forming.low, agg.forming.close) == (110.0, 90.0, 105.0)


def test_priming_the_next_day_closes_the_previous_bar():
    agg = BarAggregator(interval_seconds=86_400.0)
    agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))

    agg.prime_bar(_daily(_day(1), 105.0, 115.0, 104.0, 112.0))

    completed = agg.completed_bars()
    assert [b.high for b in completed] == [110.0]
    assert agg.forming.high == 115.0


def test_priming_out_of_order_raises_rather_than_corrupting_the_window():
    """The same rule seed() enforces: an older bar after a newer one silently
    corrupts every rolling window computed from the buffer."""
    agg = BarAggregator(interval_seconds=86_400.0)
    agg.prime_bar(_daily(_day(1), 105.0, 115.0, 104.0, 112.0))

    with pytest.raises(RuntimeError):
        agg.prime_bar(_daily(_day(0), 100.0, 110.0, 90.0, 105.0))


def test_priming_a_bar_that_is_not_on_a_boundary_raises():
    """A bar filed under the wrong boundary is a bar filed under the wrong
    day, which is the hazard as_utc exists to prevent."""
    agg = BarAggregator(interval_seconds=86_400.0)
    off_boundary = _daily(_day(0) + timedelta(hours=3), 100.0, 110.0, 90.0, 105.0)

    with pytest.raises(ValueError):
        agg.prime_bar(off_boundary)
```

Ensure the file's imports include `pytest`, `Bar`, `BarAggregator`, `MultiSymbolAggregator`, `floor_to_interval`, and `from datetime import UTC, datetime, timedelta` — **at the top of the file**, for the E402 reason.

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_bars.py -v -k prime
```

Expected: `AttributeError: 'BarAggregator' object has no attribute 'prime_bar'`.

- [ ] **Step 3: Implement it**

Add to `BarAggregator`, directly after `seed`:

```python
    def prime_bar(self, bar: Bar) -> None:
        """Install an already-true OHLC bar as the FORMING bar (W2).

        The research harness has daily bars and no ticks, and this application
        builds bars FROM ticks. One tick per day would give high == low ==
        close, ATR would collapse to zero, and ATR sets the stop distance which
        sets position size - so every figure would be wrong and nothing would
        raise.

        Priming installs the real range, and the ordinary MarketDataEvent that
        follows folds in harmlessly: the close sits inside the day's range, so
        max(high, close) and min(low, close) change nothing. Evaluation then
        runs through the production path unmodified, which is the whole point -
        a harness that fed the strategy differently would be measuring a
        different system.

        Guarded as `seed` is. An older bar landing after a newer one silently
        corrupts every rolling window computed from this buffer, and a bar off
        its boundary is a bar filed under the wrong day.
        """
        boundary = floor_to_interval(bar.ts, self.interval_seconds)
        if bar.ts != boundary:
            raise ValueError(
                f"prime_bar needs a bar on an interval boundary; {bar.ts} floors to {boundary}"
            )
        if self._forming is not None:
            if bar.ts <= self._forming.ts:
                raise RuntimeError(
                    "prime_bar must move forward: seeded and primed history cannot be "
                    "interleaved out of order"
                )
            self._completed.append(self._forming)
            self._trim()
        elif self._completed and bar.ts <= self._completed[-1].ts:
            raise RuntimeError(
                "prime_bar must move forward: seeded and primed history cannot be "
                "interleaved out of order"
            )
        self._forming = bar
```

And to `MultiSymbolAggregator`, beside `seed`:

```python
    def prime_bar(self, symbol: str, bar: Bar) -> None:
        self.for_symbol(symbol).prime_bar(bar)
```

- [ ] **Step 4: Run the tests**

```bash
.venv/Scripts/python.exe -m pytest tests/data/test_bars.py -v
```

Expected: all pass, including any pre-existing ones.

- [ ] **Step 5: Full suite — this touches a buffer every strategy reads**

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q
```

Expected: no new failures. **A failure here means the guard is stricter than some existing caller expects — stop and report rather than relaxing the guard.**

- [ ] **Step 6: Gates and commit**

```bash
.venv/Scripts/python.exe -m black src/qat/data/bars.py tests/data/test_bars.py ; .venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m mypy src
```

```bash
git add src/qat/data/bars.py tests/data/test_bars.py
```

```bash
git commit -m "W2: prime a true daily bar so a tick cannot flatten it"
```

---

### Task 2: `ReplaySession` — the wiring and the day loop

**Files:**
- Create: `src/qat/domain/backtester/replay_session.py`
- Test: `tests/domain/backtester/test_replay_session.py`

**Interfaces:**
- Consumes: `SimulatedBroker`, `prime_bar`, `OMS`, `RiskEngine`, `KillSwitch`, `EventBus`, `SignalToOrderBridge`, `StrategyEngine`, `MarketDataEvent`, `Bar`, `floor_to_interval`.
- Produces: `ReplaySession(bars, strategies, settings, warm_bars=200)` with `async def run() -> None` and attributes `broker`, `oms`, `bridge`, `engine`.

**Shape of one simulated day**, and the order is load-bearing:

1. `prime_bar` the day's true OHLC into **both** aggregators — `engine.bars` and `bridge.bars`.
2. Publish `MarketDataEvent(symbol, price=close, volume, ts)` — evaluation runs, signals may be emitted, the bridge may submit an order.
3. `broker.advance()` — pending entries fill at the **next** bar's open and protective legs are evaluated.

Step 3 comes last because `SimulatedBroker.advance` is what moves its own clock; an order submitted on day D is filled by the advance that opens day D+1, which is exactly the next-open rule already committed.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/backtester/test_replay_session.py`:

```python
"""Bars reach the strategy, and orders reach the broker (W2 step 2).

One symbol, no rails, no regime. A session loop that works for one symbol and
lies about ten is worse than one that only claims one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _trending_bars(days: int = 120) -> pd.DataFrame:
    """A clean uptrend with a pullback, so swing's thesis can actually fire."""
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i * 0.5 for i in range(days)]
    closes[-2] -= 4.0  # the pullback to the fast EMA
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


@pytest.mark.asyncio
async def test_the_strategy_sees_true_daily_bars_not_flattened_ones(tmp_path):
    """If a tick flattened the bar, high == low == close and ATR collapses -
    which would silently break every stop distance in the system."""
    session = ReplaySession(
        bars={"AAA": _trending_bars()},
        strategies=[SwingStrategy()],
        settings=Settings(_env_file=None, data_dir=str(tmp_path)),
    )

    await session.run()

    frame = session.engine.bars.frame("AAA")
    assert not frame.empty
    assert (frame["high"] > frame["low"]).all(), "a flattened bar means ATR is zero"


@pytest.mark.asyncio
async def test_the_session_advances_the_broker_to_the_end_of_the_series(tmp_path):
    bars = _trending_bars()
    session = ReplaySession(
        bars={"AAA": bars},
        strategies=[SwingStrategy()],
        settings=Settings(_env_file=None, data_dir=str(tmp_path)),
    )

    await session.run()

    assert session.broker.current_date == bars.index[-1]
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_session.py -v
```

Expected: `ModuleNotFoundError: No module named 'qat.domain.backtester.replay_session'`.

- [ ] **Step 3: Write the module**

Create `src/qat/domain/backtester/replay_session.py`:

```python
"""Drives historical bars through the PRODUCTION path (W2 step 2).

Not a backtester in the usual sense: nothing here re-implements a strategy, a
rail or a fill. It wires the real StrategyEngine, the real SignalToOrderBridge
and the real OMS to a SimulatedBroker, and moves a clock. Every decision is
made by the code that trades.

One simulated day, and the order matters:

  1. prime the day's true OHLC into BOTH aggregators - the engine keeps its own
     buffer and so does the bridge;
  2. publish MarketDataEvent at that day's close, which is what actually
     triggers evaluation;
  3. advance the broker, which fills yesterday's orders at today's open.

Step 3 is last because `advance` moves the broker's own clock: an order
submitted on day D fills on the advance that opens D+1, which is the next-open
rule the fill model already commits to.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from qat.config import Settings
from qat.data.bars import Bar, floor_to_interval
from qat.data.broker.simulated_broker import SimulatedBroker
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.domain.strategies.base import Strategy
from qat.domain.strategies.engine import StrategyEngine
from qat.presentation.runtime import resolve_fundamentals_source

_DAILY_SECONDS = 86_400.0


class ReplaySession:
    def __init__(
        self,
        bars: dict[str, pd.DataFrame],
        strategies: Sequence[Strategy],
        settings: Settings,
        warm_bars: int = 200,
    ) -> None:
        self.bars = bars
        self.settings = settings
        self.warm_bars = warm_bars
        self.bus = EventBus()
        self.kill_switch = KillSwitch()
        self.cost_model = CostModel.from_settings(settings)
        self.broker = SimulatedBroker(bars=bars, cost_model=self.cost_model)
        self.oms = OMS(
            self.broker,
            RiskEngine(self.bus, self.kill_switch, settings=settings),
            self.kill_switch,
            bus=self.bus,
        )
        self.engine = StrategyEngine(
            self.bus,
            list(strategies),
            fundamentals_source=resolve_fundamentals_source(settings),
            bar_interval_seconds=_DAILY_SECONDS,
        )
        self.bridge = SignalToOrderBridge(
            self.bus,
            self.oms,
            settings=settings,
            bar_interval_seconds=_DAILY_SECONDS,
        )

    async def run(self) -> None:
        await self.engine.start()
        await self.bridge.start()
        try:
            while True:
                await self._one_day()
                if not self.broker.advance():
                    return
        finally:
            await self.bridge.stop()
            await self.engine.stop()

    async def _one_day(self) -> None:
        today = self.broker.current_date
        for symbol, frame in self.bars.items():
            if today not in frame.index:
                continue
            row = frame.loc[today]
            bar = Bar(
                ts=floor_to_interval(today.to_pydatetime(), _DAILY_SECONDS),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
            )
            # BOTH buffers. The engine keeps its own and so does the bridge, and
            # a bar primed into only one would leave the other sizing against a
            # history that never moved.
            self.engine.bars.prime_bar(symbol, bar)
            self.bridge.bars.prime_bar(symbol, bar)
            await self.bus.publish(
                MarketDataEvent(
                    symbol=symbol,
                    price=bar.close,
                    volume=bar.volume,
                    ts=bar.ts,
                )
            )
```

- [ ] **Step 4: Run the tests**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_session.py -v
```

Expected: both pass. **If `MarketDataEvent` rejects the keyword shape or `EventBus.publish` differs, read the real signatures and fix the call — do not stub the event.**

- [ ] **Step 5: Gates and commit**

```bash
.venv/Scripts/python.exe -m black src/qat/domain/backtester/replay_session.py tests/domain/backtester/test_replay_session.py ; .venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m mypy src
```

```bash
git add src/qat/domain/backtester/replay_session.py tests/domain/backtester/test_replay_session.py
```

```bash
git commit -m "W2: drive historical bars through the production path"
```

---

### Task 3: An order actually reaches the broker

**Files:**
- Test: `tests/domain/backtester/test_replay_session.py` (append)

**Why its own task.** Task 2 proves the machinery turns. This proves it produces something — and it is the claim the whole harness rests on. A reviewer should be able to accept the wiring and reject this.

- [ ] **Step 1: Write the test**

```python
@pytest.mark.asyncio
async def test_a_signal_becomes_an_order_at_the_broker(tmp_path):
    """The claim the harness rests on: the production path, driven by history,
    produces an order without a single rule being re-implemented."""
    session = ReplaySession(
        bars={"AAA": _trending_bars()},
        strategies=[SwingStrategy()],
        settings=Settings(_env_file=None, data_dir=str(tmp_path), require_signoff=False),
    )

    await session.run()

    submitted = list(session.broker._orders.values())
    assert submitted, "the production path produced no order at all"
    assert all(o.symbol == "AAA" for o in submitted)
```

- [ ] **Step 2: Run it**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_session.py -v
```

**If no order is produced, STOP and investigate rather than adjusting the bars until one appears.** Fitting the fixture to the outcome is how a harness gets built that only works on the data it was tuned against. Likely causes, in order: sign-off is still required so nothing reaches the broker; the warm-up left too little history for `_MIN_HISTORY_FOR_SIZING`; the regime gate defaults to something that refuses; the synthetic series never satisfies swing's pullback-and-reclaim.

- [ ] **Step 3: Full suite, gates, commit**

```bash
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q
```

```bash
git add tests/domain/backtester/test_replay_session.py
```

```bash
git commit -m "W2: prove the driven path produces an order"
```

---

## Deliberately not in this plan

- **The portfolio, the governor and the caps.** Step 3.
- **The regime engine on the simulated clock.** Step 4.
- **Loading real bars from a vendor, and column normalisation.** The tests build their bars explicitly. Real loading arrives with step 3, where a universe is needed.
- **G1 against `decision_journal.csv`.** Step 5, and no research runs before it.
