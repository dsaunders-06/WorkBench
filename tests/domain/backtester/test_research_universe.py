"""The shared universe descriptor and date-alignment bar loader (W2 step 6b).

`run_ablation.py` and `run_asx_replay.py` both build a `ReplaySession` from
"a universe" - which bar cache, which benchmark, how many warm bars, and which
market `Settings` should name. This is the one place that notion is defined,
and the one place the date-alignment rule `load_bars` documents lives.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from qat.data.universe import MARKET_BENCHMARKS
from qat.domain.backtester.research_universe import ASX, US_G1, ResearchUniverse, load_bars

_REPO = Path(__file__).resolve().parents[3]


# --- the descriptor -----------------------------------------------------


def test_the_asx_universe_carries_the_asx_market():
    """Load-bearing: `market="ASX"` selects the ASX cost profile. Without it
    an ASX run prices trades on the US commission schedule and the
    cost-to-risk rail measures the wrong thing."""
    assert ASX.market == "ASX"
    assert ASX.benchmark == MARKET_BENCHMARKS["ASX"]
    assert ASX.warm_bars == 250
    assert ASX.bars_cache == _REPO / "scripts" / "research" / "asx_bars"


def test_the_us_g1_universe_is_unchanged():
    """The G1 ablation is an input to work already recorded - adding the ASX
    descriptor must not move any value the existing US invocation relies on."""
    assert US_G1.market == "US"
    assert US_G1.benchmark == "SPY"
    assert US_G1.warm_bars == 120
    assert US_G1.bars_cache == _REPO / "scripts" / "analysis" / "g1" / "bars"


# --- the date-alignment loader -------------------------------------------


def _write(path: Path, index: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame(
        {
            "ts": index,
            "open": range(len(index)),
            "high": range(len(index)),
            "low": range(len(index)),
            "close": range(len(index)),
            "volume": [1_000] * len(index),
        }
    )
    frame.to_csv(path, index=False)


def test_load_bars_trims_an_offset_symbol_to_the_intersection(tmp_path: Path):
    """`ReplaySession` warm-starts by index position, so position n must be
    the same date for every symbol. A symbol offset by one session must come
    back trimmed to the sessions every symbol shares - NOT reindexed onto a
    common spine, which would fabricate a bar by carrying a price forward."""
    full = pd.date_range("2026-01-05", periods=5, freq="B", tz="UTC")
    offset = full[1:]  # BBB is missing the earliest session AAA has.

    _write(tmp_path / "AAA.csv", full)
    _write(tmp_path / "BBB.csv", offset)

    universe = ResearchUniverse(
        name="test", bars_cache=tmp_path, benchmark="AAA", warm_bars=1, market="US"
    )
    bars = load_bars(universe)

    assert set(bars) == {"AAA", "BBB"}
    # Trimmed to the 4 sessions both carry - not reindexed to 5.
    assert len(bars["AAA"]) == 4
    assert len(bars["BBB"]) == 4
    assert list(bars["AAA"].index) == list(bars["BBB"].index) == list(offset)
    # No forward-filled row was fabricated for AAA's now-dropped first session.
    assert full[0] not in bars["AAA"].index


def test_load_bars_is_a_no_op_when_every_symbol_already_shares_one_index():
    """The US G1 cache: 38 symbols, all carrying the same 200 sessions. The
    shared loader must not drop anything from it, since every existing G1
    invocation must behave exactly as it does today."""
    bars = load_bars(US_G1)

    lengths = {len(frame) for frame in bars.values()}
    assert len(lengths) == 1, "the G1 cache is expected to share one index across symbols"
