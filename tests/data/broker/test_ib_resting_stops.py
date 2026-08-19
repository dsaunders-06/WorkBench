"""Stage 1 Task 4: `resting_stops` / `resting_stop_orders` on IBKR.

Without these the app stops verifying that what it believes protects the book
is actually resting at the broker. **"Ten of ten carrying a stop" becomes an
assertion rather than an observation** - and that was the US trial's single
strongest safety claim, held across nineteen days.

The failure they exist to catch is not hypothetical. On 31 July six brackets
were submitted DAY, their take-profit legs expired at the close, Alpaca
cancelled the paired stops with them as OCA does, and **nothing noticed** -
reconciliation compares filled quantities and an expired protective leg
changes none of them.

Four things measured on 19 August shape this, and none is guessed:

* Both `openTrades()` and `reqAllOpenOrders()` DO show a resting stop, agreeing
  on `orderType`, `auxPrice`, status and `permId`.
* **`openTrades()` is scoped to the CONNECTED client and `reqAllOpenOrders()`
  is not.** A stop placed under another clientId is invisible to the first, and
  invisible protection reads as NO protection - which makes the app re-arm a
  position that is already protected.
* **`whyHeld` distinguishes a stop held at IBKR from one working at the
  exchange.** A resting stop read `'trigger'`; a bracket leg read
  `'child,trigger'`. Carried through RAW, because the interpretation
  (simulated vs native) is a separate judgement from the evidence.
* **An order belongs to the clientId that placed it.** A cancel from another
  fails with error 10147 while `reqAllOpenOrders()` still shows the order.
  "Is this protected" and "can I move that stop" are different questions, and
  `resting_stop_orders` is what M39 calls to MODIFY - so it has to answer both.
"""

from __future__ import annotations

from typing import Any

from ib_async import Contract
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter
from qat.domain.bus import EventBus


def _resting(
    symbol: str = "BHP",
    order_type: str = "STP",
    aux: float = 58.0,
    quantity: float = 10,
    status: str = "PreSubmitted",
    why_held: str = "trigger",
    perm_id: int = 828725903,
    client_id: int = 1,
    parent_id: int = 0,
    limit_price: float = 0.0,
) -> Trade:
    order = IBOrder(
        orderId=perm_id % 1000,
        clientId=client_id,
        permId=perm_id,
        action="SELL",
        totalQuantity=quantity,
        orderType=order_type,
        auxPrice=aux,
        lmtPrice=limit_price,
        parentId=parent_id,
        tif="GTC",
    )
    return Trade(
        contract=Contract(symbol=symbol, secType="STK", exchange="ASX", currency="AUD"),
        order=order,
        orderStatus=OrderStatus(
            orderId=order.orderId, status=status, permId=perm_id, whyHeld=why_held
        ),
    )


class OpenOrdersIB:
    """Answers `reqAllOpenOrdersAsync`. `openTrades` answers something
    DIFFERENT so a test can tell which one the adapter actually asked - the
    client-scoped call would silently miss another client's stop."""

    def __init__(self, trades: list[Trade] | None = None) -> None:
        self._trades = trades or []
        self.all_open_calls = 0
        self.open_trades_calls = 0

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *a: Any, **k: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    async def reqAllOpenOrdersAsync(self) -> list[Trade]:
        self.all_open_calls += 1
        return list(self._trades)

    def openTrades(self) -> list[Trade]:
        self.open_trades_calls += 1
        return []

    def placeOrder(self, *a: Any, **k: Any) -> Any:
        raise AssertionError("a protection scan placed an order")

    def cancelOrder(self, *a: Any, **k: Any) -> Any:
        raise AssertionError("a protection scan cancelled an order")

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


def _adapter(client: OpenOrdersIB, market: str = "ASX") -> IBAdapter:
    return IBAdapter(
        client,
        EventBus(),
        settings=Settings(_env_file=None, trading_mode="paper", market=market),
    )


async def test_a_resting_stop_is_reported_under_the_apps_symbol() -> None:
    """IBKR answers BHP; the app tracks BHP.AX. A stop keyed on the wrong form
    protects nothing the app can find, and `verify_position_stops` would read
    the position as bare."""
    client = OpenOrdersIB([_resting()])

    stops = await _adapter(client).resting_stop_orders()

    assert set(stops) == {"BHP.AX"}
    assert stops["BHP.AX"].stop_price == 58.0
    assert stops["BHP.AX"].quantity == 10


async def test_the_order_id_is_the_permid_so_it_can_be_modified() -> None:
    """M39 re-prices a resting stop through a corporate action by calling
    `modify_order` with this id. It has to be the id the rest of the app knows
    the order by, which `from_ib_trade` sets to permId."""
    client = OpenOrdersIB([_resting(perm_id=828725903)])

    assert (await _adapter(client).resting_stop_orders())["BHP.AX"].order_id == "828725903"


async def test_resting_stops_derives_from_the_same_single_scan() -> None:
    """One scan, not two. Two could disagree about what counts as protection,
    and 'protected' is the answer the re-arm acts on."""
    client = OpenOrdersIB([_resting()])
    adapter = _adapter(client)

    assert await adapter.resting_stops() == {"BHP.AX": 58.0}
    assert client.all_open_calls == 1


async def test_the_all_clients_call_is_used_not_the_client_scoped_one() -> None:
    """`openTrades()` returns only the CONNECTED client's orders. A stop placed
    under another clientId would be invisible, read as no protection, and make
    the app re-arm a position that is already protected - while the duplicate
    it places is refused for insufficient shares."""
    client = OpenOrdersIB([_resting()])

    await _adapter(client).resting_stop_orders()

    assert client.all_open_calls == 1
    assert client.open_trades_calls == 0, "used the client-scoped openTrades()"


