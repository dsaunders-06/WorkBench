# Position Anomaly Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let reconciliation be told a quantity difference is explained, and let a held position be put in a state the write path refuses to treat as ordinary — plus fix a protection check that compares presence when it should compare level.

**Architecture:** A new `PositionAnomalyStore` persists operator-declared anomalies to `position_anomalies.json` and is owned by the OMS. Reconciliation consults it before tripping the kill-switch; five call sites across the OMS and the signal bridge consult it before writing. Nothing is adjusted automatically — the seam contains damage, it does not repair it.

**Tech Stack:** Python 3.12, asyncio, pytest + pytest-asyncio, dataclasses, PySide6 (Risk Console only).

**Spec:** `docs/superpowers/specs/2026-08-08-position-anomaly-seam-design.md`

## Global Constraints

- **Validation freeze.** Nothing lands that changes which trades happen or how large they are. Everything here is fix-immediately (protection not repaired; kill-switch tripping on something that is not a real discrepancy) or strictly more conservative.
- **Formatting is `black`, not `ruff format`.** Line length follows the existing config.
- **Lint gate, run via the venv python directly** — `invoke lint` shells out to a ruff that is not on PATH:
  ```
  & "C:\Claude Programming\.venv\Scripts\python.exe" -m ruff check .
  & "C:\Claude Programming\.venv\Scripts\python.exe" -m black --check .
  & "C:\Claude Programming\.venv\Scripts\python.exe" -m mypy src
  & "C:\Claude Programming\.venv\Scripts\python.exe" -m bandit -r src
  ```
- **Tests:** `& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest`. Baseline is **1,434 passing**. Never let that number fall.
- **Docstrings carry reasons, not descriptions.** This codebase documents *why* a thing is the way it is, usually naming the incident that caused it. Match that. A docstring that only restates the signature does not match house style.
- **A test whose fixture cannot reach the failure is not evidence** (M56a). Where a defect depends on recorded state existing, the test writes that state. No asserting over empty collections.
- **Every test that builds an OMS must pass its own `data_dir`.** `tests/conftest.py` sets `QAT_DATA_DIR` **session-wide and autouse**, so a bare `Settings(_env_file=None)` resolves to one directory shared by the whole suite. Since Task 2 persists `position_anomalies.json` into `data_dir`, a test declaring an anomaly would leak that quarantine into every later test that builds an OMS — and the failures would appear in unrelated files. Always `Settings(_env_file=None, data_dir=str(tmp_path))`.
- **The broker is the authority** on what is held and what rests. Never resolve a disagreement by trusting in-memory state.
- **Never** read `%LOCALAPPDATA%\QuantAdvisoryTerminal` from the Bash tool. PowerShell only.

## Deviation from the spec, deliberate

The spec writes the binding method as `explains(symbol, tracked, broker)`. **This plan drops `tracked`**, giving `explains(symbol, broker_quantity)`.

The explanation binds to what the *broker* reported when it was declared — that is the value that must not drift. `tracked` is never read in the decision, and a parameter nothing reads is the exact pattern this project has been caught by three times (the minimum hold, the expertise level, the M37 diagnostic set). Better to remove it than to ship it.

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/domain/oms/anomaly.py` | **New.** `PositionAnomaly` record, `PositionAnomalyStore` with persistence and the binding rule. No knowledge of orders, brokers or reconciliation. |
| `src/qat/domain/oms/oms.py` | **Modify.** Owns the store; `verify_position_stops` level fix; `check_reconciliation` seam; quarantine at `submit_order` and `submit_exit_order`; adoption no longer launders an anomaly. |
| `src/qat/domain/oms/signal_bridge.py` | **Modify.** Quarantine at `rearm_protective_stops` and `restore_open_lots`. |
| `src/qat/presentation/risk_console.py` | **Modify.** Active-anomaly list, declare and clear actions. |
| `tests/safety/test_protection_level_drift.py` | **New.** Task 1 only. |
| `tests/domain/oms/test_position_anomaly.py` | **New.** The store in isolation. |
| `tests/safety/test_position_anomaly_seam.py` | **New.** Reconciliation seam, quarantine, restart laundering. |

---

### Task 1: `verify_position_stops` compares level, not just presence

Independent of every other task. Land it first.

**Files:**
- Modify: `src/qat/domain/oms/oms.py:690-735` (`verify_position_stops`)
- Test: `tests/safety/test_protection_level_drift.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `OMS.verify_position_stops() -> list[str]` — unchanged signature, unchanged meaning (symbols whose protection is no longer trustworthy). Callers need no change.

- [ ] **Step 1: Write the failing tests**

Create `tests/safety/test_protection_level_drift.py`:

```python
"""A protective stop whose LEVEL moves at the broker is as serious as one that
disappears, and until now only disappearance was watched.

`verify_position_stops` compared presence - `symbol not in resting` - so a stop
still resting at a different price passed the check. `_position_stops` is what
PortfolioGovernor measures risk-at-stop against, and the book sits at 5.02%
against a 5.00% cap, so a belief wrong by a factor mis-states the aggregate
that gates entries in every OTHER symbol. A wrong denominator does not stay in
one symbol.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _StopBroker:
    """A broker that holds positions and can say what is actually resting."""

    def __init__(
        self, positions: dict[str, float], resting: dict[str, float]
    ) -> None:
        self._positions = dict(positions)
        self._resting = dict(resting)
        self.fail_resting = False

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        if self.fail_resting:
            raise ConnectionError("broker unreachable")
        return dict(self._resting)


def _build(positions: dict[str, float], resting: dict[str, float]):
    settings = Settings(_env_file=None)
    bus = EventBus()
    switch = KillSwitch()
    broker = _StopBroker(positions, resting)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch)
    return broker, oms


@pytest.mark.asyncio
async def test_a_stop_whose_level_moved_is_reported_and_corrected():
    """The defect. The symbol is still present in `resting`, so the old
    presence test passed and the app kept believing 95.00."""
    broker, oms = _build({"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()
    assert oms.position_stops() == {"AAPL": 95.0}

    broker._resting["AAPL"] = 87.5

    drifted = await oms.verify_position_stops()

    assert drifted == ["AAPL"]
    # The broker is the authority on what is resting, so the belief is
    # replaced rather than dropped - the position IS protected, just not
    # where this app thought.
    assert oms.position_stops() == {"AAPL": 87.5}


@pytest.mark.asyncio
async def test_a_stop_still_at_its_recorded_level_is_left_alone():
    """The quiet path has to stay quiet, or the log fills with non-events and
    the operator stops reading it."""
    _, oms = _build({"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()

    assert await oms.verify_position_stops() == []
    assert oms.position_stops() == {"AAPL": 95.0}


@pytest.mark.asyncio
async def test_cent_level_rounding_is_not_drift():
    """The comparison is relative, not absolute. A book holding WFC at 87 and
    GS at 1,040 cannot share an absolute epsilon: one loose enough for GS is
    blind to a real move on WFC."""
    broker, oms = _build({"GS": 7.0}, {"GS": 1040.00})
    await oms.adopt_broker_positions()

    broker._resting["GS"] = 1040.01

    assert await oms.verify_position_stops() == []


@pytest.mark.asyncio
async def test_a_vanished_stop_is_still_reported():
    """The behaviour that already existed must survive the change."""
    broker, oms = _build({"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()

    broker._resting.pop("AAPL")

    assert await oms.verify_position_stops() == ["AAPL"]
    assert oms.position_stops() == {}


@pytest.mark.asyncio
async def test_a_broker_that_cannot_answer_changes_nothing():
    """An adapter that cannot answer must not read as "no stops rest anywhere",
    which is indistinguishable from a genuinely naked book and would be acted
    on as if it were one."""
    broker, oms = _build({"AAPL": 50.0}, {"AAPL": 95.0})
    await oms.adopt_broker_positions()
    broker.fail_resting = True

    with pytest.raises(ConnectionError):
        await oms.verify_position_stops()

    assert oms.position_stops() == {"AAPL": 95.0}
```

