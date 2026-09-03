"""Error 383 arrived, was logged by ib_async, and reached nothing.

The adapter subscribes to no ib_async events by design - its docstring says
connection health is an active heartbeat instead, "simpler to reason about and
test". That decision is right and unaffected: it concerns connection health,
where polling gives the same answer. It does not extend to order rejections,
because there is no polling equivalent - Error 383 is delivered by `errorEvent`
or not at all.

⚠️ A second incident lives in this same file (Task 5 review). The FIRST cut of
this fix treated any order this process EVER placed, in any state, as
order-scoped - so routine broker lifecycle traffic (202 on every cancel,
including one IBKR issues itself when a bracket's OCA sibling is cancelled;
warning codes like 404 that leave the order live) HALTED trading, and a
filled order's status was silently overwritten by a stale late notice. The
tests below pin both halves of that fix: a DONE order stops being
order-scoped at all (`_order_for_req_id`), and the routine lifecycle codes
are enumerated as benign (`ib_errors.BENIGN_ORDER_ERROR_CODES`) rather than
falling through to HALT.
"""

from __future__ import annotations

import logging

import pytest


def test_a_benign_order_rejection_marks_the_order_rejected(adapter, order_on_the_wire):
    adapter._on_ib_error(order_on_the_wire.req_id, 383, "size exceeds the Size Limit of 500", None)

    assert adapter._orders[order_on_the_wire.app_id].status == "rejected"


def test_a_benign_rejection_does_not_halt(adapter, order_on_the_wire, published):
    adapter._on_ib_error(order_on_the_wire.req_id, 383, "size exceeds the Size Limit", None)

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_an_unknown_order_scoped_code_halts(adapter, order_on_the_wire, published):
    """⚠️ FAIL CLOSED."""
    adapter._on_ib_error(order_on_the_wire.req_id, 9999, "something nobody listed", None)

    assert adapter._orders[order_on_the_wire.app_id].status == "rejected"
    assert any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_an_error_matching_no_order_is_ignored(adapter, published, caplog):
    """⚠️ 2104 is a health notice. Halting on it would stop the system daily."""
    with caplog.at_level(logging.DEBUG):
        adapter._on_ib_error(999999, 2104, "Market data farm connection is OK", None)

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)
    # The IGNORE branch has to SAY so, not just decline to publish - a body
    # of `return` with nothing logged would pass the assertion above too.
    assert "matches no order" in caplog.text


def test_the_handler_never_raises_into_the_callback(adapter, order_on_the_wire, published):
    """ib_async calls this from its own event loop; an exception escaping here
    would surface inside the library, not in our stack.

    ⚠️ Drives a REAL failure through the body - a matched order whose
    `status` assignment raises - rather than the all-`None` malformed input
    the previous version of this test used. That input never reached
    anything that could throw: removing BOTH the isinstance guard in
    `_on_ib_error` AND its `except Exception` wrapper left it (and the other
    four tests in this file) passing, because `None` compares harmlessly
    false against every `orderId` and matches no order. This version was
    confirmed, by hand, to fail once `except Exception` is removed from
    `_on_ib_error` - the guard this test exists to pin.
    """

    class _ExplodingOrder:
        """Reads normally; writing `.status` blows up, like a broken
        downstream consumer or a corrupted `Order` would."""

        def __init__(self) -> None:
            self._status = "transmitted"

        @property
        def status(self) -> str:
            return self._status

        @status.setter
        def status(self, value: str) -> None:
            raise RuntimeError("simulated failure writing order status")

    adapter._orders[order_on_the_wire.app_id] = _ExplodingOrder()  # type: ignore[assignment]

    adapter._on_ib_error(order_on_the_wire.req_id, 383, "size exceeds the Size Limit", None)

    assert not any(
        type(e).__name__ == "KillSwitchEvent" for e in published
    ), "a handler failure must not itself masquerade as a halt-worthy rejection"


def test_a_benign_lifecycle_code_on_a_live_bracket_leg_does_not_halt(
    adapter, bracket_on_the_wire, published
):
    """⚠️ CRITICAL fix (b) + MINOR (bracket-leg matching, otherwise untested:
    deleting the `_ib_groups` loop in `_order_for_req_id` leaves every test in
    this file green). 202 is IBKR's literal cancel notice, sent even when
    nobody here asked for it: it fires the moment a bracket's OCA sibling is
    cancelled by the broker, against the CHILD's orderId - reachable only via
    `_ib_groups`, not the primary `_ib_orders` entry `_place_bracket`
    registers."""
    adapter._on_ib_error(bracket_on_the_wire.stop_req_id, 202, "Order Canceled - Reason:", None)

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)
    assert adapter._orders[bracket_on_the_wire.app_id].status == "rejected"


def test_a_warning_lifecycle_code_does_not_halt(adapter, order_on_the_wire, published):
    """404 - shares not immediately available for short sale - is ib_async's
    own `warningCodes`: the order is HELD, not dead, while IBKR looks for
    the shares. Halting a session on it was measured against the committed
    handler before this fix (Task 5 review)."""
    adapter._on_ib_error(
        order_on_the_wire.req_id,
        404,
        "Shares for this order are not immediately available for short sale",
        None,
    )

    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_a_lifecycle_code_against_an_already_filled_order_is_ignored(
    adapter, order_on_the_wire, published
):
    """⚠️ CRITICAL fix (a). `_orders`/`_ib_orders`/`_ib_groups` are never
    pruned, so a filled order's orderId stays matchable FOREVER - and a
    stale or duplicate 202 arriving after the fact must not resurrect it as
    order-scoped, silently overwrite `filled` with `rejected`, or halt."""
    adapter._orders[order_on_the_wire.app_id].status = "filled"

    adapter._on_ib_error(order_on_the_wire.req_id, 202, "Order Canceled - Reason:", None)

    assert adapter._orders[order_on_the_wire.app_id].status == "filled"
    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)


def test_an_unknown_code_against_an_already_filled_order_is_still_ignored(
    adapter, order_on_the_wire, published
):
    """Fail-closed is a property of STILL-OPEN order-scoped errors. A DONE
    order is not order-scoped at all any more, so even a code nobody
    recognises must not halt - the same way an error matching no order
    never has."""
    adapter._orders[order_on_the_wire.app_id].status = "filled"

    adapter._on_ib_error(order_on_the_wire.req_id, 9999, "something nobody listed", None)

    assert adapter._orders[order_on_the_wire.app_id].status == "filled"
    assert not any(type(e).__name__ == "KillSwitchEvent" for e in published)


@pytest.mark.asyncio
async def test_connect_subscribes_the_error_handler(adapter):
    """⚠️ IMPORTANT. The 3 September gap was exactly this wiring never
    happening: Error 383 was logged by ib_async and reached nothing because
    nothing had subscribed. Deleting the three `errorEvent` lines in
    `connect()` must fail this test."""
    await adapter.connect()

    assert adapter._on_ib_error in adapter.ib_client.errorEvent.listeners  # type: ignore[attr-defined]

    await adapter.disconnect()


@pytest.mark.asyncio
async def test_connect_logs_a_warning_when_the_client_has_no_error_event(adapter, caplog):
    """⚠️ IMPORTANT. `getattr(..., "errorEvent", None)` failing silently would
    be the SAME silent-non-delivery shape as the defect this task fixes -
    just one layer earlier."""
    del adapter.ib_client.errorEvent  # type: ignore[attr-defined]

    with caplog.at_level(logging.WARNING):
        await adapter.connect()

    assert "errorEvent" in caplog.text

    await adapter.disconnect()
