"""M96: IBKR could not resolve an ASX symbol at all.

`to_ib_contract(symbol, exchange="SMART", currency="USD")` was called by
`place_order` without ever overriding its defaults. Two faults, both measured
against the live paper Gateway on 19 August:

* **The `.AX` suffix was never stripped.** The app's ASX tickers are `BHP.AX`
  (`universe.py`, the ShareTrader convention). `Stock("BHP.AX", "SMART", ...)`
  returns **error 200, no security definition** - in AUD as well as USD. Every
  ASX order would be rejected outright.
* **The currency was hardcoded USD.** `Stock("BHP", "SMART", "USD")` resolves
  to **conId 4986, NYSE, "BHP GROUP LTD-SPON ADR"**, a different instrument
  from the ASX listing (conId 4036812, AUD).

Stated precisely, because the first reading of the evidence was wrong: this
fails LOUDLY. The wrong-instrument resolution needs an UNSUFFIXED symbol, and
the app always sends the suffix, so it gets a rejection rather than a US fill.

This is M26's problem in a new place, so it is fixed in M26's way: one internal
form and a translation at each vendor boundary, in `symbols.py`, rather than a
special case buried in the adapter. `_split_exchange` was already there and
already reasoned about - `.AX` is an exchange and `.B` is a class share, listed
rather than guessed, because `.L` would break the guess.
"""

from __future__ import annotations

from typing import Any

from ib_async import Contract
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.data.broker.ib_translate import to_ib_contract, to_ib_parent
from qat.data.symbols import to_ibkr
from qat.domain.bus import EventBus


def test_the_exchange_suffix_is_stripped_for_ibkr() -> None:
    """IBKR takes the base symbol and learns the venue from the contract's
    exchange and currency, not from a suffix. Measured: BHP.AX resolves to
    nothing at all."""
    assert to_ibkr("BHP.AX") == "BHP"


def test_a_us_symbol_is_unchanged() -> None:
    assert to_ibkr("AAPL") == "AAPL"


def test_a_class_share_keeps_its_dot() -> None:
    """The M26 distinction, which is why the suffixes are listed rather than
    inferred: `.AX` is an exchange, `.B` is a class share, and a rule that
    stripped both would send BRK for BRK.B."""
    assert to_ibkr("BRK.B") == "BRK.B"


def test_an_asx_contract_carries_aud_and_the_asx_primary_exchange() -> None:
    contract = to_ib_contract("BHP.AX", market="ASX")

    assert contract.symbol == "BHP"
    assert contract.currency == "AUD"
    assert contract.exchange == "SMART"
    assert contract.primaryExchange == "ASX", (
        "without primaryExchange the symbol is ambiguous across venues - this "
        "is what pointed BHP at the NYSE ADR"
    )


def test_a_us_contract_is_unchanged() -> None:
    contract = to_ib_contract("AAPL")

    assert contract.symbol == "AAPL"
    assert contract.currency == "USD"
    assert contract.exchange == "SMART"


class _Recorder:
    """Records the contracts orders are placed against."""

    def __init__(self) -> None:
        self.contracts: list[Contract] = []
        self._next = 10

    def isConnected(self) -> bool:
        return True

    async def connectAsync(self, *a: Any, **k: Any) -> None:
        return None

    def disconnect(self) -> None:
        return None

    async def reqCurrentTimeAsync(self) -> Any:
        return None

    def placeOrder(self, contract: Contract, order: IBOrder) -> Trade:
        self.contracts.append(contract)
        if not order.orderId:
            order.orderId = self._next
            self._next += 1
        order.permId = 0  # not yet acknowledged, as real IBKR returns it (M99)
        return Trade(
            contract=contract,
            order=order,
            orderStatus=OrderStatus(orderId=order.orderId, status="PreSubmitted"),
        )

    def cancelOrder(self, order: IBOrder, manualCancelOrderTime: str = "") -> Trade | None:
        return None

    def positions(self, account: str = "") -> list[Any]:
        return []

    def accountSummary(self, account: str = "") -> list[Any]:
        return []


async def test_place_order_builds_the_contract_from_the_configured_market() -> None:
    """The defect was never in `to_ib_contract` alone - `place_order` called it
    and took whatever the defaults gave, so the market the app is configured
    for never reached the contract."""
    client = _Recorder()
    adapter = IBAdapter(
        client,
        EventBus(),
        settings=Settings(_env_file=None, trading_mode="paper", market="ASX"),
    )

    await adapter.place_order(Order(symbol="BHP.AX", side="buy", quantity=1, order_id="a"))

    contract = client.contracts[0]
    assert contract.symbol == "BHP"
    assert contract.currency == "AUD"


