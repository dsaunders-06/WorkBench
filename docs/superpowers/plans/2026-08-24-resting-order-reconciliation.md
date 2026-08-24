# Resting-Order Reconciliation (item 23) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect resting orders at the broker that the book cannot justify — the sixteen orphaned GTC bracket legs of 24 August — quarantine the symbol, and optionally cancel them where the book is flat.

**Architecture:** A new unfiltered `open_orders()` on the broker adapter feeds a pure, I/O-free domain function that nets OCA groups per side and compares against the position. Divergences are logged leg-by-leg and quarantined in a store that deliberately has no `explains()` method. Cancelling is off by default and flat-symbols-only.

**Tech Stack:** Python 3.12, ib_async 2.1.0, pytest, pydantic-settings, PyQt6 (untouched here), invoke.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-24-resting-order-reconciliation-design.md`. Read it before Task 1.
- **PowerShell for anything that touches `%LOCALAPPDATA%\QuantAdvisoryTerminal`**, including Python that only reads it and anything that constructs `Settings()`. The Bash sandbox serves a frozen snapshot and does not error. Tests run under pytest with `tmp_path`, so they are safe in either shell; **`invoke test` and any live probe must go through PowerShell.**
- **Milestone for this work is `M141`.** `src/qat/version.py:524` currently reads `MILESTONE = "M140"`.
- **The status widening is OUT OF SCOPE.** `_IB_WORKING_STATUSES` (`ib_translate.py:380`) and `from_ib_resting_stop` must be left byte-for-byte unchanged. Operator decision, recorded in the spec. A task that modifies either has failed.
- **No sizing input may move.** `_position_stops` must contain exactly what it contains today after this change.
- **The kill switch is not touched.** It is currently tripped and stays tripped.
- **Batch the commits, push once at the end.** The repo is private and CI runs on windows-latest at a 2x multiplier.
- Line length and formatting are enforced by `ruff` and `black`; `mypy` and `bandit` must stay clean.
- Symbols crossing an IBKR boundary translate via `from_ibkr` (M104). No exceptions.

---

### Task 1: `RestingOrder`, and a translate that discards nothing

**Files:**
- Modify: `src/qat/data/broker/adapter.py` (add dataclass after `RestingStopOrder`, ~line 133; add protocol method in `BrokerAdapter`, ~line 311)
- Modify: `src/qat/data/broker/ib_translate.py` (add `from_ib_open_order` after `from_ib_resting_stop`, ~line 406)
- Test: `tests/data/broker/test_ib_open_orders.py` (create)

**Interfaces:**
- Produces: `RestingOrder` frozen dataclass; `from_ib_open_order(trade, market="US") -> RestingOrder`; `BrokerAdapter.open_orders() -> list[RestingOrder]`.

- [ ] **Step 1: Write the failing test**

```python
"""`open_orders` must discard NOTHING (M141, item 23).

`from_ib_resting_stop` returns None for any type outside `_IB_STOP_TYPES`, so a
bracket's take-profit LIMIT leg is dropped before anything can count it. Eight of
the sixteen orphaned legs on 24 August were of exactly that kind.

This boundary filters on nothing at all - not type, not status. Each consumer
applies its own rule, which is what keeps the orphan scan's WIDE status set from
leaking into `from_ib_resting_stop`'s narrow one.
"""

from __future__ import annotations

from types import SimpleNamespace

from qat.data.broker.ib_translate import from_ib_open_order


def _trade(**kw):
    order = SimpleNamespace(
        permId=kw.get("perm_id", 111),
        orderId=kw.get("order_id", 1),
        action=kw.get("action", "SELL"),
        orderType=kw.get("order_type", "STP"),
        totalQuantity=kw.get("total_quantity", 100.0),
        ocaGroup=kw.get("oca_group", ""),
        parentPermId=kw.get("parent_perm_id", 0),
        clientId=kw.get("client_id", 1),
        auxPrice=kw.get("aux_price", 30.69),
        lmtPrice=kw.get("lmt_price", 0.0),
    )
    status = SimpleNamespace(
        status=kw.get("status", "PreSubmitted"),
        remaining=kw.get("remaining", 100.0),
        whyHeld=kw.get("why_held", ""),
    )
    contract = SimpleNamespace(symbol=kw.get("symbol", "TNE"))
    return SimpleNamespace(order=order, orderStatus=status, contract=contract)


def test_a_take_profit_limit_leg_is_kept():
    """The leg `from_ib_resting_stop` throws away."""
    resting = from_ib_open_order(
        _trade(order_type="LMT", aux_price=0.0, lmt_price=36.86, perm_id=222), market="ASX"
    )
    assert resting is not None
    assert resting.order_type == "LMT"
    assert resting.limit_price == 36.86
    assert resting.stop_price is None


def test_a_done_order_is_still_returned():
    """No status filter here. Consumers decide what 'working' means."""
    resting = from_ib_open_order(_trade(status="Cancelled"), market="ASX")
    assert resting is not None
    assert resting.status == "Cancelled"


def test_quantity_is_remaining_not_total():
    """A half-filled stop carries half the risk."""
    resting = from_ib_open_order(_trade(total_quantity=100.0, remaining=40.0), market="ASX")
    assert resting.quantity == 40.0


def test_the_symbol_is_translated():
    """M104 - every IBKR boundary translates."""
    resting = from_ib_open_order(_trade(symbol="TNE"), market="ASX")
    assert resting.symbol == "TNE.AX"


def test_group_keys_are_carried_raw():
    resting = from_ib_open_order(
        _trade(oca_group="OCA-7", parent_perm_id=999, client_id=3), market="ASX"
    )
    assert resting.oca_group == "OCA-7"
    assert resting.parent_perm_id == 999
    assert resting.owner_client_id == 3


def test_absent_group_markers_become_none():
    """IBKR sends "" and 0, not None, and `solo:` fallback keys on falsiness."""
    resting = from_ib_open_order(_trade(oca_group="", parent_perm_id=0), market="ASX")
    assert resting.oca_group is None
    assert resting.parent_perm_id is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_open_orders.py -v`
Expected: FAIL — `ImportError: cannot import name 'from_ib_open_order'`

- [ ] **Step 3: Add the dataclass**

In `src/qat/data/broker/adapter.py`, immediately after the `RestingStopOrder` class:

```python
@dataclass(frozen=True, slots=True)
class RestingOrder:
    """One order open at the broker, translated and NOT judged (M141, item 23).

    Distinct from `RestingStopOrder`, which answers "is this position
    protected". This answers "what is working at the broker", which is a
    different question and the one nothing was asking: on 24 August sixteen
    orphaned GTC bracket legs rested against a FLAT TNE.AX and no code path
    could see them.

    **Nothing is filtered on the way in - not type, not status.** A bracket's
    take-profit LIMIT leg is dropped by `from_ib_resting_stop` and is exactly
    half of what went orphaned. Filtering is each consumer's own business, and
    keeping it out of here is what stops the orphan scan's WIDE working-status
    set leaking into `from_ib_resting_stop`'s deliberately narrow one.
    """

    symbol: str
    order_id: str
    side: str
    order_type: str
    # `orderStatus.remaining`, not `totalQuantity`: a half-filled stop carries
    # half the risk, and the excess calculation is a quantity comparison.
    quantity: float
    status: str
    oca_group: str | None = None
    # The OCA fallback. A bracket's legs share a parent even where IBKR sends
    # no ocaGroup, and taking the MAX within a group rather than the sum is
    # what stops a correct bracket reading as double the risk it is.
    parent_perm_id: int | None = None
    owner_client_id: int | None = None
    why_held: str | None = None
    stop_price: float | None = None
    limit_price: float | None = None
