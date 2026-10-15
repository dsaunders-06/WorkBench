"""The after-hours inventory is read-only and preserves broker identities."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_broker_inventory.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase3_broker_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeIB:
    def __init__(self, account: str = "DUQ200898") -> None:
        self.account = account
        self.calls: list[object] = []
        self.wrapper = SimpleNamespace(clientId=None)
        self.client = SimpleNamespace(connectAsync=self._connect_socket)
        self.contract = SimpleNamespace(
            symbol="BOQ", conId=11470910, secType="STK", exchange="ASX", currency="AUD"
        )

    async def _connect_socket(self, host, port, client_id, timeout):
        self.calls.append(("socket_connect", host, port, client_id, timeout))

    async def connectAsync(self, *args, **kwargs):
        raise AssertionError("IB.connectAsync would make unguarded startup requests")

    def managedAccounts(self):
        self.calls.append("du_check")
        return [self.account]

    async def reqPositionsAsync(self):
        self.calls.append("positions")
        return [SimpleNamespace(account=self.account, contract=self.contract, position=13586)]

    def positions(self):
        return [SimpleNamespace(account=self.account, contract=self.contract, position=13586)]

    async def accountSummaryAsync(self, account):
        self.calls.append(("summary", account))
        return [
            SimpleNamespace(
                account=account, tag="NetLiquidation", value="991122.01", currency="AUD"
            )
        ]

    async def reqAllOpenOrdersAsync(self):
        self.calls.append("all_open")
        return [self._trade("Submitted")]

    async def reqCompletedOrdersAsync(self, api_only):
        self.calls.append(("completed", api_only))
        return [self._trade("Filled")]

    async def reqExecutionsAsync(self, execution_filter):
        self.calls.append(("executions", execution_filter.acctCode))
        time = datetime(2026, 10, 15, 6, 0, tzinfo=timezone(timedelta(hours=10)))
        execution = SimpleNamespace(
            execId="EX123",
            acctNumber=self.account,
            time=time,
            side="BOT",
            orderId=42,
            permId=7001,
            orderRef="legacy-ref",
            shares=1,
            cumQty=1,
            price=6.38,
            avgPrice=6.38,
        )
        return [SimpleNamespace(contract=self.contract, execution=execution, commissionReport=None)]

    def _trade(self, status: str):
        order = SimpleNamespace(
            account=self.account,
            orderId=42,
            permId=7001,
            clientId=7,
            orderRef="legacy-ref",
            action="SELL",
            orderType="STP",
            totalQuantity=13586,
            auxPrice=5.75,
            lmtPrice=0.0,
            tif="GTC",
            ocaGroup="group-1",
            parentId=0,
        )
        log = [SimpleNamespace(time=datetime(2026, 10, 15, 6, 0, tzinfo=UTC), status=status)]
        return SimpleNamespace(
            contract=self.contract,
            order=order,
            orderStatus=SimpleNamespace(status=status),
            log=log,
        )

    def disconnect(self):
        self.calls.append("disconnect")


@pytest.mark.asyncio
async def test_inventory_uses_nonbinding_requests_with_du_check_before_each():
    module = _module()
    ib = FakeIB()
    await module._connect(ib)
    payload: dict[str, object] = {}
    await module._capture(ib, payload)

    assert ib.wrapper.clientId == 99
    assert ib.calls[0] == ("socket_connect", "127.0.0.1", 4002, 99, 15)
    requests = [row["method"] for row in payload["requests"]]
    assert requests == [
        "reqPositionsAsync",
        "accountSummaryAsync",
        "reqAllOpenOrdersAsync",
        "reqCompletedOrdersAsync",
        "reqExecutionsAsync",
    ]
    assert ib.calls.count("du_check") >= len(requests) + 1
    assert payload["positions_cache"][0]["quantity"] == "13586"
    order = payload["all_open_orders"][0]
    assert order["order_id"] == 42
    assert order["perm_id"] == 7001
    assert order["client_id"] == 7
    assert order["order_ref"] == "legacy-ref"
    assert order["con_id"] == 11470910
    assert order["action"] == "SELL"
    assert order["order_type"] == "STP"
    assert order["quantity"] == "13586"
    assert order["aux_price"] == "5.75"
    assert order["tif"] == "GTC"
    assert order["oca_group"] == "group-1"
    assert order["status"] == "Submitted"
    fill = payload["executions"][0]
    assert fill["exec_id"] == "EX123"
    assert fill["execution_time_type"] == "datetime"
    assert fill["execution_time_utc"] == "2026-10-14T20:00:00+00:00"


def test_inventory_guard_refuses_binding_and_order_methods():
    module = _module()
    ib = FakeIB()
    guarded = module.InventoryReadOnlyClient(ib, expected_account="DUQ200898")
    for name in ("reqOpenOrdersAsync", "reqAutoOpenOrders", "placeOrder", "cancelOrder"):
        with pytest.raises(RuntimeError, match="read-only"):
            getattr(guarded, name)()


@pytest.mark.asyncio
async def test_wrong_account_stops_before_inventory_requests():
    module = _module()
    ib = FakeIB("U123")
    await module._connect(ib)
    with pytest.raises(ValueError, match="exact DU"):
        await module._capture(ib, {})
    assert not any(call == "all_open" for call in ib.calls)
