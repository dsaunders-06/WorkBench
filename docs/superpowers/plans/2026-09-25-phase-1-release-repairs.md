# Phase 1 Release Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the complete-review blockers so one broker execution is preserved exactly once across late identity resolution and restart, while startup and repair tooling leave uncertain evidence unchanged.

**Architecture:** Extend `BrokerFill` with the application order reference, resolve every receipt to one canonical execution identity in the OMS, and persist aliases with cumulative fill state before retiring order identity. Make the ledger, entry store and correction tooling fail closed at their existing boundaries, then prepare a distinct M176 release checkpoint without deploying or launching it.

**Tech Stack:** Python 3.12, asyncio, dataclasses, JSON/CSV atomic replacement, PySide6/qasync, Windows `msvcrt` locking with POSIX `fcntl` compatibility for tests, pytest/pytest-asyncio, Ruff, Black, Mypy and Bandit.

**Spec:** `docs/superpowers/specs/2026-09-25-phase-1-release-repair-design.md`

## Global Constraints

- Do not modify `master`; work only on `recovery/phase-1-safety-and-truth`.
- Do not change strategy selection, signals, risk sizing, thresholds or autonomy policy.
- Do not connect to IBKR, launch QAT, deploy, merge or change operational configuration/data.
- Tests use isolated `tmp_path`/`QAT_HOME` locations and fake brokers.
- Missing evidence halts or preserves a pending receipt; it is never inferred.
- Existing valid legacy entry rows and existing fill-state files remain readable.
- Each task follows red-green-refactor, focused verification and its own commit.

## Review Focus

- An IBKR execution with a valid `orderRef` after a fresh adapter restart resolves without the adapter's process-local `_orders` map; Task 1 pins this.
- A completed identity retired before a duplicate broker poll still deduplicates through durable aliases; Task 2 pins this.
- A sell that partly matches lots and then has an unmatched residual writes no partial ledger image and remains pending; Task 3 pins this.
- A current-schema ledger remains byte-for-byte unchanged during stable and unstable startup; Task 4 pins this.
- A stale lock file with no operating-system owner does not prevent QAT or the correction tool from acquiring the lock; Task 6 pins this.

---

### Task 1: Carry application identity across the broker boundary

**Files:**
- Modify: `src/qat/data/broker/adapter.py:77-130`
- Modify: `src/qat/data/broker/ib_translate.py:387-442`
- Modify: `src/qat/data/broker/ib_adapter.py:734-757`
- Test: `tests/data/broker/test_ib_fill_cumulative.py`
- Test: `tests/data/broker/test_ib_recent_fills.py`

**Interfaces:**
- Produces: `BrokerFill.app_order_id: str | None`.
- Produces: `IBAdapter.recent_fills()` publishes `BrokerOrderIdResolvedEvent` whenever both IDs exist and differ.
- Consumes: IBKR `Execution.orderRef`; no OMS behavior changes in this task.

- [ ] **Step 1: Write failing translation and restarted-adapter tests**

```python
def test_ib_fill_carries_the_application_order_reference() -> None:
    raw = _fill(shares=4.0, cum_qty=4.0)
    raw.execution.orderRef = "app-order-123"
    out = from_ib_fill(raw, "ASX")
    assert out is not None
    assert out.app_order_id == "app-order-123"


@pytest.mark.asyncio
async def test_recent_fill_resolves_order_reference_after_adapter_restart() -> None:
    raw = _fill("WOW", "BOT", perm_id=998877)
    raw.execution.orderRef = "app-order-123"
    client = _Client([raw])
    bus = EventBus()
    seen: list[BrokerOrderIdResolvedEvent] = []

    async def capture(event: BrokerOrderIdResolvedEvent) -> None:
        seen.append(event)

    bus.subscribe(BrokerOrderIdResolvedEvent, capture)
    adapter = IBAdapter(client, bus, settings=_settings())
    assert adapter._orders == {}
    fills = await adapter.recent_fills(SINCE)
    assert fills[0].app_order_id == "app-order-123"
    assert [(e.order_id, e.app_order_id) for e in seen] == [
        ("998877", "app-order-123")
    ]
```

