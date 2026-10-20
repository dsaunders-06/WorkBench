"""Offline safety gates for the proposed close-only paper unwind."""

from __future__ import annotations

import ast
import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_close_unwind.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("phase3_close_unwind", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_imports_no_non_ibkr_source() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    forbidden = ("yahoo", "yfinance", "fred", "fundamentals", "news", "history")
    imported = [
        alias.name.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [(node.module or "").lower() for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all(not any(word in name for word in forbidden) for name in imported)


def test_strict_settings_refuse_live_or_autonomy(tmp_path: Path) -> None:
    from qat.config import Settings

    module = _load()
    valid = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id="DUQ200898",
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    module.require_settings(valid)
    for change in (
        {"market": "US"},
        {"trading_mode": "live"},
        {"execution_mode": "auto"},
        {"broker": "mock"},
        {"delever_sweep_enabled": True},
        {"ibkr_account_id": "DUOTHER"},
        {"ibkr_client_id": 99},
        {"ibkr_port": 4001},
        {"ibkr_host": "192.0.2.1"},
    ):
        with pytest.raises(ValueError):
            module.require_settings(valid.model_copy(update=change))


def test_date_window_defaults_to_refusal() -> None:
    module = _load()
    now = datetime(2026, 10, 19, 10, 45, tzinfo=ZoneInfo("Australia/Sydney"))
    with pytest.raises(ValueError):
        module.require_window(None, None, None, now)
    module.require_window("2026-10-19", "10:30", "15:00", now)
    with pytest.raises(ValueError):
        module.require_window("2026-10-20", "10:30", "15:00", now)
    with pytest.raises(ValueError):
        module.require_window("2026-10-19", "10:30", "15:00", now.replace(hour=15))


@pytest.mark.asyncio
async def test_armed_close_can_finish_after_1500() -> None:
    from qat.data.broker.adapter import Order

    module = _load()
    now = datetime(2026, 10, 19, 14, 29, tzinfo=ZoneInfo("Australia/Sydney"))

    class Broker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def cancel_order(self, order_id: str) -> None:
            self.calls.append(f"cancel:{order_id}")

        async def place_order(self, order: Order) -> Order:
            self.calls.append(f"place:{order.order_type}:{order.quantity}")
            return order

    broker = Broker()
    guard = module.ApprovedBroker(
        broker,
        window_check=lambda: module.require_arm_window("2026-10-19", "10:30", "15:00", now),
    )
    guard.arm("BOQ.AX")
    now = now.replace(hour=15, minute=1)
    await guard.cancel_order("1216552512")
    await guard.cancel_order("1216552513")
    await guard.place_order(
        Order(symbol="BOQ.AX", side="sell", quantity=13586, order_id="close-boq")
    )
    assert broker.calls == [
        "cancel:1216552512",
        "cancel:1216552513",
        "place:market:13586",
    ]


@pytest.mark.asyncio
async def test_arm_at_1431_refuses_without_touching_brackets() -> None:
    module = _load()

    class Broker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def cancel_order(self, order_id: str) -> None:
            self.calls.append(f"cancel:{order_id}")

    broker = Broker()
    now = datetime(2026, 10, 19, 14, 31, tzinfo=ZoneInfo("Australia/Sydney"))
    guard = module.ApprovedBroker(
        broker,
        window_check=lambda: module.require_arm_window("2026-10-19", "10:30", "15:00", now),
    )
    with pytest.raises(ValueError, match="14:30"):
        guard.arm("BOQ.AX")
    assert guard.symbol is None
    assert broker.calls == []


@pytest.mark.asyncio
async def test_armed_recovery_stop_can_be_sent_after_1500() -> None:
    from types import SimpleNamespace as NS

    from qat.data.broker.adapter import Order

    module = _load()
    now = datetime(2026, 10, 19, 14, 29, tzinfo=ZoneInfo("Australia/Sydney"))

    class Broker:
        def __init__(self) -> None:
            self.sent: list[Order] = []

        async def positions(self) -> list[object]:
            return [NS(symbol="BOQ.AX", quantity=6793)]

        async def open_orders(self) -> list[object]:
            return []

        async def place_order(self, order: Order) -> Order:
            self.sent.append(order)
            return order

        async def cancel_order(self, order_id: str) -> None:
            pass

    broker = Broker()
    guard = module.ApprovedBroker(
        broker,
        window_check=lambda: module.require_arm_window("2026-10-19", "10:30", "15:00", now),
    )
    guard.arm("BOQ.AX")
    await guard.cancel_order("1216552512")
    await guard.cancel_order("1216552513")
    now = now.replace(hour=15, minute=1)
    await guard.place_order(
        Order(
            symbol="BOQ.AX",
            side="sell",
            quantity=6793,
            order_type="stop",
            stop_price=6.07,
            order_id="recovery-boq",
        )
    )
    assert [(order.quantity, order.stop_price) for order in broker.sent] == [(6793, 6.07)]


def test_live_close_loop_has_no_clock_gate_after_arming() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    runner = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_live"
    )
    loops = [node for node in ast.walk(runner) if isinstance(node, (ast.For, ast.While))]
    for loop in loops:
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"require_window", "require_arm_window"}
            for node in ast.walk(loop)
        )