- [ ] **Step 2: Run to verify they fail**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_protection_level_drift.py -v
```
Expected: `test_a_stop_whose_level_moved_is_reported_and_corrected` FAILS with `assert [] == ['AAPL']`. `test_cent_level_rounding_is_not_drift`, `test_a_vanished_stop_is_still_reported` and the two others PASS already — that is correct, they are the regression guards.

If the *first* test passes, stop: the defect is not where the plan says it is, and the rest of this task is invalid.

- [ ] **Step 3: Implement**

In `src/qat/domain/oms/oms.py`, add a module-level constant near the other tolerances (top of file, after `logger = logging.getLogger(__name__)`):

```python
# A resting stop is "the same level" within a RELATIVE tolerance. An absolute
# epsilon cannot serve a book holding both WFC at 87 and GS at 1,040 - one
# loose enough to absorb rounding on the latter is blind to a real move on the
# former. At 1e-4 this absorbs cent-level rounding on every price in the book.
_STOP_LEVEL_TOLERANCE = 1e-4
```

Then replace the `lost` computation and its logging inside `verify_position_stops` (currently lines 722-735) with:

```python
        held = {pos.symbol for pos in await self.broker.positions() if abs(pos.quantity) > 0}
        lost: list[str] = []
        drifted: list[tuple[str, float, float]] = []
        for symbol, believed in list(self._position_stops.items()):
            if symbol not in held:
                continue
            actual = resting.get(symbol)
            if actual is None:
                lost.append(symbol)
                continue
            if abs(actual - believed) > _STOP_LEVEL_TOLERANCE * abs(believed):
                drifted.append((symbol, believed, actual))

        for symbol in lost:
            self._position_stops.pop(symbol, None)
        for symbol, _believed, actual in drifted:
            # Replaced, not dropped. The position IS protected - just not where
            # this app thought - and the broker is the authority on what rests.
            # Dropping it would count a protected position at full value and
            # overstate the aggregate the governor gates entries on.
            self._position_stops[symbol] = actual

        if lost:
            logger.error(
                "POSITION UNPROTECTED: %s held with no stop resting at the broker. The stop "
                "this app recorded is gone, so these now count their full value as at risk",
                ", ".join(sorted(lost)),
            )
        if drifted:
            # ERROR, and named with both levels. A protective level moving
            # without this app moving it is exactly as significant as one
            # disappearing, and until M39 nothing looked for it at all.
            logger.error(
                "PROTECTION LEVEL CHANGED at the broker: %s. This app did not move these, so "
                "risk-at-stop was being measured against the wrong distance",
                ", ".join(
                    f"{symbol} believed={believed:g} resting={actual:g}"
                    for symbol, believed, actual in sorted(drifted)
                ),
            )
        return sorted(lost + [symbol for symbol, _, _ in drifted])
```

Update the docstring's closing paragraph to name the new behaviour:

```python
        Unprotected positions are dropped from the record rather than kept, so
        the governor falls back to treating them as fully at risk. A position
        whose stop MOVED is different: it is still protected, so the recorded
        level is replaced by what the broker actually says rather than dropped.
        Both are returned - the caller's question is "which symbols is my
        protection record no longer trustworthy for", and both answer yes.

        The level check exists because the presence check was not one. Until
        M39 this compared `symbol not in resting`, so a stop resting at a
        different price passed - and `_position_stops` is the denominator of
        every risk-at-stop figure the governor gates entries on.
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_protection_level_drift.py -v
```
Expected: 5 passed.

Then:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest -q
```
Expected: 1,439 passed (1,434 baseline + 5). **If any pre-existing test fails, do not proceed** — `verify_position_stops` returning drifted symbols changes what callers see, and a failure here means a caller treats the return value as "unprotected" specifically.

- [ ] **Step 5: Lint and commit**

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m ruff check .
& "C:\Claude Programming\.venv\Scripts\python.exe" -m black --check .
& "C:\Claude Programming\.venv\Scripts\python.exe" -m mypy src
& "C:\Claude Programming\.venv\Scripts\python.exe" -m bandit -r src
```

```bash
git add src/qat/domain/oms/oms.py tests/safety/test_protection_level_drift.py
git commit -m "Notice a protective stop whose level moved, not only one that vanished"
```

---

### Task 2: The anomaly record and its store

**Files:**
- Create: `src/qat/domain/oms/anomaly.py`
- Test: `tests/domain/oms/test_position_anomaly.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces, relied on by Tasks 3-7:
  - `PositionAnomaly` — frozen dataclass, fields `symbol: str`, `reason: str`, `declared_by: str`, `declared_at: datetime`, `tracked_quantity: float`, `broker_quantity: float`
  - `PositionAnomalyStore(data_dir: str | Path | None = None)`
  - `.declare(*, symbol: str, reason: str, declared_by: str, tracked_quantity: float, broker_quantity: float) -> PositionAnomaly`
  - `.clear(symbol: str, operator: str) -> bool`
  - `.get(symbol: str) -> PositionAnomaly | None`
  - `.is_quarantined(symbol: str) -> bool`
  - `.active() -> list[PositionAnomaly]`
  - `.explains(symbol: str, broker_quantity: float) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/domain/oms/test_position_anomaly.py`:

