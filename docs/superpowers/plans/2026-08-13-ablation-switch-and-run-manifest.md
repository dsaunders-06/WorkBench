# W2 Step 6 — Ablation Switch and Run Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the research harness an outcome it can measure, a per-rail ablation switch, and a manifest that records what each run may and may not be quoted as saying.

**Architecture:** Rails are disabled by setting their existing `Settings` values beyond reach, so no file in the trading path is edited and the shipped `RiskEngine` and `PortfolioGovernor` run exactly as they trade. Outcomes come from wiring the existing `TradeLedger` and the existing `OMS.absorb_broker_fills` into `ReplaySession` — both ship today and are simply not connected. The manifest derives its per-rail binding counts from the run's own `risk_decisions.csv` through the existing `refusals.rail_of`, never a second classifier.

**Tech Stack:** Python 3.12, pydantic-settings, pandas, pytest. Format with `black` (never `ruff format`).

**Spec:** `docs/superpowers/specs/2026-08-13-ablation-switch-and-run-manifest-design.md`

## Global Constraints

- **Validation freeze:** nothing lands that changes which trades happen or how large they are. Reporting, logging and analysis are permitted. A defect that corrupts the record is fix-immediately.
- **New production seams must default to live behaviour.** Precedent: `SignalToOrderBridge(clock=)` and `RiskEngine(clock=)` both default to the wall clock. Task 1 adds the fourth on the same terms.
- **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets `QAT_DATA_DIR` session-wide and the anomaly store persists there, so one declared anomaly leaks a quarantine into every later test.
- **Any script run outside pytest must pass its own `data_dir`.** `Settings(_env_file=None).data_dir` resolves to the LIVE data directory.
- **Run everything through the PowerShell tool, never Bash.** The Bash sandbox is per-file and covers writes as well as reads.
- **Verification commands**, all via the venv python:
  - `& '.\.venv\Scripts\python.exe' -m ruff check .`
  - `& '.\.venv\Scripts\python.exe' -m black --check .`
  - `& '.\.venv\Scripts\python.exe' -m mypy src`
  - `& '.\.venv\Scripts\python.exe' -m bandit -r src -q`
  - `& '.\.venv\Scripts\python.exe' -m pytest tests -q`
- **Baseline at the time of writing:** 2,034 passed, 25 skipped.
- **PowerShell 5.1 on the operator's terminal:** `;` not `&&`, `@'...'@` here-strings with the closing `'@` at column 0.

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/domain/oms/oms.py` | *Modify.* Accept an injectable clock; use it for the fill watermark default. |
| `src/qat/domain/backtester/replay_session.py` | *Modify.* Wire `TradeLedger`, call the absorb sweep each day, pass the simulated clock to the OMS. |
| `src/qat/domain/backtester/ablation.py` | *Create.* The rail→knob mapping and `Settings` construction. Knows nothing about running a session. |
| `src/qat/domain/backtester/manifest.py` | *Create.* Building, serialising and reading a `RunManifest`. Knows nothing about ablation mechanics. |
| `src/qat/domain/backtester/run_comparison.py` | *Create.* Reads two runs and reports the difference, with the not-exercised guard. |
| `scripts/analysis/g1/run_g1.py` | *Modify.* Dump the `Verdict` to `g1_verdict.json`. |
| `scripts/research/run_ablation.py` | *Create.* The operator-facing runner: baseline, ablated, comparison. |

Ablation, manifest and comparison are three files rather than one because they have three different reasons to change: the mapping changes when a rail is added, the manifest when provenance requirements change, the comparison when the reporting question changes.

---

### Task 1: The OMS clock seam — the fifth wall-clock trap

`OMS._load_fill_state` returns `datetime.now(UTC)` when there is no state file, which is exactly a replay's situation with a fresh scratch `data_dir`. Every simulated `BrokerFill.filled_at` is in the past, so `recent_fills(since=now)` returns nothing and **the absorb sweep records zero closed trades while reporting success.** Task 2 cannot work until this does.

Same family as the three known seams, and it gets the same treatment: injectable, defaulting to the wall clock, so live behaviour is unchanged.

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — `__init__` signature, `_load_fill_state`
- Test: `tests/domain/oms/test_oms_clock.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `OMS(..., clock: Callable[[], datetime] | None = None)`, and `OMS._now() -> datetime`. Task 2 passes `clock=self._simulated_now`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/oms/test_oms_clock.py`:

```python
"""The OMS's fill watermark reads a clock, and in a replay that clock is not now.

`_load_fill_state` falls back to `datetime.now(UTC)` when there is no state
file. A replay of 2026 run in 2026 then asks the broker for fills "since now",
gets none, and records no closed trades at all - reporting an honest-looking
zero. The fourth injectable clock in the trading path, and the fourth for the
same reason.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_SIMULATED = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)


def _oms(tmp_path, clock=None) -> OMS:
    from qat.config import Settings

    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    return OMS(
        MockBroker(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
        clock=clock,
    )


def test_without_a_clock_the_watermark_is_now(tmp_path):
    """Live behaviour, unchanged. The default must stay the wall clock."""
    before = datetime.now(UTC)

    oms = _oms(tmp_path)

    assert before <= oms._last_fill_scan <= datetime.now(UTC)


def test_an_injected_clock_sets_the_watermark(tmp_path):
    """Without this a replay asks for fills since NOW, gets none, and records
    no closed trades while looking like it worked."""
    oms = _oms(tmp_path, clock=lambda: _SIMULATED)

    assert oms._last_fill_scan == _SIMULATED
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/oms/test_oms_clock.py -q`

Expected: FAIL — `TypeError: OMS.__init__() got an unexpected keyword argument 'clock'`.

- [ ] **Step 3: Add the seam**

In `src/qat/domain/oms/oms.py`, add `clock` to `__init__`'s signature (last parameter, after the existing optional ones) and store it. Add the accessor beside it:

```python
        # The fourth injectable clock in the trading path, and the fourth for
        # the same reason (W2 step 6). `_load_fill_state` falls back to "now"
        # when there is no state file, which is every replay: the harness then
        # asks the broker for fills since the wall clock, a simulated 2026 fill
        # is older than that, and the absorb sweep records nothing while
        # reporting success. Defaults to the wall clock, so live is unchanged.
        self._clock = clock
```

Add the method beside `_load_fill_state`:

```python
    def _now(self) -> datetime:
        """The clock the fill watermark defaults to. See `__init__`."""
        return self._clock() if self._clock is not None else datetime.now(UTC)
```

`self._clock` must be assigned **before** the `self._last_fill_scan = self._load_fill_state()` line at `oms.py:178`, or the accessor reads an attribute that does not exist yet.

- [ ] **Step 4: Use it in the fallback**

In `_load_fill_state`, replace both `return datetime.now(UTC)` statements with `return self._now()`. Extend its docstring:

```python
        No file, no settings, or an unreadable file all mean "start from the
        clock", which is exactly the pre-M50 behaviour: nothing is replayed,
        and nothing can be double-recorded either. Degrading to the old
        behaviour is the right failure here, because the old behaviour was
        merely incomplete rather than wrong.

        The clock is injectable because "now" is the wrong answer in a replay -
        see `__init__`.
```