def test_only_arm_checks_current_time_window() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    callers = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "require_window"
            for child in ast.walk(node)
        )
    ]
    assert callers == ["require_arm_window"]


def test_order_list_rejects_extra_or_changed_action() -> None:
    module = _load()
    actions = module.revised_draft_actions()
    module.require_action_list(actions)
    assert actions[0] == {
        "symbol": "BOQ.AX",
        "con_id": 11470910,
        "action": "CANCEL",
        "role": "stop",
        "order_id": 727,
        "perm_id": 255153930,
    }
    assert len(actions) == 19
    with pytest.raises(ValueError):
        module.require_action_list(module.monday_draft_actions())
    with pytest.raises(ValueError):
        module.require_action_list([*actions, {"symbol": "BHP", "action": "BUY"}])
    altered = [dict(item) for item in actions]
    altered[0]["order_id"] = 999
    with pytest.raises(ValueError):
        module.require_action_list(altered)


def test_revised_inventory_requires_only_recovery_stop_for_boq() -> None:
    module = _load()
    expected = module.expected_inventory(revised=True)
    boq = [order for order in expected["orders"] if order["symbol"] == "BOQ"]
    assert len(boq) == 1
    assert boq[0]["order_id"] == 727
    assert boq[0]["perm_id"] == 255153930
    assert boq[0]["oca_group"] == ""
    module.require_inventory(
        expected, tuple(row[0] for row in module._REVISED_HOLDINGS), revised=True
    )


def test_boq_pending_leg_must_resolve_to_observed_permanent_identity(tmp_path: Path) -> None:
    from qat.data.broker.pending_legs import PendingLegStore

    module = _load()
    store = PendingLegStore(tmp_path / "ib_pending_legs.json")
    ref = "24b3e1b783ef4066b6a8329e4d3700c4"
    store.begin(ref, "BOQ.AX", "primary", "DUQ200898", 11470910, ref, 1)
    store.observe(ref, broker_order_id=727)
    with pytest.raises(ValueError, match="did not resolve"):
        module.require_boq_recovery_identity(tmp_path)
    assert store.resolve_match(ref, "DUQ200898", 11470910, 1, perm_id=255153930)
    module.require_boq_recovery_identity(tmp_path)