```

- [ ] **Step 4: Add the protocol method**

In `BrokerAdapter`, immediately after `resting_stop_orders`:

```python
    async def open_orders(self) -> list[RestingOrder]: ...
```

- [ ] **Step 5: Add the translate**

In `src/qat/data/broker/ib_translate.py`, after `from_ib_resting_stop`. Import `RestingOrder` alongside the existing adapter imports.

```python
def from_ib_open_order(trade: Trade, market: str = "US") -> RestingOrder:
    """One open IBKR order, translated and unjudged (M141, item 23).

    Returns a record for EVERY order, always. Compare `from_ib_resting_stop`,
    which returns None three separate ways - wrong type, non-working status, no
    auxPrice - each of which is correct for the question IT answers and wrong
    for this one.

    `ocaGroup` and `parentPermId` arrive as "" and 0 rather than absent, and the
    grouping in `unjustified_resting_risk` keys on falsiness, so both are
    normalised to None here rather than at each reader.
    """
    order = trade.order
    aux = float(order.auxPrice) if order.auxPrice else None
    limit = float(order.lmtPrice) if getattr(order, "lmtPrice", 0.0) else None
    return RestingOrder(
        symbol=from_ibkr(trade.contract.symbol, market),
        order_id=str(order.permId or order.orderId),
        side=str(order.action).lower(),
        order_type=str(order.orderType),
        quantity=float(trade.orderStatus.remaining),
        status=str(trade.orderStatus.status),
        oca_group=str(order.ocaGroup) or None,
        parent_perm_id=int(order.parentPermId) or None,
        owner_client_id=int(order.clientId),
        why_held=str(trade.orderStatus.whyHeld) or None,
        stop_price=aux,
        limit_price=limit,
    )
```

- [ ] **Step 6: Run and confirm pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_open_orders.py -v`
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add src/qat/data/broker/adapter.py src/qat/data/broker/ib_translate.py tests/data/broker/test_ib_open_orders.py
git commit -m "RestingOrder: a broker order translated and not judged (M141)"
```

---

### Task 2: One scan, and proof the narrow set did not widen

**Files:**
- Modify: `src/qat/data/broker/ib_adapter.py:389-436` (`resting_stop_orders`, add `open_orders` before it)
- Test: `tests/data/broker/test_ib_open_orders.py` (extend)

**Interfaces:**
- Consumes: `RestingOrder`, `from_ib_open_order` from Task 1.
- Produces: `IBAdapter.open_orders() -> list[RestingOrder]`; `resting_stop_orders()` unchanged in behaviour.

**The trap this task exists to avoid:** `resting_stop_orders` is being rewritten to derive from `open_orders`. If `open_orders` status-filters, `from_ib_resting_stop` silently inherits the wide set and the deferred sizing change ships unannounced. `open_orders` filters nothing; the equivalence test below is the proof.

- [ ] **Step 1: Write the failing test**

Append to `tests/data/broker/test_ib_open_orders.py`:

```python
import pytest

from qat.data.broker.ib_adapter import IBAdapter


class _FakeIB:
    def __init__(self, trades):
        self._trades = trades

    async def reqAllOpenOrdersAsync(self):  # noqa: N802 - mirrors ib_async
        return self._trades


def _adapter(trades, monkeypatch):
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = _FakeIB(trades)
    adapter.settings = SimpleNamespace(market="ASX")
    return adapter


@pytest.mark.asyncio
async def test_open_orders_returns_every_order(monkeypatch):
    trades = [
        _trade(perm_id=1, order_type="STP", status="PreSubmitted"),
        _trade(perm_id=2, order_type="LMT", status="Submitted", aux_price=0.0, lmt_price=36.86),
        _trade(perm_id=3, order_type="STP", status="Cancelled"),
        _trade(perm_id=4, order_type="STP", status="ApiPending"),
    ]
    got = await _adapter(trades, monkeypatch).open_orders()
    assert [o.order_id for o in got] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
async def test_resting_stop_orders_still_applies_the_NARROW_set(monkeypatch):
    """The whole point of Task 2.

    `ApiPending` is a working state ib_async recognises and this app's
    `_IB_WORKING_STATUSES` does not. Deriving `resting_stop_orders` from
    `open_orders` must NOT widen it - that would move `_position_stops`, which
    is a sizing input, inside a change that claims to move none.
    """
    trades = [
        _trade(symbol="TNE", perm_id=1, order_type="STP", status="ApiPending", aux_price=30.69),
        _trade(symbol="DXS", perm_id=2, order_type="STP", status="PreSubmitted", aux_price=7.10),
    ]
    got = await _adapter(trades, monkeypatch).resting_stop_orders()
    assert set(got) == {"DXS.AX"}, "ApiPending must stay invisible to the protection check"


@pytest.mark.asyncio
async def test_a_take_profit_leg_is_not_a_resting_stop(monkeypatch):
    trades = [_trade(perm_id=2, order_type="LMT", aux_price=0.0, lmt_price=36.86)]
    assert await _adapter(trades, monkeypatch).resting_stop_orders() == {}


@pytest.mark.asyncio
async def test_no_capability_means_no_orders(monkeypatch):
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = SimpleNamespace()
    adapter.settings = SimpleNamespace(market="ASX")
    assert await adapter.open_orders() == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_open_orders.py -v`
Expected: FAIL — `AttributeError: 'IBAdapter' object has no attribute 'open_orders'`

- [ ] **Step 3: Add `open_orders` and rewrite `resting_stop_orders`**

In `src/qat/data/broker/ib_adapter.py`, insert `open_orders` immediately before `resting_stop_orders`:

```python
    async def open_orders(self) -> list[RestingOrder]:
        """Every order working at the broker, unfiltered (M141, item 23).

        **`reqAllOpenOrders`, not `openTrades`.** `openTrades()` is CLIENT
        SCOPED: on 24 August it reported no protective stops while sixteen were
        resting, because they belonged to clientId 1 and the probe was 99. The
        sync form is a `util.run` wrapper that raises "event loop is already
        running" inside the app (the M102 trap, hit three times in one
        afternoon), so this uses the async form and nothing else.

        Returns [] when the client cannot answer, which callers must read as
        "we could not look" and NOT as "nothing is resting".
        """
        request = getattr(self.ib_client, "reqAllOpenOrdersAsync", None)
        if not callable(request):
            return []
        return [from_ib_open_order(trade, self.settings.market) for trade in await request()]
```

Then replace the body of `resting_stop_orders` — **docstring unchanged** — so that the loop reads from the single scan. The existing signature, warning and `tighter_stop` logic stay exactly as they are; only the source of `trade` changes:

```python
        resting: dict[str, RestingStopOrder] = {}
        request = getattr(self.ib_client, "reqAllOpenOrdersAsync", None)
        if not callable(request):
            return {}
        for trade in await request():
            stop = from_ib_resting_stop(trade, self.settings.market)
            ...
```

> **Note for the implementer:** `from_ib_resting_stop` takes the raw ib_async `Trade`, not a `RestingOrder`, so `resting_stop_orders` keeps calling `reqAllOpenOrdersAsync` directly rather than going through `open_orders()`. That is the correct outcome — it is one call per method, both async, both all-clients, and **`from_ib_resting_stop` keeps its own narrow status filter untouched**, which is the constraint. Do not "improve" this by routing it through `open_orders()`: `RestingOrder` deliberately drops the raw `Trade`, and reconstructing the narrow filter on top of the wide record is how the widening leaks in.

- [ ] **Step 4: Run and confirm pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_ib_open_orders.py tests/data/broker/test_ib_resting_stops.py -v`
Expected: all pass. **`test_ib_resting_stops.py` must pass entirely unmodified.** If it does not, the narrow set has been widened — revert and re-read the constraint.