```python
"""The concept M39 and M43 share: a held position in a state the ordinary path
must not treat as ordinary.

The test that matters most here is the immunity one. An explanation that is not
bound to the quantity it was declared against grants a symbol permanent
immunity, and the next genuine divergence passes in silence - which is exactly
the failure `adopt_broker_positions` already warns about, where an operator is
trained to ignore the one signal meaning "my view of the account cannot be
trusted".
"""

from __future__ import annotations

from qat.domain.oms.anomaly import PositionAnomalyStore


def test_nothing_is_quarantined_by_default() -> None:
    store = PositionAnomalyStore()

    assert store.active() == []
    assert store.is_quarantined("CRWD") is False
    assert store.get("CRWD") is None


def test_a_declared_anomaly_quarantines_its_symbol() -> None:
    store = PositionAnomalyStore()

    anomaly = store.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert anomaly.symbol == "CRWD"
    assert anomaly.declared_at.tzinfo is not None
    assert store.is_quarantined("CRWD") is True
    assert store.is_quarantined("AMD") is False
    assert [a.symbol for a in store.active()] == ["CRWD"]


def test_it_explains_the_quantity_it_was_declared_against() -> None:
    store = PositionAnomalyStore()
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert store.explains("CRWD", 64.0) is True


def test_it_does_not_explain_a_LATER_different_quantity() -> None:
    """The immunity test, and the reason `explains` takes a quantity at all.

    Declaring 16-to-64 explained must not also explain a later 64-to-128. If it
    did, one declaration would silence that symbol forever and the second event
    - which nobody has looked at - would pass as accounted for.
    """
    store = PositionAnomalyStore()
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert store.explains("CRWD", 128.0) is False
    # Still quarantined, though - the position is no less suspect for having
    # moved again. Quarantine and explanation are separate questions.
    assert store.is_quarantined("CRWD") is True


def test_it_explains_nothing_for_an_undeclared_symbol() -> None:
    store = PositionAnomalyStore()

    assert store.explains("AMD", 14.0) is False


def test_clearing_releases_the_symbol() -> None:
    store = PositionAnomalyStore()
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert store.clear("CRWD", operator="operator") is True
    assert store.is_quarantined("CRWD") is False
    assert store.explains("CRWD", 64.0) is False
    assert store.clear("CRWD", operator="operator") is False


def test_it_survives_a_restart(tmp_path) -> None:
    """The whole point. An in-memory-only anomaly is erased by the restart that
    follows every overnight session, and the position goes back to looking
    ordinary while its records are still wrong."""
    store = PositionAnomalyStore(tmp_path)
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    reloaded = PositionAnomalyStore(tmp_path)

    assert reloaded.is_quarantined("CRWD") is True
    assert reloaded.explains("CRWD", 64.0) is True
    restored = reloaded.get("CRWD")
    assert restored is not None
    assert restored.reason == "4-for-1 split, ex 2 July"
    assert restored.declared_by == "operator"
    assert restored.tracked_quantity == 16.0


def test_clearing_survives_a_restart_too(tmp_path) -> None:
    """A cleared anomaly that comes back on the next launch would re-quarantine
    a position the operator has already dealt with."""
    store = PositionAnomalyStore(tmp_path)
    store.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )
    store.clear("CRWD", operator="operator")

    assert PositionAnomalyStore(tmp_path).is_quarantined("CRWD") is False


def test_an_unreadable_file_does_not_stop_startup(tmp_path) -> None:
    """Degrading to "nothing is quarantined" is the wrong direction on its own,
    so it is loud. It is still better than refusing to launch: an app that will
    not start protects nothing at all."""
    (tmp_path / "position_anomalies.json").write_text("{not json", encoding="utf-8")

    store = PositionAnomalyStore(tmp_path)

    assert store.active() == []
```

