"""What "a universe" means to the research harness (W2 step 6b).

Shared by `scripts/research/run_ablation.py` and
`scripts/research/run_asx_replay.py` so a second script does not grow a second
notion of "a universe" - which bar cache, which benchmark, how many warm bars,
which market - or a second copy of the date-alignment rule `load_bars` below.
One fact, one derivation.

**The `market` field is load-bearing.** It selects `Settings.market`, which
selects `costs.MARKET_COST_PROFILES` automatically. An ASX run built without it
would price Australian trades on the US commission schedule, and the
cost-to-risk rail would then be measuring the wrong thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from qat.data.universe import MARKET_BENCHMARKS, Market

# Four levels up from here (backtester -> domain -> qat -> src) is the repo
# root - same derivation `macro_cache.DEFAULT_MACRO_CACHE` uses, so the two
# frozen-input paths this module and that one point at are found the same way.
_REPO = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class ResearchUniverse:
    """Enough for a runner's `_one()` to build an equivalent session for
    either universe."""

    name: str
    bars_cache: Path
    benchmark: str
    warm_bars: int
    market: Market


# The G1 gate's own frozen cache, so an ablation and G1 rest on identical
# inputs. A research run that fetched its own bars could differ from the gate
# for a reason that has nothing to do with the rail under test.
US_G1 = ResearchUniverse(
    name="US",
    bars_cache=_REPO / "scripts" / "analysis" / "g1" / "bars",
    benchmark="SPY",
    warm_bars=120,
    market="US",
)

# A year and a half of ASX sessions, against the US window's forty - see
# `run_asx_replay`'s module docstring for why that difference is the point.
ASX = ResearchUniverse(
    name="ASX",
    bars_cache=_REPO / "scripts" / "research" / "asx_bars",
    benchmark=MARKET_BENCHMARKS["ASX"],
    warm_bars=250,
    market="ASX",
)

# Keyed by the same strings `Settings.market` accepts, so a CLI's
# `--market {US,ASX}` maps onto this dict with no translation in between.
UNIVERSES: dict[Market, ResearchUniverse] = {"US": US_G1, "ASX": ASX}


def load_bars(universe: ResearchUniverse) -> dict[str, pd.DataFrame]:
    """`universe`'s cached bars, DATE-ALIGNED across the universe.

    `ReplaySession` warm-starts by INDEX POSITION -
    `ReplayHistorySource(bars, until_index=n)` - so position n must be the
    same date for every symbol. On the ASX cache this was not true: all 95
    symbols carried 500 bars, but only the benchmark covered the earliest one,
    so the rest were offset by a session. Position 250 was then a later date
    for those symbols than for the broker's own calendar, the warm start
    seeded past the replay boundary, and `prime_bar` refused to move
    backwards - correctly, and with the one error message that could have
    explained it.

    Trimming to the intersection costs whatever sessions are not common to
    every symbol and fabricates nothing. Reindexing onto a common spine would
    have been the other option and is refused: it fills missing days by
    carrying a price forward, which invents bars in an instrument whose whole
    value is that it does not.

    On the US G1 cache every symbol already shares one index - all 38 symbols
    carry the same 200 sessions - so the intersection is the whole thing and
    this function is a no-op there. `test_research_universe.py` checks the
    ASX-shaped case (an offset symbol actually gets trimmed) rather than
    assuming the no-op case generalises correctly to it.
    """
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(universe.bars_cache.glob("*.csv")):
        frame = pd.read_csv(path, parse_dates=["ts"])
        if frame.empty:
            continue
        frame = frame.set_index(pd.DatetimeIndex(frame["ts"])).drop(columns=["ts"])
        # `run_g1.py` writes `symbol.replace('/', '-')`, and no symbol in
        # either universe contains a slash - BRK.B is stored as `BRK.B.csv` -
        # so the stem is the symbol unchanged.
        frames[path.stem] = frame[["open", "high", "low", "close", "volume"]]
    if not frames:
        return frames

    # `frames` is non-empty (checked above), so seeding from the first index
    # rather than `None` needs no later narrowing for type-checking - and
    # skips it for bandit too, which flags `assert` as removable under `-O`.
    indices = iter(frames.values())
    common = next(indices).index
    for frame in indices:
        common = common.intersection(frame.index)
    dropped = {symbol: len(f.index.difference(common)) for symbol, f in frames.items()}
    worst = max(dropped.values()) if dropped else 0
    if worst:
        print(f"aligning to {len(common)} common sessions (dropping up to {worst} per symbol)")
    return {symbol: frame.loc[common] for symbol, frame in frames.items()}
