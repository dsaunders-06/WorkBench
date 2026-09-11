"""IBKR's own commission, totalled per order (M175).

Measured 11 September: a second client's `reqExecutions` returned BHP's 10:00
stop execution with commission 0.0 and no commissionReport - so the figure only
arrives, if at all, on `commissionReportEvent` to a connected client. One report
per EXECUTION; an order is complete when its executions cover its quantity.
Real ib_async types throughout - a friendlier fake is how M174's feed check
passed its tests and never ran.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ib_async import CommissionReport, Contract, Execution, Fill
from ib_async.order import Order as IBOrder
from ib_async.order import OrderStatus, Trade

from qat.data.broker.adapter import BrokerCommission

_NOW = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
_PERM = 750830217


def _trade(total: float) -> Trade:
    return Trade(
        contract=Contract(symbol="BHP"),
        order=IBOrder(totalQuantity=total),
        orderStatus=OrderStatus(status="Filled"),
    )


def _fill(exec_id: str, shares: float, price: float, side: str = "SLD") -> Fill:
    return Fill(
        contract=Contract(symbol="BHP", secType="STK", exchange="ASX", currency="AUD"),
        execution=Execution(execId=exec_id, side=side, shares=shares, price=price, permId=_PERM),
        commissionReport=CommissionReport(),
        time=_NOW,
    )


def _report(exec_id: str, commission: float, currency: str = "AUD") -> CommissionReport:
    return CommissionReport(execId=exec_id, commission=commission, currency=currency)


def _listen(adapter) -> list[BrokerCommission]:
    seen: list[BrokerCommission] = []
    adapter.set_commission_listener(seen.append)
    return seen


@pytest.mark.asyncio
async def test_connect_subscribes_the_commission_handler(adapter):
    await adapter.connect()
    assert adapter._on_ib_commission in adapter.ib_client.commissionReportEvent.listeners
    await adapter.disconnect()


def test_a_one_execution_order_is_reported_when_its_commission_arrives(adapter):
    seen = _listen(adapter)

    adapter._on_ib_commission(_trade(793), _fill("e1", 793, 60.40), _report("e1", 42.149536))

    assert seen == [
        BrokerCommission(
            order_id=str(_PERM),
            symbol="BHP.AX",
            side="sell",
            quantity=793.0,
            notional=pytest.approx(793 * 60.40),  # type: ignore[arg-type]
            commission=pytest.approx(42.149536),  # type: ignore[arg-type]
            currency="AUD",
        )
    ]


def test_a_multi_execution_order_is_reported_once_and_only_when_complete(adapter):
    """RHC.AX's entry was 21 executions; the first was ONE share at 0.039081."""
    seen = _listen(adapter)
    trade = _trade(201)

    adapter._on_ib_commission(trade, _fill("e1", 1, 44.41, "BOT"), _report("e1", 0.039081))
    adapter._on_ib_commission(trade, _fill("e2", 100, 44.41, "BOT"), _report("e2", 3.90808))
    assert seen == []
    adapter._on_ib_commission(trade, _fill("e3", 100, 44.42, "BOT"), _report("e3", 3.908960))

    assert len(seen) == 1
    assert seen[0].side == "buy"
    assert seen[0].quantity == 201.0
    assert seen[0].commission == pytest.approx(0.039081 + 3.90808 + 3.908960)


def test_a_repeated_report_is_not_counted_twice(adapter):
    seen = _listen(adapter)
    trade = _trade(200)

    adapter._on_ib_commission(trade, _fill("e1", 100, 44.41), _report("e1", 3.90808))
    adapter._on_ib_commission(trade, _fill("e1", 100, 44.41), _report("e1", 3.90808))

    assert seen == []


def test_an_unusable_commission_suppresses_the_check(adapter):
    """IBKR sends UNSET_DOUBLE (1.797e308) for a commission it does not have."""
    seen = _listen(adapter)

    adapter._on_ib_commission(
        _trade(793), _fill("e1", 793, 60.40), _report("e1", 1.7976931348623157e308)
    )

    assert seen == []


def test_an_order_with_no_known_total_is_skipped_not_guessed(adapter):
    seen = _listen(adapter)
    no_total = Trade(
        contract=Contract(symbol="BHP"),
        order=IBOrder(totalQuantity=0),
        orderStatus=OrderStatus(),
    )

    adapter._on_ib_commission(no_total, _fill("e1", 793, 60.40), _report("e1", 42.15))
    adapter._on_ib_commission(None, _fill("e2", 793, 60.40), _report("e2", 42.15))

    assert seen == []


def test_a_listener_that_raises_never_escapes_into_ib_async(adapter, caplog):
    def boom(_: BrokerCommission) -> None:
        raise RuntimeError("listener failed")

    adapter.set_commission_listener(boom)

    # Reaching the assertion at all is half the test: nothing propagated.
    adapter._on_ib_commission(_trade(793), _fill("e1", 793, 60.40), _report("e1", 42.15))

    assert "Could not tally an IBKR commission report" in caplog.text
    assert "listener failed" in caplog.text  # the traceback was kept, not swallowed