- [ ] **Step 2: Run tests and verify the field/local-map guard fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\data\broker\test_ib_fill_cumulative.py tests\data\broker\test_ib_recent_fills.py -q
```

Expected: the first test fails because `BrokerFill` lacks `app_order_id`; the second fails because the event is suppressed when `_orders` is empty.

- [ ] **Step 3: Add the broker field and publish the evidence**

```python
@dataclass(frozen=True, slots=True)
class BrokerFill:
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    filled_at: datetime
    app_order_id: str | None = None
```

In `from_ib_fill`:

```python
app_order_id = str(getattr(execution, "orderRef", "") or "") or None
return BrokerFill(
    order_id=str(execution.permId),
    symbol=from_ibkr(fill.contract.symbol, market),
    side=side,
    quantity=float(execution.cumQty),
    price=float(execution.avgPrice),
    filled_at=execution.time,
    app_order_id=app_order_id,
)
```

In `recent_fills`, remove the `app_order_id in self._orders` condition:

```python
if fill.app_order_id is not None and fill.order_id != fill.app_order_id:
    await self.bus.publish(
        BrokerOrderIdResolvedEvent(
            order_id=fill.order_id,
            app_order_id=fill.app_order_id,
        )
    )
```

- [ ] **Step 4: Run broker tests and static checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\data\broker\test_ib_fill_cumulative.py tests\data\broker\test_ib_recent_fills.py tests\data\broker\test_ib_order_identity.py -q
.\.venv\Scripts\python.exe -m ruff check src\qat\data\broker tests\data\broker
.\.venv\Scripts\python.exe -m black --check src\qat\data\broker tests\data\broker
```

Expected: all commands pass.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/data/broker/adapter.py src/qat/data/broker/ib_translate.py src/qat/data/broker/ib_adapter.py tests/data/broker/test_ib_fill_cumulative.py tests/data/broker/test_ib_recent_fills.py
git commit -m "Carry application identity on broker fills"
```

### Task 2: Persist one canonical cumulative receipt across restart

**Files:**
- Modify: `src/qat/domain/oms/oms.py:1468-1606,1695-1728,2200-2340,2670-2742`
- Modify: `src/qat/domain/oms/order_identity.py`
- Modify: `src/qat/domain/oms/signal_bridge.py:1270-1363`
- Modify: `src/qat/domain/performance/trades.py:1105-1147`
- Test: `tests/domain/oms/test_own_fill_identity.py`
- Test: `tests/safety/test_durable_order_identity.py`
- Test: `tests/safety/test_crash_atomic_fill_persistence.py`

**Interfaces:**
- Consumes: `BrokerFill.app_order_id` from Task 1.
- Produces: `OMS._canonical_execution_id(fill: BrokerFill) -> str`.
- Produces: fill-state `aliases: dict[str, str]` mapping aliases to canonical receipt IDs.
- Produces: canonical `OrderFilledEvent.order_id` and `fill_id` values.

- [ ] **Step 1: Write the failing `4 → 10` crash matrix**

Use the real OMS, bridge and ledger. Persist four shares under the app UUID, expose ten cumulative shares under broker ID `998877` and restart at each boundary:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crash_point",
    ["before_resolution", "after_identity", "after_alias", "after_retirement"],
)
async def test_late_broker_id_restart_keeps_one_cumulative_receipt(
    tmp_path, crash_point: str
) -> None:
    first, broker, bridge, ledger, app_id = await _partially_filled_qat_order(
        tmp_path, 4.0
    )
    cumulative = BrokerFill(
        "998877", "WOW.AX", "buy", 10.0, 102.0, datetime.now(UTC), app_id
    )
    await _stop_at_identity_boundary(first, cumulative, crash_point)

    restarted, restarted_broker, restarted_bridge, restarted_ledger = _restart_stack(
        tmp_path
    )
    restarted_broker._broker_fills[:] = [cumulative]
    await restarted.absorb_broker_fills()
    await restarted.absorb_broker_fills()

    entry = restarted_bridge.position_entries()["WOW.AX"]
    lots = restarted_ledger.open_lots("WOW.AX")
    assert entry.quantity == 10.0
    assert sum(lot.quantity for lot in lots) == 10.0
    assert len({fill_id for lot in lots for fill_id in lot.fill_ids}) == 2
    assert sum(lot.entry_cost for lot in lots) == pytest.approx(
        restarted_ledger._fill_cost(10.0, 102.0)
    )
```

