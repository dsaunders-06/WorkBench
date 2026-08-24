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