- [ ] **Step 5: Commit**

```bash
git add src/qat/data/broker/ib_adapter.py tests/data/broker/test_ib_open_orders.py
git commit -m "IBAdapter.open_orders, and proof the narrow status set did not widen (M141)"
```

---

### Task 3: The rule, as a pure function

**Files:**
- Create: `src/qat/domain/oms/resting_orders.py`
- Test: `tests/domain/oms/test_resting_orders.py` (create)

**Interfaces:**
- Consumes: `RestingOrder` (Task 1), `Position` from `qat.data.broker.adapter`.
- Produces: `WORKING_STATUSES: frozenset[str]`; `SymbolOrderDivergence`; `unjustified_resting_risk(orders: Sequence[RestingOrder], positions: Sequence[Position]) -> list[SymbolOrderDivergence]`.

- [ ] **Step 1: Write the failing test**

```python
"""What rests at the broker that the book cannot justify (M141, item 23).

The three states that matter are all real and all dated. The FIRST of them is
the one that decides whether this rail can be trusted at all: TNE.AX holds 3,051
bracketed at 30.69 and 36.86, which is 6,102 shares of resting SELL against a
3,051 long. A rule that sums instead of netting OCA groups flags the only
position this system has ever placed correctly, on its first run.
"""

from __future__ import annotations

from qat.data.broker.adapter import Position, RestingOrder
from qat.domain.oms.resting_orders import WORKING_STATUSES, unjustified_resting_risk


def _order(order_id, symbol="TNE.AX", side="sell", qty=3051.0, oca=None, parent=None, **kw):
    return RestingOrder(
        symbol=symbol,
        order_id=str(order_id),
        side=side,
        order_type=kw.get("order_type", "STP"),
        quantity=qty,
        status=kw.get("status", "PreSubmitted"),
        oca_group=oca,
        parent_perm_id=parent,
        owner_client_id=kw.get("owner_client_id", 1),
        stop_price=kw.get("stop_price"),
        limit_price=kw.get("limit_price"),
    )


def _pos(symbol, qty):
    return Position(symbol=symbol, quantity=qty, avg_price=32.9783)


def test_the_live_TNE_bracket_does_NOT_flag():
    """THE regression test. 3,051 held, stop 3,051 + target 3,051, one OCA group."""
    orders = [
        _order(1, oca="OCA-1", stop_price=30.69),
        _order(2, oca="OCA-1", order_type="LMT", limit_price=36.86),
    ]
    assert unjustified_resting_risk(orders, [_pos("TNE.AX", 3051.0)]) == []


def test_24_august_mid_incident_flags_the_excess():
    """Four duplicate brackets, two legs each, 3,076 per leg, against 3,076 held.

    `(n - 1) // 2` is what makes it FOUR groups of two rather than five uneven
    ones - get this wrong and the expected total is 15,380, not 12,304.
    """
    orders = [_order(n, oca=f"OCA-{(n - 1) // 2}", qty=3076.0) for n in range(1, 9)]
    found = unjustified_resting_risk(orders, [_pos("TNE.AX", 3076.0)])
    assert len(found) == 1
    assert found[0].resting == 12304.0
    assert found[0].justified == 3076.0
    assert found[0].excess == 9228.0
    assert found[0].flat is False


def test_24_august_after_the_unwind_flags_every_leg():
    """Flat, eight legs resting. Nothing justifies any of it."""
    orders = [_order(n, oca=f"OCA-{(n - 1) // 2}", qty=3076.0) for n in range(1, 9)]
    found = unjustified_resting_risk(orders, [_pos("TNE.AX", 0.0)])
    assert len(found) == 1
    assert found[0].flat is True
    assert found[0].justified == 0.0
    assert found[0].excess == found[0].resting == 12304.0
    assert len(found[0].legs) == 8


def test_a_symbol_absent_from_positions_is_flat():
    found = unjustified_resting_risk([_order(1)], [])
    assert found[0].flat is True


def test_an_ungrouped_solo_stop_is_its_own_group():
    """Two standalone stops SUM; they are not one-cancels-all."""
    orders = [_order(1, qty=1000.0), _order(2, qty=1000.0)]
    found = unjustified_resting_risk(orders, [_pos("TNE.AX", 1000.0)])
    assert found[0].resting == 2000.0
    assert found[0].excess == 1000.0


def test_parent_perm_id_groups_when_oca_is_absent():
    orders = [_order(1, parent=77, qty=500.0), _order(2, parent=77, qty=500.0)]
    assert unjustified_resting_risk(orders, [_pos("TNE.AX", 500.0)]) == []


def test_a_short_protected_by_buy_stops_is_justified():
    orders = [_order(1, side="buy", qty=800.0, oca="OCA-9")]
    assert unjustified_resting_risk(orders, [_pos("TNE.AX", -800.0)]) == []


def test_a_buy_stop_against_a_LONG_is_unjustified():
    """Sides net independently. A long justifies SELLs, not BUYs."""
    orders = [_order(1, side="buy", qty=800.0)]
    found = unjustified_resting_risk(orders, [_pos("TNE.AX", 800.0)])
    assert found[0].side == "buy"
    assert found[0].excess == 800.0


def test_partial_fills_use_remaining():
    orders = [_order(1, qty=40.0, oca="OCA-1"), _order(2, qty=40.0, oca="OCA-1")]
    assert unjustified_resting_risk(orders, [_pos("TNE.AX", 40.0)]) == []


def test_done_statuses_are_ignored():
    orders = [_order(1, status="Cancelled"), _order(2, status="Filled")]
    assert unjustified_resting_risk(orders, [_pos("TNE.AX", 0.0)]) == []


def test_api_pending_counts():
    """The state this app's OTHER status set misses. Missing it under-counts risk."""
    found = unjustified_resting_risk([_order(1, status="ApiPending")], [_pos("TNE.AX", 0.0)])
    assert found[0].excess == 3051.0


def test_zero_quantity_orders_are_ignored():
    assert unjustified_resting_risk([_order(1, qty=0.0)], [_pos("TNE.AX", 0.0)]) == []


def test_results_are_sorted_deterministically():
    orders = [_order(1, symbol="ZZZ.AX"), _order(2, symbol="AAA.AX")]
    found = unjustified_resting_risk(orders, [])
    assert [d.symbol for d in found] == ["AAA.AX", "ZZZ.AX"]


def test_working_statuses_excludes_validation_error():
    assert "ValidationError" not in WORKING_STATUSES
    assert {"Submitted", "PreSubmitted", "PendingSubmit", "ApiPending", "ApiUpdate"} <= (
        WORKING_STATUSES
    )
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_orders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qat.domain.oms.resting_orders'`

- [ ] **Step 3: Write the module**

