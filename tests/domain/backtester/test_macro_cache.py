"""The frozen FRED cache, shared by every research runner.

It exists because `run_ablation.py` owned this privately and
`run_asx_replay.py` passed no macro at all - so the ASX run classified no
regime, and would have grown a second copy of the fetch the moment it did.
Two derivations of the same frozen input eventually disagree, and an operator
reading one while the other produced the numbers has no way to tell which was
right.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from qat.data.macro_fred import MacroObservation
from qat.domain.backtester.macro_cache import (
    frozen_macro,
    macro_coverage,
    read_macro_cache,
    write_macro_cache,
)


class _RecordingSource:
    """A macro source that counts how often it was asked."""

    def __init__(self, observations: dict[str, list[MacroObservation]]) -> None:
        self._observations = observations
        self.calls: list[str] = []

    async def fetch_series(self, series_id: str) -> list[MacroObservation]:
        self.calls.append(series_id)
        return self._observations.get(series_id, [])


def _observations() -> dict[str, list[MacroObservation]]:
    return {
        "VIXCLS": [
            MacroObservation("VIXCLS", datetime(2024, 1, 2, tzinfo=UTC), 13.2),
            MacroObservation("VIXCLS", datetime(2024, 1, 3, tzinfo=UTC), 14.0),
        ],
        "DGS10": [MacroObservation("DGS10", datetime(2024, 1, 2, tzinfo=UTC), 3.95)],
    }


def test_round_trip_preserves_series_timestamp_and_value(tmp_path: Path) -> None:
    path = tmp_path / "macro.json"
    write_macro_cache(path, _observations())

    restored = read_macro_cache(path)

    assert restored is not None
    assert sorted(restored) == ["DGS10", "VIXCLS"]
    assert restored["VIXCLS"][1].series == "VIXCLS"
    assert restored["VIXCLS"][1].ts == datetime(2024, 1, 3, tzinfo=UTC)
    assert restored["VIXCLS"][1].value == 14.0


def test_missing_cache_reads_as_none_rather_than_empty(tmp_path: Path) -> None:
    """Empty and absent are different facts, and only one of them means 'fetch'."""
    assert read_macro_cache(tmp_path / "absent.json") is None


@pytest.mark.asyncio
async def test_a_present_cache_is_never_refetched(tmp_path: Path) -> None:
    """The whole point of freezing: an ablation is a comparison of two runs, and
    inputs that move between them make the comparison meaningless."""
    path = tmp_path / "macro.json"
    write_macro_cache(path, _observations())
    source = _RecordingSource({})

    macro = await frozen_macro(path, source=lambda: source, series=["VIXCLS", "DGS10"])

    assert source.calls == []
    assert len(macro["VIXCLS"]) == 2


@pytest.mark.asyncio
async def test_a_missing_cache_fetches_once_and_freezes_it(tmp_path: Path) -> None:
    path = tmp_path / "macro.json"
    source = _RecordingSource(_observations())

    macro = await frozen_macro(path, source=lambda: source, series=["VIXCLS", "DGS10"])

    assert source.calls == ["VIXCLS", "DGS10"]
    assert macro["VIXCLS"][0].value == 13.2
    assert path.exists()
    # And the second call reads what the first wrote, asking nothing.
    again = await frozen_macro(path, source=lambda: source, series=["VIXCLS", "DGS10"])
    assert source.calls == ["VIXCLS", "DGS10"]
    assert again["DGS10"][0].value == 3.95


def test_coverage_counts_observations_on_or_before_the_date() -> None:
    """The warm start pairs each bar with `macro.as_of(series, ts)`. A series
    with nothing at or before the first replayed session contributes a constant
    column, which is the singular covariance this exists to catch."""
    coverage = macro_coverage(_observations(), datetime(2024, 1, 2, 12, tzinfo=UTC))

    assert coverage == {"VIXCLS": 1, "DGS10": 1}


def test_coverage_reports_zero_for_a_series_that_starts_later() -> None:
    coverage = macro_coverage(_observations(), datetime(2023, 6, 1, tzinfo=UTC))

    assert coverage == {"VIXCLS": 0, "DGS10": 0}