`_stop_at_identity_boundary` calls production persistence methods. It may monkeypatch `_save_fill_state` to raise `SystemExit` immediately after the selected write; it must not hand-edit JSON.

- [ ] **Step 2: Run and confirm duplication**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\domain\oms\test_own_fill_identity.py tests\safety\test_durable_order_identity.py -q
```

Expected: pre-resolution or identity-only restart reports 14 shares or duplicate cost/receipts.

- [ ] **Step 3: Add canonical resolution and durable aliases**

Initialize `self._fill_aliases: dict[str, str] = {}`. Resolve IDs before foreign/own classification, delta calculation and pending ID construction:

```python
def _canonical_execution_id(self, fill: BrokerFill) -> str:
    if fill.app_order_id:
        return self._fill_aliases.get(fill.app_order_id, fill.app_order_id)
    return self._fill_aliases.get(fill.order_id, fill.order_id)
```

When both IDs exist, persist the order identity first, then alias both IDs and copy the strongest known cumulative receipt:

```python
canonical = fill.app_order_id or fill.order_id
self._fill_aliases[canonical] = canonical
self._fill_aliases[fill.order_id] = canonical
known = self._absorbed_fills.get(canonical) or self._absorbed_fills.get(fill.order_id)
if known is not None:
    self._absorbed_fills[canonical] = known
    self._absorbed_fills[fill.order_id] = known
if not self._save_fill_state():
    self.kill_switch.trip("broker-order fill aliases could not be persisted")
    return False
```

Persist `aliases` beside `absorbed`. On load, require non-empty strings and acyclic targets. Legacy files without `aliases` load as before.

In `_account_execution`:

```python
canonical = self._canonical_execution_id(raw)
receipt = replace(raw, order_id=canonical)
fill = self._unabsorbed_part(receipt)
fill_id = f"{canonical}|{raw.symbol}|{raw.side}|{raw.quantity:.12g}"
```

Use canonical IDs for entry fill IDs, lots and `_charged`. Broker IDs remain aliases for lookup.

- [ ] **Step 4: Require durable aliases before identity retirement**

```python
canonical = app_order_id
broker_id = str(order.order_id)
absorbed = self._absorbed_fills.get(canonical)
alias_is_durable = self._fill_aliases.get(broker_id) == canonical
if (
    order.status == "filled"
    and alias_is_durable
    and absorbed is not None
    and absorbed.quantity_known
    and absorbed.quantity + _POSITION_EPSILON >= order.quantity
):
    store.remove(app_order_id)
```

- [ ] **Step 5: Run identity, replay and commission suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\domain\oms\test_own_fill_identity.py tests\safety\test_durable_order_identity.py tests\safety\test_crash_atomic_fill_persistence.py tests\domain\performance\test_ledger_charges.py tests\data\broker\test_ib_commission_reports.py -q
```

Expected: every crash point and repeated cumulative poll passes with ten shares and one order-level commission.

- [ ] **Step 6: Commit**

```powershell
git add src/qat/domain/oms/oms.py src/qat/domain/oms/order_identity.py src/qat/domain/oms/signal_bridge.py src/qat/domain/performance/trades.py tests/domain/oms/test_own_fill_identity.py tests/safety/test_durable_order_identity.py tests/safety/test_crash_atomic_fill_persistence.py
git commit -m "Persist canonical execution receipts across restart"
```

### Task 3: Refuse incomplete confirmed-execution accounting

**Files:**
- Modify: `src/qat/domain/performance/trades.py:1116-1147,1190-1343`
- Test: `tests/safety/test_an_exit_cannot_precede_its_lot.py`
- Test: `tests/safety/test_crash_atomic_fill_persistence.py`
- Test: `tests/safety/test_broker_side_fills.py`

**Interfaces:**
- Produces: `UnaccountedExecutionError(RuntimeError)`.
- Produces: `TradeLedger._close_against_lots(event) -> float`, returning complete matched quantity or raising before commit.
- Consumes: critical EventBus failure propagation and OMS pending-delivery rollback.