- [ ] **Step 5: Run the tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/oms/test_oms_clock.py -q`

Expected: PASS, 2 passed.

- [ ] **Step 6: Run the full suite — this touches the OMS constructor**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests -q`

Expected: 2,036 passed, 25 skipped. Any failure here is a caller passing positionally into the changed signature; fix by keeping `clock` last.

- [ ] **Step 7: Commit**

```bash
git add src/qat/domain/oms/oms.py tests/domain/oms/test_oms_clock.py
git commit -m "Give the OMS the fourth injectable clock, for the fill watermark"
```

---

### Task 2: Wire the TradeLedger and the absorb sweep

The harness records no closed trades: `TradeLedger` is not constructed and `absorb_broker_fills` is never called, so a stop fires, the position leaves the book, and nothing records it.

**Files:**
- Modify: `src/qat/domain/backtester/replay_session.py`
- Test: `tests/domain/backtester/test_replay_outcomes.py` (create)

**Interfaces:**
- Consumes: `OMS(clock=)` from Task 1.
- Produces: `ReplaySession.ledger: TradeLedger`, and `closed_trades.csv` in the session's `data_dir`. Task 4 reads that file; Task 6 compares two of them.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/backtester/test_replay_outcomes.py`:

```python
"""A stop that fires must become a ClosedTrade (W2 step 6).

Without this the harness opens positions, watches stops fire, correctly drops
the position count - and records no P&L, no expectancy and no R-multiple. An
ablation switch with no outcome can only compare which rails bound, never
whether the rails helped, which is the question the harness exists for.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.backtester.replay_session import ReplaySession
from qat.domain.strategies.swing import SwingStrategy


def _rising_then_collapsing(days: int = 120) -> pd.DataFrame:
    """Enough of a rise to trigger swing's entry, then a gap down through any
    plausible ATR stop. Deterministic - a random series would make the test's
    own failure mode unreadable."""
    index = pd.bdate_range("2026-01-01", periods=days, tz="UTC")
    closes = [100.0 + i * 0.75 for i in range(days - 3)] + [40.0, 39.0, 38.0]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        },
        index=index,
    )
    return frame


@pytest.mark.asyncio
async def test_a_fired_stop_becomes_a_closed_trade(tmp_path: Path):
    bars = {"AAA": _rising_then_collapsing(), "SPY": _rising_then_collapsing()}
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )

    session = ReplaySession(
        bars=bars,
        strategies=[SwingStrategy()],
        settings=settings,
        benchmark="SPY",
        warm_bars=60,
    )
    await session.run()

    path = tmp_path / "closed_trades.csv"
    assert path.exists(), "the harness recorded no closed trades at all"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "closed_trades.csv exists but is empty"
    assert any(row["symbol"] == "AAA" for row in rows)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_replay_outcomes.py -q`

Expected: FAIL — `AssertionError: the harness recorded no closed trades at all`.

- [ ] **Step 3: Construct the ledger**

In `replay_session.py`, add the import:

```python
from qat.domain.performance.trades import TradeLedger
```

In `__init__`, pass the clock to the OMS and build the ledger after it. Replace the `self.oms = OMS(...)` call's closing arguments so it reads:

```python
        self.oms = OMS(
            self.broker,
            RiskEngine(
                self.bus,
                self.kill_switch,
                settings=settings,
                # Or every audited decision is stamped with the day the replay
                # RAN rather than the day it simulated (W2 G1).
                clock=self._simulated_now,
            ),
            self.kill_switch,
            bus=self.bus,
            # Or the fill watermark starts at the wall clock, every simulated
            # fill is older than that, and the absorb sweep below records
            # nothing while reporting success (W2 step 6).
            clock=self._simulated_now,
        )
        # The only source of realised outcomes. Without it the harness opens
        # positions, watches stops fire, and measures nothing - which makes an
        # ablation switch able to compare rails bound but never whether the
        # rails helped.
        self.ledger = TradeLedger(self.bus, settings.data_dir, settings=settings)
```

- [ ] **Step 4: Start, sweep and stop it**

`await self.oms.risk_engine.start()` is **already present** — it landed on 13 August as commit `1e8ebba`, which is what revived the regime rail. Add only the ledger line beneath it. The block should read:

```python
        await self.oms.risk_engine.start()
        await self.ledger.start()
        await self.regime_engine.start()
        await self.engine.start()
        await self.bridge.start()
        await self.executor.start()
```

Change the loop so the sweep runs after the advance, and add the ledger to the teardown:

```python
        try:
            while True:
                await self._one_day()
                if not self.broker.advance():
                    return
                # AFTER the advance, which is what fires stops and targets.
                # Sweeping before it would ask about a day on which nothing had
                # yet happened, and this is also what makes the M88 absorb path
                # genuinely exercised rather than merely claimed.
                await self.oms.absorb_broker_fills()
        finally:
            await self.executor.stop()
            await self.bridge.stop()
            await self.engine.stop()
            await self.regime_engine.stop()
            await self.ledger.stop()
            await self.oms.risk_engine.stop()
```

Note the `return` inside the loop: the final advance that ends the replay skips the sweep. That is correct — an advance returning `False` moved no clock, so no new fill exists.

- [ ] **Step 5: Run the test**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_replay_outcomes.py -q`

Expected: PASS.

If it still fails with an empty file, the cause is the entry lot rather than the exit: check that `closed_trades.csv` is absent rather than empty, and confirm an `OrderFilledEvent` was published for the *entry* by adding a temporary bus subscriber in the test. Task 3 covers the entry side.

- [ ] **Step 6: Update the module docstring**

`replay_session.py`'s docstring lists three steps per simulated day. Make it four:

```
  1. prime the day's true OHLC into BOTH aggregators - the engine keeps its own
     buffer and so does the bridge;
  2. publish MarketDataEvent at that day's close, which is what actually
     triggers evaluation;
  3. advance the broker, which fills yesterday's orders at today's open;
  4. absorb broker fills, turning any stop or target the advance fired into a
     ClosedTrade through the real M88 path.
```

- [ ] **Step 7: Full suite and commit**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests -q`

```bash
git add src/qat/domain/backtester/replay_session.py tests/domain/backtester/test_replay_outcomes.py
git commit -m "Give the replay an outcome: the trade ledger and the absorb sweep"
```

---

### Task 3: The recorded entry price must be the fill, not the reference

`OMS._announce_fill` publishes `OrderFilledEvent` with `order.filled_price or order.reference_price`, and `SimulatedBroker.place_order` queues without filling — so at sign-off there is no `filled_price` and the ledger records the **reference** price. The fill model's central decision, *entries fill at the next bar's open*, would then be invisible in every recorded trade, and expectancy would be computed against a basis the simulator never charged.

This is M70 reproduced inside the instrument built to measure M70's system.

**Files:**
- Modify: `src/qat/domain/backtester/replay_session.py`
- Test: `tests/domain/backtester/test_replay_outcomes.py` (extend)

