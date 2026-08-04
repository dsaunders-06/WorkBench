"""AlpacaAdapter (spec M12), driven by a fake client.

Same approach as test_ib_adapter.py: the adapter's own logic (field
translation, status mapping, the live-trading gate) is what is worth testing,
and it is tested without API keys or network access. Nothing here proves a
real Alpaca round-trip works - see the README for how to check that yourself.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.data.broker.alpaca_adapter import (
    AlpacaAdapter,
    AlpacaLiveTradingNotConfirmedError,
    _map_status,
)


class FakeAccount:
    equity = "50000.25"
    cash = "12345.67"
    buying_power = "24691.34"


class FakePosition:
    symbol = "AAPL"
    qty = "10"
    avg_entry_price = "190.50"


class FakeAlpacaOrder:
    id = "alpaca-order-1"
    symbol = "AAPL"
    qty = "5"
    side = "OrderSide.BUY"
    status = "accepted"
    filled_avg_price = None


class FakeClient:
    def __init__(self) -> None:
        self.submitted: list[object] = []
        self.cancelled: list[str] = []
        self.orders: list[object] = []
        self.order_filters: list[object] = []
        # resting_stops bounds its query by the symbols actually held (M47),
        # so what the account holds is now part of the fixture.
        self.positions: list[object] = [FakePosition()]

    def get_account(self) -> FakeAccount:
        return FakeAccount()

    def get_all_positions(self) -> list[object]:
        return self.positions

    def submit_order(self, order_data: object) -> FakeAlpacaOrder:
        self.submitted.append(order_data)
        return FakeAlpacaOrder()

    def get_orders(self, filter: object = None) -> list[object]:
        self.order_filters.append(filter)
        return self.orders

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def get_order_by_id(self, order_id: str) -> FakeAlpacaOrder:
        return FakeAlpacaOrder()


def _adapter(**settings_kwargs: object) -> tuple[AlpacaAdapter, FakeClient]:
    client = FakeClient()
    settings = Settings(_env_file=None, **settings_kwargs)  # type: ignore[arg-type]
    return AlpacaAdapter(client=client, settings=settings), client


async def test_account_translates_alpacas_string_fields():
    adapter, _client = _adapter()

    account = await adapter.account()

    assert account.net_liquidation == 50000.25
    assert account.cash == 12345.67
    assert account.buying_power == 24691.34


async def test_positions_are_translated():
    adapter, _client = _adapter()

    positions = await adapter.positions()

    assert positions[0].symbol == "AAPL"
    assert positions[0].quantity == 10.0
    assert positions[0].avg_price == 190.50


async def test_place_order_submits_and_adopts_the_broker_order_id():
    adapter, client = _adapter()
    order = Order(symbol="AAPL", side="buy", quantity=5, order_id="local-id")

    result = await adapter.place_order(order)

    assert len(client.submitted) == 1
    assert result.order_id == "alpaca-order-1"
    # An accepted-but-unfilled order must not be reported as filled.
    assert result.status == "transmitted"


async def test_cancel_order_calls_through_and_returns_the_order():
    adapter, client = _adapter()

    result = await adapter.cancel_order("alpaca-order-1")

    assert client.cancelled == ["alpaca-order-1"]
    assert result.symbol == "AAPL"


def test_defaults_to_the_paper_endpoint():
    adapter, _client = _adapter()
    assert adapter.paper is True


def test_live_mode_requires_explicit_confirmation():
    with pytest.raises(AlpacaLiveTradingNotConfirmedError):
        AlpacaAdapter(client=FakeClient(), settings=Settings(_env_file=None, trading_mode="live"))


def test_live_mode_with_confirmation_targets_the_live_endpoint():
    adapter = AlpacaAdapter(
        client=FakeClient(),
        settings=Settings(_env_file=None, trading_mode="live"),
        live_trading_confirmed=True,
    )
    assert adapter.paper is False


@pytest.mark.parametrize(
    ("alpaca_status", "expected"),
    [
        ("filled", "filled"),
        ("accepted", "transmitted"),
        ("partially_filled", "transmitted"),
        ("canceled", "cancelled"),
        ("rejected", "rejected"),
        ("something_new_alpaca_added", "transmitted"),
    ],
)
def test_status_mapping(alpaca_status, expected):
    assert _map_status(alpaca_status) == expected


async def test_market_data_is_explicitly_unsupported():
    """This adapter is execution + account state only; pretending otherwise
    would silently produce a broken price feed."""
    adapter, _client = _adapter()

    with pytest.raises(NotImplementedError):
        await adapter.get_market_data("AAPL")


def test_a_bracketed_entry_is_gtc_so_its_stop_outlives_the_session():
    """DAY killed every stop this system ever placed.

    On 31 July six positions filled with brackets attached. At the close the
    take-profit legs EXPIRED, Alpaca cancelled the paired stops with them as
    OCO does, and six positions sat through a three-day weekend with no
    protection at the broker. A stop whose purpose is to outlive the
    application must also outlive the session.
    """
    client = FakeClient()
    adapter = AlpacaAdapter(client=client, settings=Settings(_env_file=None))
    order = Order(
        order_id="o1",
        symbol="AAPL",
        side="buy",
        quantity=10.0,
        status="pending_signoff",
        reference_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
    )

    asyncio.run(adapter.place_order(order))

    request = client.submitted[-1]
    assert str(request.time_in_force).endswith("GTC")
    assert request.stop_loss is not None, "the protective leg must be attached"


def test_a_plain_entry_stays_day():
    """An unfilled market order carrying no protection should not linger into
    the next session at a price nobody chose."""
    client = FakeClient()
    adapter = AlpacaAdapter(client=client, settings=Settings(_env_file=None))
    order = Order(
        order_id="o2",
        symbol="AAPL",
        side="sell",
        quantity=10.0,
        status="pending_signoff",
        reference_price=100.0,
    )

    asyncio.run(adapter.place_order(order))

    assert str(client.submitted[-1].time_in_force).endswith("DAY")


@pytest.mark.asyncio
async def test_a_protective_stop_is_submitted_as_a_stop_order_gtc():
    """The order that repairs an unprotected position (M31d). Submitted as a
    market sell it would liquidate the position instead of protecting it, and
    submitted DAY it would expire at the close - which is the bug it exists to
    repair, reintroduced by the repair."""
    from alpaca.trading.enums import TimeInForce
    from alpaca.trading.requests import StopOrderRequest

    adapter, client = _adapter()

    await adapter.place_order(
        Order(
            symbol="AAPL",
            side="sell",
            quantity=50.0,
            order_id="local-1",
            stop_price=95.004,
            order_type="stop",
        )
    )

    request = client.submitted[0]
    assert isinstance(request, StopOrderRequest)
    assert request.time_in_force == TimeInForce.GTC
    assert request.stop_price == pytest.approx(95.0)  # rounded to the cent


@pytest.mark.asyncio
async def test_a_stop_order_without_a_stop_price_is_refused_before_submission():
    adapter, client = _adapter()

    with pytest.raises(ValueError):
        await adapter.place_order(
            Order(symbol="AAPL", side="sell", quantity=50.0, order_id="x", order_type="stop")
        )

    assert client.submitted == []


@pytest.mark.asyncio
async def test_a_stop_with_a_target_is_submitted_as_a_single_oco():
    """Two independent resting orders for the same shares can both fill - the
    price runs to the target, later gaps back through the stop - and the
    account sells twice what it holds. OCO makes them mutually exclusive at
    the broker, which is the property the expired bracket used to provide."""
    from alpaca.trading.enums import OrderClass, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest

    adapter, client = _adapter()

    await adapter.place_order(
        Order(
            symbol="AAPL",
            side="sell",
            quantity=50.0,
            order_id="local-1",
            stop_price=95.0,
            take_profit_price=130.0,
            order_type="stop",
        )
    )

    assert len(client.submitted) == 1
    request = client.submitted[0]
    assert isinstance(request, LimitOrderRequest)
    assert request.order_class == OrderClass.OCO
    assert request.time_in_force == TimeInForce.GTC
    assert request.stop_loss.stop_price == pytest.approx(95.0)
    assert request.take_profit.limit_price == pytest.approx(130.0)


class _OcoLeg:
    """The stop leg of an OCO: status `held`, nested under its partner."""

    symbol = "CRWD"
    side = "sell"
    order_type = "stop"
    status = "held"
    stop_price = "163.32"
    legs = None


class _OcoParent:
    symbol = "CRWD"
    side = "sell"
    order_type = "limit"
    status = "accepted"
    stop_price = None
    limit_price = "235.20"
    legs = [_OcoLeg()]


@pytest.mark.asyncio
async def test_an_oco_stop_leg_counts_as_resting_protection():
    """The 1 August miss. An OCO's stop leg sits at `held` and is returned as a
    CHILD of its partner, so a flat scan for open stop orders saw nothing - and
    the app read a CRWD position carrying a perfectly good OCO as unprotected
    and proposed a second one. Signed, that is 32 shares of resting sell orders
    against a 16-share position."""
    adapter, client = _adapter()
    client.orders = [_OcoParent()]

    assert await adapter.resting_stops() == {"CRWD": pytest.approx(163.32)}


@pytest.mark.asyncio
async def test_the_orders_query_asks_for_nested_legs():
    """Without nested=True the legs never arrive to be scanned."""
    adapter, client = _adapter()
    client.orders = []

    await adapter.resting_stops()

    assert client.order_filters[-1].nested is True


# --- M47: a live leg under a filled parent -----------------------------------


class _BracketStopLeg:
    """A bracket's stop leg: still `held`, under an entry that has FILLED."""

    symbol = "AAPL"
    side = "sell"
    order_type = "stop"
    status = "held"
    stop_price = "180.00"
    legs = None


