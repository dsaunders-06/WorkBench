"""Stage 1 Task 2: `recent_fills` on IBKR.

Without it `absorb_broker_fills` returns immediately, so a protective stop
firing at the broker is never recorded as a closed trade - and `M70`/`M71`
never run at all. It is the method the most machinery hangs off.

**Four things measured before this was written**, not assumed:

* `IB.fills()` is documented "all fills from this session" and therefore
  CANNOT see a fill that happened while the app was down - which is exactly
  the case `absorb_broker_fills` exists for. `reqExecutions` is the one that
  can, so that is the one used.
* **IBKR's side is `BOT`/`SLD`, not buy/sell.** An unmapped value silently
  becoming "buy" would mis-side a fill in the ledger, so an unrecognised side
  is dropped loudly rather than guessed.
* **The window is applied on FILL time here**, not delegated. Alpaca's `after=`
  turned out to mean `submitted_at`, and the one execution the method existed
  to catch was the one it could not see (M48).
* **`permId` is the identity**, matching what `from_ib_trade` writes onto
  `order.order_id` (Task 3, confirmed surviving a Gateway restart on
  19 August). `OMS._order_the_broker_calls` compares those two strings; if
  this used `orderId` the comparison would fail and M70/M71 would stay dormant
  exactly as they were before Task 3.

**And one that only shows up here: the symbol has to come BACK.** The app
tracks `BHP.AX`; IBKR answers `BHP`. M96 translated one direction, and a fill
returned as `BHP` would never match a tracked `BHP.AX` - the `symbols` filter
would drop it and the OMS would not recognise it. M26's rule is that a symbol
which round-trips wrongly against the broker is a reconciliation mismatch and
a halted session, so the return leg is translated too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ib_async import CommissionReport, Contract, Execution, Fill

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter
from qat.data.symbols import from_ibkr
from qat.domain.bus import EventBus

NOW = datetime(2026, 8, 19, 6, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=1)


def _fill(
    symbol: str = "BHP",
    side: str = "SLD",
    shares: float = 10,
    price: float = 58.25,
    perm_id: int = 828725903,
    order_id: int = 8,
    when: datetime | None = None,
) -> Fill:
    contract = Contract(symbol=symbol, secType="STK", exchange="ASX", currency="AUD")
    execution = Execution(
        execId="0001.abc",
        time=when or NOW,
        side=side,
        shares=shares,
        price=price,
        permId=perm_id,
        orderId=order_id,
        cumQty=shares,
        avgPrice=price,
    )
    return Fill(
        contract=contract,
        execution=execution,
        commissionReport=CommissionReport(),
        time=when or NOW,
    )


class FillsIB:
    """Serves executions through `reqExecutionsAsync`, and records the filter.

    `fills()` deliberately answers something DIFFERENT, so a test can tell
    which one the adapter actually asked. If the adapter reads `fills()` it
    gets the session-scoped answer and the tests say so.
    """

    def __init__(self, executions: list[Fill] | None = None) -> None:
        self._executions = executions or []
        self.filters: list[Any] = []
        self.fills_called = False

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *a: Any, **k: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def fills(self) -> list[Fill]:
        self.fills_called = True
        return []

    async def reqExecutionsAsync(self, execFilter: Any = None) -> list[Fill]:
        self.filters.append(execFilter)
        return list(self._executions)

    def placeOrder(self, *a: Any, **k: Any) -> Any:
        raise AssertionError("recent_fills placed an order")

    def cancelOrder(self, *a: Any, **k: Any) -> Any:
        raise AssertionError("recent_fills cancelled an order")

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _adapter(client: FillsIB, market: str = "ASX") -> IBAdapter:
    return IBAdapter(
        client,
        EventBus(),
        settings=Settings(_env_file=None, trading_mode="paper", market=market),
    )


def test_the_symbol_comes_back_in_the_apps_own_form() -> None:
    assert from_ibkr("BHP", "ASX") == "BHP.AX"
    assert from_ibkr("AAPL", "US") == "AAPL"


def test_a_symbol_that_already_carries_its_suffix_is_not_doubled() -> None:
    assert from_ibkr("BHP.AX", "ASX") == "BHP.AX"


async def test_an_execution_becomes_a_broker_fill() -> None:
    client = FillsIB([_fill()])

    fills = await _adapter(client).recent_fills(SINCE)

    assert len(fills) == 1
    fill = fills[0]
    assert fill.symbol == "BHP.AX", "the fill would never match the tracked position"
    assert fill.side == "sell"
    assert fill.quantity == 10
    assert fill.price == 58.25
    assert fill.filled_at == NOW


async def test_the_order_id_is_the_permid_that_from_ib_trade_writes() -> None:
    """The whole point of Task 3. `OMS._order_the_broker_calls` compares this
    string against `order.order_id`, which `from_ib_trade` sets to the permId.
    Using `orderId` here would make that comparison fail and leave M70/M71
    dormant exactly as they were before Task 3 was written."""
    client = FillsIB([_fill(perm_id=828725903, order_id=8)])

    fill = (await _adapter(client).recent_fills(SINCE))[0]

    assert fill.order_id == "828725903"
    assert fill.order_id != "8"


async def test_bot_and_sld_map_to_buy_and_sell() -> None:
    client = FillsIB([_fill(side="BOT"), _fill(side="SLD")])

    fills = await _adapter(client).recent_fills(SINCE)

    assert [f.side for f in fills] == ["buy", "sell"]


async def test_an_unrecognised_side_is_dropped_not_guessed() -> None:
    """IBKR's side is BOT/SLD. Anything else defaulting to "buy" would put a
    fill into the ledger pointing the wrong way - a realised P&L with the sign
    reversed, which the promotion gate would then read."""
    client = FillsIB([_fill(side="WHAT", perm_id=1), _fill(side="SLD", perm_id=2)])

    fills = await _adapter(client).recent_fills(SINCE)

    assert [f.order_id for f in fills] == ["2"], "an unknown side was mapped anyway"


async def test_the_window_is_applied_on_fill_time() -> None:
    """M48's lesson. The window belongs on when the execution HAPPENED, not on
    when its order was submitted - a protective order's parent was submitted
    when the position opened, hours or days earlier."""
    client = FillsIB(
        [
            _fill(perm_id=1, when=SINCE - timedelta(minutes=1)),
            _fill(perm_id=2, when=SINCE),
            _fill(perm_id=3, when=SINCE + timedelta(minutes=1)),
        ]
    )

    fills = await _adapter(client).recent_fills(SINCE)

    assert [f.order_id for f in fills] == ["3"]


async def test_symbols_bound_the_question_in_the_apps_own_form() -> None:
    client = FillsIB([_fill(symbol="BHP", perm_id=1), _fill(symbol="CBA", perm_id=2)])

    fills = await _adapter(client).recent_fills(SINCE, symbols=["BHP.AX"])

    assert [f.order_id for f in fills] == ["1"]


async def test_an_empty_symbol_list_asks_the_broker_nothing() -> None:
    """Nothing tracked, so nothing can have closed behind our back - and no
    reason to spend a request finding that out."""
    client = FillsIB([_fill()])

    assert await _adapter(client).recent_fills(SINCE, symbols=[]) == []
    assert client.filters == []


async def test_reqexecutions_is_used_rather_than_the_session_scoped_fills() -> None:
    """`IB.fills()` is "all fills from this session", so it cannot see a fill
    that happened while the app was DOWN - which is the case
    absorb_broker_fills exists for. Asking the wrong one would work perfectly
    in every test and fail only on the restart that mattered."""
    client = FillsIB([_fill()])

    await _adapter(client).recent_fills(SINCE)

    assert client.filters, "reqExecutions was never called"
    assert not client.fills_called, "used the session-scoped IB.fills() instead"


async def test_a_us_fill_keeps_its_plain_symbol() -> None:
    client = FillsIB([_fill(symbol="AAPL")])

    fill = (await _adapter(client, market="US").recent_fills(SINCE))[0]

    assert fill.symbol == "AAPL"
