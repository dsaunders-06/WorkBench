# M39 Corporate Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a forward or reverse split on a held position from Alpaca's
announcements and re-price the resting protective stop before the ex-date open,
so an unadjusted stop cannot liquidate the position as it did on MNST.

**Architecture:** A new domain subsystem, `qat/domain/corporate_actions/`, with
four small units: an announcement source on the broker adapter, a persisted
store deduped on `(symbol, ex_date)`, a detector applying four gates, and an
adjuster carrying the never-tighten invariant. `CorporateActionMonitor` is the
public face and the orchestrator engine. `SignalToOrderBridge` gains one call.
M60's anomaly store is used as designed, never inverted.

**Tech Stack:** Python 3.12, PySide6, alpaca-py 0.43.5, pytest + pytest-asyncio,
pydantic-settings.

**Spec:** `docs/superpowers/specs/2026-08-12-corporate-actions-design.md`

## Global Constraints

- **Every test that builds an OMS must pass its own `data_dir`.** `conftest` sets
  `QAT_DATA_DIR` session-wide and the anomaly store persists there, so one
  declared anomaly leaks a quarantine into every later test.
- **Formats with `black`, not `ruff format`.** Gates are
  `python -m ruff check .`, `python -m black --check .`, `python -m mypy src`,
  `python -m bandit -r src`, all via `.venv/Scripts/python.exe`.
- **Validation freeze:** nothing lands that changes which trades happen or how
  large they are. Shadow mode is the default so this ships as a no-op.
- Ratio is `new_rate / old_rate`. `2.0` is a 2-for-1 forward split; `0.001` is a
  1-for-1000 reverse split.
- Dedupe on `(symbol, ex_date)`, never on `action_id` or a record count.
- Key on `ex_date`, never `payable_date` — CRWD's are 1 and 2 July, in that order.
- Query announcements **per symbol**; `target_symbol` is absent on ~10% of records.
- Never adjust tracked quantity or entry basis from an announcement. Only from an
  observed broker quantity change.
- Plan → approval → implement → verify → commit. Always ask before deploying.

---

### Task 1: Announcement record and persisted store

**Files:**
- Create: `src/qat/domain/corporate_actions/__init__.py`
- Create: `src/qat/domain/corporate_actions/announcements.py`
- Test: `tests/domain/corporate_actions/test_announcement_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Announcement(symbol: str, ex_date: date, ratio: float, action_id: str, payable_date: date | None, fetched_at: datetime)`, frozen dataclass with `slots=True`.
  - `AnnouncementStore(data_dir: str | Path | None)` with
    `remember(announcements: Iterable[Announcement]) -> list[Announcement]`,
    `for_symbol(symbol: str) -> list[Announcement]`,
    `all() -> list[Announcement]`.
  - Filename constant `_FILENAME = "corporate_announcements.json"`.

- [ ] **Step 1: Write the failing test**

```python
"""The announcement record, and why it is deduped the way it is (M39)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from qat.domain.corporate_actions.announcements import Announcement, AnnouncementStore


def _announcement(**kwargs) -> Announcement:
    defaults = dict(
        symbol="SFBS",
        ex_date=date(2026, 8, 21),
        ratio=2.0,
        action_id="ca-1",
        payable_date=date(2026, 8, 20),
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return Announcement(**defaults)


def test_the_same_action_returned_twice_is_stored_once(tmp_path):
    """Alpaca returned one record on the Saturday and two byte-identical ones on
    the Monday. A store keyed on a record COUNT would read that as a second
    action and adjust twice."""
    store = AnnouncementStore(tmp_path)

    store.remember([_announcement()])
    store.remember([_announcement(), _announcement()])

    assert len(store.for_symbol("SFBS")) == 1


def test_dedupe_is_on_symbol_and_ex_date_not_action_id(tmp_path):
    """Same event, different id - the id is stable per Alpaca record, not per
    corporate action, so two records for one event must not become two actions."""
    store = AnnouncementStore(tmp_path)

    store.remember([_announcement(action_id="ca-1")])
    store.remember([_announcement(action_id="ca-2")])

    assert len(store.for_symbol("SFBS")) == 1


def test_a_second_split_on_the_same_symbol_is_a_separate_action(tmp_path):
    store = AnnouncementStore(tmp_path)

    store.remember([_announcement(ex_date=date(2026, 8, 21))])
    store.remember([_announcement(ex_date=date(2026, 11, 2))])

    assert len(store.for_symbol("SFBS")) == 2


def test_it_survives_a_restart(tmp_path):
    """The whole point. A query that fails on ex-date morning must not mean
    acting blind on the one day it matters."""
    AnnouncementStore(tmp_path).remember([_announcement()])

    restored = AnnouncementStore(tmp_path).for_symbol("SFBS")

    assert len(restored) == 1
    assert restored[0].ratio == 2.0
    assert restored[0].ex_date == date(2026, 8, 21)


def test_remember_returns_only_what_was_new(tmp_path):
    """So a caller can log 'first seen' without re-announcing every sweep."""
    store = AnnouncementStore(tmp_path)

    first = store.remember([_announcement()])
    second = store.remember([_announcement()])

    assert [a.symbol for a in first] == ["SFBS"]
    assert second == []


def test_an_unreadable_file_reads_as_empty_not_as_a_crash(tmp_path):
    (tmp_path / "corporate_announcements.json").write_text("{not json", encoding="utf-8")

    assert AnnouncementStore(tmp_path).all() == []


def test_no_data_dir_keeps_everything_in_memory(tmp_path):
    store = AnnouncementStore(None)

    store.remember([_announcement()])

    assert len(store.for_symbol("SFBS")) == 1
    assert not list(tmp_path.iterdir())


def test_the_file_is_json_a_human_can_read(tmp_path):
    AnnouncementStore(tmp_path).remember([_announcement()])

    payload = json.loads((tmp_path / "corporate_announcements.json").read_text(encoding="utf-8"))

    assert payload["announcements"][0]["symbol"] == "SFBS"
    assert payload["announcements"][0]["ex_date"] == "2026-08-21"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/test_announcement_store.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'qat.domain.corporate_actions'`

- [ ] **Step 3: Write minimal implementation**

Create `src/qat/domain/corporate_actions/__init__.py` empty. Then
`announcements.py`:

```python
"""What the broker says is coming, remembered across restarts (M39).

Deduped on `(symbol, ex_date)` rather than on the record id or a count. Alpaca
returned the same MNST announcement once on the Saturday and twice on the
Monday, byte-identical - a detector reading a changing count as a changing
action would adjust the same position twice.

Persisted because the query can fail on exactly the morning it matters. A stop
that needs halving before the open cannot wait for the next successful poll.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "corporate_announcements.json"


@dataclass(frozen=True, slots=True)
class Announcement:
    """One corporate action the broker has published.

    `ratio` is `new_rate / old_rate`: 2.0 is a 2-for-1 forward split, 0.001 a
    1-for-1000 reverse. `payable_date` is carried for the record only - it can
    PRECEDE `ex_date` (CRWD's are 1 and 2 July), so nothing keys on it.
    """

    symbol: str
    ex_date: date
    ratio: float
    action_id: str
    payable_date: date | None
    fetched_at: datetime

    @property
    def key(self) -> tuple[str, date]:
        return (self.symbol, self.ex_date)


class AnnouncementStore:
    """Announcements seen so far, deduped and persisted.

    A store built with no data directory keeps everything in memory, for tests
    and for a monitor constructed without settings. Not a supported production
    configuration.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._path = Path(data_dir) / _FILENAME if data_dir is not None else None
        self._known: dict[tuple[str, date], Announcement] = {}
        self._load()

    def remember(self, announcements: Iterable[Announcement]) -> list[Announcement]:
        """Stores any that are new. Returns only those, so a caller can log
        "first seen" without re-announcing on every sweep."""
        fresh = [a for a in announcements if a.key not in self._known]
        if not fresh:
            return []
        for announcement in fresh:
            self._known[announcement.key] = announcement
        self._save()
        return fresh

    def for_symbol(self, symbol: str) -> list[Announcement]:
        return sorted(
            (a for a in self._known.values() if a.symbol == symbol),
            key=lambda a: a.ex_date,
        )

    def all(self) -> list[Announcement]:
        return sorted(self._known.values(), key=lambda a: (a.symbol, a.ex_date))

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for entry in raw.get("announcements") or []:
                announcement = Announcement(
                    symbol=str(entry["symbol"]),
                    ex_date=date.fromisoformat(entry["ex_date"]),
                    ratio=float(entry["ratio"]),
                    action_id=str(entry["action_id"]),
                    payable_date=(
                        date.fromisoformat(entry["payable_date"])
                        if entry.get("payable_date")
                        else None
                    ),
                    fetched_at=datetime.fromisoformat(entry["fetched_at"]),
                )
                self._known[announcement.key] = announcement
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Could not read %s (%s) - announcements are re-fetched from scratch, and a "
                "failed query this session means no split is known about",
                self._path,
                exc,
            )
            self._known = {}

    def _save(self) -> None:
        if self._path is None:
            return
        payload = {
            "announcements": [
                {
                    "symbol": a.symbol,
                    "ex_date": a.ex_date.isoformat(),
                    "ratio": a.ratio,
                    "action_id": a.action_id,
                    "payable_date": a.payable_date.isoformat() if a.payable_date else None,
                    "fetched_at": a.fetched_at.isoformat(),
                }
                for a in self.all()
            ]
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not write %s - announcements will not survive a restart",
                             self._path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/ -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/corporate_actions tests/domain/corporate_actions
git commit -m "Remember what the broker says is coming, deduped on (symbol, ex_date) (M39)"
```

---

### Task 2: The announcement source on the broker adapter

**Files:**
- Modify: `src/qat/data/broker/adapter.py` (add to the `BrokerAdapter` protocol)
- Modify: `src/qat/data/broker/alpaca_adapter.py` (real implementation)
- Modify: `src/qat/data/broker/mock_broker.py` (test implementation)
- Test: `tests/data/broker/test_announcements_source.py`

**Interfaces:**
- Consumes: `Announcement` from Task 1.
- Produces: `async def announcements(self, symbol: str, since: date, until: date) -> list[Announcement]` on every adapter. `MockBroker.queue_announcement(announcement)` for tests.

- [ ] **Step 1: Write the failing test**

```python
"""The only usable detection source, and its two traps (M39)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.data.broker.mock_broker import MockBroker
from qat.domain.corporate_actions.announcements import Announcement


@pytest.mark.asyncio
async def test_the_mock_returns_what_was_queued():
    broker = MockBroker(seed=1)
    broker.queue_announcement(
        Announcement(
            symbol="SFBS",
            ex_date=date(2026, 8, 21),
            ratio=2.0,
            action_id="ca-1",
            payable_date=date(2026, 8, 20),
            fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
        )
    )

    found = await broker.announcements("SFBS", date(2026, 8, 1), date(2026, 9, 1))

    assert [a.ratio for a in found] == [2.0]


@pytest.mark.asyncio
async def test_it_filters_by_symbol():
    """Per-symbol queries are the design: target_symbol is absent on ~10% of
    records, so a market-wide scan cannot attribute an announcement reliably."""
    broker = MockBroker(seed=1)
    broker.queue_announcement(
        Announcement(
            symbol="SFBS",
            ex_date=date(2026, 8, 21),
            ratio=2.0,
            action_id="ca-1",
            payable_date=None,
            fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
        )
    )

    assert await broker.announcements("AMD", date(2026, 8, 1), date(2026, 9, 1)) == []


@pytest.mark.asyncio
async def test_a_symbol_with_no_announcements_is_empty_not_an_error():
    broker = MockBroker(seed=1)

    assert await broker.announcements("AMD", date(2026, 8, 1), date(2026, 9, 1)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_announcements_source.py -v`
Expected: FAIL, `AttributeError: 'MockBroker' object has no attribute 'queue_announcement'`

- [ ] **Step 3: Write minimal implementation**

In `adapter.py`, add to the `BrokerAdapter` protocol next to `resting_stops`:

```python
    async def announcements(
        self, symbol: str, since: date, until: date
    ) -> list[Announcement]: ...
```

Import `from datetime import date` and the `Announcement` type. If importing
from `qat.domain` into `qat.data` inverts the existing dependency direction,
define `Announcement` in `qat/data/broker/adapter.py` instead and have
`announcements.py` import it from there — check which way the existing imports
run before choosing, and keep one definition only.

In `mock_broker.py`:

```python
        self._announcements: list[Announcement] = []

    def queue_announcement(self, announcement: Announcement) -> None:
        """Test seam. Corporate actions cannot be simulated from a price series,
        so they are placed here explicitly."""
        self._announcements.append(announcement)

    async def announcements(
        self, symbol: str, since: date, until: date
    ) -> list[Announcement]:
        return [
            a for a in self._announcements if a.symbol == symbol and since <= a.ex_date <= until
        ]
```

In `alpaca_adapter.py`:

```python
    async def announcements(
        self, symbol: str, since: date, until: date
    ) -> list[Announcement]:
        """Alpaca's corporate announcements, filtered server-side by symbol.

        `GetCorporateAnnouncementsRequest` accepts a `symbol` filter, which is
        what makes this affordable - unfiltered it returns roughly 1,600 records
        a year. Only split types are requested: this milestone adjusts splits
        and nothing else.

        A forward split is `old_rate=1.0, new_rate=4.0`; the ratio is new/old.
        A reverse split inverts it.
        """
        request = GetCorporateAnnouncementsRequest(
            ca_types=[CorporateActionType.SPLIT],
            since=since,
            until=until,
            symbol=symbol,
        )
        raw = await asyncio.to_thread(self._trading.get_corporate_announcements, request)
        found: list[Announcement] = []
        now = datetime.now(UTC)
        for record in raw or []:
            old_rate = float(getattr(record, "old_rate", 0) or 0)
            new_rate = float(getattr(record, "new_rate", 0) or 0)
            ex_date = getattr(record, "ex_date", None)
            if old_rate <= 0 or new_rate <= 0 or ex_date is None:
                continue
            found.append(
                Announcement(
                    symbol=symbol,
                    ex_date=ex_date,
                    ratio=new_rate / old_rate,
                    action_id=str(getattr(record, "id", "") or ""),
                    payable_date=getattr(record, "payable_date", None),
                    fetched_at=now,
                )
            )
        return found
```

Wrapped in `asyncio.to_thread` because `TradingClient` is synchronous, matching
how the adapter's other calls are made — check an existing method and follow it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/ -v`
Expected: all pass, including the pre-existing adapter tests

- [ ] **Step 5: Commit**

```bash
git add src/qat/data/broker tests/data/broker/test_announcements_source.py
git commit -m "Ask the broker what corporate actions are coming, one symbol at a time (M39)"
```

---

### Task 3: The detector and its four gates

**Files:**
- Create: `src/qat/domain/corporate_actions/detector.py`
- Test: `tests/domain/corporate_actions/test_split_detector.py`

**Interfaces:**
- Consumes: `Announcement`, `AnnouncementStore`.
- Produces:
  - `PendingAction(announcement, position_opened_at, current_stop, adjusted_stop, state, refusal)`, frozen, `slots=True`, with properties `symbol`, `ratio`, `ex_date`.
  - `SplitDetector(store: AnnouncementStore)` with
    `pending(positions: list[Position], stops: dict[str, float], opened_at: dict[str, datetime], next_session: date) -> list[PendingAction]`.
  - Module constants `MIN_RATIO = 1e-4`, `MAX_RATIO = 1e4`.

- [ ] **Step 1: Write the failing test**

```python
"""The gates, each written against the case that demands it (M39)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from qat.data.broker.adapter import Position
from qat.domain.corporate_actions.announcements import Announcement, AnnouncementStore
from qat.domain.corporate_actions.detector import SplitDetector


def _store(*announcements: Announcement) -> AnnouncementStore:
    store = AnnouncementStore(None)
    store.remember(announcements)
    return store


def _split(symbol: str, ex_date: date, ratio: float = 2.0) -> Announcement:
    return Announcement(
        symbol=symbol,
        ex_date=ex_date,
        ratio=ratio,
        action_id=f"ca-{symbol}",
        payable_date=None,
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


def _detect(store, symbol="MNST", opened=datetime(2026, 8, 10, tzinfo=UTC),
            stop=72.68, next_session=date(2026, 8, 11), quantity=8.0):
    detector = SplitDetector(store)
    return detector.pending(
        positions=[Position(symbol=symbol, quantity=quantity, avg_price=91.18)],
        stops={symbol: stop} if stop is not None else {},
        opened_at={symbol: opened},
        next_session=next_session,
    )


def test_the_mnst_case_is_detected():
    """The event that cost $375.23. 2-for-1, ex-date 11 August, bought the 10th,
    stop resting at 72.68."""
    found = _detect(_store(_split("MNST", date(2026, 8, 11))))

    assert [p.symbol for p in found] == ["MNST"]
    assert found[0].ratio == 2.0


def test_crwd_is_not_detected():
    """THE gate that matters. CRWD split 4-for-1 with ex-date 2 July; we hold 16
    bought on 31 July, correctly sized post-split, with a correct resting OCO.
    A detector matching symbol and ratio over a recent window flags this and is
    wrong, and the false positive is in the live book."""
    found = _detect(
        _store(_split("CRWD", date(2026, 7, 2), ratio=4.0)),
        symbol="CRWD",
        opened=datetime(2026, 7, 31, tzinfo=UTC),
        stop=163.32,
        next_session=date(2026, 8, 13),
        quantity=16.0,
    )

    assert found == []


def test_a_split_further_out_than_the_next_session_waits():
    found = _detect(
        _store(_split("MNST", date(2026, 11, 2))),
        next_session=date(2026, 8, 13),
    )

    assert found == []


def test_a_split_on_the_next_session_is_acted_on():
    found = _detect(
        _store(_split("MNST", date(2026, 8, 13))),
        next_session=date(2026, 8, 13),
    )

    assert len(found) == 1


def test_a_reverse_split_of_one_for_a_thousand_is_kept():
    """ratio 0.001. An earlier draft bounded the ratio at 0.01 and would have
    thrown this away - the ROADMAP records old_rate=1000.0, new_rate=1.0 as a
    real observed shape."""
    found = _detect(_store(_split("MNST", date(2026, 8, 11), ratio=0.001)))

    assert len(found) == 1
    assert found[0].ratio == 0.001


def test_a_ratio_of_one_is_not_a_split():
    assert _detect(_store(_split("MNST", date(2026, 8, 11), ratio=1.0))) == []


def test_an_absurd_ratio_is_refused():
    assert _detect(_store(_split("MNST", date(2026, 8, 11), ratio=1e9))) == []


def test_a_position_with_no_resting_stop_has_nothing_to_adjust():
    assert _detect(_store(_split("MNST", date(2026, 8, 11))), stop=None) == []


def test_a_symbol_that_is_not_held_is_ignored():
    detector = SplitDetector(_store(_split("SFBS", date(2026, 8, 21))))

    found = detector.pending(
        positions=[Position(symbol="MNST", quantity=8.0, avg_price=91.18)],
        stops={"MNST": 72.68},
        opened_at={"MNST": datetime(2026, 8, 10, tzinfo=UTC)},
        next_session=date(2026, 8, 21),
    )

    assert found == []


def test_a_position_with_no_known_open_date_is_skipped_not_guessed():
    """Without an open date the CRWD gate cannot be applied at all, and applying
    no gate is how CRWD gets adjusted wrongly."""
    detector = SplitDetector(_store(_split("MNST", date(2026, 8, 11))))

    found = detector.pending(
        positions=[Position(symbol="MNST", quantity=8.0, avg_price=91.18)],
        stops={"MNST": 72.68},
        opened_at={},
        next_session=date(2026, 8, 11),
    )

    assert found == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/test_split_detector.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'qat.domain.corporate_actions.detector'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Which held positions have a split coming, and which do not (M39).

Four gates. The first is the whole reason automatic detection was deferred in
M60: CRWD split 4-for-1 with ex-date 2 July and we bought on 31 July, so a
detector matching symbol and ratio over a recent window flags a position that is
already correctly sized. That false positive is in the live book.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from qat.data.broker.adapter import Position
from qat.domain.corporate_actions.announcements import Announcement, AnnouncementStore

logger = logging.getLogger(__name__)

# Wide on purpose: a real 1-for-1000 reverse split is ratio 0.001, and the
# ROADMAP records old_rate=1000.0, new_rate=1.0 as an observed shape.
MIN_RATIO = 1e-4
MAX_RATIO = 1e4


@dataclass(frozen=True, slots=True)
class PendingAction:
    announcement: Announcement
    position_opened_at: datetime
    current_stop: float | None
    adjusted_stop: float | None = None
    state: str = "pending"
    refusal: str | None = None

    @property
    def symbol(self) -> str:
        return self.announcement.symbol

    @property
    def ratio(self) -> float:
        return self.announcement.ratio

    @property
    def ex_date(self) -> date:
        return self.announcement.ex_date


class SplitDetector:
    def __init__(self, store: AnnouncementStore) -> None:
        self.store = store

    def pending(
        self,
        positions: list[Position],
        stops: dict[str, float],
        opened_at: dict[str, datetime],
        next_session: date,
    ) -> list[PendingAction]:
        found: list[PendingAction] = []
        for position in positions:
            if abs(position.quantity) <= 0:
                continue
            symbol = position.symbol
            stop = stops.get(symbol)
            if stop is None:
                continue  # nothing resting, so nothing to adjust
            opened = opened_at.get(symbol)
            if opened is None:
                # The CRWD gate cannot be applied without an open date, and
                # applying no gate is how CRWD gets adjusted wrongly.
                logger.debug("No open date for %s - skipped rather than guessed", symbol)
                continue
            for announcement in self.store.for_symbol(symbol):
                if not self._is_actionable(announcement, opened, next_session):
                    continue
                found.append(
                    PendingAction(
                        announcement=announcement,
                        position_opened_at=opened,
                        current_stop=stop,
                    )
                )
        return found

    def _is_actionable(
        self, announcement: Announcement, opened: datetime, next_session: date
    ) -> bool:
        if announcement.ex_date <= opened.date():
            return False  # the CRWD gate
        if announcement.ex_date > next_session:
            return False  # not yet
        ratio = announcement.ratio
        if ratio == 1.0 or not (MIN_RATIO < ratio < MAX_RATIO):
            logger.warning(
                "Ignoring a %s announcement for %s with ratio %g - outside the plausible "
                "range %g to %g, so it is bad data rather than a split",
                announcement.ex_date,
                announcement.symbol,
                ratio,
                MIN_RATIO,
                MAX_RATIO,
            )
            return False
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/corporate_actions/detector.py tests/domain/corporate_actions/test_split_detector.py
git commit -m "Gate split detection on the case that is already in the book (M39)"
```

