"""Paper and evidence boundaries for the standalone Phase 3 Gateway probes."""

from __future__ import annotations

import hashlib
import sys
from datetime import date
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
    _safe_output_dir,
    _write_raw,
)
from phase3_daily_history_probe import (
    _run as run_history,
)
from phase3_paper_stop_lifecycle_probe import (  # noqa: E402
    _cleanup,
    _GuardedGateway,
    _parcel,
    _stop_prices,
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
    first, raised = _stop_prices(Decimal("61.06"))
    assert first == Decimal("54.95")
    assert raised == Decimal("54.96")


@pytest.mark.asyncio
async def test_paper_order_probe_requires_execute_even_before_connection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--execute"):
        await run_paper_stop(date(2026, 10, 12), tmp_path, False)


def test_history_window_handles_month_ends() -> None:
    assert _months_earlier(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert _months_earlier(date(2025, 3, 31), 1) == date(2025, 2, 28)


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

        async def reqPositionsAsync(self) -> list[object]:  # noqa: N802
            return [
                SimpleNamespace(
                    account="DU123456", contract=SimpleNamespace(symbol="BHP"), position=9.0
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
                    account="DU123", contract=SimpleNamespace(symbol="BHP"), position=9.0
                )
            ]

        async def reqAllOpenOrdersAsync(self) -> list[object]:  # noqa: N802
            return [stop]

    class Adapter:
        async def place_order(self, order: object) -> None:
            raise AssertionError(f"cleanup tried to sell against a live stop: {order}")

    events: list[dict[str, str]] = []
    await _cleanup(Client(), Adapter(), "buy-ref", "stop-ref", "sell-ref", events)  # type: ignore[arg-type]
    assert events == [
        {"event": "protected paper position remains; manual close required", "quantity": "9.0"}
    ]
