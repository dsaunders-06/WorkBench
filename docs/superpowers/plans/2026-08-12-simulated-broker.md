# W2 Step 1 — SimulatedBroker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `BrokerAdapter` implementation that serves historical bars through a simulated clock and fills orders against them, so the production trading path can later be replayed over history without a second copy of the rules.

**Architecture:** One class, `SimulatedBroker`, holding per-symbol daily bars and an index into a shared session calendar. `advance()` moves one trading day and is the only thing that causes a fill. Every read method answers as of the current bar and never beyond it. Step 1 tests the broker in isolation — wiring it to the OMS is step 2.

**Tech Stack:** Python 3.12, pandas, pytest, pytest-asyncio.

## Global Constraints

- **The validation freeze applies.** A new module and its tests. Nothing in the live trading path is touched; no strategy parameter, cap, threshold or sizing rule changes.
- **Bars arrive normalised.** `SimulatedBroker` requires lowercase `open`/`high`/`low`/`close` columns on a `DatetimeIndex`. yfinance returns capitalised names and Alpaca returns lowercase, so **normalising is the caller's job** and belongs to step 2's data loading. Do not add column-guessing here — a fake that silently accepts either shape is a fake that silently accepts the wrong one.
- **The broker models the FILL PRICE only.** Slippage moves the fill; commission does not appear here. Commission reaches the record through the ledger and cost model, exactly as it does with a real broker where the charge arrives separately. Charging it twice would make every backtest quietly worse than reality.
- **Formats with `black`, not `ruff format`.** Run the four through the venv python.
- The venv python is `.\.venv\Scripts\python.exe`.

## Decisions this plan implements, and where they came from

| Decision | Why |
|---|---|
| **Stop wins any bar touching both levels** | A daily bar cannot say which came first. Assuming the stop makes every expectancy figure a floor rather than an estimate |
| **A gap through the stop fills at the OPEN** | A bar opening below the stop fills worse than the stop. The MNST lesson written into the simulator - a fake that filled politely at the trigger would hide the loss shape this account has already paid for |
| **A gap through the target fills at the TARGET, not the better open** | The same rule pointed the other way. Consistent with never flattering; revisit only with evidence |
| **Entries fill at the NEXT bar's open** | The signal is computed from a closed bar. Filling on that same bar's close is look-ahead in its most ordinary form |
| **Protective legs rest from the moment the entry fills, and are live on that same bar** | The entry filled at the open, so the rest of that bar follows it. A stop that could not fire on entry day would be optimistic about gap days |
| **`get_historical` never returns a bar after the simulated date** | The single most important guard in the file, and the one with its own test |

## File Structure

- **Create `src/qat/data/broker/simulated_broker.py`** — the adapter. Lives beside `mock_broker.py` because it is the same kind of thing and `capabilities.py` already imports adapters from this package.
- **Create `tests/data/broker/test_simulated_broker.py`** — behaviour, in isolation from the OMS.
- **Modify `src/qat/data/broker/capabilities.py`** — one line in `KNOWN_ADAPTERS()`.

---

### Task 1: Bars, the clock, and the look-ahead guard

**Files:**
- Create: `src/qat/data/broker/simulated_broker.py`
- Test: `tests/data/broker/test_simulated_broker.py`

**Interfaces:**
- Consumes: `Order`, `Position`, `BrokerFill`, `RestingStopOrder`, `AccountSummary`, `AccountBalances` from `qat.data.broker.adapter`; `Announcement` from `qat.domain.corporate_actions.announcements`; `CostModel` from `qat.domain.backtester.costs`.
- Produces: `SimulatedBroker(bars: dict[str, pd.DataFrame], cost_model: CostModel, starting_cash: float = 100_000.0)`, with `session_dates: list[pd.Timestamp]`, `current_date -> pd.Timestamp`, `advance() -> bool`, and the full `BrokerAdapter` surface.

- [ ] **Step 1: Write the failing test**

Create `tests/data/broker/test_simulated_broker.py`:

