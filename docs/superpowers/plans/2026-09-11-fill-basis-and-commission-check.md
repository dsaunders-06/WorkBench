# Fill Basis and the Commission Check — Implementation Plan (M175)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every realised cost in `closed_trades.csv` the broker's charge on the true fill price — no doubled entry commission, no doubled slippage, one floor per order — and check the model against IBKR's own `commissionReport` on every order the app hears about.

**Architecture:** `CostModel` gains `charge()` (commission + pass-through, no slippage) and the inverse of IBKR's commission-inclusive average cost. The trade ledger costs through `charge()` with a per-order running total. The entry record carries a `price_source` stamp so M65 never overwrites an observed fill, and M65 de-commissions IBKR's `avgCost` when it does correct. `IBAdapter` totals `commissionReportEvent` per order and hands a plain record to a domain `CommissionAuditor`, which writes `commission_checks.csv`. A domain module plus a thin script rewrite the existing rows and open records from logged evidence.

**Tech Stack:** Python 3.12, ib_async 2.1.0, pytest (asyncio_mode=auto), ruff, black (line length 100), mypy strict, bandit. Windows / PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-11-fill-basis-and-commission-check-design.md`

## Global Constraints

- ⚠️ Anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` runs under **PowerShell**, never Bash (the Bash sandbox serves a frozen snapshot and does not error). Tests use `tmp_path` and `Settings(_env_file=None, ...)` — never the live data dir.
- ⚠️ Never pipe `pytest` or `invoke build` through `tail`.
- ⚠️ The four checks run **separately** at the end: `ruff check`, `black --check` (read its OUTPUT — it can exit 0 while printing "1 file would be reformatted"), `mypy src`, `bandit -r src -q`.
- ⚠️ Do not reference Alpaca in new prose. Broker IBKR, market ASX.
- ⚠️ No deploy, no live-file write, during this plan's tasks. The rewrite and deploy are the operator runbook at the end, after the 16:00 close, with the app CLOSED and IB Gateway left up.
- ASX Fixed profile: `commission_bps=8.8`, `min_commission=6.60`, `third_party_bps=0.0`.
- `_ENTRY_PRICE_TOLERANCE = 1e-4` (unchanged).
- Commission check tolerance: **0.01** (one cent). Repair self-check bound: **$0.25 per order**.
- `closed_trades.csv` columns only ever GROW by appending (see `repair_csv_header`). This plan adds none.
- Commit after every task, message ending `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Do not push.

Run all commands from `C:\Claude Programming` in PowerShell. `py` below means `.\.venv\Scripts\python.exe`.

---

### Task 1: `CostModel.charge()` and the inverse of a commission-inclusive average

**Files:**
- Modify: `src/qat/domain/backtester/costs.py` (add two methods after `third_party`, before `apply`)
- Test: `tests/domain/backtester/test_cost_charge.py` (create)

**Interfaces:**
- Produces: `CostModel.charge(notional: float) -> float` and `CostModel.fill_price_from_average_cost(average_cost: float, quantity: float) -> float`. Used by Tasks 2, 4, 6, 7.

- [ ] **Step 1: Write the failing tests**

```python
"""What the broker BILLS, as distinct from what a backtest must model (M175).

The figures are the live ones. The audit of 10 September reconciled a SEK.AX
exit: modelled commission 33.88, IBKR's actual commission 33.88, modelled
slippage 19.25, ledger exit_cost 53.13. The ledger was charging the slippage
of a fill whose price already contained it.
"""

from __future__ import annotations

import pytest

from qat.domain.backtester.costs import CostModel

_ASX_FIXED = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=6.60)


def test_charge_is_the_commission_and_never_the_slippage():
    assert _ASX_FIXED.charge(38_500.0) == pytest.approx(33.88)
    # apply() is unchanged: it is still the pre-trade and backtest figure.
    assert _ASX_FIXED.apply(38_500.0) == pytest.approx(53.13)


def test_charge_keeps_the_per_order_floor():
    assert _ASX_FIXED.charge(1_000.0) == pytest.approx(6.60)


def test_charge_includes_fees_the_broker_passes_through():
    tiered = CostModel(
        commission_bps=8.8, slippage_bps=5.0, min_commission=5.50, third_party_bps=0.45375
    )
    assert tiered.charge(100_000.0) == pytest.approx(88.0 + 4.5375)


def test_bhp_average_cost_converts_back_to_its_fill():
    """BHP.AX, 11 September: IBKR's avgCost 64.1263816 over 793 shares is a
    64.07 fill - an exact tick, against a 64.08 reference."""
    assert _ASX_FIXED.fill_price_from_average_cost(64.1263816, 793) == pytest.approx(
        64.07, abs=1e-6
    )


def test_below_the_floor_the_floor_branch_is_used():
    # 10 shares at 50.00 = 500 notional: 8.8 bp is 0.44, so the 6.60 floor binds.
    average = 50.0 + 6.60 / 10
    assert _ASX_FIXED.fill_price_from_average_cost(average, 10) == pytest.approx(50.0)


@pytest.mark.parametrize("fill", [0.89, 5.49, 64.07, 135.736])
@pytest.mark.parametrize("quantity", [10.0, 793.0, 64_229.0])
def test_the_inverse_undoes_the_charge(fill, quantity):
    average = fill + _ASX_FIXED.charge(fill * quantity) / quantity
    assert _ASX_FIXED.fill_price_from_average_cost(average, quantity) == pytest.approx(
        fill, rel=1e-12
    )


def test_no_quantity_returns_the_average_unchanged():
    assert _ASX_FIXED.fill_price_from_average_cost(64.1263816, 0) == 64.1263816
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/domain/backtester/test_cost_charge.py -v`
Expected: FAIL — `AttributeError: 'CostModel' object has no attribute 'charge'`.

- [ ] **Step 3: Implement** — in `costs.py`, insert after `third_party` and before `apply`:

```python
    def charge(self, notional: float) -> float:
        """What the BROKER bills for one transaction: commission plus
        pass-through fees, and never slippage (M175).

        `apply` adds slippage because a backtest fills at an idealised price and
        the impact has to be modelled. A real fill already CONTAINS its
        slippage - the price is the slipped price - so a realised record that
        charged `apply` counted it twice. Measured on 11 September: every row in
        `closed_trades.csv` carried 5 bp a side that its fills had already paid.
        """
        return self.commission(notional) + self.third_party(notional)

    def fill_price_from_average_cost(self, average_cost: float, quantity: float) -> float:
        """The fill price inside a commission-INCLUSIVE average cost (M175).

        IBKR's `avgCost` folds the commission in: avgCost x qty = fill x qty +
        charge(fill x qty). Verified 11 September against 17 logged orders to
        well under a cent an order - BHP.AX's 64.1263816 over 793 shares is a
        64.07 fill, an exact tick.

        Solved on the proportional branch first; if that answer would not clear
        the floor, the floor branch is the self-consistent one.
        """
        qty = abs(quantity)
        if qty <= 0 or average_cost <= 0:
            return average_cost
        rate = self.commission_bps / 10_000.0
        third = self.third_party_bps / 10_000.0
        proportional = average_cost / (1.0 + rate + third)
        if proportional * qty * rate >= self.min_commission:
            return proportional
        return (average_cost * qty - self.min_commission) / (qty * (1.0 + third))
```

- [ ] **Step 4: Run to verify they pass**

Run: `py -m pytest tests/domain/backtester/test_cost_charge.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/backtester/costs.py tests/domain/backtester/test_cost_charge.py
git commit -m "M175: CostModel.charge() - what the broker bills, never slippage" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The ledger costs through `charge()`, one floor per order

**Files:**
- Modify: `src/qat/domain/performance/trades.py` — `TradeLedger.__init__` (the comment above `self._costs`, plus one new attribute), `_on_fill` (buy branch), `_fill_cost`, new `_increment_cost`, `_close_against_lots` (the `exit_cost_total` line)
- Modify: `src/qat/config.py:396-399` (the `apply_costs_in_paper` comment)
- Modify: `tests/domain/performance/test_trade_ledger.py:424-436` (one expectation that encoded slippage)
- Test: `tests/domain/performance/test_ledger_charges.py` (create)

**Interfaces:**
- Consumes: `CostModel.charge` (Task 1).
- Produces: `TradeLedger._increment_cost(order_id: str | None, quantity: float, price: float) -> float`; `_fill_cost(quantity, price)` now returns `charge()` of the whole notional.

- [ ] **Step 1: Write the failing tests** — create `tests/domain/performance/test_ledger_charges.py`:

