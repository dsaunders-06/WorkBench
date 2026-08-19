"""M95: IBKR must transmit a protective stop AS a stop, or refuse loudly.

Found 19 August while preparing Task 1's single write. `to_ib_order` branched
on `limit_price` alone:

    if order.limit_price is not None:
        return LimitOrder(...)
    return MarketOrder(...)

`OMS._propose_protective_order` builds the protective stop as `side="sell"`,
`order_type="stop"`, `stop_price=X`, **`limit_price=None`** - which fell
through to `MarketOrder("SELL", quantity)`. A protective stop for an
unprotected position became an immediate market sell OF THAT POSITION. The
`Order` dataclass warns about precisely this in the comment M31d added:
"submitting it as one would liquidate the position it was meant to protect."

`AlpacaAdapter` honours the distinction (`alpaca_adapter.py:521`). IBKR did
not, and no test noticed because `test_ib_translate.py` covers a market buy
and a limit sell and no stop at all. The capability audit could not see it
either: `place_order` is CORE and present, so a `hasattr` matrix reports the
adapter complete. The method existed; the TRANSLATION was wrong.

**The last test here is the general one.** Fixing the two known branches
leaves the next unrepresentable order shape failing exactly as silently. A
translator that cannot represent an order's intent must say so rather than
return something plausible.
"""

from __future__ import annotations

from typing import Any

import pytest

# Sibling module by bare name, NOT `tests.data.broker....`. pytest puts a test
# file's own directory on sys.path when it is not in a package, so this resolves
# under both `pytest` and `python -m pytest`. The dotted form only worked under
# the second, because that one also puts the CWD on sys.path - so the suite
# passed here and broke `invoke build`, which runs bare pytest.
from test_ib_order_identity import FakeIBClient

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.ib_adapter import IBAdapter
from qat.data.broker.ib_translate import UnrepresentableOrderError, to_ib_order
from qat.domain.bus import EventBus


def _protective_stop(**overrides: Any) -> Order:
    """Exactly what OMS._propose_protective_order builds (oms.py:1062)."""
    fields: dict[str, Any] = {
        "symbol": "BHP",
        "side": "sell",
        "quantity": 10,
        "order_id": "app-1",
        "status": "pending_signoff",
        "stop_price": 58.00,
        "order_type": "stop",
    }
    fields.update(overrides)
    return Order(**fields)


def test_a_protective_stop_is_not_transmitted_as_a_market_order() -> None:
    """THE defect. A market sell executes immediately at whatever the book
    offers - it does not protect the position, it closes it."""
    ib_order = to_ib_order(_protective_stop())

    assert ib_order.orderType != "MKT", (
        "the protective stop was transmitted as a MARKET order - this "
        "liquidates the position it was meant to protect"
    )
    assert ib_order.orderType == "STP"
    assert ib_order.auxPrice == 58.00
    assert ib_order.action == "SELL"
    assert ib_order.totalQuantity == 10


def test_a_protective_stop_is_gtc() -> None:
    """Alpaca's comment is emphatic and was written from a real loss: DAY
    killed every stop this system ever placed. On 31 July six positions filled
    with brackets attached, the take-profit legs expired at the close, the
    paired stops were cancelled with them, and about $36,000 sat through a
    three-day weekend with no protection at the broker at all. A stop whose
    purpose is to outlive the application must outlive the session."""
    assert to_ib_order(_protective_stop()).tif == "GTC"


def test_a_stop_with_no_stop_price_is_refused() -> None:
    """Mirrors alpaca_adapter.py:522. Silence is what made this dangerous;
    an unusable stop must not become a usable market order."""
    with pytest.raises(UnrepresentableOrderError, match="no stop price"):
        to_ib_order(_protective_stop(stop_price=None))


def test_an_entry_carrying_protective_legs_is_refused_not_stripped() -> None:
    """The boundary guard, and the reason it earns its place.

    An entry with `stop_price`/`take_profit_price` set is a bracket: the legs
    are the protection. Returning a bare MarketOrder places the entry and
    silently drops them, so a position the app believes is protected opens
    NAKED. Until Stage B can transmit the legs, refusing is the honest
    outcome - a rejected entry is recoverable, an unprotected position is the
    MNST failure.
    """
    entry = Order(
        symbol="BHP",
        side="buy",
        quantity=10,
        order_id="app-2",
        stop_price=58.00,
        take_profit_price=70.00,
    )
    assert entry.is_bracket

    with pytest.raises(UnrepresentableOrderError, match="protective legs"):
        to_ib_order(entry)