- [ ] **Step 2: Run to verify they fail**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/domain/oms/test_position_anomaly.py -v
```
Expected: all FAIL at collection with `ModuleNotFoundError: No module named 'qat.domain.oms.anomaly'`.

- [ ] **Step 3: Implement**

Create `src/qat/domain/oms/anomaly.py`:

```python
"""A held position in a state the ordinary path must not treat as ordinary.

Two things outside this application change a position it holds: a corporate
action changes the share count (M39), and a halt makes it unexitable (M43).
Both need the same two seams - reconciliation being able to be told a
difference is EXPLAINED, and the write path being able to be told a symbol is
not safe to act on. Built once, here, so the second one costs a producer
rather than a mechanism.

**This contains damage; it does not repair it.** A declared anomaly stays
quarantined until the underlying records are corrected by hand, as the CVS
ledger was on 6 August. Any screen rendering this must say so - "declared"
reading as "fixed" is the one failure this module could introduce.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "position_anomalies.json"

# Share counts are whole numbers at every broker this app talks to, so this is
# a float-comparison guard rather than a real tolerance.
_QUANTITY_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class PositionAnomaly:
    """One symbol, declared to be in a state nothing ordinary should act on.

    `broker_quantity` is not decoration. It is what the explanation is BOUND
    to: see `PositionAnomalyStore.explains`.
    """

    symbol: str
    reason: str
    declared_by: str
    declared_at: datetime
    tracked_quantity: float
    broker_quantity: float


class PositionAnomalyStore:
    """Active anomalies, persisted so a restart cannot erase them.

    Persistence is the point rather than a convenience. `adopt_broker_positions`
    reseeds tracked quantities wholesale from the broker at every launch, so a
    divergence VANISHES across a restart - tracked matches broker,
    reconciliation is content, and the entry record and ledger stay wrong. With
    an overnight session and a restart between each one, that is the normal
    path and not an edge case.

    A store built with no data directory keeps everything in memory. That is
    for tests and for an OMS constructed without settings; it is not a
    supported production configuration.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._path = Path(data_dir) / _FILENAME if data_dir is not None else None
        self._active: dict[str, PositionAnomaly] = {}
        self._load()

    def declare(
        self,
        *,
        symbol: str,
        reason: str,
        declared_by: str,
        tracked_quantity: float,
        broker_quantity: float,
    ) -> PositionAnomaly:
        """Records that a difference on `symbol` is accounted for.

        WARNING rather than INFO, and it names both quantities. Declaring an
        anomaly suppresses a halt that would otherwise have happened, which is
        the most consequential thing an operator can tell this application.
        """
        anomaly = PositionAnomaly(
            symbol=symbol,
            reason=reason,
            declared_by=declared_by,
            declared_at=datetime.now(UTC),
            tracked_quantity=tracked_quantity,
            broker_quantity=broker_quantity,
        )
        self._active[symbol] = anomaly
        logger.warning(
            "POSITION ANOMALY DECLARED by %s: %s tracked=%g broker=%g - %s. New entries, "
            "de-lever trims and protection re-arming are refused for this symbol until it "
            "is cleared. The records are NOT corrected by this - that is still manual.",
            declared_by,
            symbol,
            tracked_quantity,
            broker_quantity,
            reason,
        )
        self._save()
        return anomaly

    def clear(self, symbol: str, operator: str) -> bool:
        """Releases a symbol. Returns False if it was not quarantined."""
        anomaly = self._active.pop(symbol, None)
        if anomaly is None:
            return False
        logger.warning(
            "Position anomaly on %s cleared by %s (was: %s) - ordinary order flow resumes "
            "for this symbol",
            symbol,
            operator,
            anomaly.reason,
        )
        self._save()
        return True

    def get(self, symbol: str) -> PositionAnomaly | None:
        return self._active.get(symbol)

    def is_quarantined(self, symbol: str) -> bool:
        return symbol in self._active

    def active(self) -> list[PositionAnomaly]:
        return sorted(self._active.values(), key=lambda a: a.symbol)

    def explains(self, symbol: str, broker_quantity: float) -> bool:
        """Whether a difference on `symbol` has already been accounted for.

        Bound to the quantity the broker reported when the anomaly was
        declared, and that binding IS the design. Without it, declaring a
        symbol explained once grants permanent immunity and the next genuine
        divergence passes in silence - the failure `adopt_broker_positions`
        already warns about, where an operator learns to ignore the one signal
        meaning "my view of the account cannot be trusted". A difference
        declared at 16-to-64 does not explain a later 64-to-128.

        Note this is a narrower question than `is_quarantined`. A position that
        moves again is no LESS suspect, so it stays quarantined while ceasing
        to be explained.
        """
        anomaly = self._active.get(symbol)
        if anomaly is None:
            return False
        return abs(anomaly.broker_quantity - broker_quantity) <= _QUANTITY_TOLERANCE

    def _load(self) -> None:
        """No file, no directory, or an unreadable one all mean "nothing is
        quarantined" - and that is the WRONG direction, so it is logged at
        ERROR rather than swallowed. It is still better than refusing to start:
        an application that will not launch protects nothing at all, and the
        reconciliation halt is still there to catch the divergence the hard
        way.
        """
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._active = {
                str(entry["symbol"]): PositionAnomaly(
                    symbol=str(entry["symbol"]),
                    reason=str(entry["reason"]),
                    declared_by=str(entry["declared_by"]),
                    declared_at=datetime.fromisoformat(entry["declared_at"]),
                    tracked_quantity=float(entry["tracked_quantity"]),
                    broker_quantity=float(entry["broker_quantity"]),
                )
                for entry in (raw.get("anomalies") or [])
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Could not read %s (%s) - NOTHING is quarantined this session. Any position "
                "that was declared explained will halt reconciliation again instead.",
                self._path,
                exc,
            )
            self._active = {}
            return
        if self._active:
            logger.warning(
                "Restored %d quarantined position(s) from %s: %s",
                len(self._active),
                self._path.name,
                ", ".join(sorted(self._active)),
            )

    def _save(self) -> None:
        """Written on every change, not at shutdown: the restart this exists
        for is the one nobody planned."""
        if self._path is None:
            return
        payload = {
            "anomalies": [
                {
                    "symbol": a.symbol,
                    "reason": a.reason,
                    "declared_by": a.declared_by,
                    "declared_at": a.declared_at.isoformat(),
                    "tracked_quantity": a.tracked_quantity,
                    "broker_quantity": a.broker_quantity,
                }
                for a in self.active()
            ]
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception(
                "Could not write %s - the quarantine will not survive a restart", self._path
            )
```

- [ ] **Step 4: Run to verify they pass**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/domain/oms/test_position_anomaly.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Lint and commit**

Run the four lint commands from Global Constraints, then:

```bash
git add src/qat/domain/oms/anomaly.py tests/domain/oms/test_position_anomaly.py
git commit -m "Add the position-anomaly concept M39 and M43 both need"
```

---

### Task 3: The reconciliation seam

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — constructor (~line 146), `check_reconciliation` (lines 1185-1223)
- Test: `tests/safety/test_position_anomaly_seam.py` (create)

**Interfaces:**
- Consumes: `PositionAnomalyStore`, `.explains(symbol, broker_quantity)`, `.get(symbol)` from Task 2.
- Produces, relied on by Tasks 4-7: `OMS.anomalies` — a `PositionAnomalyStore` attribute on every OMS instance. `OMS.check_reconciliation()` keeps its signature and its meaning of "a *halting* mismatch was found".

- [ ] **Step 1: Write the failing tests**

Create `tests/safety/test_position_anomaly_seam.py`:

```python
"""Reconciliation being able to be told a difference is explained.

Today `check_reconciliation` compares and trips, with no way to be told "this
one is accounted for" - so an ordinary corporate action halts a session, which
is in the freeze's fix-immediately list as "the kill-switch tripping on
something that is not a real discrepancy".
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, positions: dict[str, float]) -> None:
        self._positions = dict(positions)

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since):
        return []


def _build(tmp_path, positions: dict[str, float]):
    """`data_dir` is per-test and never omitted.

    conftest sets QAT_DATA_DIR session-wide, so a bare Settings would give
    every test the SAME directory - and this store persists there, so one
    declared anomaly would quarantine that symbol for the rest of the suite.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return broker, oms, switch


@pytest.mark.asyncio
async def test_an_undeclared_divergence_still_trips_the_kill_switch(tmp_path):
    """Unchanged behaviour, and the more important half. An unexplained
    difference means this app's view of the account cannot be trusted, and that
    is account-wide by nature."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()

    broker._positions["CRWD"] = 64.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_a_declared_divergence_does_not_trip(tmp_path):
    """The seam. The session continues, and the symbol is quarantined."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0

    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert await oms.check_reconciliation() is False
    assert switch.tripped is False


@pytest.mark.asyncio
async def test_a_declaration_does_not_excuse_a_LATER_movement(tmp_path):
    """The immunity test, at the seam rather than in the store. A symbol that
    moves again has not been looked at, and must halt."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )
    assert await oms.check_reconciliation() is False

    broker._positions["CRWD"] = 128.0

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_one_declared_symbol_does_not_excuse_another(tmp_path):
    """Quarantine is per symbol. A declaration on CRWD says nothing about AMD."""
    broker, oms, switch = _build(tmp_path, {"CRWD": 16.0, "AMD": 7.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    broker._positions["AMD"] = 14.0
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    assert await oms.check_reconciliation() is True
    assert switch.tripped is True


@pytest.mark.asyncio
async def test_an_explained_divergence_is_logged_once_not_every_poll(tmp_path, caplog):
    """Reconciliation polls on an interval. A line per poll floods the log and
    trains the operator to scroll past it - the same reason KillSwitch.trip
    ignores a repeat trip."""
    broker, oms, _ = _build(tmp_path, {"CRWD": 16.0})
    await oms.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    with caplog.at_level("WARNING"):
        await oms.check_reconciliation()
        await oms.check_reconciliation()
        await oms.check_reconciliation()

    assert caplog.text.count("explained by a declared position anomaly") == 1
```

- [ ] **Step 2: Run to verify they fail**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v
```
Expected: `test_an_undeclared_divergence_still_trips_the_kill_switch` PASSES (existing behaviour). The other four FAIL with `AttributeError: 'OMS' object has no attribute 'anomalies'`.

- [ ] **Step 3: Implement**

In `src/qat/domain/oms/oms.py`, add the import next to the other domain imports:

```python
from qat.domain.oms.anomaly import PositionAnomalyStore
```

In `OMS.__init__`, immediately after `self._signoff_lock = asyncio.Lock()`:

```python
        # Positions in a state the ordinary path must not treat as ordinary
        # (M39/M43). Persisted, because adoption reseeds tracked quantities
        # from the broker at every launch and would otherwise launder the very
        # divergence this records.
        self.anomalies = PositionAnomalyStore(
            settings.data_dir if settings is not None else None
        )
        # Explained divergences are logged once per session, not once per poll.
        self._explained_logged: set[str] = set()
```

Replace the tail of `check_reconciliation` (currently lines 1214-1223) with:

```python
        explained = {
            symbol: pair
            for symbol, pair in divergent.items()
            if self.anomalies.explains(symbol, pair[1])
        }
        unexplained = {
            symbol: pair for symbol, pair in divergent.items() if symbol not in explained
        }

        for symbol, (tracked, actual) in sorted(explained.items()):
            if symbol in self._explained_logged:
                continue
            self._explained_logged.add(symbol)
            anomaly = self.anomalies.get(symbol)
            logger.warning(
                "%s tracked=%g broker=%g is explained by a declared position anomaly (%s) - "
                "not halting. The symbol stays quarantined and its records are still "
                "uncorrected.",
                symbol,
                tracked,
                actual,
                anomaly.reason if anomaly is not None else "reason unavailable",
            )

        if unexplained:
            logger.error(
                "Broker reconciliation mismatch: %s",
                ", ".join(
                    f"{sym} tracked={tracked:g} broker={actual:g}"
                    for sym, (tracked, actual) in sorted(unexplained.items())
                ),
            )
            self.kill_switch.check_reconciliation()
        return bool(unexplained)
```

Add to the `check_reconciliation` docstring, after the existing first paragraph:

```python
        A divergence the anomaly store EXPLAINS is not a mismatch (M39). The
        return value keeps its meaning - "a halting mismatch was found" - so
        ReconciliationMonitor, which publishes KillSwitchEvent on True, needs
        no change. An explained symbol is still quarantined; explanation and
        quarantine are separate questions.
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v
```
Expected: 5 passed.

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest -q
```
Expected: 1,453 passed.

- [ ] **Step 5: Lint and commit**

```bash
git add src/qat/domain/oms/oms.py tests/safety/test_position_anomaly_seam.py
git commit -m "Let reconciliation be told a difference is explained"
```

---

### Task 4: The quarantine at order admission

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — `submit_order` (lines 183-187), `submit_exit_order` (lines 276-301)
- Test: `tests/safety/test_position_anomaly_seam.py` (append)

**Interfaces:**
- Consumes: `OMS.anomalies` from Task 3; `.get(symbol)` from Task 2.
- Produces: no new public API. `submit_exit_order` gains no parameters — it re-reads the broker internally when the symbol is quarantined.

- [ ] **Step 1: Write the failing tests**

Append to `tests/safety/test_position_anomaly_seam.py`:

```python
# --- Block writes, allow exits ------------------------------------------------
#
# The rule chosen deliberately. Refusing entries, trims and re-arming stops the
# thing that destroys a position; refusing EXITS would be the shape M56c was a
# defect for, where a gate quietly suppressed the only route to selling.


class _ExitBroker(_Broker):
    """A broker whose position read can be made to fail."""

    def __init__(self, positions: dict[str, float]) -> None:
        super().__init__(positions)
        self.fail_positions = False

    async def positions(self) -> list[Position]:
        if self.fail_positions:
            raise ConnectionError("broker unreachable")
        return await super().positions()


def _build_exit(tmp_path, positions: dict[str, float]):
    """Per-test `data_dir`, for the reason given on `_build` above."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _ExitBroker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return broker, oms


def _quarantine(oms: OMS, symbol: str, tracked: float, broker_qty: float) -> None:
    oms.anomalies.declare(
        symbol=symbol,
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=tracked,
        broker_quantity=broker_qty,
    )


@pytest.mark.asyncio
async def test_a_quarantined_symbol_refuses_new_entries(tmp_path):
    """Sized against a quantity known to be wrong, an entry is wrong."""
    from qat.domain.risk_engine.engine import OrderCandidate

    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_order(
        OrderCandidate(symbol="CRWD", side="buy", price=214.42, stop_price=190.0),
        equity=100_000.0,
        existing_weights={},
        existing_returns={},
    )

    assert order.status == "rejected"
    assert "anomaly" in (order.reason or "").lower()


@pytest.mark.asyncio
async def test_a_quarantined_symbol_refuses_a_delever_trim(tmp_path):
    """A trim sized against a known-wrong quantity is the trim doing damage."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_exit_order("CRWD", quantity=8.0, price=214.42, reason="delever")

    assert order.status == "rejected"
    assert "anomaly" in (order.reason or "").lower()


@pytest.mark.asyncio
async def test_a_quarantined_symbol_still_allows_an_exit(tmp_path):
    """M56c's lesson. No gate silently suppresses the only route to selling."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_exit_order("CRWD", quantity=16.0, price=214.42, reason="signal")

    assert order.status == "pending_signoff"


@pytest.mark.asyncio
async def test_an_exit_on_a_quarantined_symbol_is_sized_from_the_broker(tmp_path):
    """The caller passes the TRACKED quantity, which is the wrong one - that is
    what being quarantined means. Selling 16 of 64 leaves three quarters of a
    position behind that nobody intended to keep."""
    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)

    order = await oms.submit_exit_order("CRWD", quantity=16.0, price=214.42, reason="signal")

    assert order.quantity == 64.0