---

### Task 4: The adjuster and the never-tighten invariant

**Files:**
- Create: `src/qat/domain/corporate_actions/adjuster.py`
- Test: `tests/domain/corporate_actions/test_stop_adjuster.py`

**Interfaces:**
- Consumes: `PendingAction`.
- Produces: `StopAdjuster(mode: str)` with
  `assess(action: PendingAction, price: float, pre_action_price: float) -> PendingAction`,
  returning a copy whose `adjusted_stop`, `state` and `refusal` are filled in.
  States are `"shadowed"`, `"applied"`, `"refused"`. Constant
  `_DISTANCE_TOLERANCE = 1e-3`.

`assess` computes and judges; it never places. Placing is the monitor's job, so
the invariant can be tested without a broker.

- [ ] **Step 1: Write the failing test**

```python
"""The invariant, checked against the numbers that produced it (M39)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.adjuster import StopAdjuster
from qat.domain.corporate_actions.detector import PendingAction


def _action(ratio: float = 2.0, stop: float = 72.68) -> PendingAction:
    return PendingAction(
        announcement=Announcement(
            symbol="MNST",
            ex_date=date(2026, 8, 11),
            ratio=ratio,
            action_id="ca-1",
            payable_date=None,
            fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
        ),
        position_opened_at=datetime(2026, 8, 10, tzinfo=UTC),
        current_stop=stop,
    )


def test_the_mnst_stop_is_halved():
    """72.68 / 2 = 36.34. This is the adjustment that was never made."""
    assessed = StopAdjuster("act").assess(_action(), price=46.30, pre_action_price=91.18)

    assert assessed.adjusted_stop == 36.34
    assert assessed.state == "applied"


def test_the_mnst_adjustment_satisfies_the_invariant():
    """Before: (91.18 - 72.68)/91.18 = 20.3%. After: (46.30 - 36.34)/46.30 =
    21.5%. The correct adjustment must be ADMITTED, or the guard is useless."""
    assessed = StopAdjuster("act").assess(_action(), price=46.30, pre_action_price=91.18)

    assert assessed.refusal is None


def test_a_stop_that_would_sit_above_the_market_is_refused():
    """An inverted ratio: 0.5 supplied for a forward split gives 145.36 against
    a 46.30 market. That is a market order wearing a stop's clothing, and it is
    exactly the MNST failure."""
    assessed = StopAdjuster("act").assess(_action(ratio=0.5), price=46.30, pre_action_price=91.18)

    assert assessed.state == "refused"
    assert assessed.refusal is not None
    assert "above" in assessed.refusal


def test_an_adjustment_that_tightens_the_stop_is_refused():
    """A ratio that leaves the stop much closer to price than it started is
    suspect, and tightening is the direction that liquidates."""
    assessed = StopAdjuster("act").assess(
        _action(ratio=2.0, stop=50.0), price=46.30, pre_action_price=91.18
    )

    assert assessed.state == "refused"
    assert "tighten" in assessed.refusal


def test_a_reverse_split_widens_the_stop_in_price_terms():
    """1-for-10: ratio 0.1, price ten times higher, stop ten times higher."""
    assessed = StopAdjuster("act").assess(
        _action(ratio=0.1, stop=72.68), price=911.80, pre_action_price=91.18
    )

    assert assessed.adjusted_stop == 726.80
    assert assessed.state == "applied"


def test_shadow_mode_reaches_a_verdict_but_never_applies():
    assessed = StopAdjuster("shadow").assess(_action(), price=46.30, pre_action_price=91.18)

    assert assessed.adjusted_stop == 36.34
    assert assessed.state == "shadowed"


def test_shadow_mode_still_refuses_what_act_mode_would_refuse():
    """Otherwise the shadow period teaches nothing about the guard."""
    assessed = StopAdjuster("shadow").assess(
        _action(ratio=0.5), price=46.30, pre_action_price=91.18
    )

    assert assessed.state == "refused"


def test_an_action_with_no_current_stop_is_refused_not_crashed():
    assessed = StopAdjuster("act").assess(
        _action(stop=None), price=46.30, pre_action_price=91.18
    )

    assert assessed.state == "refused"


def test_a_zero_price_is_refused():
    assessed = StopAdjuster("act").assess(_action(), price=0.0, pre_action_price=91.18)

    assert assessed.state == "refused"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/test_stop_adjuster.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""What the stop becomes, and the two guards it must pass (M39).

The asymmetry is deliberate. A wrong ratio that leaves the stop too FAR away
costs more if the position runs against us; a wrong ratio that leaves it too
CLOSE liquidates on contact. One is a worse loss, the other is a guaranteed one,
so both guards fail in the same direction: refuse, and say why.

Computes and judges. It never places - the monitor does that, so the invariant
can be tested without a broker.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from qat.domain.corporate_actions.detector import PendingAction

logger = logging.getLogger(__name__)

SHADOW = "shadow"
ACT = "act"

# A split preserves relative stop distance exactly, so this only absorbs
# rounding and the drift between the pre-action price and the current one.
_DISTANCE_TOLERANCE = 1e-3


class StopAdjuster:
    def __init__(self, mode: str = SHADOW) -> None:
        self.mode = mode

    def assess(
        self, action: PendingAction, price: float, pre_action_price: float
    ) -> PendingAction:
        stop = action.current_stop
        if stop is None or stop <= 0:
            return self._refuse(action, "no resting stop to adjust")
        if price <= 0 or pre_action_price <= 0:
            return self._refuse(action, "no usable price to judge the adjustment against")

        adjusted = round(stop / action.ratio, 2)

        if adjusted >= price:
            return self._refuse(
                action,
                f"the adjusted stop {adjusted:.2f} is at or above the {price:.2f} market - "
                f"placing it would be a market order rather than protection",
                adjusted,
            )

        before = (pre_action_price - stop) / pre_action_price
        after = (price - adjusted) / price
        if after < before - _DISTANCE_TOLERANCE:
            return self._refuse(
                action,
                f"the adjustment would tighten the stop from {before:.2%} to {after:.2%} of "
                f"price, and tightening is the direction that liquidates",
                adjusted,
            )

        state = ACT and "applied" if self.mode == ACT else "shadowed"
        return replace(action, adjusted_stop=adjusted, state=state, refusal=None)

    def _refuse(
        self, action: PendingAction, reason: str, adjusted: float | None = None
    ) -> PendingAction:
        logger.warning(
            "Split adjustment on %s REFUSED: %s. The stop is left as it is and the position "
            "is quarantined - an unadjusted stop is dangerous, and a wrongly adjusted one is "
            "worse.",
            action.symbol,
            reason,
        )
        return replace(action, adjusted_stop=adjusted, state="refused", refusal=reason)
```