```python
"""What rests at the broker that the book cannot justify (M141, item 23).

Pure. No broker, no clock, no logging, no I/O - so every case below is a table
and the hard part is testable without a Gateway.

**Why arithmetic and never identity.** Order identity does not survive a restart:
`_broker_order_ids` and `_orders` are in memory and empty afterwards
(`version.py:501`). The 24 August orphans were themselves inherited across such
a restart, so "did this app place it" answers no for every order that matters.
The only durable question is whether the BOOK justifies what is resting.

**Why OCA groups net rather than sum.** TNE.AX holds 3,051 bracketed at 30.69
and 36.86: a stop for 3,051 AND a target for 3,051, 6,102 shares of resting sell
against a 3,051 long. Only one leg can ever fire. A rule that sums would flag the
first position this system ever placed correctly, on its first run, which is the
most damaging possible false positive.

**Residual, recorded rather than lost.** This holds only while the application's
entries are MARKET orders (outstanding item 44), so nothing of its own ever rests
unfilled. Give this application resting entry orders and a legitimate working
limit buy on a flat symbol reads as an orphan. Revisit here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from qat.data.broker.adapter import Position, RestingOrder

# Share counts are whole numbers at every broker this app talks to, so this is a
# float-comparison guard rather than a real tolerance. Same value and same
# reasoning as `anomaly._QUANTITY_TOLERANCE` and `check_reconciliation`.
_TOLERANCE = 1e-6

# Statuses at which an order can still fill, and therefore still carries risk.
#
# DERIVED from ib_async's own `OrderStatus.ActiveStates` rather than restated,
# and asserted against it by `tests/data/broker/test_working_statuses.py`. A
# hand-maintained status set is exactly what caused M139: `_IB_STATUS_MAP` held
# four entries and none of IBKR's working states, so a transmitted order read as
# `pending_signoff` and went out four times.
#
# Written as literals HERE because this module is domain and must not import the
# broker library; the test at the boundary is what keeps the two in step. It is
# WIDER than `ib_translate._IB_WORKING_STATUSES`, deliberately and by operator
# decision on 24 August: widening that one moves `_position_stops`, which is a
# sizing input, and it is being shipped separately. The divergence is expected.
#
# `ValidationError` is subtracted: ib_async counts it active, but an order that
# failed validation cannot fill and is not resting risk.
WORKING_STATUSES = frozenset(
    {"Submitted", "PreSubmitted", "PendingSubmit", "ApiPending", "ApiUpdate"}
)


@dataclass(frozen=True, slots=True)
class SymbolOrderDivergence:
    """One symbol and one side carrying more resting quantity than the book
    justifies."""

    symbol: str
    side: str
    resting: float
    justified: float
    excess: float
    flat: bool
    legs: tuple[RestingOrder, ...]

    def describe(self) -> str:
        """Every leg, individually. "Sixteen orphaned legs" was established by
        hand on 24 August and should have been one log line."""
        legs = "; ".join(
            f"{leg.order_id} {leg.side} {leg.order_type} {leg.quantity:g}"
            f"@{leg.stop_price or leg.limit_price or 0:g} (client {leg.owner_client_id})"
            for leg in self.legs
        )
        return (
            f"{self.symbol} {self.side.upper()} resting={self.resting:g} "
            f"justified={self.justified:g} excess={self.excess:g}"
            f"{' FLAT' if self.flat else ''} - {legs}"
        )


def _group_key(order: RestingOrder) -> str:
    """OCA group, else the shared parent, else the order alone.

    IBKR sends "" and 0 rather than absent for the first two; `from_ib_open_order`
    normalises both to None, so falsiness is the right test either way.
    """
    if order.oca_group:
        return f"oca:{order.oca_group}"
    if order.parent_perm_id:
        return f"parent:{order.parent_perm_id}"
    return f"solo:{order.order_id}"


def _netted(orders: Sequence[RestingOrder]) -> float:
    """MAX within a one-cancels-all group, SUM across groups."""
    groups: dict[str, float] = defaultdict(float)
    for order in orders:
        key = _group_key(order)
        groups[key] = max(groups[key], order.quantity)
    return sum(groups.values())


def unjustified_resting_risk(
    orders: Sequence[RestingOrder], positions: Sequence[Position]
) -> list[SymbolOrderDivergence]:
    """Resting quantity the book cannot account for, per symbol and per side.

    A long justifies SELLs up to its size and no BUYs at all; a short the
    reverse; a flat symbol justifies nothing in either direction. Sides are
    grouped and netted independently, so a still-working BUY parent never nets
    against its own SELL children.

    Both directions are measured. Item 23's language is about short risk because
    that is what happened on 24 August, but unaccounted LONG risk is the same
    defect and costs the same to catch here.
    """
    held = {position.symbol: float(position.quantity) for position in positions}

    by_symbol_side: dict[tuple[str, str], list[RestingOrder]] = defaultdict(list)
    for order in orders:
        if order.status not in WORKING_STATUSES:
            continue
        if order.quantity <= _TOLERANCE:
            continue
        by_symbol_side[(order.symbol, order.side.lower())].append(order)

    divergences: list[SymbolOrderDivergence] = []
    for (symbol, side), legs in sorted(by_symbol_side.items()):
        position = held.get(symbol, 0.0)
        resting = _netted(legs)
        justified = max(position, 0.0) if side == "sell" else max(-position, 0.0)
        excess = resting - justified
        if excess <= _TOLERANCE:
            continue
        divergences.append(
            SymbolOrderDivergence(
                symbol=symbol,
                side=side,
                resting=resting,
                justified=justified,
                excess=excess,
                flat=abs(position) <= _TOLERANCE,
                legs=tuple(sorted(legs, key=lambda leg: leg.order_id)),
            )
        )
    return divergences
```

- [ ] **Step 4: Run and confirm pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_orders.py -v`
Expected: 14 passed

> If `Position` does not accept `avg_price` as a keyword, read its definition at `src/qat/data/broker/adapter.py:135` and fix the test helper to match. Do not change `Position`.

- [ ] **Step 5: Add the boundary test that keeps the set honest**

Create `tests/data/broker/test_working_statuses.py`:

```python
"""The orphan scan's status set, checked against ib_async's own (M141).

M139's cause was a hand-maintained status map that did not know IBKR's working
states. This asserts the domain module's literals against the library rather
than trusting them, so an ib_async upgrade that adds a state fails the suite
instead of narrowing the scan in silence.

Lives at the broker boundary because the domain module must not import
ib_async.
"""

from __future__ import annotations

from ib_async import OrderStatus

from qat.data.broker.ib_translate import _IB_WORKING_STATUSES
from qat.domain.oms.resting_orders import WORKING_STATUSES

# ib_async counts this active; an order that failed validation cannot fill.
_NOT_REALLY_WORKING = {"ValidationError"}


def test_the_scan_knows_every_state_ib_async_calls_active():
    assert WORKING_STATUSES == frozenset(OrderStatus.ActiveStates) - _NOT_REALLY_WORKING


def test_the_two_sets_diverge_deliberately():
    """`_IB_WORKING_STATUSES` is NARROWER, by operator decision on 24 August.

    Widening it moves `_position_stops`, which is the denominator of every
    risk-at-stop figure the governor gates entries on, so it ships separately
    with its effect measured. This test exists so the gap reads as a decision
    rather than as an oversight - and so that closing it is a deliberate act
    that updates this test.
    """
    assert _IB_WORKING_STATUSES < WORKING_STATUSES
    assert WORKING_STATUSES - _IB_WORKING_STATUSES == {"ApiPending", "ApiUpdate"}
```

- [ ] **Step 6: Run it**

Run: `.\.venv\Scripts\python.exe -m pytest tests/data/broker/test_working_statuses.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add src/qat/domain/oms/resting_orders.py tests/domain/oms/test_resting_orders.py tests/data/broker/test_working_statuses.py
git commit -m "The rule: OCA-netted resting risk against the book (M141)"
```

---

### Task 4: A store that structurally cannot suppress a halt

**Files:**
- Create: `src/qat/domain/oms/resting_order_anomaly.py`
- Test: `tests/domain/oms/test_resting_order_anomaly.py` (create)

**Interfaces:**
- Produces: `RestingOrderAnomaly` dataclass; `RestingOrderAnomalyStore(data_dir)` with `declare(*, symbol, reason, declared_by, excess) -> RestingOrderAnomaly`, `clear(symbol, operator) -> bool`, `get(symbol)`, `is_quarantined(symbol) -> bool`, `active() -> list[...]`.
- **Must NOT have `explains`.**

- [ ] **Step 1: Write the failing test**

```python
"""Quarantine that cannot lie about positions (M141, item 23).

`PositionAnomalyStore.declare` binds an anomaly to `broker_quantity`, and
`explains()` then returns True for any position divergence at that quantity -
which `check_reconciliation` uses to SUPPRESS the kill-switch trip.

Quarantining a flat symbol through it would therefore grant that symbol immunity
from the position-reconciliation halt at broker=0: the exact rail that caught the
real mismatch on 24 August. Item 23's fix would have partly disabled item 27's.

So this store has no `explains` at all, and the test below is what keeps it that
way.
"""

