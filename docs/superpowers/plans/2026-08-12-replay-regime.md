# W2 Step 4 — the regime engine on the simulated clock

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay with the real regime engine classifying, so the strategy is gated on a measurement rather than on the sideways default — and so the regime becomes an ablatable rail.

**Architecture:** No production change. `RegimeEngine.seed` and the production `WarmStart` already do everything needed; the harness supplies two tiny in-memory ports (`HistoricalBarSource`, `MacroDataSource`) bounded to the warm prefix, and publishes `MacroEvent` per simulated day so the macro columns keep moving after the seed.

**Tech Stack:** Python 3.12, pandas, pytest, pytest-asyncio.

## Global Constraints

- **No production change is required and none should be made.** If one seems necessary, stop and report — the last two times this looked true (`prime_bar`, the bridge clock) it was, and this time the seam already exists.
- **The validation freeze applies.** Harness-only code.
- **The replay boundary is absolute.** Neither adapter may return a bar or a macro observation dated after the simulated date. This is the same guard `SimulatedBroker.get_historical` carries and it needs its own test here too.
- **Every test that builds an OMS must pass its own `data_dir`.**
- **Formats with `black`.** The venv python is `.\.venv\Scripts\python.exe`.

## Why this needs no new seam

`RegimeEngine.seed(benchmark_bars, macro, breadth_bars)` was built in M27a for exactly this problem. Its docstring:

> *"Built from live ticks alone, this engine needed min_fit_bars before it could classify anything — three months of daily bars, during which the regime gate would be whatever StrategyEngine defaults to. Seeding is what makes a daily cadence viable at all."*

It is **already point-in-time correct**: each bar is paired with `macro.as_of(series, ts)`, the reading current on that bar's own date, and `MacroHistory` carries values forward rather than interpolating — *"a series that publishes on Friday is genuinely the market's best information all weekend, where an interpolated value is a number nobody could have seen."*

**And `min_fit_bars = 60` is not arbitrary.** ROADMAP records it as ~3 months of DAILY bars, the window over which VIX and credit spreads genuinely move. The 28 July NaN fit was that same 60 being fed one-minute bars — one hour of market — leaving the FRED columns constant and the covariance singular. *"A correct mechanism wired to the wrong input."* The replay is daily, so the number is being used as intended.

**This also replaces the bespoke `_warm_start` written in step 3.** Production `WarmStart` seeds every aggregator *and* the regime engine from the same ports; keeping a second warm path in the harness is exactly the duplication this whole design exists to avoid.

---

### Task 1: The two in-memory ports

**Files:**
- Create: `src/qat/domain/backtester/replay_sources.py`
- Test: `tests/domain/backtester/test_replay_sources.py`

**Interfaces:**
- Produces:
  - `ReplayHistorySource(bars: dict[str, pd.DataFrame], until_index: int)` with
    `async def get_daily_bars(symbol: str, n_bars: int = ...) -> pd.DataFrame` returning `BAR_COLUMNS`
  - `ReplayMacroSource(observations: dict[str, list[MacroObservation]], until: datetime)` with
    `async def fetch_series(series_id: str) -> list[MacroObservation]`

- [ ] **Step 1: Write the failing tests**

