"""IBKR delayed observations retain source time and distinguish unusable states."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from qat.config import Settings
from qat.data.broker import ib_adapter
from qat.data.broker.ib_adapter import IBAdapter


def _adapter(ticker: SimpleNamespace) -> tuple[IBAdapter, list[str]]:
    calls: list[str] = []
    contract = SimpleNamespace(symbol="BHP", conId=1001)

    def stream(*args: object) -> SimpleNamespace:
        calls.append("stream")
        return ticker

    def cancel(*args: object) -> None:
        calls.append("cancel")

    adapter = IBAdapter.__new__(IBAdapter)
    adapter.ib_client = SimpleNamespace(reqMktData=stream, cancelMktData=cancel)
    adapter.settings = Settings(_env_file=None, market="ASX")
    adapter._qualified_contracts = {"BHP.AX": contract}
    return adapter, calls


@pytest.mark.asyncio
async def test_delayed_type_three_last_carries_source_and_observed_time() -> None:
    source = datetime.now(UTC) - timedelta(minutes=20)
    adapter, calls = _adapter(
        SimpleNamespace(last=61.86, marketDataType=3, delayedLastTimestamp=source)
    )

    observation = await adapter.price_observation("BHP.AX")

    assert observation.value == 61.86
    assert observation.field == "last"
    assert observation.market_data_type == 3
    assert observation.source_timestamp == source
    assert observation.observed_timestamp >= source
    assert observation.refusal(max_age=timedelta(minutes=30)) is None
    assert calls == ["stream", "cancel"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("last", "source_age", "problem"),
    [
        (61.86, None, "untimestamped"),
        (61.86, 31, "stale"),
        (float("nan"), 20, "nan"),
        (0.0, 20, "nonpositive"),
        (None, 20, "absent"),
    ],
)
async def test_invalid_observation_states_remain_distinct(
    monkeypatch, last: float | None, source_age: int | None, problem: str
) -> None:
    monkeypatch.setattr(ib_adapter, "_QUOTE_WAIT_SECONDS", 0.0)
    source = datetime.now(UTC) - timedelta(minutes=source_age) if source_age else None
    adapter, calls = _adapter(
        SimpleNamespace(last=last, marketDataType=3, delayedLastTimestamp=source)
    )

    observation = await adapter.price_observation("BHP.AX")

    assert problem in str(observation.refusal(max_age=timedelta(minutes=30))).lower()
    assert calls == ["stream", "cancel"]


def test_quote_age_is_one_fixed_named_setting_until_ds_changes_it() -> None:
    assert Settings(_env_file=None).current_quote_max_age_seconds == 1800
    with pytest.raises(ValueError):
        Settings(_env_file=None, current_quote_max_age_seconds=3600)