```python
"""A realised cost is what the broker billed, once per order (M175).

Three defects, measured on the live ledger 11 September: modelled slippage was
charged on fills that already contained it; the $6.60 floor was charged once
per ABSORBED PIECE of one order (LOV.AX's single exit paid four floors); and a
replay double-counted too, because SimulatedBroker already slips its prices.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.simulated_broker import SimulatedBroker
from qat.domain.backtester.costs import CostModel
from qat.domain.bus import EventBus
from qat.domain.events import EntryPriceCorrectedEvent, ExitPriceCorrectedEvent, OrderFilledEvent
from qat.domain.performance.trades import TradeLedger

_BASE = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


async def _ledger(tmp_path, **overrides) -> TradeLedger:
    base = {
        "_env_file": None,
        "data_dir": str(tmp_path),
        "commission_bps": 8.8,
        "slippage_bps": 5.0,
        "broker_min_commission": 6.60,
    }
    base.update(overrides)
    ledger = TradeLedger(EventBus(), tmp_path, settings=Settings(**base))  # type: ignore[arg-type]
    await ledger.start()
    return ledger


def _event(order_id: str, side: str, quantity: float, price: float, day: int = 0):
    return OrderFilledEvent(
        order_id=order_id,
        symbol="SEK.AX",
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        price=price,
        strategy="swing",
        stop_price=price * 0.9 if side == "buy" else None,
        ts=_BASE + timedelta(days=day),
    )


@pytest.mark.asyncio
async def test_a_live_cost_is_the_commission_not_the_commission_plus_slippage(tmp_path):
    """The audit's own numbers: 38,500 of notional is 33.88 of commission,
    and 53.13 only if 5 bp of slippage is added on top."""
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(_event("in", "buy", 1000, 38.50))
    await ledger._on_fill(_event("out", "sell", 1000, 38.50, day=5))

    trade = ledger.closed_trades()[0]

    assert trade.entry_cost == pytest.approx(33.88)
    assert trade.exit_cost == pytest.approx(33.88)


@pytest.mark.asyncio
async def test_one_order_absorbed_in_pieces_pays_one_floor(tmp_path):
    """LOV.AX, 26 August: one exit order absorbed as several OrderFilledEvents
    under the SAME order id. The floor belongs to the order, not the piece."""
    ledger = await _ledger(tmp_path, commission_bps=5.0)
    await ledger._on_fill(_event("in", "buy", 300, 100.0))
    for _ in range(3):
        await ledger._on_fill(_event("out-1", "sell", 100, 110.0, day=1))

    exits = [t.exit_cost for t in ledger.closed_trades()]

    # 5 bp of 33,000 is 16.50 for the whole order - not three $6.60 floors.
    assert sum(exits) == pytest.approx(16.50)
    assert exits[0] == pytest.approx(6.60)  # the first piece alone is under the floor


@pytest.mark.asyncio
async def test_an_entry_price_correction_recosts_with_the_charge(tmp_path):
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(_event("in", "buy", 793, 64.08))

    await ledger._on_entry_price_corrected(
        EntryPriceCorrectedEvent(order_id="in", symbol="SEK.AX", price=64.07, announced_price=64.08)
    )

    lot = ledger.open_lots("SEK.AX")[0]
    assert lot.entry_cost == pytest.approx(CostModel(8.8, 5.0, 6.60).charge(793 * 64.07))


@pytest.mark.asyncio
async def test_an_exit_price_correction_recosts_with_the_charge(tmp_path):
    ledger = await _ledger(tmp_path)
    await ledger._on_fill(_event("in", "buy", 793, 64.07))
    await ledger._on_fill(_event("out", "sell", 793, 60.45, day=2))

    await ledger._on_exit_price_corrected(
        ExitPriceCorrectedEvent(
            order_id="out", symbol="SEK.AX", price=60.40, announced_price=60.45, quantity=793.0
        )
    )

    trade = ledger.closed_trades()[0]
    assert trade.exit_cost == pytest.approx(CostModel(8.8, 5.0, 6.60).charge(793 * 60.40))


@pytest.mark.asyncio
async def test_a_replay_round_trip_pays_slippage_once_in_the_prices(tmp_path):
    """WHERE ELSE: SimulatedBroker already moves every fill against the
    order, so the ledger must not charge slippage again on top."""
    index = pd.DatetimeIndex(
        [pd.Timestamp("2026-09-01"), pd.Timestamp("2026-09-02"), pd.Timestamp("2026-09-03")]
    )
    prices = [100.0, 100.0, 110.0]
    bars = {
        "SEK.AX": pd.DataFrame(
            {"open": prices, "high": prices, "low": prices, "close": prices}, index=index
        )
    }
    model = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=0.0)
    broker = SimulatedBroker(bars=bars, cost_model=model)
    await broker.place_order(Order(symbol="SEK.AX", side="buy", quantity=100.0, order_id="in"))
    broker.advance()
    bought = broker._orders["in"].filled_price
    await broker.place_order(Order(symbol="SEK.AX", side="sell", quantity=100.0, order_id="out"))
    broker.advance()
    sold = broker._orders["out"].filled_price
    assert bought == pytest.approx(100.0 * 1.0005)  # slippage IS in the price
    assert sold == pytest.approx(110.0 * 0.9995)

    ledger = await _ledger(tmp_path, broker_min_commission=0.0)
    await ledger._on_fill(_event("in", "buy", 100, bought))
    await ledger._on_fill(_event("out", "sell", 100, sold, day=2))
    trade = ledger.closed_trades()[0]

    assert trade.costs == pytest.approx(model.charge(100 * bought) + model.charge(100 * sold))
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/domain/performance/test_ledger_charges.py -v`
Expected: FAIL — costs include slippage (e.g. `53.13 != 33.88`), and the pieces test sums three floors.

- [ ] **Step 3: Implement in `trades.py`**

3a. In `TradeLedger.__init__`, replace the comment block above `self._costs = (` (the one beginning `# Modelled, not billed.`) with:

```python
        # The broker's CHARGE, modelled (M175). Measured 11 September: IBKR's
        # own commission equals this model on 17 of 17 logged orders, to the
        # cent - and the paper account bills it, so the Alpaca-era reason for
        # modelling ("a paper broker charges nothing") no longer applies; the
        # model is simply exact. `commission_checks.csv` keeps checking it.
        # Slippage is NOT charged here: a fill's price already contains it.
```

and directly after the `self._costs = (...)` statement add:

```python
        # Per broker order id: (notional booked so far, charge booked so far).
        # One order absorbed in several pieces pays ONE floor across all of
        # them (M175) - LOV.AX's single exit on 26 August paid four. In memory
        # only: a piece absorbed after a restart can pay a second floor, which
        # matters only below ~AUD 7,500 of notional.
        self._charged: dict[str, tuple[float, float]] = {}
```

3b. Replace `_fill_cost` with:

```python
    def _fill_cost(self, quantity: float, price: float) -> float:
        """What one WHOLE order is billed - commission and pass-through fees,
        never slippage (M175). For re-costing an order already known in full:
        a corrected entry, a corrected exit, a lot restored at startup."""
        if self._costs is None:
            return 0.0
        return self._costs.charge(abs(quantity) * price)

    def _increment_cost(self, order_id: str | None, quantity: float, price: float) -> float:
        """What THIS piece of an order adds to the order's bill (M175).

        The floor is charged once per ORDER, so each increment pays the
        difference between the order's charge with it and without it. With no
        order id there is nothing to accumulate against, so the piece is
        costed as a whole order.
        """
        if self._costs is None:
            return 0.0
        notional = abs(quantity) * price
        if not order_id:
            return self._costs.charge(notional)
        booked_notional, booked_charge = self._charged.get(order_id, (0.0, 0.0))
        total_notional = booked_notional + notional
        total_charge = self._costs.charge(total_notional)
        self._charged[order_id] = (total_notional, total_charge)
        return total_charge - booked_charge
```

3c. In `_on_fill`, buy branch, change `entry_cost=self._fill_cost(event.quantity, event.price),` to:

```python
                    entry_cost=self._increment_cost(event.order_id, event.quantity, event.price),
```

3d. In `_close_against_lots`, change `exit_cost_total = self._fill_cost(event.quantity, event.price)` to:

```python
        exit_cost_total = self._increment_cost(event.order_id, event.quantity, event.price)
```

(`restore_open_lot`, `_on_entry_price_corrected` and `_amend_closed_trade` keep calling `_fill_cost` — each re-costs a whole order.)

3e. In `src/qat/config.py`, replace the four comment lines above `apply_costs_in_paper: bool = True` with:

```python
    # Costs are recorded during paper trading. The point of a paper test is to
    # learn whether a strategy survives what it will actually pay. The ledger
    # records the broker's CHARGE only (M175) - slippage is already inside
    # every fill price, and the pre-trade estimate is where it is modelled.
```

3f. In `tests/domain/performance/test_trade_ledger.py`, `test_a_trade_records_what_it_cost_to_open_and_close` encoded slippage in a realised cost. Change its body's assertions to:

```python
    assert trade.gross_pnl == pytest.approx(1000.0)
    # 5bps commission of $10,000 in and of $11,000 out. The 5bps of slippage
    # in these settings is NOT charged: a fill's price already contains it (M175).
    assert trade.entry_cost == pytest.approx(5.0)
    assert trade.exit_cost == pytest.approx(5.5)
    assert trade.net_pnl == pytest.approx(989.5)
    assert trade.costs == pytest.approx(10.5)
```

- [ ] **Step 4: Run the new file and the ledger suites**

Run: `py -m pytest tests/domain/performance tests/safety/test_live_entry_price_correction.py tests/safety/test_live_exit_price_correction.py -v`
Expected: all PASS. If any OTHER test fails on a cost figure, stop: check whether it asserted slippage inside a REALISED cost (then change it and name it in the commit message) or whether the change broke something real (then fix the code).

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/performance/trades.py src/qat/config.py tests/domain/performance/test_ledger_charges.py tests/domain/performance/test_trade_ledger.py
git commit -m "M175: the ledger records the broker's charge - no slippage, one floor per order" -m "Slippage was charged on fills that already contained it (live and replay), and the floor once per absorbed piece. test_a_trade_records_what_it_cost_to_open_and_close encoded the slippage and now expects commission only." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Stamp where an entry price came from

**Files:**
- Modify: `src/qat/domain/events.py` — `OrderFilledEvent` (new field after `exit_reason`)
- Modify: `src/qat/domain/oms/oms.py:1173-1195` — `_announce_fill`'s `OrderFilledEvent(...)` call
- Modify: `src/qat/domain/oms/signal_bridge.py` — `_Entry` (new field), `_on_fill` (buy branch), `_on_entry_price_corrected`, `_load_entries`, `_save_entries`
- Test: `tests/domain/oms/test_entry_price_source.py` (create)

**Interfaces:**
- Produces: `OrderFilledEvent.price_is_fill: bool = False`; `_Entry.price_source: Literal["fill", "reference"] | None = None`, persisted as `"price_source"` in `open_position_entries.json`. Task 4 reads `_Entry.price_source`; Task 7's script writes `"price_source": "fill"`.

- [ ] **Step 1: Write the failing tests**

