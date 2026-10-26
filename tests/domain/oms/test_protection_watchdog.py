"""A missing stop may be restored only after a complete, unambiguous broker read."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from qat.data.broker.adapter import Position, RestingOrder
from qat.domain.oms.protection_watchdog import (
    ApprovedStopLeg,
    approved_entry_plan,
    assess_protection,
    corporate_action_warnings,
)

STOP = RestingOrder(
    "BHP.AX",
    "999",
    "sell",
    "STP",
    10,
    "Submitted",
    stop_price=50.0,
    perm_id=999,
    broker_order_id=88,
    order_ref="qat-stop-ref",
    account="DU_TEST",
    con_id=123,
    tif="GTC",
)
HELD = Position("BHP.AX", 10, 60, qat_holding=True)


def _assess(*orders: RestingOrder, position: Position = HELD, pending: bool = False):
    return assess_protection(
        position,
        list(orders),
        approved_stop_price=50.0,
        owns_order=lambda order: order.order_ref == "qat-stop-ref" and order.perm_id == 999,
        pending_identity=pending,
    )


def test_exact_working_stop_with_permid_and_orderref_is_protected() -> None:
    assert _assess(STOP).state == "protected"


def test_confirmed_empty_book_allows_original_stop_restoration() -> None:
    assert _assess().state == "restore"


def test_pending_cancel_never_allows_duplicate_restoration() -> None:
    assert _assess(replace(STOP, status="PendingCancel")).state == "wait"


def test_day_stop_is_not_accepted_as_overnight_protection() -> None:
    assert _assess(replace(STOP, tif="DAY")).state == "wait"


def test_duplicate_stops_never_allow_restoration() -> None:
    assert _assess(STOP, replace(STOP, order_id="1000", perm_id=1000)).state == "wait"


def test_matching_stop_and_owned_oca_target_are_protected() -> None:
    stop = replace(STOP, oca_group="BHP-OCA", oca_type=1)
    target = RestingOrder(
        "BHP.AX",
        "1000",
        "sell",
        "LMT",
        10,
        "Submitted",
        oca_group="BHP-OCA",
        oca_type=1,
        limit_price=70,
        perm_id=1000,
        order_ref="qat-target-ref",
        tif="GTC",
    )
    result = assess_protection(
        HELD,
        [stop, target],
        approved_stop_price=50.0,
        owns_order=lambda order: bool(order.order_ref and order.perm_id),
    )
    assert result.state == "protected"
    assert (
        assess_protection(
            HELD,
            [replace(stop, oca_type=3), target],
            approved_stop_price=50.0,
            owns_order=lambda order: bool(order.order_ref and order.perm_id),
        ).state
        == "wait"
    )
    assert (
        assess_protection(
            HELD,
            [replace(target, status="PendingCancel")],
            approved_stop_price=50.0,
            owns_order=lambda order: True,
        ).state
        == "wait"
    )


def test_unresolved_identity_never_allows_restoration() -> None:
    assert _assess(pending=True).state == "wait"
    assert _assess(replace(STOP, order_ref="")).state == "wait"


def test_manually_managed_position_is_not_restored_by_qat() -> None:
    assert _assess(position=replace(HELD, qat_holding=False)).state == "manual"


@pytest.mark.parametrize(
    "order",
    [
        replace(STOP, quantity=9),
        replace(STOP, stop_price=49.9),
        replace(STOP, status="ApiPending"),
        RestingOrder("BHP.AX", "target", "sell", "LMT", 10, "Submitted", limit_price=70),
    ],
)
def test_ambiguous_or_wrong_broker_order_blocks_restoration(order: RestingOrder) -> None:
    assert _assess(order).state == "wait"


def test_missing_plan_refuses_restoration() -> None:
    result = assess_protection(HELD, [], approved_stop_price=None, owns_order=lambda _: False)
    assert result.state == "wait"


def test_two_approved_stops_protect_only_their_own_quantities() -> None:
    banked = replace(STOP, quantity=5, total_quantity=5, oca_group="BANKED", oca_type=1)
    runner = replace(
        STOP,
        order_id="1000",
        perm_id=1000,
        order_ref="runner-ref",
        quantity=5,
        total_quantity=5,
        oca_group=None,
    )
    legs = (
        ApprovedStopLeg(
            "banked",
            5,
            50,
            order_ref="qat-stop-ref",
            perm_id=999,
            oca_group="BANKED",
            target_order_ref="target-ref",
            target_perm_id=1003,
            target_price=70,
        ),
        ApprovedStopLeg("runner", 5, 50, order_ref="runner-ref", perm_id=1000),
    )

    def owner(order: RestingOrder) -> bool:
        return bool(order.order_ref and order.perm_id)

    result = assess_protection(HELD, [banked, runner], approved_legs=legs, owns_order=owner)
    assert result.state == "protected"
    assert (
        assess_protection(HELD, [banked], approved_legs=legs, owns_order=owner).missing_role
        == "runner"
    )
    assert (
        assess_protection(HELD, [runner], approved_legs=legs, owns_order=owner).missing_role
        == "banked"
    )
    # Two independently confirmed missing legs are restored one at a time.
    # An empty broker book must not leave the whole holding unprotected.
    both_missing = assess_protection(HELD, [], approved_legs=legs, owns_order=owner)
    assert both_missing.state == "restore"
    assert both_missing.missing_role == "banked"


def test_two_leg_plan_fails_closed_on_excess_or_ambiguous_stops() -> None:
    banked = replace(STOP, quantity=5, total_quantity=5, oca_group="BANKED", oca_type=1)
    runner = replace(STOP, order_id="1000", perm_id=1000, order_ref="runner-ref", quantity=5)
    legs = (
        ApprovedStopLeg(
            "banked",
            5,
            50,
            order_ref="qat-stop-ref",
            perm_id=999,
            oca_group="BANKED",
            target_order_ref="target-ref",
            target_perm_id=1003,
            target_price=70,
        ),
        ApprovedStopLeg("runner", 5, 50, order_ref="runner-ref", perm_id=1000),
    )

    def owner(order: RestingOrder) -> bool:
        return bool(order.order_ref and order.perm_id)

    assert (
        assess_protection(
            HELD, [banked, replace(runner, quantity=6)], approved_legs=legs, owns_order=owner
        ).state
        == "wait"
    )
    assert (
        assess_protection(
            HELD,
            [banked, replace(runner, status="PendingCancel")],
            approved_legs=legs,
            owns_order=owner,
        ).state
        == "wait"
    )
    assert (
        assess_protection(
            HELD,
            [banked, replace(runner, order_ref="unknown")],
            approved_legs=legs,
            owns_order=owner,
        ).state
        == "wait"
    )
    assert (
        assess_protection(
            HELD, [banked], approved_legs=(*legs, ApprovedStopLeg("extra", 1, 50)), owns_order=owner
        ).state
        == "wait"
    )


def test_missing_banked_stop_can_restore_only_with_its_approved_oca_target() -> None:
    runner = replace(STOP, order_ref="runner-ref", perm_id=1000, order_id="1000", quantity=5)
    target = RestingOrder(
        "BHP.AX",
        "1001",
        "sell",
        "LMT",
        5,
        "Submitted",
        oca_group="BANKED",
        oca_type=1,
        limit_price=70,
        perm_id=1001,
        order_ref="target-ref",
        tif="GTC",
    )
    legs = (
        ApprovedStopLeg(
            "banked",
            5,
            50,
            order_ref="banked-ref",
            perm_id=999,
            oca_group="BANKED",
            target_order_ref="target-ref",
            target_perm_id=1001,
            target_price=70,
        ),
        ApprovedStopLeg("runner", 5, 50, order_ref="runner-ref", perm_id=1000),
    )
    assert (
        assess_protection(
            HELD, [runner, target], approved_legs=legs, owns_order=lambda _: True
        ).missing_role
        == "banked"
    )
    assert (
        assess_protection(
            HELD,
            [runner, replace(target, status="PendingCancel")],
            approved_legs=legs,
            owns_order=lambda _: True,
        ).state
        == "wait"
    )


def test_restoration_requires_durable_entry_and_named_original_signoff(tmp_path) -> None:
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "BHP.AX": {
                    "order_id": "entry-1",
                    "quantity": 10,
                    "stop_price": 50.0,
                    "opened_at": "2026-10-20T10:30:00+11:00",
                }
            }
        ),
        encoding="utf-8",
    )
    signed = [{"order_id": "entry-1", "outcome": "signed_off", "entity_name": "DS"}]
    plan = approved_entry_plan(tmp_path, signed, HELD, operator_name="DS")
    assert plan is not None
    assert (plan.stop_price, plan.order_id, plan.operator) == (50.0, "entry-1", "DS")
    assert approved_entry_plan(tmp_path, [], HELD, operator_name="DS") is None
    assert approved_entry_plan(tmp_path, signed, HELD, operator_name="Other") is None


def test_signed_two_leg_entry_plan_must_cover_exact_holding(tmp_path) -> None:
    entry = {
        "order_id": "entry-1",
        "quantity": 10,
        "stop_price": 50,
        "opened_at": "2026-10-20T10:30:00+11:00",
    }
    legs = [
        {
            "role": "banked",
            "quantity": 5,
            "stop_price": 50,
            "order_ref": "banked-ref",
            "perm_id": 999,
            "oca_group": "BANKED",
            "target_order_ref": "target-ref",
            "target_perm_id": 1003,
            "target_price": 70,
        },
        {
            "role": "runner",
            "quantity": 5,
            "stop_price": 50,
            "order_ref": "runner-ref",
            "perm_id": 1000,
        },
    ]
    path = tmp_path / "open_position_entries.json"
    path.write_text(json.dumps({"BHP.AX": entry}), encoding="utf-8")
    leg_path = tmp_path / "approved_protection_legs.json"
    leg_path.write_text(
        json.dumps({"BHP.AX": {"entry_order_id": "entry-1", "legs": legs}}),
        encoding="utf-8",
    )
    signed = [{"order_id": "entry-1", "outcome": "signed_off", "entity_name": "DS"}]
    plan = approved_entry_plan(tmp_path, signed, HELD, operator_name="DS")
    assert plan is not None and tuple(leg.role for leg in plan.legs) == ("banked", "runner")
    legs[1]["quantity"] = 6
    leg_path.write_text(
        json.dumps({"BHP.AX": {"entry_order_id": "entry-1", "legs": legs}}),
        encoding="utf-8",
    )
    assert approved_entry_plan(tmp_path, signed, HELD, operator_name="DS") is None
    legs[1]["quantity"] = 5
    leg_path.write_text(
        json.dumps({"BHP.AX": {"entry_order_id": "older-entry", "legs": legs}}),
        encoding="utf-8",
    )
    assert approved_entry_plan(tmp_path, signed, HELD, operator_name="DS") is None


def test_corporate_action_warns_for_held_symbol_before_next_session() -> None:
    events = (
        SimpleNamespace(
            symbol="BHP.AX",
            ex_session=date(2026, 10, 26),
            split_ratio=Fraction(1, 1),
            dividend=Decimal("0.50"),
        ),
        SimpleNamespace(
            symbol="ANZ.AX",
            ex_session=date(2026, 10, 26),
            split_ratio=Fraction(2, 1),
            dividend=Decimal("0"),
        ),
    )
    # Friday 23 October: Monday 26 October is the next ASX session.
    warning = corporate_action_warnings(SimpleNamespace(events=events), [HELD], date(2026, 10, 23))
    assert len(warning) == 1
    assert "BHP.AX" in warning[0]
    assert corporate_action_warnings(SimpleNamespace(events=events), [], date(2026, 10, 23)) == []