Note: `state = ACT and "applied" if ... else ...` is deliberately not the
expression to ship. Write it plainly:

```python
        state = "applied" if self.mode == ACT else "shadowed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/corporate_actions/adjuster.py tests/domain/corporate_actions/test_stop_adjuster.py
git commit -m "Never place a stop that could liquidate on contact (M39)"
```

---

### Task 5: The config setting

**Files:**
- Modify: `src/qat/config.py`
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Produces: `settings.corporate_action_mode: str`, default `"shadow"`, validated to one of `{"shadow", "act"}`. Env var `QAT_CORPORATE_ACTION_MODE`.

- [ ] **Step 1: Write the failing test**

```python
def test_corporate_action_mode_defaults_to_shadow():
    """The default is what makes M39's first deployment a no-op, which is what
    keeps it inside the freeze on arrival."""
    assert Settings(_env_file=None).corporate_action_mode == "shadow"


def test_corporate_action_mode_rejects_an_unknown_value():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, corporate_action_mode="maybe")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -k corporate_action -v`
Expected: FAIL, `AttributeError` / no such field

- [ ] **Step 3: Write minimal implementation**

Beside the other rail settings in `config.py`, following the file's existing
`Field` and `Literal` conventions:

```python
    # Shadow by default (M39). In shadow the detector, the ratio and the
    # invariant all run and log what they WOULD place, and no order is
    # modified. Promotion to "act" is a deliberate config change, and it is
    # what turns this from a recorder into a participant.
    corporate_action_mode: Literal["shadow", "act"] = "shadow"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py -k corporate_action -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/qat/config.py tests/test_config.py
git commit -m "Ship M39 in shadow mode by default (M39)"
```

---

### Task 6: The monitor — wiring, and the one place that places an order

**Files:**
- Create: `src/qat/domain/corporate_actions/monitor.py`
- Test: `tests/domain/corporate_actions/test_monitor.py`

**Interfaces:**
- Consumes: `AnnouncementStore`, `SplitDetector`, `StopAdjuster`, `PositionAnomalyStore`, the OMS/broker.
- Produces: `CorporateActionMonitor(oms, settings, entries_source, anomalies, store=None)` with:
  - `async def refresh() -> list[PendingAction]` — query, remember, detect, assess, and in `act` mode place.
  - `pending_action(symbol: str) -> PendingAction | None`
  - `pending_actions() -> list[PendingAction]`
  - `async def start() -> None` / `async def stop() -> None` for the orchestrator.

`entries_source` is a callable returning `dict[str, datetime]` of symbol to
`opened_at`, supplied by `SignalToOrderBridge` so the monitor does not reach
into it.

- [ ] **Step 1: Write the failing test**