def _verify_only_case(tmp_path: Path):  # type: ignore[no-untyped-def]
    from qat.config import Settings
    from qat.data.broker.ib_adapter import IBAdapter
    from qat.data.broker.pending_legs import PendingLegStore
    from qat.domain.bus import EventBus
    from qat.domain.oms.exit_recovery import ExitRecovery, ExitRecoveryStore
    from qat.domain.risk_engine.kill_switch import KillSwitch

    module = _load()
    # A synthetic book exercises the live code path without adding account or
    # order identities from the paper account to a new public commit.
    module.ACCOUNT = "DU000000"
    module._REVISED_HOLDINGS = (("TST.AX", 123456, 100, 0, 0, 71, 7001, "10.50"),)
    module._BOQ_RECOVERY_REF = "00000000000000000000000000000001"
    module._TARGET_PRICES["TST.AX"] = "11.50"
    expected = module.expected_inventory(revised=True)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id=module.ACCOUNT,
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )

    class Gateway:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.held = [
                NS(
                    account=row["account"],
                    contract=NS(
                        symbol=row["symbol"],
                        conId=row["con_id"],
                        secType=row["sec_type"],
                        exchange=row["exchange"],
                        primaryExchange="ASX",
                        currency=row["currency"],
                    ),
                    position=float(row["quantity"]),
                    avgCost=1.0,
                )
                for row in expected["positions"]
            ]
            self.open = []
            for row in expected["orders"]:
                contract = NS(
                    symbol=row["symbol"],
                    conId=row["con_id"],
                    secType=row["sec_type"],
                    exchange=row["exchange"],
                    currency=row["currency"],
                )
                order = NS(
                    account=row["account"],
                    orderId=row["order_id"],
                    permId=row["perm_id"],
                    clientId=row["client_id"],
                    orderRef=row["order_ref"],
                    action=row["action"],
                    orderType=row["order_type"],
                    totalQuantity=float(row["quantity"]),
                    auxPrice=float(row["aux_price"]),
                    lmtPrice=float(row["limit_price"]),
                    tif=row["tif"],
                    ocaGroup=row["oca_group"],
                    parentId=row["parent_id"],
                    parentPermId=0,
                )
                status = NS(
                    status=row["status"],
                    remaining=float(row["quantity"]),
                    whyHeld="",
                )
                self.open.append(NS(contract=contract, order=order, orderStatus=status))

        def managedAccounts(self) -> list[str]:
            return [module.ACCOUNT]

        async def reqPositionsAsync(self) -> None:
            return None

        def positions(self) -> list[object]:
            return self.held

        async def reqAllOpenOrdersAsync(self) -> list[object]:
            return self.open

        def placeOrder(self, *_args: object) -> None:
            self.sent.append("place")

        def cancelOrder(self, *_args: object) -> None:
            self.sent.append("cancel")

    gateway = Gateway()
    client = module.GuardedIBClient(gateway, verify_only=True)
    recovery = module._REVISED_HOLDINGS[0]
    pending = PendingLegStore(tmp_path / "ib_pending_legs.json")
    pending.begin(
        module._BOQ_RECOVERY_REF,
        recovery[0],
        "primary",
        module.ACCOUNT,
        recovery[1],
        module._BOQ_RECOVERY_REF,
        1,
    )
    pending.observe(module._BOQ_RECOVERY_REF, broker_order_id=recovery[5])
    ExitRecoveryStore(tmp_path / "exit_recovery.json").put(
        ExitRecovery(recovery[0], float(recovery[2]), float(recovery[7]), "working", True)
    )
    KillSwitch(tmp_path).trip("paper close halted")
    adapter = IBAdapter(client, EventBus(), settings=settings, read_only=True)
    for holding, position in zip(module._REVISED_HOLDINGS, gateway.held, strict=True):
        adapter._qualified_contracts[holding[0]] = position.contract
    return module, gateway, client, adapter, settings