```python
"""Where an entry record's price came from (M175).

M65 overwrote an OBSERVED fill with IBKR's commission-inclusive average cost at
every restart - JHX.AX on 31 August, COH.AX on 10 September - because the record
could not say that its price had already been corrected to the fill.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import EntryPriceCorrectedEvent, OrderFilledEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_WHEN = datetime(2026, 9, 10, 0, 29, tzinfo=UTC)


def _bridge(tmp_path) -> SignalToOrderBridge:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(MockBroker(seed=1), RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return SignalToOrderBridge(bus=bus, oms=oms, settings=settings)


def _buy(price: float, price_is_fill: bool) -> OrderFilledEvent:
    return OrderFilledEvent(
        order_id="coh-1",
        symbol="COH.AX",
        side="buy",
        quantity=363,
        price=price,
        strategy="swing",
        stop_price=126.09,
        reference_price=136.54,
        price_is_fill=price_is_fill,
        ts=_WHEN,
    )


@pytest.mark.asyncio
async def test_the_announcement_says_whether_its_price_is_a_fill(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        MockBroker(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    seen: list[OrderFilledEvent] = []

    async def grab(event: OrderFilledEvent) -> None:
        seen.append(event)

    bus.subscribe(OrderFilledEvent, grab)
    transmitted = Order(
        symbol="COH.AX", side="buy", quantity=363, order_id="a", status="transmitted",
        reference_price=136.54,
    )
    filled = Order(
        symbol="COH.AX", side="buy", quantity=363, order_id="b", status="filled",
        filled_price=135.736, reference_price=136.54,
    )

    await oms._announce_fill(transmitted, "test")
    await oms._announce_fill(filled, "test")

    assert [(e.price, e.price_is_fill) for e in seen] == [(136.54, False), (135.736, True)]


@pytest.mark.asyncio
async def test_an_entry_announced_at_its_fill_is_stamped_fill(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(135.736, price_is_fill=True))
    assert bridge._entries["COH.AX"].price_source == "fill"


@pytest.mark.asyncio
async def test_an_entry_announced_at_its_reference_is_stamped_reference(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(136.54, price_is_fill=False))
    assert bridge._entries["COH.AX"].price_source == "reference"


@pytest.mark.asyncio
async def test_the_live_correction_stamps_the_record_as_a_fill(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(136.54, price_is_fill=False))

    await bridge._on_entry_price_corrected(
        EntryPriceCorrectedEvent(
            order_id="coh-1", symbol="COH.AX", price=135.736, announced_price=136.54
        )
    )

    entry = bridge._entries["COH.AX"]
    assert (entry.price, entry.price_source) == (135.736, "fill")


@pytest.mark.asyncio
async def test_the_stamp_survives_a_restart(tmp_path):
    bridge = _bridge(tmp_path)
    await bridge._on_fill(_buy(135.736, price_is_fill=True))

    assert _bridge(tmp_path)._entries["COH.AX"].price_source == "fill"


def test_a_pre_m175_record_loads_with_no_stamp(tmp_path):
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "BOQ.AX": {
                    "opened_at": "2026-08-25T00:30:04.620473+00:00",
                    "price": 6.3856144,
                    "stop_price": 6.07,
                    "target_price": 7.05,
                    "strategy": "swing",
                    "reference_price": None,
                }
            }
        ),
        encoding="utf-8",
    )
    assert _bridge(tmp_path)._entries["BOQ.AX"].price_source is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/domain/oms/test_entry_price_source.py -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'price_is_fill'`.

- [ ] **Step 3: Implement**

3a. `events.py`, in `OrderFilledEvent`, after the `exit_reason` field and its docstring:

```python
    price_is_fill: bool = False
    """Whether `price` is what the broker actually charged, rather than the
    price the order was sized against (M175). `_announce_fill` publishes at
    "transmitted" as well as "filled", and at transmit only the reference
    exists. The entry record stamps which one it holds, so a restart never
    replaces an observed fill with a derived one."""
```

3b. `oms.py`, in `_announce_fill`'s `OrderFilledEvent(...)`, add after `earnings_at_entry=order.earnings_date,`:

```python
                price_is_fill=bool(order.filled_price),
```

3c. `signal_bridge.py`: add `Literal` to the `typing` import if absent. In `_Entry`, after `reference_price: float | None = None`, add:

```python
    # Where `price` came from (M175). "fill" is an OBSERVED fill - announced at
    # its fill price, or corrected mid-session by M70 - and M65 must never
    # overwrite it with a figure DERIVED from the broker's average cost.
    # "reference" is the sizing price published at transmit. `None` is a
    # record written before M175, which says neither.
    price_source: Literal["fill", "reference"] | None = None
```

In `_on_fill`, inside the `_Entry(...)` for a buy, after `reference_price=event.reference_price,` add:

```python
                    price_source="fill" if event.price_is_fill else "reference",
```

In `_on_entry_price_corrected`, change `replace(entry, price=event.price)` to:

```python
        self._entries[event.symbol] = replace(entry, price=event.price, price_source="fill")
```

In `_load_entries`, inside `_Entry(...)`, after the `reference_price=(...)` argument add:

```python
                    # M175, `.get` for the fourth time: a pre-M175 record says
                    # nothing about where its price came from, and None is that.
                    price_source=(
                        row["price_source"]
                        if row.get("price_source") in ("fill", "reference")
                        else None
                    ),
```

In `_save_entries`, add to the per-symbol dict after `"reference_price": entry.reference_price,`:

```python
                "price_source": entry.price_source,
```

- [ ] **Step 4: Run to verify they pass, plus the bridge and OMS suites**

Run: `py -m pytest tests/domain/oms tests/safety -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/events.py src/qat/domain/oms/oms.py src/qat/domain/oms/signal_bridge.py tests/domain/oms/test_entry_price_source.py
git commit -m "M175: the entry record says whether its price is an observed fill" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: M65 never overwrites a fill, and de-commissions IBKR's average cost

**Files:**
- Modify: `src/qat/domain/oms/signal_bridge.py` — `reconcile_entry_prices` (lines ~523-589) and imports
- Modify: `src/qat/data/broker/ib_adapter.py` — class attribute on `IBAdapter`
- Test: `tests/safety/test_entry_price_reconciliation.py` (append)

**Interfaces:**
- Consumes: `_Entry.price_source` (Task 3); `CostModel.fill_price_from_average_cost` (Task 1).
- Produces: `IBAdapter.avg_price_includes_commission = True` (class attribute). Any other broker is read raw via `getattr(broker, "avg_price_includes_commission", False)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/safety/test_entry_price_reconciliation.py`:

```python
# --- M175: IBKR's average cost is commission-INCLUSIVE --------------------------
#
# Every restart rewrote every position to avgCost, because the 1 bp tolerance is
# tighter than the 8.8 bp commission - and it undid M70's correct price:
#   31 Aug 10:35  ENTRY PRICE CORRECTED: JHX.AX filled at 41.9185
#   31 Aug 13:38  Corrected the recorded entry price for JHX.AX -> 41.9554


class _IBLikeBroker(_Broker):
    avg_price_includes_commission = True


def _ib_bridge(tmp_path, positions: dict[str, tuple[float, float]]):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")
    bus = EventBus()
    switch = KillSwitch()
    broker = _IBLikeBroker(positions)
    oms = OMS(broker, RiskEngine(bus, switch, settings=settings), switch, settings=settings)
    return SignalToOrderBridge(bus=bus, oms=oms, settings=settings)


@pytest.mark.asyncio
async def test_an_observed_fill_is_never_overwritten(tmp_path):
    bridge = _ib_bridge(tmp_path, {"JHX.AX": (1097.0, 41.95541155)})
    bridge._entries["JHX.AX"] = replace(_entry(41.9185, stop=39.39), price_source="fill")

    assert await bridge.reconcile_entry_prices() == []
    assert bridge._entries["JHX.AX"].price == pytest.approx(41.9185)


@pytest.mark.asyncio
async def test_ibkr_average_cost_is_converted_back_to_the_fill(tmp_path):
    """BHP.AX: a record still at the 64.08 reference, avgCost 64.1263816."""
    bridge = _ib_bridge(tmp_path, {"BHP.AX": (793.0, 64.1263816)})
    bridge._entries["BHP.AX"] = replace(_entry(64.08, stop=60.45), price_source="reference")

    assert await bridge.reconcile_entry_prices() == ["BHP.AX"]
    assert bridge._entries["BHP.AX"].price == pytest.approx(64.07, abs=1e-6)


@pytest.mark.asyncio
async def test_a_record_already_at_the_fill_is_left_alone(tmp_path):
    """The regression itself: an unstamped record holding the true fill must
    NOT be 'corrected' up to avgCost."""
    bridge = _ib_bridge(tmp_path, {"COH.AX": (363.0, 135.85548075)})
    bridge._entries["COH.AX"] = _entry(135.73603304, stop=126.09)

    assert await bridge.reconcile_entry_prices() == []


@pytest.mark.asyncio
async def test_below_the_floor_the_conversion_takes_the_floor_off(tmp_path):
    bridge = _ib_bridge(tmp_path, {"XYZ.AX": (10.0, 50.66)})
    bridge._entries["XYZ.AX"] = _entry(51.00, stop=45.0)

    assert await bridge.reconcile_entry_prices() == ["XYZ.AX"]
    assert bridge._entries["XYZ.AX"].price == pytest.approx(50.0)


def test_the_ibkr_adapter_declares_its_average_cost_commission_inclusive():
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.mock_broker import MockBroker

    assert IBAdapter.avg_price_includes_commission is True
    assert getattr(MockBroker(seed=1), "avg_price_includes_commission", False) is False
```

Also add `from dataclasses import replace` to that file's imports.

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/safety/test_entry_price_reconciliation.py -v`
Expected: the four new async tests FAIL (price overwritten to the average / not converted); the adapter test FAILS with `AttributeError`. The seven existing tests still PASS.

- [ ] **Step 3: Implement**

3a. `signal_bridge.py` imports: add `from qat.domain.backtester.costs import CostModel`.

3b. In `reconcile_entry_prices`, replace everything from `corrected: list[str] = []` down to (not including) `if corrected:` with:

```python
        # M175. IBKR's `avgCost` is commission-INCLUSIVE (Alpaca's average was
        # not), so read raw it put every entry 8.8 bp high and charged the
        # commission twice - once in the price, once in `entry_cost`. An adapter
        # that says so has it converted back to the fill first.
        includes_commission = bool(
            getattr(self.oms.broker, "avg_price_includes_commission", False)
        )
        costs = CostModel.from_settings(self.settings)
        corrected: list[str] = []
        for position in positions:
            entry = self._entries.get(position.symbol)
            if entry is None or not position.avg_price:
                continue
            if entry.price_source == "fill":
                # An OBSERVED fill beats anything derived from an average - the
                # JHX.AX and COH.AX regression, where this overwrote M70's price.
                continue
            # A corporate action changes avg_entry_price legitimately - a
            # 2-for-1 split halves it - so correcting to the post-event figure
            # would silently rewrite the basis of a position M60 exists to stop
            # anything touching.
            if self.oms.anomalies.is_quarantined(position.symbol):
                continue
            paid = float(position.avg_price)
            if includes_commission:
                paid = costs.fill_price_from_average_cost(paid, float(position.quantity))
            if abs(paid - entry.price) <= _ENTRY_PRICE_TOLERANCE * abs(entry.price):
                continue
            self._entries[position.symbol] = replace(entry, price=paid)
            corrected.append(position.symbol)
```

(The corrected record is NOT stamped "fill": its price is derived, and re-deriving it next launch lands inside the tolerance.)

3c. `ib_adapter.py`, in `class IBAdapter:` directly under `name = "ib-adapter"`:

```python
    # IBKR's position `avgCost` INCLUDES the commission (M175): avgCost x qty =
    # fill x qty + commission. Measured 11 September on 17 orders. M65 reads
    # this to convert back to the fill; every other broker is read raw.
    avg_price_includes_commission = True
```

- [ ] **Step 4: Run to verify they pass**

Run: `py -m pytest tests/safety/test_entry_price_reconciliation.py tests/domain/oms -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/oms/signal_bridge.py src/qat/data/broker/ib_adapter.py tests/safety/test_entry_price_reconciliation.py
git commit -m "M175: M65 never overwrites a fill, and takes IBKR's commission out of avgCost" -m "Other avg_price readers (governor fallbacks, delever, book-risk weights, corporate-action basis) are risk estimates where 8.8 bp is immaterial - deliberately unchanged." -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: IBAdapter totals IBKR's commission reports per order

**Files:**
- Modify: `src/qat/data/broker/adapter.py` — new dataclass `BrokerCommission` after `BrokerFill`
- Modify: `src/qat/data/broker/ib_adapter.py` — imports, module helpers, `__init__`, `connect`, three new methods
- Modify: `tests/data/broker/conftest.py` — `FakeIBClient.__init__` gains `self.commissionReportEvent = FakeErrorEvent()`
- Test: `tests/data/broker/test_ib_commission_reports.py` (create)

**Interfaces:**
- Produces: `BrokerCommission(order_id: str, symbol: str, side: Literal["buy","sell"], quantity: float, notional: float, commission: float, currency: str)`; `IBAdapter.set_commission_listener(listener: Callable[[BrokerCommission], None]) -> None`; `IBAdapter._on_ib_commission(trade, fill, report) -> None`. Task 6 consumes both.

- [ ] **Step 1: Write the failing tests**

```python
"""IBKR's own commission, totalled per order (M175).

Measured 11 September: a second client's `reqExecutions` returned BHP's 10:00
stop execution with commission 0.0 and no commissionReport - so the figure only
arrives, if at all, on `commissionReportEvent` to a connected client. One report
per EXECUTION; an order is complete when its executions cover its quantity.
Real ib_async types throughout - a friendlier fake is how M174's feed check
passed its tests and never ran.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ib_async import CommissionReport, Contract, Execution, Fill
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.data.broker.adapter import BrokerCommission

_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
_PERM = 750830217


def _trade(total: float) -> Trade:
    return Trade(
        contract=Contract(symbol="BHP"),
        order=IBOrder(totalQuantity=total),
        orderStatus=OrderStatus(status="Filled"),
    )


def _fill(exec_id: str, shares: float, price: float, side: str = "SLD") -> Fill:
    return Fill(
        contract=Contract(symbol="BHP", secType="STK", exchange="ASX", currency="AUD"),
        execution=Execution(execId=exec_id, side=side, shares=shares, price=price, permId=_PERM),
        commissionReport=CommissionReport(),
        time=_NOW,
    )


def _report(exec_id: str, commission: float, currency: str = "AUD") -> CommissionReport:
    return CommissionReport(execId=exec_id, commission=commission, currency=currency)


def _listen(adapter) -> list[BrokerCommission]:
    seen: list[BrokerCommission] = []
    adapter.set_commission_listener(seen.append)
    return seen


@pytest.mark.asyncio
async def test_connect_subscribes_the_commission_handler(adapter):
    await adapter.connect()
    assert adapter._on_ib_commission in adapter.ib_client.commissionReportEvent.listeners
    await adapter.disconnect()


def test_a_one_execution_order_is_reported_when_its_commission_arrives(adapter):
    seen = _listen(adapter)

    adapter._on_ib_commission(_trade(793), _fill("e1", 793, 60.40), _report("e1", 42.149536))

    assert seen == [
        BrokerCommission(
            order_id=str(_PERM),
            symbol="BHP.AX",
            side="sell",
            quantity=793.0,
            notional=pytest.approx(793 * 60.40),  # type: ignore[arg-type]
            commission=pytest.approx(42.149536),  # type: ignore[arg-type]
            currency="AUD",
        )
    ]


def test_a_multi_execution_order_is_reported_once_and_only_when_complete(adapter):
    """RHC.AX's entry was 21 executions; the first was ONE share at 0.039081."""
    seen = _listen(adapter)
    trade = _trade(201)

    adapter._on_ib_commission(trade, _fill("e1", 1, 44.41, "BOT"), _report("e1", 0.039081))
    adapter._on_ib_commission(trade, _fill("e2", 100, 44.41, "BOT"), _report("e2", 3.90808))
    assert seen == []
    adapter._on_ib_commission(trade, _fill("e3", 100, 44.42, "BOT"), _report("e3", 3.908960))

    assert len(seen) == 1
    assert seen[0].side == "buy"
    assert seen[0].quantity == 201.0
    assert seen[0].commission == pytest.approx(0.039081 + 3.90808 + 3.908960)


def test_a_repeated_report_is_not_counted_twice(adapter):
    seen = _listen(adapter)
    trade = _trade(200)

    adapter._on_ib_commission(trade, _fill("e1", 100, 44.41), _report("e1", 3.90808))
    adapter._on_ib_commission(trade, _fill("e1", 100, 44.41), _report("e1", 3.90808))

    assert seen == []


def test_an_unusable_commission_suppresses_the_check(adapter):
    """IBKR sends UNSET_DOUBLE (1.797e308) for a commission it does not have."""
    seen = _listen(adapter)

    adapter._on_ib_commission(
        _trade(793), _fill("e1", 793, 60.40), _report("e1", 1.7976931348623157e308)
    )

    assert seen == []


def test_an_order_with_no_known_total_is_skipped_not_guessed(adapter):
    seen = _listen(adapter)
    no_total = Trade(
        contract=Contract(symbol="BHP"),
        order=IBOrder(totalQuantity=0),
        orderStatus=OrderStatus(),
    )

    adapter._on_ib_commission(no_total, _fill("e1", 793, 60.40), _report("e1", 42.15))
    adapter._on_ib_commission(None, _fill("e2", 793, 60.40), _report("e2", 42.15))

    assert seen == []


def test_a_listener_that_raises_never_escapes_into_ib_async(adapter, caplog):
    def boom(_: BrokerCommission) -> None:
        raise RuntimeError("listener failed")

    adapter.set_commission_listener(boom)

    # Reaching the assertion at all is half the test: nothing propagated.
    adapter._on_ib_commission(_trade(793), _fill("e1", 793, 60.40), _report("e1", 42.15))

    assert "Could not tally an IBKR commission report" in caplog.text
    assert "listener failed" in caplog.text  # the traceback was kept, not swallowed
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/data/broker/test_ib_commission_reports.py -v`
Expected: FAIL — `ImportError: cannot import name 'BrokerCommission'`.

- [ ] **Step 3: Implement**

3a. `adapter.py`, directly after the `BrokerFill` class:

```python
@dataclass(frozen=True, slots=True)
class BrokerCommission:
    """What the broker billed for ONE completed order, as it reported it (M175).

    Totalled across the order's executions - IBKR sends one commission report
    per execution, and the per-order floor is spread across them. A plain
    record, so the judging happens in the domain (`CommissionAuditor`) and the
    data layer never imports the cost model.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    notional: float
    commission: float
    currency: str
```

3b. `ib_adapter.py` imports: change `from collections.abc import Awaitable` to `from collections.abc import Awaitable, Callable`; add `from dataclasses import dataclass, field`; change `from typing import Any, TypeVar` to `from typing import Any, Literal, TypeVar`; add `BrokerCommission` to the `qat.data.broker.adapter` import list.

3c. `ib_adapter.py`, module level, after `_CANCEL_CONFIRM_INTERVAL_SECONDS = 0.7`:

```python
# IBKR's execution sides - the same strict mapping `from_ib_fill` applies.
_COMMISSION_SIDES: dict[str, Literal["buy", "sell"]] = {"BOT": "buy", "SLD": "sell"}

# IBKR reports a commission it does not have as UNSET_DOUBLE (~1.8e308).
# Anything at or above this is "no figure", never a charge.
_UNUSABLE_COMMISSION = 1e9


@dataclass
class _CommissionTally:
    """One order's commission reports so far (M175)."""

    symbol: str
    side: Literal["buy", "sell"]
    total_quantity: float
    shares: float = 0.0
    notional: float = 0.0
    commission: float = 0.0
    currency: str = ""
    usable: bool = True
    exec_ids: set[str] = field(default_factory=set)


def _order_total_quantity(trade: object) -> float | None:
    """The order's full size, or None when the report cannot say.

    `order.totalQuantity` first; `filled + remaining` from the status second.
    None means the check cannot tell when the order is complete - which is
    reported, never guessed.
    """
    order = getattr(trade, "order", None)
    total = float(getattr(order, "totalQuantity", 0.0) or 0.0)
    if total > 0:
        return total
    status = getattr(trade, "orderStatus", None)
    filled = float(getattr(status, "filled", 0.0) or 0.0)
    remaining = float(getattr(status, "remaining", 0.0) or 0.0)
    return filled + remaining if filled + remaining > 0 else None
```

3d. `IBAdapter.__init__`, after `self._ib_groups: dict[str, list[object]] = {}`:

```python
        # M175. Where a completed order's commission goes; None until wired.
        self._commission_listener: Callable[[BrokerCommission], None] | None = None
        self._commission_tallies: dict[str, _CommissionTally] = {}
        self._commission_unknown_total: set[str] = set()
```

3e. `connect()`, directly after the `errorEvent` `if/else` block and before `return`:

```python
            # M175. The ONLY place IBKR's own commission arrives - a second
            # client's reqExecutions returned BHP's stop with commission 0.0 on
            # 11 September. Same getattr rule as errorEvent, and subscribed on
            # this success path only, so a reconnect adds no duplicate.
            commission_event = getattr(self.ib_client, "commissionReportEvent", None)
            if commission_event is not None:
                commission_event += self._on_ib_commission