@pytest.mark.asyncio
async def test_an_exit_is_refused_when_the_broker_cannot_be_read(tmp_path):
    """Exiting a known-wrong quantity on a symbol already flagged as
    untrustworthy is worse than not exiting. Recorded as a rejection with a
    reason, per M54, rather than vanishing."""
    broker, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    _quarantine(oms, "CRWD", 16.0, 64.0)
    broker.fail_positions = True

    order = await oms.submit_exit_order("CRWD", quantity=16.0, price=214.42, reason="signal")

    assert order.status == "rejected"
    assert "anomaly" in (order.reason or "").lower()


@pytest.mark.asyncio
async def test_an_unquarantined_symbol_is_untouched(tmp_path):
    """The ordinary path must not pay for this."""
    _, oms = _build_exit(tmp_path, {"AMD": 7.0})

    order = await oms.submit_exit_order("AMD", quantity=7.0, price=483.36, reason="signal")

    assert order.status == "pending_signoff"
    assert order.quantity == 7.0
```

- [ ] **Step 2: Run to verify they fail**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v -k "quarantined or exit_is_refused or unquarantined"
```
Expected: the entry, trim, broker-sizing and broker-failure tests FAIL (orders come back `pending_signoff` or at the wrong quantity). `test_a_quarantined_symbol_still_allows_an_exit` and `test_an_unquarantined_symbol_is_untouched` PASS already — they are the regression guards.