```python
"""SimulatedBroker in isolation - no OMS, no session loop (W2 step 1).

The guard that matters most here is the one with no equivalent in any real
adapter: a simulator can see the future, and must refuse to.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.data.broker.simulated_broker import SimulatedBroker
from qat.domain.backtester.costs import CostModel


def _bars(closes: list[float], symbol_high: float = 1.0) -> pd.DataFrame:
    """Daily bars with a controllable body. High/low straddle the close."""
    index = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + symbol_high for c in closes],
            "low": [c - symbol_high for c in closes],
            "close": closes,
        },
        index=index,
    )


def _broker(**kwargs) -> SimulatedBroker:
    bars = {"AAA": _bars([100.0, 101.0, 102.0, 103.0, 104.0])}
    return SimulatedBroker(bars=bars, cost_model=CostModel(commission_bps=0.0, slippage_bps=0.0), **kwargs)


def test_the_session_starts_on_the_first_bar():
    broker = _broker()
    assert broker.current_date == pd.Timestamp("2026-01-05")


def test_advance_moves_one_trading_day_and_reports_the_end():
    broker = _broker()
    moved = [broker.advance() for _ in range(6)]
    assert moved[:4] == [True, True, True, True]
    assert moved[4] is False, "there are five bars, so the fifth advance runs out"


@pytest.mark.asyncio
async def test_market_data_is_the_current_bar_not_the_last_one():
    broker = _broker()
    broker.advance()
    quote = await broker.get_market_data("AAA")
    assert quote["last"] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_get_historical_cannot_see_the_future():
    """The guard with no equivalent in a real adapter. A simulator holds the
    whole series in memory, so nothing but this stops the strategy being handed
    bars that had not happened yet - which would manufacture an edge from
    nothing and look entirely plausible doing it."""
    broker = _broker()
    broker.advance()  # now on bar index 1, close 101.0

    history = await broker.get_historical("AAA", 10)

    assert [row["close"] for row in history] == [100.0, 101.0]
    assert len(history) == 2, "only the bars that have happened"


@pytest.mark.asyncio
async def test_get_historical_returns_at_most_the_bars_asked_for():
    broker = _broker()
    for _ in range(4):
        broker.advance()
    history = await broker.get_historical("AAA", 2)
    assert [row["close"] for row in history] == [103.0, 104.0]


@pytest.mark.asyncio
async def test_an_unknown_symbol_answers_empty_rather_than_raising():
    """A universe member with no bars in the window must not end the run."""
    broker = _broker()
    assert await broker.get_historical("ZZZ", 5) == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_simulated_broker.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'qat.data.broker.simulated_broker'`.

- [ ] **Step 3: Write the module**

Create `src/qat/data/broker/simulated_broker.py`:

```python
"""A BrokerAdapter backed by historical bars and a simulated clock (W2).

The point of this class is that the production trading path can be replayed
over history WITHOUT a second copy of the rules. `MockBroker` invents prices
from a seeded RNG and fills instantly; this one serves real bars, fills on the
next bar's open, and executes protective orders against a bar's high and low.

The guard with no equivalent in any real adapter is `get_historical`: a
simulator holds the whole series in memory and must refuse to answer beyond the
simulated date. Nothing else prevents the strategy being handed bars that had
not happened yet, and the resulting backtest would look entirely plausible.

Bars arrive NORMALISED - lowercase open/high/low/close on a DatetimeIndex.
Accepting either capitalisation would be accepting the wrong one silently.

Slippage moves the fill price; commission does not appear here. Commission
reaches the record through the ledger and the cost model, exactly as it does
with a real broker, and charging it in both places would make every backtest
quietly worse than reality.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pandas as pd

from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    BrokerFill,
    Order,
    Position,
    RestingStopOrder,
)
from qat.domain.backtester.costs import CostModel
from qat.domain.corporate_actions.announcements import Announcement

_REQUIRED_COLUMNS = ("open", "high", "low", "close")


class SimulatedBroker:
    name = "simulated-broker"

    def __init__(
        self,
        bars: dict[str, pd.DataFrame],
        cost_model: CostModel,
        starting_cash: float = 100_000.0,
    ) -> None:
        for symbol, frame in bars.items():
            missing = [c for c in _REQUIRED_COLUMNS if c not in frame.columns]
            if missing:
                raise ValueError(
                    f"{symbol} bars are missing {missing}. SimulatedBroker requires normalised "
                    "lowercase open/high/low/close - normalising is the caller's job, because a "
                    "fake that accepts either shape accepts the wrong one silently."
                )
        self._bars = bars
        self.cost_model = cost_model
        self._cash = starting_cash

        every_date: set[pd.Timestamp] = set()
        for frame in bars.values():
            every_date.update(frame.index)
        self.session_dates: list[pd.Timestamp] = sorted(every_date)
        self._index = 0

        self._orders: dict[str, Order] = {}
        self._pending: list[Order] = []
        self._positions: dict[str, Position] = {}
        self._resting_stops: dict[str, float | None] = {}
        self._resting_targets: dict[str, float | None] = {}
        self._broker_fills: list[BrokerFill] = []
        self._announcements: list[Announcement] = []

    # --- the clock ----------------------------------------------------------

    @property
    def current_date(self) -> pd.Timestamp:
        return self.session_dates[self._index]

    def advance(self) -> bool:
        """Move to the next trading day. False when the series is exhausted.

        The ONLY thing that causes a fill. A test that expects an order to have
        filled without advancing is expecting a broker that trades on a bar
        that has not happened.
        """
        if self._index + 1 >= len(self.session_dates):
            return False
        self._index += 1
        return True

    def _bar(self, symbol: str) -> pd.Series | None:
        frame = self._bars.get(symbol)
        if frame is None:
            return None
        row = frame[frame.index <= self.current_date]
        if row.empty:
            return None
        return row.iloc[-1]

    def _now(self) -> datetime:
        return self.current_date.to_pydatetime().replace(tzinfo=UTC)

    # --- reads --------------------------------------------------------------

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        bar = self._bar(symbol)
        if bar is None:
            return {}
        price = float(bar["close"])
        return {"bid": price, "ask": price, "last": price}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        """Bars up to AND INCLUDING the simulated date, never beyond it."""
        frame = self._bars.get(symbol)
        if frame is None:
            return []
        visible = frame[frame.index <= self.current_date]
        if visible.empty:
            return []
        window = visible.iloc[-bars:] if bars > 0 else visible
        return [
            {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            for _, row in window.iterrows()
        ]

    async def positions(self) -> list[Position]:
        return list(self._positions.values())

    async def account(self) -> AccountSummary:
        market_value = 0.0
        for position in self._positions.values():
            bar = self._bar(position.symbol)
            if bar is not None:
                market_value += position.quantity * float(bar["close"])
        net_liq = self._cash + market_value
        return AccountSummary(net_liquidation=net_liq, cash=self._cash, buying_power=self._cash)

    async def balances(self) -> AccountBalances:
        summary = await self.account()
        return AccountBalances(
            equity=summary.net_liquidation,
            cash=summary.cash,
            buying_power=summary.buying_power,
            long_market_value=summary.net_liquidation - summary.cash,
            short_market_value=0.0,
            currency="USD",
            status="SIMULATED",
        )

    async def resting_stops(self) -> dict[str, float]:
        return {s: v for s, v in self._resting_stops.items() if v is not None}

    async def resting_stop_orders(self) -> dict[str, RestingStopOrder]:
        orders: dict[str, RestingStopOrder] = {}
        for symbol, stop in self._resting_stops.items():
            if stop is None:
                continue
            position = self._positions.get(symbol)
            orders[symbol] = RestingStopOrder(
                symbol=symbol,
                order_id=f"resting-stop-{symbol}",
                stop_price=stop,
                quantity=abs(position.quantity) if position else 0.0,
            )
        return orders

    async def recent_fills(
        self, since: datetime, symbols: list[str] | None = None
    ) -> list[BrokerFill]:
        wanted = set(symbols) if symbols is not None else None
        return [
            f
            for f in self._broker_fills
            if f.filled_at > since and (wanted is None or f.symbol in wanted)
        ]

    async def announcements(self, symbol: str, since: date, until: date) -> list[Announcement]:
        return [
            a for a in self._announcements if a.symbol == symbol and since <= a.ex_date <= until
        ]

    def queue_announcement(self, announcement: Announcement) -> None:
        """Test seam, as MockBroker's is. A corporate action cannot be derived
        from a price series."""
        self._announcements.append(announcement)

    # --- writes -------------------------------------------------------------

    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError("Task 2")

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        order = self._orders[order_id]
        for key, value in changes.items():
            setattr(order, key, value)
        if order.is_protective_stop and order.stop_price is not None:
            self._resting_stops[order.symbol] = order.stop_price
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        order.status = "cancelled"
        self._pending = [p for p in self._pending if p.order_id != order_id]
        if order.is_protective_stop:
            self._resting_stops.pop(order.symbol, None)
        return order


def new_simulated_order_id() -> str:
    return uuid.uuid4().hex
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_simulated_broker.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Lint, format and type-check**

```bash
.venv/Scripts/python.exe -m black src/qat/data/broker/simulated_broker.py tests/data/broker/test_simulated_broker.py
```

```bash
.venv/Scripts/python.exe -m ruff check . ; .venv/Scripts/python.exe -m mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/simulated_broker.py tests/data/broker/test_simulated_broker.py
```

```bash
git commit -m "W2: a broker that serves historical bars and cannot see past today"
```

---

### Task 2: Entries fill at the next bar's open

**Files:**
- Modify: `src/qat/data/broker/simulated_broker.py` (`place_order`, plus fill processing in `advance`)
- Test: `tests/data/broker/test_simulated_broker.py` (append)

**Interfaces:**
- Consumes: `SimulatedBroker` from Task 1.
- Produces: `place_order` returning an Order with status `"transmitted"`; the same Order reaching status `"filled"` with `filled_price` set after `advance()`.

- [ ] **Step 1: Write the failing test**

First add the import **at the top of the file**, beside the existing ones — not
beside the new code. `ruff` rejects a module-level import that is not at the top
(E402), and appending it inline is the obvious way to trip that:

```python
from qat.data.broker.adapter import Order
```

Then append to `tests/data/broker/test_simulated_broker.py`:

```python
def _buy(symbol: str = "AAA", quantity: float = 10.0, **kwargs) -> Order:
    return Order(symbol=symbol, side="buy", quantity=quantity, order_id="o-1", **kwargs)