```

3f. New methods on `IBAdapter`, placed directly before `def _on_ib_error(`:

```python
    def set_commission_listener(self, listener: Callable[[BrokerCommission], None]) -> None:
        """Where each completed order's commission is handed (M175)."""
        self._commission_listener = listener

    def _on_ib_commission(self, trade: object, fill: object, report: object) -> None:
        """ib_async's `commissionReportEvent`. Never raises - like
        `_on_ib_error`, it runs inside the library's own dispatch, where an
        exception would vanish. A check that fails costs a check, not an order.
        """
        try:
            self._tally_commission(trade, fill, report)
        except Exception:  # noqa: BLE001 - see docstring
            logger.exception(
                "Could not tally an IBKR commission report - that order's commission "
                "goes unchecked"
            )

    def _tally_commission(self, trade: object, fill: object, report: object) -> None:
        execution = getattr(fill, "execution", None)
        contract = getattr(fill, "contract", None)
        if execution is None or contract is None:
            return
        side = _COMMISSION_SIDES.get(str(getattr(execution, "side", "")).upper())
        order_id = str(getattr(execution, "permId", 0) or "")
        exec_id = str(getattr(execution, "execId", "") or "")
        if side is None or not order_id or not exec_id:
            return
        tally = self._commission_tallies.get(order_id)
        if tally is None:
            total = _order_total_quantity(trade)
            if total is None:
                if order_id not in self._commission_unknown_total:
                    self._commission_unknown_total.add(order_id)
                    logger.info(
                        "IBKR order %s reported no total quantity, so the commission check "
                        "cannot tell when it is complete - skipped, not guessed",
                        order_id,
                    )
                return
            tally = _CommissionTally(
                symbol=from_ibkr(str(getattr(contract, "symbol", "")), self.settings.market),
                side=side,
                total_quantity=total,
            )
            self._commission_tallies[order_id] = tally
        if exec_id in tally.exec_ids:
            return
        tally.exec_ids.add(exec_id)
        shares = float(getattr(execution, "shares", 0.0) or 0.0)
        tally.shares += shares
        tally.notional += shares * float(getattr(execution, "price", 0.0) or 0.0)
        commission = float(getattr(report, "commission", math.nan))
        if math.isfinite(commission) and 0.0 <= commission < _UNUSABLE_COMMISSION:
            tally.commission += commission
        else:
            tally.usable = False
        tally.currency = str(getattr(report, "currency", "") or tally.currency)
        if tally.shares + 1e-9 < tally.total_quantity:
            return
        del self._commission_tallies[order_id]
        if not tally.usable:
            logger.info(
                "IBKR sent no usable commission for part of order %s (%s) - its commission "
                "check is skipped",
                order_id,
                tally.symbol,
            )
            return
        if self._commission_listener is not None:
            self._commission_listener(
                BrokerCommission(
                    order_id=order_id,
                    symbol=tally.symbol,
                    side=tally.side,
                    quantity=tally.shares,
                    notional=tally.notional,
                    commission=tally.commission,
                    currency=tally.currency,
                )
            )
```

3g. `tests/data/broker/conftest.py`, in `FakeIBClient.__init__`, after `self.errorEvent = FakeErrorEvent()`:

```python
        self.commissionReportEvent = FakeErrorEvent()
```

- [ ] **Step 4: Run to verify they pass, plus the adapter suite**

Run: `py -m pytest tests/data/broker -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/data/broker/adapter.py src/qat/data/broker/ib_adapter.py tests/data/broker/conftest.py tests/data/broker/test_ib_commission_reports.py
git commit -m "M175: IBAdapter totals IBKR's commission reports per order" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `CommissionAuditor`, and wiring it to the broker

**Files:**
- Create: `src/qat/domain/performance/commission_audit.py`
- Modify: `src/qat/presentation/runtime.py` — imports, and after `trade_ledger = TradeLedger(...)` (line ~608)
- Test: `tests/domain/performance/test_commission_audit.py` (create)

**Interfaces:**
- Consumes: `BrokerCommission` (Task 5), `CostModel.charge` (Task 1), `mc.currency_for(market)` from `qat.domain.market_calendar`.
- Produces: `CommissionAuditor(data_dir, settings, clock=...)`, `.check(report: BrokerCommission) -> CommissionCheck`, `COMMISSION_CHECKS_FILENAME = "commission_checks.csv"`.

- [ ] **Step 1: Write the failing tests**

```python
"""IBKR's own commission against the model the ledger records (M175)."""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import BrokerCommission
from qat.data.broker.mock_broker import MockBroker
from qat.domain.performance.commission_audit import (
    COMMISSION_CHECKS_FILENAME,
    CommissionAuditor,
)

_WHEN = datetime(2026, 9, 11, 0, 3, 22, tzinfo=UTC)


def _report(**overrides) -> BrokerCommission:
    fields = {
        "order_id": "750830217",
        "symbol": "BHP.AX",
        "side": "sell",
        "quantity": 793.0,
        "notional": 793 * 60.40,
        "commission": 42.149536,
        "currency": "AUD",
    }
    fields.update(overrides)
    return BrokerCommission(**fields)  # type: ignore[arg-type]


def _auditor(tmp_path) -> CommissionAuditor:
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")
    return CommissionAuditor(tmp_path, settings=settings, clock=lambda: _WHEN)


def _rows(tmp_path) -> list[dict[str, str]]:
    with (tmp_path / COMMISSION_CHECKS_FILENAME).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_a_matching_commission_is_verified_and_recorded(tmp_path, caplog):
    caplog.set_level(logging.INFO)

    check = _auditor(tmp_path).check(_report())

    assert check.agrees
    assert check.modelled == pytest.approx(42.15, abs=0.01)
    [row] = _rows(tmp_path)
    assert row["order_id"] == "750830217"
    assert row["agrees"] == "True"
    assert "COMMISSION VERIFIED" in caplog.text


def test_a_different_commission_is_a_warning(tmp_path, caplog):
    check = _auditor(tmp_path).check(_report(commission=50.00))

    assert not check.agrees
    assert any(
        r.levelno == logging.WARNING and "COMMISSION DISAGREES" in r.getMessage()
        for r in caplog.records
    )


def test_a_currency_other_than_the_markets_disagrees(tmp_path):
    assert not _auditor(tmp_path).check(_report(currency="USD")).agrees


def test_checks_append_under_one_header(tmp_path):
    auditor = _auditor(tmp_path)
    auditor.check(_report())
    auditor.check(_report(order_id="750830242", symbol="SEK.AX"))

    assert [r["symbol"] for r in _rows(tmp_path)] == ["BHP.AX", "SEK.AX"]


def test_an_unwritable_file_is_logged_never_raised(tmp_path, caplog):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")

    check = CommissionAuditor(blocker, settings=settings, clock=lambda: _WHEN).check(_report())

    assert check.agrees
    assert "Could not record" in caplog.text


def test_the_runtime_hands_the_auditor_to_a_broker_that_reports_commissions(tmp_path):
    """Wiring, not mechanism - this project's recurring failure is machinery
    built and never reached."""
    from qat.presentation.runtime import Runtime

    class _ListeningBroker(MockBroker):
        def __init__(self) -> None:
            super().__init__(seed=1)
            self.listener = None

        def set_commission_listener(self, listener) -> None:
            self.listener = listener

    broker = _ListeningBroker()
    Runtime.build_demo(
        settings=Settings(_env_file=None, data_dir=str(tmp_path), market="ASX"),
        broker=broker,  # type: ignore[arg-type]
    )

    assert broker.listener is not None
    assert type(broker.listener.__self__).__name__ == "CommissionAuditor"  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/domain/performance/test_commission_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qat.domain.performance.commission_audit'`.

- [ ] **Step 3: Implement** — create `src/qat/domain/performance/commission_audit.py`:

```python
"""IBKR's own commission, checked against the model the ledger records (M175).

The ledger records the MODELLED charge, and that is deliberate: measured
11 September, IBKR's commission equals the model on 17 of 17 logged orders, and
a report only arrives for fills the app is connected for - so actuals could
never cover every row. What was wrong was that the actuals were thrown away.
Now every one the app hears about checks the model, in its own file joined to
the ledger on `order_id`, because a report arrives AFTER the fill is recorded
and marking the ledger row would mean amending rows already written.
"""

from __future__ import annotations

import csv
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qat.config import Settings
from qat.data.broker.adapter import BrokerCommission
from qat.domain import market_calendar as mc
from qat.domain.backtester.costs import CostModel

logger = logging.getLogger(__name__)

COMMISSION_CHECKS_FILENAME = "commission_checks.csv"
_FIELDS = (
    "checked_at",
    "order_id",
    "symbol",
    "side",
    "quantity",
    "notional",
    "actual",
    "modelled",
    "currency",
    "agrees",
)
# One cent. The model and IBKR agreed to the cent on every order measured.
_TOLERANCE = 0.01


@dataclass(frozen=True, slots=True)
class CommissionCheck:
    order_id: str
    symbol: str
    side: str
    quantity: float
    notional: float
    actual: float
    modelled: float
    currency: str
    agrees: bool


class CommissionAuditor:
    def __init__(
        self,
        data_dir: str | Path,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = Path(data_dir) / COMMISSION_CHECKS_FILENAME
        self._costs = CostModel.from_settings(settings)
        self._currency = mc.currency_for(settings.market)
        self._clock = clock
        self._lock = threading.Lock()

    def check(self, report: BrokerCommission) -> CommissionCheck:
        """Compare, record, and say so. Never raises: it is called from
        ib_async's own dispatch, where an exception would vanish."""
        modelled = self._costs.charge(report.notional)
        agrees = (
            abs(report.commission - modelled) <= _TOLERANCE and report.currency == self._currency
        )
        result = CommissionCheck(
            order_id=report.order_id,
            symbol=report.symbol,
            side=report.side,
            quantity=report.quantity,
            notional=report.notional,
            actual=report.commission,
            modelled=modelled,
            currency=report.currency,
            agrees=agrees,
        )
        self._append(result)
        if agrees:
            logger.info(
                "COMMISSION VERIFIED: %s %s %g (order %s) - IBKR charged %.2f %s, the model "
                "says %.2f",
                report.side,
                report.symbol,
                report.quantity,
                report.order_id,
                report.commission,
                report.currency,
                modelled,
            )
        else:
            logger.warning(
                "COMMISSION DISAGREES: %s %s %g (order %s) - IBKR charged %.2f %s, the model "
                "says %.2f %s. The ledger records the MODEL, so this trade's costs are wrong by "
                "the difference until it is explained (M175).",
                report.side,
                report.symbol,
                report.quantity,
                report.order_id,
                report.commission,
                report.currency,
                modelled,
                self._currency,
            )
        return result

    def _append(self, result: CommissionCheck) -> None:
        row = {
            "checked_at": self._clock().isoformat(timespec="seconds"),
            "order_id": result.order_id,
            "symbol": result.symbol,
            "side": result.side,
            "quantity": round(result.quantity, 6),
            "notional": round(result.notional, 2),
            "actual": round(result.actual, 6),
            "modelled": round(result.modelled, 6),
            "currency": result.currency,
            "agrees": str(result.agrees),
        }
        try:
            with self._lock:
                new = not self.path.exists()
                with self.path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
                    if new:
                        writer.writeheader()
                    writer.writerow(row)
        except OSError:
            logger.exception("Could not record the commission check for order %s", result.order_id)
```

In `runtime.py`, add the import `from qat.domain.performance.commission_audit import CommissionAuditor` beside the other `qat.domain.performance` imports, and directly after `trade_ledger = TradeLedger(bus, settings.data_dir, settings=settings)`:

```python
        # IBKR's own commission, checked against the model the ledger records
        # (M175). Only an adapter that reports commissions offers the hook.
        commission_auditor = CommissionAuditor(settings.data_dir, settings=settings)
        set_commission_listener = getattr(broker, "set_commission_listener", None)
        if callable(set_commission_listener):
            set_commission_listener(commission_auditor.check)
```

- [ ] **Step 4: Run to verify they pass**

Run: `py -m pytest tests/domain/performance/test_commission_audit.py tests/test_m111_trading_day.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/qat/domain/performance/commission_audit.py src/qat/presentation/runtime.py tests/domain/performance/test_commission_audit.py
git commit -m "M175: CommissionAuditor - every IBKR commission report checks the model" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The rewrite — evidence, self-check, and the script

**Files:**
- Create: `src/qat/domain/performance/fill_basis_repair.py` (pure logic, typed, tested)
- Create: `scripts/repair_fill_basis.py` (thin CLI; dry run by default)
- Test: `tests/domain/performance/test_fill_basis_repair.py` (create)

**Interfaces:**
- Consumes: `CostModel.charge`, `CostModel.fill_price_from_average_cost` (Task 1); `ClosedTrade`, `_FIELDS`, `_reseeded`, `audit_closed_trades` from `trades.py`; `from_ibkr` from `qat.data.symbols`; `_Entry.price_source` value `"fill"` (Task 3).
- Produces: `parse_m65_corrections`, `parse_logged_buys`, `evidence_for`, `repair_closed_rows`, `repair_open_records`, `SelfCheckFailed`, `SELF_CHECK_DOLLARS = 0.25`.

- [ ] **Step 1: Write the failing tests**

```python
"""The rewrite of records whose entry price is IBKR's commission-inclusive
average (M175). Fixtures only - never the live ledger. Log lines are the REAL
formats, copied from qat.log."""

from __future__ import annotations

import csv
from datetime import UTC, datetime

import pytest

from qat.domain.backtester.costs import CostModel
from qat.domain.performance.fill_basis_repair import (
    SelfCheckFailed,
    evidence_for,
    parse_logged_buys,
    parse_m65_corrections,
    repair_closed_rows,
    repair_open_records,
)
from qat.domain.performance.trades import _FIELDS, ClosedTrade, audit_closed_trades

_COSTS = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=6.60)