```python
"""The monitor end to end, including the two things it must not do (M39)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.monitor import CorporateActionMonitor
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, announcements: list[Announcement]) -> None:
        self._announcements = announcements
        self.modified: list[tuple[str, dict]] = []

    async def positions(self):
        return [Position(symbol="MNST", quantity=8.0, avg_price=91.18)]

    async def resting_stops(self):
        return {"MNST": 72.68}

    async def announcements(self, symbol, since, until):
        return [a for a in self._announcements if a.symbol == symbol]

    async def recent_fills(self, since):
        return []

    async def modify_order(self, order_id, **changes):
        self.modified.append((order_id, changes))
        return None

    async def get_market_data(self, symbol):
        return {"price": 46.30}


def _monitor(tmp_path, mode: str):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), corporate_action_mode=mode)
    bus = EventBus()
    switch = KillSwitch()
    broker = _Broker(
        [
            Announcement(
                symbol="MNST",
                ex_date=date(2026, 8, 11),
                ratio=2.0,
                action_id="ca-1",
                payable_date=None,
                fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
            )
        ]
    )
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus,
              settings=settings)
    monitor = CorporateActionMonitor(
        oms=oms,
        settings=settings,
        entries_source=lambda: {"MNST": datetime(2026, 8, 10, tzinfo=UTC)},
        anomalies=oms.anomalies,
    )
    return broker, monitor


@pytest.mark.asyncio
async def test_shadow_mode_detects_and_places_nothing(tmp_path):
    broker, monitor = _monitor(tmp_path, "shadow")

    found = await monitor.refresh()

    assert [p.symbol for p in found] == ["MNST"]
    assert found[0].adjusted_stop == 36.34
    assert found[0].state == "shadowed"
    assert broker.modified == [], "shadow mode placed an order"


@pytest.mark.asyncio
async def test_the_pending_action_is_queryable_by_symbol(tmp_path):
    """R1 and R2 both depend on this being the single source of truth."""
    _broker, monitor = _monitor(tmp_path, "shadow")
    await monitor.refresh()

    assert monitor.pending_action("MNST") is not None
    assert monitor.pending_action("AMD") is None


@pytest.mark.asyncio
async def test_a_failed_query_falls_back_to_what_was_persisted(tmp_path):
    """The morning the query fails is the morning it matters."""
    broker, monitor = _monitor(tmp_path, "shadow")
    await monitor.refresh()

    async def _raise(symbol, since, until):
        raise ConnectionError("broker unreachable")

    broker.announcements = _raise
    found = await monitor.refresh()

    assert [p.symbol for p in found] == ["MNST"]


@pytest.mark.asyncio
async def test_the_announcement_is_remembered_across_monitors(tmp_path):
    _broker, monitor = _monitor(tmp_path, "shadow")
    await monitor.refresh()

    _broker2, second = _monitor(tmp_path, "shadow")

    assert second.store.for_symbol("MNST") != []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/test_monitor.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`monitor.py` composes the three units, and is the only place that touches the
broker. Its `refresh()`:

1. reads positions and resting stops from the OMS's broker;
2. for each held symbol, queries `announcements` over
   `today - 5 days` to `today + 45 days`, catching every exception and
   continuing (the store is the fallback);
3. `store.remember(...)`, logging anything newly seen at WARNING with symbol,
   ex-date and ratio;
4. computes `next_session` from `market_calendar.next_open(market)`, refusing
   every action if it returns `None`;
5. runs the detector, then the adjuster per action, using `get_market_data` for
   the current price and the position's `avg_price` as `pre_action_price`;
6. in `act` mode only, and only for a `state == "applied"` action, calls
   `modify_order` on the resting stop's order id, then records the outcome;
7. for any `state == "refused"` action, declares an anomaly through
   `anomalies.declare(...)` with `declared_by="corporate-action-monitor"`;
8. stores the results so `pending_action` / `pending_actions` can serve them.

`start()` creates a task looping on `settings.protection_sweep_seconds` and
calling `refresh()`; `stop()` cancels it. Follow `SignalToOrderBridge`'s
`_sweep_protection` for the shape, including its exception handling — a sweep
that raises must not end the session.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/corporate_actions/monitor.py tests/domain/corporate_actions/test_monitor.py
git commit -m "Query, detect, assess, and in act mode re-price (M39)"
```

---

### Task 7: Register the engine and stop the re-arm fighting it

**Files:**
- Modify: `src/qat/presentation/runtime.py` (build and register the monitor)
- Modify: `src/qat/domain/oms/signal_bridge.py` (`rearm_protective_stops` asks the monitor first)
- Test: `tests/safety/test_rearm_defers_to_corporate_actions.py`

**Interfaces:**
- Consumes: `CorporateActionMonitor.pending_action`.
- Produces: `runtime.corporate_action_monitor` attribute; `SignalToOrderBridge(corporate_actions=...)` optional keyword defaulting to `None`.

- [ ] **Step 1: Write the failing test**

```python
"""Re-arming must not fight the adjustment (M39).

`rearm_protective_stops` proposes a stop from the ENTRY record, which is the
pre-split level. On a symbol with a split pending, that is precisely the number
that liquidates the position - so the re-arm defers.
"""

@pytest.mark.asyncio
async def test_rearm_skips_a_symbol_with_a_pending_action(tmp_path):
    bridge = _bridge_with_pending_split(tmp_path, symbol="MNST")

    rearmed = await bridge.rearm_protective_stops()

    assert "MNST" not in rearmed


@pytest.mark.asyncio
async def test_rearm_says_why_it_skipped(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        bridge = _bridge_with_pending_split(tmp_path, symbol="MNST")
        await bridge.rearm_protective_stops()

    assert any("split" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_rearm_is_unchanged_for_everything_else(tmp_path):
    """The guard must be narrow. A symbol with no pending action re-arms exactly
    as it did before."""
    bridge = _bridge_with_pending_split(tmp_path, symbol="MNST", also_holds="AMD")

    rearmed = await bridge.rearm_protective_stops()

    assert "AMD" in rearmed
```

Write `_bridge_with_pending_split` in the test module: build the bridge with its
own `data_dir`, hold two positions, give one an entry record and a pending action
via a stub monitor exposing only `pending_action(symbol)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/safety/test_rearm_defers_to_corporate_actions.py -v`
Expected: FAIL — `SignalToOrderBridge` takes no `corporate_actions` argument

- [ ] **Step 3: Write minimal implementation**

Add the optional constructor keyword, store it, and in `rearm_protective_stops`,
beside the existing quarantine check:

```python
            pending = (
                self.corporate_actions.pending_action(position.symbol)
                if self.corporate_actions is not None
                else None
            )
            if pending is not None:
                deferred.append(position.symbol)
                continue
```