@pytest.mark.asyncio
async def test_a_market_entry_does_not_fill_on_the_bar_that_signalled_it():
    """Filling on the signal bar's close is look-ahead in its most ordinary
    form: the signal was computed FROM that close."""
    broker = _broker()

    placed = await broker.place_order(_buy())

    assert placed.status == "transmitted"
    assert placed.filled_price is None
    assert await broker.positions() == []


@pytest.mark.asyncio
async def test_a_market_entry_fills_at_the_next_bars_open():
    broker = _broker()
    await broker.place_order(_buy())

    broker.advance()

    positions = await broker.positions()
    assert [p.symbol for p in positions] == ["AAA"]
    assert positions[0].quantity == pytest.approx(10.0)
    assert positions[0].avg_price == pytest.approx(101.0), "bar index 1's open"


@pytest.mark.asyncio
async def test_slippage_moves_a_buy_fill_against_the_buyer():
    bars = {"AAA": _bars([100.0, 101.0, 102.0])}
    broker = SimulatedBroker(
        bars=bars, cost_model=CostModel(commission_bps=0.0, slippage_bps=10.0)
    )
    await broker.place_order(_buy())

    broker.advance()

    positions = await broker.positions()
    # 101.0 * (1 + 10bps) = 101.101
    assert positions[0].avg_price == pytest.approx(101.101)


@pytest.mark.asyncio
async def test_a_bracket_entry_leaves_its_protective_legs_resting_once_filled():
    broker = _broker()
    await broker.place_order(_buy(stop_price=95.0, take_profit_price=115.0))

    assert await broker.resting_stops() == {}, "nothing rests before the shares exist"

    broker.advance()

    assert await broker.resting_stops() == {"AAA": 95.0}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_simulated_broker.py -v -k "entry or slippage or bracket"