class _CancelledStopLeg:
    symbol = "AAPL"
    side = "sell"
    order_type = "stop"
    status = "canceled"
    stop_price = "150.00"
    legs = None


class _FilledEntry:
    symbol = "AAPL"
    side = "buy"
    order_type = "market"
    status = "filled"
    stop_price = None
    submitted_at = datetime(2026, 2, 1, tzinfo=UTC)
    legs = [_BracketStopLeg()]


class _OldCancelledBracket:
    symbol = "AAPL"
    side = "buy"
    order_type = "market"
    status = "filled"
    stop_price = None
    submitted_at = datetime(2026, 1, 1, tzinfo=UTC)
    legs = [_CancelledStopLeg()]


@pytest.mark.asyncio
async def test_a_live_leg_under_a_filled_parent_is_seen():
    """The 4 August failure. `status=open` excludes a filled parent and takes
    its still-`held` stop leg out of the result with it, so four bracketed
    positions read as unprotected the moment their entries filled - and the app
    proposed four duplicate OCOs, which Alpaca refused for insufficient
    shares."""
    adapter, client = _adapter()
    client.orders = [_FilledEntry()]

    assert await adapter.resting_stops() == {"AAPL": pytest.approx(180.0)}


@pytest.mark.asyncio
async def test_a_dead_leg_is_not_read_as_protection():
    """The other half of the fix, and the more dangerous direction. Under
    status=all the query returns every order the account ever placed; without a
    check on each leg's OWN status a cancelled stop from a closed trade would
    report as live protection, and a position believed protected is never
    repaired."""
    adapter, client = _adapter()
    client.orders = [_OldCancelledBracket()]

    assert await adapter.resting_stops() == {}