**Interfaces:**
- Consumes: `ReplaySession.ledger` from Task 2.
- Produces: closed-trade rows whose `entry_price` equals the next session's open.

- [ ] **Step 1: Write the failing test**

Append to `tests/domain/backtester/test_replay_outcomes.py`:

```python
@pytest.mark.asyncio
async def test_the_recorded_entry_price_is_the_fill_not_the_reference(tmp_path: Path):
    """The fill model's central decision is that entries fill at the NEXT bar's
    open. If the ledger records the signal bar's close instead, every
    expectancy figure is computed against a basis the simulator never charged -
    and the look-ahead the fill model was written to exclude comes back in
    through the record."""
    frame = _rising_then_collapsing()
    bars = {"AAA": frame, "SPY": frame}
    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )

    session = ReplaySession(
        bars=bars,
        strategies=[SwingStrategy()],
        settings=settings,
        benchmark="SPY",
        warm_bars=60,
    )
    await session.run()

    with (tmp_path / "closed_trades.csv").open(encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["symbol"] == "AAA"]
    assert rows

    opened = pd.Timestamp(rows[0]["opened_at"]).normalize()
    opens = frame.index.normalize()
    following = opens[opens > opened]
    assert len(following) > 0
    expected_open = float(frame.loc[following[0], "open"])

    assert float(rows[0]["entry_price"]) == pytest.approx(expected_open, rel=1e-6)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_replay_outcomes.py::test_the_recorded_entry_price_is_the_fill_not_the_reference -q`

Expected: FAIL — the recorded `entry_price` is the signal bar's close, higher than the next open in a rising series.

- [ ] **Step 3: Correct the basis after the advance**

The production correction path already exists: `TradeLedger` subscribes to `EntryPriceCorrectedEvent`, which is M65's mechanism. Publish it from the replay once the true fill is known — in `run()`, immediately after the absorb sweep:

```python
                await self.oms.absorb_broker_fills()
                await self._correct_entry_prices()
```

Add the method to `ReplaySession`:

```python
    async def _correct_entry_prices(self) -> None:
        """Replace the reference price the sign-off announced with what the
        broker actually charged (W2 step 6).

        `_announce_fill` publishes at `filled_price or reference_price`, and a
        SimulatedBroker order is queued rather than filled at sign-off - so
        without this every recorded entry carries the signal bar's CLOSE while
        the simulator charged the next bar's OPEN. The fill model's central
        decision would be invisible in the record, and expectancy would be
        computed against a basis nobody paid.

        This is M70 reproduced inside the instrument built to measure it, and
        it uses M65's own correction event rather than a second mechanism.
        """
        for order_id, fill_price in self.broker.drain_entry_fills().items():
            order = self.oms._orders.get(order_id)
            if order is None or order.side != "buy":
                continue
            await self.bus.publish(
                EntryPriceCorrectedEvent(
                    symbol=order.symbol,
                    order_id=order_id,
                    old_price=float(order.reference_price or fill_price),
                    new_price=float(fill_price),
                )
            )
```

Import it at the top of the module:

```python
from qat.domain.events import EntryPriceCorrectedEvent, MacroEvent, MarketDataEvent
```

- [ ] **Step 4: Expose the fills the broker charged**

`SimulatedBroker._fill_pending_entries` knows each entry's fill price and currently keeps it. Add the accessor beside it in `src/qat/data/broker/simulated_broker.py`:

```python
    def drain_entry_fills(self) -> dict[str, float]:
        """Entry fills executed since the last call, by order id.

        Drained rather than accumulated: a caller that read the same fill twice
        would publish a second correction against a price already corrected,
        and the ledger would record a basis that drifts further from the truth
        with every sweep.
        """
        fills, self._entry_fills = dict(self._entry_fills), {}
        return fills
```

Initialise `self._entry_fills: dict[str, float] = {}` in `__init__`, and record into it inside `_fill_pending_entries` at the point the fill price is computed:

```python
            self._entry_fills[order.order_id] = fill_price
```

- [ ] **Step 5: Run both tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_replay_outcomes.py -q`

Expected: PASS, 2 passed.

- [ ] **Step 6: Verify the event's field names against the source**

`EntryPriceCorrectedEvent`'s constructor arguments in Step 3 are written from `src/qat/domain/events.py`. Open that file, confirm the field names, and correct Step 3's call if they differ. A plan that guessed a field name would fail at runtime rather than at type-check.

Run: `& '.\.venv\Scripts\python.exe' -m mypy src`

- [ ] **Step 7: Full suite and commit**

```bash
git add src/qat/domain/backtester/replay_session.py src/qat/data/broker/simulated_broker.py tests/domain/backtester/test_replay_outcomes.py
git commit -m "Record what the simulator charged, not what the sign-off announced"
```

---

### Task 4: AblationConfig

**Files:**
- Create: `src/qat/domain/backtester/ablation.py`
- Test: `tests/domain/backtester/test_ablation.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RAILS: dict[str, dict[str, object]]` — rail name → the `Settings` overrides that neutralise it.
  - `ablated_settings(base: Settings, disabled: Sequence[str]) -> Settings`
  - `REGIME_RAIL: str` — the one rail with no knob, handled by the caller.
  - `UnablatableRail(ValueError)`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/backtester/test_ablation.py`:

```python
"""Turning a rail off, and refusing to pretend when it cannot be (W2 step 6)."""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.backtester.ablation import (
    RAILS,
    UnablatableRail,
    ablated_settings,
)


def _base(tmp_path) -> Settings:
    return Settings(_env_file=None, data_dir=str(tmp_path))


def test_every_neutral_value_survives_its_own_validator(tmp_path):
    """A neutral value outside a field's bounds would raise at construction and
    make the rail silently unablatable."""
    for rail in RAILS:
        settings = ablated_settings(_base(tmp_path), [rail])
        assert isinstance(settings, Settings)


def test_the_position_limit_stops_binding(tmp_path):
    settings = ablated_settings(_base(tmp_path), ["position_limit"])

    assert settings.max_concurrent_positions >= 10_000


def test_an_unknown_rail_is_refused_not_ignored(tmp_path):
    """Silently running a baseline twice and reporting no difference is the
    failure this whole design is shaped to avoid."""
    with pytest.raises(UnablatableRail, match="not ablatable"):
        ablated_settings(_base(tmp_path), ["a rail nobody has written"])


def test_the_cost_flag_is_refused_by_name(tmp_path):
    """`apply_costs_in_paper` gates the cost RAIL and whether TradeLedger
    charges costs into recorded P&L. Using it would disable the rail and make
    every trade free, so the no-rail arm would win for a reason unrelated to
    the rail."""
    with pytest.raises(UnablatableRail, match="two consumers"):
        ablated_settings(_base(tmp_path), ["apply_costs_in_paper"])


def test_disabling_nothing_changes_nothing(tmp_path):
    base = _base(tmp_path)

    settings = ablated_settings(base, [])

    assert settings.max_concurrent_positions == base.max_concurrent_positions
    assert settings.max_cost_to_risk_pct == base.max_cost_to_risk_pct
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_ablation.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'qat.domain.backtester.ablation'`.

