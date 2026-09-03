"""Error 383 arrived, was logged by ib_async, and reached nothing.

The adapter subscribes to no ib_async events by design - its docstring says
connection health is an active heartbeat instead, "simpler to reason about and
test". That decision is right and unaffected: it concerns connection health,
where polling gives the same answer. It does not extend to order rejections,
because there is no polling equivalent - Error 383 is delivered by `errorEvent`
or not at all.
"""

from __future__ import annotations

import logging


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


def test_the_handler_never_raises_into_the_callback(adapter, published):
    """ib_async calls this from its own event loop; an exception escaping here
    would surface inside the library, not in our stack.

    ⚠️ Asserts the CONSEQUENCES, not merely that nothing was raised. A test
    whose only content is "it did not throw" passes against a handler that
    silently swallows a real rejection, which is the failure mode this whole
    task exists to remove."""
    adapter._orders.clear()
    adapter._ib_orders.clear()

    adapter._on_ib_error(None, None, None, None)  # deliberately malformed

    assert not any(
        type(e).__name__ == "KillSwitchEvent" for e in published
    ), "a malformed error must not halt trading"
    assert adapter._orders == {}, "no order should have been invented"