@pytest.mark.asyncio
async def test_the_scan_is_bounded_by_the_symbols_actually_held():
    """Bounding by date would reintroduce the same invisibility for an older
    entry. Symbol membership does not age, so it is the axis that cannot."""
    adapter, client = _adapter()
    client.orders = []

    await adapter.resting_stops()

    request = client.order_filters[-1]
    assert request.symbols == ["AAPL"]  # FakeClient holds exactly one position
    assert str(request.status).lower().endswith("all")
    assert request.nested is True
    assert str(request.direction).lower().endswith("desc")


@pytest.mark.asyncio
async def test_nothing_held_asks_the_broker_nothing():
    """An empty symbols filter is dropped from the request, which would return
    the whole account - the unbounded query this change exists to avoid."""
    adapter, client = _adapter()
    client.positions = []

    assert await adapter.resting_stops() == {}
    assert client.order_filters == []


class _PagingClient(FakeClient):
    """Serves one symbol's history in pages, so the deep scan has something to
    walk. The protective leg is deliberately on the LAST page."""

    def __init__(self, pages: list[list[object]]) -> None:
        super().__init__()
        self.pages = pages
        self.symbol_queries: list[list[str]] = []

    def get_orders(self, filter: object = None) -> list[object]:
        self.order_filters.append(filter)
        symbols = list(getattr(filter, "symbols", None) or [])
        self.symbol_queries.append(symbols)
        until = getattr(filter, "until", None)
        if until is None:
            return self.pages[0]
        for index, page in enumerate(self.pages[:-1]):
            if any(getattr(o, "submitted_at", None) == until for o in page):
                return self.pages[index + 1]
        return []


@pytest.mark.asyncio
async def test_a_symbol_the_broad_scan_misses_is_looked_up_before_it_reads_naked(monkeypatch):
    """ "No protection found" must mean we went and looked, not that the page
    ran out. Every held position's live leg was the most recent order for its
    symbol when this was measured - the deep scan is what stops that
    measurement from becoming an assumption."""
    from qat.data.broker import alpaca_adapter as module

    # A page is "full" at 2 here so the walk is testable without 500 fakes.
    monkeypatch.setattr(module, "_DEEP_SCAN_LIMIT", 2)

    first = [_OldCancelledBracket(), _OldCancelledBracket()]
    last = [_FilledEntry()]
    client = _PagingClient(pages=[first, last])
    settings = Settings(_env_file=None)  # type: ignore[arg-type]
    adapter = AlpacaAdapter(client=client, settings=settings)

    assert await adapter.resting_stops() == {"AAPL": pytest.approx(180.0)}
    # Broad scan first, then the single unresolved symbol on its own.
    assert client.symbol_queries[0] == ["AAPL"]
    assert len(client.symbol_queries) > 1