- [ ] **Step 3: Implement**

In `submit_order`, insert immediately after the allow-list check and **before** the kill-switch check, so the rejection names the anomaly rather than a generic halt:

```python
        anomaly = self.anomalies.get(candidate.symbol)
        if anomaly is not None:
            return self._new_rejected_order(
                candidate, 0.0, f"position anomaly - {anomaly.reason}"
            )
```

In `submit_exit_order`, insert immediately after the allow-list check:

```python
        anomaly = self.anomalies.get(symbol)
        if anomaly is not None:
            if reason == "delever":
                # A trim sized against a quantity known to be wrong is the trim
                # doing the damage. Exits are allowed below; trims are not.
                return self._new_rejected_order_for(
                    symbol,
                    "sell",
                    0.0,
                    f"position anomaly - de-lever trim refused ({anomaly.reason})",
                )
            held = await self._broker_quantity(symbol)
            if held is None:
                # Refusing an exit is normally the M56c defect. Here the
                # alternative is selling a quantity this app has already
                # recorded as untrustworthy, and the refusal is a rejected
                # order with a reason rather than a silent gate.
                return self._new_rejected_order_for(
                    symbol,
                    "sell",
                    0.0,
                    f"position anomaly - could not read the broker to size the exit "
                    f"({anomaly.reason})",
                )
            logger.warning(
                "Exit on quarantined %s sized from the broker at %g, not the tracked %g",
                symbol,
                held,
                quantity,
            )
            quantity = held
```

Add the helper next to `naked_positions`:

```python
    async def _broker_quantity(self, symbol: str) -> float | None:
        """What the broker says is held, or None if it cannot be asked.

        None and zero are different answers and must not collapse: zero means
        the position is gone, None means this app does not know - and sizing an
        exit on a guess is what the quarantine exists to prevent.
        """
        try:
            positions = await self.broker.positions()
        except Exception:
            logger.exception("Could not read the broker to size an exit on %s", symbol)
            return None
        return next(
            (abs(pos.quantity) for pos in positions if pos.symbol == symbol),
            0.0,
        )
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v
```
Expected: 11 passed.

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest -q
```
Expected: 1,459 passed.

- [ ] **Step 5: Lint and commit**

```bash
git add src/qat/domain/oms/oms.py tests/safety/test_position_anomaly_seam.py
git commit -m "Refuse writes on a quarantined symbol, and never its exits"
```

---

### Task 5: The quarantine at the signal bridge

**Files:**
- Modify: `src/qat/domain/oms/signal_bridge.py` — `restore_open_lots` (lines 324-385), `rearm_protective_stops` (lines 437-487)
- Test: `tests/safety/test_position_anomaly_seam.py` (append)

**Interfaces:**
- Consumes: `OMS.anomalies` from Task 3, reached as `self.oms.anomalies`. No new import direction — `signal_bridge` already imports from `oms`.
- Produces: no new public API. Both methods keep their signatures and their return types (`list[str]` of symbols acted on).

- [ ] **Step 1: Write the failing tests**

Append to `tests/safety/test_position_anomaly_seam.py`:

```python
# --- The two signal-bridge sites ---------------------------------------------


@pytest.mark.asyncio
async def test_rearm_skips_a_quarantined_position(tmp_path, caplog):
    """The liquidation guard, and the reason this task exists at all.

    `_entries[symbol].stop_price` is the PRE-event level. Re-arming from it
    after a 4-for-1 split rests a stop at roughly four times the new price,
    which on a long position triggers immediately and liquidates it at the next
    open.
    """
    from qat.domain.oms.signal_bridge import SignalToOrderBridge, _Entry
    from datetime import UTC, datetime

    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    bridge = SignalToOrderBridge(
        bus=EventBus(), oms=oms, settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )
    bridge._entries["CRWD"] = _Entry(
        opened_at=datetime(2026, 7, 31, tzinfo=UTC),
        price=187.40,
        stop_price=163.32,
        target_price=235.20,
        strategy="swing",
    )
    _quarantine(oms, "CRWD", 16.0, 64.0)

    with caplog.at_level("ERROR"):
        proposed = await bridge.rearm_protective_stops()

    assert "CRWD" not in proposed
    assert "CRWD" in caplog.text


@pytest.mark.asyncio
async def test_lot_restore_skips_a_quarantined_position(tmp_path, caplog):
    """`restore_open_lots` takes QUANTITY from the broker and BASIS from
    `_entries`, so after an external quantity change it builds a lot at the
    post-event size on the pre-event basis - silently, because the entry record
    exists so no `unknown` warning fires. P&L is then wrong by the event's
    factor and R is wrong in its denominator, feeding the promotion gate.

    `_Entry` carries no quantity, so there is nothing to compare against and no
    cheaper guard than this.
    """
    from qat.domain.oms.signal_bridge import SignalToOrderBridge, _Entry
    from datetime import UTC, datetime

    _, oms = _build_exit(tmp_path, {"CRWD": 64.0})
    bridge = SignalToOrderBridge(
        bus=EventBus(), oms=oms, settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )
    bridge._entries["CRWD"] = _Entry(
        opened_at=datetime(2026, 7, 31, tzinfo=UTC),
        price=187.40,
        stop_price=163.32,
        strategy="swing",
    )
    _quarantine(oms, "CRWD", 16.0, 64.0)

    with caplog.at_level("WARNING"):
        restored = await bridge.restore_open_lots()

    assert "CRWD" not in restored
    assert "CRWD" in caplog.text
```

- [ ] **Step 2: Run to verify they fail**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v -k "rearm_skips or lot_restore_skips"
```
Expected: both FAIL — `CRWD` appears in the returned list.

If `SignalToOrderBridge`'s constructor signature differs from `(bus, oms, settings)`, read `src/qat/domain/oms/signal_bridge.py` and correct the test's construction before proceeding. Do not change the production code to fit the test.

- [ ] **Step 3: Implement**

In `restore_open_lots`, inside the `for position in positions:` loop, immediately after the `quantity <= 0` guard:

```python
            if self.oms.anomalies.is_quarantined(position.symbol):
                quarantined.append(position.symbol)
                continue
```

Declare `quarantined: list[str] = []` alongside `restored` and `unknown`, and add after the `unknown` logging block:

```python
        if quarantined:
            # A visibly missing lot rather than a quietly wrong one - the rule
            # this module already applies to an unknown stop. Quantity comes
            # from the broker and basis from `_entries`, so after an external
            # quantity change the lot would be built at the post-event size on
            # the pre-event basis, and nothing would say so.
            logger.warning(
                "No lot restored for quarantined position(s) %s - the entry basis on record "
                "does not match what the broker holds, so a lot built from it would be wrong "
                "by the same factor. These produce no closed trade until corrected.",
                ", ".join(sorted(quarantined)),
            )
```

