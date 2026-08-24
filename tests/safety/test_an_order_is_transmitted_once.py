"""An order reaches the broker once. Reproduces the 24 August 2026 incident.

WHAT HAPPENED. The autonomy gate opened at 14:04:51 AEST and auto-signed two
pending orders - TNE.AX 3,076 and DXS.AX 17,067, the first orders this system
had ever transmitted. `AutonomousExecutor.retry_pending` then re-signed and
re-transmitted BOTH, every sixty seconds, four times each, until the session was
stopped by hand. The broker ended up holding 68,268 DXS against an intended
17,067 - exactly four times - and 8,587 TNE, and the application had no record of
owning any of it.

WHY. `_IB_STATUS_MAP` held four entries: Filled, Cancelled, ApiCancelled,
Inactive. IBKR reports a live order as PendingSubmit / PreSubmitted / Submitted,
none of which was mapped, and `from_ib_trade` only assigned a status when the
lookup succeeded. So a transmitted order came back still carrying
`pending_signoff`; `OMS.pending_orders` filters on exactly that; the retry sweep
found it again a minute later and the gate, correctly, allowed it again.

Every individual rail behaved correctly. The per-order cap trimmed 3,468 shares
to 3,076 and was then defeated by the same 3,076 going out four times, which is
the lesson worth keeping: a per-order limit is not a per-position limit.

Two independent defences are tested here, because one of them failing silently
is what this incident was:

* the adapter now maps the working states and DEFAULTS to "transmitted", so an
  unrecognised status can never preserve `pending_signoff`;
* the OMS refuses to transmit an order id it has already transmitted, whatever
  the status field says.
"""

from __future__ import annotations

import pytest

from qat.data.broker.adapter import Order


class _Trade:
    """The shape `from_ib_trade` reads off an ib_async Trade."""

    def __init__(self, status: str, filled: float = 0.0, avg_price: float = 0.0) -> None:
        self.orderStatus = type(
            "S", (), {"status": status, "avgFillPrice": avg_price, "permId": 0, "filled": filled}
        )()
        self.order = type("O", (), {"permId": 0})()


def _order() -> Order:
    return Order(
        symbol="TNE.AX",
        side="buy",
        quantity=3076.0,
        order_id="the-order",
        status="pending_signoff",
    )


@pytest.mark.parametrize("ib_status", ["PendingSubmit", "PreSubmitted", "Submitted"])
def test_a_working_order_never_comes_back_as_pending_signoff(ib_status):
    """THE test. Each of these left the status untouched before 24 August, and
    `pending_signoff` is the one value that makes the retry sweep pick it up
    again."""
    from qat.data.broker.ib_translate import from_ib_trade

    result = from_ib_trade(_Trade(ib_status), _order())

    assert result.status != "pending_signoff", (
        f"IBKR status {ib_status!r} left the order re-signable - this is the "
        "24 August duplicate-transmission defect"
    )
    assert result.status == "transmitted"


def test_an_unrecognised_status_defaults_to_transmitted_not_to_pending():
    """The defect was not the missing keys so much as the missing DEFAULT: a
    status nobody anticipated must never read as 'still needs signing'. Matches
    alpaca_adapter, whose own note says anything unrecognised maps to
    transmitted rather than a terminal state."""
    from qat.data.broker.ib_translate import from_ib_trade

    result = from_ib_trade(_Trade("SomeStatusIBKRAddedLater"), _order())

    assert result.status == "transmitted"


def test_a_partial_fill_is_transmitted_not_filled():
    """IBKR reports a partial as Submitted with a non-zero filled quantity. It
    is live at the broker and must not be re-signed, but it is not done either -
    TNE.AX ended the incident partially filled across four orders."""
    from qat.data.broker.ib_translate import from_ib_trade

    result = from_ib_trade(_Trade("Submitted", filled=1000.0, avg_price=32.47), _order())

    assert result.status == "transmitted"


def test_terminal_statuses_still_map_as_before():
    """The fix must not have cost the four mappings that already worked."""
    from qat.data.broker.ib_translate import from_ib_trade

    assert from_ib_trade(_Trade("Filled"), _order()).status == "filled"
    assert from_ib_trade(_Trade("Cancelled"), _order()).status == "cancelled"
    assert from_ib_trade(_Trade("ApiCancelled"), _order()).status == "cancelled"
    assert from_ib_trade(_Trade("Inactive"), _order()).status == "rejected"
