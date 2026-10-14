"""Paper and evidence boundaries for the standalone Phase 3 Gateway probes."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import ib_async
import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import LivePortInPaperModeError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import phase3_paper_stop_lifecycle_probe as paper_probe  # noqa: E402
from phase3_auction_whatif_probe import _order_size  # noqa: E402
from phase3_auction_whatif_probe import _run as run_whatif
from phase3_daily_history_probe import (  # noqa: E402
    _months_earlier,
    _paper_target,
    _request,
    _safe_output_dir,
    _tick_request,
    _write_raw,
)
from phase3_daily_history_probe import (
    _run as run_history,
)
from phase3_paper_stop_lifecycle_probe import (  # noqa: E402
    _cleanup,
    _GuardedGateway,
    _parcel,
    _positions,
    _record_trade,
    _stop_prices,
    _wait_for_stop,
)
from phase3_paper_stop_lifecycle_probe import _run as run_paper_stop


def test_probe_rejects_remote_and_live_targets() -> None:
    assert _paper_target(Settings(market="ASX", trading_mode="paper"))[1] == 4002
    with pytest.raises(ValueError, match="local IBKR paper API port"):
        _paper_target(Settings(market="ASX", trading_mode="paper", ibkr_host="example.com"))
    with pytest.raises(LivePortInPaperModeError, match="LIVE IBKR session"):
        _paper_target(Settings(market="ASX", trading_mode="paper", ibkr_port=4001))
    with pytest.raises(ValueError, match="ASX and paper"):
        _paper_target(Settings(market="ASX", trading_mode="live"))


def test_gateway_rechecks_du_before_each_broker_request() -> None:
    class Client:
        account = "DU123456"
        requests = 0

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return [self.account]

        def placeOrder(self) -> None:  # noqa: N802
            self.requests += 1

    raw = Client()
    guarded = _GuardedGateway(raw)
    guarded.placeOrder()
    raw.account = "U123456"
    with pytest.raises(LivePortInPaperModeError, match="LIVE session"):
        guarded.placeOrder()
    assert raw.requests == 1


def test_raw_response_cannot_be_written_under_git(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside Git"):
        _safe_output_dir(checkout / "raw")
    out_dir = _safe_output_dir(tmp_path / "raw")
    path, digest = _write_raw(out_dir, "test", {"value": "unchanged"})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert path.with_suffix(".sha256").read_text(encoding="ascii").startswith(digest)


def test_bounded_auction_preview_size() -> None:
    assert _order_size(Decimal("61.06"), Decimal("61.06")) == 9
    with pytest.raises(ValueError, match="tick grid"):
        _order_size(Decimal("61.06"), Decimal("61.061"))
    with pytest.raises(ValueError, match="AUD 800"):
        _order_size(Decimal("61.06"), Decimal("100"))


def test_paper_stop_probe_uses_minimum_parcel_and_upward_stop_move() -> None:
    assert _parcel(Decimal("61.06")) == 9
    first, raised, second = _stop_prices(Decimal("61.06"))
    assert first == Decimal("54.95")
    assert raised == Decimal("54.96")
    assert second == Decimal("54.97")


def test_wednesday_window_starts_after_1030(monkeypatch: pytest.MonkeyPatch) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 10, 14, 10, 29, tzinfo=paper_probe.SYDNEY)

    monkeypatch.setattr(paper_probe, "datetime", Clock)
    with pytest.raises(ValueError, match="10:30"):
        paper_probe._session_window(date(2026, 10, 14))


def test_wednesday_probe_rejects_other_session(monkeypatch: pytest.MonkeyPatch) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 10, 14, 10, 40, tzinfo=paper_probe.SYDNEY)

    monkeypatch.setattr(paper_probe, "datetime", Clock)
    with pytest.raises(ValueError, match="14 October"):
        paper_probe._session_window(date(2026, 10, 13))


def test_wednesday_window_accepts_only_14_october_after_1030(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock(datetime):
        observed = datetime(2026, 10, 14, 10, 30, tzinfo=paper_probe.SYDNEY)

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls.observed

    monkeypatch.setattr(paper_probe, "datetime", Clock)
    paper_probe._session_window(date(2026, 10, 14))
    Clock.observed = datetime(2026, 10, 14, 10, 29, tzinfo=paper_probe.SYDNEY)
    with pytest.raises(ValueError, match="10:30"):
        paper_probe._session_window(date(2026, 10, 14))
    Clock.observed = datetime(2026, 10, 14, 15, 1, tzinfo=paper_probe.SYDNEY)
    with pytest.raises(ValueError, match="10:30"):
        paper_probe._session_window(date(2026, 10, 14))
    Clock.observed = datetime(2026, 10, 14, 10, 40, tzinfo=paper_probe.SYDNEY)
    with pytest.raises(ValueError, match="14 October"):
        paper_probe._session_window(date(2026, 10, 13))


@pytest.mark.asyncio
async def test_stop_ack_wait_ignores_pending_submit_even_with_new_aux_price() -> None:
    class Client:
        calls = 0

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            self.calls += 1
            status = "PendingSubmit" if self.calls == 1 else "PreSubmitted"
            return [
                SimpleNamespace(
                    contract=SimpleNamespace(symbol="BHP"),
                    order=SimpleNamespace(
                        orderRef="stop-ref",
                        orderType="STP",
                        action="SELL",
                        tif="GTC",
                        auxPrice=55.48,
                    ),
                    orderStatus=SimpleNamespace(status=status),
                )
            ]

    client = Client()
    await _wait_for_stop(client, "stop-ref", Decimal("55.48"), seconds=3)
    assert client.calls >= 2


@pytest.mark.asyncio
async def test_stop_ack_wait_times_out_on_pending_submit() -> None:
    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return [
                SimpleNamespace(
                    contract=SimpleNamespace(symbol="BHP"),
                    order=SimpleNamespace(
                        orderRef="stop-ref",
                        orderType="STP",
                        action="SELL",
                        tif="GTC",
                        auxPrice=55.48,
                    ),
                    orderStatus=SimpleNamespace(status="PendingSubmit"),
                )
            ]

    with pytest.raises(TimeoutError, match="acknowledged"):
        await _wait_for_stop(Client(), "stop-ref", Decimal("55.48"), seconds=1)


@pytest.mark.asyncio
async def test_cancel_wait_requires_cancelled_status_as_well_as_absence() -> None:
    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return []

        def trades(self) -> list[object]:
            return [
                SimpleNamespace(
                    order=SimpleNamespace(orderRef="stop-ref"),
                    orderStatus=SimpleNamespace(status="PendingCancel"),
                )
            ]

    with pytest.raises(TimeoutError, match="cancellation"):
        await _wait_for_stop(Client(), "stop-ref", None, seconds=1)


@pytest.mark.asyncio
async def test_stop_ack_requires_status_after_modification() -> None:
    changed_at = datetime(2026, 10, 14, 0, 30, tzinfo=UTC)
    trade = SimpleNamespace(
        contract=SimpleNamespace(symbol="BHP"),
        order=SimpleNamespace(
            orderRef="stop-ref", orderType="STP", action="SELL", tif="GTC", auxPrice=55.48
        ),
        orderStatus=SimpleNamespace(status="PreSubmitted"),
        log=[SimpleNamespace(time=changed_at - timedelta(seconds=1), status="PreSubmitted")],
    )

    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return [trade]

    with pytest.raises(TimeoutError, match="acknowledged"):
        await _wait_for_stop(Client(), "stop-ref", Decimal("55.48"), seconds=1, since=changed_at)
    trade.log.append(SimpleNamespace(time=changed_at + timedelta(seconds=1), status="PreSubmitted"))
    await _wait_for_stop(Client(), "stop-ref", Decimal("55.48"), seconds=1, since=changed_at)


def test_partial_buy_is_unexpected_broker_state() -> None:
    with pytest.raises(RuntimeError, match="unexpected broker holding"):
        paper_probe._require_full_holding(4, 9, "after buy")
    paper_probe._require_full_holding(9, 9, "after buy")


def test_emergency_exit_never_exceeds_probe_parcel() -> None:
    assert paper_probe._rescue_quantity(18, 9, 4) == 4
    assert paper_probe._rescue_quantity(4, 9, 9) == 4
    with pytest.raises(RuntimeError, match="fractional"):
        paper_probe._rescue_quantity(4.5, 9, 9)


@pytest.mark.asyncio
async def test_delayed_reference_requires_type_and_source_age() -> None:
    now = datetime(2026, 10, 13, 10, 40, tzinfo=UTC)

    class Client:
        def __init__(self, market_data_type: int, timestamp: datetime | None) -> None:
            self.ticker = SimpleNamespace(
                last=62.43,
                marketDataType=market_data_type,
                delayedLastTimestamp=timestamp,
            )
            self.cancelled = False
            self.account_checks = 0

        def managedAccounts(self) -> list[str]:  # noqa: N802
            self.account_checks += 1
            return ["DU123456"]

        def reqMktData(self, contract: object, *args: object) -> SimpleNamespace:  # noqa: N802
            return self.ticker

        def cancelMktData(self, contract: object) -> None:  # noqa: N802
            self.cancelled = True

    fresh = Client(3, now - timedelta(minutes=30))
    result = await paper_probe._reference_quote(fresh, object(), now=now, wait_seconds=0)
    assert result["price"] == Decimal("62.43")
    assert result["market_data_type"] == 3
    assert result["source_timestamp"] == (now - timedelta(minutes=30)).isoformat()
    assert result["age_seconds"] == 1800
    assert fresh.cancelled and fresh.account_checks >= 2

    for data_type, timestamp in (
        (1, now - timedelta(minutes=20)),
        (3, None),
        (3, now - timedelta(minutes=30, seconds=1)),
    ):
        client = Client(data_type, timestamp)
        with pytest.raises(ValueError, match="type|timestamp|age"):
            await paper_probe._reference_quote(client, object(), now=now, wait_seconds=0)
        assert client.cancelled


@pytest.mark.asyncio
async def test_position_read_deduplicates_callbacks_for_one_du_contract() -> None:
    class Client:
        def __init__(self) -> None:
            self.rows: list[SimpleNamespace] = []

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123456"]

        async def reqPositionsAsync(self) -> list[SimpleNamespace]:  # noqa: N802
            row = SimpleNamespace(
                account="DU123456",
                contract=SimpleNamespace(symbol="BHP", conId=4036812, primaryExchange="ASX"),
                position=9.0,
            )
            self.rows.extend((row, row))
            return self.rows

        def positions(self) -> list[SimpleNamespace]:
            return [self.rows[-1]]

    client = Client()
    events: list[dict[str, object]] = []
    assert await _positions(client, 4036812, events) == 9.0
    assert sum(row.position for row in client.rows) == 18.0  # former callback-list result
    assert len(events) == 1
    assert events[0]["event"] == "position rows"
    assert len(events[0]["request_rows"]) == 2  # type: ignore[arg-type]
    assert len(events[0]["cache_rows"]) == 1  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_position_read_ignores_same_symbol_on_another_contract() -> None:
    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123456"]

        async def reqPositionsAsync(self) -> list[SimpleNamespace]:  # noqa: N802
            return []

        def positions(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    account="DU123456",
                    contract=SimpleNamespace(symbol="BHP", conId=4036812, primaryExchange="ASX"),
                    position=9.0,
                ),
                SimpleNamespace(
                    account="DU123456",
                    contract=SimpleNamespace(symbol="BHP", conId=999, primaryExchange="NYSE"),
                    position=20.0,
                ),
                SimpleNamespace(
                    account="DU999999",
                    contract=SimpleNamespace(symbol="BHP", conId=4036812, primaryExchange="ASX"),
                    position=30.0,
                ),
            ]

    events: list[dict[str, object]] = []
    assert await _positions(Client(), 4036812, events) == 9.0
    assert len(events[0]["cache_rows"]) == 3  # type: ignore[arg-type]
    assert len(events[0]["matched_rows"]) == 1  # type: ignore[arg-type]


def test_paper_trade_record_includes_broker_id_status_fill_and_time() -> None:
    execution_time = datetime(2026, 10, 14, 0, 40, tzinfo=UTC)
    receipt_time = datetime(2026, 10, 14, 11, 40, tzinfo=paper_probe.SYDNEY)
    trade = SimpleNamespace(
        order=SimpleNamespace(
            orderId=42,
            permId=99,
            orderRef="probe-buy",
            orderType="MKT",
            tif="DAY",
            action="BUY",
            totalQuantity=9,
            auxPrice=0,
        ),
        orderStatus=SimpleNamespace(
            status="Filled", filled=9, avgFillPrice=61.0, whyHeld="IB simulated"
        ),
        fills=[
            SimpleNamespace(
                time=receipt_time,
                execution=SimpleNamespace(
                    time=execution_time, price=61.0, shares=9, execId="paper-1"
                ),
                commissionReport=SimpleNamespace(commission=1.25, currency="AUD"),
            )
        ],
        log=[
            SimpleNamespace(
                time="2026-10-12 10:10:00+11:00", status="Filled", message="", errorCode=0
            )
        ],
    )
    client = SimpleNamespace(trades=lambda: [trade])
    events: list[dict[str, object]] = []
    _record_trade(client, "probe-buy", "buy holding confirmed", events)
    assert events[0]["broker_order"]["broker_order_id"] == "42"  # type: ignore[index]
    assert events[0]["broker_order"]["status"] == "Filled"  # type: ignore[index]
    assert events[0]["broker_order"]["why_held"] == "IB simulated"  # type: ignore[index]
    assert events[0]["fills"][0]["shares"] == "9"  # type: ignore[index]
    assert events[0]["fills"][0]["commission"] == "1.25"  # type: ignore[index]
    assert events[0]["fills"][0]["execution_time_repr"] == repr(execution_time)  # type: ignore[index]
    assert events[0]["fills"][0]["execution_time_type"] == "datetime"  # type: ignore[index]
    assert events[0]["fills"][0]["execution_time_tzinfo"] == "UTC"  # type: ignore[index]
    assert events[0]["fills"][0]["receipt_time"] == str(receipt_time)  # type: ignore[index]


def test_connection_records_both_ib_async_timezones() -> None:
    client = SimpleNamespace(
        TimezoneTWS="Australia/Sydney",
        wrapper=SimpleNamespace(defaultTimezone=UTC),
    )
    events: list[dict[str, object]] = []
    paper_probe._record_connection_timezones(client, events)
    assert events[0]["event"] == "connection timezones"
    assert events[0]["client_TimezoneTWS_repr"] == "'Australia/Sydney'"
    assert events[0]["wrapper_defaultTimezone_repr"] == "datetime.timezone.utc"


@pytest.mark.asyncio
async def test_execution_recheck_pairs_streamed_and_requested_times_by_exec_id() -> None:
    streamed = datetime(2026, 10, 13, 12, 40, tzinfo=UTC)
    requested = datetime(2026, 10, 14, 10, 40, tzinfo=paper_probe.SYDNEY)

    def fill(exec_id: str, when: datetime, con_id: int = 4036812) -> SimpleNamespace:
        return SimpleNamespace(
            contract=SimpleNamespace(symbol="BHP", conId=con_id),
            execution=SimpleNamespace(execId=exec_id, time=when, acctNumber="DU123456"),
        )

    streamed_buy = fill("buy-exec", streamed)
    streamed_sell = fill("sell-exec", streamed)
    requested_buy = fill("buy-exec", requested)
    requested_sell = fill("sell-exec", requested)

    class Client:
        account = "DU123456"
        calls = 0
        filter: object = None

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return [self.account]

        def trades(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(order=SimpleNamespace(orderRef="buy-ref"), fills=[streamed_buy]),
                SimpleNamespace(order=SimpleNamespace(orderRef="sell-ref"), fills=[streamed_sell]),
            ]

        async def reqExecutionsAsync(
            self, execFilter: object
        ) -> list[SimpleNamespace]:  # noqa: N802
            self.calls += 1
            self.filter = execFilter
            return [requested_sell, fill("other-contract", requested, 999), requested_buy]

    raw = Client()
    events: list[dict[str, object]] = []
    await paper_probe._record_execution_recheck(
        _GuardedGateway(raw), 4036812, ("buy-ref", "stop-ref", "sell-ref"), events
    )
    assert raw.calls == 1
    assert raw.filter.acctCode == "DU123456"  # type: ignore[attr-defined]
    assert raw.filter.symbol == "BHP"  # type: ignore[attr-defined]
    assert raw.filter.secType == "STK"  # type: ignore[attr-defined]
    rows = events[0]["paired_fills"]  # type: ignore[assignment]
    assert [row["exec_id"] for row in rows] == ["buy-exec", "sell-exec"]  # type: ignore[index]
    assert rows[0]["streamed"]["repr"] == repr(streamed)  # type: ignore[index]
    assert rows[0]["requested"]["repr"] == repr(requested)  # type: ignore[index]
    assert rows[0]["streamed"]["type"] == "datetime"  # type: ignore[index]
    assert rows[0]["requested"]["tzinfo"] == "Australia/Sydney"  # type: ignore[index]
    assert rows[0]["difference_seconds"] == "39600.0"  # type: ignore[index]


@pytest.mark.asyncio
async def test_execution_recheck_records_missing_pair_without_retry() -> None:
    fill = SimpleNamespace(
        contract=SimpleNamespace(symbol="BHP", conId=4036812),
        execution=SimpleNamespace(
            execId="buy-exec", time=datetime(2026, 10, 14, tzinfo=UTC), acctNumber="DU123"
        ),
    )

    class Client:
        requests = 0

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        def trades(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(order=SimpleNamespace(orderRef="buy-ref"), fills=[fill])]

        async def reqExecutionsAsync(self, execFilter: object) -> list[object]:  # noqa: N802
            self.requests += 1
            return []

    client = Client()
    events: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="omitted"):
        await paper_probe._record_execution_recheck(
            _GuardedGateway(client), 4036812, ("buy-ref",), events
        )
    assert client.requests == 1
    assert events[0]["missing_requested_exec_ids"] == ["buy-exec"]


@pytest.mark.asyncio
async def test_execution_recheck_refuses_non_du_before_request() -> None:
    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["U123456"]

        def trades(self) -> list[object]:
            return []

        async def reqExecutionsAsync(self, execFilter: object) -> list[object]:  # noqa: N802
            raise AssertionError("live account reached reqExecutions")

    with pytest.raises(LivePortInPaperModeError):
        await paper_probe._record_execution_recheck(
            _GuardedGateway(Client()), 4036812, ("buy-ref", "sell-ref"), []
        )


@pytest.mark.asyncio
async def test_exit_perm_id_arrival_is_measured_from_submission() -> None:
    trade = SimpleNamespace(order=SimpleNamespace(orderRef="exit-ref", permId=0))
    client = SimpleNamespace(trades=lambda: [trade])
    task = asyncio.create_task(paper_probe._watch_perm_id(client, "exit-ref", seconds=2))
    await asyncio.sleep(0.1)
    trade.order.permId = 1234
    result = await task
    assert result["perm_id"] == "1234"
    assert float(result["elapsed_seconds"]) >= 0.1
    assert result["at_utc"]


@pytest.mark.asyncio
async def test_paper_order_probe_requires_execute_even_before_connection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--execute"):
        await run_paper_stop(date(2026, 10, 12), tmp_path, False)


def test_history_window_handles_month_ends() -> None:
    assert _months_earlier(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert _months_earlier(date(2025, 3, 31), 1) == date(2025, 2, 28)


@pytest.mark.asyncio
async def test_minute_request_preserves_rth_and_rechecks_du() -> None:
    class Client:
        account = "DU123456"
        qualified = False
        requested: dict[str, object] | None = None

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return [self.account]

        async def qualifyContractsAsync(self, contract: object) -> list[object]:  # noqa: N802
            self.qualified = True
            return [contract]

        async def reqHistoricalDataAsync(  # noqa: N802
            self, contract: object, **kwargs: object
        ) -> list[object]:
            self.requested = kwargs
            return [SimpleNamespace(date="2026-10-12 16:00:00", close=61.0, volume=9)]

    client = Client()
    result = await _request(client, "BHP.AX", "TRADES", None, "1 D", 1.0, False, "1 min")
    assert client.qualified
    assert client.requested is not None
    assert client.requested["barSizeSetting"] == "1 min"
    assert client.requested["useRTH"] is False
    assert result["bar_size"] == "1 min"
    client.account = "U123456"
    with pytest.raises(LivePortInPaperModeError, match="LIVE session"):
        await _request(client, "BHP.AX", "TRADES", None, "1 D", 1.0, True, "1 min")


@pytest.mark.asyncio
async def test_tick_request_rechecks_du_after_qualification() -> None:
    class Client:
        account = "DU123456"
        tick_requested = False

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return [self.account]

        async def qualifyContractsAsync(self, contract: object) -> list[object]:  # noqa: N802
            self.account = "U123456"
            return [contract]

        async def reqHistoricalTicksAsync(
            self, *args: object, **kwargs: object
        ) -> list[object]:  # noqa: N802
            self.tick_requested = True
            return []

    client = Client()
    with pytest.raises(LivePortInPaperModeError, match="LIVE session"):
        await _tick_request(client, "SUN.AX", date(2026, 10, 12), 1.0)
    assert not client.tick_requested


class _LiveAccountClient:
    def __init__(self) -> None:
        self.requested = False
        self.errorEvent = _FakeEvent()

    async def connectAsync(self, *args: object, **kwargs: object) -> None:  # noqa: N802
        pass

    def managedAccounts(self) -> list[str]:  # noqa: N802
        return ["U123456"]

    async def qualifyContractsAsync(self, *args: object) -> None:  # noqa: N802
        self.requested = True
        raise AssertionError("a live account reached a market-data or order request")

    def disconnect(self) -> None:
        pass


class _FakeEvent:
    def __iadd__(self, callback: object) -> _FakeEvent:
        return self


@pytest.mark.asyncio
async def test_live_account_stops_both_probes_before_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _LiveAccountClient()
    monkeypatch.setattr(ib_async, "IB", lambda: client)
    with pytest.raises(LivePortInPaperModeError):
        await run_history(
            "history", tmp_path, ("BHP.AX",), ("TRADES",), 1.0, "2 D", 12, None, False, True
        )
    with pytest.raises(LivePortInPaperModeError):
        await run_history(
            "close_window",
            tmp_path,
            ("BHP.AX",),
            ("TRADES",),
            1.0,
            "2 D",
            12,
            None,
            False,
            True,
            date(2026, 10, 12),
        )
    with pytest.raises(LivePortInPaperModeError):
        await run_whatif("BHP.AX", Decimal("61.06"), Decimal("61.06"), "ASX", tmp_path)
    assert not client.requested


@pytest.mark.asyncio
async def test_live_account_stops_paper_order_probe_before_data_or_orders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _LiveAccountClient()
    monkeypatch.setattr(ib_async, "IB", lambda: client)
    monkeypatch.setattr(paper_probe, "_session_window", lambda session: None)

    class Adapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def get_market_data(self, symbol: str) -> None:
            raise AssertionError(f"live account reached market data for {symbol}")

        async def place_order(self, order: object) -> None:
            raise AssertionError(f"live account reached an order: {order}")

    monkeypatch.setattr(paper_probe, "IBAdapter", Adapter)
    assert await run_paper_stop(date(2026, 10, 12), tmp_path, True) == 1
    assert not client.requested


@pytest.mark.asyncio
async def test_existing_paper_holding_is_never_cleaned_up_as_probe_exposure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Client(_LiveAccountClient):
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123456"]

        async def qualifyContractsAsync(self, contract: object) -> list[object]:  # noqa: N802
            return [
                SimpleNamespace(conId=4036812, symbol="BHP", primaryExchange="ASX", currency="AUD")
            ]

        async def reqPositionsAsync(self) -> list[object]:  # noqa: N802
            return [
                SimpleNamespace(
                    account="DU123456",
                    contract=SimpleNamespace(symbol="BHP", conId=4036812),
                    position=9.0,
                )
            ]

        def positions(self) -> list[object]:
            return [
                SimpleNamespace(
                    account="DU123456",
                    contract=SimpleNamespace(symbol="BHP", conId=4036812),
                    position=9.0,
                )
            ]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return []

    client = Client()
    monkeypatch.setattr(ib_async, "IB", lambda: client)
    monkeypatch.setattr(paper_probe, "_session_window", lambda session: None)
    placed: list[object] = []

    class Adapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def place_order(self, order: object) -> None:
            placed.append(order)

    monkeypatch.setattr(paper_probe, "IBAdapter", Adapter)
    assert await run_paper_stop(date(2026, 10, 12), tmp_path, True) == 1
    assert not placed


@pytest.mark.asyncio
async def test_cleanup_never_sells_against_a_resting_stop() -> None:
    stop = SimpleNamespace(
        contract=SimpleNamespace(symbol="BHP"),
        order=SimpleNamespace(orderRef="stop-ref"),
        orderStatus=SimpleNamespace(status="Submitted"),
    )

    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqPositionsAsync(self) -> list[object]:  # noqa: N802
            return [
                SimpleNamespace(
                    account="DU123",
                    contract=SimpleNamespace(symbol="BHP", conId=4036812),
                    position=9.0,
                )
            ]

        def positions(self) -> list[object]:
            return [
                SimpleNamespace(
                    account="DU123",
                    contract=SimpleNamespace(symbol="BHP", conId=4036812),
                    position=9.0,
                )
            ]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return [stop]

    class Adapter:
        async def place_order(self, order: object) -> None:
            raise AssertionError(f"cleanup tried to sell against a live stop: {order}")

    events: list[dict[str, object]] = []
    await _cleanup(Client(), Adapter(), 4036812, "buy-ref", "stop-ref", "sell-ref", 9, events)  # type: ignore[arg-type]
    assert events[-1:] == [
        {"event": "protected paper position remains; manual close required", "quantity": "9.0"}
    ]
    assert events[0]["event"] == "position rows"


@pytest.mark.asyncio
async def test_cleanup_cancels_ack_timed_out_stop_before_one_emergency_exit() -> None:
    stop = SimpleNamespace(
        contract=SimpleNamespace(symbol="BHP"),
        order=SimpleNamespace(orderRef="stop-ref"),
        orderStatus=SimpleNamespace(status="PendingSubmit", filled=0),
    )

    class Client:
        held = 9.0
        stop_open = True

        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqPositionsAsync(self) -> list[object]:  # noqa: N802
            return []

        def positions(self) -> list[object]:
            return (
                [
                    SimpleNamespace(
                        account="DU123",
                        contract=SimpleNamespace(conId=4036812, symbol="BHP"),
                        position=self.held,
                    )
                ]
                if self.held
                else []
            )

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return [stop] if self.stop_open else []

        def trades(self) -> list[object]:
            return [
                SimpleNamespace(
                    order=SimpleNamespace(orderRef="buy-ref"), orderStatus=SimpleNamespace(filled=9)
                ),
                stop,
            ]

    client = Client()
    placed: list[object] = []

    class Adapter:
        async def cancel_order(self, ref: str) -> None:
            assert ref == "stop-ref"
            stop.orderStatus.status = "Cancelled"
            client.stop_open = False

        async def place_order(self, order: object) -> None:
            placed.append(order)
            client.held = 0

    events: list[dict[str, object]] = []
    await _cleanup(client, Adapter(), 4036812, "buy-ref", "stop-ref", "sell-ref", 9, events)  # type: ignore[arg-type]
    assert len(placed) == 1
    assert placed[0].quantity == 9  # type: ignore[attr-defined]
    assert any(event["event"] == "adapter cancellation requested" for event in events)


@pytest.mark.asyncio
async def test_cleanup_does_not_resell_when_exit_fill_precedes_position_refresh() -> None:
    class Client:
        def managedAccounts(self) -> list[str]:  # noqa: N802
            return ["DU123"]

        async def reqPositionsAsync(self) -> list[object]:  # noqa: N802
            return []

        def positions(self) -> list[object]:
            return [
                SimpleNamespace(
                    account="DU123",
                    contract=SimpleNamespace(conId=4036812, symbol="BHP"),
                    position=9.0,
                )
            ]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return []

        def trades(self) -> list[object]:
            return [
                SimpleNamespace(
                    order=SimpleNamespace(orderRef="buy-ref"),
                    orderStatus=SimpleNamespace(filled=9),
                ),
                SimpleNamespace(
                    order=SimpleNamespace(orderRef="sell-ref"),
                    orderStatus=SimpleNamespace(filled=9, status="Filled"),
                ),
            ]

    class Adapter:
        async def place_order(self, order: object) -> None:
            raise AssertionError(f"duplicate emergency sale: {order}")

    events: list[dict[str, object]] = []
    await _cleanup(Client(), Adapter(), 4036812, "buy-ref", "stop-ref", "sell-ref", 9, events)  # type: ignore[arg-type]
    assert any(event["event"] == "sale fill precedes position reconciliation" for event in events)