from __future__ import annotations

from qat.domain.oms.resting_order_anomaly import RestingOrderAnomalyStore


def test_it_cannot_explain_a_position_divergence():
    """THE test. Structural, not behavioural - there is no method to call."""
    assert not hasattr(RestingOrderAnomalyStore, "explains")


def test_declare_then_quarantined(tmp_path):
    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(
        symbol="TNE.AX", reason="8 legs resting on a flat book", declared_by="order-reconciler",
        excess=12304.0,
    )
    assert store.is_quarantined("TNE.AX")
    assert store.get("TNE.AX").excess == 12304.0


def test_it_survives_a_restart(tmp_path):
    RestingOrderAnomalyStore(tmp_path).declare(
        symbol="TNE.AX", reason="orphaned legs", declared_by="order-reconciler", excess=1.0
    )
    assert RestingOrderAnomalyStore(tmp_path).is_quarantined("TNE.AX")


def test_clear_releases_and_reports_whether_it_did(tmp_path):
    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(symbol="TNE.AX", reason="r", declared_by="d", excess=1.0)
    assert store.clear("TNE.AX", "operator") is True
    assert store.clear("TNE.AX", "operator") is False
    assert not store.is_quarantined("TNE.AX")


def test_redeclaring_replaces_rather_than_duplicates(tmp_path):
    store = RestingOrderAnomalyStore(tmp_path)
    store.declare(symbol="TNE.AX", reason="a", declared_by="d", excess=1.0)
    store.declare(symbol="TNE.AX", reason="b", declared_by="d", excess=2.0)
    assert len(store.active()) == 1
    assert store.get("TNE.AX").excess == 2.0


def test_an_unreadable_file_quarantines_nothing_and_does_not_raise(tmp_path):
    (tmp_path / "resting_order_anomalies.json").write_text("{not json", encoding="utf-8")
    assert RestingOrderAnomalyStore(tmp_path).active() == []


def test_no_data_dir_is_tolerated(tmp_path):
    store = RestingOrderAnomalyStore(None)
    store.declare(symbol="TNE.AX", reason="r", declared_by="d", excess=1.0)
    assert store.is_quarantined("TNE.AX")
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_order_anomaly.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the module**

```python
"""A symbol carrying resting orders the book cannot justify (M141, item 23).

Deliberately NOT `PositionAnomalyStore`, and the reason is worth the file.

That store binds an anomaly to `broker_quantity`, and its `explains()` then
tells `check_reconciliation` a position divergence at that quantity is
accounted for - suppressing the kill-switch trip. Quarantining a FLAT symbol
through it (`broker_quantity=0.0`) would grant that symbol immunity from the
position-reconciliation halt at broker=0: precisely the rail that caught the
real mismatch on 24 August.

So item 23's fix would have partly disabled item 27's - the M31a shape, two
individually correct decisions combining into a defect. This store has no
`explains` method at all, so it cannot participate in that question, and a test
asserts the absence so re-adding one fails the suite.

**This contains damage; it does not repair it.** A quarantined symbol stays
quarantined until the orders are dealt with and somebody clears it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "resting_order_anomalies.json"


@dataclass(frozen=True, slots=True)
class RestingOrderAnomaly:
    symbol: str
    reason: str
    declared_by: str
    declared_at: datetime
    excess: float


class RestingOrderAnomalyStore:
    """Active resting-order quarantines, persisted so a restart cannot erase
    them.

    Persistence is the point rather than a convenience: the 24 August orphans
    were INHERITED across a restart, so a quarantine that dies with the process
    is a quarantine that is never in force when it is needed.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._path = Path(data_dir) / _FILENAME if data_dir is not None else None
        self._active: dict[str, RestingOrderAnomaly] = {}
        self._load()

    def declare(
        self, *, symbol: str, reason: str, declared_by: str, excess: float
    ) -> RestingOrderAnomaly:
        anomaly = RestingOrderAnomaly(
            symbol=symbol,
            reason=reason,
            declared_by=declared_by,
            declared_at=datetime.now(UTC),
            excess=excess,
        )
        self._active[symbol] = anomaly
        logger.warning(
            "RESTING ORDER QUARANTINE on %s by %s: %g shares of resting risk the book does "
            "not justify - %s. New entries in this symbol are refused until it is cleared. "
            "The ORDERS ARE NOT CANCELLED by this.",
            symbol,
            declared_by,
            excess,
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
            "Resting-order quarantine on %s cleared by %s (was: %s) - ordinary order flow "
            "resumes for this symbol",
            symbol,
            operator,
            anomaly.reason,
        )
        self._save()
        return True

    def get(self, symbol: str) -> RestingOrderAnomaly | None:
        return self._active.get(symbol)

    def is_quarantined(self, symbol: str) -> bool:
        return symbol in self._active

    def active(self) -> list[RestingOrderAnomaly]:
        return sorted(self._active.values(), key=lambda a: a.symbol)

    def _load(self) -> None:
        """No file, or an unreadable one, means nothing is quarantined - the
        WRONG direction, so it is logged at ERROR rather than swallowed. Still
        better than refusing to start: an application that will not launch
        protects nothing at all.
        """
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._active = {
                str(entry["symbol"]): RestingOrderAnomaly(
                    symbol=str(entry["symbol"]),
                    reason=str(entry["reason"]),
                    declared_by=str(entry["declared_by"]),
                    declared_at=datetime.fromisoformat(entry["declared_at"]),
                    excess=float(entry["excess"]),
                )
                for entry in (raw.get("anomalies") or [])
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Could not read %s (%s) - NO symbol is quarantined for resting orders this "
                "session. The scan will re-detect on its first poll.",
                self._path,
                exc,
            )
            self._active = {}
            return
        if self._active:
            logger.warning(
                "Restored %d resting-order quarantine(s) from %s: %s",
                len(self._active),
                self._path.name,
                ", ".join(sorted(self._active)),
            )

    def _save(self) -> None:
        """Written on every change, not at shutdown: the restart this exists for
        is the one nobody planned."""
        if self._path is None:
            return
        payload = {
            "anomalies": [
                {
                    "symbol": a.symbol,
                    "reason": a.reason,
                    "declared_by": a.declared_by,
                    "declared_at": a.declared_at.isoformat(),
                    "excess": a.excess,
                }
                for a in self.active()
            ]
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run and confirm pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_order_anomaly.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/resting_order_anomaly.py tests/domain/oms/test_resting_order_anomaly.py
git commit -m "RestingOrderAnomalyStore: quarantine with no explains(), on purpose (M141)"
```

---

### Task 5: `OMS.check_resting_orders`, the entry gate, and the Blotter row

**Files:**
- Modify: `src/qat/domain/oms/oms.py:232` (construct the store), `:280-282` (entry gate), and add `check_resting_orders` beside `check_reconciliation` (~line 1840)
- Modify: `src/qat/domain/evaluation/refusals.py:136` (add the refusal row)
- Test: `tests/domain/oms/test_resting_order_reconciliation.py` (create)