```

Expected: FAIL with `NotImplementedError: Task 2`.

- [ ] **Step 3: Implement `place_order` and entry filling**

In `src/qat/data/broker/simulated_broker.py`, replace:

```python
    async def place_order(self, order: Order) -> Order:
        raise NotImplementedError("Task 2")
```

with:

```python
    async def place_order(self, order: Order) -> Order:
        """Queued, never filled here. A market order placed against a closed
        bar reaches the market at the next open, and the app's own sizing was
        computed from that closed bar - so filling now would hand the strategy
        a price it could not have traded at."""
        self._orders[order.order_id] = order
        if order.is_protective_stop:
            order.status = "transmitted"
            self._resting_stops[order.symbol] = order.stop_price
            if order.take_profit_price is not None:
                self._resting_targets[order.symbol] = order.take_profit_price
            return order
        order.status = "transmitted"
        self._pending.append(order)
        return order

    def _fill_pending_entries(self) -> None:
        still_pending: list[Order] = []
        for order in self._pending:
            bar = self._bar(order.symbol)
            if bar is None or bar.name != self.current_date:
                # No bar for this symbol today - the order waits rather than
                # filling at a stale price from an earlier session.
                still_pending.append(order)
                continue
            fill_price = self._slipped(float(bar["open"]), order.side)
            order.status = "filled"
            order.filled_price = fill_price
            self._apply_fill(order, fill_price)
            if order.is_bracket and order.side == "buy":
                self._resting_stops[order.symbol] = order.stop_price
                self._resting_targets[order.symbol] = order.take_profit_price
            elif order.side == "sell":
                self._resting_stops.pop(order.symbol, None)
                self._resting_targets.pop(order.symbol, None)
        self._pending = still_pending

    def _slipped(self, price: float, side: str) -> float:
        """Slippage always moves the fill AGAINST the order."""
        drift = price * (self.cost_model.slippage_bps / 10_000.0)
        return price + drift if side == "buy" else price - drift

    def _apply_fill(self, order: Order, fill_price: float) -> None:
        signed_qty = order.quantity if order.side == "buy" else -order.quantity
        self._cash -= signed_qty * fill_price
        existing = self._positions.get(order.symbol)
        if existing is None:
            self._positions[order.symbol] = Position(
                symbol=order.symbol, quantity=signed_qty, avg_price=fill_price
            )
            return
        new_qty = existing.quantity + signed_qty
        if abs(new_qty) < 1e-9:
            self._positions.pop(order.symbol, None)
            return
        self._positions[order.symbol] = Position(
            symbol=order.symbol, quantity=new_qty, avg_price=fill_price
        )
```

- [ ] **Step 4: Call it from `advance`**

Replace the body of `advance`:

```python
    def advance(self) -> bool:
        if self._index + 1 >= len(self.session_dates):
            return False
        self._index += 1
        self._fill_pending_entries()
        return True
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_simulated_broker.py -v
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/simulated_broker.py tests/data/broker/test_simulated_broker.py
```

```bash
git commit -m "W2: entries fill at the next bar's open, with slippage against them"
```

---

### Task 3: Protective fills, and the pessimistic rule

**Files:**
- Modify: `src/qat/data/broker/simulated_broker.py` (add `_fill_protective_orders`, call from `advance`)
- Test: `tests/data/broker/test_simulated_broker.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: protective executions appearing in `recent_fills` and closing the position.

**This is the task that decides what every expectancy figure means.** Four rules, each with a test.

- [ ] **Step 1: Write the failing tests**

First add this **at the top of the file** with the other imports, for the same
E402 reason as Task 2:

```python
from datetime import UTC, datetime
```

Then append to `tests/data/broker/test_simulated_broker.py`:

```python
def _ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Explicit open/high/low/close per bar, for the ambiguous cases."""
    index = pd.date_range("2026-01-05", periods=len(rows), freq="B")
    return pd.DataFrame(
        {
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
        },
        index=index,
    )


async def _entered(bars: pd.DataFrame, stop: float, target: float) -> SimulatedBroker:
    broker = SimulatedBroker(
        bars={"AAA": bars}, cost_model=CostModel(commission_bps=0.0, slippage_bps=0.0)
    )
    await broker.place_order(_buy(stop_price=stop, take_profit_price=target))
    broker.advance()  # fills at bar 1's open, legs go resting
    return broker


@pytest.mark.asyncio
async def test_a_stop_fills_when_the_low_touches_it():
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 94, 95)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    assert await broker.positions() == []
    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [(f.symbol, f.side, f.price) for f in fills] == [("AAA", "sell", 95.0)]


@pytest.mark.asyncio
async def test_a_bar_that_touches_both_levels_is_recorded_as_the_STOP():
    """The decision that makes every expectancy figure a floor. The bar cannot
    say which came first, so the unfavourable one is assumed."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (100, 120, 94, 100)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [95.0], "the target was touched too, and loses"


@pytest.mark.asyncio
async def test_a_gap_through_the_stop_fills_at_the_OPEN_not_the_stop():
    """The MNST lesson in the simulator. A bar opening below the stop does not
    fill politely at the trigger."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (80, 82, 78, 80)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [80.0], "the open, which is worse than the stop"


@pytest.mark.asyncio
async def test_a_gap_through_the_target_fills_at_the_TARGET_not_the_better_open():
    """The same rule pointed the other way: never flatter."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 99, 100), (130, 132, 128, 130)])
    broker = await _entered(bars, stop=95.0, target=115.0)

    broker.advance()

    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [115.0], "the target, not the 130 open"


@pytest.mark.asyncio
async def test_a_stop_can_fire_on_the_bar_the_entry_filled():
    """The entry filled at the open, so the rest of that bar follows it. A stop
    that could not fire on entry day would be optimistic about gap days."""
    bars = _ohlc([(100, 101, 99, 100), (100, 101, 90, 92)])
    broker = SimulatedBroker(
        bars={"AAA": bars}, cost_model=CostModel(commission_bps=0.0, slippage_bps=0.0)
    )
    await broker.place_order(_buy(stop_price=95.0, take_profit_price=115.0))

    broker.advance()

    assert await broker.positions() == []
    fills = await broker.recent_fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert [f.price for f in fills] == [95.0]
```

Add to the imports at the top of the test file:

```python
from datetime import UTC, datetime
```

- [ ] **Step 2: Run them to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_simulated_broker.py -v -k "stop or gap or both"
```

Expected: FAIL — positions are still held, and `recent_fills` is empty.

- [ ] **Step 3: Implement protective filling**

Add to `src/qat/data/broker/simulated_broker.py`:

```python
    def _fill_protective_orders(self) -> None:
        """Resting legs against today's bar.

        The stop is evaluated FIRST and wins any bar that touches both levels.
        A daily bar cannot say which came first, and assuming the unfavourable
        one makes every expectancy figure a floor rather than an estimate.
        """
        for symbol in list(self._positions):
            position = self._positions.get(symbol)
            if position is None or position.quantity <= 0:
                continue
            bar = self._bar(symbol)
            if bar is None or bar.name != self.current_date:
                continue
            stop = self._resting_stops.get(symbol)
            target = self._resting_targets.get(symbol)
            low, high, open_ = float(bar["low"]), float(bar["high"]), float(bar["open"])

            if stop is not None and low <= stop:
                # A bar that OPENS through the stop fills at the open, which is
                # worse. Filling at the trigger would hide the loss shape a
                # split and a gap both produce.
                self._execute_protective(symbol, open_ if open_ <= stop else stop)
                continue
            if target is not None and high >= target:
                # The target, never the better gapped-up open - the same
                # never-flatter rule pointed the other way.
                self._execute_protective(symbol, target)

    def _execute_protective(self, symbol: str, price: float) -> None:
        position = self._positions.get(symbol)
        if position is None or position.quantity <= 0:
            return
        quantity = position.quantity
        self._broker_fills.append(
            BrokerFill(
                order_id=f"sim-{uuid.uuid4().hex[:8]}",
                symbol=symbol,
                side="sell",
                quantity=quantity,
                price=price,
                filled_at=self._now(),
            )
        )
        self._positions.pop(symbol, None)
        self._resting_stops.pop(symbol, None)
        self._resting_targets.pop(symbol, None)
        self._cash += quantity * price
