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

import pytest

from qat.data.broker.ib_adapter import IBAdapter
from qat.data.broker.ib_translate import from_ib_open_order


def _trade(**kw: object) -> SimpleNamespace:
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


def test_a_take_profit_limit_leg_is_kept() -> None:
    """The leg `from_ib_resting_stop` throws away."""
    resting = from_ib_open_order(
        _trade(order_type="LMT", aux_price=0.0, lmt_price=36.86, perm_id=222), market="ASX"  # type: ignore[arg-type]
    )
    assert resting is not None
    assert resting.order_type == "LMT"
    assert resting.limit_price == 36.86
    assert resting.stop_price is None


def test_a_done_order_is_still_returned() -> None:
    """No status filter here. Consumers decide what 'working' means."""
    resting = from_ib_open_order(_trade(status="Cancelled"), market="ASX")  # type: ignore[arg-type]
    assert resting is not None
    assert resting.status == "Cancelled"


def test_quantity_is_remaining_not_total() -> None:
    """A half-filled stop carries half the risk."""
    resting = from_ib_open_order(_trade(total_quantity=100.0, remaining=40.0), market="ASX")  # type: ignore[arg-type]
    assert resting.quantity == 40.0


def test_total_quantity_is_carried_too() -> None:
    """I7, final review: the fallback for the case where `remaining` is 0.0
    only because `orderStatus` has not populated it yet - `total_quantity`
    has to be on the record for `unjustified_resting_risk` to fall back to."""
    resting = from_ib_open_order(_trade(total_quantity=3051.0, remaining=0.0), market="ASX")  # type: ignore[arg-type]
    assert resting.quantity == 0.0
    assert resting.total_quantity == 3051.0


def test_the_symbol_is_translated() -> None:
    """M104 - every IBKR boundary translates."""
    resting = from_ib_open_order(_trade(symbol="TNE"), market="ASX")  # type: ignore[arg-type]
    assert resting.symbol == "TNE.AX"


def test_group_keys_are_carried_raw() -> None:
    resting = from_ib_open_order(
        _trade(oca_group="OCA-7", parent_perm_id=999, client_id=3), market="ASX"  # type: ignore[arg-type]
    )
    assert resting.oca_group == "OCA-7"
    assert resting.parent_perm_id == 999
    assert resting.owner_client_id == 3


def test_absent_group_markers_become_none() -> None:
    """IBKR sends "" and 0, not None, and `solo:` fallback keys on falsiness."""
    resting = from_ib_open_order(_trade(oca_group="", parent_perm_id=0), market="ASX")  # type: ignore[arg-type]
    assert resting.oca_group is None
    assert resting.parent_perm_id is None


class _FakeIB:
    def __init__(self, trades):
        self._trades = trades

    async def reqAllOpenOrdersAsync(self):  # noqa: N802 - mirrors ib_async
        return self._trades


def _settings():
    """A REAL Settings, not a SimpleNamespace stub.

    The stub carried only `market` and broke the moment the adapter needed
    `ibkr_call_timeout_seconds` (item 34's timeout guard). A hand-built stand-in
    for a config object drifts from it silently; the real thing cannot.
    `_env_file=None` keeps %LOCALAPPDATA%'s .env out of it.
    """
    from qat.config import Settings

    return Settings(_env_file=None, market="ASX")  # type: ignore[arg-type]


def _adapter(trades, monkeypatch):
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = _FakeIB(trades)
    adapter.settings = _settings()
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
async def test_resting_stop_orders_now_sees_every_working_state(monkeypatch):
    """⚠️ REWRITTEN 28 August (item 31). This asserted the OPPOSITE - that
    `ApiPending` stayed invisible - because widening moves `_position_stops`,
    a sizing input, and that had to be a change of its own rather than a side
    effect of Task 2.

    It is now that change. A stop in `ApiPending` IS protection, and reading it
    as none made `verify_position_stops` log POSITION UNPROTECTED on a protected
    position.

    ⚠️ It LOOSENS a rail - a position whose stop was ignored counted its full
    value against the aggregate cap and now counts only to the stop. Measured
    against the live book before shipping: 20 open orders, 10 Submitted and 10
    PreSubmitted, ZERO in either added state, so the change could not move the
    number on that book.
    """
    trades = [
        _trade(symbol="TNE", perm_id=1, order_type="STP", status="ApiPending", aux_price=30.69),
        _trade(symbol="DXS", perm_id=2, order_type="STP", status="PreSubmitted", aux_price=7.10),
    ]
    got = await _adapter(trades, monkeypatch).resting_stop_orders()
    assert set(got) == {"TNE.AX", "DXS.AX"}, "a stop in ApiPending is protection"


@pytest.mark.asyncio
async def test_a_take_profit_leg_is_not_a_resting_stop(monkeypatch):
    trades = [_trade(perm_id=2, order_type="LMT", aux_price=0.0, lmt_price=36.86)]
    assert await _adapter(trades, monkeypatch).resting_stop_orders() == {}


@pytest.mark.asyncio
async def test_unavailable_order_query_is_not_an_empty_book(monkeypatch):
    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = SimpleNamespace()
    adapter.settings = _settings()
    with pytest.raises(RuntimeError, match="could not verify"):
        await adapter.open_orders()


@pytest.mark.asyncio
async def test_a_successful_empty_order_query_remains_empty(monkeypatch):
    assert await _adapter([], monkeypatch).open_orders() == []