@pytest.mark.asyncio
async def test_verify_only_resolves_identity_and_clears_only_confirmed_plan(tmp_path: Path) -> None:
    from qat.data.broker.pending_legs import PendingLegStore
    from qat.domain.oms.exit_recovery import ExitRecoveryStore
    from qat.domain.risk_engine.kill_switch import KillSwitch

    module, gateway, client, adapter, settings = _verify_only_case(tmp_path)
    report = await module.verify_recovery_plan(adapter, client, settings)
    recovery = module._REVISED_HOLDINGS[0]
    leg = PendingLegStore(tmp_path / "ib_pending_legs.json").legs[module._BOQ_RECOVERY_REF]
    assert (leg.broker_order_id, leg.perm_id, leg.resolved) == (recovery[5], recovery[6], True)
    assert ExitRecoveryStore(tmp_path / "exit_recovery.json").plans == {}
    assert KillSwitch(tmp_path).tripped
    assert report["before_inventory"] == report["after_inventory"]
    assert gateway.sent == [] and client.violations == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "difference", ["absent", "duplicate", "pending_cancel", "quantity", "price"]
)
async def test_verify_only_keeps_plan_and_halt_if_stop_differs(
    tmp_path: Path, difference: str
) -> None:
    from qat.data.broker.pending_legs import PendingLegStore
    from qat.domain.oms.exit_recovery import ExitRecoveryStore
    from qat.domain.risk_engine.kill_switch import KillSwitch

    module, gateway, client, adapter, settings = _verify_only_case(tmp_path)
    symbol = module._REVISED_HOLDINGS[0][0]
    recovery = next(
        trade for trade in gateway.open if trade.contract.symbol == symbol.removesuffix(".AX")
    )
    if difference == "absent":
        gateway.open.remove(recovery)
    elif difference == "duplicate":
        gateway.open.append(recovery)
    elif difference == "pending_cancel":
        recovery.orderStatus.status = "PendingCancel"
    elif difference == "quantity":
        recovery.order.totalQuantity -= 1
    else:
        recovery.order.auxPrice += 0.01
    with pytest.raises(ValueError):
        await module.verify_recovery_plan(adapter, client, settings)
    assert symbol in ExitRecoveryStore(tmp_path / "exit_recovery.json").plans
    assert KillSwitch(tmp_path).tripped
    assert (
        not PendingLegStore(tmp_path / "ib_pending_legs.json")
        .legs[module._BOQ_RECOVERY_REF]
        .resolved
    )
    assert gateway.sent == [] and client.violations == []


@pytest.mark.asyncio
async def test_verify_only_denies_every_order_and_cancellation(tmp_path: Path) -> None:
    from qat.data.broker.adapter import Order

    module, gateway, client, adapter, _ = _verify_only_case(tmp_path)
    guard = module.VerifyOnlyBroker(adapter)
    with pytest.raises(ValueError, match="forbidden"):
        await guard.place_order(Order(module._REVISED_HOLDINGS[0][0], "sell", 1, "test"))
    with pytest.raises(ValueError, match="forbidden"):
        await guard.cancel_order("test")
    with pytest.raises(ValueError, match="forbidden"):
        await guard.modify_order("test", quantity=1)
    with pytest.raises(ValueError, match="forbidden"):
        client.placeOrder(None, None)
    with pytest.raises(ValueError, match="forbidden"):
        client.cancelOrder(1)
    assert guard.violations == ["place_order", "cancel_order", "modify_order"]
    assert client.violations == ["placeOrder", "cancelOrder"]
    assert gateway.sent == []


@pytest.mark.asyncio
async def test_verify_only_halts_if_stop_disappears_after_first_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qat.domain.oms.exit_recovery import ExitRecoveryStore
    from qat.domain.risk_engine.kill_switch import KillSwitch

    module, gateway, client, adapter, settings = _verify_only_case(tmp_path)
    original = gateway.reqAllOpenOrdersAsync
    reads = 0

    async def disappearing() -> list[object]:
        nonlocal reads
        reads += 1
        if reads == 4:
            symbol = module._REVISED_HOLDINGS[0][0].removesuffix(".AX")
            gateway.open = [row for row in gateway.open if row.contract.symbol != symbol]
        return await original()

    monkeypatch.setattr(gateway, "reqAllOpenOrdersAsync", disappearing)
    with pytest.raises(ValueError, match="plan remains"):
        await module.verify_recovery_plan(adapter, client, settings)
    assert (
        module._REVISED_HOLDINGS[0][0] in ExitRecoveryStore(tmp_path / "exit_recovery.json").plans
    )
    assert KillSwitch(tmp_path).tripped
    assert gateway.sent == [] and client.violations == []


