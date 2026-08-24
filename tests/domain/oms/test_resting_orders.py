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


def test_unequal_quantities_in_oca_group_uses_max():
    """Within one OCA group, only the largest leg can fire, so risk is the MAX.

    A partial fill on one leg (e.g., 3,051 filled down to 1,200 remaining)
    leaves its sibling at full size (3,051). Only one leg can ever fire, so
    the worst-case resting risk is the larger leg, not the sum.
    """
    orders = [
        _order(1, qty=3051.0, oca="OCA-1"),
        _order(2, qty=1200.0, oca="OCA-1"),
    ]
    found = unjustified_resting_risk(orders, [_pos("TNE.AX", 1200.0)])
    assert len(found) == 1
    assert found[0].resting == 3051.0
    assert found[0].justified == 1200.0
    assert found[0].excess == 1851.0


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