_M65 = (
    "Corrected the recorded entry price for BHP.AX -> 64.1264 to what the broker charged. "
    "The record held the price the order was SIZED against, not the price it filled at, so "
    "P&L and every R-multiple on these was wrong by that difference."
)
_M65_PAIR = (
    "Corrected the recorded entry price for RHC.AX -> 44.4523, TNE.AX -> 32.9783 to what the "
    "broker charged. The record held the price the order was SIZED against."
)


def _exec(exec_id: str, symbol: str, shares: float, price: float, perm: int, side="BOT") -> str:
    return (
        f"execDetails: Fill(contract=Stock(conId=12565187, symbol='{symbol}', exchange='SMART', "
        f"currency='AUD', localSymbol='{symbol}', tradingClass='{symbol}'), "
        f"execution=Execution(execId='{exec_id}', time=datetime.datetime(2026, 8, 24, 18, 5, 24, "
        f"tzinfo=datetime.timezone.utc), acctNumber='DUQ200898', exchange='SMART', side='{side}', "
        f"shares={shares}, price={price}, permId={perm}, clientId=1, orderId=417, liquidation=0, "
        f"cumQty={shares}, avgPrice={price}, orderRef='')"
    )


def _row(**overrides) -> dict[str, str]:
    trade = ClosedTrade(
        symbol="BHP.AX",
        strategy="swing",
        quantity=793.0,
        entry_price=64.1263816,
        exit_price=60.40,
        stop_price=60.45,
        opened_at=datetime(2026, 9, 9, 4, 5, 11, tzinfo=UTC),
        closed_at=datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
        entry_cost=70.18,
        exit_cost=66.10,
        reference_price=64.08000183,
        worst_price=60.40,
        best_price=64.9,
        order_id="750830217",
        market="ASX",
        currency="AUD",
    )
    row = {k: str(v) for k, v in trade.as_row().items()}
    row.update(overrides)
    return row


def test_the_m65_line_is_parsed_into_the_strings_it_wrote():
    found = parse_m65_corrections([_M65, _M65_PAIR, "unrelated"])
    assert found == {"BHP.AX": {"64.1264"}, "RHC.AX": {"44.4523"}, "TNE.AX": {"32.9783"}}


def test_logged_buys_are_totalled_per_order_and_sells_ignored():
    buys = parse_logged_buys(
        [
            _exec("x1", "RHC", 1.0, 44.41, 1216558923),
            _exec("x2", "RHC", 100.0, 44.41, 1216558923),
            _exec("x3", "RHC", 50.0, 44.50, 1216558999, side="SLD"),
        ],
        market="ASX",
    )
    assert len(buys) == 1
    assert (buys[0].symbol, buys[0].quantity) == ("RHC.AX", 101.0)
    assert buys[0].average_price == pytest.approx(44.41)


def test_no_m65_line_means_no_evidence():
    assert evidence_for("BHP.AX", 64.1263816, 793.0, {}, [], _COSTS) is None


def test_without_a_logged_fill_the_formula_is_the_evidence():
    ev = evidence_for("BHP.AX", 64.1263816, 793.0, {"BHP.AX": {"64.1264"}}, [], _COSTS)
    assert ev is not None
    assert ev.fill == pytest.approx(64.07, abs=1e-6)
    assert ev.order_quantity is None


def test_a_logged_fill_that_reproduces_is_preferred():
    buys = parse_logged_buys([_exec("x1", "BHP", 793.0, 64.07, 1)], market="ASX")
    ev = evidence_for("BHP.AX", 64.1263816, 793.0, {"BHP.AX": {"64.1264"}}, buys, _COSTS)
    assert ev is not None
    assert ev.fill == 64.07
    assert ev.order_quantity == 793.0
    assert "logged" in ev.source


def test_the_self_check_refuses_when_no_logged_fill_reproduces():
    buys = parse_logged_buys([_exec("x1", "BHP", 793.0, 63.00, 1)], market="ASX")
    with pytest.raises(SelfCheckFailed):
        evidence_for("BHP.AX", 64.1263816, 793.0, {"BHP.AX": {"64.1264"}}, buys, _COSTS)


def test_the_bhp_row_is_restored_and_charged_commission_only():
    [repair] = repair_closed_rows([_row()], {"BHP.AX": {"64.1264"}}, [], _COSTS)

    after = repair.after
    assert after.entry_price == pytest.approx(64.07, abs=1e-6)
    assert after.entry_cost == pytest.approx(_COSTS.charge(793 * 64.07))
    assert after.exit_cost == pytest.approx(_COSTS.charge(793 * 60.40))
    assert after.entry_slippage == pytest.approx(-0.01, abs=1e-4)  # was +0.0464


def test_a_row_without_evidence_keeps_its_price_but_loses_its_slippage():
    [repair] = repair_closed_rows([_row()], {}, [], _COSTS)

    assert repair.after.entry_price == pytest.approx(64.1263816)
    assert repair.evidence is None
    assert repair.after.exit_cost == pytest.approx(_COSTS.charge(793 * 60.40))