async def test_why_held_is_carried_through_raw() -> None:
    """Measured: a resting stop reads whyHeld='trigger' - IBKR's marker for an
    order held AT IBKR awaiting its trigger rather than working at the
    exchange. Carried raw: whether that means 'simulated' in a live ASX account
    is a separate judgement from the evidence, and the evidence is what belongs
    in the record."""
    client = OpenOrdersIB([_resting(why_held="trigger")])

    assert (await _adapter(client).resting_stop_orders())["BHP.AX"].why_held == "trigger"


async def test_the_owning_client_id_is_carried() -> None:
    """An order belongs to the clientId that placed it: a cancel from another
    fails with error 10147 while reqAllOpenOrders() still shows it. Visible is
    not cancellable, so the record that M39 modifies from has to say whose it
    is."""
    client = OpenOrdersIB([_resting(client_id=7)])

    assert (await _adapter(client).resting_stop_orders())["BHP.AX"].owner_client_id == 7


async def test_a_bracket_leg_still_counts_as_resting() -> None:
    """The M33d shape in IBKR clothes. A bracket's stop child sits
    PreSubmitted with whyHeld='child,trigger' until the parent fills - it IS
    the protection, and a scan that only accepted fully-live orders would
    report every bracketed position as unprotected."""
    client = OpenOrdersIB([_resting(status="PreSubmitted", why_held="child,trigger", parent_id=3)])

    stops = await _adapter(client).resting_stop_orders()

    assert "BHP.AX" in stops


async def test_a_take_profit_leg_is_not_mistaken_for_a_stop() -> None:
    """The other leg of the same bracket is a LIMIT. Reporting it as the stop
    would put the TARGET price into `risk_at_stop` - measuring risk to a level
    above the entry, which reads as risk-free."""
    client = OpenOrdersIB([_resting(order_type="LMT", aux=0.0, limit_price=70.0)])

    assert await _adapter(client).resting_stop_orders() == {}


async def test_a_trailing_stop_is_not_reported_with_a_wrong_level() -> None:
    """TRAIL's working level is not `auxPrice` - reading it as one would report
    a stop price the broker is not holding. Excluded deliberately rather than
    by omission; the app places STP, and a TRAIL on an adopted position is a
    thing to notice rather than to mis-report."""
    client = OpenOrdersIB([_resting(order_type="TRAIL")])

    assert await _adapter(client).resting_stop_orders() == {}


async def test_a_terminal_order_is_not_resting() -> None:
    """A cancelled stop is exactly the 31 July failure: the record says
    protected, the broker holds nothing."""
    client = OpenOrdersIB([_resting(status="Cancelled")])

    assert await _adapter(client).resting_stop_orders() == {}


async def test_nothing_open_reads_as_no_protection_found() -> None:
    assert await _adapter(OpenOrdersIB([])).resting_stop_orders() == {}
    assert await _adapter(OpenOrdersIB([])).resting_stops() == {}


async def test_two_stops_for_one_symbol_resolve_deterministically() -> None:
    """A symbol carrying two live stops is an anomaly, not a normal state - a
    duplicate re-arm, or a leg that outlived its parent. The dict has one slot,
    so the choice must not depend on the order the broker happened to return
    them in: the TIGHTEST stop wins, because it is the one that will actually
    fire, and reporting the looser one would overstate the risk taken."""
    # The TIGHTEST is listed FIRST on purpose. Ordered the other way round,
    # "whichever came last" gives the same answer and the test proves nothing -
    # which is exactly what it did until a mutation run pointed it out.
    client = OpenOrdersIB([_resting(aux=58.0, perm_id=1), _resting(aux=55.0, perm_id=2)])

    assert (await _adapter(client).resting_stop_orders())["BHP.AX"].stop_price == 58.0


async def test_a_us_symbol_keeps_its_plain_form() -> None:
    client = OpenOrdersIB([_resting(symbol="AAPL")])

    assert set(await _adapter(client, market="US").resting_stop_orders()) == {"AAPL"}


async def test_the_tightest_stop_flips_direction_for_a_short() -> None:
    """ "Tightest" is not "highest". A SELL stop protecting a long fires on the
    way DOWN, so the higher one fires first; a BUY stop protecting a short
    fires on the way UP, so the LOWER one does. A rule that always took the
    maximum would report the stop furthest from firing on every short - an
    overstatement of the risk actually being carried.
    """
    # Again the tightest first, so "last wins" would answer 70.0.
    client = OpenOrdersIB([_resting(aux=66.0, perm_id=1), _resting(aux=70.0, perm_id=2)])
    for trade in client._trades:
        trade.order.action = "BUY"

    stops = await _adapter(client).resting_stop_orders()

    assert stops["BHP.AX"].stop_price == 66.0


async def test_the_choice_is_the_rule_not_a_position_in_the_list() -> None:
    """Three stops, tightest in the MIDDLE.

    With only two, "first" and "last" are the only positions a naive
    implementation can pick, so no two-order test can rule both out - a
    mutation run demonstrated exactly that by surviving as "first wins". The
    broker returns open orders in whatever order it likes, and the answer has
    one slot, so what matters is that the RULE decides and not the arrival
    sequence.
    """
    client = OpenOrdersIB(
        [
            _resting(aux=55.0, perm_id=1),
            _resting(aux=58.0, perm_id=2),
            _resting(aux=56.0, perm_id=3),
        ]
    )

    stop = (await _adapter(client).resting_stop_orders())["BHP.AX"]

    assert stop.stop_price == 58.0, "picked by arrival order rather than by the rule"
    assert stop.order_id == "2"
