"""reqExecutions time, never streamed callback time, owns fill attribution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_ib_recent_fills import FillsIB, _adapter, _fill

from qat.data.broker.ib_translate import from_ib_fill


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "streamed"),
    [
        (
            datetime(2026, 10, 12, 23, 25, 18, tzinfo=UTC),
            datetime(2026, 10, 12, 12, 25, 18, tzinfo=UTC),
        ),
        (
            datetime(2026, 10, 13, 23, 31, 47, tzinfo=UTC),
            datetime(2026, 10, 13, 12, 31, 47, tzinfo=UTC),
        ),
    ],
)
async def test_monday_and_wednesday_pairs_attribute_requested_utc_and_log_discrepancy(
    caplog, requested: datetime, streamed: datetime
) -> None:
    class Client(FillsIB):
        TimezoneTWS = ""

        def fills(self):  # type: ignore[override]
            return [_fill(when=streamed)]

    client = Client([_fill(when=requested)])
    fills = await _adapter(client).recent_fills(requested - timedelta(minutes=1))

    assert len(fills) == 1
    assert fills[0].filled_at == requested
    assert fills[0].filled_at.tzinfo is UTC
    assert "39600" in caplog.text
    assert "TimezoneTWS" in caplog.text


@pytest.mark.parametrize(
    "local",
    [
        datetime(2026, 10, 4, 1, 59, tzinfo=ZoneInfo("Australia/Sydney")),
        datetime(2026, 10, 4, 3, 1, tzinfo=ZoneInfo("Australia/Sydney")),
        datetime(2026, 10, 13, 0, 1, tzinfo=ZoneInfo("Australia/Sydney")),
    ],
)
def test_cross_midnight_and_dst_are_normalized_from_non_utc_zone(local: datetime) -> None:
    raw = _fill(when=local)
    translated = from_ib_fill(raw, "ASX")

    assert translated is not None
    assert translated.filled_at == local.astimezone(UTC)
    assert translated.filled_at.tzinfo is UTC


def test_naive_execution_time_is_not_attributed_by_guessing_host_zone() -> None:
    raw = _fill(when=datetime(2026, 10, 13, 23, 31, 47))
    assert from_ib_fill(raw, "ASX") is None