@pytest.mark.asyncio
async def test_verify_only_rechecks_window_before_clearing_plan(tmp_path: Path) -> None:
    from qat.domain.oms.exit_recovery import ExitRecoveryStore
    from qat.domain.risk_engine.kill_switch import KillSwitch

    module, gateway, client, adapter, settings = _verify_only_case(tmp_path)
    checks = 0

    def window_check() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ValueError("pre-open window closed")

    with pytest.raises(ValueError, match="pre-open window closed"):
        await module.verify_recovery_plan(adapter, client, settings, window_check=window_check)
    assert (
        module._REVISED_HOLDINGS[0][0] in ExitRecoveryStore(tmp_path / "exit_recovery.json").plans
    )
    assert KillSwitch(tmp_path).tripped
    assert gateway.sent == []


@pytest.mark.parametrize(
    "hour,minute,allowed", [(9, 59, False), (10, 0, True), (12, 59, True), (13, 0, False)]
)
def test_verify_only_has_explicit_window(hour: int, minute: int, allowed: bool) -> None:
    module = _load()
    now = datetime(2026, 10, 20, hour, minute, tzinfo=ZoneInfo("Australia/Sydney"))
    if allowed:
        module.require_verify_window("2026-10-20", now)
    else:
        with pytest.raises(ValueError):
            module.require_verify_window("2026-10-20", now)
    with pytest.raises(ValueError, match="Tuesday"):
        module.require_verify_window("2026-10-21", now.replace(day=21))


@pytest.mark.asyncio
async def test_revised_guard_allows_boq_stop_then_exact_market_sell() -> None:
    from qat.data.broker.adapter import Order

    module = _load()

    class Broker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def cancel_order(self, order_id: str) -> None:
            self.calls.append(f"cancel:{order_id}")

        async def place_order(self, order: Order) -> Order:
            self.calls.append(f"place:{order.order_type}:{order.quantity}")
            return order

    broker = Broker()
    guard = module.ApprovedBroker(broker, revised=True)
    guard.arm("BOQ.AX")
    with pytest.raises(ValueError):
        await guard.cancel_order("1216552512")
    # Use a fresh guard after the intentionally denied request.
    guard = module.ApprovedBroker(broker, revised=True)
    guard.arm("BOQ.AX")
    await guard.cancel_order("255153930")
    await guard.place_order(Order("BOQ.AX", "sell", 13586, "close-boq"))
    assert broker.calls == ["cancel:255153930", "place:market:13586"]


@pytest.mark.asyncio
async def test_revised_guard_accepts_verified_oca_partner_without_second_cancel() -> None:
    from qat.data.broker.adapter import Order

    module = _load()

    class Broker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def cancel_order(self, order_id: str) -> None:
            self.calls.append(f"cancel:{order_id}")

        async def place_order(self, order: Order) -> Order:
            self.calls.append(f"place:{order.order_type}:{order.quantity}")
            return order

    broker = Broker()
    guard = module.ApprovedBroker(broker, revised=True)
    guard.arm("ANZ.AX")
    await guard.cancel_order("1216558933")
    guard.acknowledge_oca_cancelled_leg("1216558934")
    await guard.place_order(Order("ANZ.AX", "sell", 640, "close-anz"))
    assert broker.calls == ["cancel:1216558933", "place:market:640"]