- [ ] **Step 1: Add failing impossible and partial-unmatched tests**

```python
@pytest.mark.asyncio
async def test_partly_unmatched_sell_stays_pending_and_writes_no_trade(tmp_path) -> None:
    oms, broker, ledger, switch = _stack_with_open_lot(tmp_path, quantity=4.0)
    path = tmp_path / "closed_trades.csv"
    before = path.read_bytes() if path.exists() else b""
    broker._broker_fills.append(_sell_fill(quantity=10.0, order_id="sell-1"))

    await oms.absorb_broker_fills()

    assert switch.tripped
    assert oms._pending_fill_deliveries
    assert ledger.closed_trades() == []
    assert (path.read_bytes() if path.exists() else b"") == before
```

For a pre-entry timestamp, assert the same pending receipt and unchanged ledger.

- [ ] **Step 2: Run and verify the receipt is currently retired**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\safety\test_an_exit_cannot_precede_its_lot.py tests\safety\test_crash_atomic_fill_persistence.py -q
```

Expected: new assertions fail because `_on_fill` returns normally.

- [ ] **Step 3: Raise before durable commit**

```python
class UnaccountedExecutionError(RuntimeError):
    pass


def _close_against_lots(self, event: OrderFilledEvent) -> float:
    # Existing matching logic works against staged deques.
    if impossible:
        self._charged = original_charged
        self._open_lots[event.symbol] = original_lots
        raise UnaccountedExecutionError(
            f"{event.symbol} confirmed sell precedes its recorded lot"
        )
    if remaining > 1e-9:
        self._charged = original_charged
        self._open_lots[event.symbol] = original_lots
        raise UnaccountedExecutionError(
            f"{event.symbol} confirmed sell has {remaining:g} unmatched shares"
        )
    self._record_many(staged)
    return event.quantity
```

Only add `fill_id` to `_processed_fill_ids` after complete matching returns.

- [ ] **Step 4: Run focused and broker-fill suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\safety\test_an_exit_cannot_precede_its_lot.py tests\safety\test_crash_atomic_fill_persistence.py tests\safety\test_broker_side_fills.py -q
```

Expected: all pass; a legitimate adopted-position exit either has a synthetic/restored lot or halts pending evidence.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/performance/trades.py tests/safety/test_an_exit_cannot_precede_its_lot.py tests/safety/test_crash_atomic_fill_persistence.py tests/safety/test_broker_side_fills.py
git commit -m "Keep unaccounted broker executions pending"
```

### Task 4: Defer ledger schema writes until broker stability

**Files:**
- Modify: `src/qat/domain/performance/trades.py:121-170,629-672`
- Modify: `src/qat/domain/oms/signal_bridge.py:430-452`
- Test: `tests/domain/performance/test_trade_ledger.py`
- Test: `tests/safety/test_broker_side_fills.py`

**Interfaces:**
- Produces: `TradeLedger.prepare_schema_migration() -> LedgerSchemaMigration | None`, read-only.
- Produces: `TradeLedger.apply_schema_migration(plan: LedgerSchemaMigration) -> bool`, backed up and atomic.
- Consumes: the already-captured stable `_FillReplaySnapshot` only as the gate.
- Extend the bridge-local `_LotStore` protocol with both migration methods; keep the narrower `ClosedTradeSource` protocol unchanged.

- [ ] **Step 1: Add constructor and unstable-snapshot byte tests**

```python
def test_constructing_ledger_never_repairs_an_old_header(tmp_path) -> None:
    path = _write_prefix_header_ledger(tmp_path)
    before = path.read_bytes()
    ledger = TradeLedger(EventBus(), tmp_path)
    assert ledger.closed_trades()
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_unstable_startup_does_not_migrate_ledger_header(tmp_path) -> None:
    path = _write_prefix_header_ledger(tmp_path)
    before = path.read_bytes()
    bridge, switch = _unstable_bridge(tmp_path)
    await bridge.start()
    assert switch.tripped
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("closed_trades.csv.bak-pre-schema-*"))
```

Add a current-schema stable-startup test asserting byte identity and no backup.

- [ ] **Step 2: Run and verify constructor mutation**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\domain\performance\test_trade_ledger.py tests\safety\test_broker_side_fills.py -q
```