```python
"""The warm-start ports, bounded at the replay boundary (W2 step 4).

Both exist to feed the PRODUCTION WarmStart from bars already in memory. The
property that matters is the same one SimulatedBroker.get_historical carries:
a simulator holds the whole series and must refuse to answer past the boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from qat.data.macro_fred import MacroObservation
from qat.domain.backtester.replay_sources import ReplayHistorySource, ReplayMacroSource


def _bars(days: int = 100) -> pd.DataFrame:
    index = pd.date_range("2026-01-05", periods=days, freq="B", tz="UTC")
    closes = [100.0 + i for i in range(days)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000.0] * days,
        },
        index=index,
    )


@pytest.mark.asyncio
async def test_history_stops_at_the_replay_boundary():
    source = ReplayHistorySource({"AAA": _bars()}, until_index=60)

    frame = await source.get_daily_bars("AAA", n_bars=500)

    assert len(frame) == 60, "the warm prefix only - never a bar the replay has not reached"
    assert list(frame.columns) == ["ts", "open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_history_respects_the_requested_count():
    source = ReplayHistorySource({"AAA": _bars()}, until_index=60)
    frame = await source.get_daily_bars("AAA", n_bars=10)
    assert len(frame) == 10
    assert frame["close"].iloc[-1] == pytest.approx(159.0), "the newest of the prefix"


@pytest.mark.asyncio
async def test_an_unknown_symbol_answers_empty():
    source = ReplayHistorySource({"AAA": _bars()}, until_index=60)
    assert (await source.get_daily_bars("ZZZ")).empty


@pytest.mark.asyncio
async def test_macro_stops_at_the_replay_boundary():
    boundary = datetime(2026, 3, 1, tzinfo=UTC)
    observations = {
        "VIXCLS": [
            MacroObservation(series="VIXCLS", ts=datetime(2026, 2, 1, tzinfo=UTC), value=14.0),
            MacroObservation(series="VIXCLS", ts=datetime(2026, 4, 1, tzinfo=UTC), value=30.0),
        ]
    }
    source = ReplayMacroSource(observations, until=boundary)

    got = await source.fetch_series("VIXCLS")

    assert [o.value for o in got] == [14.0], "the April reading had not happened yet"


@pytest.mark.asyncio
async def test_an_unknown_series_answers_empty():
    source = ReplayMacroSource({}, until=datetime(2026, 3, 1, tzinfo=UTC))
    assert await source.fetch_series("NOPE") == []
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError`.

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester/test_replay_sources.py -v
```

- [ ] **Step 3: Write the module**

```python
"""In-memory warm-start ports for the replay harness (W2 step 4).

The production `WarmStart` seeds every aggregator and the regime engine from a
HistoricalBarSource and a MacroDataSource. The harness already holds its bars,
so rather than a second warm-start path it supplies those two ports - which is
what keeps there being exactly one implementation of "fill the buffers".

Both are bounded at the replay boundary. A simulator holds the whole series in
memory, and nothing except the bound stops the warm start handing the strategy
and the regime engine data from the future.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from qat.data.bars import BAR_COLUMNS
from qat.data.history import DEFAULT_BARS
from qat.data.macro_fred import MacroObservation


class ReplayHistorySource:
    """Daily bars up to the replay boundary, in BAR_COLUMNS shape."""

    def __init__(self, bars: dict[str, pd.DataFrame], until_index: int) -> None:
        self._bars = bars
        self._until_index = max(0, until_index)

    async def get_daily_bars(self, symbol: str, n_bars: int = DEFAULT_BARS) -> pd.DataFrame:
        frame = self._bars.get(symbol)
        if frame is None:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        prefix = frame.iloc[: self._until_index]
        if prefix.empty:
            return pd.DataFrame(columns=list(BAR_COLUMNS))
        window = prefix.iloc[-n_bars:] if n_bars > 0 else prefix
        out = window.reset_index()
        out = out.rename(columns={out.columns[0]: "ts"})
        if "volume" not in out.columns:
            out["volume"] = 0.0
        return out[list(BAR_COLUMNS)]


class ReplayMacroSource:
    """Macro observations that had already been published at the boundary."""

    def __init__(
        self, observations: dict[str, list[MacroObservation]], until: datetime
    ) -> None:
        self._observations = observations
        self._until = until

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        return [o for o in self._observations.get(series_id, []) if o.ts <= self._until]
```

- [ ] **Step 4: Run the tests**, then gates, then commit.

```bash
git commit -m "W2: in-memory warm-start ports, bounded at the replay boundary"
```

---

### Task 2: Use the production warm start, and wire the regime engine

**Files:**
- Modify: `src/qat/domain/backtester/replay_session.py`
- Test: `tests/domain/backtester/test_replay_session.py` (the existing warm test must still pass)

**Interfaces:**
- Consumes: Task 1's ports, `WarmStart`, `RegimeEngine`.
- Produces: `ReplaySession(..., macro: dict[str, list[MacroObservation]] | None = None, benchmark: str = "SPY")`, and `session.regime_engine`.

- [ ] **Step 1: Replace `_warm_start`**

Delete the bespoke `_warm_start` body and replace with a `WarmStart` call. Construct the regime engine first, since `WarmStart` takes it:

```python
        self.regime_engine = RegimeEngine(
            self.bus,
            benchmark_symbol=benchmark,
            breadth_symbols=tuple(bars),
            bar_interval_seconds=_DAILY_SECONDS,
        )
```

```python
    async def _warm_start(self) -> None:
        """Seed every buffer AND the regime engine, through the production path.

        `WarmStart` is what the live application runs, and it already seeds all
        three aggregators plus the regime engine from two ports. Writing a
        second warm path here would be the duplication this whole harness
        exists to avoid - and would drift from the live one the first time
        either changed.

        The regime engine's own seed is point-in-time correct: it pairs each
        bar with `macro.as_of(series, ts)` rather than one constant reading,
        which is both look-ahead-safe and the reason its covariance matrix is
        not singular.
        """
        if self.warm_bars <= 0:
            return
        start = min(self.warm_bars, len(self.broker.session_dates) - 1)
        warm = WarmStart(
            ReplayHistorySource(self.bars, until_index=start),
            ReplayMacroSource(self._macro, until=self.broker.session_dates[start].to_pydatetime()),
            symbols=tuple(self.bars),
            benchmark_symbol=self.benchmark,
            aggregators=(self.engine.bars, self.bridge.bars),
            regime_engine=self.regime_engine,
            macro_series=tuple(self._macro),
            n_bars=start,
        )
        await warm.seed()
        self.broker._index = start
```

**`_warm_start` becomes async**, so it moves out of `__init__` and into `run()` before the engines start. Update the existing warm test accordingly — it currently asserts on a session that has not run, so it must `await session.warm()` or assert after `run()`.

- [ ] **Step 2: Start the regime engine in `run()`**

```python
        await self._warm_start()
        await self.regime_engine.start()
        await self.engine.start()
```

- [ ] **Step 3: Run the existing tests**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/backtester -v
```

**The step-2 and step-3 tests must still pass.** If the order test now fails, check whether the regime engine is refusing swing — the gate is real now, and a refusal is a legitimate outcome that the test may need to accommodate rather than a bug to suppress. **Report before changing the assertion.**

- [ ] **Step 4: Gates and commit.**

```bash
git commit -m "W2: warm through the production WarmStart, with the regime engine in it"
```

---

### Task 3: Macro keeps moving, and the regime goes live

**Files:**
- Modify: `src/qat/domain/backtester/replay_session.py` (`_one_day`)
- Test: `tests/domain/backtester/test_replay_regime.py` (create)

**Why.** Seeding fills the matrix up to the boundary. After that the macro columns freeze unless the replay keeps publishing them, and a frozen VIX column across a decade is the constant column that makes the fit singular — the 28 July failure by a slower route.

- [ ] **Step 1: Publish `MacroEvent` per simulated day**

In `_one_day`, before the per-symbol loop:

```python
        for series, observations in self._macro.items():
            value = _as_of(observations, today.to_pydatetime())
            if value is not None:
                await self.bus.publish(MacroEvent(series=series, value=value))
```

with a module-level helper that carries the last reading forward, matching `MacroHistory`'s documented rule — *values are carried forward, not interpolated*.

- [ ] **Step 2: Write the test**

The claim to test is the one the log already makes. Today every replay prints:

> `Gating 1 strategies on the sideways DEFAULT - the regime engine has published nothing.`

With the regime engine seeded and fed, that warning must stop, and the engine must publish a real label.

```python
@pytest.mark.asyncio
async def test_the_regime_is_measured_rather_than_defaulted(tmp_path, caplog):
    """The engine's own warning is the assertion: gating on the sideways
    DEFAULT means strategies are permitted or refused with no reading of the
    market at all."""
    session = _session_with_benchmark(tmp_path)

    with caplog.at_level(logging.WARNING):
        await session.run()

    assert "sideways DEFAULT" not in caplog.text
    assert session.regime_engine._hmm.is_fitted
```

Build the fixture with a benchmark series (`SPY`) and at least `warm_bars` of macro observations for the five configured series — `DGS3MO`, `DGS10`, `T10Y3M`, `VIXCLS`, `BAA10Y`. **They must vary across rows**; constant columns are the singular-covariance failure this plan quotes twice.

- [ ] **Step 3: Run it**

**If the regime never publishes, count the stages** — matrix rows against `min_fit_bars`, whether `_fit` returned False, whether the benchmark symbol matches. Do not lower `min_fit_bars`; ROADMAP explains what it is for and lowering it is how the singular covariance comes back.

- [ ] **Step 4: Full suite, gates, commit, push.**

```bash
git commit -m "W2: feed macro daily so the regime is measured, not defaulted"
```

---

## Verification, end to end

- [ ] `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q`
- [ ] All four gates clean
- [ ] CI green on the pushed commit

## Deliberately not in this plan

- **Real FRED series.** The ports take observations from the caller; wiring a live fetch belongs with the first real research run, and a test must never reach the network.
- **G1.** Step 5, and no research runs before it passes.
- **The ablation switch and the manifest.** Step 6 — but note that regime is now a rail like any other, which is what makes it ablatable at all.