with a WARNING naming the symbols and saying the recorded stop is the pre-split
level. Register the monitor in `runtime.py` alongside the other engines, after
the OMS and the bridge exist, and pass `entries_source=bridge.entry_open_dates`.
Add that small accessor to the bridge returning
`{symbol: entry.opened_at for symbol, entry in self._entries.items()}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/safety/ -v`
Expected: all pass, including the existing re-arm tests

- [ ] **Step 5: Commit**

```bash
git add src/qat/presentation/runtime.py src/qat/domain/oms/signal_bridge.py tests/safety/test_rearm_defers_to_corporate_actions.py
git commit -m "Keep the re-arm from restoring the pre-split stop (M39)"
```

---

### Task 8: Refuse new entries while an action is pending (R2)

**Files:**
- Modify: `src/qat/domain/oms/oms.py` (`submit_order`, beside the anomaly check)
- Test: `tests/safety/test_entries_refused_on_pending_action.py`

**Interfaces:**
- Consumes: `CorporateActionMonitor.pending_action`.
- Produces: `OMS(corporate_actions=...)` optional keyword defaulting to `None`.

- [ ] **Step 1: Write the failing test**

```python
"""A pending split expires the size basis, so entries wait (M39).

Refusing strictly MORE is what keeps this inside the freeze - the same argument
M60 was accepted under.
"""

@pytest.mark.asyncio
async def test_an_entry_is_refused_while_a_split_is_pending(tmp_path):
    oms = _oms_with_pending_split(tmp_path, symbol="MNST")

    order = await oms.submit_order(_candidate("MNST"), 100_000.0, {}, {})

    assert order.status == "rejected"
    assert "split" in (order.rejection_reason or "").lower()


@pytest.mark.asyncio
async def test_an_exit_is_still_allowed(tmp_path):
    """A rail whose effect is 'the account may not de-risk' is a broken rail."""
    oms = _oms_with_pending_split(tmp_path, symbol="MNST")

    order = await oms.submit_exit_order("MNST", quantity=8.0, price=46.30)

    assert order.status != "rejected"


@pytest.mark.asyncio
async def test_another_symbol_is_unaffected(tmp_path):
    oms = _oms_with_pending_split(tmp_path, symbol="MNST")

    order = await oms.submit_order(_candidate("AMD"), 100_000.0, {}, {})

    assert order.status != "rejected"


@pytest.mark.asyncio
async def test_the_refusal_reaches_the_journal(tmp_path):
    """R2: the reason has to be in risk_decisions.csv, not only in a log line."""
    oms = _oms_with_pending_split(tmp_path, symbol="MNST")

    await oms.submit_order(_candidate("MNST"), 100_000.0, {}, {})

    rows = (tmp_path / "risk_decisions.csv").read_text(encoding="utf-8")
    assert "MNST" in rows
```

Check the existing rejection-reason attribute name on `Order` before writing
these — use whatever `_new_rejected_order` actually sets.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/safety/test_entries_refused_on_pending_action.py -v`
Expected: FAIL — `OMS` takes no `corporate_actions` argument

- [ ] **Step 3: Write minimal implementation**

In `submit_order`, directly after the existing anomaly check so the ordering of
refusals stays stable:

```python
        pending = (
            self.corporate_actions.pending_action(candidate.symbol)
            if self.corporate_actions is not None
            else None
        )
        if pending is not None:
            return self._new_rejected_order(
                candidate,
                0.0,
                f"corporate action pending - a {pending.ratio:g}-for-1 split with ex-date "
                f"{pending.ex_date} changes the size basis, so an entry now would be sized "
                f"against a number with a known expiry",
            )
```

Nothing is added to `submit_exit_order`. Exits stay allowed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/safety/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/oms.py tests/safety/test_entries_refused_on_pending_action.py
git commit -m "Refuse an entry sized against a basis about to change (M39)"
```

---

### Task 9: The visibility contract, and the test that enforces it (R1)

**Files:**
- Modify: `src/qat/presentation/dashboard.py`, `risk_console.py`, `blotter.py`, `workbench.py`, `screener.py`, `ai_advisor.py`
- Modify: `src/qat/domain/performance/reports.py` (daily report section)
- Modify: `tests/domain/test_computed_values_have_readers.py` (add the module to `_WATCHED`)
- Create: `tests/domain/test_corporate_action_has_every_reader.py`
- Test: `tests/presentation/test_corporate_action_visibility.py`

**Interfaces:**
- Consumes: `CorporateActionMonitor.pending_action`, `.pending_actions()`.
- Produces: nothing new.

The enforcement is two tests, not one. `test_computed_values_have_readers`
asserts a `@property` is read *somewhere in `src/`*, which is a weaker claim than
"read by the Blotter" — `is_synthetic` had a reader from M40 and still took two
milestones to reach the operator.

- [ ] **Step 1: Write the failing test**

```python
"""Every screen where this matters reads it, and a test says so (R1, M39).

The generic guard in test_computed_values_have_readers asserts that SOMETHING in
src/ reads a computed value. That is not this claim. `is_synthetic` had a reader
from M40 - the language model - and the operator did not see it until M72. So
this names the modules and fails if one of them stops reading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import qat

_SRC = Path(qat.__file__).parent

_MUST_READ = (
    "presentation/dashboard.py",
    "presentation/risk_console.py",
    "presentation/blotter.py",
    "presentation/workbench.py",
    "presentation/screener.py",
    "presentation/ai_advisor.py",
    "domain/performance/reports.py",
)


@pytest.mark.parametrize("module", _MUST_READ)
def test_the_module_reads_the_pending_action(module):
    source = (_SRC / module).read_text(encoding="utf-8")

    assert "pending_action" in source, (
        f"{module} does not read pending_action. A corporate action visible on one screen "
        f"and not the others is the defect this project has already found five times."
    )


def test_the_list_names_modules_that_exist():
    """An allowlist naming a file that has been renamed is how a guard quietly
    stops covering anything."""
    for module in _MUST_READ:
        assert (_SRC / module).exists(), module
```