In `rearm_protective_stops`, inside the `for symbol, quantity in naked:` loop, as the first statement:

```python
            if self.oms.anomalies.is_quarantined(symbol):
                quarantined.append(symbol)
                continue
```

Declare `quarantined: list[str] = []` alongside `proposed` and `unknown`, and add after the `unknown` logging block:

```python
        if quarantined:
            logger.error(
                "POSITION UNPROTECTED and quarantined: %s. The recorded entry stop is from "
                "before the change that quarantined it, so re-arming from it would rest "
                "protection at a level that liquidates. No stop is proposed - protect or "
                "close these manually.",
                ", ".join(sorted(quarantined)),
            )
```

- [ ] **Step 4: Run the new tests, then the full suite**

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v
```
Expected: 13 passed.

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest -q
```
Expected: 1,461 passed.

- [ ] **Step 5: Lint and commit**

```bash
git add src/qat/domain/oms/signal_bridge.py tests/safety/test_position_anomaly_seam.py
git commit -m "Never re-arm or rebuild a lot for a quarantined position"
```

---

### Task 6: Adoption must not launder an anomaly

**Files:**
- Modify: `src/qat/domain/oms/oms.py` — `adopt_broker_positions` (lines 586-652)
- Test: `tests/safety/test_position_anomaly_seam.py` (append)

**Interfaces:**
- Consumes: `OMS.anomalies` from Task 3.
- Produces: no new public API. `adopt_broker_positions` keeps returning `dict[str, float]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/safety/test_position_anomaly_seam.py`:

```python
# --- The restart laundering ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_restart_does_not_erase_a_quarantine(tmp_path):
    """`adopt_broker_positions` does `self._filled_quantities = dict(adopted)`
    - wholesale from the broker - so a restart makes the divergence VANISH.
    Tracked matches broker, reconciliation is content, and the entry record and
    ledger stay wrong. With an overnight session and a restart between each
    one, that is the normal path.

    The fixture writes the persisted file, because a test whose fixture cannot
    reach the failure is not evidence (M56a).
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker({"CRWD": 16.0})
    first = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    await first.adopt_broker_positions()
    broker._positions["CRWD"] = 64.0
    first.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split, ex 2 July",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    # A new session, same data directory, broker now reporting the post-split
    # quantity as if it had always been so.
    second_switch = KillSwitch()
    second = OMS(
        broker,
        RiskEngine(EventBus(), second_switch, settings=settings),
        second_switch,
        settings=settings,
    )
    await second.adopt_broker_positions()

    assert second.anomalies.is_quarantined("CRWD") is True


@pytest.mark.asyncio
async def test_a_further_change_on_a_quarantined_position_is_reported(tmp_path, caplog):
    """A position that moves AGAIN after being declared has not been looked at.
    Adoption is where that is noticed, because adoption is what overwrites the
    evidence."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    switch = KillSwitch()
    broker = _Broker({"CRWD": 64.0})
    oms = OMS(
        broker, RiskEngine(EventBus(), switch, settings=settings), switch, settings=settings
    )
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    broker._positions["CRWD"] = 128.0
    with caplog.at_level("ERROR"):
        await oms.adopt_broker_positions()

    assert "CRWD" in caplog.text
    assert oms.anomalies.is_quarantined("CRWD") is True


@pytest.mark.asyncio
async def test_the_adoption_banner_names_quarantined_positions(tmp_path, caplog):
    """The operator is told to read the startup lines and treat their ABSENCE
    as the signal, so this belongs there and not only in the UI."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    switch = KillSwitch()
    broker = _Broker({"CRWD": 64.0, "AMD": 7.0})
    oms = OMS(
        broker, RiskEngine(EventBus(), switch, settings=settings), switch, settings=settings
    )
    oms.anomalies.declare(
        symbol="CRWD",
        reason="4-for-1 split",
        declared_by="operator",
        tracked_quantity=16.0,
        broker_quantity=64.0,
    )

    with caplog.at_level("WARNING"):
        await oms.adopt_broker_positions()

    assert "quarantined" in caplog.text.lower()
    assert "CRWD" in caplog.text
```

- [ ] **Step 2: Run to verify they fail**

