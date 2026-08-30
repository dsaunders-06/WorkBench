# Restored-Lot Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lot rebuilt after a restart carries the price it was sized against and the excursion it actually travelled, so `entry_slippage`, `mae_r` and `mfe_r` stop being permanently empty on every trade this system closes.

**Architecture:** `TradeLedger.restore_open_lot` gains three optional parameters. The bridge — the only component holding both the entry record and the bar history — supplies `reference_price` from `_Entry` and computes `worst_price`/`best_price` from the daily OHLC bars warm start already seeded. Nothing new is persisted.

**Tech Stack:** Python 3.12, pandas, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-30-restored-lot-diagnostics-design.md` (commit `d98d0c3`).

## Global Constraints

- **DO NOT PUSH.** Standing operator hold since 27 August. Commit locally as normal.
- **The local suite is the only verification.** All four checks, every task: `pytest`, `ruff`, `black`, `mypy src`, `bandit`.
- **The FULL suite, not the targeted one.** Item 22's three green tests hid a broken order path that the full suite found in 134 failures.
- **PowerShell** for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal`, including Python that only reads it or builds `Settings()`. The Bash sandbox serves a frozen snapshot and does not error.
- **Use the edit tool, which errors on a failed match.** A `str.replace` in a heredoc silently no-opped six times this week.
- `None` for `reference_price` means **UNKNOWN**, never the entry price — that would report zero slippage on a trade nobody measured.
- New parameters are **optional, defaulting to today's behaviour**, so untouched call sites are unchanged.
- Next milestone number: **M157**.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/qat/domain/performance/trades.py` | Owns `OpenLot` and lot restoration | Modify `restore_open_lot` (line 617) — three new optional parameters |
| `src/qat/domain/oms/signal_bridge.py` | Holds the entry record *and* the bar history | Modify `_LotStore` Protocol (line 95), add `_excursion_since`, modify `restore_open_lots` (line 653) |
| `tests/domain/performance/test_restored_lot_carries_its_diagnostics.py` | The structural guard and the consumer-level tests | Create |
| `tests/domain/oms/test_excursion_backfill.py` | The helper, the entry-day rule, the empty-buffer guard, the end-to-end wiring | Create |

---

### Task 1: `reference_price` reaches the restored lot

Closes Defect A. Independently shippable: it finishes work M156 started and left inert.

**Files:**
- Create: `tests/domain/performance/test_restored_lot_carries_its_diagnostics.py`
- Modify: `src/qat/domain/performance/trades.py:617-661`
- Modify: `src/qat/domain/oms/signal_bridge.py:95-104` (Protocol), `:695-702` (call site)

**Interfaces:**
- Produces: `TradeLedger.restore_open_lot(..., reference_price: float | None = None) -> bool`, relied on by Task 3.

- [ ] **Step 1: Write the structural guard and the consumer tests**

Create `tests/domain/performance/test_restored_lot_carries_its_diagnostics.py`:

```python
"""What a lot rebuilt after a restart must carry from the record behind it.

⚠️ THE FOURTH AND FIFTH FIELDS this record has lost across a restart - and the
THIRD was believed fixed. M33 lost `target_price`; M49 lost `strategy`; M44 lost
`reference_price`, and M44's fix on 28 August carried it onto the record, into
the file and back out again, then stopped one call short of the lot a
`ClosedTrade` is actually made from.

The guard below is anchored on SHAPE rather than on a list of names, because a
list of names is the thing that failed three times.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.oms.signal_bridge import _Entry
from qat.domain.performance.trades import OpenLot, TradeLedger

_BASE = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)


async def _ledger(tmp_path) -> TradeLedger:
    ledger = TradeLedger(EventBus(), tmp_path)
    await ledger.start()
    return ledger


async def _sell(ledger: TradeLedger, quantity: float, price: float, day: int) -> None:
    await ledger._on_fill(
        OrderFilledEvent(
            order_id=f"sell-{day}",
            symbol="AAA",
            side="sell",
            quantity=quantity,
            price=price,
            strategy="swing",
            ts=_BASE + timedelta(days=day),
        )
    )


def test_every_field_common_to_the_record_and_the_lot_can_be_restored() -> None:
    """⚠️ THE GUARD THAT WOULD HAVE CAUGHT THIS ON 28 AUGUST.

    A field can be added to the persisted record AND to the lot and still not
    travel between them, because a third thing - this function's signature -
    has to change too, and nothing checked that it did.

    Anchored on the shape, so the SIXTH field to be lost fails the build.
    `target_price` is correctly outside this set: it is on the record and not
    on the lot, so there is nothing for `restore_open_lot` to carry.
    """
    stored = set(_Entry.__dataclass_fields__)
    lot = set(OpenLot.__dataclass_fields__)
    restorable = set(inspect.signature(TradeLedger.restore_open_lot).parameters) - {"self"}

    lost = (stored & lot) - restorable

    assert not lost, (
        f"{sorted(lost)} is persisted on the entry record AND carried on the lot, but "
        f"restore_open_lot cannot accept it - so a restart rebuilds the lot without it "
        f"and every trade closed after a restart loses it silently. That is how M33, "
        f"M49 and M44 each went missing."
    )


@pytest.mark.asyncio
async def test_a_lot_opened_this_session_records_its_slippage(tmp_path) -> None:
    """⚠️ THE CONTROL. This path already worked on 28 August. A test green on
    both paths would have proved nothing about the one that was broken."""
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(
        OrderFilledEvent(
            order_id="buy-1",
            symbol="AAA",
            side="buy",
            quantity=20.0,
            price=50.0,
            strategy="swing",
            stop_price=45.0,
            reference_price=49.90,
            ts=_BASE,
        )
    )
    await _sell(ledger, 20.0, 55.0, day=16)

    trade = ledger.closed_trades("swing")[0]
    assert trade.reference_price == pytest.approx(49.90)
    assert trade.entry_slippage == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_a_lot_that_survived_a_restart_records_its_slippage(tmp_path) -> None:
    """⚠️ THE ONE THAT WAS BROKEN. With a ten-day minimum hold and a session
    most nights, this is the path EVERY trade this system closes takes."""
    ledger = await _ledger(tmp_path)
    assert ledger.restore_open_lot(
        symbol="AAA",
        quantity=20.0,
        price=50.0,
        stop_price=45.0,
        strategy="swing",
        opened_at=_BASE,
        reference_price=49.90,
    )
    await _sell(ledger, 20.0, 55.0, day=16)

    trade = ledger.closed_trades("swing")[0]
    assert trade.reference_price == pytest.approx(49.90)
    assert trade.entry_slippage == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_a_record_without_one_restores_as_unknown(tmp_path) -> None:
    """`None` means UNKNOWN. Falling back to the entry price would report ZERO
    slippage on a trade nobody measured - worse than an empty column, because it
    looks like a measurement. Every record written before 28 August is this."""
    ledger = await _ledger(tmp_path)
    assert ledger.restore_open_lot(
        symbol="AAA",
        quantity=20.0,
        price=50.0,
        stop_price=45.0,
        strategy="swing",
        opened_at=_BASE,
    )
    await _sell(ledger, 20.0, 55.0, day=16)

    trade = ledger.closed_trades("swing")[0]
    assert trade.reference_price is None
    assert trade.entry_slippage is None
```

- [ ] **Step 2: Run them and confirm they fail for the right reasons**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/performance/test_restored_lot_carries_its_diagnostics.py -v
```

Expected: `test_every_field_common_to_the_record_and_the_lot_can_be_restored` FAILS naming exactly `['reference_price']`. The two restart tests FAIL with `TypeError: restore_open_lot() got an unexpected keyword argument 'reference_price'`. **The control and the unknown-record test PASS** — that is what makes the others evidence.

- [ ] **Step 3: Add the parameter to `restore_open_lot`**

In `src/qat/domain/performance/trades.py`, change the signature at line 617 to add a seventh parameter after `opened_at`:

```python
        opened_at: datetime,
        reference_price: float | None = None,
    ) -> bool:
```

Append to its docstring, after the existing excursion paragraph:

```
        `reference_price` is the price the order was SIZED against, and `None`
        means UNKNOWN - never the entry price, which would report zero slippage
        on a trade nobody measured. M156 carried it onto the record, into the
        file and back out again, and stopped here: the parameter did not exist,
        so the bridge could not pass it and every restored lot got `None`.
```

And in the `OpenLot(...)` construction, add one line beside the excursion seeds:

```python
                entry_cost=self._fill_cost(quantity, price),
                reference_price=reference_price,
                worst_price=price,
                best_price=price,
```

- [ ] **Step 4: Update the `_LotStore` Protocol**

In `src/qat/domain/oms/signal_bridge.py`, the Protocol at line 95 must match, or the bridge's own type contract states something false:

```python
    def restore_open_lot(
        self,
        symbol: str,
        quantity: float,
        price: float,
        stop_price: float | None,
        strategy: str | None,
        opened_at: datetime,
        reference_price: float | None = None,
    ) -> bool: ...
```

- [ ] **Step 5: Pass it at the call site**

In `restore_open_lots`, add one line to the `ledger.restore_open_lot(...)` call:

```python
                opened_at=entry.opened_at,
                reference_price=entry.reference_price,
            ):
```

- [ ] **Step 6: Run the new tests and confirm all four pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/performance/test_restored_lot_carries_its_diagnostics.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Run the FULL suite and the three static checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

Expected: no failures, no new skips. If anything fails, **read mypy's output first** — on item 22 it had already named the cause while three targeted tests stayed green.

- [ ] **Step 8: Commit**

```bash
git add tests/domain/performance/test_restored_lot_carries_its_diagnostics.py src/qat/domain/performance/trades.py src/qat/domain/oms/signal_bridge.py
```

```bash
git commit -m "M157: reference_price now reaches the lot, which is where M156 stopped"
```

---

### Task 2: The excursion helper

A pure read of the bar frame, with no wiring. Reviewable on its own: the entry-day rule either holds or it does not.

**Files:**
- Create: `tests/domain/oms/test_excursion_backfill.py`
- Modify: `src/qat/domain/oms/signal_bridge.py` — add `_excursion_since` immediately above `restore_open_lots` (currently line 653)

**Interfaces:**
- Consumes: `self.bars` (`MultiSymbolAggregator`), which exposes `frame_if_present`, `interval_seconds` and `tz`.
- Produces: `SignalToOrderBridge._excursion_since(symbol: str, opened_at: datetime) -> tuple[float | None, float | None, int]`, used by Task 3.

- [ ] **Step 1: Write the helper's tests, including the planted violation**

Create `tests/domain/oms/test_excursion_backfill.py`:

```python
"""Excursion recovered from bars a restart cannot destroy (M44's other half).

`worst_price` and `best_price` EVOLVE over a trade's life, so persisting them at
open would restore a stale excursion - which is why M44's other half stayed open.
They are not persisted at all. They are recomputed at restore from the daily OHLC
bars warm start has already seeded into the bridge's own aggregator: the one whose
comment calls it "the most load-bearing of the three", because the ATR that sets
every stop distance comes from it.

⚠️ THE ENTRY DAY'S OWN BAR IS EXCLUDED, and that is the load-bearing rule. It
holds prices from before the position existed. Folding it in would attribute to
the trade a low it never experienced, which is the fabrication
`restore_open_lot`'s docstring already forbids. Understating a diagnostic is
acceptable; inventing one is not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from qat.data.bars import BAR_COLUMNS
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.data.broker.mock_broker import MockBroker
from qat.config import Settings

# ⚠️ SYDNEY, NOT UTC, and this is not cosmetic. The real record reads
# "2026-08-24T15:19:36.392342+10:00". Written as UTC instead, the same clock
# time is already 25 August in Sydney, the entry day shifts by one, and the
# rule then excludes the WRONG bar - which is how this test data was wrong on
# first writing. The daily boundary is local midnight on the exchange (M111).
_OPENED = datetime(2026, 8, 24, 15, 19, 36, tzinfo=ZoneInfo("Australia/Sydney"))


def _bridge(tmp_path, ledger=None, broker=None) -> SignalToOrderBridge:
    """⚠️ `bar_interval_seconds` AND `bar_tz` MUST BE PASSED EXPLICITLY.

    `SignalToOrderBridge.__init__` defaults the interval to 60.0, while
    `Settings.bar_interval_seconds` defaults to 86,400 and `runtime.py` passes
    that plus the market's timezone. A fixture that omits them builds
    SIXTY-SECOND bars, and then "the entry day's boundary" is really the entry
    MINUTE's boundary.

    The entry-day test below would still pass under that mistake, because bars
    a day apart are also a minute apart - green for a reason that has nothing to
    do with the rule being tested. Mirror production or the test measures
    nothing.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        broker or MockBroker(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
    )
    return SignalToOrderBridge(
        bus,
        oms,
        settings=settings,
        trade_ledger=ledger,
        bar_interval_seconds=settings.bar_interval_seconds,
        bar_tz=ZoneInfo("Australia/Sydney"),
    )


def test_the_bridge_in_production_keeps_daily_bars() -> None:
    """The rule above says "the entry DAY's bar". That is only true while the
    shipped interval is a day, and nothing else in the suite pins it."""
    assert Settings(_env_file=None).bar_interval_seconds == 86_400.0


def _seed_daily(bridge: SignalToOrderBridge, symbol: str, rows: list[tuple[str, float, float]]) -> None:
    """rows are (iso date, low, high). Open and close sit between them."""
    frame = pd.DataFrame(
        [
            {
                "ts": pd.Timestamp(day, tz="UTC"),
                "open": (low + high) / 2,
                "high": high,
                "low": low,
                "close": (low + high) / 2,
                "volume": 1000.0,
            }
            for day, low, high in rows
        ],
        columns=list(BAR_COLUMNS),
    )
    bridge.bars.seed(symbol, frame)


def test_the_excursion_comes_from_the_bars_after_the_entry_day(tmp_path) -> None:
    bridge = _bridge(tmp_path)
    _seed_daily(
        bridge,
        "AAA",
        [("2026-08-24", 49.0, 51.0), ("2026-08-25", 46.0, 52.0), ("2026-08-26", 47.0, 58.0)],
    )

    worst, best, bars = bridge._excursion_since("AAA", _OPENED)

    assert worst == pytest.approx(46.0)
    assert best == pytest.approx(58.0)
    assert bars == 2


def test_the_entry_days_own_bar_is_excluded(tmp_path) -> None:
    """⚠️ THE PLANTED VIOLATION. The entry day carries a low of 20.0 and a high
    of 99.0 - neither of which the position was open for, because it opened at
    15:19:36 that afternoon. Asserting the absence of a bad value alone would
    report the same clean result whether the rule works or the scan has gone
    blind, so the value that must not appear is planted where it would show."""
    bridge = _bridge(tmp_path)
    _seed_daily(
        bridge,
        "AAA",
        [("2026-08-24", 20.0, 99.0), ("2026-08-25", 46.0, 52.0), ("2026-08-26", 47.0, 58.0)],
    )

    worst, best, bars = bridge._excursion_since("AAA", _OPENED)

    assert worst == pytest.approx(46.0), "the entry day's low reached the excursion"
    assert best == pytest.approx(58.0), "the entry day's high reached the excursion"
    assert bars == 2


def test_a_symbol_with_no_bars_after_its_entry_day_reports_nothing(tmp_path) -> None:
    """Opened today, restarted today. Honest: there is nothing to measure yet."""
    bridge = _bridge(tmp_path)
    _seed_daily(bridge, "AAA", [("2026-08-24", 49.0, 51.0)])

    assert bridge._excursion_since("AAA", _OPENED) == (None, None, 0)


def test_a_symbol_the_aggregator_has_never_seen_reports_nothing(tmp_path) -> None:
    """⚠️ Warm start catches its own exceptions and continues - "a cold start
    beats no application" - so empty buffers are a live possibility, not a
    theoretical one. And this must not CREATE an aggregator by asking."""
    bridge = _bridge(tmp_path)

    assert bridge._excursion_since("NEVERSEEN", _OPENED) == (None, None, 0)
    assert bridge.bars.frame_if_present("NEVERSEEN") is None, (
        "asking about a symbol must not start tracking it"
    )
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_excursion_backfill.py -v
```

Expected: all five FAIL with `AttributeError: 'SignalToOrderBridge' object has no attribute '_excursion_since'`.

- [ ] **Step 3: Add the helper**

In `src/qat/domain/oms/signal_bridge.py`, immediately above `async def restore_open_lots`, add:

```python
    def _excursion_since(
        self, symbol: str, opened_at: datetime
    ) -> tuple[float | None, float | None, int]:
        """How far a held position travelled, from the bars rather than from a
        file (M44's other half).

        `worst_price` and `best_price` EVOLVE, so persisting them at open would
        restore a stale excursion - which is why this half stayed open. Nothing
        is persisted: the daily OHLC bars warm start seeded into this
        aggregator already contain the answer, and they cannot go stale.

        It is also the better instrument. The feed is polled every 60 seconds,
        so a six-hour session is sampled around 360 times and cannot see an
        extreme that fell between two samples. A bar's high and low are the
        extremes of every trade.

        ⚠️ THE ENTRY DAY'S OWN BAR IS EXCLUDED. It holds prices from before the
        position existed, and attributing those to the trade is the fabrication
        `restore_open_lot`'s docstring forbids. The cost is genuine same-day
        excursion, which on a ten-to-thirty-day hold at daily granularity is
        small and always in the safe direction. Bars from the restore day
        onward need no such care - every price in them was while held.

        `frame_if_present`, not `frame`: a read-only caller must not be able to
        start tracking a symbol merely by asking about it.

        ✅ **Why the boundary comparison is exact.** `BarAggregator.seed` stamps
        every bar as `floor_to_interval(as_utc(vendor_ts), interval, tz)` - the
        same function, interval and timezone used here. So both sides of the
        comparison are already floored to the same grid, and it does not matter
        whether the vendor timestamps a daily row at local midnight or at UTC
        midnight: both land on the same boundary. This is why the interval and
        tz are read off `self.bars` rather than assumed.
        """
        frame = self.bars.frame_if_present(symbol)
        if frame is None or frame.empty:
            return None, None, 0
        entry_day = floor_to_interval(opened_at, self.bars.interval_seconds, self.bars.tz)
        after = frame[pd.to_datetime(frame["ts"], utc=True) > entry_day.astimezone(UTC)]
        if after.empty:
            return None, None, 0
        return float(after["low"].min()), float(after["high"].max()), len(after)
```

Add the imports it needs. `pd` and `datetime` are already imported; confirm `UTC` is on the `datetime` import line and add `floor_to_interval`:

```python
from qat.data.bars import floor_to_interval
```

- [ ] **Step 4: Run the tests and confirm all five pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_excursion_backfill.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run the FULL suite and the three static checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 6: Commit**

```bash
git add tests/domain/oms/test_excursion_backfill.py src/qat/domain/oms/signal_bridge.py
```

```bash
git commit -m "M157: the excursion is in the bars, so stop trying to persist it"
```

---

### Task 3: Wire the backfill, and count what it did

**Files:**
- Modify: `src/qat/domain/performance/trades.py` — `restore_open_lot` gains `worst_price` and `best_price`
- Modify: `src/qat/domain/oms/signal_bridge.py` — `_LotStore` Protocol, and `restore_open_lots` passes them and logs a count
- Modify: `tests/domain/oms/test_excursion_backfill.py` — add the end-to-end wiring tests

**Interfaces:**
- Consumes: `_excursion_since` from Task 2; `restore_open_lot(..., reference_price=...)` from Task 1.
- Produces: `restore_open_lot(..., worst_price: float | None = None, best_price: float | None = None)`.

- [ ] **Step 1: Write the end-to-end tests**

Append to `tests/domain/oms/test_excursion_backfill.py`:

```python
@pytest.mark.asyncio
async def test_a_restored_lot_carries_the_excursion_from_its_bars(tmp_path) -> None:
    """⚠️ AT THE CONSUMER. `mae_r` and `mfe_r` are what M44 cannot read, and a
    test that stops at the lot cannot tell whether they arrive. Item 59's six
    store tests all stayed green when the caller was deleted."""
    import json

    from qat.data.broker.adapter import Position
    from qat.domain.performance.trades import TradeLedger

    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "OLD": {
                    # ⚠️ +10:00, matching the real record. As UTC this is
                    # already 25 August in Sydney and the entry day shifts.
                    "opened_at": "2026-08-24T15:19:36+10:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "target_price": 60.0,
                    "strategy": "swing",
                    "reference_price": 49.90,
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position(symbol="OLD", quantity=20.0, avg_price=50.0)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    bridge = SignalToOrderBridge(
        bus,
        oms,
        settings=settings,
        trade_ledger=ledger,
        # ⚠️ Production values, NOT the constructor defaults. See `_bridge` above:
        # the constructor defaults to 60-second bars and this rule is about days.
        bar_interval_seconds=settings.bar_interval_seconds,
        bar_tz=ZoneInfo("Australia/Sydney"),
    )
    _seed_daily(
        bridge,
        "OLD",
        [("2026-08-24", 20.0, 99.0), ("2026-08-25", 45.5, 52.0), ("2026-08-26", 47.0, 59.0)],
    )

    await bridge.restore_open_lots()

    lot = ledger.open_lots("OLD")[0]
    assert lot.reference_price == pytest.approx(49.90), "Task 1's field must still arrive"
    assert lot.worst_price == pytest.approx(45.5)
    assert lot.best_price == pytest.approx(59.0)
    assert lot.worst_price != pytest.approx(20.0), "the entry day's bar reached a real lot"


@pytest.mark.asyncio
async def test_a_restored_lot_without_bars_starts_at_the_entry_price(tmp_path) -> None:
    """The guard. Warm start can fail and the app continues by design, so this
    is the shape an empty buffer takes - and it must be today's behaviour
    exactly, not a crash and not a fabricated excursion."""
    import json

    from qat.data.broker.adapter import Position
    from qat.domain.performance.trades import TradeLedger

    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "OLD": {
                    # ⚠️ +10:00, matching the real record. As UTC this is
                    # already 25 August in Sydney and the entry day shifts.
                    "opened_at": "2026-08-24T15:19:36+10:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "strategy": "swing",
                }
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    broker = MockBroker(seed=1)
    broker._positions["OLD"] = Position(symbol="OLD", quantity=20.0, avg_price=50.0)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    bridge = SignalToOrderBridge(
        bus,
        oms,
        settings=settings,
        trade_ledger=ledger,
        # ⚠️ Production values, NOT the constructor defaults. See `_bridge` above:
        # the constructor defaults to 60-second bars and this rule is about days.
        bar_interval_seconds=settings.bar_interval_seconds,
        bar_tz=ZoneInfo("Australia/Sydney"),
    )

    await bridge.restore_open_lots()

    lot = ledger.open_lots("OLD")[0]
    assert lot.worst_price == pytest.approx(50.0)
    assert lot.best_price == pytest.approx(50.0)
    assert lot.reference_price is None


@pytest.mark.asyncio
async def test_the_backfill_reports_a_count(tmp_path, caplog) -> None:
    """⚠️ A COUNT, NOT AN ADJECTIVE - M154's shape. M151 asserted a suppression
    that never reached the log, 678 claimed against 774 still present. A line
    with no number cannot be checked against anything."""
    import json
    import logging

    from qat.data.broker.adapter import Position
    from qat.domain.performance.trades import TradeLedger

    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "WITH": {
                    # ⚠️ +10:00, matching the real record. As UTC this is
                    # already 25 August in Sydney and the entry day shifts.
                    "opened_at": "2026-08-24T15:19:36+10:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "strategy": "swing",
                },
                "WITHOUT": {
                    # ⚠️ +10:00, matching the real record. As UTC this is
                    # already 25 August in Sydney and the entry day shifts.
                    "opened_at": "2026-08-24T15:19:36+10:00",
                    "price": 50.0,
                    "stop_price": 45.0,
                    "strategy": "swing",
                },
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    ledger = TradeLedger(bus, tmp_path, settings=settings)
    await ledger.start()
    broker = MockBroker(seed=1)
    broker._positions["WITH"] = Position(symbol="WITH", quantity=20.0, avg_price=50.0)
    broker._positions["WITHOUT"] = Position(symbol="WITHOUT", quantity=20.0, avg_price=50.0)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus)
    bridge = SignalToOrderBridge(
        bus,
        oms,
        settings=settings,
        trade_ledger=ledger,
        # ⚠️ Production values, NOT the constructor defaults. See `_bridge` above:
        # the constructor defaults to 60-second bars and this rule is about days.
        bar_interval_seconds=settings.bar_interval_seconds,
        bar_tz=ZoneInfo("Australia/Sydney"),
    )
    _seed_daily(bridge, "WITH", [("2026-08-24", 49.0, 51.0), ("2026-08-25", 46.0, 58.0)])

    with caplog.at_level(logging.INFO):
        await bridge.restore_open_lots()

    line = next(m for m in caplog.messages if "Excursion backfilled" in m)
    assert "on 1 of 2" in line
    assert "1 had no bars" in line
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_excursion_backfill.py -v
```

Expected: the three new tests FAIL — the first two on the excursion assertions (worst/best are still the entry price), the third on `StopIteration` because no such line is logged.

- [ ] **Step 3: Add the two parameters to `restore_open_lot`**

In `src/qat/domain/performance/trades.py`, extend the signature:

```python
        reference_price: float | None = None,
        worst_price: float | None = None,
        best_price: float | None = None,
    ) -> bool:
```

Replace the existing excursion paragraph in its docstring with:

```
        The excursion fields fall back to the entry price when the caller has
        nothing better, which understates MAE and MFE rather than inventing
        them. The bridge supplies them from daily bars where it can - see
        `_excursion_since` - and that is measurement from the same instrument
        the stop distance already rests on, not fabrication.
```

And in the `OpenLot(...)` construction:

```python
                worst_price=worst_price if worst_price is not None else price,
                best_price=best_price if best_price is not None else price,
```

- [ ] **Step 4: Update the `_LotStore` Protocol to match**

```python
        reference_price: float | None = None,
        worst_price: float | None = None,
        best_price: float | None = None,
    ) -> bool: ...
```

- [ ] **Step 5: Wire it in `restore_open_lots` and count**

Before the `for position in positions:` loop, add two counters alongside the existing lists:

```python
        backfilled: list[str] = []
        no_bars: list[str] = []
```

Inside the loop, immediately before the `if ledger.restore_open_lot(` call:

```python
            worst, best, bar_count = self._excursion_since(position.symbol, entry.opened_at)
```

Extend the call:

```python
                reference_price=entry.reference_price,
                worst_price=worst,
                best_price=best,
            ):
                restored.append(position.symbol)
                (backfilled if bar_count else no_bars).append(position.symbol)
```

After the existing `if restored:` block, add:

```python
        if restored:
            # A COUNT, not an adjective (M154). Warm start catches its own
            # exceptions and continues, so empty buffers are a live
            # possibility - and when that happens every lot lands in `no_bars`
            # and this line says so, rather than the excursion quietly
            # reverting to the entry price the way it did until M157.
            logger.info(
                "Excursion backfilled from daily bars on %d of %d restored lot(s); %d had no "
                "bars after their entry day and start at the entry price, which understates "
                "both MAE and MFE.",
                len(backfilled),
                len(restored),
                len(no_bars),
            )
```

- [ ] **Step 6: Run the file and confirm all eight pass**

```bash
.venv/Scripts/python.exe -m pytest tests/domain/oms/test_excursion_backfill.py -v
```

Expected: 8 passed.

- [ ] **Step 7: Run the FULL suite and the three static checks**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 8: Commit**

```bash
git add src/qat/domain/performance/trades.py src/qat/domain/oms/signal_bridge.py tests/domain/oms/test_excursion_backfill.py
```

```bash
git commit -m "M157: a restored lot now knows how far it travelled"
```

---

### Task 4: Record it, and say what is still unproven

**Files:**
- Modify: `docs/HANDOFF.md` — item 7 (M44) in "Turns an ordinary market event into a loss"
- Modify: `src/qat/version.py` — M157 entry

- [ ] **Step 1: Update item 7 in `docs/HANDOFF.md`**

Under the existing `⚠️ STILL OPEN: worst_price and best_price` block, replace it with:

```markdown
   ✅ **BOTH HALVES DONE — M157, 30 August.** And a second defect was found in
   the first: **M156's `reference_price` never reached the lot.** It was carried
   onto `_Entry`, persisted, and read back — and `restore_open_lot` had no such
   parameter, so the rebuilt lot got `None` and `entry_slippage` was still
   empty on every trade closed after a restart, which is every trade. M156's
   five tests pin the record and the file; none asked the consumer.

   `worst_price` and `best_price` are **not persisted**. They are recomputed at
   restore from the daily bars warm start already seeds, so they cannot go
   stale, and the ten positions held on 30 August recover their excursion back
   to their entry days. The entry day's own bar is excluded: it holds prices
   from before the position existed.

   ⚠️ **UNPROVEN UNTIL A TRADE CLOSES.** Every measurement above is from the
   suite. The check is the first trade opened and closed under M157, and it
   must survive a RESTART before it counts — losing it at restart is the whole
   defect. The six existing rows stay empty and always will.
```

- [ ] **Step 2: Add the M157 entry to `src/qat/version.py` and bump the milestone**

Add the narrative entry following the shape of the M156 block above it — what changed, that the excursion is derived rather than stored, and that the guard is anchored on shape. Then bump the constant at line 1167:

```python
MILESTONE = "M157"
```

- [ ] **Step 3: Confirm the milestone reports M157**

```bash
.venv/Scripts/python.exe -c "from qat.version import MILESTONE; print(MILESTONE)"
```

Expected: `M157`.

- [ ] **Step 4: Run the FULL suite and all four checks one final time**

```bash
.venv/Scripts/python.exe -m pytest -q
```

```bash
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m black --check . && .venv/Scripts/python.exe -m mypy src && .venv/Scripts/python.exe -m bandit -q -r src
```

- [ ] **Step 5: Confirm the guard actually fails when the defect returns**

⚠️ **A test never seen to fail is not evidence.** Temporarily delete `reference_price` from `restore_open_lot`'s signature, run the guard, confirm it fails naming that field, then restore the line.

```bash
.venv/Scripts/python.exe -m pytest tests/domain/performance/test_restored_lot_carries_its_diagnostics.py::test_every_field_common_to_the_record_and_the_lot_can_be_restored -v
```

Expected while broken: FAIL naming `['reference_price']`. Confirm `git diff` is empty afterwards.

- [ ] **Step 6: Commit**

```bash
git add docs/HANDOFF.md src/qat/version.py
```

```bash
git commit -m "M157: record the two fields a restart destroyed, and the one believed fixed"
```

---

## Deploy

**Not part of the task list — it needs the operator.** When the four checks are clean:

1. Dry run first: `powershell -File scripts\deploy.ps1`
2. **Ask the operator before applying.** Then `scripts\deploy.ps1 -Apply`.
3. Launch and read back: expect `Build: M157`, ten positions adopted, and the new `Excursion backfilled from daily bars on N of 10 restored lot(s)` line with a real count.
4. ⚠️ **`N` should be 10.** The ten held positions were opened 24–27 August and warm start seeds 300 daily bars, so every one of them has bars after its entry day. **If `N` is 0, the backfill is not working** — that is the M151 shape, a feature shipped onto a path nothing reaches.

## What this does NOT prove

- **`entry_slippage` on a real trade.** The first trade opened and closed under M157 is the check, and it must survive a restart.
- **`mae_r` and `mfe_r` against reality.** The suite proves the numbers arrive from the bars, not that they match what the position experienced.
- **The six existing closed trades.** Unrecoverable. Their reference prices were never written down.