Plus, in `tests/presentation/test_corporate_action_visibility.py`, a rendering
test per screen asserting the symbol and ex-date actually appear in the widget's
text — the file-scan above proves the reference exists, not that it renders.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/test_corporate_action_has_every_reader.py -v`
Expected: FAIL for all seven modules

- [ ] **Step 3: Write minimal implementation**

Wire each reader, following each screen's existing conventions:

- **Dashboard**: a banner beside the adopted-positions banner, naming symbol,
  ratio, ex-date and whether the mode is shadow or act.
- **Risk Console**: a row per pending action with current stop, adjusted stop
  and state, plus the permanent line saying a declared anomaly is contained and
  not repaired.
- **Blotter**: the adjustment as an order event carrying its reason.
- **Workbench** and **Screener**: a caveat on the symbol.
- **AI Advisor**: the pending action in the context handed to the model.
- **reports.py**: a daily-report section listing pending actions.

Add `"domain/corporate_actions/detector.py"` to `_WATCHED` in
`test_computed_values_have_readers.py` so `PendingAction`'s properties are
covered by the generic rule too.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/test_corporate_action_has_every_reader.py tests/presentation/ tests/domain/test_computed_values_have_readers.py -v`
Expected: all pass

- [ ] **Step 5: Render it, do not trust the suite**

Run the app or the offscreen render and LOOK at the Dashboard banner and the
Risk Console rows. Screenshotting has found an orphaned grid row, an off-scale
font, stranded labels, "Grew -0.0% a year", a notice floating in an empty screen
and a truncated column, and every one of those had a passing suite.

- [ ] **Step 6: Commit**

```bash
git add src/qat/presentation src/qat/domain/performance/reports.py tests/domain/test_corporate_action_has_every_reader.py tests/presentation/test_corporate_action_visibility.py tests/domain/test_computed_values_have_readers.py
git commit -m "Make a pending corporate action visible on every screen it bears on (M39, R1)"
```

---

### Task 10: Phase 2 — the observed quantity change

**Files:**
- Modify: `src/qat/domain/corporate_actions/monitor.py`
- Test: `tests/domain/corporate_actions/test_observed_share_delivery.py`

**Interfaces:**
- Consumes: `PositionAnomalyStore.declare`, `.explains`.
- Produces: `async def reconcile_observed(tracked: dict[str, float]) -> list[str]` on the monitor, returning symbols it acted on.

Deliberately incomplete, and the spec says why: this path has **zero
observations**. MNST never reached the share adjustment.

- [ ] **Step 1: Write the failing test**

```python
"""When the shares actually arrive (M39, Phase 2).

Never exercised against a real event. MNST's stop closed the position before the
share side landed, so every assertion here is built from the announcement's
arithmetic rather than from an observation - which is exactly why the ledger
correction is logged and not applied.
"""

@pytest.mark.asyncio
async def test_a_doubling_that_matches_the_ratio_is_declared_explained(tmp_path):
    monitor, oms = await _with_delivered_shares(tmp_path, tracked=8.0, broker=16.0, ratio=2.0)

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == ["MNST"]
    assert oms.anomalies.is_quarantined("MNST")
    assert oms.anomalies.explains("MNST", 16.0)


@pytest.mark.asyncio
async def test_a_change_that_does_not_match_the_ratio_is_left_to_the_kill_switch(tmp_path):
    """8 to 17 is not a 2-for-1. Declaring it explained would grant immunity to
    a genuine divergence."""
    monitor, oms = await _with_delivered_shares(tmp_path, tracked=8.0, broker=17.0, ratio=2.0)

    acted = await monitor.reconcile_observed({"MNST": 8.0})

    assert acted == []
    assert not oms.anomalies.is_quarantined("MNST")


@pytest.mark.asyncio
async def test_the_stop_quantity_is_raised_to_cover_the_whole_holding(tmp_path):
    """8 shares of protection against 16 held leaves half the position naked."""
    monitor, oms = await _with_delivered_shares(tmp_path, tracked=8.0, broker=16.0, ratio=2.0)

    await monitor.reconcile_observed({"MNST": 8.0})

    assert oms.broker.modified, "the resting stop's quantity was never raised"
    assert oms.broker.modified[-1][1]["quantity"] == 16.0


@pytest.mark.asyncio
async def test_the_ledger_basis_correction_is_logged_and_not_applied(tmp_path, caplog):
    """The deliberate boundary. Zero observations of this path, so the record
    rewrite stays manual as the CVS and MNST corrections were."""
    monitor, _oms = await _with_delivered_shares(tmp_path, tracked=8.0, broker=16.0, ratio=2.0)

    with caplog.at_level("WARNING"):
        await monitor.reconcile_observed({"MNST": 8.0})

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "45.59" in messages, "the correction it would make is not stated"
    assert "not been applied" in messages or "manual" in messages
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/test_observed_share_delivery.py -v`
Expected: FAIL, no `reconcile_observed`

- [ ] **Step 3: Write minimal implementation**

`reconcile_observed(tracked)` compares each tracked quantity against the
broker's. Where they differ and a pending or recent announcement's ratio
explains the change within tolerance, it declares the anomaly through M60,
raises the resting stop's quantity via `modify_order`, and logs the basis
correction it would make — `entry_price / ratio`, named explicitly — stating
that it has NOT been applied. Where the ratio does not explain the change it
does nothing, leaving reconciliation to halt as it should.

In `act` mode only for the `modify_order` call; in shadow it logs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/corporate_actions/ -v`
Expected: all pass

- [ ] **Step 5: Full verification**

```bash
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m bandit -r src -q
```

- [ ] **Step 6: Commit and record the milestone**

```bash
git add -A
git commit -m "Adjust protection when the shares actually arrive, and log the rest (M39)"
```

Then add the M39 section to `ROADMAP.md` and update `docs/HANDOFF.md`, including
that the mode ships as `shadow` and what promoting it to `act` requires.

---

## Self-Review

**Spec coverage:** scope (Task 3 gates, splits only), R1 (Task 9), R2 (Task 8),
architecture (Tasks 1-6), data model (Tasks 1, 3), detection gating (Task 3),
Phase 1 and the invariant (Task 4), Phase 2 (Task 10), shadow mode (Tasks 4-6),
freeze position (Task 5's default plus Task 8's refuse-more), testing (every
task). The `next_open` returning `None` case is Task 6 step 3 item 4.

**Placeholders:** none. Task 6 and Task 10 describe `refresh()` and
`reconcile_observed()` as numbered behaviour rather than full code, because both
compose units whose signatures are fixed in Tasks 1-4 and the composition is
mechanical; every name they call is defined in an earlier task's Interfaces
block.

**Type consistency:** `pending_action` singular for one symbol, `pending_actions`
plural for all, used identically in Tasks 6-9. `assess` returns a `PendingAction`
throughout. `ratio` is `new/old` everywhere. States are exactly `pending`,
`shadowed`, `applied`, `refused`.

**One deliberate correction carried in:** Task 4's code block shows a wrong
expression for `state` and then the plain replacement immediately beneath it.
Ship the plain one.
