"""A refusal at sign-off must leave a record (item 43, corrected).

The original finding claimed refusal reasons reach neither the log nor the
Blotter. **That was wrong**: `_new_rejected_order_for` journals every rejection
it creates, and the Blotter reads reasons from the decision journal by order
id. Seven rejections on 25 August carry full text - "kill-switch tripped",
"already at the 10-position limit (10 held or pending)".

The real defect is one path. There are TWO kill-switch refusals:

  * `submit_order` (oms.py:334) -> `_new_rejected_order` -> journalled.
  * `_sign_off_locked` (oms.py:633) -> sets status, logs INFO, RETURNS.

Its neighbours in the same method - no price available, and broker refused -
both call `_record`. Only this one does not, so an order refused at sign-off
appears on the Blotter with an empty reason column and no journal row at all.

Observed: order ab701dff, RHC.AX, 12:37:35, rejected during the kill-switch
window - absent from the decision journal entirely, while three other
kill-switch rejections that same window were recorded.
"""

from __future__ import annotations

import tempfile

import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


@pytest.mark.asyncio
async def test_a_signoff_refused_by_the_kill_switch_is_journalled():
    data_dir = tempfile.mkdtemp()
    settings = Settings(_env_file=None, data_dir=data_dir)  # type: ignore[arg-type]
    journal = DecisionJournal(data_dir)
    switch = KillSwitch()
    oms = OMS(
        MockBroker(seed=1),
        RiskEngine(EventBus(), switch, settings=settings),
        switch,
        journal=journal,
        settings=settings,
    )

    order = oms._new_order_for_test() if hasattr(oms, "_new_order_for_test") else None
    if order is None:
        from qat.domain.oms.oms import Order, new_order_id

        order = Order(
            symbol="RHC.AX",
            side="buy",
            quantity=1194.0,
            order_id=new_order_id(),
            status="pending_signoff",
            strategy="swing",
        )
        oms._orders[order.order_id] = order

    switch.trip("Manual trigger by operator (risk console)")
    refused = await oms.sign_off(order.order_id, operator="autonomous-executor")

    assert refused.status == "rejected"

    rows = [r for r in journal.entries() if r.get("order_id") == order.order_id]
    assert rows, (
        "the sign-off refusal left NO journal row, so the Blotter shows an "
        "empty reason - this is item 43"
    )
    assert any("kill-switch" in (r.get("reason") or "").lower() for r in rows), (
        "the row must carry WHY it was refused; 'rejected' with no reason is "
        "what an operator cannot act on"
    )