async def test_every_leg_of_a_bracket_uses_the_same_market_contract() -> None:
    """Three orders, three contracts. A leg built against the wrong venue
    would protect a position on a different exchange."""
    client = _Recorder()
    adapter = IBAdapter(
        client,
        EventBus(),
        settings=Settings(_env_file=None, trading_mode="paper", market="ASX"),
    )

    await adapter.place_order(
        Order(
            symbol="BHP.AX",
            side="buy",
            quantity=1,
            order_id="b",
            stop_price=25.0,
            take_profit_price=40.0,
        )
    )

    assert len(client.contracts) == 3
    assert {c.symbol for c in client.contracts} == {"BHP"}
    assert {c.currency for c in client.contracts} == {"AUD"}


def test_a_bracketed_entry_is_gtc_not_left_to_a_broker_preset() -> None:
    """Measured live: IBKR answered warning 10349, "Order TIF was set to DAY
    based on order preset" - the parent carried no TIF and a Gateway-side
    preset chose one. `AlpacaAdapter` sets GTC on an entry carrying protective
    legs (M31b) and keeps DAY only for a bare entry. A TIF decided by whatever
    the Gateway happens to be configured with is not a decision this
    application made.
    """
    entry = Order(
        symbol="BHP.AX",
        side="buy",
        quantity=1,
        order_id="c",
        stop_price=25.0,
        take_profit_price=40.0,
    )

    assert to_ib_parent(entry).tif == "GTC"


def test_a_position_comes_back_in_the_apps_own_symbol_form() -> None:
    """M104, and the one that would have ended the first ASX session.

    Three of the four boundaries where an IBKR symbol enters the app were
    translated - fills (M97), resting stops (M98), adopted orders (M99). This
    one was not, and it is the one reconciliation reads:

        broker_positions = {pos.symbol: pos.quantity for pos in ...positions()}
        symbols = set(self._filled_quantities) | set(broker_positions)

    Tracked `{"BHP.AX": 10}` against broker `{"BHP": 10}` gives TWO divergences
    - BHP.AX reading (10, 0) and BHP reading (0, 10) - and a reconciliation
    mismatch TRIPS THE KILL SWITCH. The first fill would have halted the
    session, and the halt would have looked like a real discrepancy rather than
    a spelling difference.

    `verify_position_stops` would have failed the same way first: resting stops
    are keyed BHP.AX and positions were BHP, so every held position would have
    read as unprotected.
    """
    from ib_async import Contract
    from ib_async import Position as IBPosition

    from qat.data.broker.ib_translate import from_ib_position

    ib_position = IBPosition(
        account="DUQ200898",
        contract=Contract(symbol="BHP", secType="STK", exchange="ASX", currency="AUD"),
        position=10.0,
        avgCost=60.0,
    )

    assert from_ib_position(ib_position, market="ASX").symbol == "BHP.AX"


def test_a_us_position_is_unchanged() -> None:
    from ib_async import Contract
    from ib_async import Position as IBPosition

    from qat.data.broker.ib_translate import from_ib_position

    ib_position = IBPosition(
        account="DU1",
        contract=Contract(symbol="AAPL", secType="STK", exchange="SMART", currency="USD"),
        position=5.0,
        avgCost=200.0,
    )

    assert from_ib_position(ib_position, market="US").symbol == "AAPL"


async def test_positions_and_resting_stops_agree_on_the_symbol_form() -> None:
    """The invariant that actually matters, asserted across the two calls
    rather than inside either.

    `OMS.verify_position_stops` looks a position's symbol up in the resting-stop
    map, and `check_reconciliation` unions position symbols with tracked ones.
    Both are silent if the two halves spell the same holding differently - one
    reports every position unprotected, the other trips the kill switch.
    """
    from ib_async import Contract
    from ib_async import Position as IBPosition
    from ib_async.order import Order as IBOrder
    from ib_async.order import OrderStatus, Trade

    from qat.domain.bus import EventBus

    contract = Contract(symbol="BHP", secType="STK", exchange="ASX", currency="AUD")
    stop = IBOrder(
        orderId=1,
        clientId=1,
        permId=99,
        action="SELL",
        totalQuantity=10,
        orderType="STP",
        auxPrice=58.0,
        tif="GTC",
    )

    class _IB:
        def isConnected(self) -> bool:
            return True

        def positions(self, account: str = "") -> list[IBPosition]:
            return [IBPosition(account="DU1", contract=contract, position=10.0, avgCost=60.0)]

        async def reqAllOpenOrdersAsync(self) -> list[Trade]:
            return [
                Trade(
                    contract=contract,
                    order=stop,
                    orderStatus=OrderStatus(orderId=1, status="PreSubmitted", permId=99),
                )
            ]

    adapter = IBAdapter(
        _IB(), EventBus(), settings=Settings(_env_file=None, trading_mode="paper", market="ASX")
    )

    held = {p.symbol for p in await adapter.positions()}
    protected = set(await adapter.resting_stops())

    assert held == {"BHP.AX"}
    assert held == protected, (
        f"positions say {held} and resting stops say {protected} - the position would "
        f"read as unprotected and reconciliation would see two holdings, not one"
    )