Expected: old-header bytes change during construction.

- [ ] **Step 3: Split read-only planning from atomic application**

```python
@dataclass(frozen=True, slots=True)
class LedgerSchemaMigration:
    source_sha256: str
    corrected: bytes


def prepare_schema_migration(self) -> LedgerSchemaMigration | None:
    source = self.path.read_bytes()
    corrected = _header_repaired_bytes(source, _FIELDS)
    if corrected == source:
        return None
    return LedgerSchemaMigration(hashlib.sha256(source).hexdigest(), corrected)
```

`_load_closed()` parses a strict-prefix header positionally without writing. `apply_schema_migration()` rechecks the source hash, creates and verifies `closed_trades.csv.bak-pre-schema-<timestamp>`, writes/fsyncs a same-directory temporary file, uses `os.replace`, validates via `audit_closed_trades` and restores the backup on post-write failure.

- [ ] **Step 4: Gate migration after stable snapshot**

In `SignalToOrderBridge.start()`, immediately after `prepare_missed_fill_replay()` returns a snapshot:

```python
migration = self.trade_ledger.prepare_schema_migration()
if migration is not None and not self.trade_ledger.apply_schema_migration(migration):
    self.oms.kill_switch.trip("closed-trade ledger schema migration failed")
    return
```

Use the shared ledger already supplied to the bridge; do not construct another.

- [ ] **Step 5: Run ledger, replay and audit tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\domain\performance\test_trade_ledger.py tests\safety\test_broker_side_fills.py tests\safety\test_crash_atomic_fill_persistence.py tests\domain\performance\test_historical_correction.py -q
```

Expected: old headers migrate only after stability; current headers never rewrite.

- [ ] **Step 6: Commit**

```powershell
git add src/qat/domain/performance/trades.py src/qat/domain/oms/signal_bridge.py tests/domain/performance/test_trade_ledger.py tests/safety/test_broker_side_fills.py
git commit -m "Defer ledger migration until broker state is stable"
```

### Task 5: Halt on corrupt position-entry evidence

**Files:**
- Modify: `src/qat/domain/oms/signal_bridge.py:390-452,1383-1445`
- Test: `tests/safety/test_legacy_entry_quantity_migration.py`
- Test: `tests/domain/oms/test_entry_record_survives_a_restart.py`

**Interfaces:**
- Produces: `EntryStoreError(ValueError)`.
- Produces: `SignalToOrderBridge._entry_store_error: EntryStoreError | None`.
- Consumes: existing kill switch; `start()` returns before broker snapshot/replay.

- [ ] **Step 1: Add malformed, permission and mixed-row tests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    ["{not-json", "[]", '{"WOW.AX": {"opened_at": "bad"}}'],
)
async def test_corrupt_entry_evidence_halts_without_mutation(
    tmp_path, payload: str
) -> None:
    path = tmp_path / "open_position_entries.json"
    path.write_text(payload, encoding="utf-8")
    before = path.read_bytes()
    bridge, switch, broker = _bridge(tmp_path)
    await bridge.start()
    assert switch.tripped
    assert "entry" in switch.reason
    assert broker.recent_fill_calls == 0
    assert path.read_bytes() == before
```

Add an `OSError` test by monkeypatching `Path.read_text` only for the target path. Keep missing-file first-run behavior green.

- [ ] **Step 2: Run and verify silent-empty behavior**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\safety\test_legacy_entry_quantity_migration.py tests\domain\oms\test_entry_record_survives_a_restart.py -q
```

Expected: corrupt inputs currently return `{}` and startup continues.

- [ ] **Step 3: Distinguish absence from unreadable evidence**

```python
class EntryStoreError(ValueError):
    pass