Run:
```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v -k "restart_does_not_erase or further_change or adoption_banner"
```
Expected: `test_a_restart_does_not_erase_a_quarantine` may PASS already (the store is loaded from disk in Task 3's constructor change) — that is fine, it is the guard that the persistence actually reaches adoption. The other two FAIL: no ERROR naming CRWD, no "quarantined" in the banner.

- [ ] **Step 3: Implement**

In `adopt_broker_positions`, after `self._adopted_baseline = dict(adopted)` and before the `if not adopted:` early return:

```python
        # Adoption overwrites `_filled_quantities` wholesale, which is exactly
        # what would erase a divergence somebody has already declared. Check
        # against the declaration BEFORE the evidence is gone.
        moved_again = [
            anomaly.symbol
            for anomaly in self.anomalies.active()
            if abs(adopted.get(anomaly.symbol, 0.0) - anomaly.broker_quantity) > 1e-6
        ]
        if moved_again:
            logger.error(
                "QUARANTINED POSITION MOVED AGAIN since it was declared: %s. The declaration "
                "no longer explains what the broker holds, so reconciliation will halt on "
                "these until they are re-declared or cleared.",
                ", ".join(
                    f"{symbol} declared={self.anomalies.get(symbol).broker_quantity:g} "  # type: ignore[union-attr]
                    f"now={adopted.get(symbol, 0.0):g}"
                    for symbol in sorted(moved_again)
                ),
            )
```

Then, immediately after the existing `logger.warning("Adopted %d pre-existing broker position(s)...` call, add:

```python
        quarantined = [a.symbol for a in self.anomalies.active() if a.symbol in adopted]
        if quarantined:
            logger.warning(
                "%d adopted position(s) are QUARANTINED: %s. New entries, de-lever trims and "
                "protection re-arming are refused for these, and their records are still "
                "uncorrected - a declaration explains a difference, it does not repair it.",
                len(quarantined),
                ", ".join(sorted(quarantined)),
            )
```

- [ ] **Step 4: Run the new tests, then the full suite**

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/safety/test_position_anomaly_seam.py -v
```
Expected: 16 passed.

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest -q
```
Expected: 1,464 passed.

- [ ] **Step 5: Lint and commit**

```bash
git add src/qat/domain/oms/oms.py tests/safety/test_position_anomaly_seam.py
git commit -m "Stop a restart laundering a declared anomaly"
```

---

### Task 7: The Risk Console surface

**Files:**
- Modify: `src/qat/presentation/risk_console.py` (168 lines; `RiskConsoleScreen` at line 35)
- Test: `tests/presentation/test_risk_console_anomalies.py` (create)

**Interfaces:**
- Consumes: `OMS.anomalies` from Task 3, reached through `runtime`. Confirm the accessor by reading how `risk_console.py` already reaches the OMS (`self._runtime...`) before writing code — the plan does not assume the attribute name.
- Produces: nothing other tasks depend on. This is the last task.

- [ ] **Step 1: Write the failing test**

The existing console test (`tests/presentation/test_risk_console_kill_switch.py`) establishes the pattern: `Runtime.build_demo(settings=...)`, `qtbot.addWidget`, and handlers invoked directly rather than through a running event loop.

**Before writing, confirm two things by reading:** that `Runtime.build_demo` exposes the OMS as `runtime.oms` (the kill-switch test uses `runtime.kill_switch`), and how `_on_timer_tick` drives refreshes. If the OMS accessor is named differently, use the real name — do not add an alias to make the test compile.

Create `tests/presentation/test_risk_console_anomalies.py`:

```python
"""The console is the only place an operator can say a difference is explained.

If the control does not reach the store, the whole seam is unreachable in the
running application - which is the M58a failure exactly: a first-run dialog
that told the operator their choice decided something, and decided nothing.
A control is built here only because something consumes it.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.risk_console import RiskConsoleScreen
from qat.presentation.runtime import Runtime


def _build_screen(qtbot, tmp_path) -> tuple[RiskConsoleScreen, Runtime]:
    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, data_dir=str(tmp_path))
    )
    screen = RiskConsoleScreen(runtime)
    qtbot.addWidget(screen)
    return screen, runtime


def test_declaring_reaches_the_store(qtbot, tmp_path):
    """The seam is only real if this call arrives."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    assert runtime.oms.anomalies.is_quarantined("CRWD") is False

    screen._declare_anomaly("CRWD", reason="4-for-1 split, ex 2 July")

    assert runtime.oms.anomalies.is_quarantined("CRWD") is True


def test_clearing_reaches_the_store(qtbot, tmp_path):
    screen, runtime = _build_screen(qtbot, tmp_path)
    screen._declare_anomaly("CRWD", reason="4-for-1 split")

    screen._clear_anomaly("CRWD")

    assert runtime.oms.anomalies.is_quarantined("CRWD") is False


def test_the_declared_anomaly_is_listed(qtbot, tmp_path):
    """A quarantine nobody can see is one nobody clears."""
    screen, runtime = _build_screen(qtbot, tmp_path)
    screen._declare_anomaly("CRWD", reason="4-for-1 split, ex 2 July")

    screen._refresh_anomalies()

    rendered = screen.anomaly_list.toPlainText()
    assert "CRWD" in rendered
    assert "4-for-1 split" in rendered


def test_the_panel_says_declared_is_not_fixed(qtbot, tmp_path):
    """The one failure this feature could introduce is "declared" reading as
    "fixed". The wording is asserted rather than left to review, because a
    reviewer sees it once and an operator sees it every session."""
    screen, _ = _build_screen(qtbot, tmp_path)

    caption = screen.anomaly_caption.text().lower()

    assert "not" in caption
    assert "correct" in caption or "repair" in caption
```

- [ ] **Step 2: Run to verify it fails**

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest tests/presentation/test_risk_console_anomalies.py -v
```
Expected: all 4 FAIL with `AttributeError: 'RiskConsoleScreen' object has no attribute '_declare_anomaly'`.

- [ ] **Step 3: Implement**

Add to `RiskConsoleScreen.__init__`, following the layout style already in the file:

```python
        self.anomaly_caption = QLabel(
            "A declared anomaly explains a difference so the session is not halted. "
            "It does NOT correct the quantity, the entry record, the resting protection "
            "or the ledger - that is still manual."
        )
        self.anomaly_caption.setWordWrap(True)
        self.anomaly_list = QPlainTextEdit()
        self.anomaly_list.setReadOnly(True)
```

Add the three methods:

```python
    def _refresh_anomalies(self) -> None:
        active = self._runtime.oms.anomalies.active()
        if not active:
            self.anomaly_list.setPlainText("No quarantined positions.")
            return
        self.anomaly_list.setPlainText(
            "\n".join(
                f"{a.symbol}  tracked={a.tracked_quantity:g} broker={a.broker_quantity:g}  "
                f"{a.reason}  (declared by {a.declared_by}, "
                f"{a.declared_at:%Y-%m-%d %H:%M} UTC)"
                for a in active
            )
        )

    def _declare_anomaly(self, symbol: str, reason: str) -> None:
        """Binds the declaration to what the broker reports RIGHT NOW.

        Captured here rather than taken from the operator, because the binding
        is what stops one declaration granting a symbol permanent immunity -
        and a hand-typed quantity is exactly the thing that would be typed to
        match whatever silences the alert.
        """
        oms = self._runtime.oms
        tracked = oms.filled_quantities().get(symbol, 0.0)
        broker = 0.0
        for position in getattr(oms, "last_known_positions", lambda: [])():
            if position.symbol == symbol:
                broker = abs(position.quantity)
        oms.anomalies.declare(
            symbol=symbol,
            reason=reason,
            declared_by="operator",
            tracked_quantity=tracked,
            broker_quantity=broker,
        )
        self._refresh_anomalies()

    def _clear_anomaly(self, symbol: str) -> None:
        self._runtime.oms.anomalies.clear(symbol, operator="operator")
        self._refresh_anomalies()
```

**Two things to resolve while implementing, not to guess at:**

1. `oms.filled_quantities()` and a positions accessor may not exist under those names. Read the OMS and use what is there; if tracked quantities are only available as the private `_filled_quantities`, add a small public accessor rather than reaching into it from the presentation layer.
2. The broker read is synchronous here and the OMS's is `async`. If no cached position list exists, the honest options are a cached one populated by the reconciliation poll, or making the declare action async in the same way other console actions handle it. **Do not** block the Qt thread on an `await`.

Wire the declare/clear actions to buttons following `_on_kill_switch_clicked`'s shape, and call `_refresh_anomalies` from the existing `_on_timer_tick` — do not add a second timer.

- [ ] **Step 4: Run tests, lint, commit**

```
& "C:\Claude Programming\.venv\Scripts\python.exe" -m pytest -q
```
Expected: 1,468 passed.

Run the four lint commands, then:

```bash
git add src/qat/presentation/risk_console.py tests/presentation/test_risk_console_anomalies.py
git commit -m "Give the operator somewhere to declare a difference explained"
```

---

## After the plan

Do **not** deploy without asking. Per the standing convention: build and sign freely, always ask before unzipping over `C:\QuantAdvisoryTerminal`, verify by hash, then **launch it in daylight** and confirm the startup lines. A hash proves the right bytes landed, never that they run — M56a passed its hash check and could not start.

The new startup line to look for, when any position is quarantined:

```
N adopted position(s) are QUARANTINED: ...
```

Its absence when nothing is quarantined is correct and expected.

**Still outstanding, with a deadline:** the MNST measurement, spec item 2 — Tuesday 11 August. It is a decision for the operator, not implementation work, and it determines the shape of M39 step 2.