def test_rehearsal_preserves_recorded_broker_cost_basis() -> None:
    module = _load()
    inventory = module.expected_inventory()
    inventory["positions"][0]["repr"] = "Position(position=13586.0, avgCost=6.3856144)"
    broker = module.RehearsalBroker(inventory)
    assert broker._positions["BOQ.AX"].avg_price == 6.3856144


def test_ib_client_guard_refuses_wrong_account_and_unapproved_requests() -> None:
    module = _load()

    class Client:
        def __init__(self, accounts: list[str]) -> None:
            self.accounts = accounts
            self.calls: list[str] = []

        def managedAccounts(self) -> list[str]:
            return self.accounts

        def reqAllOpenOrdersAsync(self) -> list:
            self.calls.append("all-open")
            return []

        def reqAutoOpenOrders(self, bind: bool) -> None:
            self.calls.append("bind")

        def reqMktData(self, *args) -> None:
            self.calls.append("data")

    wrong = Client(["U1234567"])
    with pytest.raises(ValueError):
        module.GuardedIBClient(wrong).reqAllOpenOrdersAsync()
    assert wrong.calls == []
    paper = Client(["DUQ200898"])
    guarded = module.GuardedIBClient(paper)
    assert guarded.reqAllOpenOrdersAsync() == []
    with pytest.raises(ValueError):
        guarded.reqAutoOpenOrders(True)
    with pytest.raises(ValueError):
        guarded.reqMktData("BHP")
    assert paper.calls == ["all-open"]


def test_raw_ib_rows_preserve_account_contract_and_order_identity() -> None:
    from types import SimpleNamespace as NS

    module = _load()
    contract = NS(symbol="BOQ", conId=11470910, secType="STK", exchange="ASX", currency="AUD")
    position = NS(account="DUQ200898", contract=contract, position=13586.0)
    row = module.position_row(position)
    assert row["con_id"] == 11470910 and row["account"] == "DUQ200898"
    order = NS(
        account="DUQ200898",
        orderId=152,
        permId=1216552512,
        clientId=1,
        orderRef="",
        action="SELL",
        orderType="LMT",
        totalQuantity=13586.0,
        auxPrice=0.0,
        lmtPrice=7.05,
        tif="GTC",
        ocaGroup="1216552511",
        parentId=0,
    )
    trade = NS(contract=contract, order=order, orderStatus=NS(status="Submitted"))
    assert module.order_row(trade)["perm_id"] == 1216552512


def test_execution_evidence_requires_account_contract_and_order_ref() -> None:
    from datetime import UTC
    from types import SimpleNamespace as NS

    module = _load()
    contract = NS(conId=11470910, symbol="BOQ")
    execution = NS(
        execId="0001",
        acctNumber="DUQ200898",
        clientId=1,
        orderRef="close-boq",
        side="SLD",
        shares=13586.0,
        price=6.5,
        time=datetime(2026, 10, 19, tzinfo=UTC),
    )
    fill = NS(contract=contract, execution=execution, commissionReport=NS(commission=6.0))
    evidence = module.match_executions([fill], 11470910, "close-boq", 13586)
    assert evidence[0]["exec_id"] == "0001"
    assert evidence[0]["commission"] == "6.0"
    with pytest.raises(ValueError):
        module.match_executions([fill], 11470911, "close-boq", 13586)


@pytest.mark.parametrize(
    ("section", "change"),
    [
        ("positions", {"quantity": 13585}),
        ("orders", {"status": "Filled"}),
        ("orders", {"order_id": 999}),
    ],
)
def test_changed_holding_or_leg_halts_before_close(section: str, change: dict) -> None:
    module = _load()
    snapshot = module.expected_inventory()
    snapshot[section][0].update(change)
    with pytest.raises(ValueError, match="inventory"):
        module.require_inventory(snapshot, tuple(item[0] for item in module._HOLDINGS))