def _load_entries(self) -> dict[str, _Entry]:
    try:
        text = self._entries_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise EntryStoreError(f"cannot read {self._entries_path}: {exc}") from exc
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise TypeError("entry root is not an object")
        return _parse_every_entry(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise EntryStoreError(
            f"invalid entry evidence in {self._entries_path}: {exc}"
        ) from exc
```

Catch once in `__init__`, retain the error, and in `start()` trip `position-entry evidence is unreadable` and return before subscribing or querying. Do not write the file.

- [ ] **Step 4: Run entry, migration and startup suites**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\safety\test_legacy_entry_quantity_migration.py tests\domain\oms\test_entry_record_survives_a_restart.py tests\safety\test_replayed_buy_opens_a_lot.py -q
```

Expected: all pass, including valid legacy rows.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/oms/signal_bridge.py tests/safety/test_legacy_entry_quantity_migration.py tests/domain/oms/test_entry_record_survives_a_restart.py
git commit -m "Halt on unreadable position-entry evidence"
```

### Task 6: Hold one operating-system application lock

**Files:**
- Create: `src/qat/application_lock.py`
- Modify: `src/qat/app.py:31-99`
- Modify: `scripts/apply_historical_correction.py:26-118`
- Create: `tests/test_application_lock.py`
- Modify: `tests/domain/performance/test_historical_correction.py`

**Interfaces:**
- Produces: `ApplicationLock(path: Path | None = None)` context manager.
- Produces: `ApplicationLockUnavailable(RuntimeError)`.
- Default path: `qat.paths.app_dir() / "application.lock"`; tests inject `tmp_path`.

- [ ] **Step 1: Add contention, stale-file and subprocess tests**

```python
def test_second_owner_is_refused_until_first_releases(tmp_path) -> None:
    path = tmp_path / "application.lock"
    with ApplicationLock(path):
        with pytest.raises(ApplicationLockUnavailable):
            with ApplicationLock(path):
                pass
    with ApplicationLock(path):
        pass


def test_stale_lock_file_without_owner_is_reusable(tmp_path) -> None:
    path = tmp_path / "application.lock"
    path.write_text("stale metadata", encoding="utf-8")
    with ApplicationLock(path):
        assert path.exists()
```

Add a subprocess that acquires the lock under `python.exe`. While held, invoke correction apply with an injected lock path and assert refusal before backup/staging; after child exit, acquisition succeeds.

- [ ] **Step 2: Run and verify the module is absent**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_application_lock.py tests\domain\performance\test_historical_correction.py -q
```

Expected: collection fails because `qat.application_lock` does not exist.

- [ ] **Step 3: Implement the cross-platform lock**

```python
class ApplicationLock:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_dir() / "application.lock"
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            _lock_one_byte(handle)
        except OSError as exc:
            handle.close()
            raise ApplicationLockUnavailable(str(self.path)) from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is not None:
            _unlock_one_byte(self._handle)
            self._handle.close()
            self._handle = None
```

Windows uses `msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)`; POSIX uses `fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)`. Unlock mirrors acquisition.

- [ ] **Step 4: Acquire before migration and hold through shutdown**

Wrap the application body before `ensure_app_dir()`:

```python
try:
    with ApplicationLock():
        _run_application(app, loop)
except ApplicationLockUnavailable:
    raise SystemExit("Quant Advisory Terminal is already running") from None
```

Extract `_run_application()` only far enough to hold the lock through engine startup, event loop and existing marker release. Do not alter engine order.

- [ ] **Step 5: Hold the same lock through correction apply**

Add injectable `--application-lock` for tests. Dry-run stays read-only. In apply mode, reacquire and re-run final preparation inside the lock:

```python
try:
    with ApplicationLock(args.application_lock):
        plan = prepare_correction(
            args.proposal,
            args.statement,
            args.ledger,
            expected_proposal_sha256=APPROVED_PROPOSAL_SHA256,
        )
        result = apply_correction(plan)
except ApplicationLockUnavailable:
    print("REFUSING: QAT holds the operational-data lock.")
    return 1
```

- [ ] **Step 6: Run lock, app and correction tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_application_lock.py tests\test_run_marker.py tests\domain\performance\test_historical_correction.py -q
```

Expected: all pass and no operational path is accessed.

- [ ] **Step 7: Commit**

```powershell
git add src/qat/application_lock.py src/qat/app.py scripts/apply_historical_correction.py tests/test_application_lock.py tests/domain/performance/test_historical_correction.py
git commit -m "Lock QAT operational data across processes"
```

### Task 7: Integrate the repair set and assign M176

**Files:**
- Modify: `src/qat/version.py`
- Create: `docs/phase-1-release-readiness-checkpoint.md`
- Modify: `docs/phase-1-historical-correction-checkpoint.md`
- Modify: `docs/HANDOFF.md`

**Interfaces:**
- Produces: `MILESTONE = "M176"` and one release-readiness record.
- Consumes: Tasks 1-6; introduces no runtime mechanism.

- [ ] **Step 1: Run the combined Phase 1 set**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\safety tests\domain\oms tests\domain\performance tests\data\broker -q
```

Expected: all pass. Fix only regressions caused by Tasks 1-6; do not weaken assertions.

- [ ] **Step 2: Record the release identity**

Set:

```python
MILESTONE = "M176"
```

Add a concise M176 comment describing canonical receipts, fail-closed evidence loading, stable-gated ledger migration and the application lock.

- [ ] **Step 3: Write the checkpoint**

Create:

```markdown
# Phase 1 release-readiness checkpoint

Status: code-complete candidate; not merged, packaged, deployed or launched.

## Closed review findings
- Canonical application/broker execution identity survives every tested crash boundary.
- Unaccounted confirmed sells remain pending and halt.
- Ledger schema writes occur only after a stable broker snapshot.
- Corrupt entry evidence halts without mutation.
- Packaged and source QAT processes hold the same application lock.

## First-launch boundary
- Paper account only.
- QAT_EXECUTION_MODE=recommend.
- QAT_AUTONOMOUS_STRATEGIES is empty.
- Verified configuration and data backups before launch.
- Nine legacy entry records make the first launch a supervised migration event.
- Autonomous trading remains suspended.
```

Append the lock clarification to the historical-correction checkpoint and update the handoff's current Phase 1 status without rewriting preserved audit narrative.

- [ ] **Step 4: Run source and documentation gates**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest tests\test_version.py tests\test_open_items_are_still_open.py -q
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m black --check src scripts tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m bandit -q -r src scripts
```

Expected: each command passes. Use the repository's exact CI Bandit configuration if it contains established exclusions.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/version.py docs/phase-1-release-readiness-checkpoint.md docs/phase-1-historical-correction-checkpoint.md docs/HANDOFF.md
git commit -m "Prepare M176 Phase 1 release checkpoint"
```

### Task 8: Complete verification, review and publication

**Files:**
- Modify only files required by validated review findings.
- Update: `docs/phase-1-release-readiness-checkpoint.md` with exact final evidence.

**Interfaces:**
- Produces: one reviewed, tested Phase 1 candidate tree.
- Does not merge, package, sign, deploy, launch or alter operational state.

- [ ] **Step 1: Run the complete suite from a fresh isolated temp root**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTEST_ADDOPTS='--basetemp=test-tmp-phase1-release-final'
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the full suite passes with only recorded warning classes.

- [ ] **Step 2: Run every static gate separately**

```powershell
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m black --check src scripts tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m bandit -q -r src scripts
git diff --check 5757fd28d96453441a9514b9c696a027b2e46247..HEAD
git status --short --untracked-files=no
```

Expected: every command exits zero and the tracked tree is clean.

- [ ] **Step 3: Request a fresh whole-repair review**

Give the reviewer the approved spec, this plan, the pre-repair commit, current head and the five original findings. Require explicit verification of the crash matrix, unmatched execution rollback, schema-migration timing, corrupt-entry halt and cross-process lock. Fix Critical and Important findings test-first, one at a time.

- [ ] **Step 4: Re-run final gates after review fixes**

Repeat Steps 1 and 2. Record exact counts, duration, warnings, local head and tree in the checkpoint, then commit the evidence update:

```powershell
git add docs/phase-1-release-readiness-checkpoint.md
git commit -m "Record final M176 release evidence"
```

- [ ] **Step 5: Publish the exact tree to draft PR #3**

Push `recovery/phase-1-safety-and-truth`, verify the remote tree matches the tested local tree, update PR #3 with repaired findings and final evidence, and keep it draft. Wait for GitHub CI and require Ruff, Black, Mypy, Bandit and the full suite to pass.

- [ ] **Step 6: Stop at the controlled boundary**

Report the merge recommendation and separate deployment prerequisites. Do not mark the PR ready, merge, package, sign, edit operational `.env`, deploy or launch without the operator's next explicit decision.