```

- [ ] **Step 4: Call it from `advance`, after entries**

Replace the body of `advance`:

```python
    def advance(self) -> bool:
        if self._index + 1 >= len(self.session_dates):
            return False
        self._index += 1
        # Entries first: an order filling at today's open exists for the rest of
        # today, so its protective legs are live on this bar.
        self._fill_pending_entries()
        self._fill_protective_orders()
        return True
```

- [ ] **Step 5: Run the whole file**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_simulated_broker.py -v
```

Expected: 15 passed.

- [ ] **Step 6: Commit**

```bash
git add src/qat/data/broker/simulated_broker.py tests/data/broker/test_simulated_broker.py
```

```bash
git commit -m "W2: protective fills, with the stop winning every ambiguous bar"
```

---

### Task 4: Register it as an adapter

**Files:**
- Modify: `src/qat/data/broker/capabilities.py` (`KNOWN_ADAPTERS`)

**Interfaces:**
- Consumes: `SimulatedBroker`.
- Produces: nothing new. The existing `test_no_known_adapter_is_missing_a_core_capability` picks it up by parametrisation.

**Why this is a task and not a footnote.** W1.0 built a test that fails when an adapter lacks a capability the live path depends on. Registering `SimulatedBroker` means that test covers it **the day it exists** — so a harness missing, say, `resting_stops` fails a test rather than quietly measuring a book whose protection was never verified.

- [ ] **Step 1: Add it to the registry**

In `src/qat/data/broker/capabilities.py`, replace:

```python
    from qat.data.broker.alpaca_adapter import AlpacaAdapter
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.mock_broker import MockBroker

    return {"alpaca": AlpacaAdapter, "ibkr": IBAdapter, "mock": MockBroker}
```

with:

```python
    from qat.data.broker.alpaca_adapter import AlpacaAdapter
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.mock_broker import MockBroker
    from qat.data.broker.simulated_broker import SimulatedBroker

    # `simulated` is not selectable as `broker=` in config - it needs bars and a
    # clock, which no resolver can supply. It is registered because the audit is
    # the point: a harness missing a capability the live path depends on must
    # fail a test rather than quietly measure a book it never verified.
    return {
        "alpaca": AlpacaAdapter,
        "ibkr": IBAdapter,
        "mock": MockBroker,
        "simulated": SimulatedBroker,
    }
```

- [ ] **Step 2: Run the conformance tests**

```bash
.venv/Scripts/python.exe -m pytest tests/data/broker/test_capabilities.py -v
```

Expected: PASS, now with a `[simulated]` case. **If `test_no_known_adapter_is_missing_a_core_capability[simulated]` fails, do not weaken the test** — the named method is one the live path depends on and the harness must implement it.

- [ ] **Step 3: Confirm the matrix reports it**

```bash
.venv/Scripts/python.exe scripts/broker_capabilities.py
```

Expected: a `simulated` column, `yes` against all twelve methods.

- [ ] **Step 4: Commit**

```bash
git add src/qat/data/broker/capabilities.py
```

```bash
git commit -m "W2: register SimulatedBroker so the capability audit covers it"
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

- [ ] **CI green on the pushed commit**

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" run list --limit 3
```

## Deliberately not in this plan

- **Wiring it to the OMS.** That is step 2 — the clock and the session loop. This plan tests the broker in isolation on purpose; a fake proven only through the thing it is meant to test proves neither.
- **Loading real bars.** Step 2 owns data loading and column normalisation. Every test here builds its bars explicitly, which is why the ambiguous cases can be stated exactly.
- **Partial fills.** Real, and deferred: no partial-fill behaviour is modelled, so the harness fills whole orders. Record it as a stated limitation when the manifest is built in step 6.
- **Short selling.** The live OMS submits buys and sells-to-close only, so the simulator does not model shorts either.