def test_unknown_order_halts_before_close() -> None:
    module = _load()
    snapshot = module.expected_inventory()
    snapshot["orders"].append({"symbol": "BHP", "order_id": 1000})
    with pytest.raises(ValueError, match="inventory"):
        module.require_inventory(snapshot, tuple(item[0] for item in module._HOLDINGS))


def test_composition_builds_only_close_components(tmp_path: Path, monkeypatch) -> None:
    import builtins

    from qat.config import Settings
    from qat.data.broker.mock_broker import MockBroker

    original_import = builtins.__import__
    forbidden = (
        "qat.data.yfinance_source",
        "qat.data.yfinance_fundamentals",
        "qat.data.market_data",
        "qat.data.history",
        "qat.data.news",
        "qat.data.macro_fred",
        "qat.data.fundamentals",
        "qat.data.alpaca_source",
        "qat.presentation.runtime",
        "qat.domain.ai_advisory",
    )

    def guarded_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
            raise AssertionError(f"a forbidden source was imported: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module = _load()
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id="DUQ200898",
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    components = module.build_close_components(MockBroker(), settings)
    assert set(components) == {
        "bus",
        "kill_switch",
        "risk_engine",
        "oms",
        "journal",
        "ledger",
        "bridge",
        "reconciliation",
        "closer",
    }


@pytest.mark.asyncio
async def test_close_components_start_without_a_data_feed(tmp_path: Path) -> None:
    from qat.config import Settings
    from qat.data.broker.mock_broker import MockBroker

    module = _load()
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id="DUQ200898",
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    components = module.build_close_components(MockBroker(), settings)
    try:
        await module.start_close_components(components)
        assert not components["kill_switch"].tripped
    finally:
        await module.stop_close_components(components)


@pytest.mark.asyncio
async def test_broker_guard_allows_only_pinned_close_sequence() -> None:
    from qat.data.broker.adapter import Order

    module = _load()

    class Broker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def cancel_order(self, order_id: str) -> Order:
            self.calls.append(f"cancel:{order_id}")
            return Order(symbol="BOQ.AX", side="sell", quantity=0, order_id=order_id)

        async def place_order(self, order: Order) -> Order:
            self.calls.append(f"place:{order.side}:{order.order_type}:{order.quantity}")
            order.status = "transmitted"
            return order

    broker = Broker()
    guarded = module.ApprovedBroker(broker)
    order = Order(symbol="BOQ.AX", side="sell", quantity=13586, order_id="close-boq")
    with pytest.raises(ValueError):
        await guarded.place_order(order)
    guarded.arm("BOQ.AX")
    with pytest.raises(ValueError):
        await guarded.cancel_order("1216552513")
    await guarded.cancel_order("1216552512")
    await guarded.cancel_order("1216552513")
    await guarded.place_order(order)
    with pytest.raises(ValueError):
        await guarded.place_order(order)
    assert broker.calls == ["cancel:1216552512", "cancel:1216552513", "place:sell:market:13586"]


@pytest.mark.asyncio
async def test_rehearsal_broker_adopts_exact_five_holding_book(tmp_path: Path) -> None:
    from qat.config import Settings

    module = _load()
    broker = module.RehearsalBroker(module.expected_inventory())
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id="DUQ200898",
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    components = module.build_close_components(module.ApprovedBroker(broker), settings)
    try:
        await module.start_close_components(components)
        assert set(components["reconciliation"].adopted) == {row[0] for row in module._HOLDINGS}
        assert broker.sent == []
    finally:
        await module.stop_close_components(components)


@pytest.mark.asyncio
async def test_rehearsal_broker_fill_changes_only_selected_holding() -> None:
    from qat.data.broker.adapter import Order

    module = _load()
    broker = module.RehearsalBroker(module.expected_inventory())
    broker._pending_sell = Order(symbol="BOQ.AX", side="sell", quantity=13586, order_id="close-boq")
    broker.fill_pending()
    remaining = tuple(row[0] for row in module._HOLDINGS if row[0] != "BOQ.AX")
    snapshot = broker.snapshot()
    assert {row["symbol"] for row in snapshot["positions"]} == {
        row.removesuffix(".AX") for row in remaining
    }
    assert len(broker.executions) == 1


@pytest.mark.asyncio
async def test_one_close_uses_real_oms_and_removes_entry(tmp_path: Path) -> None:
    import json

    from qat.config import Settings

    module = _load()
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                row[0]: {
                    "opened_at": "2026-08-25T10:30:00+10:00",
                    "price": 1.0,
                    "stop_price": float(row[7]),
                    "target_price": 2.0,
                    "strategy": "swing",
                    "reference_price": None,
                    "price_source": "fill",
                }
                for row in module._HOLDINGS
            }
        ),
        encoding="utf-8",
    )
    broker = module.RehearsalBroker(module.expected_inventory())
    guard = module.ApprovedBroker(broker)
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        market="ASX",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        ibkr_account_id="DUQ200898",
        ibkr_client_id=1,
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    components = module.build_close_components(guard, settings)
    try:
        await module.start_close_components(components)
        assert not guard.violations
        assert components["bridge"].position_entries()["BOQ.AX"].quantity == 13586
        guard.arm("BOQ.AX")
        outcome = await components["closer"].close_position(
            "BOQ.AX", operator=module.signoff_label("2026-10-19", "a" * 64)
        )
        assert outcome.outcome.value == "closed"
        assert broker.cancelled == ["1216552512", "1216552513"]
        assert len(broker.sent) == 1
        broker.fill_pending()
        assert await components["oms"].check_reconciliation() is False
        assert "BOQ.AX" not in components["bridge"].position_entries()
    finally:
        await module.stop_close_components(components)