**Interfaces:**
- Consumes: `unjustified_resting_risk`, `SymbolOrderDivergence` (Task 3); `RestingOrderAnomalyStore` (Task 4).
- Produces: `OMS.resting_order_anomalies` attribute; `OMS.check_resting_orders() -> list[SymbolOrderDivergence]`.

- [ ] **Step 1: Write the failing test**

```python
"""The orphan scan, wired into the OMS (M141, item 23)."""

from __future__ import annotations

import logging

import pytest

from qat.data.broker.adapter import Position, RestingOrder


def _order(order_id, symbol="TNE.AX", side="sell", qty=3051.0, oca=None):
    return RestingOrder(
        symbol=symbol, order_id=str(order_id), side=side, order_type="STP",
        quantity=qty, status="PreSubmitted", oca_group=oca, owner_client_id=1,
        stop_price=30.69,
    )


class _Broker:
    def __init__(self, orders, positions):
        self._orders, self._positions = orders, positions
        self.cancelled: list[str] = []

    async def open_orders(self):
        return self._orders

    async def positions(self):
        return self._positions

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)


@pytest.mark.asyncio
async def test_a_flat_symbol_with_legs_is_quarantined(oms_factory):
    broker = _Broker([_order(1), _order(2)], [Position(symbol="TNE.AX", quantity=0.0,
                                                       avg_price=0.0)])
    oms = oms_factory(broker)
    found = await oms.check_resting_orders()
    assert len(found) == 1
    assert oms.resting_order_anomalies.is_quarantined("TNE.AX")


@pytest.mark.asyncio
async def test_the_live_TNE_bracket_is_left_alone(oms_factory):
    broker = _Broker(
        [_order(1, oca="OCA-1"), _order(2, oca="OCA-1")],
        [Position(symbol="TNE.AX", quantity=3051.0, avg_price=32.9783)],
    )
    oms = oms_factory(broker)
    assert await oms.check_resting_orders() == []
    assert not oms.resting_order_anomalies.is_quarantined("TNE.AX")


@pytest.mark.asyncio
async def test_every_leg_is_named_in_the_log(oms_factory, caplog):
    broker = _Broker([_order(1), _order(2)], [])
    with caplog.at_level(logging.ERROR):
        await oms_factory(broker).check_resting_orders()
    logged = caplog.text
    assert "RESTING ORDER ORPHAN" in logged
    assert "1 sell STP" in logged and "2 sell STP" in logged


@pytest.mark.asyncio
async def test_a_broker_without_the_capability_judges_nothing(oms_factory):
    class _Old:
        async def positions(self):
            return []

    oms = oms_factory(_Old())
    assert await oms.check_resting_orders() == []


@pytest.mark.asyncio
async def test_it_does_not_touch_the_position_kill_switch(oms_factory):
    broker = _Broker([_order(1)], [])
    oms = oms_factory(broker)
    await oms.check_resting_orders()
    assert not oms.kill_switch.tripped


@pytest.mark.asyncio
async def test_the_scan_quarantines_the_symbol(oms_factory):
    """The refusal itself is exercised by the existing entry-path tests; what
    this asserts is that the scan puts the symbol into the store those read."""
    broker = _Broker([_order(1)], [])
    oms = oms_factory(broker)
    await oms.check_resting_orders()
    assert oms.resting_order_anomalies.get("TNE.AX").excess == 3051.0
```

> **Implementer note on `oms_factory`:** `tests/domain/oms/test_oms.py` already constructs an OMS for tests. Reuse whatever it uses. If it builds one inline, add a local `oms_factory` fixture in **this** file that mirrors it — do **not** invent a new construction path or add a fixture to the shared `conftest.py` for one test module.
>
> The fixture must take the broker positionally and accept `cancel_enabled: bool = False`, building the OMS with a `Settings(resting_order_cancel_enabled=cancel_enabled)` and a `tmp_path` data dir. Task 7 depends on that signature. Give it a `tmp_path`-backed data dir so `RestingOrderAnomalyStore` never writes to `%LOCALAPPDATA%`.

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_order_reconciliation.py -v`
Expected: FAIL — `AttributeError: 'OMS' object has no attribute 'check_resting_orders'`

- [ ] **Step 3: Construct the store**

In `src/qat/domain/oms/oms.py`, immediately after line 232's `self.anomalies = PositionAnomalyStore(...)`:

```python
        # Separate from `anomalies`, and separate ON PURPOSE (M141, item 23).
        # `PositionAnomalyStore.explains` suppresses the reconciliation halt;
        # this store has no such method, so quarantining a flat symbol here
        # cannot grant it immunity from the halt that caught the real mismatch
        # on 24 August.
        self.resting_order_anomalies = RestingOrderAnomalyStore(
            settings.data_dir if settings is not None else None
        )
```

Add the import at the top of the file alongside the `PositionAnomalyStore` import.

- [ ] **Step 4: Add the check**

Immediately after `check_reconciliation`:

```python
    async def check_resting_orders(self) -> list[SymbolOrderDivergence]:
        """Orders resting at the broker that the book cannot justify (M141).

        The counterpart to `check_reconciliation`, and the question nothing was
        asking. That one unions tracked positions with broker positions, so a
        holding this app knows nothing about is still compared. Orders had no
        equivalent: every order-side check asked "is what I believe still
        there" and none asked "what is there that I do not believe in". On
        24 August sixteen orphaned GTC bracket legs rested against a flat
        TNE.AX - up to 12,304 shares of automatic short risk that buying power
        would not have refused.

        Does NOT trip the kill-switch. The risk is symbol-local, the switch
        halts new flow without cancelling anything (24 August's second lesson:
        stopping the process did not stop the fills), and spending a rail that
        needs a human reset on a detector with no field history is how the
        staleness rail ended up suppressed with a 69-hour value.

        A broker that cannot answer judges NOTHING. An adapter without
        `open_orders` must never read as "nothing rests anywhere", which would
        be a fabricated all-clear - the same defensive shape
        `verify_position_stops` uses.
        """
        source = getattr(self.broker, "open_orders", None)
        if source is None:
            return []
        divergences = unjustified_resting_risk(await source(), await self.broker.positions())
        for divergence in divergences:
            logger.error("RESTING ORDER ORPHAN: %s", divergence.describe())
            self.resting_order_anomalies.declare(
                symbol=divergence.symbol,
                reason=(
                    f"{divergence.excess:g} shares of resting {divergence.side} the book does "
                    f"not justify ({'flat' if divergence.flat else f'holds {divergence.justified:g}'})"
                ),
                declared_by="order-reconciler",
                excess=divergence.excess,
            )
        return divergences
```

Add to the imports at the top of `oms.py`:

```python
from qat.domain.oms.resting_order_anomaly import RestingOrderAnomalyStore
from qat.domain.oms.resting_orders import SymbolOrderDivergence, unjustified_resting_risk
```

- [ ] **Step 5: Gate new entries**

In `oms.py`, immediately after the existing `position anomaly` refusal at line 282:

```python
        # Beside the position anomaly for the same reason, and separately
        # because the two stores answer different questions (M141, item 23). A
        # symbol carrying resting orders the book cannot justify may be about
        # to acquire a position nobody asked for; sizing a new entry into it
        # sizes against a quantity with a known expiry.
        resting_anomaly = self.resting_order_anomalies.get(candidate.symbol)
        if resting_anomaly is not None:
            return self._new_rejected_order(
                candidate, 0.0, f"resting order anomaly - {resting_anomaly.reason}"
            )