- [ ] **Step 3: Write the module**

Create `src/qat/domain/backtester/ablation.py`:

```python
"""Turning one rail off, without editing the code that decides trades (W2 step 6).

A rail is disabled by setting its existing `Settings` value beyond reach, so the
shipped `RiskEngine` and `PortfolioGovernor` run exactly as they trade. The
alternative - threading a RailSet through the decision path with `if enabled`
guards - would make "off" genuinely off, and would put new branches inside the
code the validation freeze exists to hold still. A guard defaulting to on is
still an edit to the decision path.

TWO RAILS CANNOT BE MADE PERFECTLY ABSENT, and the manifest states so rather
than this table pretending otherwise:

* the aggregate cap at 1.0 still refuses when risk-at-stop reaches 100% of
  equity, reachable through positions carrying no known stop;
* cost-to-risk at 1.0 still refuses a trade whose round trip exceeds its whole
  1R.

Every value here is inside its field's own validator - see
`test_every_neutral_value_survives_its_own_validator`, which constructs each
one rather than trusting this comment.
"""

from __future__ import annotations

from collections.abc import Sequence

from qat.config import Settings

# The regime gate has no knob: it arrives as `RegimeEvent.exposure_scalar`.
# Ablating it means not starting the regime engine, which is the caller's job.
REGIME_RAIL = "regime_gate"

# Refused by name, with the reason, because it is the one plausible-looking
# choice that would silently confound a result. `apply_costs_in_paper` is read
# by `RiskEngine._costs_apply` for the rail AND by `TradeLedger.__init__` for
# whether costs are charged into recorded P&L.
_TWO_CONSUMERS = {
    "apply_costs_in_paper": (
        "`apply_costs_in_paper` has two consumers - the cost rail and the trade "
        "ledger's cost accounting. Disabling it would switch off the rail and make "
        "every recorded trade free, so the no-rail arm would win for a reason that "
        "has nothing to do with the rail. Use the `cost_to_risk` rail instead."
    )
}

RAILS: dict[str, dict[str, object]] = {
    "position_limit": {"max_concurrent_positions": 10_000},
    "aggregate_risk_cap": {"max_aggregate_risk_at_stop_pct": 1.0},
    "single_name_cap": {"max_single_name_concentration_pct": 1.0},
    "sector_cap": {"max_sector_concentration_pct": 1.0},
    # BOTH knobs. The percentage alone leaves a perfectly correlated pair still
    # forming a cluster; the threshold alone leaves the cap in place for one.
    "correlated_cluster": {
        "correlation_cluster_threshold": 1.0,
        "max_correlated_cluster_pct": 1.0,
    },
    "gap_risk": {"max_gap_risk_at_shock_pct": 1.0},
    "portfolio_es": {"portfolio_es_limit_pct": 1e6},
    "cost_to_risk": {"max_cost_to_risk_pct": 1.0},
    "minimum_hold": {"enforce_min_holding_period": False},
    "time_stop": {"enforce_time_stop": False},
    "churn_cap": {"max_entries_per_week": 10_000},
    "earnings_trim": {"enforce_earnings_event_risk": False},
}

# Neither is perfectly absent when neutralised. Named here so the manifest can
# say so rather than a reader having to remember it.
IMPERFECT: dict[str, str] = {
    "aggregate_risk_cap": "still refuses at 100% of equity at risk",
    "cost_to_risk": "still refuses a round trip exceeding the whole 1R",
}


class UnablatableRail(ValueError):
    """A rail this module cannot neutralise.

    Raised rather than ignored. Running a baseline twice and reporting no
    difference is indistinguishable from a rail that costs nothing, and that
    is the failure shape this design exists to prevent.
    """


def ablated_settings(base: Settings, disabled: Sequence[str]) -> Settings:
    """`base` with every named rail's knob set beyond reach."""
    overrides: dict[str, object] = {}
    for rail in disabled:
        if rail in _TWO_CONSUMERS:
            raise UnablatableRail(_TWO_CONSUMERS[rail])
        if rail == REGIME_RAIL:
            # Real, and not a Settings change: the caller does not start the
            # regime engine. Accepted here so a caller can name every rail in
            # one list.
            continue
        if rail not in RAILS:
            raise UnablatableRail(
                f"{rail!r} is not ablatable - no known Settings knob neutralises it. "
                f"Known rails: {', '.join(sorted(RAILS))}, {REGIME_RAIL}."
            )
        overrides.update(RAILS[rail])
    return base.model_copy(update=overrides)
```

- [ ] **Step 4: Run the tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_ablation.py -q`

Expected: PASS, 5 passed.

If `test_every_neutral_value_survives_its_own_validator` fails, `model_copy(update=...)` is bypassing validation — replace it with `Settings(**{**base.model_dump(), **overrides})` so the validators actually run, and re-run.

- [ ] **Step 5: Prove a neutralised rail actually stops binding**

This is the step that separates a mapping from a working switch. Append to `tests/domain/backtester/test_ablation.py`:

```python
@pytest.mark.asyncio
async def test_the_position_limit_binds_then_does_not(tmp_path):
    """The mapping is exercised, not asserted. A neutral value that failed to
    neutralise would otherwise show up as a quiet zero in an ablation result."""
    import pandas as pd

    from qat.domain.backtester.replay_session import ReplaySession
    from qat.domain.evaluation.refusals import load_risk_decisions, rail_of
    from qat.domain.strategies.swing import SwingStrategy

    def rising(seed: float) -> pd.DataFrame:
        index = pd.bdate_range("2026-01-01", periods=120, tz="UTC")
        closes = [seed + i * 0.5 for i in range(120)]
        return pd.DataFrame(
            {
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1_000_000.0] * 120,
            },
            index=index,
        )

    bars = {name: rising(100.0 + i) for i, name in enumerate(["AAA", "BBB", "CCC", "SPY"])}

    async def refusals_with(limit: int, directory) -> set[str]:
        settings = Settings(
            _env_file=None,
            data_dir=str(directory),
            execution_mode="auto",
            deployed_strategies="swing",
            autonomous_strategies="swing",
            max_concurrent_positions=limit,
        )
        session = ReplaySession(
            bars=bars, strategies=[SwingStrategy()], settings=settings,
            benchmark="SPY", warm_bars=60,
        )
        await session.run()
        rows = load_risk_decisions(directory)
        return {
            rail_of(r["reason"]) for r in rows if str(r["approved"]).lower() == "false"
        }

    bound = await refusals_with(1, tmp_path / "on")
    (tmp_path / "off").mkdir(parents=True, exist_ok=True)
    free = await refusals_with(RAILS["position_limit"]["max_concurrent_positions"], tmp_path / "off")

    assert "Position limit" in bound
    assert "Position limit" not in free