def test_one_exit_order_across_rows_pays_one_floor():
    small = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=6.60)
    rows = [
        _row(quantity="10.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
        _row(quantity="15.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
    ]
    repairs = repair_closed_rows(rows, {}, [], small)

    # 25 x 21 = 525 of notional: one 6.60 floor for the order, split 10:15.
    assert sum(r.after.exit_cost for r in repairs) == pytest.approx(6.60)


def test_a_fragment_is_charged_its_share_and_never_a_whole_floor():
    """TNE.AX: 60 shares of a 3,051-share entry; the rest left another way."""
    buys = parse_logged_buys([_exec("t1", "TNE", 3051.0, 32.94925926, 509334698)], market="ASX")
    row = _row(
        symbol="TNE.AX",
        quantity="60.0",
        entry_price="32.9783",
        stop_price="30.0",
        exit_price="30.6858",
        order_id="509334700",
        reference_price="",
        worst_price="30.6858",
        best_price="33.5",
    )
    [repair] = repair_closed_rows([row], {"TNE.AX": {"32.9783"}}, buys, _COSTS)

    assert repair.fragment
    assert repair.after.entry_cost == pytest.approx(
        _COSTS.charge(3051 * 32.94925926) * 60 / 3051
    )
    assert repair.after.exit_cost == pytest.approx(60 * 30.6858 * 8.8 / 10_000)


def test_the_repaired_rows_pass_the_ledgers_own_audit(tmp_path):
    repairs = repair_closed_rows([_row()], {"BHP.AX": {"64.1264"}}, [], _COSTS)
    path = tmp_path / "closed_trades.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(r.after.as_row() for r in repairs)

    assert audit_closed_trades(path) == []


def test_open_records_get_the_fill_and_the_stamp():
    records = {
        "BOQ.AX": {"opened_at": "2026-08-25T00:30:04+00:00", "price": 6.3856144,
                   "stop_price": 6.07, "target_price": 7.05, "strategy": "swing",
                   "reference_price": None},
        "XYZ.AX": {"opened_at": "2026-08-25T00:30:04+00:00", "price": 10.0,
                   "stop_price": 9.0, "target_price": None, "strategy": "swing",
                   "reference_price": None},
    }
    repaired, changes = repair_open_records(records, {"BOQ.AX": {"6.38561"}}, [], _COSTS)

    assert repaired["BOQ.AX"]["price"] == pytest.approx(6.38, abs=1e-6)
    assert repaired["BOQ.AX"]["price_source"] == "fill"
    assert repaired["XYZ.AX"] == records["XYZ.AX"]  # no evidence, untouched
    assert [c.symbol for c in changes] == ["BOQ.AX"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `py -m pytest tests/domain/performance/test_fill_basis_repair.py -v`
Expected: FAIL — `ModuleNotFoundError: ... fill_basis_repair`.

- [ ] **Step 3: Implement the module** — create `src/qat/domain/performance/fill_basis_repair.py`:

```python
"""Rebuild records whose entry price is IBKR's commission-inclusive average (M175).

`reconcile_entry_prices` (M65) wrote IBKR's `avgCost` over the fill at every
restart, and `avgCost` includes the commission - so every stored entry sits
8.8 bp high and `entry_cost` charged the same commission again. Found
11 September on all 12 closed rows and all 10 open records.

Evidence, never blanket:
  * a price is inflated ONLY if a logged M65 line wrote it (matched on the %g
    string M65 printed);
  * the true fill is the logged execDetails average where the logs hold the
    entry, else `CostModel.fill_price_from_average_cost`;
  * SELF-CHECK: where a logged fill exists, the formula must reproduce it within
    SELF_CHECK_DOLLARS over the order, or nothing is written.

Costs are recomputed on EVERY row - option A needs no evidence.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from qat.data.symbols import from_ibkr
from qat.domain.backtester.costs import CostModel
from qat.domain.performance.trades import ClosedTrade, _reseeded

SELF_CHECK_DOLLARS = 0.25

_M65_RE = re.compile(
    r"Corrected the recorded entry price for (?P<body>.+?) to what the broker charged"
)
_M65_PAIR_RE = re.compile(r"(?P<symbol>[A-Z0-9.]+) -> (?P<price>[0-9.eE+-]+)")
_EXEC_RE = re.compile(
    r"execDetails: Fill\(contract=Stock\([^)]*symbol='(?P<sym>[^']+)'.*?"
    r"execId='(?P<exec>[^']+)'.*?side='(?P<side>[A-Z]+)', shares=(?P<shares>[\d.]+), "
    r"price=(?P<price>[\d.]+), permId=(?P<perm>\d+)"
)


class SelfCheckFailed(Exception):
    """The formula did not reproduce a logged fill - write nothing."""


@dataclass(frozen=True, slots=True)
class LoggedBuy:
    order_id: str
    symbol: str
    quantity: float
    average_price: float


@dataclass(frozen=True, slots=True)
class Evidence:
    fill: float
    source: str
    order_quantity: float | None
    """The entry order's whole size, when the logs hold it."""


@dataclass(frozen=True, slots=True)
class RowRepair:
    index: int
    before: ClosedTrade
    after: ClosedTrade
    evidence: Evidence | None
    fragment: bool


@dataclass(frozen=True, slots=True)
class RecordChange:
    symbol: str
    before: float
    after: float
    evidence: Evidence


def read_log_messages(log_dir: Path) -> list[str]:
    """The `message` field of every JSON line in qat.log and its rotations."""
    messages: list[str] = []
    for path in sorted(log_dir.glob("qat.log*")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "Corrected the recorded entry price" not in line and "execDetails" not in line:
                    continue
                try:
                    messages.append(str(json.loads(line)["message"]))
                except (ValueError, KeyError):
                    continue
    return messages


def parse_m65_corrections(messages: Iterable[str]) -> dict[str, set[str]]:
    """symbol -> every %g price string M65 ever wrote for it."""
    found: dict[str, set[str]] = defaultdict(set)
    for message in messages:
        match = _M65_RE.search(message)
        if match is None:
            continue
        for pair in _M65_PAIR_RE.finditer(match["body"]):
            found[pair["symbol"]].add(pair["price"])
    return dict(found)


def parse_logged_buys(messages: Iterable[str], market: str) -> list[LoggedBuy]:
    """BOT executions totalled per permId, in the app's symbol form."""
    seen: set[str] = set()
    totals: dict[str, list[Any]] = {}
    for message in messages:
        if not message.startswith("execDetails"):
            continue
        match = _EXEC_RE.search(message)
        if match is None or match["side"] != "BOT" or match["exec"] in seen:
            continue
        seen.add(match["exec"])
        shares, price = float(match["shares"]), float(match["price"])
        entry = totals.setdefault(match["perm"], [from_ibkr(match["sym"], market), 0.0, 0.0])
        entry[1] += shares
        entry[2] += shares * price
    return [
        LoggedBuy(order_id=perm, symbol=sym, quantity=qty, average_price=notional / qty)
        for perm, (sym, qty, notional) in totals.items()
        if qty > 0
    ]


def evidence_for(
    symbol: str,
    stored_price: float,
    quantity: float,
    corrections: dict[str, set[str]],
    buys: list[LoggedBuy],
    costs: CostModel,
) -> Evidence | None:
    """The true fill behind an inflated price, or None when M65 never wrote it."""
    if f"{stored_price:g}" not in corrections.get(symbol, set()):
        return None
    derived = costs.fill_price_from_average_cost(stored_price, quantity)
    candidates = [b for b in buys if b.symbol == symbol]
    for buy in candidates:
        if abs(derived - buy.average_price) * buy.quantity <= SELF_CHECK_DOLLARS:
            return Evidence(buy.average_price, f"logged fill, order {buy.order_id}", buy.quantity)
    if candidates:
        raise SelfCheckFailed(
            f"{symbol}: {len(candidates)} logged buy(s), and none is reproduced by "
            f"{stored_price} / (1 + commission) = {derived:.8f} within "
            f"${SELF_CHECK_DOLLARS} an order - refusing to write anything"
        )
    return Evidence(derived, "IBKR avgCost / (1 + commission rate)", None)


def _proportional(costs: CostModel, notional: float) -> float:
    """The rate without the floor - for a fragment of an order of unknown size."""
    return abs(notional) * (costs.commission_bps + costs.third_party_bps) / 10_000.0


def repair_closed_rows(
    rows: list[dict[str, str]],
    corrections: dict[str, set[str]],
    buys: list[LoggedBuy],
    costs: CostModel,
) -> list[RowRepair]:
    trades: list[ClosedTrade] = []
    for number, row in enumerate(rows):
        trade = ClosedTrade.from_row(row)
        if trade is None:
            raise ValueError(f"row {number + 2} cannot be parsed - refusing to rewrite the file")
        trades.append(trade)

    lots: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, trade in enumerate(trades):
        lots[(trade.symbol, trade.opened_at.isoformat())].append(index)

    fill_of: dict[int, float] = {}
    evidence_of: dict[int, Evidence | None] = {}
    fragment_of: dict[int, bool] = {}
    entry_cost_of: dict[int, float] = {}
    for (symbol, _), members in lots.items():
        stored = trades[members[0]].entry_price
        lot_quantity = sum(trades[i].quantity for i in members)
        ev = evidence_for(symbol, stored, lot_quantity, corrections, buys, costs)
        fill = ev.fill if ev is not None else stored
        whole = ev.order_quantity if ev is not None and ev.order_quantity else lot_quantity
        order_charge = costs.charge(fill * whole)
        for i in members:
            fill_of[i] = fill
            evidence_of[i] = ev
            fragment_of[i] = lot_quantity + 1e-9 < whole
            entry_cost_of[i] = order_charge * trades[i].quantity / whole

    exit_groups: dict[str, list[int]] = defaultdict(list)
    for index, trade in enumerate(trades):
        exit_groups[trade.order_id or f"row-{index}"].append(index)
    exit_cost_of: dict[int, float] = {}
    for members in exit_groups.values():
        quantity = sum(trades[i].quantity for i in members)
        notional = sum(trades[i].quantity * trades[i].exit_price for i in members)
        fragment = any(fragment_of[i] for i in members)
        total = _proportional(costs, notional) if fragment else costs.charge(notional)
        for i in members:
            exit_cost_of[i] = total * trades[i].quantity / quantity

    repairs: list[RowRepair] = []
    for index, before in enumerate(trades):
        fill = fill_of[index]
        after = replace(
            before,
            entry_price=fill,
            entry_cost=entry_cost_of[index],
            exit_cost=exit_cost_of[index],
            worst_price=_reseeded(before.worst_price, before.entry_price, fill, min),
            best_price=_reseeded(before.best_price, before.entry_price, fill, max),
        )
        repairs.append(RowRepair(index, before, after, evidence_of[index], fragment_of[index]))
    return repairs


def repair_open_records(
    records: dict[str, dict[str, Any]],
    corrections: dict[str, set[str]],
    buys: list[LoggedBuy],
    costs: CostModel,
) -> tuple[dict[str, dict[str, Any]], list[RecordChange]]:
    """Open entry records: price -> fill, stamped "fill". Quantity is not on
    the record, so the formula takes its proportional branch - every open
    position is far above the ~AUD 7,500 floor crossover."""
    repaired: dict[str, dict[str, Any]] = {}
    changes: list[RecordChange] = []
    for symbol, record in records.items():
        stored = float(record["price"])
        ev = evidence_for(symbol, stored, 1e12, corrections, buys, costs)
        if ev is None:
            repaired[symbol] = dict(record)
            continue
        repaired[symbol] = {**record, "price": ev.fill, "price_source": "fill"}
        changes.append(RecordChange(symbol, stored, ev.fill, ev))
    return repaired, changes
```

Note for the implementer: `evidence_for(..., 1e12, ...)` passes a quantity large enough that the proportional branch is always the self-consistent one; this is deliberate and the docstring says why.

- [ ] **Step 4: Run to verify they pass**

Run: `py -m pytest tests/domain/performance/test_fill_basis_repair.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the script** — create `scripts/repair_fill_basis.py`:

```python
r"""Rewrite entry prices and costs onto the true fill basis (M175).

    .\.venv\Scripts\python.exe scripts/repair_fill_basis.py            # dry run
    .\.venv\Scripts\python.exe scripts/repair_fill_basis.py --apply    # write

⚠️ POWERSHELL ONLY - it builds Settings() and reads/writes the live data dir.
⚠️ THE APP MUST BE CLOSED, and M175 must be the build launched next: an older
   build's M65 re-inflates the open records at its first startup.

See `qat.domain.performance.fill_basis_repair` for what is changed and on what
evidence. Dry run prints every row and record, before and after, and writes
nothing.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.backtester.costs import CostModel  # noqa: E402
from qat.domain.performance.fill_basis_repair import (  # noqa: E402
    SelfCheckFailed,
    parse_logged_buys,
    parse_m65_corrections,
    read_log_messages,
    repair_closed_rows,
    repair_open_records,
)
from qat.domain.performance.trades import _FIELDS, audit_closed_trades  # noqa: E402


def _app_is_running() -> bool:
    """Same check as prune_entry_records.py: absolute tasklist path, and a
    check that cannot run counts as RUNNING."""
    import subprocess  # nosec B404 - fixed argv, absolute path, no shell, no user input

    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    if not tasklist.exists():
        print(f"  could not find {tasklist} - refusing")
        return True
    try:
        out = subprocess.run(  # nosec B603 - absolute path, fixed argv, shell=False
            [str(tasklist), "/FI", "IMAGENAME eq QuantAdvisoryTerminal.exe"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001 - a failed check must not silently permit
        print("  could not determine whether the app is running - refusing")
        return True
    return "QuantAdvisoryTerminal.exe" in (out.stdout or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write; omit for a dry run")
    args = parser.parse_args()

    if _app_is_running():
        print("REFUSING: QuantAdvisoryTerminal.exe is running. Close it first.")
        return 1

    settings = Settings()
    data = Path(settings.data_dir)
    ledger = data / "closed_trades.csv"
    entries = data / "open_position_entries.json"
    costs = CostModel.from_settings(settings)
    print(f"data    : {data}")
    print(
        f"profile : {costs.commission_bps} bp, floor {costs.min_commission}, "
        f"third-party {costs.third_party_bps} bp"
    )

    messages = read_log_messages(data / "logs")
    corrections = parse_m65_corrections(messages)
    buys = parse_logged_buys(messages, settings.market)
    print(f"evidence: {len(corrections)} symbol(s) with M65 lines, {len(buys)} logged buy order(s)")

    with ledger.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    records = json.loads(entries.read_text(encoding="utf-8"))

    try:
        repairs = repair_closed_rows(rows, corrections, buys, costs)
        repaired_records, changes = repair_open_records(records, corrections, buys, costs)
    except SelfCheckFailed as exc:
        print(f"\nSELF-CHECK FAILED - nothing written.\n  {exc}")
        return 1

    print(f"\n=== closed_trades.csv: {len(repairs)} row(s) ===")
    print(
        f"{'#':>2} {'symbol':7} {'qty':>7} {'entry before':>13} {'entry after':>13} "
        f"{'costs before':>12} {'costs after':>11} {'net before':>11} {'net after':>11} "
        f"{'R before':>8} {'R after':>8} {'slip after':>10}  evidence"
    )
    for r in repairs:
        b, a = r.before, r.after
        ev = r.evidence.source if r.evidence else "NO M65 LINE - price kept"
        flag = "  [FRAGMENT: no floor]" if r.fragment else ""
        slip = f"{a.entry_slippage:+.4f}" if a.entry_slippage is not None else "-"
        rb = f"{b.r_multiple:.4f}" if b.r_multiple is not None else "-"
        ra = f"{a.r_multiple:.4f}" if a.r_multiple is not None else "-"
        print(
            f"{r.index + 2:>2} {b.symbol:7} {b.quantity:>7g} {b.entry_price:>13.8f} "
            f"{a.entry_price:>13.8f} {b.costs:>12.2f} {a.costs:>11.2f} {b.net_pnl:>11.2f} "
            f"{a.net_pnl:>11.2f} {rb:>8} {ra:>8} {slip:>10}  {ev}{flag}"
        )
    print(
        f"   net P&L, all rows: {sum(r.before.net_pnl for r in repairs):,.2f} -> "
        f"{sum(r.after.net_pnl for r in repairs):,.2f}"
    )

    print(f"\n=== open_position_entries.json: {len(changes)} of {len(records)} record(s) ===")
    for c in changes:
        print(f"   {c.symbol:7} {c.before:>13.8f} -> {c.after:>13.8f}  {c.evidence.source}")
    for symbol in sorted(set(records) - {c.symbol for c in changes}):
        print(f"   {symbol:7} unchanged - no M65 line")

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in (ledger, entries):
        backup = path.with_name(f"{path.name}.bak-fill-basis-{stamp}")
        shutil.copy2(path, backup)
        print(f"backup  : {backup}")

    tmp = ledger.with_name(f"{ledger.name}.tmp-{os.getpid()}")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(r.after.as_row() for r in repairs)
    findings = audit_closed_trades(tmp)
    if findings:
        tmp.unlink()
        print("AUDIT FAILED on the rewritten ledger - nothing replaced:")
        for line in findings:
            print(f"  {line}")
        return 1
    os.replace(tmp, ledger)
    entries.write_text(json.dumps(repaired_records, indent=2), encoding="utf-8")
    print(f"\nWRITTEN. {len(repairs)} row(s) rewritten, {len(changes)} record(s) corrected.")
    print("Deploy M175 BEFORE launching - an older build re-inflates the records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Check the script at least imports and refuses cleanly** (it reads the live dir, so PowerShell; the app is running during the session, so it must REFUSE):

Run: `py scripts/repair_fill_basis.py`
Expected: `REFUSING: QuantAdvisoryTerminal.exe is running. Close it first.` and exit code 1. (The real dry run is runbook step 3, after the close.)

- [ ] **Step 7: Commit**

```powershell
git add src/qat/domain/performance/fill_basis_repair.py scripts/repair_fill_basis.py tests/domain/performance/test_fill_basis_repair.py
git commit -m "M175: repair_fill_basis - rewrite entries and costs from logged evidence, self-checked" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Milestone M175 and the full checks

**Files:**
- Modify: `src/qat/version.py` — comment block before `MILESTONE`, and `MILESTONE = "M175"`

- [ ] **Step 1: Bump the milestone** — in `version.py`, insert directly above `MILESTONE = "M174"` and change that line:

```python
# M175. THE LEDGER'S COSTS WERE NEVER THE COMMISSION - THEY WERE THE FILL BASIS.
#
# Measured 11 September: IBKR's commission equals the model on 17 of 17 logged
# orders, to the cent. What was wrong was around it. `reconcile_entry_prices`
# (M65) wrote IBKR's commission-INCLUSIVE `avgCost` over the fill at every
# restart - undoing M70's correct price for JHX.AX and COH.AX - so entry
# commission was charged twice; the ledger charged 5 bp of modelled slippage on
# fills that already contained it (a replay did the same over SimulatedBroker's
# slipped prices); and the $6.60 floor was charged per absorbed piece. BHP.AX,
# stopped at the 11 September open, was the first row ever with a reference
# price, and its slippage read +0.0464 when the truth was -0.01.
#
# Now: costs are `CostModel.charge()`, one floor per order; the entry record
# stamps `price_source`, M65 never overwrites a fill and de-commissions avgCost
# when it corrects; and every IBKR commission report is checked against the
# model in `commission_checks.csv`. `scripts/repair_fill_basis.py` rewrites the
# existing rows and records from logged evidence, self-checked.
MILESTONE = "M175"
```

- [ ] **Step 2: Full suite** (never through `tail`)

Run: `py -m pytest -q`
Expected: every test passes (3,601 collected before this plan, plus the new ones); report the exact counts.

- [ ] **Step 3: The four checks, SEPARATELY**

Run each and read the OUTPUT, not only the exit code:
- `py -m ruff check src tests scripts` → `All checks passed!`
- `py -m black --check src tests scripts` → must NOT print "would be reformatted" (exit code alone is not trusted)
- `py -m mypy src` → `Success: no issues found`
- `py -m bandit -r src -q` → no issues

- [ ] **Step 4: Commit**

```powershell
git add src/qat/version.py
git commit -m "M175: milestone - the fill basis and the commission check" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Operator runbook — after the 16:00 close, never mid-session

Not a subagent task. Each ⛔ needs the operator.

Revised after the final whole-branch review (I1-I4). The order matters: the
repair runs AFTER the M175 deploy and BEFORE M175's first launch. It refuses
once the log records any `Build: M175`+ launch on the data, because that
build's M65 writes unstamped corrections the repair would read as fresh
inflation.

1. **Build and sign:** `invoke build`, then `invoke sign`. Confirm the dist hash MOVED from M174's `0DB8E1BA…`.
2. **Close the app normally.** Leave IB Gateway up. (`deploy.ps1` refuses while the app runs.)
3. **Deploy dry run:** `pwsh scripts\deploy.ps1`. ⛔ Operator's OK.
4. **Deploy:** `pwsh scripts\deploy.ps1 -Apply`. It does NOT launch the app. Do not launch it yet.
5. **Repair dry run:** `py scripts/repair_fill_basis.py`. Expect:
   - open records: **4 corrected from logged fills** (BOQ, ASX, SUN, ANZ, stamped `fill`) and **5 left for M65 at launch** (WOW, JHX, TWE, TAH, COH - no logged fill, so unchanged here), plus any record with no M65 line (for example a position bought by hand this afternoon, whose record already holds the execution price);
   - closed rows: only **TNE** flagged `[FRAGMENT: exit order 509334700 absorbed 3051 …]` - unless the operator's manual partial sells created exit orders larger than their rows (a manual partial sell is normally a whole order and pays its own $6.60 floor); only **SEK** and **BHP**, plus any manual-trade rows, formula-sourced (a manual-trade row may also read `NO M65 LINE - price kept`); BHP's slippage `-0.0100`;
   - `audit: clean`.
   ⛔ Operator reads the table. A `SELF-CHECK FAILED` or `REFUSING` means STOP: do not apply, do not launch the old build; M175 is deployed, so read the reason first.
6. **Apply:** `py scripts/repair_fill_basis.py --apply`. Then the ledger audit must be clean, and note the new ledger sha256.
7. **Operator launches.** Read back off the log: `Build: M175 (...)`. Then READ every `Corrected the recorded entry price` line rather than treating it as a failure. They are expected for WOW, JHX, TWE, TAH, COH and any manually traded symbol, and each should be roughly 8.8 bp below the prior record. A line naming BOQ, ASX, SUN or ANZ is NOT expected, because those records are stamped `fill`. A `Did not correct the recorded entry price` warning means a position below the floor crossover kept its record, which is intentional (I3). `session_check.ps1` clean.
8. **If the deploy fails after the repair was applied,** restore BOTH `closed_trades.csv.bak-fill-basis-*` and `open_position_entries.json.bak-fill-basis-*` over their originals before ANY launch. An older build's M65 re-inflates the repaired records.
9. **Watch for:** the first `COMMISSION VERIFIED` on any app-transmitted order (the positive control), and whether a broker-side stop ever produces one. `commission_checks.csv` holds one row per order, and a restart no longer adds duplicates (M4).
