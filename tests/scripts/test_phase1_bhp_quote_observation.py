"""The BHP observation uses the adapter's delayed tier and one guarded stream."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.data.broker.ib_adapter import IBAdapter, LivePortInPaperModeError
from qat.domain.bus import EventBus

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase1_bhp_quote_observation.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase1_bhp_quote_observation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, account: str = "DUQ200898") -> None:
        self.account = account
        self.calls: list[object] = []
        self.source_time = datetime.now(UTC) - timedelta(minutes=20)

    async def connectAsync(self, host, port, client_id, *, readonly):
        self.calls.append(("connect", host, port, client_id, readonly))

    def managedAccounts(self):
        self.calls.append("account_check")
        return [self.account]

    def reqMarketDataType(self, tier):
        self.calls.append(("tier", tier))

    async def qualifyContractsAsync(self, contract):
        self.calls.append(("qualify", contract.symbol))
        contract.conId = 4036812
        return [contract]

    def reqMktData(self, contract, generic, snapshot, regulatory):
        self.calls.append(("stream", contract.conId, generic, snapshot, regulatory))
        return SimpleNamespace(
            last=61.06,
            delayedLastTimestamp=self.source_time,
            marketDataType=3,
        )

    def cancelMktData(self, contract):
        self.calls.append(("cancel", contract.conId))

    def disconnect(self):
        self.calls.append("disconnect")


@pytest.mark.asyncio
async def test_one_quote_uses_adapter_connect_checks_du_and_cancels_stream(tmp_path):
    module = _module()
    client = FakeClient()
    guarded = module.GuardedReadOnlyClient(client, expected_account="DUQ200898")
    settings = Settings(
        _env_file=None,
        market="ASX",
        trading_mode="paper",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_account_id="DUQ200898",
        data_dir=str(tmp_path),
    )
    adapter = IBAdapter(
        guarded, EventBus(), settings=settings, read_only=True, heartbeat_interval_seconds=600
    )
    try:
        result = await module._observe(adapter, client)
    finally:
        await adapter.disconnect()
    assert result["value"] == "61.06"
    assert result["field"] == "last"
    assert result["market_data_type"] == 3
    assert result["raw_ticker"]["last_repr"] == "61.06"
    assert "datetime.datetime" in result["raw_ticker"]["delayed_last_timestamp_repr"]
    assert result["source_timestamp"] is not None
    assert result["age_seconds"] is not None and result["age_seconds"] < 1800
    assert result["refusal_30_minutes"] is None
    assert [call for call in client.calls if isinstance(call, tuple)] == [
        ("connect", "127.0.0.1", 4002, 1, True),
        ("tier", 3),
        ("qualify", "BHP"),
        ("stream", 4036812, "", False, False),
        ("cancel", 4036812),
    ]
    for request in guarded.requests:
        assert request["method"] in {
            "reqMarketDataType",
            "qualifyContractsAsync",
            "reqMktData",
            "cancelMktData",
        }
    assert client.calls.count("account_check") >= len(guarded.requests)


@pytest.mark.asyncio
async def test_account_change_to_another_du_stops_before_the_stream(tmp_path):
    module = _module()
    client = FakeClient("DUOTHER")
    guarded = module.GuardedReadOnlyClient(client, expected_account="DUQ200898")
    settings = Settings(
        _env_file=None,
        market="ASX",
        trading_mode="paper",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    adapter = IBAdapter(guarded, EventBus(), settings=settings, read_only=True)
    with pytest.raises(ValueError, match="managed DU account changed"):
        await module._observe(adapter, client)
    await adapter.disconnect()
    assert not any(call for call in client.calls if isinstance(call, tuple) and call[0] == "stream")


@pytest.mark.asyncio
async def test_a_non_du_account_stops_before_the_tier_or_stream(tmp_path):
    module = _module()
    client = FakeClient("U123")
    guarded = module.GuardedReadOnlyClient(client)
    settings = Settings(
        _env_file=None,
        market="ASX",
        trading_mode="paper",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        data_dir=str(tmp_path),
    )
    adapter = IBAdapter(guarded, EventBus(), settings=settings, read_only=True)
    with pytest.raises(LivePortInPaperModeError, match="non-paper"):
        await module._observe(adapter, client)
    await adapter.disconnect()
    assert not any(call for call in client.calls if isinstance(call, tuple) and call[0] == "stream")


def test_observation_is_date_and_time_gated():
    module = _module()
    local = ZoneInfo("Australia/Sydney")
    session = date(2026, 10, 15)
    module._check_window(session, datetime(2026, 10, 15, 11, 0, tzinfo=local))
    with pytest.raises(ValueError, match="11:00 to 15:00"):
        module._check_window(session, datetime(2026, 10, 15, 10, 59, tzinfo=local))
    with pytest.raises(ValueError, match="11:00 to 15:00"):
        module._check_window(session, datetime(2026, 10, 16, 11, 0, tzinfo=local))