@pytest.mark.asyncio
async def test_full_rehearsal_closes_five_in_order(tmp_path: Path) -> None:
    import json

    module = _load()
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                row[0]: {
                    "opened_at": "2026-08-25T10:30:00+10:00",
                    "price": 1.0,
                    "stop_price": float(row[7]),
                    "target_price": 2.0,
                    "strategy": "swing",
                    "reference_price": None,
                    "price_source": "fill",
                }
                for row in module._HOLDINGS
            }
        ),
        encoding="utf-8",
    )
    report = await module.rehearse_in_place(tmp_path, module.expected_inventory())
    assert report["status"] == "completed"
    assert [row["symbol"] for row in report["closes"]] == [row[0] for row in module._HOLDINGS]
    assert all(row["execution_id"].startswith("SIM-") for row in report["closes"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["cancel_refused", "leg_filled", "quantity_mismatch", "partial_fill", "unknown_order"]
)
async def test_rehearsal_fault_halts_and_leaves_later_holdings(tmp_path: Path, fault: str) -> None:
    import json

    module = _load()
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                row[0]: {
                    "opened_at": "2026-08-25T10:30:00+10:00",
                    "price": 1.0,
                    "stop_price": float(row[7]),
                    "target_price": 2.0,
                    "strategy": "swing",
                    "reference_price": None,
                    "price_source": "fill",
                }
                for row in module._HOLDINGS
            }
        ),
        encoding="utf-8",
    )
    report = await module.rehearse_in_place(tmp_path, module.expected_inventory(), fault=fault)
    assert report["status"] == "halted"
    assert len(report["closes"]) == 0
    assert all(row[0] in report["remaining_positions"] for row in module._HOLDINGS[1:])
    assert all(
        str(perm_id) in report["remaining_working_orders"]
        for row in module._HOLDINGS[1:]
        for perm_id in (row[4], row[6])
    )
    if fault == "partial_fill":
        recovery = [
            row
            for row in report["remaining_order_details"]
            if row["symbol"] == "BOQ.AX" and row["stop_price"] == 6.07
        ]
        assert len(recovery) == 1 and recovery[0]["quantity"] == 6793
