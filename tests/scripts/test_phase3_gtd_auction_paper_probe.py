"""Offline guards for the one-session ASX GTD auction probe."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from eventkit import Event
from ib_async import CommissionReport, Execution, Fill, OrderStatus, Stock, Trade

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import phase3_gtd_auction_paper_probe as probe  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")


def test_date_gate_refuses_other_day_and_late_start() -> None:
    probe._session_window(date(2026, 10, 27), datetime(2026, 10, 27, 9, 45, tzinfo=SYDNEY))
    with pytest.raises(ValueError):
        probe._session_window(date(2026, 10, 26), datetime(2026, 10, 26, 9, 45, tzinfo=SYDNEY))
    with pytest.raises(ValueError):
        probe._session_window(date(2026, 10, 27), datetime(2026, 10, 27, 10, 0, tzinfo=SYDNEY))


def test_two_limits_and_each_parcel_have_separate_800_cap() -> None:
    limits = probe._orders_from_close(Decimal("40.00"))
    assert limits == ((Decimal("40.80"), 19), (Decimal("38.00"), 21))
    assert all(limit * quantity <= 800 for limit, quantity in limits)
    assert sum(limit * quantity for limit, quantity in limits) > 800


def test_gtd_order_is_explicit_utc_expiry_without_day_fallback() -> None:
    order = probe._buy_order(19, Decimal("40.80"), "DUFAKE", "probe-A")
    assert order.orderType == "LMT"
    assert order.tif == "GTD"
    assert order.goodTillDate == "20261026-23:15:00"
    assert order.action == "BUY"
    assert order.outsideRth is False


def test_prior_close_must_be_previous_session_not_current_or_stale() -> None:
    bars = [
        SimpleNamespace(date=date(2026, 10, 23), close=39),
        SimpleNamespace(date=date(2026, 10, 26), close=40),
    ]
    assert probe._prior_close(bars) == Decimal("40")
    with pytest.raises(ValueError):
        probe._prior_close(bars[:1])
    with pytest.raises(ValueError):
        probe._prior_close([SimpleNamespace(date=date(2026, 10, 27), close=40)])


class FakeIB:
    def __init__(self) -> None:
        self.accounts = ["DUFAKE"]
        self.requests = 0

    def managedAccounts(self) -> list[str]:
        return self.accounts

    def reqPositionsAsync(self) -> list[object]:
        self.requests += 1
        return []

    def placeOrder(self, contract: object, order: object) -> object:
        self.requests += 1
        return order

    def cancelOrder(self, order: object) -> object:
        self.requests += 1
        return order


def test_account_rechecked_before_every_request_and_order() -> None:
    raw = FakeIB()
    client = probe._ExactAccountGateway(raw, "DUFAKE")
    client.reqPositionsAsync()
    client.placeOrder(None, None)
    client.cancelOrder(None)
    assert raw.requests == 3
    raw.accounts = ["DUFAKE", "DUOTHER"]
    with pytest.raises(ValueError):
        client.reqPositionsAsync()
    with pytest.raises(ValueError):
        client.placeOrder(None, None)
    with pytest.raises(ValueError):
        client.cancelOrder(None)
    assert raw.requests == 3


def test_cancel_only_live_remainder_and_never_retry() -> None:
    assert probe._cancel_required("Submitted", 1) is True
    assert probe._cancel_required("PreSubmitted", 1) is True
    assert probe._cancel_required("Filled", 0) is False
    assert probe._cancel_required("Cancelled", 1) is False
    with pytest.raises(RuntimeError):
        probe._cancel_required("PendingCancel", 1)
    with pytest.raises(RuntimeError):
        probe._cancel_required("Inactive", 1)


def test_early_cancellation_and_preopen_fill_halt() -> None:
    cancelled = SimpleNamespace(orderStatus=SimpleNamespace(status="Cancelled"))
    filled = SimpleNamespace(orderStatus=SimpleNamespace(status="Filled"))
    with pytest.raises(RuntimeError, match="before GTD expiry"):
        probe._check_pre_expiry([cancelled], datetime(2026, 10, 27, 10, 5, tzinfo=SYDNEY))
    with pytest.raises(RuntimeError, match="before the ASX opening auction"):
        probe._check_pre_expiry([filled], datetime(2026, 10, 27, 9, 55, tzinfo=SYDNEY))
    probe._check_pre_expiry([cancelled], datetime(2026, 10, 27, 10, 16, tzinfo=SYDNEY))


def test_exit_rejects_unattributed_or_extra_shares() -> None:
    assert probe._exit_quantity(19, 2, 21) == 21
    with pytest.raises(RuntimeError):
        probe._exit_quantity(19, 2, 22)
    with pytest.raises(RuntimeError):
        probe._exit_quantity(19, 2, 20)


def test_session_attempt_cannot_be_repeated(tmp_path: Path) -> None:
    probe._claim_attempt(tmp_path)
    with pytest.raises(FileExistsError):
        probe._claim_attempt(tmp_path)


def test_unrelated_working_order_blocks_exit() -> None:
    own = SimpleNamespace(order=SimpleNamespace(orderRef="gtd-20261027-A"))
    foreign = SimpleNamespace(order=SimpleNamespace(orderRef="other-client"))
    probe._owned_orders_only([own], {"gtd-20261027-A"})
    with pytest.raises(RuntimeError, match="unrelated working order"):
        probe._owned_orders_only([own, foreign], {"gtd-20261027-A"})


def test_fill_details_must_match_broker_filled_status() -> None:
    fill = SimpleNamespace(execution=SimpleNamespace(shares=2))
    trade = SimpleNamespace(orderStatus=SimpleNamespace(filled=3), fills=[fill])
    assert probe._fills_match_status(trade) is False
    trade.orderStatus.filled = 2
    assert probe._fills_match_status(trade) is True


def test_exact_private_approval_terms_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    terms = {
        "account": "DUFAKE",
        "approved_by": "DS",
        "approval_date": "2026-10-26",
        "session": "2026-10-27",
        "symbol": "BHP.AX",
        "operator": "DS",
        "cap_per_order_aud": "800",
    }
    path.write_text(json.dumps(terms), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert probe._load_approval(path, digest) == "DUFAKE"
    terms["cap_per_order_aud"] = "1600"
    path.write_text(json.dumps(terms), encoding="utf-8")
    with pytest.raises(ValueError):
        probe._load_approval(path, digest)


def _trade(label: str = "B", quantity: int = 15) -> Trade:
    order = probe._buy_order(quantity, Decimal("38.00"), "DUFAKE", f"gtd-20261027-{label}")
    order.orderId = 1 if label == "A" else 2
    order.permId = 101 if label == "A" else 102
    return Trade(
        contract=Stock("BHP", "SMART", "AUD", primaryExchange="ASX", conId=42),
        order=order,
        orderStatus=OrderStatus(status="Submitted", filled=0, remaining=quantity),
    )


def _fill(trade: Trade, at: datetime, quantity: int, exec_id: str = "test-buy") -> Fill:
    return Fill(
        trade.contract,
        Execution(
            execId=exec_id,
            time=at.astimezone(UTC),
            acctNumber="DUFAKE",
            orderId=trade.order.orderId,
            permId=trade.order.permId,
            orderRef=trade.order.orderRef,
            side="BOT" if trade.order.action == "BUY" else "SLD",
            shares=quantity,
            price=40,
        ),
        CommissionReport(execId=exec_id, commission=1, currency="AUD"),
        at.astimezone(UTC),
    )


@pytest.mark.parametrize("second", [45, 50])
def test_real_trade_fill_at_or_after_095945_is_permitted(second: int) -> None:
    trade = _trade("A", 14)
    at = datetime(2026, 10, 27, 9, 59, second, tzinfo=SYDNEY)
    trade.fills.append(_fill(trade, at, 14))
    trade.orderStatus = OrderStatus(status="Filled", filled=14, remaining=0)
    probe._check_pre_expiry([trade], at)


@pytest.mark.parametrize("status", ["Submitted", "Filled"])
def test_execution_before_095945_halts_even_if_observed_after_1000(status: str) -> None:
    trade = _trade("A", 14)
    at = datetime(2026, 10, 27, 9, 59, 40, tzinfo=SYDNEY)
    trade.fills.append(_fill(trade, at, 1))
    trade.orderStatus = OrderStatus(status=status, filled=1, remaining=13)
    with pytest.raises(RuntimeError, match="before the ASX opening"):
        probe._check_pre_expiry([trade], datetime(2026, 10, 27, 10, 1, tzinfo=SYDNEY))


@pytest.mark.asyncio
async def test_own_cancel_waits_through_pendingcancel_to_apicancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade = _trade()
    events: list[dict] = []

    class CancelGateway:
        calls = 0

        def cancelOrder(self, order: object) -> None:
            assert order is trade.order
            self.calls += 1
            trade.orderStatus.status = "PendingCancel"

    gateway = CancelGateway()

    async def settle(_: float) -> None:
        trade.orderStatus.status = "ApiCancelled"

    monkeypatch.setattr(probe, "_now", lambda: datetime(2026, 10, 27, 10, 16, tzinfo=SYDNEY))
    monkeypatch.setattr(probe.asyncio, "sleep", settle)
    await probe._cancel_live_buy(gateway, trade, events)
    assert trade.orderStatus.status == "ApiCancelled"
    assert gateway.calls == 1
    assert [row["order"]["status"] for row in events if row["event"] == "cancel state"] == [
        "PendingCancel",
        "ApiCancelled",
    ]
    await probe._cancel_live_buy(gateway, trade, events)
    assert gateway.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["PendingCancel", "Inactive"])
async def test_unrequested_cancel_or_inactive_halts(status: str) -> None:
    trade = _trade()
    trade.orderStatus.status = status
    with pytest.raises(RuntimeError):
        await probe._cancel_live_buy(object(), trade, [], set())


class ScenarioGateway:
    """Offline broker boundary; every trade, fill and status is a real ib_async object."""

    def __init__(
        self, clock: list[datetime], *, early: bool, natural_expiry: bool, late_fill: bool = False
    ) -> None:
        self.clock = clock
        self.early = early
        self.natural_expiry = natural_expiry
        self.late_fill = late_fill
        self.buy_filled = False
        self.delayed_fill: Fill | None = None
        self.connected = False
        self.orderStatusEvent = Event()
        self.execDetailsEvent = Event()
        self.buys: list[Trade] = []
        self.sales: list[Trade] = []
        self.executions: list[Fill] = []
        self.cancel_requests: list[tuple[str, datetime]] = []
        self.completed_requests: list[datetime] = []
        self.execution_requests: list[datetime] = []
        self.held = 0

    def managedAccounts(self) -> list[str]:
        return ["DUFAKE"]

    async def connectAsync(self, *args: object, **kwargs: object) -> None:
        self.connected = True

    def isConnected(self) -> bool:
        return self.connected

    def disconnect(self) -> None:
        self.connected = False

    async def qualifyContractsAsync(self, contract: Stock) -> list[Stock]:
        contract.conId = 42
        return [contract]

    async def reqHistoricalDataAsync(self, *args: object, **kwargs: object) -> list[object]:
        return [SimpleNamespace(date=date(2026, 10, 26), close=40)]

    async def reqPositionsAsync(self) -> list[object]:
        if not self.held:
            return []
        return [
            SimpleNamespace(account="DUFAKE", contract=self.buys[0].contract, position=self.held)
        ]

    async def reqAllOpenOrdersAsync(self) -> list[Trade]:
        return [trade for trade in self.buys if trade.orderStatus.status not in probe.TERMINAL]

    async def reqCompletedOrdersAsync(self, api_only: bool) -> list[Trade]:
        assert api_only is False
        self.completed_requests.append(self.clock[0])
        return [trade for trade in self.buys if trade.orderStatus.status in probe.TERMINAL]

    async def reqExecutionsAsync(self, execution_filter: object) -> list[Fill]:
        self.execution_requests.append(self.clock[0])
        return list(self.executions)

    def placeOrder(self, contract: Stock, order: object) -> Trade:
        order.orderId = len(self.buys) + len(self.sales) + 1
        order.permId = order.orderId + 100
        trade = Trade(
            contract, order, OrderStatus(status="Submitted", remaining=order.totalQuantity)
        )
        if order.action == "BUY":
            self.buys.append(trade)
        else:
            assert order.totalQuantity == self.held
            trade.fills.append(_fill(trade, self.clock[0], self.held, "test-sale"))
            trade.orderStatus = OrderStatus(status="Filled", filled=self.held, remaining=0)
            self.executions.extend(trade.fills)
            self.held = 0
            self.sales.append(trade)
        return trade

    def cancelOrder(self, order: object) -> None:
        trade = next(trade for trade in self.buys if trade.order is order)
        self.cancel_requests.append((order.orderRef, self.clock[0]))
        trade.orderStatus.status = "PendingCancel"
        self.orderStatusEvent(trade)

    async def advance(self, seconds: float) -> None:
        self.clock[0] += timedelta(seconds=seconds)
        for trade in self.buys:
            if trade.orderStatus.status == "PendingCancel":
                trade.orderStatus.status = "ApiCancelled"
                self.orderStatusEvent(trade)
        if not self.buys:
            return
        first = self.buys[0]
        at = datetime(2026, 10, 27, 9, 59, 40 if self.early else 50, tzinfo=SYDNEY)
        if self.clock[0] >= at and not self.buy_filled:
            quantity = int(first.order.totalQuantity)
            fill = _fill(first, at, quantity)
            self.buy_filled = True
            if self.late_fill:
                self.delayed_fill = fill
            else:
                first.fills.append(fill)
                self.executions.append(fill)
            first.orderStatus = OrderStatus(status="Filled", filled=quantity, remaining=0)
            self.held = quantity
            if not self.late_fill:
                self.execDetailsEvent(first, fill)
            self.orderStatusEvent(first)
        if self.delayed_fill and self.clock[0].time() >= time(10, 20):
            first.fills.append(self.delayed_fill)
            self.executions.append(self.delayed_fill)
            self.execDetailsEvent(first, self.delayed_fill)
            self.delayed_fill = None
        if self.natural_expiry and self.clock[0].time() >= time(10, 15):
            second = self.buys[1]
            if second.orderStatus.status == "Submitted":
                second.orderStatus.status = "ApiCancelled"
                self.orderStatusEvent(second)


def _approval(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "test-approval.json"
    path.write_text(
        json.dumps(
            {
                "account": "DUFAKE",
                "approved_by": "DS",
                "approval_date": "2026-10-26",
                "session": "2026-10-27",
                "symbol": "BHP.AX",
                "operator": "DS",
                "cap_per_order_aud": "800",
            }
        ),
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


async def _scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    early: bool,
    natural_expiry: bool,
    late_fill: bool = False,
) -> tuple[int, ScenarioGateway, list[dict]]:
    clock = [datetime(2026, 10, 27, 9, 45, tzinfo=SYDNEY)]
    gateway = ScenarioGateway(
        clock, early=early, natural_expiry=natural_expiry, late_fill=late_fill
    )
    monkeypatch.setattr(probe, "IB", lambda: gateway)
    monkeypatch.setattr(probe, "_now", lambda: clock[0])
    monkeypatch.setattr(probe.asyncio, "sleep", gateway.advance)
    approval, digest = _approval(tmp_path)
    output = tmp_path / "evidence"
    result = await probe._run(date(2026, 10, 27), output, approval, digest, True)
    records = list(output.glob("phase3-gtd-auction-paper-*.json"))
    assert len(records) == 1
    return result, gateway, json.loads(records[0].read_text())["events"]


@pytest.mark.asyncio
async def test_emergency_sale_proceeds_after_pendingcancel_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, gateway, events = await _scenario(
        monkeypatch, tmp_path, early=True, natural_expiry=False
    )
    assert result == 1  # the original early-fill halt remains recorded
    assert gateway.held == 0
    assert len(gateway.sales) == 1
    assert gateway.sales[0].order.orderRef == "gtd-20261027-emergency"
    assert gateway.sales[0].order.totalQuantity == gateway.buys[0].order.totalQuantity
    assert len(gateway.cancel_requests) == 1
    assert gateway.buys[1].orderStatus.status == "ApiCancelled"
    assert any(row["event"] == "emergency exit result" for row in events)
    assert not any(row["event"] == "emergency halt" for row in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("natural_expiry", [False, True])
async def test_both_expiry_observations_precede_any_cancel_and_keep_broker_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, natural_expiry: bool
) -> None:
    result, gateway, events = await _scenario(
        monkeypatch, tmp_path, early=False, natural_expiry=natural_expiry
    )
    assert result == 0
    assert gateway.completed_requests == [
        datetime(2026, 10, 27, 10, 15, 30, tzinfo=SYDNEY),
        datetime(2026, 10, 27, 10, 16, tzinfo=SYDNEY),
    ]
    observations = [row for row in events if row["event"] == "B GTD expiry observation"]
    assert len(observations) == 2
    assert all(row["script_cancel_requested"] is False for row in observations)
    assert all(row["terminal_without_script_cancel"] is natural_expiry for row in observations)
    assert all(bool(row["completed_orders"]) is natural_expiry for row in observations)
    assert len(gateway.cancel_requests) == (0 if natural_expiry else 1)
    if gateway.cancel_requests:
        assert gateway.cancel_requests[0][1] >= datetime(2026, 10, 27, 10, 16, tzinfo=SYDNEY)
    assert gateway.held == 0
    assert len(gateway.sales) == 1
    assert gateway.sales[0].fills[0].execution.time.astimezone(SYDNEY).time() >= time(10, 30)
    rechecks = [row for row in events if row["event"] == "execution times recheck"]
    times = {
        row["exec_id"]: row["execution_time_utc"] for event in rechecks for row in event["fills"]
    }
    assert times["test-buy"] == "2026-10-26T22:59:50+00:00"
    assert times["test-sale"] == "2026-10-26T23:30:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("request_kind", ["executions", "completed"])
async def test_unanswered_evidence_request_has_its_own_timeout(
    monkeypatch: pytest.MonkeyPatch, request_kind: str
) -> None:
    class UnresponsiveGateway:
        expected_account = "DUFAKE"

        async def reqExecutionsAsync(self, *args: object) -> list[Fill]:
            return await asyncio.Future()

        async def reqCompletedOrdersAsync(self, *args: object) -> list[Trade]:
            return await asyncio.Future()

    monkeypatch.setattr(probe, "EVIDENCE_TIMEOUT_SECONDS", 0.001, raising=False)
    gateway = UnresponsiveGateway()
    operation = (
        probe._record_execution_times(gateway, [])
        if request_kind == "executions"
        else probe._observe_b_expiry(gateway, _trade(), [], set())
    )
    task = asyncio.create_task(operation)
    try:
        await asyncio.sleep(0.1)
        assert task.done(), "probe's own timeout must bound the unanswered request"
        with pytest.raises(TimeoutError):
            task.result()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["PendingCancel", "Inactive"])
async def test_brief_unsolicited_state_is_latched_between_poll_iterations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> None:
    advance = ScenarioGateway.advance
    injected = False

    async def flash(self: ScenarioGateway, seconds: float) -> None:
        nonlocal injected
        await advance(self, seconds)
        if not injected and self.clock[0].time() >= time(10, 5):
            injected = True
            trade = self.buys[1]
            trade.orderStatus.status = status
            self.orderStatusEvent(trade)
            trade.orderStatus.status = "Submitted"
            self.orderStatusEvent(trade)

    monkeypatch.setattr(ScenarioGateway, "advance", flash)
    result, gateway, events = await _scenario(
        monkeypatch, tmp_path, early=False, natural_expiry=False
    )
    assert result == 1
    assert any(
        row["event"] == "callback halt latched" and status in row["reason"] for row in events
    )
    assert gateway.held == 0  # bounded emergency cleanup still runs


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["test-buy", "test-sale"])
async def test_missing_reqexecutions_confirmation_for_late_buy_or_sale_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    request = ScenarioGateway.reqExecutionsAsync

    async def incomplete(self: ScenarioGateway, execution_filter: object) -> list[Fill]:
        fills = await request(self, execution_filter)
        return [fill for fill in fills if fill.execution.execId != missing]

    monkeypatch.setattr(ScenarioGateway, "reqExecutionsAsync", incomplete)
    result, _, events = await _scenario(
        monkeypatch, tmp_path, early=False, natural_expiry=False, late_fill=missing == "test-buy"
    )
    assert result == 1
    assert any("reqExecutions did not confirm" in row.get("reason", "") for row in events)