def test_a_plain_market_order_is_unchanged() -> None:
    order = Order(symbol="AAPL", side="buy", quantity=10, order_id="x")
    ib_order = to_ib_order(order)

    assert ib_order.orderType == "MKT"
    assert ib_order.totalQuantity == 10


def test_a_plain_limit_order_is_unchanged() -> None:
    order = Order(symbol="AAPL", side="sell", quantity=5, order_id="x", limit_price=123.45)
    ib_order = to_ib_order(order)

    assert ib_order.orderType == "LMT"
    assert ib_order.lmtPrice == 123.45


async def test_modify_order_repricing_a_stop_reaches_the_broker() -> None:
    """M39 re-prices a resting stop through a corporate action. `modify_order`
    propagated only `limit_price`, so a stop re-price was accepted, recorded
    on our own object, and never sent - the app would believe a stop had moved
    while the broker held the old level. The MNST shape exactly: an unadjusted
    stop through a split.
    """
    client = FakeIBClient(perm_ids=[9001])
    adapter = IBAdapter(
        client,
        EventBus(),
        settings=Settings(_env_file=None, trading_mode="paper"),
    )
    placed = await adapter.place_order(_protective_stop())

    await adapter.modify_order(placed.order_id, stop_price=61.50)

    resent = client.placed_orders[-1][1]
    assert resent.auxPrice == 61.50, (
        "the re-priced stop never reached the broker - the app believes the "
        "stop moved and the broker still holds the old level"
    )


def test_a_stop_carrying_a_take_profit_is_refused_not_silently_stripped() -> None:
    """The gap in Stage A as first shipped, and the guard's own principle
    applied to itself.

    `AlpacaAdapter` sends a stop that carries `take_profit_price` as ONE OCO,
    never two orders (M33): a resting stop and a resting limit for the same
    shares are not independent - if price runs to the target and later gaps
    back through the stop, both fill and a protected long becomes an
    accidental short. Returning a bare `StopOrder` here keeps the protection
    but silently discards the target, and `is_bracket` is False for
    `order_type="stop"` so the bracket guard never sees it.

    Less dangerous than transmitting a market sell. Still a translator
    quietly deciding half an instruction is close enough.
    """
    with pytest.raises(UnrepresentableOrderError, match="take-profit|OCO"):
        to_ib_order(_protective_stop(take_profit_price=70.00))


async def test_account_prefers_the_async_summary_inside_a_running_loop() -> None:
    """M102, found the first time the APP ran on IBKR rather than a script.

    `IB.accountSummary()` is a sync wrapper around `util.run`, which calls
    `loop.run_until_complete` - and the application runs inside an asyncio
    loop already. The real failure, verbatim:

        RuntimeError: This event loop is already running

    So `account()` - and `balances()`, which derives from it - could never have
    worked in the running app. **The suite could not catch it**, because every
    fake implements `accountSummary` as a plain method that returns a list;
    the fakes were wrong in exactly the direction production was, which is the
    same trap as M99's synchronous permId, twice in one session.
    """

    class LoopHostileIB:
        """Sync `accountSummary` raises the way ib_async's does inside a loop;
        the async form works. A client offering both must be asked the one
        that can answer."""

        def __init__(self) -> None:
            self.async_used = False

        def isConnected(self) -> bool:
            return True

        def accountSummary(self, account: str = "") -> list[Any]:
            raise RuntimeError("This event loop is already running")

        async def accountSummaryAsync(self, account: str = "") -> list[Any]:
            from ib_async import AccountValue

            self.async_used = True
            return [
                AccountValue(
                    account="DU1",
                    tag="NetLiquidation",
                    value="1000.0",
                    currency="AUD",
                    modelCode="",
                ),
                AccountValue(
                    account="DU1", tag="TotalCashValue", value="900.0", currency="AUD", modelCode=""
                ),
                AccountValue(
                    account="DU1", tag="BuyingPower", value="4000.0", currency="AUD", modelCode=""
                ),
            ]

        def positions(self, account: str = "") -> list[Any]:
            return []

    client = LoopHostileIB()
    adapter = IBAdapter(client, EventBus(), settings=Settings(_env_file=None, trading_mode="paper"))

    summary = await adapter.account()

    assert client.async_used, "used the sync form, which cannot run inside the app's loop"
    assert summary.net_liquidation == 1000.0
    assert summary.cash == 900.0