```

Create `tmp_path / "on"` before the first call. Run:

`& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_ablation.py -q`

Expected: PASS, 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/qat/domain/backtester/ablation.py tests/domain/backtester/test_ablation.py
git commit -m "Add the ablation switch, and refuse the rails it cannot neutralise"
```

---

### Task 5: The G1 verdict on disk

The manifest's `live_agreement` field must be derived, not typed. Four hand-maintained counts in this project were wrong in three days.

**Files:**
- Modify: `scripts/analysis/g1/run_g1.py`
- Test: none — this is a script writing a file, covered by Task 6's read of it.

**Interfaces:**
- Produces: `scripts/analysis/g1/g1_verdict.json`, shaped `{"created_at": str, "rails": {<rail name>: {"agreed": int, "live_only": int, "harness_only": int, "rate": float}}}`.

- [ ] **Step 1: Write the dump**

Add to `run_g1.py` beside the other constants:

```python
G1_VERDICT = _HERE / "g1_verdict.json"
```

And after `_print_verdict(...)` in `main`, when `--day` was not given:

```python
    if not args.day:
        G1_VERDICT.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "window": {"first": min(_day_of(r) for r in _frozen_rows()),
                               "last": max(_day_of(r) for r in _frozen_rows())},
                    "rails": {
                        rail.rail: {
                            "agreed": rail.agreed,
                            "live_only": rail.live_only,
                            "harness_only": rail.harness_only,
                            "rate": rail.agreement_rate,
                        }
                        for rail in verdict.rails
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
```

This requires holding the verdict in a variable rather than passing it inline, and `import json` at the top.

- [ ] **Step 2: Run it and check the file**

Run: `& '.\.venv\Scripts\python.exe' scripts\analysis\g1\run_g1.py --score-only`

Then: `Get-Content 'scripts\analysis\g1\g1_verdict.json'`

Expected: four rails, `Position limit` at rate 0.0, `Aggregate risk-at-stop cap` at 0.09.

- [ ] **Step 3: Commit**

```bash
git add scripts/analysis/g1/run_g1.py scripts/analysis/g1/g1_verdict.json
git commit -m "Write G1's verdict to disk so the manifest can derive it"
```

---

### Task 6: The run manifest

**Files:**
- Create: `src/qat/domain/backtester/manifest.py`
- Test: `tests/domain/backtester/test_manifest.py` (create)

**Interfaces:**
- Consumes: `RAILS`, `IMPERFECT`, `REGIME_RAIL` from Task 4; `g1_verdict.json` from Task 5; the run's `risk_decisions.csv` from Task 2.
- Produces:
  - `RailRecord` — `enabled: bool`, `bound_count: int`, `exercised: bool`, `live_agreement: str`, `caveat: str | None`
  - `build_manifest(...) -> RunManifest`
  - `RunManifest.write(path: Path) -> None`, `read_manifest(path: Path) -> RunManifest`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/backtester/test_manifest.py`:

```python
"""What a run may and may not be quoted as saying (W2 step 6)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from qat.domain.backtester.manifest import build_manifest, read_manifest


def _decisions(directory: Path, reasons: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "risk_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["timestamp", "symbol", "approved", "final_shares", "stop_price", "reason", "inputs"]
        )
        writer.writeheader()
        for reason in reasons:
            writer.writerow(
                {
                    "timestamp": "2026-07-31T15:00:00+00:00",
                    "symbol": "AAA",
                    "approved": "False",
                    "final_shares": "0.0",
                    "stop_price": "",
                    "reason": reason,
                    "inputs": "{}",
                }
            )


def test_a_rail_that_never_bound_reports_not_exercised(tmp_path):
    """Never `no difference`. A zero gets quoted and a caveat does not."""
    _decisions(tmp_path, ["already at the 10-position limit (10 held or pending)"])

    manifest = build_manifest(data_dir=tmp_path, disabled=[], universe=["AAA"], starting_equity=100_000.0)

    assert manifest.rails["position_limit"].exercised is True
    assert manifest.rails["position_limit"].bound_count == 1
    assert manifest.rails["sector_cap"].exercised is False
    assert manifest.rails["sector_cap"].bound_count == 0


def test_a_disabled_rail_is_recorded_as_disabled(tmp_path):
    _decisions(tmp_path, [])

    manifest = build_manifest(
        data_dir=tmp_path, disabled=["cost_to_risk"], universe=["AAA"], starting_equity=100_000.0
    )

    assert manifest.rails["cost_to_risk"].enabled is False
    assert manifest.rails["position_limit"].enabled is True


def test_the_imperfect_rails_carry_their_caveat(tmp_path):
    _decisions(tmp_path, [])

    manifest = build_manifest(
        data_dir=tmp_path, disabled=["cost_to_risk"], universe=["AAA"], starting_equity=100_000.0
    )

    assert "1R" in (manifest.rails["cost_to_risk"].caveat or "")
    assert manifest.rails["position_limit"].caveat is None


def test_it_round_trips(tmp_path):
    _decisions(tmp_path, ["aggregate risk-at-stop 5.01% is at or above the 5.00% cap"])
    manifest = build_manifest(data_dir=tmp_path, disabled=[], universe=["AAA"], starting_equity=100_000.0)

    manifest.write(tmp_path / "manifest.json")
    again = read_manifest(tmp_path / "manifest.json")

    assert again.rails["aggregate_risk_cap"].bound_count == 1
    assert again.starting_equity == 100_000.0
    assert again.code_commit


def test_the_manifest_names_the_fill_model_and_the_limitations(tmp_path):
    """Stated on every run, not buried in a footnote."""
    _decisions(tmp_path, [])

    manifest = build_manifest(data_dir=tmp_path, disabled=[], universe=["AAA"], starting_equity=100_000.0)

    assert manifest.fill_model["stop_wins_ambiguous_bar"] is True
    assert manifest.fill_model["entry"] == "next_open"
    assert any("survivorship" in limit.lower() for limit in manifest.stated_limitations)
    assert any("earnings" in limit.lower() for limit in manifest.stated_limitations)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_manifest.py -q`

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Map rail names to the labels `rail_of` produces**

`ablation.py` keys rails by a config-shaped name; `refusals.rail_of` returns a human label. The manifest needs both, and the mapping must live in one place. Add to `src/qat/domain/backtester/manifest.py`:

```python
# The ablation name on the left, `refusals.rail_of`'s label on the right. Two
# vocabularies meet here and nowhere else - one names a config knob, the other
# names what an operator calls the rail on a report.
_RAIL_LABELS: dict[str, str] = {
    "position_limit": "Position limit",
    "aggregate_risk_cap": "Aggregate risk-at-stop cap",
    "single_name_cap": "Single-name concentration cap",
    "sector_cap": "Sector concentration cap",
    "correlated_cluster": "Correlated-cluster cap",
    "gap_risk": "Gap-risk budget",
    "portfolio_es": "Portfolio ES limit",
    "cost_to_risk": "Cost-to-risk (trade too small)",
    "minimum_hold": "Minimum holding period",
    "time_stop": "Time stop",
    "churn_cap": "Weekly entry cap",
    "earnings_trim": "Earnings trim",
    "regime_gate": "Regime gate",
}
```

- [ ] **Step 4: Write the module**

Create `src/qat/domain/backtester/manifest.py`:

```python
"""What a run may and may not be quoted as saying (W2 step 6).