# --- M48: the fill of an order submitted long ago ----------------------------


_LONG_AGO = datetime(2026, 2, 1, tzinfo=UTC)
_JUST_NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_WINDOW_OPENED = datetime(2026, 8, 5, 11, 55, tzinfo=UTC)


class _StopLegFilledJustNow:
    id = "leg-1"
    symbol = "AAPL"
    side = "sell"
    status = "filled"
    stop_price = "180.00"
    filled_qty = "10"
    filled_avg_price = "179.55"
    filled_at = _JUST_NOW
    submitted_at = _LONG_AGO
    legs = None


class _EntryFilledLongAgo:
    id = "parent-1"
    symbol = "AAPL"
    side = "buy"
    status = "filled"
    stop_price = None
    filled_qty = "10"
    filled_avg_price = "150.00"
    filled_at = _LONG_AGO
    submitted_at = _LONG_AGO
    legs = [_StopLegFilledJustNow()]


@pytest.mark.asyncio
async def test_a_leg_that_fills_today_is_seen_though_its_parent_is_months_old():
    """The defect M48 fixes. The query asked Alpaca for `after=since` with a
    five-minute cursor, and `after=` filters on SUBMITTED_AT - so a protective
    order placed when the position opened and firing today fell outside the
    window every time. On the first stop-out that loses the closed trade and
    trips the kill-switch, which is M34 defeated in the one case it exists
    for."""
    adapter, client = _adapter()
    client.orders = [_EntryFilledLongAgo()]

    fills = await adapter.recent_fills(_WINDOW_OPENED, symbols=["AAPL"])

    assert [f.order_id for f in fills] == ["leg-1"]
    assert fills[0].side == "sell"
    assert fills[0].quantity == 10.0
    assert fills[0].price == pytest.approx(179.55)


@pytest.mark.asyncio
async def test_the_window_is_applied_to_fill_time_not_submission_time():
    """The entry filled months ago and must not be absorbed again. Every order
    for a tracked symbol now comes back, so this local check is the only thing
    standing between one poll and re-absorbing the account's whole history."""
    adapter, client = _adapter()
    client.orders = [_EntryFilledLongAgo()]

    fills = await adapter.recent_fills(_WINDOW_OPENED, symbols=["AAPL"])

    assert "parent-1" not in [f.order_id for f in fills]

    # And nothing at all once the window has moved past the leg's fill.
    assert await adapter.recent_fills(_JUST_NOW, symbols=["AAPL"]) == []


@pytest.mark.asyncio
async def test_the_fill_query_is_bounded_by_symbol_and_not_by_submission_date():
    adapter, client = _adapter()
    client.orders = []

    await adapter.recent_fills(_WINDOW_OPENED, symbols=["AAPL", "MSFT"])

    request = client.order_filters[-1]
    assert request.symbols == ["AAPL", "MSFT"]
    assert request.after is None, "after= means submitted_at, which is not the question"
    assert str(request.status).lower().endswith("all")
    assert request.nested is True


@pytest.mark.asyncio
async def test_tracking_nothing_asks_the_broker_nothing():
    adapter, client = _adapter()

    assert await adapter.recent_fills(_WINDOW_OPENED, symbols=[]) == []
    assert client.order_filters == []


@pytest.mark.asyncio
async def test_the_deep_scan_stops_rather_than_walking_forever(monkeypatch, caplog):
    """A capped walk that gives up reports UNPROTECTED, which proposes a
    replacement. Assuming protection exists because we stopped looking is the
    one answer that can leave a position quietly naked."""
    from qat.data.broker import alpaca_adapter as module

    monkeypatch.setattr(module, "_DEEP_SCAN_LIMIT", 1)
    monkeypatch.setattr(module, "_DEEP_SCAN_MAX_PAGES", 2)

    class _EndlessClient(FakeClient):
        def get_orders(self, filter: object = None) -> list[object]:
            self.order_filters.append(filter)
            return [_OldCancelledBracket()]

    client = _EndlessClient()
    settings = Settings(_env_file=None)  # type: ignore[arg-type]
    adapter = AlpacaAdapter(client=client, settings=settings)

    with caplog.at_level("WARNING"):
        assert await adapter.resting_stops() == {}
    assert "Gave up scanning AAPL" in caplog.text