```

- [ ] **Step 6: Add the Blotter row**

In `src/qat/domain/evaluation/refusals.py`, immediately after the `("position anomaly", ...)` row:

```python
    # M141's, and added WITH the reason string rather than after it. M60's
    # "position anomaly" was never added, so every quarantine refusal rendered
    # as "not recognised - see the note below" from 8 August onward - the exact
    # failure this module exists to prevent, committed against this module.
    ("resting order anomaly", RefusalFamily.STATE, "Resting orders unjustified"),
```

- [ ] **Step 7: Run and confirm pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/ tests/domain/evaluation/ -v`
Expected: all pass, including the pre-existing OMS suite unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/qat/domain/oms/oms.py src/qat/domain/evaluation/refusals.py tests/domain/oms/test_resting_order_reconciliation.py
git commit -m "OMS.check_resting_orders, gated at entry and visible on the Blotter (M141)"
```

---

### Task 6: Run it — startup and poll — with its settings

**Files:**
- Modify: `src/qat/domain/oms/reconciliation.py:48-60` (`start`), and `poll`
- Modify: `src/qat/config.py:360` (beside `reconciliation_poll_seconds`)
- Modify: `scripts/manual_body.py` (beside `QAT_PROTECTION_SWEEP_SECONDS`, ~line 2769)
- Test: `tests/domain/oms/test_resting_order_reconciliation.py` (extend)

**Interfaces:**
- Consumes: `OMS.check_resting_orders` (Task 5).
- Produces: `Settings.resting_order_reconcile_enabled`, `Settings.resting_order_cancel_enabled`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_the_scan_runs_at_startup_before_any_strategy_could_trade(oms_factory, monkeypatch):
    """The 24 August orphans were INHERITED across a restart. A poll-only rail
    would have found them one interval late.

    Both stubs must be COROUTINES. `start()` awaits the scan and passes `_run()`
    to `asyncio.create_task`, so a plain lambda raises rather than failing the
    assertion, which reads as an unrelated error.
    """
    from qat.domain.oms.reconciliation import ReconciliationMonitor

    calls: list[str] = []

    async def _scan():
        calls.append("scan")
        return []

    async def _never_run():
        return None

    oms = oms_factory(_Broker([_order(1)], []))
    monkeypatch.setattr(oms, "check_resting_orders", _scan)
    monitor = ReconciliationMonitor(oms)
    monkeypatch.setattr(monitor, "_run", _never_run)
    await monitor.start()
    await monitor.stop()
    assert calls == ["scan"]


def test_the_settings_default_correctly():
    """Detection on, cancelling off. The second is the one that matters."""
    from qat.config import Settings

    settings = Settings()
    assert settings.resting_order_reconcile_enabled is True
    assert settings.resting_order_cancel_enabled is False


@pytest.mark.asyncio
async def test_detection_can_be_switched_off(oms_factory, monkeypatch):
    from qat.domain.oms.reconciliation import ReconciliationMonitor
    from qat.config import Settings

    calls: list[str] = []

    async def _scan():
        calls.append("scan")
        return []

    async def _never_run():
        return None

    oms = oms_factory(_Broker([_order(1)], []))
    monkeypatch.setattr(oms, "check_resting_orders", _scan)
    monitor = ReconciliationMonitor(oms, settings=Settings(resting_order_reconcile_enabled=False))
    monkeypatch.setattr(monitor, "_run", _never_run)
    await monitor.start()
    await monitor.stop()
    assert calls == []
```

> **`Settings()` reads `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env` whether or not the test mentions it.** Run these under PowerShell, and if the suite already has a fixture that isolates `Settings` (check `tests/conftest.py`), use it rather than constructing bare.

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_order_reconciliation.py -k startup -v`
Expected: FAIL — `ValidationError` / `AttributeError` on the new settings.

- [ ] **Step 3: Add the settings**

In `src/qat/config.py`, immediately after `protection_sweep_seconds`:

```python
    # Whether resting orders are reconciled against the book at all (M141,
    # item 23). On by default: it only observes and quarantines.
    #
    # The gap it closes is that NOTHING watched open orders. On 24 August an
    # interrupted session left sixteen orphaned GTC bracket legs at the broker
    # and a FLAT TNE.AX carried up to 12,304 shares of automatic short risk,
    # which buying power would not have refused.
    resting_order_reconcile_enabled: bool = True

    # Whether the reconciler may CANCEL what it finds, and only on symbols the
    # book is flat in.
    #
    # Off by default, for `delever_sweep_enabled`'s reason one step down:
    # cancelling is a smaller delegation than selling, but it is still this
    # application acting on the account unattended, on a detector with no field
    # history. A HELD symbol carrying excess is never trimmed - choosing which
    # OCA group dies is a judgement made badly without a human, and getting it
    # wrong strips the stop from a real long.
    resting_order_cancel_enabled: bool = False
```

- [ ] **Step 4: Wire the monitor**

In `reconciliation.py`, inside `start()`, after the `adopt_broker_positions` try/except block:

```python
        # After adoption and before the first poll, because the orphans this
        # looks for are INHERITED across a restart - the 24 August case exactly
        # - and a poll-only rail finds them one interval late.
        if self.settings.resting_order_reconcile_enabled:
            try:
                await self.oms.check_resting_orders()
            except Exception:  # noqa: BLE001 - a broker blip must not block startup
                logger.warning(
                    "Could not scan resting orders at startup - the first poll will retry",
                    exc_info=True,
                )
```

And inside `poll()`, after `check_reconciliation`:

```python
        if self.settings.resting_order_reconcile_enabled:
            await self.oms.check_resting_orders()
```

- [ ] **Step 5: Document both settings**

In `scripts/manual_body.py`, immediately after the `QAT_PROTECTION_SWEEP_SECONDS` tuple:

```python
            (
                "QAT_RESTING_ORDER_RECONCILE_ENABLED",
                "true",
                "Whether orders resting at the broker are checked against what the book "
                "justifies. On 24 August sixteen orphaned bracket legs rested against a FLAT "
                "position and nothing was watching. Observes and quarantines; cancels nothing.",
            ),
            (
                "QAT_RESTING_ORDER_CANCEL_ENABLED",
                "false",
                "Whether that check may CANCEL what it finds, and only where the book holds "
                "none of the symbol. Off by default: acting on the account unattended is not "
                "granted implicitly. A held symbol is never trimmed.",
            ),
```

- [ ] **Step 6: Run the settings guard and the new tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_manual_documents_every_setting.py tests/domain/oms/test_resting_order_reconciliation.py -v`
Expected: all pass. If the manual guard fails, the wording above did not land in `manual_body.py` — fix it there, **not** by adding to `_NOT_IN_THE_MANUAL`; both settings are trading controls.

- [ ] **Step 7: Commit**

```bash
git add src/qat/config.py src/qat/domain/oms/reconciliation.py scripts/manual_body.py tests/domain/oms/test_resting_order_reconciliation.py
git commit -m "Run the resting-order scan at startup and on the poll (M141)"
```

---

### Task 7: Cancelling, flat symbols only

**Files:**
- Modify: `src/qat/domain/oms/oms.py` (`check_resting_orders`)
- Test: `tests/domain/oms/test_resting_order_reconciliation.py` (extend)

**Interfaces:**
- Consumes: `Settings.resting_order_cancel_enabled` (Task 6).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_cancel_is_off_by_default(oms_factory):
    broker = _Broker([_order(1), _order(2)], [])
    await oms_factory(broker).check_resting_orders()
    assert broker.cancelled == []