A result whose provenance is not recorded is a result nobody can reproduce, and
this project's whole argument is that figures must be derived rather than
remembered.

Three fields carry the scoping the operator approved on 13 August, after G1
showed that NO RAIL HAS A VALIDATED AGREEMENT RATE:

* `bound_count` - how often the rail bound in THIS run, derived from the run's
  own `risk_decisions.csv` through `refusals.rail_of`. The existing classifier,
  never a private copy: two derivations of "which rail bound" would eventually
  disagree, and an operator reading one while the other produced the number
  would have no way to tell which was right.
* `exercised` - `bound_count > 0`. A rail that never bound reports NOT
  EXERCISED, never "no difference".
* `live_agreement` - read from the verdict `run_g1.py` writes, not typed.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from qat.domain.backtester.ablation import IMPERFECT, RAILS, REGIME_RAIL
from qat.domain.evaluation.refusals import load_risk_decisions, rail_of

_G1_VERDICT = Path(__file__).resolve().parents[4] / "scripts" / "analysis" / "g1" / "g1_verdict.json"

_FILL_MODEL = {
    "stop_wins_ambiguous_bar": True,
    "gap_through_stop": "open",
    "gap_through_target": "target",
    "entry": "next_open",
    "stop_can_fire_on_entry_bar": True,
}

_STATED_LIMITATIONS = (
    "Survivorship: the universe is a static 2026 megacap snapshot, not a "
    "point-in-time index membership.",
    "The earnings rail is inert - NullEarningsCalendar, so M57's trim never "
    "fires and some entries are sized LARGER than live would size them.",
    "The fill model is pessimistic, so expectancy is a floor rather than an "
    "estimate.",
    "Daily bars only. Entry timing and fill rate are out of reach.",
    "The regime rail is nearly constant on daily bars - hysteresis and a "
    "20-bar refit make it far stickier than live's intraday reclassification.",
)


@dataclass(frozen=True, slots=True)
class RailRecord:
    enabled: bool
    bound_count: int
    exercised: bool
    live_agreement: str
    caveat: str | None = None


@dataclass(frozen=True, slots=True)
class RunManifest:
    created_at: str
    code_commit: str
    code_dirty: bool
    rails: dict[str, RailRecord]
    universe: tuple[str, ...]
    starting_equity: float
    fill_model: dict[str, object] = field(default_factory=lambda: dict(_FILL_MODEL))
    stated_limitations: tuple[str, ...] = _STATED_LIMITATIONS

    def write(self, path: Path) -> None:
        payload = asdict(self)
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def read_manifest(path: Path) -> RunManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RunManifest(
        created_at=raw["created_at"],
        code_commit=raw["code_commit"],
        code_dirty=raw["code_dirty"],
        rails={name: RailRecord(**record) for name, record in raw["rails"].items()},
        universe=tuple(raw["universe"]),
        starting_equity=float(raw["starting_equity"]),
        fill_model=raw["fill_model"],
        stated_limitations=tuple(raw["stated_limitations"]),
    )


def _commit() -> tuple[str, bool]:
    """The commit and whether the tree was dirty. Unknown rather than raising -
    a manifest is provenance, and failing to produce one must never stop a run
    that has already happened."""
    try:
        head = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        status = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        return head, bool(status)
    except (OSError, subprocess.SubprocessError):
        return "unknown", True


def _live_agreement() -> dict[str, str]:
    """G1's per-rail verdict, or `unvalidated` where it has none."""
    if not _G1_VERDICT.exists():
        return {}
    try:
        raw = json.loads(_G1_VERDICT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        label: f"{record['rate']:.0%} over {record['agreed'] + record['live_only'] + record['harness_only']} symbol-days"
        for label, record in (raw.get("rails") or {}).items()
    }


def build_manifest(
    *,
    data_dir: Path,
    disabled: Sequence[str],
    universe: Sequence[str],
    starting_equity: float,
) -> RunManifest:
    rows = load_risk_decisions(data_dir)
    bound: dict[str, int] = {}
    for row in rows:
        if str(row.get("approved", "")).strip().lower() == "true":
            continue
        label = rail_of(row.get("reason", ""))
        bound[label] = bound.get(label, 0) + 1

    agreement = _live_agreement()
    disabled_set = set(disabled)
    rails: dict[str, RailRecord] = {}
    for name in [*RAILS, REGIME_RAIL]:
        label = _RAIL_LABELS[name]
        count = bound.get(label, 0)
        rails[name] = RailRecord(
            enabled=name not in disabled_set,
            bound_count=count,
            exercised=count > 0,
            live_agreement=agreement.get(label, "unvalidated"),
            caveat=IMPERFECT.get(name),
        )

    commit, dirty = _commit()
    return RunManifest(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        code_commit=commit,
        code_dirty=dirty,
        rails=rails,
        universe=tuple(universe),
        starting_equity=starting_equity,
    )
```

Paste `_RAIL_LABELS` from Step 3 in at module level, above `RailRecord`.

- [ ] **Step 5: Run the tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_manifest.py -q`

Expected: PASS, 5 passed.

- [ ] **Step 6: Check the repo-root path**

`_G1_VERDICT` uses `parents[4]` from `src/qat/domain/backtester/manifest.py`. Verify with:

```bash
& '.\.venv\Scripts\python.exe' -c "from qat.domain.backtester.manifest import _G1_VERDICT; print(_G1_VERDICT, _G1_VERDICT.exists())"
```

Expected: the path ends `scripts\analysis\g1\g1_verdict.json` and prints `True`. Adjust the index if not.

- [ ] **Step 7: Commit**

```bash
git add src/qat/domain/backtester/manifest.py tests/domain/backtester/test_manifest.py
git commit -m "Record what each run may be quoted as saying"
```

---

### Task 7: The comparison, and the guard that suppresses a meaningless number

**Files:**
- Create: `src/qat/domain/backtester/run_comparison.py`
- Test: `tests/domain/backtester/test_run_comparison.py` (create)

**Interfaces:**
- Consumes: `RunManifest`, `read_manifest` from Task 6; `closed_trades.csv` from Task 2.
- Produces: `compare_runs(baseline_dir: Path, ablated_dir: Path, rail: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/backtester/test_run_comparison.py`:

```python
"""Comparing two runs, and refusing to when the comparison means nothing."""

from __future__ import annotations

import csv
from pathlib import Path

from qat.domain.backtester.manifest import build_manifest
from qat.domain.backtester.run_comparison import compare_runs


def _run(directory: Path, *, reasons: list[str], trades: list[tuple[str, float]], disabled: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "risk_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "symbol", "approved", "reason"])
        writer.writeheader()
        for reason in reasons:
            writer.writerow(
                {"timestamp": "2026-07-31T15:00:00+00:00", "symbol": "AAA", "approved": "False", "reason": reason}
            )
    with (directory / "closed_trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "r_multiple"])
        writer.writeheader()
        for symbol, r in trades:
            writer.writerow({"symbol": symbol, "r_multiple": r})
    build_manifest(
        data_dir=directory, disabled=disabled, universe=["AAA"], starting_equity=100_000.0
    ).write(directory / "manifest.json")


def test_an_unexercised_rail_reports_nothing_to_compare(tmp_path):
    """The heart of the design. A zero gets quoted and a caveat does not, so
    the difference figure is suppressed rather than printed beside a warning."""
    _run(tmp_path / "base", reasons=[], trades=[("AAA", 1.0)], disabled=[])
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 1.4)], disabled=["sector_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "NOT EXERCISED" in report
    assert "measures nothing" in report
    assert "1.4" not in report


def test_an_exercised_rail_reports_the_difference(tmp_path):
    _run(
        tmp_path / "base",
        reasons=["Technology already holds $31,000, at or above the 30% sector cap"],
        trades=[("AAA", 1.0), ("BBB", -1.0)],
        disabled=[],
    )
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 1.0), ("BBB", -1.0), ("CCC", 2.0)], disabled=["sector_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "NOT EXERCISED" not in report
    assert "3" in report  # the ablated arm took one more trade


def test_the_report_states_that_no_rail_is_validated_against_live(tmp_path):
    """The scoping the operator approved: a result says what a rail costs
    INSIDE the harness, and the report says so rather than a reader
    remembering it."""
    _run(
        tmp_path / "base",
        reasons=["Technology already holds $31,000, at or above the 30% sector cap"],
        trades=[("AAA", 1.0)],
        disabled=[],
    )
    _run(tmp_path / "abl", reasons=[], trades=[("AAA", 1.0)], disabled=["sector_cap"])

    report = compare_runs(tmp_path / "base", tmp_path / "abl", "sector_cap")

    assert "inside the harness" in report
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_run_comparison.py -q`

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

Create `src/qat/domain/backtester/run_comparison.py`:

```python
"""Did the rail help? - asked of two runs of the harness (W2 step 6).

It leads with a guard rather than a number. If the rail never bound in the
BASELINE run, there was nothing for its removal to change, and the difference
is suppressed entirely rather than printed as a zero beside a caveat: a zero
gets quoted and a caveat does not.

The claim is scoped in the report itself. As of 13 August no rail in the G1
window has a validated agreement rate, so a difference measured here says what
a rail costs INSIDE the harness - never what it costs the live system.
"""

from __future__ import annotations

import csv
from pathlib import Path

from qat.domain.backtester.manifest import RunManifest, read_manifest

_SCOPE = (
    "Measured inside the harness. No rail has a validated live agreement rate, "
    "so this is what the rail costs THIS INSTRUMENT, not what it costs the "
    "live book."
)


def _trades(directory: Path) -> list[dict[str, str]]:
    path = directory / "closed_trades.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _r_total(rows: list[dict[str, str]]) -> float:
    total = 0.0
    for row in rows:
        try:
            total += float(row.get("r_multiple") or 0.0)
        except ValueError:
            continue
    return total


def _wins(rows: list[dict[str, str]]) -> int:
    won = 0
    for row in rows:
        try:
            won += 1 if float(row.get("r_multiple") or 0.0) > 0 else 0
        except ValueError:
            continue
    return won


def _summarise(name: str, manifest: RunManifest, rows: list[dict[str, str]]) -> str:
    total = _r_total(rows)
    wins = _wins(rows)
    rate = f"{wins / len(rows):.0%}" if rows else "n/a"
    mean = f"{total / len(rows):+.2f}R" if rows else "n/a"
    return (
        f"{name:<10}{len(rows):>8} trades{rate:>8} win{mean:>10} mean{total:>10.2f}R total"
        f"   [{manifest.code_commit}{'*' if manifest.code_dirty else ''}]"
    )


def compare_runs(baseline_dir: Path, ablated_dir: Path, rail: str) -> str:
    baseline = read_manifest(baseline_dir / "manifest.json")
    ablated = read_manifest(ablated_dir / "manifest.json")

    record = baseline.rails.get(rail)
    if record is None:
        return f"{rail!r} is not a rail this manifest knows."

    lines = [f"=== {rail} ===", ""]

    if not record.exercised:
        lines += [
            f"NOT EXERCISED - {rail} never bound in the baseline run.",
            "This comparison measures nothing about that rail.",
            "",
            "Ablating a rail that never binds cannot produce evidence about it. "
            "Either the window does not reach the condition the rail governs, or "
            "the harness cannot reach it by construction - the position limit is "
            "the known case.",
        ]
        return "\n".join(lines)

    lines += [
        _summarise("baseline", baseline, _trades(baseline_dir)),
        _summarise("ablated", ablated, _trades(ablated_dir)),
        "",
        f"{rail} bound {record.bound_count} time(s) in the baseline.",
        f"Live agreement for this rail: {record.live_agreement}.",
    ]
    if record.caveat:
        lines.append(f"Caveat: neutralising this rail is imperfect - it {record.caveat}.")
    lines += ["", _SCOPE]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_run_comparison.py -q`

Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/backtester/run_comparison.py tests/domain/backtester/test_run_comparison.py
git commit -m "Compare two runs, and suppress the number when the rail never bound"
```

---

### Task 8: The runner

**Files:**
- Create: `scripts/research/run_ablation.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the script**

Create `scripts/research/run_ablation.py`:

```python
"""Run the harness twice - all rails on, then one rail off - and compare.

    Set-Location "C:\\Claude Programming"
    & ".\\.venv\\Scripts\\python.exe" scripts\\research\\run_ablation.py --rail cost_to_risk

**RUN THROUGH POWERSHELL, NEVER BASH**, and note that this script passes its
own `data_dir`: `Settings(_env_file=None).data_dir` resolves to the LIVE data
directory, which is how a probe wrote a row for a symbol named AAA into the
live record on 12 August.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.backtester.ablation import REGIME_RAIL, ablated_settings  # noqa: E402
from qat.domain.backtester.manifest import build_manifest  # noqa: E402
from qat.domain.backtester.replay_session import ReplaySession  # noqa: E402
from qat.domain.backtester.run_comparison import compare_runs  # noqa: E402
from qat.domain.strategies.swing import SwingStrategy  # noqa: E402

BARS_CACHE = _REPO / "scripts" / "analysis" / "g1" / "bars"
BENCHMARK = "SPY"


def _cached_bars() -> dict[str, pd.DataFrame]:
    """The G1 cache, so an ablation and the gate rest on identical inputs."""
    out: dict[str, pd.DataFrame] = {}
    for path in sorted(BARS_CACHE.glob("*.csv")):
        frame = pd.read_csv(path, parse_dates=["ts"])
        frame = frame.set_index(pd.DatetimeIndex(frame["ts"])).drop(columns=["ts"])
        # `run_g1.py` writes `symbol.replace('/', '-')`, and no symbol in this
        # universe contains a slash - BRK.B is stored as `BRK.B.csv` - so the
        # stem is the symbol unchanged.
        out[path.stem] = frame[["open", "high", "low", "close", "volume"]]
    return out


async def _one(directory: Path, disabled: list[str], bars: dict[str, pd.DataFrame]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    base = Settings(
        _env_file=None,
        data_dir=str(directory),
        execution_mode="auto",
        deployed_strategies="swing",
        autonomous_strategies="swing",
    )
    settings = ablated_settings(base, disabled)
    session = ReplaySession(
        bars=bars,
        strategies=[SwingStrategy()],
        settings=settings,
        benchmark=BENCHMARK,
        warm_bars=120,
    )
    if REGIME_RAIL in disabled:
        # The one rail with no knob: leaving the engine unstarted holds
        # RiskEngine.regime_scalar at its 1.0 default.
        session.regime_engine.start = _noop  # type: ignore[method-assign]
        session.regime_engine.stop = _noop  # type: ignore[method-assign]
    await session.run()
    build_manifest(
        data_dir=directory,
        disabled=disabled,
        universe=sorted(bars),
        starting_equity=100_000.0,
    ).write(directory / "manifest.json")


async def _noop() -> None:
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ablate one rail and compare")
    parser.add_argument("--rail", required=True, help="the rail to switch off")
    parser.add_argument("--out", default=None, help="where to write both runs")
    args = parser.parse_args()

    root = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="ablation-"))
    bars = _cached_bars()
    print(f"universe   : {len(bars)} symbols from the G1 cache")
    print(f"output     : {root}")

    print("baseline (all rails on)...")
    await _one(root / "baseline", [], bars)
    print(f"ablated ({args.rail} off)...")
    await _one(root / "ablated", [args.rail], bars)

    print()
    print(compare_runs(root / "baseline", root / "ablated", args.rail))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: Run it on a rail that binds**

Run: `& '.\.venv\Scripts\python.exe' scripts\research\run_ablation.py --rail cost_to_risk`

Expected: two runs, then a comparison naming the trade counts and the scope line.

- [ ] **Step 3: Run it on the rail that cannot bind, and confirm the guard fires**

Run: `& '.\.venv\Scripts\python.exe' scripts\research\run_ablation.py --rail position_limit`

Expected: `NOT EXERCISED - position_limit never bound in the baseline run.` This is the correct result on the G1 window and the reason the guard exists.

- [ ] **Step 4: Commit**

```bash
git add scripts/research/run_ablation.py
git commit -m "Add the ablation runner"
```

---

### Task 9: A test that the harness starts every engine the live app starts

The regime rail was dead for the whole G1 window because `ReplaySession` never started the `RiskEngine`. Nothing errored; the rail held its permissive default. This is what stops the next one.

**A compromise, stated rather than glossed.** The spec asked for this to be derived from the live runtime's own engine-registration list rather than from a hand-written one. It is not: `ReplaySession` holds a deliberately different set of engines from the live runtime — no kill-switch engine, no reconciliation monitor, no session controller — so the runtime's list is not the right oracle for it. The list below is hand-written, which is the weaker form. It still converts "somebody must notice" into "a test fails", which is the whole gap that let the risk engine go unstarted; a genuinely derived check would need a shared registry that does not exist yet.

**Files:**
- Test: `tests/domain/backtester/test_replay_starts_every_engine.py` (create)

- [ ] **Step 1: Write the test**

```python
"""A production object wired but never started is a rail holding its default.

Measured 13 August: ReplaySession started four engines and omitted the risk
engine, whose `start` is the only place it subscribes to RegimeEvent. The
scalar held 1.0 for the whole G1 window while live varied 0.4/0.5/0.7/1.0, so
the harness sized up to 2.5x larger than the book it was compared against.
Nothing errored - which is why this needs a test rather than vigilance.
"""

from __future__ import annotations

import inspect

from qat.domain.backtester.replay_session import ReplaySession

# Engines ReplaySession holds that carry the Engine protocol's start/stop.
_MUST_START = (
    "self.oms.risk_engine.start",
    "self.ledger.start",
    "self.regime_engine.start",
    "self.engine.start",
    "self.bridge.start",
    "self.executor.start",
)


def test_every_engine_the_session_holds_is_started():
    source = inspect.getsource(ReplaySession.run)

    missing = [name for name in _MUST_START if name not in source]

    assert not missing, (
        f"ReplaySession.run does not start: {', '.join(missing)}. An engine that is "
        "constructed and never started holds its defaults silently - the risk engine "
        "did exactly that, and the regime rail was inert for the whole G1 window."
    )


def test_every_started_engine_is_also_stopped():
    source = inspect.getsource(ReplaySession.run)

    missing = [name.replace(".start", ".stop") for name in _MUST_START
               if name.replace(".start", ".stop") not in source]

    assert not missing, f"ReplaySession.run does not stop: {', '.join(missing)}"
```

- [ ] **Step 2: Run it**

Run: `& '.\.venv\Scripts\python.exe' -m pytest tests/domain/backtester/test_replay_starts_every_engine.py -q`

Expected: PASS, 2 passed — Tasks 1 and 2 having added the two missing lines.

- [ ] **Step 3: Full verification pass**

```bash
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' -m black --check .
& '.\.venv\Scripts\python.exe' -m mypy src
& '.\.venv\Scripts\python.exe' -m bandit -r src -q
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```

- [ ] **Step 4: Re-run G1 and record what moved**

The harness now records outcomes and corrects entry prices, so the gate's numbers may differ from the 13 August run.

Run: `& '.\.venv\Scripts\python.exe' scripts\analysis\g1\run_g1.py`

Compare against the recorded baseline — exact 6 · partial 2 · disjoint 12 · live-only 38 · harness-only 8 — and write whatever changed into the spec, **including if nothing changed.** The 13 August lesson was that a predicted change failing to appear is itself the finding.

- [ ] **Step 5: Commit**

```bash
git add tests/domain/backtester/test_replay_starts_every_engine.py docs/superpowers/specs/2026-08-13-ablation-switch-and-run-manifest-design.md
git commit -m "Test that every engine the session holds is started, and re-run the gate"
```

---

## Recorded, deliberately not built

Both change which trades the harness takes, so neither belongs in a step whose
purpose is to measure the harness as it stands.

* **The regime updates only when the benchmark's bar publishes.** `_one_day`
  iterates `self.bars`, and the regime engine reclassifies on SPY's
  `MarketDataEvent` - so every symbol ordered before SPY that day is evaluated
  against the PREVIOUS day's regime. Live has no such split. Publishing the
  benchmark first would close it.
* **The harness classifies one regime label for a whole window** (0.7 across
  G1) against live's 0.4 · 0.7 · 1.0. Daily bars through `HysteresisGate` with
  a 20-bar refit are far stickier than intraday reclassification. It makes the
  regime ablation measure one label rather than a varying one, and Task 6's
  manifest states it as a limitation rather than fixing it.
* **Intraday evaluation.** The spec's revisit trigger, declined 13 August, and
  still the thing that would make any of these numbers transferable to live.