@pytest.mark.asyncio
async def test_with_the_flag_on_a_flat_symbol_is_cancelled(oms_factory):
    broker = _Broker([_order(1), _order(2)], [])
    oms = oms_factory(broker, cancel_enabled=True)
    await oms.check_resting_orders()
    assert broker.cancelled == ["1", "2"]


@pytest.mark.asyncio
async def test_a_HELD_symbol_is_never_cancelled(oms_factory):
    """Excess on a held name is reported and quarantined, never trimmed.
    Choosing which OCA group dies strips the stop from a real long."""
    broker = _Broker(
        [_order(1, qty=3076.0), _order(2, qty=3076.0), _order(3, qty=3076.0)],
        [Position(symbol="TNE.AX", quantity=3076.0, avg_price=32.0)],
    )
    oms = oms_factory(broker, cancel_enabled=True)
    found = await oms.check_resting_orders()
    assert found and found[0].excess > 0
    assert broker.cancelled == []
    assert oms.resting_order_anomalies.is_quarantined("TNE.AX")


@pytest.mark.asyncio
async def test_one_refused_cancel_does_not_abort_the_rest(oms_factory, caplog):
    """Error 10147: visible via reqAllOpenOrders, not cancellable from here."""

    class _Stubborn(_Broker):
        async def cancel_order(self, order_id):
            if order_id == "1":
                raise RuntimeError("Error 10147: order not found from this client")
            self.cancelled.append(order_id)

    broker = _Stubborn([_order(1), _order(2), _order(3)], [])
    with caplog.at_level(logging.ERROR):
        await oms_factory(broker, cancel_enabled=True).check_resting_orders()
    assert broker.cancelled == ["2", "3"]
    assert "10147" in caplog.text or "could not be cancelled" in caplog.text
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_order_reconciliation.py -k cancel -v`
Expected: FAIL — `assert [] == ["1", "2"]`

- [ ] **Step 3: Add the cancel branch**

In `check_resting_orders`, inside the `for divergence in divergences:` loop, after `declare(...)`:

```python
            if not divergence.flat:
                # Reported and quarantined, never trimmed. Choosing which OCA
                # group dies on a HELD symbol is a judgement this application
                # should not make unattended, and getting it wrong strips the
                # stop from a real long - the failure `verify_position_stops`
                # exists to shout about.
                continue
            if self.settings is None or not self.settings.resting_order_cancel_enabled:
                continue
            for leg in divergence.legs:
                try:
                    await self.broker.cancel_order(leg.order_id)
                except Exception as exc:  # noqa: BLE001 - one refusal must not stop the rest
                    logger.error(
                        "Orphaned leg %s on %s could not be cancelled (%s). It is visible via "
                        "reqAllOpenOrders but owned by client %s, which is error 10147's shape: "
                        "visible is not cancellable. STILL RESTING.",
                        leg.order_id,
                        divergence.symbol,
                        exc,
                        leg.owner_client_id,
                    )
                    continue
                logger.warning(
                    "Cancelled orphaned leg %s on %s (%s %s %g) - the book holds none of it",
                    leg.order_id,
                    divergence.symbol,
                    leg.side,
                    leg.order_type,
                    leg.quantity,
                )
```

- [ ] **Step 4: Run and confirm pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/domain/oms/test_resting_order_reconciliation.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/qat/domain/oms/oms.py tests/domain/oms/test_resting_order_reconciliation.py
git commit -m "Cancel orphaned legs on flat symbols only, behind an off-by-default flag (M141)"
```

---

### Task 8: The fifth check, the milestone, and the full suite

**Files:**
- Modify: `scripts/session_check.ps1:212` (heading and a fifth check)
- Modify: `src/qat/version.py:524` (`MILESTONE`) and the milestone comment block above it
- Modify: `docs/HANDOFF.md` (item 23 → DONE; add the split-out status-widening item)

- [ ] **Step 1: Add the fifth check**

In `scripts/session_check.ps1`, change `Write-Section 'THE FOUR CHECKS'` to `Write-Section 'THE FIVE CHECKS'`, and after check 4 add:

```powershell
# 5 - orders resting at the broker that the book cannot justify (M141, item 23).
# A FLAT symbol can carry automatic short risk: on 24 August TNE.AX carried up to
# 12,304 shares of it in sixteen orphaned GTC bracket legs, and nothing watched.
$orphans = $rows | Where-Object { $_.message -cmatch 'RESTING ORDER ORPHAN' }
if ($orphans) {
    Write-Output ("5 orphans  *** {0} UNJUSTIFIED RESTING ORDER LINE(S) ***" -f $orphans.Count)
    $orphans | Select-Object -Last 3 | ForEach-Object {
        Write-Output ("           {0}" -f $_.message)
    }
} else {
    Write-Output "5 orphans  none reported this run"
}
```

> Match the surrounding style: check how checks 2 and 4 render their counts and follow it rather than the sketch above if it differs.

- [ ] **Step 2: Verify the script still runs**

Run in **PowerShell**: `& "C:\Claude Programming\scripts\session_check.ps1"`
Expected: the report prints, now with a `5 orphans` line and the heading `THE FIVE CHECKS`. No errors.

- [ ] **Step 3: Bump the milestone**

In `src/qat/version.py`, set `MILESTONE = "M141"` and add a comment block above it in the established style, covering: what item 23 was, that the scan is arithmetic and not identity, why OCA groups net, that the quarantine store has no `explains()` and why, that the status widening is deliberately split out, and that cancel is off by default and flat-only.

- [ ] **Step 4: Update the handoff**

In `docs/HANDOFF.md`, strike item 23 to `**DONE — M141**` in the established style, keeping the original text below the strike. Add a new outstanding item for the split-out work:

> **The working-status set is narrow in `ib_translate`.** `_IB_WORKING_STATUSES` holds three of ib_async's five real working states; `ApiPending` and `ApiUpdate` are missing, so `from_ib_resting_stop` reads a stop in either as no protection and `verify_position_stops` logs `POSITION UNPROTECTED` on a protected position. M141 fixed this for the orphan scan only, in its own set, because widening the shared one moves `_position_stops` — the denominator of every risk-at-stop figure the governor gates entries on. Ship it separately and measure the aggregate before and after on a watched session. `tests/data/broker/test_working_statuses.py` asserts the divergence, so closing it is a deliberate act.

Also correct item 25 in place: `preflight` already routes through `reqAllOpenOrdersAsync` via `broker.resting_stops()` (`preflight.py:445`); its real defect is deriving `unprotected` from held positions only (`preflight.py:450`).

- [ ] **Step 5: Full suite and the linters**

Run in **PowerShell**:

```
.\.venv\Scripts\python.exe -m invoke lint
.\.venv\Scripts\python.exe -m invoke test
```

Expected: ruff, black, mypy and bandit clean; suite green with ~2,617 + the new tests collected, 25 skipped.

**If a pre-existing test fails, check the fixture before the guard** (M140's lesson). One of the three tests M140's first version broke turned out to run two clocks.

- [ ] **Step 6: Commit and push once**

```bash
git add -A
git commit -m "M141: reconcile resting orders against the book (item 23)"
git push
```

- [ ] **Step 7: Confirm CI**

Run: `gh run list --limit 3`
A green local suite is not evidence CI passed. Wait for the run and confirm it is green before reporting the work done.

---

## What is NOT done when this plan is finished

- **The kill switch is still tripped.** Resetting it is item 28 and belongs to a launch the operator is watching.
- **Nothing has run against the live account.** The first real exercise of this rail is that watched launch, and per the habit that found everything on 24 August, the rail is not proven until it has run there.
- **The status widening is outstanding**, as its own item, by decision.
- **Order identity still does not survive a restart** (`version.py:501`). This design is built to be correct without it; that remains true and remains unfixed.
